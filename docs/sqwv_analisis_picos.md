# Análisis de picos SQWV

> **26/10/2026:** el guardado pasó a `.xlsx` ([almacenamiento_por_experimento.md](almacenamiento_por_experimento.md)): Load lee la hoja `data`; Export escribe un libro `peaks` + `curves` (antes `<base>.csv` + `_curves.csv`) e Import lee la hoja `curves`.
>
> **24/11/2026 (revisión de código):** el rango de E que usan Compute, Export, Add peak y el
> dibujo es el **aplicado** (Apply / Select on plot / Full range / Import); lo escrito en los
> campos sin aplicar no cuenta (§8). Export etiqueta `y_filtered` con el filtro del último
> Compute (§7) y el aviso de ventana reducida cubre todo el intervalo de reducción (§8).

Pestaña de análisis dedicada a **detectar múltiples picos** en las corridas de SQWV y
reportar `E_pico` / `I_pico` en cada punto. A diferencia de la pestaña de picos CV
(`PeakAnalysisFrame`), **no calcula tendencia** entre experimentos: el énfasis es el
pico y su valor en ese punto, no la evolución corrida-a-corrida.

Una traza SQWV típica trae **varios picos a distintos potenciales** (multiplexado: cada
analito aparece a su `E`), por eso la detección es multi-pico. **Solo se calculan
máximos** (el pico de corriente neta de SWV); los mínimos se quitaron (decisión 24/11/2026).

