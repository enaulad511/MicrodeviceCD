# Análisis de las lecturas de Quick Control

Pestaña **"Quick Control"** de la ventana de análisis
([quick.py](../ui/analysis/quick.py)), agregada el 17/11/2026. Hasta entonces las lecturas
de temperatura y del fotodetector que se guardan desde Quick Control (`unified_*.xlsx`) no
tenían dónde analizarse: el plan de validación del TIA ([tia_fotodiodo.md](tia_fotodiodo.md)
§8: nivel a oscuras, ruido a oscuras vs con LED, deriva) y las comparaciones IR vs termopar
([ir_vs_termopar.md](ir_vs_termopar.md)) se hacían a mano. El vocabulario (corrida, canal,
traza, ventana, evento de actuador, señal del fotodetector vs fluorescencia) está en
[GLOSSARY.md](../GLOSSARY.md).

## 1. Decisiones (sesión de diseño del 17/11/2026)

| # | Decisión | Por qué |
| --- | --- | --- |
| Q1 | Superponer trazas + **estadísticas por ventana** (dos clics). Sin detección del escalón del LED | Una sola herramienta cubre ruido, deriva, offset entre canales y tasas. El escalón no se puede medir: cada muestra de fluorescencia promedia 8 lecturas del ADS a 64 SPS (~60–125 ms), y el paso 6 de §8 pide τ ≤ 10 ms |
| Q2 | Solo `unified_*` | Un único formato y una sola ruta de lectura. Los `temperature_log_*` / `photoreceptor_data_*` de las pestañas viejas salen como "not recognized" |
| Q3 | Una pestaña, **una señal a la vez**. El primer archivo fija la señal; la otra se rechaza hasta "Clear all" | °C y V en el mismo eje no tienen sentido, y Quick Control nunca graba las dos señales a la vez, así que no hay un tiempo común para apilar dos ejes |
| Q4 | La señal del fotodetector se rotula **"Photodetector (V)"**, no "Fluorescence"; los archivos siguen con `signal=fluor` | Con el LED encendido, el nivel es fondo y no fluorescencia (tia_fotodiodo §9) |
| Q5, Q13 | Hoja `settings` **por corrida** (foto al Start) con `photoreceptor.rf_ohm`; nA solo si la corrida trae Rf; el gráfico siempre en V | El paso 3 de §8 cambia el par/FSR entre corridas con Keep data, así que una foto por archivo se pierde. Inventar Rf para archivos viejos es justo lo que impide comparar en nA |
| Q6, Q14 | Hoja `events` con el estado inicial en t = 0 y cada cambio de LED/motor durante la lectura | Antes los metadatos solo se tomaban al Start: prender el LED a mitad de corrida no quedaba en ningún lado |
| Q7, Q19 | Siembra en vivo al abrir + botón **"Reload live"** | "Analyze" con la ventana abierta solo la trae al frente; sin recarga, las corridas nuevas nunca llegarían |
| Q8 | Guardado en `files/QUICK` (`experiment_dir("quick")`) | Igual que los demás guardados ([almacenamiento_por_experimento.md](almacenamiento_por_experimento.md)). Los `unified_*` anteriores siguen en `files/` y se mueven a mano |
| Q10 | La ventana pertenece a **una corrida** y da una fila por canal | En "All (3 temps)" deja los tres sensores en el mismo intervalo (offset IR−TC). Un rango global no sirve: cada corrida arranca su tiempo en 0 |
| Q11 | Etiqueta automática a partir de los eventos, editable; **"mixed"** (⚠) si cruza un evento | Ver §4.3 |
| Q12 | Columnas de la tabla | Ver §4.4 |
| Q15 | Export/Import con ida y vuelta completa | Igual que los segmentos de la pestaña PCR |
| Q16 | Sin alineación: `t_s` desde el Start de su corrida | Alinear al primer "LED on" sería otra herramienta que hoy no hace falta |
| Q17 | Árbol archivo → corrida → canal; un eje de alto fijo dentro del scroll; sombreado solo de la corrida seleccionada | Con varias corridas superpuestas el sombreado de todas es ilegible. Tamaño fijo: [pcr_analisis.md](pcr_analisis.md) §4.4 |
| Q18 | Si la pestaña principal activa es Manual Control, la ventana abre en Quick Control | `MainGUI.open_analysis_window` → `prefer_quick` ([MainGUI.py:244](../ui/MainGUI.py#L244)) |

## 2. Qué guarda Quick Control

[QuickControlFrame.py](../ui/QuickControlFrame.py) `save_data`
([:916](../ui/QuickControlFrame.py#L916)) escribe un `unified_{temp|fluor}_<ts>[_meta].xlsx`
en `files/QUICK` con tres hojas:

- **`data`** (sin cambios): `t_s, value, channel, signal, run`, en formato largo.
- **`settings`**: `run, key, value`. Es una foto al Start de cada corrida
  (`_run_settings`, [:864](../ui/QuickControlFrame.py#L864)) con `signal`, `interval_ms`
  y los metadatos `meta.*` (`rpm`/`osc`/`heat`/`fluorled`/`tsrc`). En las corridas del
  fotodetector agrega `ads_fsr` (el del lector en uso), `photoreceptor.use_diff`, `ch_p`,
  `ch_n` (ya validados por `photoreceptor_channels`) y `photoreceptor.rf_ohm`.
- **`events`**: `run, t_s, actuator, state`.
  - Actuadores: `fluor_led` y `heat_led` (`on`/`off`) y `motor` (`off`, `700 CW`,
    `osc 30° 10%`, o `stopping` mientras frena y vuelve a cero).
  - Al Start se escriben los tres estados iniciales en t = 0
    ([:659](../ui/QuickControlFrame.py#L659)). Después, cada cambio pasa por `_log_event`
    ([:849](../ui/QuickControlFrame.py#L849)), con el mismo origen de tiempo que las
    muestras.
  - Un estado igual al último anotado se descarta. Por ejemplo, un toggle que falla y
    vuelve a OFF no es un evento; si lo fuera, marcaría "mixed" una ventana que no cruzó
    nada.
  - Solo se anota mientras hay una lectura corriendo.

**Rf**: `settings.json` → `photoreceptor.rf_ohm` (default 0 = desconocido; sembrado por
`DEFAULT_SETTINGS`, así que aparece solo en Config). No interviene en ninguna lectura:
solo viaja con la corrida. **Hay que actualizarlo cada vez que se mueve Rt**; si no, la
conversión a nA sale mal sin ningún aviso. Lo lee `photoreceptor_rf_ohm`
([utils.py:344](../templates/utils.py#L344)).

Los archivos anteriores al 17/11 no tienen `settings` ni `events`: se cargan igual, solo
en V, sin sombreado y con la etiqueta de ventana vacía. Los guardados entre el 09 y el
11/11 son con Rf = 56.3 kΩ (tia_fotodiodo §7); los del 13/11 en adelante usan el TIA nuevo
con Rt sin registrar.

## 3. Modelo

En [quick.py](../ui/analysis/quick.py):

- `QuickRun` es una corrida (fuente = nombre corto del archivo o `live`).
- `QuickTrace` es un canal con su propio eje de tiempo y su visibilidad.
- `QuickWindow` guarda `t_a`, `t_b` y la etiqueta.

`parse_readings` ([:261](../ui/analysis/quick.py#L261)) agrupa por columnas de encabezado,
no por posición. Rechaza:

- un libro sin hoja `data` (p. ej. `unified_temp_All.xlsx`, armado a mano el 05/08);
- un export de esta pestaña cargado con Load, que hay que abrir con Import;
- una corrida con más de una señal.

## 4. La pestaña

### 4.1 Gráfico

Un solo eje, con la figura de `PLOT_FIG_W_IN × PLOT_IN_PER_WEIGHT·3` (el mismo alto que el
eje de temperatura de la pestaña PCR) dentro del área con scroll. Es una constante: nunca
sale de `winfo_height()` (pcr_analisis §4.4). La barra de zoom va fuera del scroll.

### 4.2 Sombreado y ventanas

- **Sombreado** (`QuickRun.intervals`, [:172](../ui/analysis/quick.py#L172)): solo la
  corrida seleccionada en el árbol, o la única visible.
  - LED de fluorescencia: azul a toda la altura.
  - LED de calentamiento: naranja.
  - Motor: franja gris al pie. Cuenta como activo todo lo que no sea `off`, incluido
    `stopping`.
- **Ventanas**: "Add window" y dos clics sobre la corrida seleccionada. Cada clic se ajusta
  a la muestra más cercana (`_on_add_click`, [:824](../ui/analysis/quick.py#L824)). Las
  ventanas de la corrida seleccionada se resaltan con su número (W1, W2…); las demás quedan
  tenues y sin texto.

### 4.3 Etiqueta automática

`auto_label` ([:149](../ui/analysis/quick.py#L149)) arma la etiqueta así:

- **Fotodetector**: "LED on" / "LED off", más "heat on" si el LED de calentamiento estaba
  encendido.
- **Temperatura**: "heat on" / "heat off", más "LED on".
- En ambos casos agrega "motor <estado>" si el motor estaba en marcha. Ejemplo:
  "LED off · motor 700 CW".
- Si un evento cae dentro de (t_a, t_b], la etiqueta es "mixed".
- La etiqueta se edita con doble clic en la columna Label. La marca ⚠ en la tabla sale
  siempre de los eventos, aunque se cambie el texto.

### 4.3b Renombrar (doble clic en el árbol)

Pedido del usuario el 17/11/2026, mismo gesto que en la pestaña PCR (`_begin_rename`, [:598](../ui/analysis/quick.py#L598)):

- **Archivo**: renombra la fuente de todas sus corridas. Si choca con otra, se le agrega
  `_1`. Una fuente `live` renombrada sigue siendo live, así que "Reload live" la reemplaza.
- **Canal**: le da a la traza un nombre visible, que se usa en la leyenda, el árbol
  (`nombre (canal)`) y la columna Channel de la tabla. **No reemplaza a `channel`**,
  porque el Δ respecto al termopar y las claves del export lo usan. Si el campo queda
  vacío, o con el nombre por defecto (`<archivo> r<n> <canal>`), vuelve al de por defecto.
- **Corrida**: no se renombra. Su número es la clave de `settings`/`events`/`windows`.

### 4.4 Estadísticas

`window_stats` ([:191](../ui/analysis/quick.py#L191)) da una fila por canal de la corrida.
La tabla muestra solo las trazas visibles; el export incluye todas.

| Columna | Cálculo |
| --- | --- |
| n, media, P-P | sobre las muestras con t_a ≤ t ≤ t_b |
| Std | `ddof = 1`: ruido rms alrededor de la media (§8 paso 5) |
| Std/mean % | std / \|media\| |
| Slope | mínimos cuadrados, unidad/s: °C/s en temperatura (tasa), V/s en el fotodetector (deriva) |
| Δ vs TC (temperatura, varios canales) | media del canal − media del termopar en la misma ventana |
| Drift % (fotodetector) | pendiente × (t_b − t_a) / media |
| Mean / Std (nA) (fotodetector) | V / Rf × 1e9, solo si la corrida trae `rf_ohm` > 0 |

## 5. Export / Import

`export_results` ([:1093](../ui/analysis/quick.py#L1093)) escribe `quick_analysis_<ts>.xlsx`
con estas hojas:

- `data`, `settings`, `events`: las de Quick Control más una columna `file`;
- `windows`: `file, run, label, t_a, t_b`;
- `names`: `file, run, channel, name`, solo de las trazas renombradas;
- `stats`: todas las ventanas y canales, con `name`, `mixed` y `unit`.

`import_analysis` reconstruye trazas, settings, eventos, ventanas con su etiqueta y los
nombres de traza. Los exports anteriores al renombrado no traen la hoja `names` y se
importan igual. Si un nombre de fuente choca con lo ya cargado, se le
agrega un sufijo `_1`. La visibilidad no viaja.

## 6. En vivo

`_seed_live` ([:1032](../ui/analysis/quick.py#L1032)) copia `QuickControlFrame.runs`, incluida
la corrida en curso hasta la última muestra. Es una foto: lo que se lea después llega con
**Reload live** ([:1076](../ui/analysis/quick.py#L1076)), que reemplaza las corridas `live`
y descarta sus ventanas; las de los archivos cargados no se tocan. Si la ventana se abre
desde electroquímica, no hay `quick_frame` y el botón queda deshabilitado.

## 7. Verificación (17/11/2026, Windows, sin hardware)

Script en la scratchpad, no en el repo:

- Se parsearon los 15 `unified_*` existentes (solo `unified_temp_All.xlsx` no se reconoce).
- Las estadísticas se comprobaron contra una recta sintética: pendiente, media, nA, deriva
  y Δ vs TC.
- Etiquetas: "LED off", "LED on · motor 700 CW", "mixed".
- `_log_event` descarta los no-cambios.
- `save_data` escribe las tres hojas en `files/QUICK`.
- La pestaña se probó con datos en vivo simulados: tabla, Export → Import (ventanas,
  etiquetas, Rf, eventos), Load con rechazo del export y del libro sin `data`, y
  Reload live.

## 8. Pendientes

- [ ] HW — En el Pi: una lectura de fluorescencia prendiendo y apagando el LED a mitad de
      corrida y moviendo el motor. Confirmar que la hoja `events` coincide con lo hecho y
      que el sombreado cae donde salta la señal.
- [ ] HW — Al ajustar Rt: medir R1 + Rt y cargarlo en Config → `photoreceptor.rf_ohm`
      antes de las corridas del paso 5 de §8.
- [ ] Usuario — Mover los `unified_*` de `files/` a `files/QUICK/` (el diálogo Load arranca
      ahí).

__author__ = "Edisson A. Naula"
__date__ = "$ 17/11/2026 $"
