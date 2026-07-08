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
  `data_photodetector` (mismas listas del plot en vivo de PcrFrame).
- **Electroquímica** (`EventEmstatFrame`): pasa `pcr_frame=None`, así que la pestaña PCR
  arranca vacía y no se auto-selecciona.

Además de la siembra, siempre se puede **Load CSV** e **Import** para acumular más
experimentos (como las otras pestañas). Los atajos `Ctrl+L` / `Ctrl+I` del shell se
enrutan a la pestaña activa (`_active_load` / `_active_import`).

## 2. Eje temporal sintético (dt global)

La temperatura que guarda PcrFrame **no lleva eje temporal**: `save_data_temps_file`
escribe una fila de prefijo/metadatos y luego un valor por muestra, sin timestamp
([ui/PcrFrame.py:923](../ui/PcrFrame.py#L923)). Por eso el tiempo se **sintetiza** con un
`dt` global editable (decisión Q1): `X = índice_de_muestra · dt` [s]. **No se tocó el
guardado de PcrFrame.**

- Campo "Sampling dt (s)" en la barra; default desde `settings.json` →
  `pidControllerRPM.ts_pcr` (`_default_dt`, fallback 0.05).
- El botón "↻ Apply dt" (o Enter en el campo) recomputa todo. Un solo `dt` aplica a
  **todos** los experimentos (decisión Q11); al importar un bundle, su `dt` restaura el
  campo.

## 3. Modelo de datos

- `PcrExperiment` ([pcr.py:31](../ui/analysis/pcr.py#L31)): `temps`
  (np.array denso), `photo` (np.array, delta por ciclo), `visible`, y `segments`.
- `PcrSegment` ([pcr.py:18](../ui/analysis/pcr.py#L18)): par de
  **índices de muestra** `(ia, ib)`. La tasa se deriva con el `dt` global en
  `PcrExperiment.seg_metrics` → `rate = ΔT / (Δidx·dt)` [°C/s]. Signo **positivo →
  calentamiento**, negativo → enfriamiento (clasificación por signo, decisión Q7).

## 4. Cuatro ejes apilados (con scroll)

`_create_plot_canvas` arma una `Figure` alta (6 ejes, `height_ratios=[3,2,2,2,2,2]`,
`figsize=(7,17)`) dentro del área con **scroll vertical** del contenedor (mismo patrón
`_main_sc` que las otras pestañas) para caber en la pantalla chica del Pi (decisión Q8):

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
punto más temprano (`xs = (arange(lo,hi+1)-lo)·dt`). La clasificación calentamiento vs
enfriamiento usa el signo de `rate` de `seg_metrics`, que es **invariante al orden de los
dos clics** (numerador y denominador cambian de signo juntos), así que da igual si se picó
B antes que A. Solo se dibuja la línea del corte real (sin cuerda ni marcadores). No hay
datos nuevos en el export: los slices se reconstruyen de `temps` + índices de segmento.

Como las otras pestañas, el canvas se **recrea** entero en cada redibujo (`_reset_plot_canvas`),
lo que re-arma el modo "Add segment" si seguía activo.

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
  activa se fija `xlim=[lo·dt, hi·dt]` y se calcula `ylim` **solo** del corte visible
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
  `dt` (una fila global), `temp` (experimento, índice, valor), `photo` (experimento,
  ciclo, valor) y `segment` (experimento, `a`, `b`). `import_analysis` reconstruye cada
  experimento **con sus segmentos** y restaura el `dt`.
- **`<name>_rates.csv`** — resumen legible (solo lectura, no se reimporta): una fila por
  segmento (tiempos, temperaturas, ΔT, Δt, tasa) + `mean_/std_` por tipo y experimento.

`import_analysis` valida por la presencia de la columna `record`; si falta, avisa que se
eligió el archivo equivocado (p. ej. el `_rates.csv`).

__author__ = "Edisson A. Naula"
__date__ = "2026-07-06"
