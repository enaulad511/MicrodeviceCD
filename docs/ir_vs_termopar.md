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
3. **Registrar `t_amb`** (temperatura del propio MLX) como columna extra: ayudaría a explicar
   la deriva dentro de la corrida. **Hecho el 04/11/2026** (columna 6,
   [pcr_csv_ciclo_fase.md](pcr_csv_ciclo_fase.md) §7).
4. **Corrección en el código** (opción en `settings.json`, aplicada a `ir_object` antes
   del PID) y corridas de prueba con `temp_source = ir_object`, dejando el termopar de
   secundario para comparar.
5. Reajustar el margen de enfriamiento con el IR al mando (§2, giro).

## 5. Dos cámaras más (26/10/2026, receta 85/50/62 °C, control adaptativo)

Corridas `files_test/Newn2_pcr_data_20261026_182410.xlsx` (A) y `…_192302.xlsx` (B),
con el termopar al mando ([pcr_control_adaptativo.md](pcr_control_adaptativo.md) §6).
**Son el mismo disco en dos cámaras distintas** (usuario). `ir_vs_tc.py` ahora toma los
setpoints de la metadata.

| | cámara A | cámara B |
|---|:-:|:-:|
| IR − TC a 50 °C | +1.35 | +1.28 |
| IR − TC a 62 °C | −1.11 | +0.16 |
| IR − TC a 85 °C (primeros 5 → últimos 5 ciclos) | **−3.47** (−3.3 → −3.9) | −0.44 (−0.1 → −0.6) |
| ajuste IR = a·TC + b | 0.868·TC + 7.71 | 0.952·TC + 3.51 |
| ruido en régimen, TC / IR (°C) | 0.135 / 0.080 | 0.118 / 0.082 |
| saltos > 3 °C entre muestras, TC / IR | **60** / 5 | 5 / 4 |

- **Confirma el §3:** a 50 °C las cinco corridas coinciden (+1.3 a +2.1), y a 85–90 °C
  se separan (de −4.5 a −0.3). La recta de A es casi la del disco 3 del 21/10
  (0.868·TC + 7.77), pero el disco 3 casi no tenía saltos: el desfase y los saltos no van
  juntos.
- **El desfase es por cámara, no por disco.** En el mismo disco, a 85 °C, A da −3.5 y B
  −0.4: tanta dispersión como entre discos distintos. Si el PID pasa al IR, la
  corrección del §4 tendría que ser por cámara (o aprenderse en cada corrida), no por
  disco.
- **Saltos del termopar por encima de ~70 °C:** en A, 19 de 34 rampas a high suben más de
  20 °C/s (el heater llega a ~10 °C/s), y el IR nunca lo hace. Medido contra el nivel
  del *hold*, el pico del IR es ~1/3 del del termopar. Para cortar una rampa, el IR es
  la señal más fiable de las dos. Detalle y efecto sobre el control:
  [pcr_control_adaptativo.md](pcr_control_adaptativo.md) §7.2.

## 6. Newn3 (02/11/2026): el desfase cambia dentro de la corrida

Misma receta 85/50/62, con el termopar al mando (`Newn3_pcr_data_20261102_152624.xlsx`).

| ciclos | IR − TC a 85 °C (mediana) | rango | IR − TC a 50 °C |
|:-:|:-:|:-:|:-:|
| 2–8 | **−5.0** | −5.5 a −2.7 | +1.5 |
| 9–16 | +0.6 | **−2.6 a +2.3** | +1.6 |
| 17–35 | **+1.1** | −0.5 a +2.4 | +1.4 |

- **Hasta ahora el desfase se trataba como fijo por cámara (§5). Aquí se mueve ~6 °C en la
  misma corrida**, con un cambio brusco entre los ciclos 8 y 9 (de −3.0 a +2.3). Una
  corrección de una sola vez al arrancar no serviría: si el PID pasa al IR, la calibración
  del §4 tendría que seguir ese cambio, o no aplica a corridas como esta.
- **Con el termopar al mando, cuál de los dos se movió no se sabe.** Si el IR refleja la
  muestra, "85 °C" fue ~79–80 °C en los primeros ciclos y ~86–88 °C al final. Es relevante
  para el experimento, aunque el control se vea bien.
- **A 50 °C no se mueve.** El problema es a temperatura alta, como en el §3.

Contexto de la corrida: [pcr_control_adaptativo.md](pcr_control_adaptativo.md) §10.2.

## 7. Newn4 (04/11/2026): el IR no siempre lee menos, y también salta

Receta 85/40/62, termopar al mando, corridas R1 y R2
([pcr_control_adaptativo.md](pcr_control_adaptativo.md) §12). Dos cámaras distintas (usuario).

| | R1 | R2 |
|---|:-:|:-:|
| IR − TC a 40 °C | +0.49 | +2.62 |
| IR − TC a 62 °C | −2.68 | **+3.74** |
| IR − TC a 85 °C (primeros 5 → últimos 5 ciclos) | −3.42 (−3.21 → −3.81) | **+5.74** (+3.42 → +5.71) |
| ajuste IR = a·TC + b | 0.910·TC + 3.72 | **1.061·TC + 0.38** |
| IR − TC en la rampa, con TC ≈ 66 °C | −2.8 | **+5.9** (+3.8 a +9.5) |
| saltos > 3 °C entre muestras, TC / IR | 1 / 1 | **50 / 12** |

