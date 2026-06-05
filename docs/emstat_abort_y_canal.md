# EmStat — Aborto en caliente y canal de electrodo (host)

Cambios del lado del host (esta app) para alinearse con el firmware del Pico 2
**`emstat_wifi_v1.6`**. La fuente de verdad del protocolo es
[`emstat_wifi_v1.6.md`](../../MicroPython/DiscPCB/docs/emstat_wifi_v1.6.md).

Archivos modificados:

- `ui/EventEmstatFrame.py` — aborto en caliente, manejo de cierres terminales, lock de envío.
- `ui/ElectrochemicalFrame.py` — selector de canal de electrodo.
- `ui/CvFrame.py` / `ui/SqwVFrame.py` — `"ch"` en el payload del experimento.

---

## 1. Contrato con el firmware v1.6

| Comando host → Pico | Efecto |
|---|---|
| `{"cmd":"STOP"}` | **Solo** detiene la telemetría de temperatura. **No** aborta el experimento. |
| `{"cmd":"ABORT"}` | **Cancela en caliente** el experimento del EmStat (envía `Z\n` → `on_finished:` → celda apagada, libera el canal MCP). |

> `STOP` y `ABORT` son distintos: `STOP` = telemetría; `ABORT` = experimento.

**Canal de electrodo obligatorio.** Cada payload de experimento (`cv`/`sqwv`) debe
incluir `"ch":N` con `N` ∈ `0..7` (MCP23017, puerto A, multiplex: un canal activo a
la vez). Si `ch` falta, está fuera de rango o el MCP no aparece en el bus, el firmware
**rechaza el experimento** y responde `emstat_error`. El canal se apaga (`clear_all`)
en un `finally` que cubre todas las salidas (fin, abort, maxtime, timeout, error).

**Mensajes terminales** (Pico → host, dentro de `EMSTAT:<json>`):

| `type` | Significado |
|---|---|
| `emstat_end` | Fin normal del experimento. |
| `emstat_error` | Error al generar/enviar el script, o canal inválido (`error` ∈ `{mcp_no_disponible, ch_invalido, ch_fuera_de_rango, mcp_error:...}`). |
| `emstat_aborted` | El host mandó `ABORT`; incluye `clean` (bool: celda apagada confirmada). |
| `emstat_maxtime` | Se superó el tope absoluto (`MAX_EXPERIMENT_MS`). |
| `emstat_timeout` | El EmStat dejó de responder; incluye `connected` (re-test de conexión). |

---

## 2. Aborto en caliente al detener (`EventPlotter.stop`)

Antes: `stop()` solo cerraba el socket TCP local. Cerrar el socket **no** aborta el
EmStat (el Pico lee `ABORT` con `poll_stop()` entre líneas, no por cierre de conexión):
el experimento seguía corriendo y **la celda quedaba energizada** con el electrodo
conectado.

Ahora: `stop(send_abort=False)` recibe un parámetro.

- El botón **⏹ Stop** llama `stop(send_abort=True)` (vía `lambda` para que Tkinter no
  inyecte un `event` posicional). Si el experimento sigue vivo, envía primero
  `{"cmd":"ABORT"}\n` por el socket y luego hace el teardown normal.
- Es **fire-and-close**: no se espera la confirmación `emstat_aborted`. El firmware
  garantiza el cierre limpio (`Z\n` → `on_finished:` → `cell_off`) lea o no el host la
  respuesta.
- Las salidas disparadas por el firmware (cierres terminales) llaman
  `stop(send_abort=False)`: el experimento **ya terminó** en el Pico, así que reenviar
  `ABORT` sería inútil y competiría con el cierre del socket.

## 3. Manejo de cierres terminales (`_tcp_processor`)

Antes solo se manejaban `emstat_data` y `emstat_end`; cualquier `emstat_error` se
descartaba en silencio, de modo que un canal rechazado **colgaba la corrida** sin
mensaje ni datos hasta que el usuario pulsaba Stop.

Ahora `_tcp_processor` maneja además `emstat_error`, `emstat_aborted`,
`emstat_maxtime` y `emstat_timeout`: muestra un texto legible en la etiqueta de estado
(`_format_terminal_status`) y cierra la corrida igual que `emstat_end`
(`stop_event.set()` + `break` → `stop(send_abort=False)`). Así un canal rechazado se ve
de inmediato.

## 4. Lock de envío

`stop()` (hilo de UI) y `_tcp_reader` (hilo lector) pueden hacer `sock.sendall` a la
vez (ABORT vs. keepalive cada 120 s), y dos `sendall` concurrentes pueden intercalar
bytes y corromper la línea JSON. Se añadió `self._send_lock = threading.Lock()` y se
envuelven los **tres** envíos: payload inicial, keepalive y ABORT.

---

## 5. Selector de canal de electrodo

`ui/ElectrochemicalFrame.py` agrega un `Combobox` de solo lectura
**"Electrode channel:"** con valores `0..7`, default `0`, junto al selector de método.
Es la **fuente única de verdad** del canal, independiente del método (CV/SQWV) y
persiste al cambiar de método.

- `ElectrochemicalFrame.get_channel()` devuelve el canal como `int` (degrada a `0` si la
  lectura falla).
