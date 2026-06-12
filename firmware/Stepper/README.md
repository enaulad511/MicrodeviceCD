# Firmware Stepper — espejo (mirror) en el repo

Copia **de referencia** del firmware MicroPython del **Pico del stepper** (el que
genera los pulsos STEP/DIR del disco vía PIO y habla UART con la Raspberry Pi).
La fuente original vive fuera de git en `~/MicroPython/Stepper/` y es lo que
realmente se flashea a la placa.

> ⚠️ **Este directorio NO se ejecuta ni se flashea desde aquí.** Es un espejo para
> que el firmware quede versionado junto al host (`ui/`, `Drivers/`) y se pueda
> leer/diff sin salir del proyecto. **Editar aquí no cambia la placa**: hay que
> copiar a `~/MicroPython/Stepper/` y flashear. Mantener ambos en sync manualmente.

## La cadena

```
App Python (este repo) ──UART /dev/ttyAMA0 @115200──► Pico stepper ──STEP(GP17)/DIR(GP16)──► driver de pasos
   Drivers/DriverStepperSys.py                        (StepperClass_V5.py)        sensor IFR de cero en GP22
                          ◄── STAT:<pos_deg>:<rpm> cada 50 ms ──┘
```

## Inventario de archivos

| Archivo | Rol |
|---|---|
| `StepperClass_V5.py` | **Firmware actual** (flashear como `main.py`): rampa de velocidad en firmware, `STOP:0/1`, hilo de comandos a 10 ms. |
| `main_copy.py` | Snapshot de lo que estaba flasheado antes de V5 (V4 + baud 115200 + pines 17/16 + fixes de zero/sweep). |
| `StepperClass_V4.py` | Versión histórica (protocolo de 4 campos). |

## Protocolo UART (4 campos, `\n` al final)

```
MODO:0:<grados>:<_>          movimiento relativo en grados (POS)
MODO:1:<rpm>:<accel_rpm_s>   velocidad continua en RPM; accel>0 => RAMPA en firmware, 0 => inmediato
MODO:2:<hz>:<accel_hz_s>     velocidad continua en Hz; ídem
MODO:4:<grados>:<hz>         oscilación (SWEEP) ±grados a hz
MODO:6:<rpm>:<_>             homing a la marca IFR (ZERO); el signo de rpm da la dirección
VEL:<hz>:0:0                 velocidad por defecto para POS
DWELL:<ms>:0:0               pausa en extremos del SWEEP
STOP:0:0:0                   frenado EN RAMPA con la pendiente del último MODO:1/2 (inmediato si no hubo rampa)
STOP:1:0:0                   paro de emergencia inmediato
```

Telemetría: `STAT:<pos_deg>:<rpm>` cada 50 ms (la rpm reportada sigue la rampa).

Diseño completo de la rampa (por qué vive en el firmware, zona muerta del PIO,
escritura en vivo de `SMx_CLKDIV`): [docs/stepper_rampa_firmware.md](../../docs/stepper_rampa_firmware.md).

## Flashear

1. Conecta el Pico por USB y abre el REPL (Thonny / mpremote).
2. Copia `StepperClass_V5.py` a la placa como `main.py`.
3. Reinicia. El LED parpadea ~0.5 s cuando el hilo de comandos corre.

## Sincronización con el espejo

Tras editar el original y flashear, refresca este espejo:

```powershell
Copy-Item ~\MicroPython\Stepper\*.py firmware\Stepper\ -Force
```
