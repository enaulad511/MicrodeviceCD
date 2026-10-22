# Ajuste de ganancias PCR con la corrida del 21/10/2026

Corrida `Newn1_temperature_data_20261021_143105.csv`: 35 ciclos, high 90 °C × 15 s, low
50 °C × 15 s, ext 65 °C × 6 s, denat 90 °C × 120 s, ext final 120 s, 800 rpm, termopar,
**disco con muestra** (a potencia plena calienta ~9–11 °C/s en el termopar; los ~4–6 °C/s
"con muestra" de las corridas del paper son de otro montaje).
Código del Pi = HEAD de esa fecha: margen de enfriamiento fijo en +9.5 °C, CSV sin
`heater_on_s`. El usuario editó ganancias en el ConfigFrame hasta el **ciclo ~15**, así que
solo los **ciclos 16–35** corresponden al `settings.json` del equipo (respaldo en
`files_test/settings_device_20261021.json`, gitignored). Prioridad del usuario: **llegar a
las temperaturas**; el tiempo de la corrida se optimiza después.

Scripts y figuras del análisis: `files_test/ajuste_21oct/` (gitignored; se corren desde la
raíz del repo).

## 1. Lo que muestran los datos (ciclos 16–35)

| fase | dentro de ±0.5 °C | media − sp | std (tras 5 s) | periodo | máximo − sp |
|------|:-:|:-:|:-:|:-:|:-:|
| `high_hold` 90 °C | **21 %** | −0.39 | 1.36 | 2.7 s | +3.6 (hasta +9.4) |
| `ext_hold` 65 °C (6 s) | 24 % | +0.57 | 1.13 | — | +2.4 |
| `low_hold` 50 °C | **86 %** | +0.09 | 0.37 | — | −0.55 (mínimo) |
| `denat_hold` 90 °C (120 s) | — | +0.45 → +1.12 | 1.26 → 1.87, **crece** | 1.5–2.1 s | +6.1 |
| `final_ext` 65 °C (120 s) | — | +0.5 | 1.1 | 3.5 s | +3.5 |

- Los *holds* calientes (90 y 65 °C) están en una **oscilación sostenida** de ±2 °C, no
  en un transitorio que se apaga. El de 50 °C es estable porque ahí el heater casi no
  actúa (duty ~1 %).
- Las rampas se pasan del setpoint: a ~10 °C/s, cada ráfaga UDP de 3–4 muestras mueve la
  lectura ~3 °C. La banda de ±0.5 se salta, así que la rampa suele salir **de bajada**
  después del sobreimpulso (ext: 50 → 68 → sale en 65.3).
- Enfriamiento: el motor baja a 59.5 °C en ~15 s; de ahí a 50.5 °C el disco cae **en
  pasivo** a ~0.35 °C/s y tarda **26 s** (21–48 s), porque el cuerpo del disco está a
  ~50 °C. Es casi la mitad del ciclo (86 s). Con el margen configurable de 5.5 °C
  ([pcr_temperature_control.md](pcr_temperature_control.md)) el motor para 5 °C por
  encima del objetivo: sin riesgo de *undershoot*.
- Validaciones de [pcr_pendientes.md](pcr_pendientes.md) §7 que cierra esta corrida:
  `dt_mean 0.081 s`, `fresh eff 0.352 s`, sin timeouts, `ext_ramp` en el ciclo 1, ETA
  inicial +3 % (3330 s contra 3222 s reales).

**El CSV no guarda el termopar crudo.** La columna 0 es la EMA (α = 0.3) que ve el PID
(`update_displayed_temperature`). El crudo se recupera exacto:
`raw_k = (y_k − 0.7·y_{k−1}) / 0.3`; el 100 % de los valores recuperados son múltiplos de
0.25 °C (resolución del MAX31855). Los picos reales son algo mayores que los del CSV.

## 2. Mecanismo

