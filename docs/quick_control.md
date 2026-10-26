# Quick Control: tab unificada del control manual

> **26/10/2026:** el guardado pasó a `.xlsx` ([almacenamiento_por_experimento.md](almacenamiento_por_experimento.md)): el guardado es `unified_*.xlsx`, hoja `data` (mismo formato largo).

## Qué es

`ui/QuickControlFrame.py` agrega una tab **"Quick Control" ⚡** como **primera**
página del notebook anidado del Manual Control (`ui/MainGUI.py`). Reúne en una
sola vista lo esencial de las otras cinco tabs, para el flujo típico de
laboratorio (girar el disco + encender un LED + leer una señal) sin saltar
entre páginas. Las cinco tabs originales **coexisten** intactas como vista
"avanzada" (timed LED, ciclos on/off, go-to-zero, °C/°F, etc.).

Secciones del frame:

1. **Disc motor** — giro **continuo** (dirección CW/CCW + RPM, default 700) u
   **oscilador** de ángulo (0–45°, default 30 + velocidad %, default 10),
   elegidos con un combobox de modo y UN solo par Start/Stop. El oscilador es
   continuo hasta Stop (`n_times=None, flag_continue=True`); no se expone el
   número de repeticiones.
2. **LEDs** — dos `Checkbutton(bootstyle="round-toggle")`: calentamiento
   (GPIO 25, `led_heatin_pin`) y fluorescencia (GPIO 24, `led_fluorescence_pin`).
3. **Readings** — temperatura (UDP 5005) o fluorescencia (ADS1115 canal 0),
   **una señal a la vez**, con plot, retención de corridas ("Keep data") y
   guardado a CSV.

## Decisiones de diseño

### Motor: reuso del singleton de DiscFrame (no una instancia propia)

El motor sólo admite UNA conexión UART (`/dev/ttyAMA0`); dos `DriverStepperSys`
simultáneos corrompen los comandos. Por eso Quick Control **no** crea su propio
driver: muta los globales de módulo de `ui/DiscFrame.py` (`drv`, `thread_motor`,
`thread_lock`) vía `import ui.DiscFrame as disc` y reusa `spinMotorAngle` de
DiscFrame y `spinMotorRPM_ramped` de `Drivers/DriverStepperSys.py` (centralizada
ahí; la rampa corre en el firmware del Pico — ver
[stepper_rampa_firmware.md](stepper_rampa_firmware.md))
(`ui/QuickControlFrame.py`, `callback_motor_start`). El `thread_lock` global
garantiza un solo hilo de motor aunque se usen ambas tabs en la misma sesión.

El **Stop** del motor difiere de DiscFrame en un punto deliberado: DiscFrame
hace `thread_motor.join()` en el hilo de UI (congela la ventana durante la
rampa de frenado + `go_zero`, varios segundos). Quick Control hace el join y la
liberación del driver en un hilo aparte (`_motor_stop_worker`) y reactiva la UI
con `after(0, self._on_motor_stopped)`. Mientras "se detiene", ambos botones
quedan deshabilitados (`motor_stopping=True`) para impedir un re-Start.

### Motor: el driver solo está abierto mientras hay un hilo de motor vivo

Invariante (`ui/DiscFrame.py`): **`drv` abierto ⇔ hay un hilo de motor vivo**.
Todo hilo de motor de las tabs Disc y Quick Control corre envuelto en
`run_and_release(target, *args)`, que en un `finally` llama a
`release_driver()` (deshabilita ENABLE, cierra UART y libera GPIO 12, bajo
`thread_lock`, idempotente). Así el driver se suelta tanto por Stop como cuando
el movimiento acaba solo, o por una excepción. Los Stop de ambas tabs llaman
también a `release_driver()` tras el join, como red de seguridad.

