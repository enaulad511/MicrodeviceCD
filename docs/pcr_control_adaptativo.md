# Control adaptativo de PCR (opcional)

Archivo: [ui/PcrFrame.py](../ui/PcrFrame.py) (`_ramp_adaptive`, `_hold_adaptive`,
`_adaptive_cfg`). Config: `settings.json` → `pcr_adaptive`. **Apagado por defecto.**

## 1. Por qué

Cada experimento usa un **disco nuevo** y la respuesta térmica cambia mucho de uno a otro
([pcr_ajuste_ganancias.md](pcr_ajuste_ganancias.md) §7, tres discos el 21/10/2026):

- **Constante entre discos:** la potencia para *sostener* una temperatura es del
  instrumento: duty ≈ 0.20–0.21 a 90 °C y 0.03–0.05 a 50 °C, estable de un ciclo a otro.
- **Variable entre discos:** el **calor en vuelo**, cuánto sigue subiendo la temperatura
  tras apagar el heater (2.7–8.2 °C en la rampa a ext), con el termopar respondiendo en
  0.3–1.25 s según el disco.

El control clásico (rampa a potencia plena + PI con integral que satura en < 1 s) se pasa
según el disco (+2.7 a +9.2 °C en ext) y deja los *holds* calientes en un ciclo límite de
±2 °C. Ninguna ganancia fija sirvió para todos los discos. El adaptativo **aprende el
disco durante la corrida**.

## 2. Cómo funciona

**Rampa** (`denat_ramp`, `high_ramp`, `ext_ramp`):

1. **Potencia plena** hasta `setpoint − coast`, con el mismo descarte de lectura vieja
   que el blast clásico. La temperatura se **extrapola entre ráfagas**: con lecturas cada
   ~0.27 s y ~10 °C/s, sin extrapolar el corte llegaba una ráfaga (~3 °C) tarde.
2. **Inercia:** solo el *feed-forward* del *hold* siguiente mientras dure la subida
   rápida. Apagar del todo haría caer la temperatura tras el pico. Termina cuando la
   temperatura baja 0.15 °C de su máximo, cuando la subida cae de 0.8 °C/s (ya sube solo
   por el *feed-forward*) o a `coast_window_s`. El resto del acercamiento lo hace el
   *hold*.
3. **Aprende** (solo si hubo ≥ 1 s de potencia plena):
   `coast += coast_learn · (máximo de la subida rápida − setpoint)`. Pasarse adelanta el
   corte y quedarse corto lo atrasa. Hay un `coast` por rampa (high y ext difieren mucho
   en el mismo disco); el de `denat` sirve de punto de partida para `high`.

`break_if_below` se respeta igual que en el clásico, y la salvaguarda de tiempo
([pcr_timeout_fases.md](pcr_timeout_fases.md)) cubre la rampa completa, inercia incluida.

**Hold** (`h_denat`, `h_high`, `h_low`, `h_ext`, también la extensión final):

- **Potencia** = *feed-forward* + PI suave (`hold_kp/ki/imax`, con el mismo escalado de
  `_fuzzy_gains`). Dentro de `hold_tband` se mantiene *feed-forward* + I: el clásico
  fuerza 0.
- ***Feed-forward*:** el duty aprendido para ese *hold* en esta corrida o, mientras no
  hay, el modelo `ff_slope · (setpoint − ff_t0)` (0.21 a 90 °C, 0.04 a 50 °C, 0.11 a
  65 °C).
- **Aprende** el duty medido por `heater_on_s` en la segunda mitad del *hold*, con peso
  `ff_learn`, solo si duró ≥ 2 s y el error medio fue ≤ 0.75 °C. Un *hold* pasado de
  temperatura mide 0, y eso no es el duty de régimen.

Todo lo aprendido se reinicia en cada corrida: el disco cambia.

## 3. Configuración (`settings.json` → `pcr_adaptive`)

`main.py` lo siembra al arrancar (`seed_default_settings`) con `enabled 0`. Se activa
poniendo `enabled` en 1 (ConfigFrame) y se lee **una vez por corrida**. Un valor no
numérico o negativo cae a su default.