**Holds: el integrador es un relé con retardo.** En el código, `integral += e × WINDOW`
en cada vuelta de duración WINDOW, o sea `d(integral)/dt = e` (°C·s). Con `imax = 0.5`, un
error de 1–2 °C lo satura en **0.25–0.5 s**, y el término I queda en ±`ki × imax` ≈
**±0.25–0.33** de potencia: cambia de signo poco después que el error. Eso es un relé con
retardo, y un relé en un lazo con retraso (ráfagas de ~0.27 s + EMA + la planta) oscila
sin remedio. Además ese techo es igual o menor que el **duty de régimen a 90 °C**
(~0.2–0.26, estimado con el balance térmico y con la potencia reconstruida), así que el
P tiene que aportar el resto con error: la media queda ~0.4 °C abajo.

Bajar KP/KI a mano, que fue lo que se probó en los ciclos 1–15, no lo arregla: el
problema es el **techo** (`imax`) y la **velocidad** (`KI`) del integrador, no el P.

**Rampas: el integrador empuja a fondo hasta el setpoint.** Con `KI_high 1.9` (y
`KI_denat 1.9`), cerca del setpoint el término I solo vale 1.9 × 0.5 ≈ 1.0: potencia plena
hasta llegar, y con ~0.3 s de retraso a ~10 °C/s el resultado es +2–4 °C.

## 3. Modelo y método

1. **Planta de dos nodos + retardo de sensor:** `T' = a·u(t−L) − b·(T − Td)` y
   `Td' = k2·(T − Td)` (membrana acoplada a un cuerpo que se calienta). Medición: muestras
   cada 82 ms cuantizadas a 0.25 °C, entregadas en ráfagas de 4, y EMA α 0.3. Controlador
   réplica de `_reach_temperature_pi`/`hold_temperature`: fuzzy, clamp, banda, frescura,
   PWM promediado por ventana.
2. **Calibración en lazo cerrado:** con las ganancias del equipo, el modelo debe
   reproducir período, std, media y sobreimpulso del *hold* de 90 °C, el sobreimpulso y
   el *hold* de 65 °C, y la duración de las rampas. Un ajuste en lazo abierto deriva (la
   planta es casi un integrador), así que no sirve.
3. **Ensamble:** los 8 mejores modelos (a 11.5–16 °C/s por unidad de potencia, b
   0.07–0.15 /s, sin retardo extra más allá de ráfagas + EMA). Como la corrida es con
   muestra, **el ensamble calibrado ya es el disco con muestra**. Se le suman sus
   versiones con **a × 0.6** (~6 °C/s: más volumen o peor contacto) como margen. Se
   eligen valores que mejoren el **peor caso** de los 16, con rampas acotadas (≤ 10 s;
   denat ≤ 25 s). Aparte se revisó una planta **a × 1.4** (p. ej. membrana seca).

Fidelidad: el ensamble reproduce el período (2.6–3.1 contra 2.7 s) y la media (−0.31
contra −0.39), pero es **optimista en amplitud**: std 0.95 contra 1.36 y 32 % contra 21 %
dentro de ±0.5. Las mejoras predichas valen como **relativas**; en el equipo los valores
absolutos serán algo peores.

## 4. Valores propuestos con la corrida 1 — **NO desplegar** (ver §7)

Buenos para la planta de la corrida 1, pero la corrida 2 mostró una planta mucho más lenta
en la que **empeoran** el *hold* de 90 °C. `resources/settings.json` se restauró a la
versión del equipo; la tabla queda como referencia.

| clave | equipo 21/10 | nuevo | por qué |
|-------|:-:|:-:|---------|
| `KP_high` / `KI_high` | 0.9 / 1.9 | **0.3 / 0.5** | frenar antes; el I ya no sostiene potencia plena hasta el setpoint |
| `KP_h_high` / `KI_h_high` / `imax_h_high` | 0.1 / 0.5 / 0.5 | **0.25 / 0.1 / 5** | integrador lento con techo (0.5–0.65) por encima del duty de régimen; más P para amortiguar |
| `KP_denat` / `KI_denat` / `ff_frac_denat` | 1.9 / 1.9 / 0.8 | **0.5 / 0.5 / 0.75** | mismo motivo que high |
| `*_h_denat` (KP/KI/imax/tband/win) | 0.5 / 0.3 / 0.55 / 0.05 / 0.09 | **0.25 / 0.1 / 5 / 0.02 / 0.05** | mismo setpoint que `h_high` → mismo juego |
| `KP_ext` / `KI_ext` / `imax_ext` | 0.1 / 0.5 / 0.5 | **0.07 / 0.1 / 2** | menos sobreimpulso; `imax 2` evita que se atasque con muestra |
| `KI_h_ext` / `imax_h_ext` | 0.9 / 0.5 | **0.1 / 5** | mismo mecanismo que `h_high` (`KP_h_ext 0.5` se queda) |
| `*_h_low` | — | sin cambio | ya está en 86 % dentro de ±0.5 |
| `cool_stop_margin_c` | (9.5 fijo en el código) | **5.5** | clave nueva; necesita el código que la lee |

