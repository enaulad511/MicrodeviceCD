# Análisis de picos SQWV

Pestaña de análisis dedicada a **detectar múltiples picos** en las corridas de SQWV y
reportar `E_pico` / `I_pico` en cada punto. A diferencia de la pestaña de picos CV
(`PeakAnalysisFrame`), **no calcula tendencia** entre experimentos: el énfasis es el
pico y su valor en ese punto, no la evolución corrida-a-corrida.

Una traza SQWV típica trae **varios picos a distintos potenciales** (multiplexado: cada
analito aparece a su `E`), por eso la detección es multi-pico y de **ambas direcciones**
(máximos = oxidación, mínimos = reducción).

UI: [ui/AnalysisWindow.py](../ui/AnalysisWindow.py) (`SqwvAnalysisFrame`), tercera
pestaña de `AnalysisWindow` ("SQWV Peaks"), junto a "Peaks (CV)" y "EIS".

## 1. Dónde vive y cómo se abre

`AnalysisWindow` es un `Notebook` con tres pestañas. Se lanza desde el botón de la barra
del `EventPlotter` ([ui/EventEmstatFrame.py:651](../ui/EventEmstatFrame.py#L651)) y desde
`MainGUI`. La pestaña activa por defecto la decide el método del plotter:

- `eis` → pestaña EIS.
- `sqwv` → pestaña **SQWV Peaks** (auto-select nuevo).
- resto (cv) → pestaña Peaks (CV).

La pestaña vieja "Peaks (CV/SWV)" se renombró a **"Peaks (CV)"** y ya **no auto-siembra**
desde una corrida SWV (`method not in ("eis", "sqwv")`,
[ui/AnalysisWindow.py:158](../ui/AnalysisWindow.py#L158)); sí puede cargar CSVs SWV a mano
si alguien quiere su lógica de tendencia.

## 2. Modelo de datos

Reusa `Experiment` / `CycleCurve`, pero el ítem por curva es una **corrida (run)**: SQWV
hace **un barrido `I` vs `E` por run**, y un archivo puede traer **varias corridas** (Keep
runs). Los picos de cada curva se guardan en `CycleCurve.max_points` / `min_points` como
listas de `(x, y)`.

## 3. Siembra (`_seed_from_plotter`)

Dos fuentes, ambas para un plotter `sqwv`:

1. **Corrida en memoria** — `plotter.total_data`, agrupada por `run`, **excluyendo** las
   filas `phase == "pretreatment"` (el pre-tratamiento se conserva en el CSV pero no se
   analiza). Un experimento "SWV run" con un `CycleCurve` por run (`r1`, `r2`, …).
2. **Curvas CSV ya cargadas** en el plotter — `plotter.loaded_lines`, agrupadas por
   archivo. La etiqueta `"<base>-r<run>c<cycle>"` se parsea con `_parse_sqwv_label`.

`load_csv` añade un experimento desde un CSV de `save_data` (header
`sample,E_V,I_A,cycle,run,…,phase`): lee columnas **por nombre**, agrupa por `run` y
**salta** filas `phase == "pretreatment"`.

## 4. Detección de picos

`_detect_peaks(xs, ys, direction, window, prom_frac)` → `(maxima, minima)`:

- **Dirección** — selector Max / Min / **Both** (default Both).
- **Peak window** — un punto es candidato si es el extremo en su ventana `±window`.
- **Min prominence (%)** — fracción del **span** de `ys` (decisión Q11: porcentaje, así
  escala con el current range de cada corrida; default 5%). La prominencia local se mide
  contra el lado menos profundo dentro de la ventana.
- Candidatos a `<= window` se **fusionan** conservando el más extremo (una meseta u
  hombro no genera un racimo de picos pegados).
- **Filtro** opcional de suavizado (none / moving_avg / median + ventana), reusando
  `_apply_filter`; la detección corre sobre `ys` filtrado y el overlay muestra lo mismo.

**Compute borra y re-detecta de cero** (decisión Q10): la edición manual es un retoque
posterior, no es sticky.

## 5. Valor reportado

Por pico: `E_pico` (x) y la **corriente absoluta `I_A` en ese punto** (y). Sin línea
base, sin altura corregida, sin tendencia (decisión Q4 = absoluto).

## 6. Gráfica y edición manual

Un **solo overlay** (`I` vs `E`) con todas las curvas visibles; cada pico marcado
`▲`(max, rojo) / `▼`(min, azul) y anotado con `E`/`I`. La tabla inferior lista **un pico
por fila** (`Experiment/Run`, `Type`, `E peak`, `I peak`).

- **Add peak** (toggle): captura clics en el overlay; añade un pico en el **punto medido
  más cercano** de la curva visible más próxima (cercanía en píxeles `transData` para no
  sesgar por las escalas dispares de `E` [V] e `I` [A]). Se clasifica max/min según la
  forma local (vs la media de la ventana). El modo queda activo entre clics (el `cid` se
  re-arma al recrear el canvas).
- **Delete selected**: borra los picos de las filas seleccionadas en la tabla.

## 7. Persistencia

Espejo de la pestaña Peaks: **Export** escribe dos archivos —

- el path elegido: un pico por fila (`experiment, run, type, E_peak_V, I_peak_A`).
- `<base>_curves.csv`: curvas punto-a-punto (`x`, `y_raw`, `y_filtered`, filtro), que
  **Import** vuelve a cargar agrupando por `experiment → run`.

**Leyendas editables** preservadas: doble clic sobre un experimento/run (en el árbol o en
la tabla) lo renombra y actualiza la etiqueta del overlay.

__author__ = "Edisson A. Naula"
