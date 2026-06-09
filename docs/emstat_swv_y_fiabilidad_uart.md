# EmStat — SWV: correcciones de script y fiabilidad del UART

Documenta el diagnóstico y las correcciones que hicieron funcionar el **SWV** (Square Wave
Voltammetry), más el manejo robusto de errores de MethodSCRIPT. Complementa
[emstat_udp_recovery.md](emstat_udp_recovery.md) (tap UDP, `seq`, parser, fin `*`+blank).

Cadena de tres nodos (recordatorio):

```
App Python ──TCP:5006──► Wemos D1 mini ──UART_LINK(GP8/9)──► Pico 2 ──UART_EMSTAT(GP0/1)──► EmStat
                                                              (genera/envía MethodSCRIPT)
```

---

## 1. Síntoma

Al correr un SWV, el EmStat rechazaba el script con errores de MethodSCRIPT
(`e!4001`, `e!4008`) en líneas que **cambiaban entre corridas con los mismos parámetros**,
seguidos de `emstat_timeout`/`emstat_aborted` y reinicio. Además se veían paquetes basura
(`aE"^G~$M99999`) y mensajes EMSTAT truncados/pegados.

## 2. La causa raíz: ráfagas sin pacing desbordan el RX del receptor

El diagnóstico definitivo fue un **eco temporal del script** (`DEBUG_ECHO_SCRIPT` en el
Pico): el Pico reenvía al host el script exacto que mandó al EmStat, numerado. Reveló:

1. **El script se genera correctamente** — coincide carácter por carácter con lo esperado.
   No era un bug del generador.
2. **Errores inconsistentes con el mismo script** (`e!4001 L21` una vez, `e!4008 L19` otra)
   ⇒ el EmStat recibe el script **corrupto e intermitentemente**. Un parser determinístico
   daría siempre el mismo error con los mismos bytes; errores que cambian = bytes que
   cambian = **corrupción en el UART Pico→EmStat**.
3. **El eco mismo llegó truncado/pegado** porque se enviaron 25 mensajes en ráfaga y
   desbordaron el RX del Wemos — el **mismo mecanismo** que corrompe el script:
   `write_lines` enviaba las ~26 líneas del script seguidas, sin pausa, a 230400 baud, y
   desbordaba el buffer RX del EmStat.

> En operación normal los datos llegan al ritmo de medición (pausados), por eso la pérdida
> de datos era ~3% y no peor; el problema agudo era solo la **ráfaga del script**.

## 3. El fix: pacing en `write_lines` (firmware Pico)

`EmstatDrivers.EmstatPico.write_lines` ahora hace una pausa de **5 ms entre líneas** al
enviar el script al EmStat, para que drene su RX. ~130 ms extra por corrida, imperceptible.

```python
def write_lines(self, lines):
    for i, line in enumerate(lines):
        self.uart.write(line + "\n")
        time.sleep_ms(5)   # pacing: evita overflow del RX del EmStat
    self.uart.write("\n")
```

**Si el `e!####` persistiera tras el pacing** sería corrupción eléctrica (no de ráfaga):
subir el pacing, bajar el baud de `uart_emstat` (230400→115200, ambos lados) o revisar
cableado/tierra Pico↔EmStat.

## 3-bis. El gemelo de entrada: el comando SWV desborda el RX del Pico

Síntoma distinto al `e!####`: el SWV **a veces ni arranca**. La consola del host queda en

```
reseting states
UDP tap escuchando en :5005
starting tcp on port 5006 and address 192.168.137.223 …
```

y no avanza. CV arranca siempre y múltiples veces; SWV es intermitente.

**Causa.** Es el mismo desbordamiento de ráfaga, pero en el sentido **host → Wemos → Pico**.
El payload de SWV es una línea JSON larga (~350 B: ~16 parámetros) frente a los ~150 B de CV.
El UART_LINK del Pico se creaba **sin `rxbuf`** → RX por defecto del puerto RP2 = **256 B**.
Cuando el Wemos vuelca la línea de SWV en ráfaga a 230400 baud mientras el Pico está en la
lectura I2C de temperatura (`maybe_send_temperature` es bloqueante) + `sleep_ms(2)` del
`main_loop`, el RX de 256 B se desborda y se caen bytes → `json.loads` falla en
`process_uart_rx` → el Pico manda `{"error":"JSON_PARSE", ...}` (sin `"type"`). CV cabe en
256 B y nunca desborda; SWV no cabe → intermitente según coincida la ráfaga con la ventana
ocupada del Pico.

**Por qué se colgaba el host (no solo fallaba).** El host descartaba en silencio cualquier
mensaje EMSTAT sin `"type"` reconocido, y su watchdog de inactividad solo dispara tras
`_run_started`. Como el experimento nunca arrancó, `_run_started` quedaba en False → cuelgue
indefinido tras "starting tcp".

**Fixes (tres):**

- **Pico (reflash):** `uart_link = UART(..., rxbuf=2048)`. Da margen para absorber la línea
  larga aunque el Pico esté ocupado. Resuelve la causa.