Por qué importa: un `DriverStepperSys` abierto (1) retiene GPIO 12, así que PCR
(`sistemaMotor`) y el oscilador de CV/SWV (`spinMotorAngleDriver`, que crea su
propio driver) fallan con `line busy`. PCR aborta la corrida y en CV/SWV el
hilo del motor muere y **el experimento sigue sin agitación**. (2) Su hilo
lector `_reader_loop` **no es daemon**, así que al cerrar la app el proceso
quedaba colgado para siempre. Antes pasaba en dos casos: el **Zero** de la tab
Disc, que termina solo y dejaba el driver abierto hasta pulsar Stop, y cerrar
la app con el disco girando desde la tab Disc, que no tenía `<Destroy>`. En ese
segundo caso tampoco se mandaba `STOP` y el Pico seguía girando.

Al cerrar la app, `ControlDiscFrame._on_destroy` y `QuickControlFrame._on_destroy`
activan el stop del motor: el hilo frena en rampa, vuelve a cero (como Stop) y
libera el driver, y recién entonces sale el proceso (unos segundos). Los hilos
de motor de ambas tabs son **no daemon** a propósito: con `daemon=True` Python
los mataba a mitad del `close()`. La espera está acotada porque `_on_destroy`
siempre activa el stop y el `go_zero` expira a los 15 s. Si un dueño externo
tiene el motor, Disc (`_ensure_driver`) y Quick Control avisan
("Motor not available" / "Motor busy") y no arrancan, en vez de soltar un
traceback.

### Bloqueo de tabs mientras hay algo activo

Pedido explícito del usuario: mientras Quick Control opere **cualquier** cosa
(motor girando, algún LED ON, o lectura corriendo), el cambio de tab se
deshabilita — en **ambos** notebooks, porque PCR y Electrochemical también usan
el motor/UDP. Implementación:

- `QuickControlFrame._update_lock()` calcula el estado y llama a
  `lock_tabs_callback(locked)` (dueño `"quick"`).
- `MainGUI.set_tabs_locked()` pone `state="disabled"` en todas las tabs del
  notebook principal salvo Manual Control (índice 2) y en todas las del
  notebook anidado salvo Quick Control (índice 0).
- El desbloqueo es automático al quedar todo apagado/detenido; un label 🔒 en
  el frame indica qué lo mantiene bloqueado.

Este bloqueo se generalizó después a una **exclusión mutua entre PCR,
Electrochemical y los controles manuales**: solo puede correr una cosa a la
vez. `set_tabs_locked(locked, owner)` lleva un conjunto de dueños (`"pcr"`,
`"electrochem"`, `"quick"`, `"disc"`, `"led_heat"`, `"led_fluor"`, `"photo"`,
`"temp"`), y solo `"quick"` bloquea también el notebook anidado. Ver
[bloqueo_tabs_exclusion.md](bloqueo_tabs_exclusion.md).

### LEDs: línea gpiod abierta mientras el toggle está ON

A diferencia de las tabs viejas `LEDFrame` y `FluorecenseLEDFrame`, aquí el
`GPIOPin` se retiene mientras el toggle está ON y se libera al apagar
(`_toggle_led` / `_release_led`). Es seguro **porque** el bloqueo de tabs
impide que la tab vieja pida la misma línea (evita el `line busy` de libgpiod).
Si algún día se quita el bloqueo, hay que volver al patrón abrir-escribir-cerrar.
En `<Destroy>` se fuerza `write(False)+close` de ambos pines.

Las tabs viejas **no** bloquean nada, así que usan ese patrón en cada
escritura (`_set_led`: `GPIOPin` → `write` → `close` en un `finally`), también
en el "Timed On" (enciende y libera; el apagado agendado vuelve a abrir, escribir
y cerrar). Así nunca dejan la línea tomada y PCR puede pedirla aunque el LED se
haya dejado encendido: PCR lo pone en bajo al tomarlo. Si PCR la tiene, la tab
recibe el `line busy`, lo imprime y no hace nada (no interfiere con el heater).
El nivel escrito persiste tras liberar la línea (comportamiento del kernel del
Pi en el que ya se apoyaba `FluorecenseLEDFrame`). Como el LED puede quedar
encendido con la línea libre, cada tab recuerda si lo dejó encendido
(`_led_on`) y en `<Destroy>` lo apaga solo en ese caso; si no, no toca la línea
(antes `LEDFrame` llamaba `write` sobre `pin=None` y en cada cierre de la app
imprimía `Error closing heating LED GPIO`).