Márgenes (ensamble calibrado): el *hold* de 90 °C tiene una meseta con KP 0.2–0.4; desde
KP 0.5 el peor modelo se degrada a 33 %. Con KI 0.15 el peor caso cae a 26–49 %. Se eligió
el centro de la meseta.

**Predicción** (simulación; fracción del *hold* dentro de ±0.5, media del ensamble y peor
caso entre paréntesis):

| fase | calibrado (con muestra): equipo → nuevo | planta 40 % más lenta (a×0.6): equipo → nuevo | sobreimpulso máx. calibrado |
|------|:-:|:-:|:-:|
| high (15 s) | 0.32 (0.24) → **0.69 (0.58)** | 0.39 (0.02) → **0.70 (0.58)** | +4.7 → +2.9 |
| ext (6 s) | 0.28 (0.23) → **0.85 (0.55)** | 0.42 (0.34) → **0.92 (0.78)** | +3.7 → +3.1 |
| denat (120 s) | 0.69 (0.46) → **0.90 (0.87)** | 0.83 (0.73) → **0.91 (0.84)** | +4.0 → +2.9 |
| ext final (120 s) | 0.59 (0.41) → **0.99 (0.98)** | 0.64 (0.47) → **1.00 (0.99)** | +3.7 → +3.1 |

Rampa más lenta del ensamble: high 7.5 s, ext 7.9 s, denat 21 s, igual que hoy y por
debajo de su timeout (20 / 20 / 36.6 s). Con la planta **a × 1.4** los *holds* nuevos
siguen ganando (high 0.19 → 0.69, ext 0.33 → 0.88, denat 0.56 → 0.91), pero las rampas
se pasan +5–6 °C con ambos juegos: si algún día se corre en seco, hay que revisar las
rampas. Lo que limita a high en ~0.7 es la transición
rampa → *hold* dentro de 15 s; en régimen, la std del *hold* baja de ~1.0 a ~0.35 °C.

## 5. Lo que no se hizo

- **Arrastrar el integral entre ciclos** (arrancar cada *hold* con el valor aprendido en el
  ciclo anterior): en simulación sube high de 0.69 a 0.72 en seco y de 0.70 a 0.79 con
  muestra. No justifica tocar código hasta ver la corrida con estos valores.
- **EMA α = 0.3 hardcodeado:** es parte del retraso del lazo y además define lo que se
  guarda en el CSV. Cambiarlo es código y cambia los datos; no se tocó.
- **Tolerancia de salida de rampa (0.5 °C, hardcodeada):** con ráfagas de ~3 °C casi
  nunca se cae dentro; no se tocó.
- **`DEFAULT_SETTINGS`** ([templates/utils.py](../templates/utils.py)) sigue con los
  valores viejos: se actualiza **después** de validar en el equipo.

## 6. Validación en la próxima corrida

La próxima corrida trae `heater_on_s` ([pcr_csv_ciclo_fase.md](pcr_csv_ciclo_fase.md) §6):
el duty deja de deducirse y se mide.

**Orden acordado (21/10/2026).** Ya está corriendo una corrida con `afa8545` (columna
`heater_on_s` + margen configurable) y las **ganancias viejas del equipo**. Sirve para
recalibrar el modelo con el duty **medido**, un ajuste en lazo abierto que con la potencia
reconstruida no era posible, y para medir el enfriamiento con el margen nuevo (la
metadata dice cuál corrió: `stop +X C`). Los valores de §4 se confirman o corrigen con
ese modelo y **recién después** se copian al Pi.

