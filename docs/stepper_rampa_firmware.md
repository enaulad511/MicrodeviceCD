# Stepper: rampa de velocidad en firmware y centralización de `spinMotorRPM_ramped`

## Problema

El giro continuo del disco (`spinMotorRPM_ramped`) aceleraba en rampa pero **el
frenado era de golpe** (o la rampa de bajada se cortaba a medias). Tres causas
encadenadas:

1. **Firmware (V4 / `main_copy.py`)**: el hilo de comandos del Pico procesaba
   **1 línea cada 0.5 s** (`commands_thread` con `time.sleep(0.5)` y un solo
   `uart.readline()` por iteración). La rampa host-side mandaba ~10 comandos/s
   (ts=0.1): el buffer RX se desbordaba, se corrompían/perdían líneas y el
   `STOP` o los pasos de bajada llegaban tarde o nunca.
2. **Host (`Drivers/DriverStepperSys.py`)**: `_reader_loop` hacía
   `reset_input_buffer()` antes de **cada** `readline()` (descartaba casi toda
   la telemetría `STAT` → `get_status()` rancio) y `run_rpm` hacía
   `reset_output_buffer()` (descartaba comandos de rampa aún no transmitidos).
3. **Host (vieja rampa en `ui/DiscFrame.py`)**: la rampa de bajada no dormía
   `ts` entre pasos; esperaba telemetría con una condición que en CCW
   (`cur` negativo) rompía de inmediato → ráfaga de comandos.

Se intentó previamente arreglar la rampa **en el host**, pero cualquier
problema de conexión UART dejaba el frenado a medias (decisión del usuario:
la rampa debe vivir en el firmware, donde un solo comando basta).

## Diseño

### Rampa en el firmware (`StepperClass_V5.py`)

El protocolo de 4 campos no cambia de forma; se aprovecha el tercer valor
(antes siempre 0) para llevar la pendiente:

```
MODO:1:<rpm>:<accel_rpm_s>   accel > 0 => rampa en firmware; 0 => inmediato (legado)
MODO:2:<hz>:<accel_hz_s>     ídem para Hz
STOP:0:0:0                   frenado EN RAMPA con la pendiente del último MODO:1/2
                             (inmediato si no hubo rampa) — es lo que ya manda drv.stop()
STOP:1:0:0                   paro de emergencia inmediato (drv.stop_hard())
```

Puntos clave del firmware:

- **Slew en `update()`**: `_ramp_cur_hz` (Hz con signo) se integra hacia
  `_ramp_target_hz` a `_ramp_accel_hz_s` por segundo en cada vuelta del lazo
  principal (~300 µs). Cambios de dirección pasan por 0 de forma natural
  (desacelera, voltea DIR, acelera).
- **Cambio de frecuencia EN VIVO sin recrear la StateMachine**:
  `_write_clkdiv()` escribe el registro `SMx_CLKDIV` del PIO
  (`machine.mem32`, INT[31:16].FRAC[15:8]) mientras la SM sigue corriendo el
  lazo continuo. Recrear la SM por paso de rampa (lo que hacía
  `_set_sm_freq` vía `AttributeError`) pausaba los pulsos en cada paso.
- **Zona muerta**: el divisor del PIO tope (65536) limita la frecuencia mínima
  a `sysclk/(2*65536)` (~954 Hz a 125 MHz ≈ **9 RPM** con 6400 pasos/rev).
  Bajo ese umbral la SM se pausa y la rampa sigue integrando (para el cruce de
  0 en cambios de dirección). En la práctica el frenado pasa de ~9 RPM a 0 de
  golpe — imperceptible.
- **Arranques deterministas**: `_start_continuous`/`_start_n_pulses` siempre
  recrean la SM (`_init_sm`) antes de `put()`. Re-activar una SM pausada
  retoma el lazo `cont` sin hacer `pull`, y los `put` repetidos acabarían
  llenando (y **bloqueando**) el TX FIFO — con eso se colgaría el hilo de
  comandos.
