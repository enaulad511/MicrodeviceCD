# Almacenamiento de datos por experimento

Desde el **26/10/2026** cada guardado de la app es **un solo archivo `.xlsx` con varias
hojas** (antes: uno o varios CSV por guardado). Motivo: una corrida PCR eran 3 CSV
hermanos y cada export de análisis 2; al mover archivos de un lado a otro se perdían
pares y el análisis PCR dependía de encontrar el hermano por nombre. Los archivos se
ordenan en subcarpetas de `files/` **por método**.

> Los demás docs hablan de "el CSV de temperatura", "la fila de metadata", "`_curves.csv`"…:
> es el formato anterior. La tabla de [§3](#3-qué-guarda-cada-cosa) dice en qué hoja
> quedó cada cosa.

## 1. Carpetas

```
files/
  PCR/    ← corridas del ciclador
  CV/
  SQWV/
  EIS/
  CA/
```

Todo pasa por `experiment_dir(method) -> "files/<METODO>"` en
[templates/utils.py](../templates/utils.py) (crea la carpeta y la devuelve; el nombre es
el método en mayúsculas). Si cambia la estructura, se toca solo esa función. Los diálogos
"Save as" **no** se fuerzan: solo arrancan en esa carpeta (`initialdir`).

## 2. Lectura/escritura: `templates/xlsx_io.py`

[templates/xlsx_io.py](../templates/xlsx_io.py) es el único punto que toca `openpyxl`
(dependencia nueva en `requirements.txt`; **en el Pi: `pip install openpyxl`**). Se
importa perezoso dentro de cada función: un Pi sin la librería arranca igual y el fallo
aparece solo al guardar/cargar.

- `write_workbook(path, {hoja: filas})` — escribe a `<path>.tmp` y hace `os.replace`:
  un fallo a media escritura nunca deja un `.xlsx` corrupto con el nombre final.
- `read_sheets_text(path)` / `read_sheet_text(path, hoja)` — filas **como texto**, igual
  que `csv.reader` (celda vacía → `""`, sin celdas vacías al final). Así los loaders
  conservaron su lógica de parseo; solo cambió de dónde salen las filas.
- `XLSX_FILETYPES`, `xlsx_path` (normaliza a `.xlsx` lo que se teclee en el diálogo),
  `kv_rows`/`flatten_settings` (hojas `key | value`), `num_or_text`.

### 2.1 Precisión de los floats (medido)

openpyxl escribe los números con `"%.16g"` y pierde el 17.º dígito (~1e-14 a 90 °C).
Parece nada, pero los scripts reconstruyen el crudo del termopar invirtiendo la EMA
(α 0.3) y el MAX31855 cuantiza a 0.25 °C: hay saltos de **exactamente** 3.0 °C y ese ruido
los pasaba de un lado al otro de un umbral `> 3`. Por eso `_exact_floats()` escribe los
floats finitos con `repr` (el formato más corto que relee exacto, como el CSV). Si otra
versión de openpyxl cambia ese interno, cae a 16 dígitos sin romper nada.

- `NaN`/`inf` se escriben como **texto** (`"nan"`): como número, Excel reporta el libro
  corrupto. `float("nan")` los relee igual que antes (el overlay secundario del bundle
  PCR lleva NaN).
- Excel no distingue `94` de `94.0`: un entero guardado como float puede releerse `94`.
  Los loaders usan `float()`/`int(float())`, así que da igual.

Hallazgo de paso: `pd.read_csv` con el parser por defecto **no** es exacto (1 ulp de
error en ~9 % de los valores de una corrida Newn1); con el xlsx (o
`float_precision="round_trip"`) sí. Por eso en Newn1 21/10 corrida 2 `fingerprint.py`
pasó de `tc_resp_s` 1.25 a **1.24** y `ir_vs_tc.py` de 111 a **109** saltos > 3 °C:
los valores nuevos son los exactos.

## 3. Qué guarda cada cosa

| Guardado | Archivo | Hojas | Antes |
| --- | --- | --- | --- |
| Corrida PCR ([PcrFrame.py](../ui/PcrFrame.py) `save_data_temps_file`, automático al terminar y botón Save Data) | `files/PCR/<slug>_pcr_data_<ts>.xlsx` | `metadata`, `settings`, `temperature`, `photodetector`, `photodetector_raw` | 3 CSV `_temperature_data_`, `_photodetector_data_`, `_photodetector_raw_` |
| EmStat CV/SQWV/EIS/CA ([EventEmstatFrame.py](../ui/EventEmstatFrame.py) `save_data`) | `<method>_data_<ts><sufijo>.xlsx` | `data`, `runs` | 1 CSV |
| Export análisis PCR | `pcr_analysis_<ts>.xlsx` | `bundle` (re-importable), `rates` | `<base>.csv` + `_rates.csv` |
| Export SQWV peaks | `sqwv_peaks_<ts>.xlsx` | `peaks`, `curves` (re-importable) | `<base>.csv` + `_curves.csv` |
| Export Peaks (CV) | `analysis_<ts>.xlsx` | `results`, `curves` (re-importable) | `<base>.csv` + `_curves.csv` |
| Export EIS | `eis_analysis_<ts>.xlsx` | `spectra` (siempre, re-importable), `nyquist` (si hay mediciones) | `_spectra.csv` + `<base>.csv` |
| Photoreceptor / Temperature / Quick Control | `photoreceptor_data_*`, `temperature_log_*`, `unified_*` | `data` | 1 CSV |

### 3.1 Corrida PCR

- **`metadata`**: una fila `key | value` por campo, construida como pares desde el origen
  (`self.meta_pairs` al arrancar + `_cadence_meta`, `_timeouts_meta`, `adaptive` al final;
  ver `_run_meta`). Números como números. Antes era **una sola celda** concatenada con
  `-` (`project: …-high_temp: 95-…-start:2026-…`), que no se podía partir de forma
  confiable porque la fecha y los negativos llevan guiones. Claves: receta (`project`,
  `high_temp` … `initial_spin`), `ts`, `temp_source`, ventanas de fluorescencia
  (`fluor_pre_s`, `fluor_baseline_s`, `fluor_light_s`, `fluor_post_s`,
  `fluor_sample_dt_s`, `fluor_averages`), `start`, `cols`, cadencia (`dt_mean`, `dt_p95`,
  `dt_max`, `n`, `span`), `timeout_cfg`, `failed_cycles`, `timeouts`, `fresh`,
  `adaptive`.
- **`settings`**: snapshot **completo** de `settings.json` leído al arrancar la corrida,
  aplanado (`pidControllerRPM.KP_denat | 1.9`, `pcr_adaptive.ff_slope | …`). Cada archivo
  dice con qué sintonización se midió, sin depender del `settings.json` del Pi (en Newn1
  hubo que deducir cosas de la curva por no tenerlo).
- **`temperature`**: fila 1 = encabezado real (`<primario>|<secundario>|t_s|cycle|phase|heater_on_s`,
  los dos primeros según la fuente elegida); luego una fila por muestra. El loader del
  análisis sigue leyendo **por posición** las columnas 0–2.
- **`photodetector`**: `cycle | photodetector | timeouts` (fila *k* = ciclo *k*, la última =
  lectura final). El loader lee la columna `photodetector` por nombre.
- **`photodetector_raw`**: `cycle | t_rel_s | light_on | voltage` (formato largo).

**Respaldo CSV.** El guardado PCR es automático al final de una corrida de ~1 h y antes
usaba solo la stdlib. Si el xlsx falla (falta `openpyxl`, error de escritura), se escriben
los **3 CSV del formato anterior** (`_save_csv_fallback`, metadata en una celda) y el status
lo dice (`Saved as CSV in … (xlsx failed: …)`); el conversor de §4 los recoge después. El
mensaje se muestra al terminar la corrida (`_save_note`, lo pinta `_ui_poll_loop`; el hilo
del experimento no toca Tk). Los guardados con diálogo **no** tienen respaldo: solo
mensaje de error, el usuario reintenta.

Costo (PC de desarrollo, corrida tamaño Newn1 de 45 k muestras): escribir ~2 s, leer
~2.4 s; el xlsx pesa menos que el CSV (2.1 vs 3.05 MB). En el Pi será más lento; la
escritura corre en el hilo del experimento.

### 3.2 EmStat

- **`data`**: las mismas columnas de antes (`sample, <x>, <y>, cycle, run, [freq_Hz, E_V,
  t_s, Z_mod, phase]`); Load/análisis leen por posición (EmStat Load, CV) o por nombre
  (SQWV, EIS) como antes.
- **`runs`**: una fila por corrida en `total_data`: `run, method, start`, `filename_meta`
  (motor) y **cada clave del payload** (incluye `ch`). Se captura en `start()` (`runs_meta`)
  porque `payload_exp` se sobrescribe en la siguiente corrida y con **Keep runs** un
  guardado mezcla corridas con parámetros distintos. Columnas = unión de claves en orden
  de aparición. Se limpia junto con `total_data`.

### 3.3 Exports de análisis

Mismo contenido y columnas que los dos CSV de antes, una hoja por archivo. Import lee la
hoja de reimportación con la misma lógica; desaparecieron los errores "elegiste el archivo
equivocado (`_rates.csv`)". El bundle PCR conserva su formato largo de registros
(`record, experiment, i, a, b, value`): reestructurarlo en hojas limpias se descartó para no
rediseñar 4 formatos e imports a la vez.

## 4. Archivos viejos: `tools/csv_to_xlsx.py`

La app **solo lee `.xlsx`** (decisión: no mantener dos ramas de lectura). Lo viejo se
convierte una vez:

```
python tools/csv_to_xlsx.py <carpeta> [--dry-run] [--force]
```

Recorre la carpeta recursivo y escribe cada `.xlsx` **al lado** de sus CSV; **nunca borra
ni modifica los CSV**. Si el `.xlsx` ya existe lo salta (`--force` lo reescribe).

- Tripletes PCR agrupados por `(prefijo, timestamp)` → `<prefijo>pcr_data_<ts>.xlsx` con
  las hojas que existan (corridas con solo el archivo de temperatura, como las copias de
  `files_test/`, convierten igual). La metadata vieja va **completa** a la fila `prefix`
  (no se parte, mismo motivo de arriba), más `converted_from | csv`; el encabezado de
  `temperature` sale del `cols:` del prefijo o, si no lo trae, de nombres genéricos. Sin
  hoja `settings`: esas corridas no la registraban.
- Exports de análisis detectados **por encabezado** y emparejados con su hermano; un
  `_curves`/`_spectra`/`_rates` suelto se convierte solo.
- CSV únicos de la app (`<method>_data_*`, `photoreceptor_data_*`, `temperature_log_*`,
  `unified_*`, `data_temps*`) → hoja `data`. Lo demás se lista como "not recognized".

**Verificado** sobre copias de OneDrive `FilesCodes/PCR` + `PCR_temp_temocouple` +
`files_test/` + `files/` (184 libros, 0 fallos): los loaders de HEAD leyendo el CSV y los
nuevos leyendo el xlsx convertido dan **exactamente** lo mismo (`==`) en 129 corridas PCR
(temperatura + fotodetector), 13 archivos EIS y 2 bundles PCR.

## 5. Lectores fuera de la app

- `files_test/ajuste_21oct/` (gitignored): `runio.py` da `read_temps(path, names)` (hoja
  `temperature` por posición), `meta_line(path)` (la metadata como la línea 0 del CSV
  viejo, para que las regex de `fingerprint.py`/`ir_vs_tc.py` sigan igual; en convertidas
  es el `prefix`) y `run_settings(path)`. `ident2.py` toma la sintonización de la hoja
  `settings` si no se le pasa `settings.json`. Al migrarlos apareció un bug: `an_osc.py`,
  `an_run.py` y `plot_run.py` pasaban 5 nombres a archivos de 6 columnas y pandas usaba la
  primera como índice (columnas corridas); `read_temps` lee por posición y lo corrige.
- **No se migraron** (datos congelados en CSV): notebooks del paper,
  `analysis_plots.ipynb`, `analysis_fluorescense_test.py`.
- `ClientUDP.initial_file`/`save_data_file` siguen escribiendo CSV pero son código muerto
  (nadie los llama).

## 6. Decisiones (grill-me)

26/10/2026 (paso a xlsx):

- **Todo** a xlsx, también los guardados que ya eran un solo CSV (uniformidad).
- `openpyxl` directo (ligero, lee y escribe); pandas descartado en la app (pesado en el Pi
  y el código no lo usa); xlsxwriter descartado (no lee → dos dependencias).
- La app lee **solo xlsx** + conversor CLI de una vez (no botón: es una migración).
- Metadata PCR como pares clave/valor desde el origen; hoja `settings` con el
  `settings.json` completo.
- EmStat: `data` + `runs` por corrida.
- Exports: una hoja por archivo anterior, sin reestructurar.
- Pestañas manuales: solo `data`.
- Respaldo CSV + aviso solo en el guardado automático PCR.

Anteriores (carpetas por método):

- **Subcarpetas dentro de `files/`**, no carpetas de primer nivel: `files/` ya está
  gitignoreado y es la convención existente.
- **CA incluido** aunque se pidieron PCR/SQWV/CV/EIS: el guardado electroquímico es
  genérico por `self.method`.
- **Diálogo de guardado NO forzado**: solo cambia el `initialdir`.
- **Nombres con prefijo de método/slug** (`cv_data_…`, `<slug>_pcr_data_…`): red de
  seguridad si un archivo se mueve fuera de su carpeta.
- **Guard `dev` respetado** en `ClientUDP`: en dev el early-return sigue antes de tocar
  disco.
- Los diálogos de import/export de análisis quedan **sin** `initialdir` forzado: son
  archivos que el usuario gestiona aparte.

## 7. Pendiente (HW)

- [ ] `pip install openpyxl` en el Pi y una corrida PCR real: confirmar el `.xlsx`, el
  tiempo de escritura al final y que el respaldo CSV no se dispara.
- [ ] Convertir `files/` del Pi y las carpetas de OneDrive con `tools/csv_to_xlsx.py`.

__author__ = "Edisson A. Naula"
__date__ = "$ 26/10/2026 $"