- **La regla del §3 no es general.** "El IR comprime la escala y lee menos a temperatura alta" falla
  en R2: la pendiente pasa de 1 y lee más que el termopar a todas las temperaturas.
- **Dispersión a 85 °C: 9 °C** entre dos cámaras, el mismo día. Con el termopar en 85 °C, el IR leyó
  ~81.6 °C en R1 y ~90.7 °C en R2. Sigue sin saberse cuál refleja la muestra, y una corrección fija al
  migrar el PID al IR no serviría.
- **El IR también salta.** En los eventos de calor salta 7–9 °C de mediana, contra 10–15 °C del
  termopar, así que "el IR no salta" (§5) era por comparar tasas, no eventos.

## 8. ¿Ruido inducido en los cables? (04/11/2026)

**Duda del usuario:** los cables del IR pueden recoger ruido, así que su medición no es tan válida. Por
eso **su nivel no se usa como evidencia** de la temperatura de la muestra
([pcr_control_adaptativo.md](pcr_control_adaptativo.md) §12.6).

**Lo que se buscó** en los crudos de A, B, Newn3, R1 y R2 (`files_test/ajuste_21oct/an_ir_ruido*.py`).
B queda fuera de las dos últimas filas, porque su tasa normal ya pasa el umbral:

| prueba | qué dejaría el ruido | IR | termopar |
|---|---|:-:|:-:|
| ruido en *holds* sin eventos, std (°C) | más con heater encendido | 0.07–0.09, con y sin heater | 0.10–0.15 |
| ruido con el motor girando, std (°C) | mucho más | 0.10–0.13 | 0.14–0.17 |
| picos aislados > 1 °C, por 1000 muestras | muchos | 0.02–0.03 (R2 0.15) | 0.08–1.1 |
| salto en 0.25 s al encender el heater (°C) | instantáneo | +0.02 a +0.07 | +0.03 a +0.11 |
| salto al apagar el heater (°C) | instantáneo | −0.01 a +0.03 | −0.04 a +0.03 |
| salto al arrancar el motor (°C) | instantáneo | −0.06 a +0.06 | −0.04 a +0.07 |
| subidas / bajadas rápidas sin motor | simétricas | A 32 / 0, R2 29 / 2 | A 35 / 14, R2 42 / 1 |
| saltos solo de este sensor | muchos | A 3 de 32, R2 3 de 29 | A 5 de 35, R2 16 de 42 |

**No aparece la firma de ruido inducido en el IR.** No lo descarta, y hay dos cosas a favor de la duda:

- **Nadie valida la lectura.** `read16` lee 2 bytes y **no comprueba el PEC**
  ([mlx90614.py:45](../firmware/DiscPCB/mlx90614.py#L45)), así que un bit cambiado solo se detecta si
  es el 15. Además, el bus ya mostró EMI del motor ([mlx90614_fiabilidad_lectura.md](mlx90614_fiabilidad_lectura.md)).
- **El nivel no es estable,** aunque no por lo que deja el ruido. El desfase IR − TC cambia en
  escalones **con cada parada del motor** y se mantiene hasta la siguiente: misma parada contra otra,
  R1 +0.91 / +0.10 y Newn3 +0.89 / +0.26 (R2 +0.48 / +0.27, B +0.49 / +0.36, A +0.07 / +0.51). En R1,
  c25 y c29 quedan en −6.6 y −6.3 °C contra ~−3.3 normal, y no se va al apagar el heater (−6.1 en el
  primer segundo de `cooling`).

Dos razones por las que ese escalón no parece inducción, sin poder descartarla: el MLX convierte
dentro del encapsulado y por los cables van palabras digitales, y un error de bits no da un desfase
constante durante minutos. Quedan el ángulo del disco, lo que ve el sensor, un gradiente térmico sobre
el encapsulado o, si el cable se mueve con el disco, su posición. **Es deducción.**

**Si hay inducción, el termopar es más sospechoso:** lleva una señal de µV por el cable, y en la tabla
tiene más picos y más saltos propios.

**Pruebas que lo resolverían:**

1. **PEC en la lectura, con un contador de fallos** (firmware: leer 3 bytes y verificar): mide
   directamente si llegan palabras corruptas.
2. **Mirar `t_amb`:** se guarda desde el 04/11/2026 ([pcr_csv_ciclo_fase.md](pcr_csv_ciclo_fase.md)
   §7). Es la temperatura del encapsulado, así que solo da indicios: si cambia de golpe con el desfase,
   apunta a un efecto térmico sobre el sensor; si el desfase salta y `t_amb` no se mueve, no. No mide
   el gradiente directamente.
3. **Disco frío, Quick Control con "All (3 temps)":** alternar heater y motor. Un cambio instantáneo es
   eléctrico; uno lento, térmico.

**Para la migración del PID (§4):** conviene cerrar esto antes.

__author__ = "Edisson A. Naula"
__date__ = "$ 04/11/2026 $"