- **Hilo de comandos a 10 ms con buffer de líneas**: `handle_commands` drena
  todo lo pendiente del UART a un buffer y procesa cada línea completa
  (`_process_command`). Cualquier comando de movimiento/STOP inmediato
  **cancela la rampa activa** (`_ramp_cancel`).
- La telemetría `STAT:<pos>:<rpm>` (50 ms) reporta la rpm **rampada**, no el
  setpoint.

### Host: `spinMotorRPM_ramped` centralizado

La función vive ahora en
[Drivers/DriverStepperSys.py](../Drivers/DriverStepperSys.py) (antes en
`ui/DiscFrame.py`) y quedó reducida a orquestación:

1. `drv.run_rpm(target, accel_rpm_s)` — **un** comando; el Pico hace la rampa.
2. Espera `stop_event` / `stop_func` / `time_exp` sondeando cada `ts`.
3. `drv.stop()` (STOP:0, frenado en rampa) y duerme `|rpm|/accel + 0.5 s` —
   espera **por tiempo, no por telemetría** (cota superior de la
   desaceleración). Con `soft_stop=False` manda `drv.stop_hard()`.
4. `drv.go_zero(50)` y espera quieto por telemetría con timeout de 15 s (el
   homing del firmware expira solo a los 5 s).

`accel_rpm_s` ahora son **RPM/s reales** (antes era "RPM por iteración", que
con ts=0.1 pedía 10× más pendiente de la configurada; el ritmo que se veía en
hardware era un artefacto del cuello de botella del firmware). La pendiente se
configura en `resources/settings.json` → `acceleration_spin` (RPM/s); si tras
flashear V5 la rampa se siente lenta/rápida, ajustar ahí, no en código.

Firma intacta (mismos 10 parámetros posicionales), así que los callers solo
cambiaron el import:

- [ui/DiscFrame.py](../ui/DiscFrame.py) `callback_spin` — import lazy
  `from Drivers.DriverStepperSys import DriverStepperSys, spinMotorRPM_ramped`.
- [ui/PcrFrame.py](../ui/PcrFrame.py) `_run_cycle` y `experiment_pcr` — ídem
  (se quitó el import a nivel de módulo `from ui.DiscFrame import …`).
- [ui/QuickControlFrame.py](../ui/QuickControlFrame.py)
  `callback_motor_start` — usa la función del driver en vez de
  `disc.spinMotorRPM_ramped` (los globales `drv`/`thread_motor`/`thread_lock`
  siguen siendo de `ui.DiscFrame`, ver
  [quick_control.md](quick_control.md)).

El import es **lazy dentro de cada callback** porque
`Drivers/DriverStepperSys.py` importa `gpiod`/`serial` a nivel de módulo y un
import top-level rompería el modo dev en Windows.

Limpiezas en el driver: `_reader_loop` ya no hace `reset_input_buffer()` (la
telemetría ahora sí actualiza `_last_status`) y `run_rpm` ya no hace
`reset_output_buffer()`. Nuevo `stop_hard()` para el paro inmediato.

## Archivos del firmware

- Original (lo que se flashea): `~/MicroPython/Stepper/StepperClass_V5.py` →
  copiar a la placa como `main.py`. `main_copy.py` es el snapshot de lo que
  estaba flasheado antes (V4 + baud 115200 + pines 17/16).
- Espejo versionado en el repo: [firmware/Stepper/](../firmware/Stepper/)
  (README con el protocolo y el comando de resync).

## Compatibilidad

- Firmware V5 con host viejo: `MODO:1:<rpm>:0` ⇒ cambio inmediato (legado);
  `STOP:0` sin rampa previa ⇒ paro inmediato. Nada cambia.
- Host nuevo con firmware viejo (V4/main_copy): el campo accel se ignora en la
  práctica (V4 no lo usa para RPM) ⇒ el setpoint se aplica de golpe y el STOP
  es inmediato. Funciona, pero **sin rampas** — flashear V5 para el
  comportamiento completo.

__author__ = "Edisson A. Naula"
