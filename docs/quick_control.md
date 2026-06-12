# Quick Control: tab unificada del control manual

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

### Bloqueo de tabs mientras hay algo activo

Pedido explícito del usuario: mientras Quick Control opere **cualquier** cosa
(motor girando, algún LED ON, o lectura corriendo), el cambio de tab se
deshabilita — en **ambos** notebooks, porque PCR y Electrochemical también usan
el motor/UDP. Implementación:

- `QuickControlFrame._update_lock()` calcula el estado y llama a
  `lock_tabs_callback(locked)`.
- `MainGUI.set_tabs_locked()` pone `state="disabled"` en todas las tabs del
  notebook principal salvo Manual Control (índice 2) y en todas las del
  notebook anidado salvo Quick Control (índice 0).
- El desbloqueo es automático al quedar todo apagado/detenido; un label 🔒 en
  el frame indica qué lo mantiene bloqueado.

### LEDs: línea gpiod abierta mientras el toggle está ON

A diferencia de `FluorecenseLEDFrame` (abre→write→close inmediato), aquí el
`GPIOPin` se retiene mientras el toggle está ON y se libera al apagar
(`_toggle_led` / `_release_led`). Es seguro **porque** el bloqueo de tabs
impide que la tab vieja pida la misma línea (evita el `line busy` de libgpiod).
Si algún día se quita el bloqueo, hay que volver al patrón abrir-escribir-cerrar.
En `<Destroy>` se fuerza `write(False)+close` de ambos pines.

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
