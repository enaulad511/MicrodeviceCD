# IR (MLX90614) contra termopar (MAX31855): estabilidad y desfase

Objetivo del usuario: **reemplazar el termopar por el sensor IR** como fuente del PID
(`temp_source = ir_object`, [temp_source_selector.md](temp_source_selector.md)) y saber
cuánto desfase tiene el IR. Este documento es la validación "`t_obj` contra el termopar
en régimen, en el rango de PCR" que pedía la migración.

## 1. Datos y método

Las tres corridas PCR del 21/10/2026 (`files_test/Newn1_temperature_data_20261021_*.csv`,
receta 90/50/65 °C, 35 ciclos, un **disco distinto** en cada una), con el termopar como
primario y el IR objeto como secundario.

- **Crudo recuperado:** las dos columnas del CSV son la EMA (α 0.3) de
  `update_displayed_temperature`, así que el crudo de cada sensor sale exacto con
  `raw_k = (y_k − 0.7·y_{k−1}) / 0.3`.
- **Régimen:** segunda mitad de cada *hold*.
- **Ruido:** desviación del residuo frente a un ajuste lineal en ventanas de 1 s.
- **Script:** `files_test/ajuste_21oct/ir_vs_tc.py` (gitignored; acepta más corridas).

## 2. Estabilidad: el IR es la señal más estable

| | termopar | IR objeto |
|---|:-:|:-:|
| resolución del crudo | 0.25 °C | **0.02 °C** |
| ruido en régimen (discos 1 / 2 / 3) | 0.26 / 0.15 / 0.12 °C | **0.15 / 0.09 / 0.09 °C** |
| lecturas fallidas (3 corridas, ~130 k muestras) | — | **0** |
| heater → +1 °C (discos 1 / 2 / 3) | 0.32 / 1.25 / 0.61 s | 0.61 / 0.93 / 0.64 s |
| saltos > 3 °C entre muestras, rampa a 90 del disco 2 | **98** (artefacto de contacto) | 20 |

- **Sin diafonía óptica:** en los 0.25 s tras encender el heater, el IR sube lo mismo que
  el termopar (+0.06 / +0.11 contra +0.06 / +0.09 °C, n = 56–65), o sea calentamiento
  real. Al encender el LED de fluorescencia ninguno de los dos se mueve (≤ 0.03 °C).
- **Respuesta más pareja entre discos:** el IR tarda 0.6–0.9 s en todos; el termopar va de
  0.3 a 1.25 s según dónde quedó en el disco. Para un PID es mejor un retraso que no
  dependa del disco.
- **Ojo con el giro:** cuando el disco gira (enfriamiento), el IR baja mucho más rápido
  que el termopar, porque la superficie se enfría antes que la muestra (disco 1: 39
  saltos de bajada en `cooling`). Con el IR al mando, el motor pararía antes
  (`cool_stop_margin_c` habría que reajustarlo).

## 3. Desfase IR − termopar: no es una constante

| | disco 1 | disco 2 | disco 3 |
|---|:-:|:-:|:-:|
| a 50 °C (mediana) | +2.1 | +2.0 | +1.4 |
| a 65 °C | −0.5 | +1.0 | −2.4 |
| a 90 °C | −2.2 | −0.3 | **−4.5** |
| ajuste IR = a·TC + b | 0.90·TC + 6.6 | 0.95·TC + 4.6 | 0.87·TC + 7.8 |
| deriva dentro de la corrida a 90 °C (primeros 5 → últimos 5 ciclos) | −0.7 → −0.9 | +1.2 → −0.6 | −3.4 → −4.5 |

- **Depende de la temperatura:** el IR "comprime" la escala, con pendiente 0.87–0.95.
  Lee más que el termopar a 50 °C y menos a 90 °C.
- **Depende del disco:** a 50 °C los tres coinciden en ±0.4 °C, pero a 90 °C la
  dispersión es de **4.2 °C**. Una corrección fija dejaría unos ±2 °C de error a 90 °C
  de disco a disco.
- **Deriva dentro de la corrida:** 0.5–1.8 °C, del mismo orden que el desplazamiento
  milimétrico del heater o los cambios de la muestra.
- **Una emisividad mal puesta** (ε = 0.96 es un valor genérico,
  [mlx90614_emisividad.md](mlx90614_emisividad.md)) produce un error que crece con la
  temperatura, compatible con la pendiente < 1. No explica por sí sola que el IR lea
  **más** a 50 °C, así que hay algo más: la posición del termopar o lo que ve el IR
  alrededor de la muestra.

**Lo que no se puede saber con estos datos:** cuál de los dos refleja la temperatura de
la **muestra**. Los dos dependen del disco (el termopar, de su posición; el IR, de la
superficie que ve). Sin una tercera referencia, el desfase no se puede atribuir.

## 4. Para reemplazar el termopar

**Plan acordado (usuario, 21/10/2026).** Una sonda calibrada en la muestra no es práctica
porque el disco gira. La referencia será el **termopar de un experimento con resultado
positivo** (amplificación) controlado por termopar: ese perfil es el que funciona, y el
reemplazo debe reproducirlo leyendo el IR. Orden:

1. **Conseguir un experimento positivo** con el control en el termopar (IR como
   secundario, como hoy).
2. Con esa corrida y las siguientes, **ajustar la correspondencia IR → termopar**
   (`TC ≈ (IR − b) / a`, §3) y medir cuánto varía entre discos. La tolerancia que admite
   el experimento dirá si los ±2 °C a 90 °C entre discos son aceptables o si hace falta
   corregir por disco.
3. **Registrar `t_amb`** (temperatura del propio MLX) como columna extra del CSV: ayudaría
   a explicar la deriva dentro de la corrida. Hoy no se guarda.
4. **Corrección en el código** (opción en `settings.json`, aplicada a `ir_object` antes
   del PID) y corridas de prueba con `temp_source = ir_object`, dejando el termopar de
   secundario para comparar.
5. Reajustar el margen de enfriamiento con el IR al mando (§2, giro).

__author__ = "Edisson A. Naula"
__date__ = "$ 21/10/2026 $"