- Se pasa como `callback_get_channel=self.get_channel` a `CVFrame` y `SWVFrame`
  (mismo patrón que `callback_get_ip_sender`).

## 6. `"ch"` en el payload

`CVFrame.create_payload_cv()` y `SWVFrame.generate_payload()` añaden `"ch": <int>` leído
con `self._get_channel()`:

- Es un **`int` crudo**, no pasa por `convert_si_integer_full`.
- Si no hay callback (uso aislado del frame, p. ej. los demos `__main__`) o la lectura
  falla, degrada a `ch = 0`.
- **No** hay validación de rango en el host: el firmware v1.6 es el validador estricto y
  su `emstat_error` ya se muestra en la UI (ver §3).

---

## 7. Seguridad: defensa por capas y dead-man switch

El aborto recorre **tres nodos**:

```
App Python (este repo) ──TCP:5006──► Wemos D1 mini ──UART_LINK──► Pico 2 ──UART──► EmStat
        stop()                       (WemosD1Mini.ino)      (emstat_wifi_v1.6.py)      celda
```

### 7.1 El riesgo: `fire-and-close` + ABORT perdido = celda energizada

El host hace **fire-and-close**: envía `{"cmd":"ABORT"}` y cierra el socket de
inmediato (no espera `emstat_aborted`). Ese ABORT puede **perderse**:

- El Wemos, al detectar la caída del cliente TCP, hace `tcpClient.stop()` en
  `acceptTcpIfNeeded()`, que **descarta el buffer RX** (la línea ABORT aún sin
  reenviar al Pico). `acceptTcpIfNeeded()` corre **antes** de `handleTcpRx()` en el
  `loop()`, así que el FIN puede procesarse antes de drenar el ABORT.
- O el host **crashea / pierde red**: no queda código que reintente.

Si el ABORT se pierde, **ningún watchdog se dispara a tiempo**: el EmStat responde
bien y el experimento dura <10 min, así que ni el idle-timeout ni `MAX_EXPERIMENT_MS`
(10 min) del Pico cortan. El experimento corre hasta el final **con la celda
encendida**, aunque el host crea que paró.

### 7.2 La defensa: dead-man switch en el Wemos (capa primaria)

`WemosD1Mini.ino` aborta **por su cuenta** cuando detecta la caída del cliente TCP,
sin depender de que el host siga vivo ni de que su ABORT haya sobrevivido:

- **Rastreo de estado** (`experimentActive`): en `handleSerialLines()`, observando el
  stream `EMSTAT:` que ya reenvía, marca `true` al ver `emstat_start` y `false` ante
  cualquier tipo terminal (`emstat_end`/`aborted`/`maxtime`/`timeout`/`error`).
- **Detección de caída** (`tcpWasConnected`): en `acceptTcpIfNeeded()`, en la
  transición conectado→caído, **si `experimentActive`**, inyecta
  `EMSTAT:{"cmd":"ABORT"}` al Pico (`injectAbortToPico()`) **antes** de `stop()`.
- **Gating por experimento activo:** evita un ABORT espurio en el cierre por fin
  normal (que envenenaría la siguiente corrida si quedara en el buffer del Pico).
- **Idle timeout** bajado de 15 min a **4 min**: un host muerto *sin FIN* se corta y
  aborta en ≤4 min (vía el mismo dead-man), antes del tope de 10 min del Pico. El
  margen sobre el keepalive del host (120 s) evita cortar uno vivo.

Esto hace que el **fire-and-close del host sea seguro por construcción**: cerrar el
socket *es* el disparador del aborto. Por eso el host **no** reintroduce la espera de
`emstat_aborted` (se mantuvo `fire-and-close`).

### 7.3 Por qué el Pico no cambia

`run_experiment_read_loop()` resetea `_abort_requested = False` al **inicio de cada
experimento** (`emstat_wifi_v1.6.py`), y el gating del Wemos evita ABORTs espurios
mientras está idle. No se requiere cambio en el firmware del Pico.

### 7.4 Hueco conocido (aceptado)

Pérdida de energía/cable del host **sin FIN**: el Wemos no se entera hasta que falla
una escritura TCP o vence el idle-timeout (4 min). En esa ventana el backstop es el
`MAX_EXPERIMENT_MS` (≤10 min) del Pico. Aceptado.

> El cambio del dead-man vive en un proyecto Arduino **separado** (no en este repo):
> `…/Documents/Arduino/WemosD1Mini/WemosD1Mini.ino`.

---

## 8. Pendientes / a verificar

- [ ] Validar en hardware que `ABORT` apaga la celda (`emstat_aborted` con `clean=true`).
- [ ] Validar el dead-man: matar el host (cerrar socket / kill del proceso) a mitad de
      experimento y confirmar que el Wemos inyecta ABORT y la celda se apaga.
- [ ] Confirmar que un fin normal (`emstat_end`) **no** dispara ABORT espurio que
      aborte la siguiente corrida.
- [ ] Confirmar el mapeo físico canal MCP (puerto A, pin `0-7`) → electrodo real.

---

__author__ = "Edisson A. Naula"