### Lecturas: una señal a la vez, preparado para escalar

Decisión "por ahora": los checkbuttons Temperature/Fluorescence son mutuamente
excluyentes (`_on_sig_temp`/`_on_sig_fluor`) y hay un solo eje cuyo
título/etiquetas se reescriben por señal (`_redraw`). El modelo de datos ya es
por-corrida (`self.runs`: lista de `{"signal","t","v","run","meta"}`), de modo
que escalar a dos señales simultáneas con subplots apilados sólo toca la capa
de plotting, no la adquisición.

- **Temperatura**: `UdpClient` propio en el puerto 5005 (convive con los demás
  por `SO_REUSEADDR`) + promedio móvil de 4 muestras, copiado de
  `TemperatureFrame._thermocouple_reader`. Sólo °C (el selector °C/°F vive en
  la tab Temperature Control).
- **Fluorescencia**: `Ads1115Reader` inyectado desde MainGUI o lazy-init
  (`_ensure_ads`, mismo patrón y guard dev de `PhotoreceptorFrame`), canal 0
  single-ended u 0-1 diferencial según `settings["photoreceptor"]["use_diff"]`.
- **Intervalo común** (entry, default 500 ms, mínimo 100) con cadena de
  `self.after()`.

### Keep data (retención de corridas)

Inspirado en el "Keep runs" de `EventPlotter` (ver `docs/emstat_keep_runs.md`)
pero simplificado: cada Start con "Keep data" activo apila una corrida nueva
(`R1, R2, …`) en el mismo eje. Regla acordada: **cambiar de señal limpia el
plot aunque Keep esté activo** (no se mezclan °C con V en un mismo eje); lo
implementa el chequeo `self.runs[-1]["signal"] != signal` en `start_reading`.

### Guardado CSV

Botones: Start/Stop/Clean/Save + Keep data. **Sin Load** — el análisis/carga de
CSVs queda para una futura página de análisis (fuera de alcance, decisión del
usuario). Formato: header `t_s,value,signal,run`, una fila por punto de cada
corrida retenida. Nombre: `unified_{temp|fluor}_YYYYMMDD_HHMMSS{sufijo}.csv`
donde el sufijo documenta las condiciones del experimento al momento del Start
(`_rpm700CW`, `_osc30deg10pct`, `_heatON`, `_fluorledON`), construido con el
mismo criterio que `EventPlotter._build_filename_suffix`. La metadata se captura
en `start_reading` (no en Save) para reflejar el estado real durante la corrida.

### Modo dev (Windows)

Con `environment=dev` en `.env`, `_apply_dev_mode()` deshabilita los controles
sin hardware (motor, ambos toggles de LED y el checkbox de fluorescencia) con
un aviso en el status. La **temperatura funciona completa** en dev: el
`UdpClient` es sólo un socket y recibe el broadcast real del disco si está en
la misma red. No hay simulación.

## Archivos tocados

- `ui/QuickControlFrame.py` — el frame (nuevo).
- `ui/MainGUI.py` — import, tab en índice 0 del notebook anidado (los demás se
  corren +1), y `set_tabs_locked()`.
- `templates/constants.py` — "Quick Control" al inicio de `tab_texts` y "⚡" en
  `tab_icons`.

## Pendientes conocidos

- Dos plots apilados / señales simultáneas (la estructura de `runs` ya lo
  permite).
- Página de análisis para cargar los CSV `unified_*` (decidido fuera de
  alcance en esta iteración).

__author__ = "Edisson A. Naula"
