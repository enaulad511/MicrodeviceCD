# Exclusión mutua: PCR, Electrochemical o controles manuales

## Regla

**Solo puede correr una cosa a la vez**: una corrida de PCR, un experimento
electroquímico o los controles manuales. Comparten hardware que no admite dos
dueños: el motor (GPIO 12 + UART `/dev/ttyAMA0`), los LEDs (GPIO 24/25), el
ADS1115 y el disco/cadena EmStat. Mientras un grupo tiene algo activo, las tabs
principales de los **otros** grupos quedan deshabilitadas; la del grupo activo
sigue habilitada (desde ahí se detiene lo que corre).

| Grupo activo | PCR | Electrochemical | Manual Control |
|---|---|---|---|
| PCR corriendo | ✔ | ✖ | ✖ |
| Experimento electroquímico | ✖ | ✔ | ✖ |
| Algún control manual activo | ✖ | ✖ | ✔ |

Antes solo existía la dirección manual → resto (Quick Control y, después, la
tab Disc). PCR y Electrochemical no bloqueaban nada. Por ejemplo, con PCR
corriendo se podía arrancar un CV/SWV con agitación: su oscilador no podía
crear el driver del motor (`line busy`), y el experimento seguía **sin
agitación y sin avisar**.

## Implementación

Un único mecanismo en `MainGUI` ([ui/MainGUI.py:258](../ui/MainGUI.py#L258)),
`set_tabs_locked(locked, owner)`:

- Lleva un **conjunto de dueños** activos (`_tab_lock_owners`). Cada frame se
  registra con su propio nombre, así que el desbloqueo de uno no suelta el
  bloqueo de otro (p. ej. apagar un LED con el motor de Disc todavía girando).
- El grupo de cada dueño sale de `LOCK_OWNER_TAB`
  ([ui/MainGUI.py:88](../ui/MainGUI.py#L88)): `"pcr"` → tab 0,
  `"electrochem"` → tab 1; cualquier otro nombre es un control manual (tab 2,
  `MANUAL_CONTROL_TAB`). Una tab principal se deshabilita si hay dueños y
  ninguno pertenece a ella.
- `"quick"` además bloquea las tabs hermanas del notebook anidado, salvo la
  propia Quick Control (pedido original, ver
  [quick_control.md](quick_control.md)). Los demás dueños manuales no se
  bloquean entre sí: los controles manuales son un solo grupo.
- Cada frame recibe un `lock_tabs_callback(locked)` ya ligado a su dueño vía
  `MainGUI.lock_callback(owner)` ([ui/MainGUI.py:254](../ui/MainGUI.py#L254)).

Dueños y cuándo bloquean:

| Dueño | Frame | Bloquea | Desbloquea |
|---|---|---|---|
| `pcr` | `PCRFrame` | justo antes de arrancar el hilo del experimento ([ui/PcrFrame.py:1728](../ui/PcrFrame.py#L1728)) | `_restore_input_ui` ([ui/PcrFrame.py:2462](../ui/PcrFrame.py#L2462)): fin natural (lo detecta `_ui_poll_loop`) y Stop |
| `electrochem` | `ElectrochemicalFrame._on_run_state` | `EventPlotter.start()` ([ui/EventEmstatFrame.py:319](../ui/EventEmstatFrame.py#L319)) | `EventPlotter.stop()`, vía `after(0)` ([ui/EventEmstatFrame.py:441](../ui/EventEmstatFrame.py#L441)) |
| `quick` | `QuickControlFrame._update_lock` | motor, algún LED o lectura activa | todo apagado |
| `disc` | `ControlDiscFrame._lock_while_running` | arranca un hilo de motor | el hilo termina (sondeo `after(200)`) |
| `led_heat` / `led_fluor` | `ControleLEDFrame` / `ControlFluorescenteFrame._update_lock` | la tab deja el LED encendido (On o Timed On) | Off o fin del Timed On |
| `photo` | `PhotoreceptorFrame` | Start de la lectura | Stop |
| `temp` | `TemperatureFrame` | Start de la lectura | Stop / Clean |

Detalles que importan:

- **PCR bloquea después de leer las entradas, no al poner
  `running_experiment`.** Si un `float()` de las entradas fallara, las tabs no
  quedan bloqueadas para siempre. Desbloquea en `_restore_input_ui` porque es
  el punto que PCR ya usa para decir "terminó, se puede volver a correr" en
  ambos caminos. En el Stop, el join (hasta 3 s) y el teardown forzado ocurren
  dentro del mismo callback del hilo de UI, así que nadie puede hacer clic en
  otra tab antes de que terminen.
- **Electrochemical usa un hook nuevo, `EventPlotter.on_run_state(running)`**
  ([ui/EventEmstatFrame.py:83](../ui/EventEmstatFrame.py#L83)), con el mismo
  espíritu que `on_first_data`. Se invoca **siempre en el hilo de UI**:
  `start()` viene del botón y `stop()` puede venir del hilo procesador (los
  terminales del firmware), así que el `False` se agenda con `after(0)`. Basta
  un dueño para los cuatro métodos, porque el cambio de método ya está
  bloqueado durante una corrida
  ([electrochem_cache_frames.md](electrochem_cache_frames.md)). El hook se
  conecta al construir cada frame del cache
  ([ui/ElectrochemicalFrame.py:175](../ui/ElectrochemicalFrame.py#L175)).
- **Qué cuenta como "activo" en los controles manuales:** la misma regla que
  Quick Control, es decir, un actuador encendido o una lectura en curso. Las
  tabs LED/Fluorescence bloquean mientras **dejaron el LED encendido**, aunque
  no retengan la línea gpiod (abren → escriben → cierran).
- **Lo que no se bloquea:** el botón "Test Connection Disc" del footer (escucha
  UDP 5005 unos segundos; todos los clientes usan `SO_REUSEADDR` y conviven),
  Configuration y Analyze (no tocan hardware).

## Verificación

En Windows (modo dev) con `gpiod`/`serial` simulados y el `MainGUI` real
corriendo en `mainloop` (sin `mainloop`, Tkinter rechaza las llamadas desde
otros hilos y la prueba da falsos negativos), se comprobaron estas
transiciones: PCR (hook real), Electrochemical con `start()`/`stop()` reales
contra un servidor TCP local (incluido `stop()` desde otro hilo), LED + Disc
combinados, Temperature y Quick Control. Falta validarlo en el equipo.

__author__ = "Edisson A. Naula"
__date__ = "$ 14/10/2026 $"
