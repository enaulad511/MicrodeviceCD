# EmStat WiFi Bridge — v1.6

Documentación de la versión `emstat_wifi_v1.6.py` (firmware MicroPython para Raspberry Pi Pico 2).
Pensada para usarse como **contexto** en futuras sesiones de desarrollo.

- **Archivo:** [../emstat_wifi_v1.6.py](../emstat_wifi_v1.6.py)
- **Driver del EmStat:** [../EmstatDrivers.py](../EmstatDrivers.py)
- **Base:** `emstat_wifi_v1.5.py` (se conserva sin cambios)
- **Autor:** Edisson Naula

---

## 1. Qué hace este firmware

El Pico 2 actúa como **puente** entre un host (Raspberry / Wemos D1 mini) y un **potenciostato PalmSens EmStat Pico**:

```
                 UART_LINK (UART1, GP8/GP9, 230400)
   Host  <───────── comandos EMSTAT:{json} ──────────>  Pico 2
 (Wemos /          <──── telemetría UDP:/EMSTAT: ─────         │
  Raspberry)                                                   │ UART_EMSTAT
                                                               │ (UART0, GP0/GP1, 230400)
                                                               ▼
                                                        EmStat Pico
                                                       (MethodSCRIPT)
        Sensores locales: MLX90614 (I2C0), MAX31855 (SPI1)
```

El Pico:
1. Recibe comandos del host por `UART_LINK` con prefijo `EMSTAT:`.
2. Traduce los parámetros del experimento y genera un **script MethodSCRIPT** (vía `EmstatDrivers`).
3. Lo envía al EmStat por `UART_EMSTAT`, lee la respuesta línea a línea y la reenvía al host.
4. En paralelo (cuando no hay experimento) emite **telemetría de temperatura** por UDP.

---

## 2. Mapa de hardware

| Recurso | Bus / Pines | Notas |
|---|---|---|
| Enlace con host | `UART1` TX=GP8, RX=GP9, 230400, `timeout=0` | Lectura no bloqueante. Alterno: GP0/GP1 si GP8/GP9 falla |
| EmStat Pico | `UART0` TX=GP0, RX=GP1, 230400, `timeout=2000` | **El timeout de 2s es la granularidad del idle-watchdog** |
| MLX90614 (IR temp) | `I2C0` SDA=GP20, SCL=GP21, 100 kHz | Opcional; `sensor_temp=None` si no aparece |
| MCP23017 (canales electrodos) | `I2C0` @ `0x20` (comparte bus con MLX) | 8 canales en puerto A, multiplex; `mcp=None` si no aparece |
| MAX31855 (termopar) | `SPI1` SCK=GP14, MISO=GP12, CS=GP13 | 14-bit con signo, 0.25 °C/LSB |
| LED on-board | `Pin("LED")` vía `Timer` | Parpadeo indica estado (ver §6) |

---

## 3. Protocolo con el host

### 3.1 Comandos entrantes (host → Pico, por `UART_LINK`)

Todos van como una línea: `EMSTAT:<json>\n`.

| Comando | Efecto |
|---|---|
| `{"cmd":"PING"}` | Responde `{"type":"pong"}` por UDP |
| `{"cmd":"START"}` | Reanuda telemetría de temperatura |
| `{"cmd":"STOP"}` | **Solo** detiene la telemetría de temperatura (NO aborta un experimento) |
| `{"cmd":"ABORT"}` | **Cancela en caliente el experimento en curso** (ver §4) |
| `{"cmd":"SET","sample_ms":N}` | Cambia el periodo de muestreo de temperatura (mín. 10) |
| `{"method":"cv", ...}` | Lanza una Voltametría Cíclica |
| `{"method":"sqwv", ...}` | Lanza una Voltametría de Onda Cuadrada |

> **Importante:** `STOP` y `ABORT` son distintos. `STOP` = telemetría; `ABORT` = experimento.

#### Parámetros de experimento (nombres cortos del host → internos)

**Común a todo experimento:** `ch`→canal de electrodo (0-7, **obligatorio**, ver §6).

**CV (`method:"cv"`):** `t_e`→t_equilibration, `E_b`→E_begin, `E_1`→E_vertex1, `E_2`→E_vertex2,
`E_s`→E_step, `sc_r`→scan_rate, `n_sc`→nscans, `m_b`→max_bandwith, `min_da`, `max_da`,
`range_ba`, `ba_1`→auto_ba1, `ba_2`→auto_ba2.

