# Fin de corrida PCR: apagar, guardar siempre, Stop sin congelar, cierre de la app

Cómo termina una corrida PCR en cada camino de salida y por qué. Antes del 26/10/2026 el
guardado vivía al final del cuerpo del hilo: todo lo que no fuera un fin natural o un Stop
limpio perdía la corrida entera. Con el guardado `.xlsx` (~3 s en el Pi,
[almacenamiento_por_experimento.md](almacenamiento_por_experimento.md) §3.1), además, el
Stop dejó de mostrar su mensaje.

## 1. Qué fallaba (revisado el 26/10/2026)

| Caso | Antes |
|---|---|
| Excepción en el hilo (p. ej. un error I2C del ADS al leer la fluorescencia) | `except` solo imprimía; `finally` apagaba. **No se guardaba nada** y el status no decía nada del error. |
| Cerrar la ventana a mitad de corrida | No había `<Destroy>` en `PCRFrame`. La corrida **seguía sin UI, con el heater**, hasta la siguiente lectura de fluorescencia. Ahí `self.after(...)` desde el hilo lanzaba `RuntimeError: main thread is not in main loop` (reproducido) y caía en el caso anterior: se perdía todo. |
| Stop en una corrida larga | El callback hacía `join(timeout=3)` en el hilo de UI (UI congelada) y luego `_teardown_hardware`, que ponía `running_experiment=False`. El guardado tarda 3.2 s en el Pi: el poll terminaba antes y el mensaje "Data saved" se perdía. El archivo sí se escribía. |
| Excepción en la preparación (antes del `try`, p. ej. el puerto UDP ocupado) | El hilo moría sin `finally`: `running_experiment` quedaba en `True`, la UI en "corriendo" y las tabs bloqueadas para siempre. |
| Corrida después de un aborto (watchdog o salvaguarda de fases) | Los stop-events quedaban activados y la corrida siguiente los **reusaba** (`Event() if None else existente`): se detenía al arrancar. |
| Aborto del watchdog | Marcaba `aborted_sensors`, pero el hilo entraba a otra fase antes de ver el stop y sobrescribía `phase_code`. |
| Corte de luz, cuelgue o kill del Pi | Todo vive en RAM hasta el final: se pierde. **Sigue igual** (§5). |

## 2. Diseño: `experiment_pcr` envuelve a `_run_pcr`