UI: [ui/analysis/sqwv.py](../ui/analysis/sqwv.py) (`SqwvAnalysisFrame`), tercera
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
[ui/analysis/peaks.py:96](../ui/analysis/peaks.py#L96)); sí puede cargar CSVs SWV a mano
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

`_detect_peaks(xs, ys, window, prom_frac, method)` → lista de máximos `(x, y)`. Dos métodos
(combobox **Method**, **`Slope` por defecto** desde 24/11/2026):

- **Local max** (clásico) — lo descrito abajo. Sigue disponible para curvas limpias.
- **Slope** — ver §4.1. Por defecto porque en las corridas reales (18/11/2026, 42 curvas)
  Local max no encontró ningún pico en 36: la mayoría de las curvas son monótonas en el
  tramo central y un máximo local no existe.

Lo común a ambos:

- **Peak window (mV)** — semi-ventana en **mV**, no en puntos (el paso de E cambia entre
  archivos: 5.9 mV/punto en los de 18/11, otro en `113540` run 2). Se pasa a puntos por
  curva con el paso medio de E (`_window_pts`). Default **60 mV** (~10 puntos): con ±30 mV
  los picos de la serie de referencia (`163121`) aparecían y desaparecían entre corridas.
  Un punto es candidato si es el máximo en su ventana `±window`. (La ventana del filtro
  sigue en puntos: "Filter window (pts)".) En el [GLOSSARY.md](../GLOSSARY.md) es la
  *semi-ventana del pico*, no una *ventana* (que es un intervalo de tiempo).
- **Min prominence (%)** — fracción del **span** de `ys` (decisión Q11: porcentaje, así
  escala con el current range de cada corrida; default 5%). **Un valor por método**: el
  campo muestra el del método activo y cada uno recuerda el suyo (`_prom`); significan cosas
  distintas (% del span vs % de la curvatura máxima). La prominencia local se mide
  contra el lado menos profundo dentro de la ventana.
- Candidatos a `<= window` se **fusionan** conservando el más alto (una meseta u
  hombro no genera un racimo de picos pegados).
- **Filtro** opcional de suavizado (none / moving_avg / median + ventana), reusando
  `_apply_filter`; la detección corre sobre `ys` filtrado y el overlay muestra lo mismo.

**Compute borra y re-detecta de cero** (decisión Q10): la edición manual es un retoque
posterior, no es sticky.

### 4.1 Método Slope (pendiente / curvatura)

Motivo: un pico sobre una **línea base decreciente** (típico tras el pre-tratamiento o con
decaimiento de corriente) a menudo **no es un máximo local** — `Local max` no lo ve. La
1.ª derivada tampoco sirve sola: sobre una base con pendiente negativa `y'` nunca cruza por
cero, el pico solo la frena. Lo que sí lo delata es el cambio de pendiente: `-y''`
(curvatura) es máxima en el centro del pico y **negativa** en una base convexa
decreciente (no genera falsos picos).

`_detect_slope_indices`:

1. `y'` e `y''` por Savitzky-Golay (cúbico, ventana `2w+1`, `w` = Peak window, mínimo 2),
   calculadas respecto al **índice** de muestra (un barrido con E descendente da lo mismo).
2. Candidatos = máximos locales de `-y''` sobre `max(prom × máx(-y''), 5 × ruido)`. El
   ruido sale de la MAD de las **segundas diferencias** de `y` propagada a `y''`
   (la dispersión de `y''` no sirve: base y picos la inflan, y con ella un pico débil
   sobre una base fuerte se perdía). El umbral absoluto evita "picos" en una curva sin
   picos (el umbral relativo solo siempre encontraría el "más fuerte").
3. Candidatos a `<= w` se fusionan (gana mayor `-y''`).
4. **Ajuste con la pendiente**: si `y'` cruza de + a − a menos de `w` del centro, el pico
   se mueve a ese máximo real; si no, queda en el hombro (centro de `-y''`).

- El control "Min prominence (%)" cambia de etiqueta a **"Min curvature (% of max)"**: es
  fracción de la curvatura del pico más marcado de la curva, no del span de `I`.
- **Peak window** hace de ventana de derivada: más ruido → subirla (sintético, ruido 2e-8:
  w=5 pts no ve el pico débil; w=12–16 sí). La pendiente solo decide **dónde** está el
  pico; `I_pico` sigue siendo absoluta (§5) y la base se trata en la altura.
- Sintético: dos picos sobre un decaimiento exponencial → `Local max` 0, `Slope` 2;
  curva solo ruido + base → 0.
- **Validado con la serie `163121`** (12 corridas del mismo electrodo; el usuario confirmó
  que −0.22, +0.20 y +0.40 V son los analitos reales). Barrido de ventana (40–100 mV) ×
  umbral (2–30 %): con **60–80 mV y 2–5 %** se encuentran los tres en 11 de 12 corridas
  (la corrida 1 es la del electrodo recién montado, con los picos corridos), con ~0.25
  picos de más por corrida; umbrales ≥ 20 % empiezan a perder el de +0.40 V. Por eso los
  defaults son **60 mV / 5 %**. Con ventana de 40 mV o menos pierde estabilidad.

## 5. Valor reportado

Por pico: `E_pico` (x), la **corriente absoluta `I_pico` en ese punto** (y) — sin
tendencia — y, desde 24/11/2026, la **altura `height_A`** sobre la base local.

`I_pico` se conserva absoluta (decisión Q4) porque no rompe nada, pero con base inclinada
mezcla analito y nivel de la base: dos picos del mismo analito a distinto `E` darían
cifras distintas solo por la base. `height_A` = `I_pico` − recta que une los puntos a
**±2 × semi-ventana** del pico (`BASE_ANCHOR`, sobre los datos filtrados y recortados al
rango de E; acotada a los extremos). El factor 2 sale de la serie `163121`: con ±1× las
anclas caen sobre los flancos y la altura sale a la **mitad** (0.77 vs 1.53 µA en un pico),
y con ±3× el ancla cae en el pico vecino (picos a 150–200 mV). Un hombro sin vértice puede
dar altura ≤ 0; se muestra tal cual. Sin anclas distintas (o el pico es él mismo un ancla,
en el borde del rango) → vacío.

**La altura se fija al detectar** (Compute) o al añadir el pico a mano, con el filtro y la
ventana de ese momento (`_remember_heights`, `WeakKeyDictionary` curva → {(x, y): altura}):
cambiar filtro o ventana sin recalcular no la mueve, así queda siempre coherente con
`E`/`I` de la misma fila.

## 6. Gráfica y edición manual

Un **solo overlay** (`I` vs `E`) con todas las curvas visibles; cada pico marcado
`▲` (rojo) y anotado con `E`/`I`. La tabla inferior lista **un pico
por fila** (`Experiment/Run`, `E peak`, `I peak`, `Height`). La columna `Type` se quitó de
la tabla (solo hay máximos); el export la conserva como constante `max`.

- **Add peak** (toggle): captura clics en el overlay; añade un pico en el **punto medido
  más cercano** de la curva visible más próxima (cercanía en píxeles `transData` para no
  sesgar por las escalas dispares de `E` [V] e `I` [A]). Siempre se añade como máximo. Si el
  clic cae en un pico que ya existe no añade nada y el estado dice "Peak already present"
  (antes decía "Added peak" en ambos casos). El modo queda activo entre clics (el `cid` se
  re-arma al recrear el canvas).
- **Delete selected**: borra los picos de las filas seleccionadas en la tabla.

## 7. Persistencia

Espejo de la pestaña Peaks: **Export** escribe **un libro** `.xlsx` con tres hojas —

- `peaks`: un pico por fila (`experiment, run, type, E_peak_V, I_peak_A, height_A`).
- `curves`: curvas punto-a-punto (`x`, `y_raw`, `y_filtered`, filtro), que **Import**
  vuelve a cargar agrupando por `experiment → run`. `filter` / `filter_window` de cada curva
  son los del filtro que produjo su `y_filtered` en el último Compute (`_filters`), no los
  controles de ahora; una curva que no pasó por Compute se filtra al exportar con los
  controles y se etiqueta con ellos. Así `curves`, `peaks` y `settings` describen el mismo
  análisis (antes la etiqueta salía de los controles vivos y podía decir `moving_avg` sobre
  valores sin filtrar). El overlay en pantalla sí usa los controles vivos, por eso
  `y_filtered` del archivo puede diferir de lo que se ve.
- `settings`: rango de E y parámetros de detección (ver §8).

**Leyendas editables** preservadas: doble clic sobre un experimento/run (en el árbol o en
la tabla) lo renombra y actualiza la etiqueta del overlay.

## 8. Rango de potencial (`E range`)

Fila "E range (V)" de la barra: `E min` / `E max` (vacío = sin límite), **Apply**,
**↔ Select on plot** y **Full range**. Un solo rango global para todas las curvas.

- **Un único rango, cualquier cantidad de picos dentro**: el recorte no limita a un pico;
  `_detect_peaks` corre sobre el tramo y devuelve todos los máximos que cumplan
  ventana y prominencia. Para aislar analitos distintos se cambia el rango y se vuelve a
  pulsar Compute (y se exporta cada vez).
- **Solo cuenta el rango aplicado** (24/11/2026): `_range()` devuelve `_applied_range`, que
  solo cambian Apply, Select on plot (rellena los campos y aplica), Full range e Import.
  Escribir en E min / E max no cambia nada hasta aplicar. Antes `_range()` releía el texto en
  cada llamada, así que Compute, Export, Add peak y `_peaks_in_range` usaban un rango que el
  gráfico y la tabla aún no mostraban: con `0.3` escrito y sin aplicar, Export dejaba 1 de 3
  picos; `0.` se leía como 0.0; `0.2 V` se leía como "sin límite" mientras que Apply lo
  rechaza. Si los campos difieren del rango aplicado, Compute y Export lo dicen al final del
  estado (`The E range fields are not applied — press Apply`). No se redibuja al escribir:
  cada redibujo recrea el canvas de Matplotlib y en la Pi es lento.
- **Rango estrecho**: con `n` puntos en el rango la semi-ventana efectiva de Slope es
  `min(w, n // 4)` (mínimo 2; `_slope_window`, la usan el detector y el aviso). Se reduce
  **siempre que n < 4w**, y con `n < 2·w_ef + 3` no queda nada que detectar; Compute avisa en
  ambos casos. (Antes avisaba solo por debajo de `2w+3`: entre `2w+3` y `4w` la ventana se
  reducía sin decirlo; 60 mV = 10 pts con 34 puntos corría con w = 8.) Las anclas de la
  altura (§5) siguen en ±2× la ventana **pedida**: se acotan a los extremos del rango, y con
  la ventana reducida a n/4 caen en esos mismos extremos, así que no hay diferencia práctica.
  Un pico a menos de una ventana del borde del
  rango no se puede detectar (la curvatura necesita puntos a ambos lados): ampliar el rango.
  Ej.: 17 puntos (0.15–0.25 V) en `163121` run 8 no ve el pico de 0.185 V; con 0.12–0.28 V sí.
- **Validación de los campos**: `nan`/`inf` se rechazan; Apply rechaza un texto inválido
  (`0.2 V`) sin cambiar el rango aplicado; con mín > máx se intercambian y los campos muestran
  el rango realmente aplicado. Los campos numéricos (ventana, prominencia, ventana del filtro)
  se leen con `_num`: vacío o texto mientras se escribe devuelve el último valor válido, sin
  excepción (también `inf` / `1e400` en los spinbox enteros: `OverflowError`). Lo que el código
  escribe en el campo de prominencia (cambio de método, Import) pasa por `_set_prom_field`, que
  lo registra como último valor válido: si luego se vacía el campo, vuelve al valor de **ese**
  método y no al que tenía con el otro (antes con Slope = 12 y Local max = 5, vaciar el campo en
  Local max calculaba con 12 y dejaba `_prom` = {local: 12, slope: 12}).
- **Muestra y calcula con el mismo rango**: el overlay solo dibuja los puntos dentro (el eje Y
  se reajusta) y Compute detecta solo ahí. El filtro de suavizado se aplica a la curva
  **completa** y luego se recorta (sin efectos de borde); la prominencia (% del span) es la
  del tramo recortado, no la del barrido entero. Un punto en el borde del rango nunca cuenta
  como pico (la prominencia lo descarta).
- **Select on plot**: arrastre horizontal (`SpanSelector`) de un solo uso; rellena los campos
  y aplica. Es excluyente con *Add peak* (ambos capturan clics). El selector se re-crea con
  el canvas, igual que el `cid` de *Add peak*.
- **Los picos fuera del rango no se muestran ni se exportan** (`_peaks_in_range`, sobre el
  rango aplicado; sirve sobre todo tras restaurar el rango con Import, que no poda).
  **Apply además los descarta** (no quedan picos ocultos que se exporten); los de dentro se
  conservan. Para recuperar los descartados por Apply: ampliar y Compute; los que solo
  estaban ocultos por un Import reaparecen con Full range.
- Export: la hoja `peaks` lleva solo los picos del rango; la hoja `curves` guarda el barrido
  **completo** (para que Import no pierda datos). El rango **no** va como columnas: se guarda
  en la hoja `settings` (`key`/`value`: `e_min_V`, `e_max_V`, `method`, `peak_window_mV`,
  `prominence_pct_local`, `prominence_pct_slope`, `filter`, `filter_window`; vacío = sin
  límite). Exports anteriores con `peak_window` (puntos) y `min_prominence_pct` (un solo
  valor, del método guardado) se siguen leyendo: la ventana se convierte a mV con el paso
  de las curvas cargadas.
- Los parámetros de detección que se exportan son los **del último Compute** (los que
  produjeron los picos del archivo); si se cambiaron controles después, Export lo avisa en la
  barra de estado. El rango es el aplicado.
- Import restaura esos controles desde `settings` (exports viejos sin la hoja siguen
  cargando) pero **no** recalcula: se pulsa Compute y salen los mismos picos sobre el mismo
  rango. El rango restaurado queda **aplicado** (un campo vacío en el archivo lo limpia) pero
  **no poda** los picos de lo que ya estaba cargado: importar un archivo nunca borra picos
  de otros (quedan ocultos; Full range los devuelve). Clear all conserva el rango aplicado,
  igual que los campos. Los picos editados a mano no se reimportan (como antes).

__author__ = "Edisson A. Naula"
