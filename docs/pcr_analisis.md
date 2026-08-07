# Análisis PCR (pestaña «PCR» de AnalysisWindow)

Pestaña de análisis para las corridas de [ui/PcrFrame.py](../ui/PcrFrame.py): carga los
datos guardados (temperatura + fotodetector), dibuja las curvas y mide **tasas de
calentamiento y enfriamiento** picando dos puntos sobre la curva de temperatura.

UI: [ui/analysis/pcr.py](../ui/analysis/pcr.py) → `PcrAnalysisFrame`
([pcr.py:63](../ui/analysis/pcr.py#L63)), **cuarta** pestaña del
`Notebook` de `AnalysisWindow` ("PCR"), junto a "Peaks (CV)", "SQWV Peaks" y "EIS".

## 1. Lanzamiento y siembra

`AnalysisWindow` es un `Notebook` con cuatro pestañas
([window.py:26](../ui/analysis/window.py#L26)). Se abre desde dos sitios:

- **Footer general de MainGUI** (botón "🔬 Analyze"): `MainGUI.open_analysis_window`
  pasa `pcr_frame=self.tab_pcr` ([ui/MainGUI.py:214](../ui/MainGUI.py#L214)). Si el
  `PCRFrame` tiene datos en memoria, la pestaña PCR queda **seleccionada por defecto** y
  la corrida en curso se **siembra** como un experimento `"<proyecto> (live)"`
  (`_seed_from_pcr`, decisión Q3). La siembra lee `data_temperature` /
  `data_photodetector` / `data_time` (mismas listas del plot en vivo de PcrFrame), así
  que la corrida sembrada trae su **eje temporal real**.
- **Electroquímica** (`EventEmstatFrame`): pasa `pcr_frame=None`, así que la pestaña PCR
  arranca vacía y no se auto-selecciona.

Además de la siembra, siempre se puede **Load CSV** e **Import** para acumular más
experimentos (como las otras pestañas). Los atajos `Ctrl+L` / `Ctrl+I` del shell se
enrutan a la pestaña activa (`_active_load` / `_active_import`).

## 2. Eje temporal (real medido, con fallback sintético)

> **Superseded.** Este doc describía un eje 100 % sintético sembrado de
> `pidControllerRPM.ts_pcr`. Ese `ts` es el periodo del lazo PI, **nunca fue la cadencia
> de muestreo**, y usarlo dejaba las tasas °C/s ~20 % bajas. Ver
> [pcr_eje_tiempo.md](pcr_eje_tiempo.md) para el porqué completo y el impacto en datos
> históricos.

`save_data_temps_file` escribe una fila de prefijo/metadatos y luego, por muestra, **tres
columnas** `[primario, secundario, t_s]`, donde `t_s` es el **tiempo real** de recepción
en segundos desde el inicio de la corrida. Cuando existe, el eje X sale de ahí.

Los CSV anteriores no traen esa columna: para ellos el tiempo se **sintetiza** con el `dt`
global (`X = índice_de_muestra · dt`). La resolución es **por experimento**
(`PcrExperiment.xs()`), para que una corrida vieja y una nueva superpuestas en el mismo
eje sigan siendo cada una honesta.

- Campo **"Legacy dt (s)"** en la barra (antes "Sampling dt"): solo rige a los
  experimentos **sin** tiempo real. Default `PCR_LEGACY_DT_S = 0.08` (cadencia nominal
  del firmware), **no** `ts_pcr`.
- El botón "↻ Apply dt" (o Enter en el campo) recomputa todo; los experimentos con `t_s`
  lo ignoran. Al importar un bundle, su `dt` restaura el campo.
- `load_csv` avisa en el status cuál de los dos ejes se está usando ("real time axis" vs
  "no t_s column — synthetic axis from Legacy dt").

## 3. Modelo de datos

- `PcrExperiment`: `temps` (np.array denso), `times` (eje real; vacío = sin `t_s`),
  `photo` (np.array, delta por ciclo), `visible`, y `segments`. `xs(dt, n)` es el único
  punto que decide entre tiempo real y sintético.
- `PcrSegment`: par de **índices de muestra** `(ia, ib)` — no de tiempos, así que los
  bundles exportados antes del cambio de eje siguen importando igual. La tasa se deriva
  del eje del experimento en `PcrExperiment.seg_metrics` → `rate = ΔT / Δt` [°C/s], con
  `Δt = t_b − t_a`. Signo **positivo → calentamiento**, negativo → enfriamiento
  (clasificación por signo, decisión Q7).

## 4. Área con scroll + selector «View»

El contenido va dentro del `Canvas` con scrollbar vertical (`_main_sc`, mismo patrón que
Peaks/SQWV/EIS), y `_create_plot_canvas` construye **solo los ejes que pide la vista
actual** (`PLOT_VIEWS`, §4.4); los demás quedan en `None` y el código de dibujo los saltea.
Las dos piezas son complementarias: el scroll deja que la figura sea más alta que la
ventana (por eso cada gráfico conserva su tamaño), y la vista decide **cuánto** hay que
recorrer. Los seis ejes posibles son:

1. **Temperatura (°C) vs tiempo** — una curva por experimento; cada segmento se dibuja
   como una recta A→B roja (calentamiento) / azul (enfriamiento) con sus dos puntos. El
   punto A pendiente (primer clic a la espera del segundo) se marca con una «×» negra.
2. **Fotodetector (Δ V) vs ciclo** — delta por ciclo, igual que el plot en vivo (decisión Q4).
3. **Extracted heating slices** — el corte **real** de temperatura de cada segmento de
   calentamiento (`temps[lo:hi+1]`), con el tiempo re-zeroado al punto A (`_draw_extracted`).
4. **Extracted cooling slices** — lo mismo para los segmentos de enfriamiento. Color por
   índice de segmento (ciclado), leyenda `exp/segK/rate`, respeta el botón Legend. Todos
   los segmentos de experimentos visibles, auto en cada redibujo (decisiones §5.1).
5. **Heating rate (°C/s)** — scatter de **cada** segmento de calentamiento + media±std por
   experimento (`errorbar`), X = índice de experimento.
6. **Cooling rate (°C/s)** — lo mismo para enfriamiento.

### 4.1 Slices extraídos (`_draw_extracted`)

El corte usa índices ordenados `lo=min(ia,ib)`, `hi=max(ia,ib)` y re-zerea el tiempo al
punto más temprano (`xs = exp.xs(dt)[lo:hi+1] − xs[lo]`). La clasificación calentamiento vs
enfriamiento usa el signo de `rate` de `seg_metrics`, que es **invariante al orden de los
dos clics** (numerador y denominador cambian de signo juntos), así que da igual si se picó
B antes que A. Solo se dibuja la línea del corte real (sin cuerda ni marcadores). No hay
datos nuevos en el export: los slices se reconstruyen de `temps` + índices de segmento.

Como las otras pestañas, el canvas se **recrea** entero en cada redibujo (`_reset_plot_canvas`),
lo que re-arma el modo "Add segment" si seguía activo.

### 4.3 Barra de navegación de matplotlib (fila propia)

El `NavigationToolbar2Tk` **no** cuelga del canvas: vive en `self._mpl_toolbar_host`, un
frame propio empaquetado bajo `toolbar3`. Colgado bajo el canvas —como en las otras
pestañas— quedaba al pie de la figura; arriba queda siempre a la vista y sirve a
**cualquier** eje, porque el zoom actúa sobre aquel donde se arrastra.

Se probó **compartir fila** con los tres botones de segmento para recuperar ~45 px, y se
descartó: en la Raspberry las fuentes por defecto son más anchas, los botones crecen y el
toolbar —que se empaqueta último— se sale del borde. Lo que se pierde es el **zoom**, justo
lo que hace falta para picar segmentos con precisión.

El contenedor es **persistente**; lo que se destruye y recrea en cada redibujo es el
toolbar (`_reset_plot_canvas` → `_create_plot_canvas`), dentro de él. El atributo sigue
llamándose `self.toolbar_mpl`, así que el guard del picado (`_on_add_click` ignora los
clics mientras `toolbar_mpl.mode` no esté vacío: pan/zoom activo no debe añadir segmentos)
no cambia.

### 4.4 Alto de la figura: `PLOT_IN_PER_WEIGHT` × los ejes de la vista

`figsize = (PLOT_FIG_W_IN, PLOT_IN_PER_WEIGHT · Σ pesos)` con `PLOT_IN_PER_WEIGHT = 1.8"`
y `PLOT_ROW_WEIGHT` = 3 para temperatura (el interactivo) y 2 para el resto. Da:

| Vista | Ejes | Figura | Alto por eje (medido) |
|---|---|---|---|
| Temperature | 1 | 540 px | 472 |
| Photodetector | 1 | 360 px | 293 |
| Slices / Rates | 2 | 720 px | 293 / 293 |
| All (6) | 6 | 2340 px | 448, 299 ×5 |

La propiedad que importa: **un gráfico mide lo mismo esté solo o acompañado, y en cualquier
tamaño de ventana** (verificado en 800×480, 1024×600 y 1180×860: idénticos). La vista no
cambia el tamaño, cambia **cuánto scroll** hay que recorrer — de una gráfica que casi entra
en pantalla a los 2340 px de `All (6)`, que es exactamente la figura fija anterior.

**Historia, porque el diseño dio varias vueltas y todas dejaron una regla.**

1. `figsize=(7,17)` fijo. En el Pi cada eje daba ~197 px: se veía una tira.
2. Derivar el alto del viewport (selector «Plot size», default `Fit` =
   `_main_sc.winfo_height()`). En Windows salía bien; **en la Raspberry salían diminutos**,
   porque allí las filas de toolbar son más altas (fuentes de Linux), el viewport real es
   más chico y `Fit` encogía la figura para «caber» — al revés de lo que hace falta. Regla
   que quedó: **no atar el tamaño a la geometría en runtime**.
3. Tamaño fijo mayor (23.4"), 498×298 px por eje. Siguió sin convencer en el Pi.
4. Se quitó el área con scroll y se agregó el selector «View». Midió el costo exacto de no
   tener scroll: la figura se escala al hueco disponible, así que el techo pasa a ser
   `alto_ventana − chrome` (~272 px de chrome en 800×480) y un solo eje caía a **103 px**,
   los seis a **26/17 px**. Regla que quedó: **el scroll es lo que permite que la figura
   sea más alta que la ventana**; sin él no hay tamaño de gráfico que sobreviva a 480 px.
5. **Actual: scroll + selector «View».** El scroll aporta el alto, la vista aporta que no
   haya que recorrer seis gráficos para ver uno.

**Implementación.** `PLOT_VIEWS` mapea nombre → tupla de claves de eje; `_create_plot_canvas`
pone en `None` los seis atributos `ax_*` y solo crea los de la vista, con
`height_ratios=[PLOT_ROW_WEIGHT[k] …]`. Todo el dibujo tolera `None` (`_redraw`,
`_draw_extracted`, `_draw_rates_and_table`, `toggle_legend`), y `_toggle_add_mode` **avisa y
no se activa** si el eje de temperatura no está en la vista, en vez de dejar al usuario
clickeando sin efecto. La **tabla** de segmentos se llena siempre, esté o no el eje de
tasas: los números no dependen de qué se grafique. `main` se empaqueta con `fill=X` (no
`BOTH`/`expand`) a propósito: el alto lo pide la figura, y ese exceso sobre la ventana es
justo lo que el scroll recorre.

El **ancho** se reparte por lo que pide cada panel del `PanedWindow`. El izquierdo pedía
~380 px (columnas 240+120 y el título largo «Experiments (double-click to rename)», que
empuja el mínimo del `LabelFrame`); con columnas de 150+70 (`minwidth` 80/50) y título
«Experiments» la figura gana ~130 px. La ganancia es en píxeles, así que vale igual en
Linux, donde el título largo habría empujado el mínimo todavía más.

## 4.2 Ventana de muestras (solo vista, global)

Campos **"Show samples: [start]–[end]"** + botón **"⤢ Full"** en la barra `toolbar2`
(junto a `dt`). Recorta **solo el eje de temperatura** a un rango contiguo de índices de
muestra; **no descarta datos ni segmentos**, solo la vista. Su propósito es **ampliar una
región para seleccionar segmentos** con precisión (por eso los segmentos se siguen
dibujando dentro de la ventana).

- **Índices de muestra**, no segundos (`_window`, [pcr.py:319](../ui/analysis/pcr.py#L319)):
  robusto a cambios de `dt`. En blanco = rango completo; entradas inválidas o `start≥end`
  → completo. Se recorta a la longitud máxima entre experimentos visibles.
- **Global**: una sola ventana para todos los experimentos superpuestos (como `dt`).
- **Persistente**: el canvas se recrea en cada redibujo (el zoom del toolbar mpl se
  pierde), pero la ventana sobrevive porque vive en los `StringVar`. `<Return>` en
  cualquier campo → `_apply_window` (redibuja + status `Showing samples lo–hi`); "⤢ Full"
  limpia los campos.
- **Eje Y reajustado a la banda visible**: en `_redraw` ([pcr.py](../ui/analysis/pcr.py))
  las curvas y **todos** los segmentos se dibujan en coordenadas absolutas; con ventana
  activa el `xlim` es la **unión** de los tramos `[lo, hi]` de cada curva visible
  (`min(xs[lo])`, `max(xs[hi])` — cada experimento puede tener su propia base de tiempo)
  y se calcula `ylim` **solo** del corte visible
  (`temps[lo:hi+1]` de los experimentos visibles, +5 % de margen). Matplotlib recorta a la
  caja del eje, así que un segmento parcialmente fuera muestra su porción visible y el
  resto se corta (la tabla y las tasas conservan **todos** los segmentos). La ventana
  **no** se expande para encajar un segmento — recortar es el objetivo.
- **Picado restringido a la ventana**: con ventana activa, `_nearest_temp_index` limita las
  muestras candidatas a `[lo, hi]` para que A/B caigan sobre lo que se ve.
- **Round-trip**: `export_results` escribe una fila global `window` (`a`=lo, `b`=hi, solo si
  hay ventana activa) junto a la fila `dt`; `import_analysis` la restaura en los campos (si
  falta, deja la vista actual intacta, igual que `dt`). El guard de import (columna
  `record`) no cambia.

## 5. Picado de segmentos (dos clics)

`_on_add_click` ([pcr.py:577](../ui/analysis/pcr.py#L577)): "➕ Add
segment" arma la captura; se elige **un** experimento en el árbol (o el único visible) y
se hacen **dos clics** sobre el eje de temperatura. Cada clic hace *snap* a la muestra
más cercana en píxeles (`_nearest_temp_index`, en `transData` para no sesgar por las
escalas dispares de s vs °C — mismo criterio que `_on_hover`/`_nearest_point` de las
otras pestañas). El par forma un segmento ligado a ese experimento; repetir añade más
(decisión Q6). Pan/zoom del toolbar debe estar apagado.

## 6. Tabla y edición

Tabla de resultados (`tree_res`): una fila por experimento con sus segmentos anidados
(`seg{k} [ia→ib]`, tipo, ΔT, Δt, tasa) y filas agregadas `⟨heating⟩` / `⟨cooling⟩` con
media±std (decisión Q9). Acciones:

- **🗑 Remove exp** (árbol izq): borra experimentos seleccionados.
- **👁 Show/Hide**: alterna visibilidad de experimentos.
- **➖ Remove segment**: borra las filas de segmento seleccionadas en la tabla.
- **🧹 Clear segments**: limpia segmentos de los experimentos seleccionados (o de todos).
- Doble clic sobre el nombre de un experimento (en cualquiera de los dos árboles) lo
  renombra in-place (las filas de segmento/agregado no son renombrables).

Cualquier cambio recomputa tabla + gráficas de tasas.

## 7. Export / Import (round-trip con segmentos)

Como las demás pestañas, permite cargar **múltiples** experimentos. `export_results`
escribe dos archivos (decisión Q10):

- **`<name>.csv`** — bundle **re-importable**, formato largo con columna `record`:
  `dt` (una fila global), `temp` (experimento, índice, valor), `temp2` (secundario),
  `time` (eje temporal real, ausente en bundles anteriores → cae al Legacy dt), `photo`
  (experimento, ciclo, valor) y `segment` (experimento, `a`, `b`). `import_analysis`
  reconstruye cada experimento **con sus segmentos** y restaura el `dt`.
- **`<name>_rates.csv`** — resumen legible (solo lectura, no se reimporta): una fila por
  segmento (tiempos, temperaturas, ΔT, Δt, tasa) + `mean_/std_` por tipo y experimento.

`import_analysis` valida por la presencia de la columna `record`; si falta, avisa que se
eligió el archivo equivocado (p. ej. el `_rates.csv`).

## 8. Canal secundario (overlay de referencia)

PcrFrame ahora guarda dos temperaturas del par IR Object ↔ Termocupla (primario que
regula el PID + secundario; ver [docs/temp_source_selector.md](temp_source_selector.md)
§9). El análisis las trata como **overlay de solo lectura**: la 2ª curva se dibuja como
cross-check visual, pero **no participa** del picado de segmentos, tasas, slices
extraídos, ventana ni tabla — esos siguen sobre el **primario** (la temperatura que el
instrumento regula es la que define las tasas de calentamiento/enfriamiento).

- **Modelo.** `PcrExperiment` gana `temps_secondary` (np.array; vacío = corrida de 1
  canal). `PcrSegment` **no cambia** (los índices siguen siendo sobre `temps`).
- **Carga.** `_read_temp_csv` devuelve `(primario, secundario)`: lee la columna 0 y, si
  existe, la columna 1. Los CSV viejos de 1 columna cargan igual, con secundario vacío
  (retrocompatible). Las dos listas quedan **alineadas por muestra** (una fila con
  primario no parseable descarta también su secundario); si ninguna muestra trajo
  secundario, se devuelve `[]` y no se dibuja overlay. La **siembra en vivo**
  (`_seed_from_pcr`) toma además `data_temperature_secondary` de la corrida.
- **Dibujo** (`_redraw`, eje 1). Tras la curva primaria se dibuja la secundaria con el
  **mismo color** del experimento (`line.get_color()`), `linewidth=0.8`, `alpha=0.4` y
  **sin entrada de leyenda** (no duplica). Con la ventana de muestras activa, la Y se
  sigue calculando **solo del primario** (el overlay puede recortarse, como los
  segmentos): la ventana existe para picar sobre el primario.
- **Round-trip.** El bundle re-importable gana un registro **`temp2`** (experimento,
  índice, valor) por muestra del secundario; `import_analysis` lo reconstruye en
  `temps_secondary`. Bundles viejos sin `temp2` → experimento sin overlay (sin romper).
  El resumen `_rates.csv` **no** cambia (solo mide tasas del primario).
- **Checkbox "Show secondary"** (`toolbar2`, `command=self._redraw`). Bandera **global**,
  una sola para todos los experimentos: el secundario es un cross-check de solo lectura,
  o lo quieres ver o estorba — rara vez "solo el del exp 3". Por eso **no** entra al
  árbol de experimentos (que ya tiene su 👁/🚫 por experimento) ni al bundle: es vista,
  no estado del experimento, así que tampoco se persiste ni sobrevive a export→import.
  Arranca visible. La condición vive en `_redraw`
  (`if self.show_secondary.get() and exp.temps_secondary.size`): al ocultarlo la curva
  simplemente no se dibuja, así que el eje Y se reajusta solo — el bloque de la ventana
  de muestras ya calculaba la Y solo del primario y no cambia. Es independiente del
  checkbox homónimo de la gráfica en vivo
  ([temp_source_selector.md](temp_source_selector.md) §9).

## Orden de decisiones nuevas

- **Rol del secundario:** overlay de solo lectura (no se pican segmentos ni tasas sobre él).
- **Round-trip:** el secundario se persiste en el bundle (`temp2`) para sobrevivir export→import.
- **Estilo:** tenue (mismo color, alpha 0.4, sin leyenda) para no ensuciar el plot con
  varios experimentos superpuestos.
- **Visibilidad del overlay:** un checkbox **global** (no por experimento, no persistido):
  es vista, no estado del experimento.
- **Toolbar de matplotlib:** fijo fuera del área con scroll, no colgado del canvas —
  alcanzable desde cualquier posición de scroll a cambio de ~35 px permanentes (§4.3).

__author__ = "Edisson A. Naula"
__date__ = "2026-07-08"