- [ ] Seguir corriendo con muestra (la condición calibrada).
- [ ] `high_hold`: ≥ 50–60 % dentro de ±0.5, media dentro de ±0.2, std tras 5 s ≲ 0.5.
- [ ] Duty de la segunda mitad de `high_hold` **estable** en ~0.2–0.3. Si oscila entre 0 y
      ~0.5 con periodo ~2.5 s, el relé sigue ahí.
- [ ] `ext_hold` y `final_ext` sin la oscilación de ±2 °C; `denat_hold` ya no crece.
- [ ] Sin `-timeouts:` en la metadata. Si una rampa se atasca, subir **su** `KI_*`.
- [ ] Sobreimpulso máximo ≲ +3 °C.
- [ ] Recalibrar el modelo con el duty medido (`files_test/ajuste_21oct/`) antes de un
      segundo ajuste.

## 7. Corrida 2 (21/10/2026 14:51, `afa8545`, ganancias del equipo)

`Newn1_temperature_data_20261021_155301.csv` + `files_test/logconsole.txt`: misma receta,
con muestra, código con `heater_on_s` y margen de enfriamiento de 5.5 °C, y las mismas
ganancias que la corrida 1.

**Lo que se validó:**

- **La réplica del controlador es fiel:** la potencia reconstruida desde la EMA coincide
  con el duty medido en los *holds* (corr 0.99, error medio 0.024; a 90 °C, 0.232 contra
  0.219 medido). Confirma además que el Pi corrió con `settings_device_20261021.json`.
- **Se confirma el mecanismo del §2 con el duty medido:** en `high_hold` el heater da
  pulsos de ~0.45 y luego 0, en ciclo límite.
- **Duty de régimen medido** (estable de un ciclo a otro): **0.20–0.22 a 90 °C**, 0.05 a
  50 °C, ~0.09 a ~67 °C.
- **Escribir datos no agrega retraso:** durante la corrida no se escribe a disco
  (`save_data=False`; el CSV se guarda una sola vez al final), y la gráfica se redibuja
  cada 2.5 s, que no coincide con las ráfagas de ~0.27 s.
- **Margen 5.5 °C:** el motor termina de frenar en 52–53.5 °C. Sin *undershoot* (mínimo
  −0.65 °C, igual que con 9.5).
- Consola: `cool stop: +5.5 C`, ETA 55.5 min, cierre limpio (pines liberados), sin abortos.

**Lo que cambió: el disco respondió mucho más lento.**

| | corrida 1 (13:37) | corrida 2 (14:51) |
|---|:-:|:-:|
| heater encendido → termopar +1 °C | 0.31 s | 1.25–1.75 s |
| heater encendido → IR +1 °C | 0.61 s | 0.93–1.23 s |
| calentamiento a potencia plena | 9–11 °C/s | ~4.5 °C/s (rampa a ext) |
| periodo del ciclo límite a 90 °C | 2.7 s | 6.0 s |
| sobreimpulso de ext | +2.4 | **+9.2** (la extensión pasa sus 6 s a ~72 °C) |
| dentro de ±0.5: high / low / ext | 21 % / 86 % / 24 % | 20 % / 51 % / **0 %** |
| timeouts | 0 | 7 de `ext_ramp`, todos **por encima** del objetivo (68–71 °C) |
| duración | 3222 s | 3675 s |

IR y termopar viajan en el mismo datagrama, medidos en la misma vuelta del firmware
(`read_temperatures_payload`, sin filtro). Así que el tiempo de registro y transporte es
común a los dos y en la corrida 1 era ≤ 0.3 s en total: **el retraso extra es térmico**.
En la rampa, el termopar además queda plano ~2.5 s con el heater a fondo y luego salta
~20 °C en 0.6 s (más rápido de lo que el heater puede calentar). Encaja con un cambio
físico del contacto termopar–muestra (burbuja, desplazamiento del líquido o alineación
del disco); es una deducción sin confirmar. Los timeouts salen de ahí: si la ráfaga
salta la banda de ±0.5, la rampa espera a que baje de ~75 °C a 0.6 °C/s.

**Duración (estimador inicial 3330 s = 55.5 min).** Disco 1: 3222 s (−108); disco 2:
3676 s (+346). Las fases de tiempo fijo (*holds*, lecturas, extensión final) coinciden con
el estimado a ±3 s en ambas corridas. Los +454 s del disco 2 sobre el 1 salen solo de las
fases que dependen del disco:

