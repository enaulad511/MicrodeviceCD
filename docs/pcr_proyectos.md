# Proyectos PCR: recetas con nombre de las 12 entradas

## Qué es

Antes, las 12 entradas de la pestaña PCR (High/Low Temp, tiempos, ciclos, RPM,
denat, ext, initial spin) arrancaban siempre con valores por defecto
*hardcodeados* (`create_widgets_pcr`, [ui/PcrFrame.py](../ui/PcrFrame.py)) y no
había forma de guardar/recuperar una receta. Ahora un **proyecto** es esa receta
con un **nombre**: se guarda, se carga, se importa y se exporta desde una barra
nueva arriba de las entradas, sin pantalla previa (panel integrado).

Un proyecto guarda **solo las 12 entradas visibles** — lo que el biólogo edita
entre corridas. El tuning de control (ganancias PID por fase, `ts_pcr`,
`acceleration_spin`, `windows_pcr`, `photoreceptor.use_diff`) **no** entra en el
proyecto: es calibración del *equipo* (inercia térmica del disco, heater), vive
en `resources/settings.json` y se edita allí. Mezclar tuning por-protocolo
invitaría a regresiones silenciosas de calibración.

## Almacén: `resources/pcr_projects.json`

Archivo **dedicado**, separado de `settings.json`, manejado por
[templates/pcr_projects.py](../templates/pcr_projects.py). Que sea un archivo
aparte hace que import/export de recetas nunca toque la calibración del equipo.

```json
{
    "_last_used": "Protocolo COVID",
    "_last_run": { ...12 valores },
    "Default":  { ...12 valores },
    "Protocolo COVID": { ...12 valores }
}
```

- Claves reservadas empiezan con `_` y **nunca** son nombres de proyecto
  (`is_reserved`). Las dos reservadas:
  - **`_last_used`** — puntero al último proyecto cargado (para auto-cargarlo al
    abrir).
  - **`_last_run`** — *snapshot implícito* de la última corrida (ver abajo).
- Claves canónicas de cada receta: `ENTRY_KEYS` (mismo orden que los `Entry`; el
  índice en la lista == índice del `Entry`). `DEFAULT_VALUES` es la fuente única
  de la receta de fábrica y debe coincidir con `default_values` de
  `create_widgets_pcr`.
- `_write` **sobrescribe el archivo completo** (no hace merge como
  `write_settings_to_file`): es lo que permite *borrar* claves (delete project,
  limpiar `_last_used`). La lectura sí reusa `read_settings_from_file(path)`.

## Ciclo de vida

### Auto-carga al abrir (cascada)

`resolve_initial()` siembra el archivo si falta (`ensure_seeded` → crea
`Default`) y elige qué cargar en este orden:

1. `_last_used` (si apunta a algo cargable),
2. `_last_run` (la última corrida, aunque no se guardara con nombre),
3. primer proyecto con nombre (`Default` siempre primero),
4. `Default` de fábrica.

Se invoca desde `PCRFrame._load_initial_project`, **al final** de `__init__`
(necesita que `profile_frame`/`canvas` ya existan, porque cargar regenera la
preview). No persiste `_last_used` aquí: solo refleja lo ya elegido.

### Guardado explícito ("Save")

`_on_save_as` valida los 12 valores (`validate_values`: `int` para `cycles`,
`float` para el resto) **antes** de escribir — un proyecto guardado siempre debe
ser ejecutable. Pide nombre en un Toplevel modal ("Save project as") que lanza
`onboard` (teclado del SO) al enfocar el campo (`_launch_os_keyboard`, no-op
silencioso en dev/Windows). Si el nombre existe, **confirma sobrescritura**.

### Snapshot implícito en Start

Al pulsar ▶️Start, `callback_start_experiment` vuelca el estado actual de las 12
entradas a `_last_run` (`snapshot_last_run`, siempre sobrescrito) **antes** de
correr. Así "la última corrida" nunca se pierde aunque no se guardara con
nombre. En el combobox aparece como `« Última corrida »` (`LAST_RUN_LABEL`),
siempre arriba.

### Carga desde el combobox

El combobox es selector puro (read-only). `_on_project_selected` **carga al
seleccionar**, con guardia: si hay cambios sin guardar respecto al proyecto
activo (`_has_unsaved_changes`, compara entradas contra `_loaded_snapshot`),
pregunta "¿Descartar cambios y cargar 'X'?"; si se cancela, revierte la
selección al proyecto activo. `_do_load_project` escribe las entradas, fija el
baseline, persiste `_last_used` y regenera la preview.

### Borrar / Importar / Exportar

- 🗑️**Delete** (`_on_delete`): solo proyectos de usuario (no reservados), con
  confirmación. Tras borrar limpia `_last_used` si apuntaba ahí y recarga la
  cascada.
- 📁**Import** (`_on_import`): `filedialog.askopenfilename` → lee **un** proyecto
  (`import_project` tolera `{"name","values"}` o un dict plano), valida, pide
  nombre (resuelve choque con la misma confirmación de sobrescritura) y lo
  **añade** — nunca reemplaza la lista entera.
- 📤**Export** (`_on_export`): `filedialog.asksaveasfilename` → vuelca el
  proyecto activo a un `.json` suelto (`{"name","values"}`).

## Trazabilidad receta → datos

`experiment_pcr` antepone `project: <nombre>` al `prefix_col` que ya encabeza el
CSV de temperatura ([ui/PcrFrame.py](../ui/PcrFrame.py), `save_data_temps_file`).
Si corrió con entradas editadas a mano (proyecto activo == `_last_run` o `None`),
se marca `project: _last_run (sin guardar)`.

Además, **el nombre del proyecto activo prefija el nombre de archivo** de los tres
CSV: `files/<slug>_temperature_data_<ts>.csv`, `..._photodetector_data_...` y
`..._photodetector_raw_...`. El slug lo deriva `_project_slug(active_project_name)`:
el snapshot implícito (`_last_run`/`None`) cae a `last_run`, y cualquier carácter
fuera de `[A-Za-z0-9._-]` se neutraliza a `_` (sin transliterar acentos, colapsando
repeticiones; vacío → `last_run`). Se usa `active_project_name` tal cual —sin
detectar entradas editadas-pero-no-guardadas—, consistente con la etiqueta del
encabezado. El timestamp sigue garantizando unicidad por corrida.

## Layout y runtime

La barra de proyecto (`_build_project_bar`) vive en `content_frame` **row 0**,
arriba de las entradas (row 1) y los botones de experimento (row 2). Durante la
corrida se **oculta** junto con `frame_entries` (`grid_forget` en
`callback_start_experiment`; se restauran en `callback_stop_experiment`): no hay
nada que hacer con ella mientras corre, y el proyecto activo se ve en
`svar_status`.

__author__ = "Edisson A. Naula"