| clave | default | significado |
|-------|:-:|-------------|
| `enabled` | 0 | 1 = adaptativo; 0 = control clásico **intacto** |
| `ff_slope`, `ff_t0` | 0.0043, 40 | duty inicial = ff_slope × (setpoint − ff_t0) |
| `ff_learn` | 0.5 | peso del duty medido en cada *hold* (0 = no aprende) |
| `hold_kp`, `hold_ki`, `hold_imax` | 0.1, 0.03, 3 | PI suave sobre el *feed-forward* (techo del I ≈ ±0.12) |
| `hold_tband`, `hold_win` | 0.05, 0.05 | banda (sin P) y ventana de PWM (s) |
| `coast_init` | 4 °C | calor en vuelo supuesto antes de medir (discos: 2.7–8.2) |
| `coast_learn` | 0.5 | ganancia: coast += coast_learn·(pico − setpoint) |
| `coast_min`, `coast_max` | 0.5, 12 °C | límites del corte |
| `coast_window_s` | 8 s | espera máxima de la inercia |

## 4. Qué queda registrado

- **Consola,** en cada rampa y en cada *hold*:
  `Adaptive ext ramp: cut at 56.9 °C (coast 7.1), peak 64.9 °C → coast 7.0 °C` y
  `Adaptive h_high: duty 0.202 (mean err −0.03 °C) → bias 0.203` (o `not learned`).
- **Metadata del CSV de temperatura:** `-adaptive: off`, o la config y lo aprendido al
  final (`| bias h_high 0.212 … | coast ext 7.0 high 7.1`).
- **Columnas** `phase` y `heater_on_s`: con ellas se reconstruye cada corte y cada duty.

## 5. Verificación (sin equipo)

`files_test/ajuste_21oct/test_adaptive.py` corre el **código real** de
`_reach_phase`/`_hold_phase` en **tiempo virtual**: sustituye el `time` que ve
`ui.PcrFrame` por un reloj que avanza un disco simulado (con pérdidas al ambiente, duty de
régimen 0.21 a 90 °C) y entrega lecturas en ráfagas de 4 cuantizadas a 0.25 °C. Doce
ciclos en segundos.

Ciclos 4–12, fracción del *hold* dentro de ±0.5 °C y sobreimpulso:

| disco simulado | clásico | adaptativo |
|---|:-:|:-:|
| rápido: high / low / ext | 0.14 / 0.48 / 0.24, +5.3 / +6.2 °C | **0.88 / 0.89 / 0.64, +0.7 / +0.9 °C** |
| lento: high / low / ext | 0.10 / 0.41 / 0.29, +7.2 / +7.6 °C | 0.28 / 0.61 / 0.57, **+1.5 / +0.7 °C** |

Desde el tercer ciclo los picos caen en 90.0 ± 0.2 °C y 65.0 ± 0.5 °C, y el corte converge
sin saturar. Los discos simulados **no** son el equipo: sirven para comprobar que el
código aprende, no se cuelga (0 timeouts) y no toca el clásico, no para predecir números.

**Dos fallos de diseño detectados en simulación y corregidos:**

1. Aprender `coast` como "pico − corte", o del pico completo, lo dejaba clavado en
   `coast_max`. Con el *feed-forward* encendido la temperatura sigue subiendo despacio
   hasta el setpoint, así que un corte demasiado temprano también "acertaba".
2. Sin extrapolar entre ráfagas, el corte llegaba ~3 °C tarde.

**Pendiente:** el *hold* de 90 °C del disco lento sigue oscilando en simulación
(std 0.9 °C). Cambiar `hold_kp/ki` no mejoró a la vez los dos discos simulados.

## 6. Validación en el equipo (pendiente)

1. Correr con `enabled 1` en un disco y, si se puede, con `enabled 0` en uno comparable.
   Comparar con `files_test/ajuste_21oct/fingerprint.py`.
2. Revisar en consola que los picos caigan en ±1 °C del setpoint a partir del 3er–4º
   ciclo, y que `bias` converja a ~0.20 en `h_high`.
3. Sin timeouts. Si una rampa se queda corta varias veces, el *hold* lo compensa; revisar
   que `coast` baje.
4. Ajustar `hold_kp/ki/imax` con los datos reales si el *hold* de 90 °C sigue oscilando.

__author__ = "Edisson A. Naula"
__date__ = "$ 21/10/2026 $"