- **enfriamiento +232 s:** 45.2 s/ciclo contra 38.7;
- **`ext_ramp` +177 s:** 7 timeouts cuestan ~105 s, y las rampas normales tardan 5.2 s
  contra 2.9;
- **`high_ramp` +42 s.**

En las dos corridas el enfriamiento **se alarga durante la corrida** porque el cuerpo del
disco se calienta: disco 1 de 34 a 42 s, disco 2 de 40 a 48 s (ciclos 2–6 contra 31–35).
Por eso la ETA en vivo (`_estimate_remaining_time`, promedio de los ciclos medidos) queda
corta al principio y se corrige sola a medida que avanzan los ciclos.

**Consecuencia para el ajuste (simulación, modelos calibrados de cada corrida):**

| hold de 90 °C estable (std, °C) | planta rápida | planta lenta |
|---|:-:|:-:|
| equipo (0.1 / 0.5 / 0.5) | 1.03 | 1.51 |
| propuesto §4 (0.25 / 0.1 / 5) | **0.24** | **2.95** |
| suave (0.1 / 0.03 / 10) | 0.23 | 1.85 |

- **No hay un juego de PI que sirva para las dos plantas:** lo que arregla la rápida
  desestabiliza la lenta (~1.5 s de retraso).
- En la planta lenta el *hold* de 15 s queda dominado por el **sobreimpulso de la rampa**,
  no por las ganancias del *hold*: 13–16 % dentro de ±0.5 con cualquier juego, con o sin
  arrastre del integral.
- El modelo de la corrida 2 es aproximado: no reproduce el salto del termopar, y su rampa
  a 90 dura 14–18 s contra 5 s reales.

**Causa (usuario, 21/10/2026): se usa un disco nuevo en cada experimento.** Cada disco
cambia la ubicación del termopar respecto a la muestra y las burbujas, así que ninguna de
las dos corridas es "la" planta: son dos muestras de un **rango**. El objetivo del ajuste
pasa a ser la **robustez entre discos**, o un control que **aprenda el disco** durante la
corrida, no el óptimo para uno.

Huella por disco con `files_test/ajuste_21oct/fingerprint.py` (acepta CSV con o sin
`heater_on_s`; medianas de los ciclos ≥ 2):

| | disco 1 (13:37) | disco 2 (14:51) | disco 3 (16:13) |
|---|:-:|:-:|:-:|
| respuesta del termopar / IR (s) | 0.32 / 0.61 | 1.25 / 0.93 | 0.61 / 0.64 |
| calentamiento a ext (°C/s) | 8.9 | 3.5 | 5.3 |
| calor en vuelo: subida tras apagar el heater (°C) | — | 8.2 | 4.5 |
| sobreimpulso de ext (°C) | +2.7 | +9.2 | +5.2 |
| periodo del ciclo límite a 90 °C (s) | 2.6 | 6.0 | 6.2 |
| dentro de ±0.5: high / low / ext | 19 / 80 / 25 % | 19 / 51 / 0 % | 27 / 49 / 0 % |
| **duty de régimen 90 / 50 °C** | ~0.20 (reconstruido) | **0.20 / 0.05** | **0.21 / 0.03** |
| enfriamiento / ciclo (s) | 38.8 | 45.2 | 39.7 |
| timeouts / duración | 0 / 3222 s | 7 / 3676 s | 0 / 3444 s |

El disco 3 (`Newn1_temperature_data_20261021_171340.csv`) no muestra el salto del
termopar del disco 2. Aun así, su extensión pasa los 6 s entera por encima de 65.5 °C,
y el *hold* de 90 está en el mismo ciclo límite de ~6 s.

**Lo constante y lo variable entre discos.**

- **Constante:** la potencia de régimen para *sostener* una temperatura (≈0.20 a 90 °C,
  0.03–0.05 a 50 °C) es del **instrumento**, no del disco.
- **Variable:** el **retraso**, es decir, cuánto calor queda en vuelo al apagar el
  heater (de ~2.7 a 8.2 °C en la extensión).

Con el control actual, una rampa a potencia plena seguida de un *hold* que solo puede
apagar el heater, el sobreimpulso depende del disco y ninguna ganancia fija lo corrige
en los discos lentos.