**SQWV (`method:"sqwv"`):** `t_e`, `E_b`→E_begin, `E_e`→E_end, `E_s`→E_step, `Amp`→Amplitude,
`Freq`→frequency, `m_b`, `min_da`, `max_da`, `range_ba`, `ba_1`, `ba_2`,
`E_con`/`t_con` (condicionamiento), `E_dep`/`t_dep` (deposición).

> Los tiempos en `"0"` se normalizan a `""` (etapa omitida en el script MethodSCRIPT).

Ejemplo: `EMSTAT:{"method":"cv","ch":3,"E_b":"0","E_1":"-1","E_2":"1","sc_r":"1"}`

### 3.2 Mensajes salientes (Pico → host)

Telemetría general: `UDP:<...>\n`. Resultados/estado del EmStat: `EMSTAT:<json>\n`.

| `type` | Cuándo |
|---|---|
| `emstat_start` | Al iniciar; incluye `method`, `ch` (canal) y `params` resueltos |
| `emstat_data` | Cada línea de datos del EmStat (`raw` = línea cruda) |
| `emstat_end` | **Fin normal** del experimento |
| `emstat_aborted` | El host mandó `ABORT`; incluye `clean` (bool) |
| `emstat_maxtime` | Se superó el tope absoluto; incluye `clean` (bool) |
| `emstat_timeout` | El EmStat dejó de responder (desconexión); incluye `connected` (bool tras re-test) |
| `emstat_error` | Error al generar/enviar el script o excepción |

`clean=True` significa que tras enviar `Z` se confirmó el cierre por `on_finished:` (celda apagada).
`connected` (en `emstat_timeout`) es el resultado de re-testear la conexión tras la caída.

---

## 4. El loop de lectura robusto (corazón de v1.6)

