# Análisis de picos CV (pestaña «Peaks (CV)» de AnalysisWindow)

`PeakAnalysisFrame` ([peaks.py](../ui/analysis/peaks.py)): experimentos → ciclos, picos
max/min por ciclo (Global / Local / At X, filtro opcional) y tendencia mean ± std por
experimento. La agrupación por corrida (Keep runs) está en
[emstat_keep_runs.md](emstat_keep_runs.md) §5; aquí va el área de gráficas.

## 1. Selector «View» (10/11/2026)

Antes la figura era fija de 8×6" con un 2×2: overlay arriba a todo el ancho y las dos
tendencias abajo lado a lado. En la pantalla del Pi cada eje quedaba chico y no había forma
de ver solo el overlay más grande. Ahora usa **el mismo esquema que la pestaña PCR**
([pcr_analisis.md](pcr_analisis.md) §4 y §4.4):

| Vista | Ejes | Figura |
|---|---|---|
| Overlay (default) | overlay | 540 px |
| Trends | min, max | 720 px |
| All (3) | overlay, min, max | 1260 px |

- [`PLOT_VIEWS`](../ui/analysis/peaks.py#L33) mapea nombre → claves de eje;
  [`_create_plot_canvas`](../ui/analysis/peaks.py#L399) pone en `None` los tres `ax_*` y
  solo crea los de la vista, apilados en una columna con `height_ratios` de
  [`PLOT_ROW_WEIGHT`](../ui/analysis/peaks.py#L46) (overlay 3, tendencias 2).
- El alto es `PLOT_IN_PER_WEIGHT · Σ pesos` con la constante **importada de
  [pcr.py](../ui/analysis/pcr.py)**: un gráfico mide lo mismo solo o acompañado y en las dos
  pestañas. Valen las mismas reglas que costaron en PCR: no derivar el tamaño de
  `winfo_height()` y no quitar el área con scroll.
- La barra de matplotlib vive en `_mpl_toolbar_host`, fila fija fuera del scroll
  ([peaks.py:289](../ui/analysis/peaks.py#L289)); colgada bajo el canvas quedaba al pie de
  una figura de 1260 px. También se copió el guard del `<Configure>` de 1 px y el margen
  `padx=(5, 20)` del área con scroll.
- **Pick X@max/min** solo funciona con el overlay en la vista: si no está,
  [`_toggle_pick_mode`](../ui/analysis/peaks.py#L678) avisa y no se activa. Un pick
  pendiente sobrevive a los redibujos (`_create_plot_canvas` lo re-arma).

## 2. Cambiar de vista no recalcula

[`compute_extrema`](../ui/analysis/peaks.py#L855) llena la tabla y **guarda** lo dibujable
en `self._computed` (markers, guías At X, tendencias, y el filtro con que se calcularon);
[`_redraw`](../ui/analysis/peaks.py#L579) recrea el canvas y pinta overlay + lo guardado en
los ejes que haya. Así un cambio de vista no vuelve a leer los parámetros de la UI —que
pudieron cambiar sin apretar Compute— ni regenera la tabla.

El overlay se dibuja con el **filtro del Compute guardado**, no con el de la UI: si no, al
cambiar de vista tras tocar el filtro los markers quedarían despegados de la curva.

[`_refresh_overlay`](../ui/analysis/peaks.py#L571) (carga, borrado, visibilidad, import)
descarta `_computed`: markers y tendencias quedan en blanco hasta el próximo Compute, como
antes. La tabla no se toca.

__author__ = "Edisson A. Naula"
__date__ = "$ 10/11/2026 $"