- **Host:** `_handle_emstat_msg` ahora **surfacea** un mensaje sin `type` que trae `error`
  (`JSON_PARSE`): muestra el estado y cierra la corrida (no va a arrancar, hay que reintentar)
  en vez de tragárselo.
- **Host:** watchdog de **arranque** — si se conectó el TCP y se mandó el payload pero el Pico
  no respondió nada en `2 × watchdog_timeout`, cierra la corrida con aviso (red de seguridad
  si hasta el `JSON_PARSE` se pierde).

**Si persistiera tras el `rxbuf`**: el Pico podría seguir perdiendo bytes si la lectura I2C
del MLX90614 bloquea demasiado; opciones: leer temperatura con menos frecuencia durante un
experimento, o no medir temperatura mientras `process_uart_rx` tenga datos a medio recibir.

## 4. Bugs de generación del script SWV (corregidos de paso)

Encontrados al regenerar el script con los parámetros reales. En `construc_*` (presentes
**dos veces**: host `Drivers/EmstatUtils.py` para preview y firmware
`DiscPCB/EmstatDrivers.py` para ejecución):

- **Fix A — `var i_forward` duplicado** en `construct_header_experiment`: el bloque
  `if i_reverse` declaraba `var i_forward` (en vez de `var i_reverse`) y otro `var i_reverse`
  iba incondicional. Resultado: `i_forward` ×2 e `i_reverse` ×1, dejando la variable
  ambigua (`e!4001` "unknown command" en `pck_add i_forward/i_reverse`). Ahora cada variable
  se declara una vez, igual al ejemplo oficial PalmSens. (De paso, CV ya no declara un
  `var i_reverse` que no usa.)
- **Fix B — potencial vacío en acondicionamiento/deposición** en
  `construc_individual_script_sqwv`: con tiempo pero sin potencial (`t_con` sin `E_con`) se
  generaba `set_e ` / `meas_loop_ca e i  200m t` (potencial vacío) → `e!4001`/`e!4008`. Ahora
  cada bloque requiere **tiempo y potencial** (`if t_con != "" and E_con != ""`); si falta el
  potencial, el bloque se omite.

## 5. Manejo robusto de errores de MethodSCRIPT (host)

- **Códigos legibles:** `Drivers/EmstatUtils.decode_methodscript_error()` parsea
  `e!<hex>: Line L, Col C` y, vía `resources/errors_emstat.json` (Appendix A del manual),
  produce `{code, code_int, description, line, col}`. El parser adjunta esto al evento
  `error`, y `EventPlotter._handle_methodscript_error` lo muestra:
  `MethodSCRIPT error: 0x4001 (The script command is unknown) @ L31:C11 (via UDP)`.
- **Mensajes EMSTAT pegados/truncados:** `_handle_emstat_line` parte la línea por el marcador
  `EMSTAT:` y procesa cada segmento, así un mensaje truncado no se traga al válido pegado.
  Un guard adicional surfacea cualquier `e!####:` en el payload aunque no parsee como JSON.
- **Error fatal = cierre:** un error de MethodSCRIPT termina la corrida (sin ABORT; ante un
  error de parseo la celda no se encendió).

## 6. Diagnóstico temporal: `DEBUG_ECHO_SCRIPT`

Flag en `emstat_wifi_v1.7.py` (default **False**). En True, antes de medir, el Pico ecoa el
script enviado al EmStat como `EMSTAT:{"type":"script_dbg","line":N,"text":...}`; el host lo
imprime (`SCRIPT[N]: ...`). Útil para mapear futuros `e!#### Line/Col` al comando real y
detectar corrupción en tránsito. Dejarlo en False en operación (el eco va en ráfaga y
estresa el enlace Pico→Wemos).

## 7. Archivos tocados

| Archivo | Cambio | ¿Reflasheo? |
|---|---|---|
| `DiscPCB/EmstatDrivers.py` | pacing en `write_lines`; Fix A + Fix B en builders | **Sí (Pico)** |
| `DiscPCB/emstat_wifi_v1.7.py` | `DEBUG_ECHO_SCRIPT` + eco en rama sqwv; `uart_link rxbuf=2048` (§3-bis) | **Sí (Pico)** |
| `Drivers/EmstatUtils.py` | Fix A + Fix B (preview); `decode_methodscript_error` | No (host) |
| `ui/EventEmstatFrame.py` | error legible, split de pegados, eco; surfacear `JSON_PARSE` + watchdog de arranque (§3-bis) | No (host) |
| `resources/errors_emstat.json` | tabla de códigos (Appendix A) | No (datos) |

Espejos git-trackeados en [../firmware/DiscPCB/](../firmware/DiscPCB/).

## 8. Verificación

- [x] Eco confirma que el script SWV se genera correcto (sin `var` duplicado, 4 variables).
- [x] Con pacing (5 ms/línea), el SWV corre sin `e!####` y entrega paquetes `da;ba;ba;ba`.
- [ ] Con `rxbuf=2048` (§3-bis), el SWV arranca de forma fiable (no se queda en "starting tcp").
- [ ] (Opcional) Confirmar estabilidad en corridas largas / con acondicionamiento.

---

__author__ = "Edisson A. Naula"