Función única [`run_experiment_read_loop(method, on_data=None)`](../emstat_wifi_v1.6.py#L306),
compartida por CV, SQWV y métodos futuros. El parámetro `on_data` permite reformatear cada
línea por método sin tocar la lógica de control (por defecto: passthrough crudo).

### 4.1 Diagrama de estados

```
        ┌─────────────────────────── loop ───────────────────────────┐
        │                                                             │
   poll_stop() ── ABORT? ──► Z\n ─► drenar limpio ─► emstat_aborted   │
        │                                                             │
   ¿elapsed > MAX_EXPERIMENT_MS? ─► Z\n ─► drenar ─► emstat_maxtime    │
        │                                                             │
   readline() (timeout 2s)                                            │
        ├─ ERROR_TOKEN (timeout/err) ─► ¿idle > MAX_IDLE_MS?          │
        │        ├─ sí ─► Z\n ─► drenar corto ─► flush ─► re-test ─► emstat_timeout
        │        └─ no ─► continue ───────────────────────────────────┘
        ├─ línea en blanco ─► emstat_end
        └─ dato válido ─► reenviar + reset idle ──────────────────────┘
```

### 4.2 Por qué funciona

- El EmStat puede tardar **hasta ~10 s** en responder en **cualquier punto** (antes de la 1ª línea
  o entre líneas). Por eso el watchdog es un **idle timeout que se reinicia con cada dato válido**,
  no un timeout por lectura.
- Como `UART_EMSTAT.timeout = 2000 ms`, cada `readline()` vacío equivale a 2 s sin datos. El idle se
  mide con `time.ticks_ms()` desde la última línea válida (`MAX_IDLE_MS`).
- El **tope absoluto** (`MAX_EXPERIMENT_MS`) protege contra un EmStat que "gotea" datos sin terminar.
- El abort no es un simple `break`: se envía **`Z\n`** para que el EmStat termine la iteración actual
  y salte a `on_finished:` (que contiene `cell_off`), dejando la **celda apagada** por protocolo.

### 4.3 Cancelación en caliente sin hilos

El experimento corre **inline** en `main_loop` (no usa `_thread`). Para poder cancelar a mitad,
[`poll_stop()`](../emstat_wifi_v1.6.py#L225) lee `UART_LINK` entre líneas y prende el flag global
`_abort_requested` si llega `{"cmd":"ABORT"}`. **No re-despacha** otros comandos (evita reentrancia
en `handle_command`); cualquier otra línea recibida durante el experimento se ignora.

> Limitación conocida: durante un experimento la telemetría de temperatura queda en pausa (modelo
> inline). Si en el futuro se requiere telemetría simultánea, migrar a `_thread` (la infraestructura
> `_emstat_running` / `emstat_job_stream_over_tcp` ya existe en `EmstatDrivers.py`).

---

## 5. El comando de aborto del EmStat (`Z`)

> Enviar el carácter ASCII **`Z`** seguido de salto de línea (`Z\n`) a un EmStat que está ejecutando
> una medición hace que **termine la iteración actual del loop activo y salte inmediatamente a la
> etiqueta `on_finished:`** del script.

Ambos generadores de script (`construc_nscans_script_cv` y `construc_individual_script_sqwv` en
`EmstatDrivers.py`) terminan con `on_finished:` → `cell_off`. Por eso `Z\n` apaga la celda de forma
limpia sin resets de hardware. Tras `Z`, el firmware **drena** los paquetes finales hasta la línea en
blanco (`_drain_after_z`, ventana `DRAIN_MS`); si no llega, hace flush duro del UART.

---

## 6. Canales de electrodos (MCP23017)

El MCP23017 conmuta **electrodos externos** que usa el EmStat. Comparte el bus `I2C0` con el
MLX90614 (direcciones distintas) y trabaja en **multiplex**: un solo canal activo a la vez.

- **Config:** puerto A, canales `0-7`, `multiplex_mode=True` (al activar uno, apaga el resto).
- **Especificación:** campo `"ch":N` **obligatorio** en cada payload de experimento (cv/sqwv).
- **Ciclo de vida:** se activa justo antes de enviar el script (con `CH_SETTLE_MS` de asentamiento)
  y se apaga (`clear_all`) en un `finally` que cubre **todas** las salidas (fin, abort, maxtime,
  timeout, error). El electrodo queda aislado al terminar.
- **Validación estricta:** si `ch` falta, está fuera de rango, o el MCP no aparece en el bus, el
  experimento **no corre** y se responde `emstat_error` con `error` en `{mcp_no_disponible,
  ch_invalido, ch_fuera_de_rango, mcp_error:...}` más el `ch` recibido.

Funciones: [`_activate_channel(ch)`](../emstat_wifi_v1.6.py#L368) y
[`_deactivate_channel()`](../emstat_wifi_v1.6.py#L387). Degradación: si el MCP no está, `mcp=None`
y cualquier experimento con `ch` se rechaza (no hay medición sin electrodo).

---

## 7. Constantes ajustables

Lectura del EmStat ([líneas 75-78](../emstat_wifi_v1.6.py#L75-L78)):

| Constante | Valor | Significado |
|---|---|---|
| `MAX_IDLE_MS` | `16000` | Aborta si pasan >16 s **sin ninguna línea nueva** (margen sobre los 10 s legítimos) |
| `MAX_EXPERIMENT_MS` | `600000` | Tope absoluto: 10 min (los experimentos reales llegan a ~5 min) |
| `DRAIN_MS` | `6000` | Ventana para drenar la cola tras enviar `Z` |

Canales de electrodos (MCP23017):

| Constante | Valor | Significado |
|---|---|---|
| `MCP_ADDR` | `0x20` | Dirección I2C del MCP (A0-A2 a GND) |
| `CH_PORT` | `"A"` | Puerto usado para los electrodos |
| `CH_MIN`, `CH_MAX` | `0`, `7` | Rango válido de canal |
| `CH_SETTLE_MS` | `100` | Asentamiento tras conmutar, antes de medir |

Perfiles de LED: `LED_IDLE_S=0.5` (ok), `LED_FAST_S=0.20` (EmStat desconectado), `LED_VFAST_S=0.10`.

### 7.1 Arranque seguro / re-flasheo

El archivo corre como **`main.py`**, así que arranca solo al encender. Como `test_connection()` bloquea
hasta ~4 s leyendo el UART del EmStat y luego entra a un `main_loop` infinito, la placa queda ocupada
al instante y subir firmware nuevo es difícil. Dos mecanismos liberan el REPL **antes** de inicializar
los puertos serie (ambos al inicio del archivo, ver [líneas 18-49](../emstat_wifi_v1.6.py#L18-L49)):

| Constante | Valor | Significado |
|---|---|---|
| `SAFE_BOOT_PIN` | `22` | GPIO con botón a GND; si está presionado al encender, **salta la app al instante** (REPL libre). `None` lo desactiva. Elige un GPIO libre (en uso: GP0,1,8,9,12,13,14,20,21) |
| `BOOT_DELAY_S` | `5` | Cuenta regresiva al arrancar; **Ctrl-C / botón Stop** durante ella detiene el programa. `0` la desactiva |

Flujo para actualizar: resetear el Pico → durante la cuenta regresiva pulsar **Stop** en MicroPico
(o mantener el botón de `SAFE_BOOT_PIN` a GND) → REPL libre → subir el archivo. En producción se pueden
poner `BOOT_DELAY_S = 0` y `SAFE_BOOT_PIN = None`.

---

## 8. Cambios respecto a v1.5

1. **Fix del cuelgue infinito.** En v1.5, `EmstatPico.readline()` devuelve el string
   `"error-->comunication timeout"` (no `None`) al hacer timeout; el loop hacía `continue` ante todo lo
   que empezara con `"error"`, y el único `break` (línea en blanco) nunca llegaba con el EmStat muerto.
   Resultado: loop infinito que **congelaba todo el dispositivo** (también la telemetría). v1.6 distingue
   timeout/error vs dato vs fin, y aplica idle + tope absoluto.
2. **Loop unificado.** El loop de lectura, antes **duplicado** en las ramas `cv` y `sqwv`, se extrajo a
   `run_experiment_read_loop()` (un solo lugar, con hook `on_data` para futuros métodos).
3. **Cancelación `ABORT`** en caliente vía `poll_stop()`.
4. **Aborto limpio del EmStat** con `Z\n` + drenado + flush + re-test de conexión.
5. **4 tipos de mensaje de cierre** (`emstat_end` / `emstat_aborted` / `emstat_maxtime` / `emstat_timeout`).
6. **Bonus fix:** en la rama SQWV de v1.5 la llave del parámetro era `"frequebcy"` (typo) en lugar de
   `"frequency"`, por lo que la **frecuencia SQWV siempre caía al default (10)**. Corregido en v1.6.
7. **Canales de electrodos (MCP23017).** Integrado el control de electrodos externos vía `"ch"` en el
   payload, con validación estricta y apagado garantizado en todas las salidas (ver §6).
8. **Arranque seguro.** Pin de safe-boot (`SAFE_BOOT_PIN`) + ventana de arranque (`BOOT_DELAY_S`) para
   liberar el REPL y poder re-flashear, ya que el archivo corre como `main.py` (ver §7.1).

---

## 9. Integración con el host y pendientes

**Cadena de transporte:** `App (PC, TCP) → Wemos D1 mini → (UART) → Pico`. El **Wemos agrega el
prefijo `EMSTAT:`** a todo lo que reenvía TCP→UART; el host envía JSON crudo (p.ej.
`{"cmd":"ABORT"}`). El firmware ignora cualquier línea sin ese prefijo (`process_uart_rx` y
`poll_stop`). Cambios del lado del host documentados en
[`emstat_abort_y_canal.md`](../../../PycharmProjects/MicrodeviceCD/docs/emstat_abort_y_canal.md).

Hecho:

- [x] Envío de `{"cmd":"ABORT"}` desde el host (botón Stop → fire-and-close).
- [x] Selector de canal + `"ch"` en el payload (host es validador laxo; firmware es el estricto).
- [x] Host maneja los 4 cierres terminales (`emstat_error/aborted/maxtime/timeout`).

Pendiente / a verificar:

- [ ] **Riesgo: ABORT perdido = celda energizada.** Con *fire-and-close*, si el ABORT no llega al
      Pico (ruido UART, o el Wemos descarta RX al caer el TCP), ningún watchdog se dispara
      (el EmStat responde y el experimento dura <10 min) y la celda queda encendida hasta el fin
      natural. Mitigación recomendada: que el **Wemos inyecte `EMSTAT:{"cmd":"ABORT"}` al detectar
      desconexión del cliente TCP** (dead-man switch); o que el host espere `emstat_aborted` y
      reintente ABORT antes de cerrar.
- [ ] Confirmar el mapeo físico canal MCP (puerto A, pin 0-7) → electrodo real.
- [ ] Validar en hardware el drenado tras `Z` (que `on_finished:` cierre con línea en blanco →
      `emstat_aborted` con `clean=true`).
- [ ] Confirmar tiempos reales del peor caso para afinar `MAX_IDLE_MS` / `MAX_EXPERIMENT_MS`.
- [ ] (Opcional) Telemetría de temperatura simultánea al experimento → requeriría `_thread`.