El hilo corre [`experiment_pcr`](../ui/PcrFrame.py#L2657), un envoltorio del cuerpo de
siempre ([`_run_pcr`](../ui/PcrFrame.py#L2719), sin `try/finally` propio). Termine como
termine (fin natural, Stop, aborto, excepción en el cuerpo o en la preparación, cierre de
la app), el cierre sigue siempre este orden:

1. `_run_closing = True`. Desarma el watchdog, porque el UDP se cierra a propósito, y el
   status pasa a "Saving data…".
2. **`_teardown_hardware()` primero**: motor, UDP, heater y LED de fluorescencia. Antes el
   motor seguía girando durante el guardado.
3. `_run_end = _end_reason(error)` → fila **`end`** de la metadata.
4. Guardar (`save_data_temps_file`, con su respaldo CSV), **solo si se pasó el start-gate**
   (`_run_started`). Un `aborted_start` o un fallo en la preparación no tienen datos.
5. `_save_note = _end_note(...)`: el mensaje final del status.
6. **`running_experiment = False` al final**, en un `finally`. Es la señal para que
   `_ui_poll_loop` restaure la UI, desbloquee las tabs y muestre el mensaje.
   `_teardown_hardware` ya no toca ese flag.

Valores de `end` ([`_end_reason`](../ui/PcrFrame.py#L2687)). Gana el motivo del paro
pedido, aunque luego salte una excepción: es consecuencia del paro, y la traza queda en el
log.

| `end` | Cuándo | Status final |
|---|---|---|
| `done` | fin natural | `Data saved to …` |
| `stopped` | botón Stop | `Stopped. Data saved to …` |
| `app_closed` | cierre de la app | (la ventana ya se cerró) |
| `aborted_sensors` / `aborted_timeouts` | watchdog / salvaguarda de fases | `Aborted: …. Data saved to …` |
| `aborted_start` | ningún sensor al inicio (no guarda) | el State lo dice |
| `error: <Tipo>: <msg>` | excepción | `Run failed (<Tipo>: <msg>). Data saved to …` o `… No data saved.` |

Los motivos de paro pasan todos por [`request_stop(reason)`](../ui/PcrFrame.py#L3067).
Activa los dos eventos, anota el motivo (gana el primero) y la hora: Stop, cierre, watchdog
y salvaguarda. Los eventos se crean **nuevos en cada corrida** en
`callback_start_experiment`.

**El hilo del experimento nunca toca Tk.** El único caso que había, el refresco de la
gráfica del fotodetector desde `_read_fluorescence`, pasó a `_ui_poll_loop`, que la
redibuja cuando cambia `len(data_photodetector)`. El callback UDP y el guardado ya eran
Python puro.

`_teardown_hardware` es idempotente bajo `_teardown_lock`, porque lo pueden llamar a la vez
el cierre del hilo y la red de seguridad del Stop.

## 3. Stop sin congelar la UI

[`callback_stop_experiment`](../ui/PcrFrame.py#L3053) solo señaliza (`request_stop`). La
UI no espera. `_ui_poll_loop` sigue con su tick de 500 ms, muestra "Stopping…" y luego
"Saving data…", y restaura la UI **cuando el hilo terminó todo**, con el mensaje final. Las
tabs siguen bloqueadas hasta entonces: nadie toca el hardware ni arranca otra corrida
mientras se guarda (Start comprueba `running_experiment`).

Redes de seguridad ([`_check_stop_timeouts`](../ui/PcrFrame.py#L3079), desde el poll):

- **`PCR_STOP_FORCE_S` = 3 s** sin que el hilo llegue a su cierre: la UI fuerza
  `_teardown_hardware`, como hacía el Stop de antes tras su `join`.
- **`PCR_STOP_GIVEUP_S` = 30 s** con el hilo vivo: la UI se restaura igual, con
  `Warning: the run did not finish cleanly; data may not be saved`. Start sigue rechazado
  mientras ese hilo viva.

Si no hay hilo vivo, Stop restaura la UI directamente, como antes. Eso cubre una entrada
inválida en `callback_start_experiment`, que deja la UI escondida.

## 4. Cierre de la app

- [`MainGUI.on_close_window`](../ui/MainGUI.py#L400): con una corrida activa pide
  confirmación ("A PCR run is in progress. Stop it, save its data and close?"). Si se
  acepta, llama a `request_stop("app_closed")` y **la ventana espera** a que
  `running_experiment` sea `False` (sondeo `after(200)`, tope `PCR_STOP_GIVEUP_S`); luego
  destruye. Mientras tanto, el status de la tab PCR muestra el progreso.
- **Backstop** [`PCRFrame._on_destroy`](../ui/PcrFrame.py#L3098), para cualquier otro
  camino de cierre: cancela el tick pendiente del poll (si no, Tcl reporta un comando
  borrado al salir) y pide el paro. El hilo no es daemon, así que apaga y guarda aunque la
  ventana ya no exista, y el proceso sale cuando termina.

## 5. Fuera de alcance (decisión del 26/10/2026)

- **Corte de luz / cuelgue / kill**: se descartó por ahora el respaldo incremental (filas
  nuevas a un `.partial.csv` por ciclo, recuperable con el conversor). Reescribir el
  `.xlsx` cada ciclo costaría hasta 3 s en el Pi y competiría con el control. Retomarlo si
  el Pi llega a caerse a mitad de una corrida.
- Al cerrar la app puede salir en stderr un `bgerror … idle_draw` de matplotlib (un
  `draw_idle` pendiente del canvas). Es cosmético.

## 6. Verificación (26/10/2026, Windows, dev)

Simulación con el código real de `PcrFrame`/`MainGUI` y hardware falso: GPIO, motor,
UDP con una planta térmica simple, ADS, y un guardado retrasado 3.5 s para imitar al Pi.
Resultado: **56/56 comprobaciones**.

- Fin natural, Stop a mitad, excepción I2C a mitad, excepción al preparar, aborto del
  watchdog y corrida tras el aborto: un `.xlsx` con el `end` correcto (salvo al preparar:
  nada), hardware apagado **antes** de guardar, tabs desbloqueadas **después** de guardar,
  "Saving data…" visible y el status final esperado.
- El Stop tarda < 0.1 s en el hilo de UI y muestra "Stopping…". Start durante el guardado
  se ignora.
- Cierre con confirmación (`MainGUI.on_close_window`): la ventana se destruye después del
  guardado, con `end = app_closed`. Destroy directo (backstop): guarda igual, sin
  `RuntimeError`.

Además: `files_test/ajuste_21oct/test_adaptive.py` da una salida **idéntica** a `HEAD`
(clásico y adaptativo: los lazos térmicos no cambiaron), pyrefly no marca errores nuevos y
la app arranca y cierra limpia.

## 7. Pendiente (HW)

- [ ] En el Pi, con la corrida del adaptativo o una corta: al terminar se ve
  "Saving data…" y luego `Data saved to …`, y el `.xlsx` trae `end = done`.
- [ ] Una corrida corta con Stop a mitad: la UI no se congela, se ve
  `Stopped. Data saved to …` y `end = stopped`.
- [ ] (Opcional) Cerrar la ventana durante una corrida corta: aparece la confirmación, la
  ventana espera al guardado, el heater queda apagado y `end = app_closed`.

__author__ = "Edisson A. Naula"
__date__ = "$ 26/10/2026 $"