**Estabilidad dentro de una corrida** (base para aprender del ciclo anterior):

| | disco 2 | disco 3 |
|---|:-:|:-:|
| duty a 90 °C (mediana, cambio medio entre ciclos) | 0.20, ±0.03 | 0.23, ±0.04 |
| duty a 50 °C | 0.05, ±0.00 | 0.03, ±0.00 |
| calor en vuelo, rampa a ext | 8.2 °C, ±0.7 (deriva 9.6 → 6.8) | 4.5 °C, ±1.4 |
| calor en vuelo, rampa a high | 0.9 °C, ±1.3 | 3.3 °C, ±0.7 |

Las dos magnitudes se pueden aprender ciclo a ciclo, con dos condiciones de diseño:

- **promediar los últimos ciclos**, no copiar el anterior (±1 °C de ruido y deriva lenta);
- **aprender por fase:** dentro del mismo disco, el calor en vuelo de la rampa a ext y el
  de la rampa a high difieren mucho.

Una cuarta corrida con la configuración del disco 3 (validación de repetibilidad) se
**canceló por un goteo**: no es válida y no se analizó.

**Factor mecánico (usuario, 21/10/2026).** Tras ~4 h de uso los soportes se calientan,
algunas tuercas se aflojan y **el heater se mueve con el giro**; se corregirá antes de las
próximas corridas. Así que parte de la variación atribuida a los discos puede ser
posición del heater. Los datos:

- **Sin saltos dentro de las corridas:** la respuesta del termopar es estable en los 35
  ciclos de cada una, sin cambios bruscos de un ciclo a otro.
- **Deriva lenta solo en el disco 3:** calentamiento −20 % a lo largo de la corrida.
- **Cambio grande entre corridas:** la rampa de denaturación, a potencia plena desde
  frío, bajó de 13.9 °C/s (corrida 1) a 8.4 y 9.1 °C/s (corridas 2 y 3).

**Aclaración del usuario:** el desplazamiento es de **milímetros** y cambia la tasa de
calentamiento de forma sutil y gradual, no súbita; probablemente despreciable, solo a
tener en cuenta. Encaja con la deriva lenta del disco 3, no con el salto entre las
corridas 1 y 2, que se atribuye sobre todo al **cambio de disco**.

`fingerprint.py` reporta `denat_rate` y `denat_tc_resp` como control de posición del
heater entre corridas.

**Próximo paso (decisión del usuario):** elegir entre:

1. **Ganancias fijas conservadoras** que no empeoren ningún disco. En simulación, el juego
   "suave" de la rampa y el *hold* de ext (KP_ext 0.04, KI_ext 0.1, imax_ext 2;
   `h_ext` 0.15 / 0.03 / 10) mejoró la extensión en los dos discos. Para 90 °C ningún
   juego fijo mejoró los dos.
2. **Control que aprende el disco** (código):
   - **arrastre del integral entre ciclos:** el duty de régimen es estable dentro de una
     corrida;
   - **corte de rampa por calor en vuelo medido:** apagar el heater tantos grados antes
     del setpoint como siguió subiendo la temperatura en las rampas previas. En el disco 2
     serían ~8 °C; en el disco 1, ~2–3.
   - **potencia de régimen como *feed-forward* en los *holds*** (≈0.20 a 90 °C), con un PI
     suave encima. Dentro de la banda debe **mantenerse** el *feed-forward*: hoy la banda
     fuerza 0.
   - Detrás de una opción de `settings.json` apagada por defecto, para compararla en el
     equipo contra el control actual.

   **No se simuló de forma fiable:** el modelo de dos nodos no tiene pérdidas al ambiente,
   así que en un *hold* largo la potencia de régimen tiende a 0 y no sirve para evaluar un
   esquema basado en ella. La validación tiene que ser en el equipo.

   **Implementado (21/10/2026)** como opción apagada por defecto:
   [pcr_control_adaptativo.md](pcr_control_adaptativo.md). Se verificó con el código real
   en tiempo virtual, con discos simulados que sí tienen pérdidas al ambiente.

__author__ = "Edisson A. Naula"
__date__ = "$ 21/10/2026 $"
