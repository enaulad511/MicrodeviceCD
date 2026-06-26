# Proyectos electroquímicos: recetas con nombre por método (CV / SQWV / EIS)

## Qué es

Réplica del principio de [proyectos PCR](pcr_proyectos.md) para la pestaña
**Electrochemical**. Antes, los formularios de CV, SQWV y EIS arrancaban siempre
con valores *hardcodeados* y no había forma de guardar/recuperar una
configuración de experimento. Ahora un **proyecto** es esa configuración con un
**nombre**: se guarda, carga, importa y exporta desde una barra arriba de las
entradas de cada frame, sin pantalla previa (panel integrado).

A diferencia de PCR (una sola lista de 12 entradas), aquí los proyectos son
**por método** (decisión Q1): CV, SQWV y EIS tienen formularios disjuntos —una
receta de CV no puede cargarse en EIS— así que cada método tiene su propia lista,
su semilla `Default` y su snapshot `_last_run`. Guardas/cargas proyectos de CV
estando en la sub-pestaña CV, de SQWV en SQWV, etc.

Un proyecto guarda el **estado completo del formulario** del método (decisión Q3):
todas las entradas de texto, la selección de rango de corriente, los ajustes de
motor (CV), el flag "measure i fwd/rev" (SQWV) y los **dos comboboxes de modo**
de EIS (scan type / freq type). El **canal de electrodo NO se guarda**
(decisión Q4): vive en el selector compartido del padre `ElectrochemicalFrame`
porque es cableado de hardware, no parte de la receta.

## Almacén: `resources/electrochem_projects.json`

Archivo **dedicado** (separado de `settings.json` y de `pcr_projects.json`),
manejado por [templates/electrochem_projects.py](../templates/electrochem_projects.py).
Estructura **anidada por método**, cada sección con el mismo patrón de claves
reservadas `_` que PCR:

```json
{
    "cv":   { "_last_used": "...", "_last_run": { ... }, "Default": { ... }, "<proyecto>": { ... } },
    "sqwv": { ... },
    "eis":  { ... }
}
```

- Claves reservadas empiezan con `_` y **nunca** son nombres de proyecto
  (`is_reserved`): `_last_used` (puntero al último proyecto cargado) y `_last_run`
  (snapshot implícito de la última corrida).
- Claves canónicas de cada método: `CV_KEYS` / `SQWV_KEYS` / `EIS_KEYS`, con sus
  `*_DEFAULTS` de fábrica (derivados de los constantes existentes de cada frame:
  `DEFAUL_VALUES_CV`, `DEFAULT`+`LABELS_PRE`, `DEF_*`).

## Backend genérico: un módulo, parametrizado por método

[templates/electrochem_projects.py](../templates/electrochem_projects.py) es
**un solo módulo** (decisión Q2) cuyas funciones públicas toman `method` como
primer argumento (`"cv"` / `"sqwv"` / `"eis"`). Refleja casi 1:1 a
`pcr_projects.py` (que queda intacto) pero opera sobre la sección del método:
`ensure_seeded`, `project_names`, `get_project`, `save_project`, `delete_project`,
`set_last_used`/`get_last_used`, `snapshot_last_run`, `resolve_initial`,
`export_project`, `import_project`.

El **registro de métodos** `METHODS` mapea cada método a `{keys, defaults,
validate}`. Las diferencias por método son pequeñas y viven ahí:

- **Validación por clave numérica** (decisión Q8): `validate_values(method,...)`
  valida solo las claves numéricas pertinentes (las selecciones/flags se aceptan
  tal cual). `n_scans` (CV) y `n_freq` (EIS) son enteros; el resto floats. Para
  **EIS se valida solo el modo activo** (`_validate_eis` lee `scan_type`/
  `freq_type` del propio dict y valida solo el grupo de campos visible).
- **Semilla `Default` por método** (decisión Q9): `ensure_seeded` repone una
  receta de fábrica reservada e indeleteable si falta.

## Barra de UI compartida: el mixin

[ui/ElectrochemProjectBar.py](../ui/ElectrochemProjectBar.py) implementa **toda**
la cola de UI común (decisión Q6) contra el backend genérico: el combobox + 4
botones (Save/Import/Export/Delete), el diálogo "Guardar como" (con `onboard` en
el Pi), la detección de cambios sin guardar, el mapeo de nombre legible
(`« Last run »`), el status propio de la barra y la cascada de auto-carga.

`ElectrochemProjectBarMixin` se mezcla en cada frame
(`class CVFrame(ElectrochemProjectBarMixin, ttk.Frame)`, etc.). El frame solo
aporta **tres cosas**:

- `project_method` — `"cv"` / `"sqwv"` / `"eis"` (atributo de clase).
- `collect_values() -> dict` — lee el estado completo del formulario.
- `apply_values(dict)` — vuelca un dict en los widgets.

La barra vive **dentro de cada frame hijo** (decisión Q5): como
`ElectrochemicalFrame.on_test_selected` **destruye y recrea** el frame al cambiar
de método, la barra se reconstruye y auto-carga el proyecto inicial de ESE método
en cada (re)creación.

Refs de wiring:
[ui/CvFrame.py](../ui/CvFrame.py),
[ui/SqwVFrame.py](../ui/SqwVFrame.py),
[ui/EisFrame.py](../ui/EisFrame.py) — cada uno: `build_project_bar(...)` en
`__init__`, `load_initial_project()` al final del `__init__`, y
`snapshot_current_run()` al inicio de su rutina de envío.

### Caso EIS: comboboxes y orden de `apply_values`

EIS es el más complejo: ~20 `StringVar` + dos comboboxes que muestran/ocultan
grupos de entradas. Los modos se guardan como **cadenas legibles** (decisión Q10:
`"scan_type": "E_dc Scan"`, `"freq_type": "Fixed"`), mapeadas de vuelta vía
`SCAN_TYPES`/`FREQ_TYPES`. Se guardan **todas** las vars (lossless, sin importar
el modo activo). El orden de `apply_values` importa: primero las `StringVar` (sus
`trace_add` recalculan val/dec y duración estimada), luego los comboboxes por
etiqueta, y por último `on_scan_type_changed`/`on_freq_type_changed` para mostrar
el grupo correcto, cerrando con un recompute explícito.

## Comportamiento de corrida: `_last_run` + cascada

- **Snapshot** (decisión Q7): al inicio de la rutina de envío de cada frame
  (`callback_send_script` en CV, `send_script` en SQWV/EIS) se llama
  `snapshot_current_run()`, que vuelca el estado actual a `_last_run` del método.
  Así `« Last run »` siempre refleja lo último ejecutado, aunque no se guardara
  con nombre. En EIS el snapshot va **después** de un `generate_payload()` válido.
- **Auto-carga**: `resolve_initial(method)` aplica la cascada
  `_last_used → _last_run → primer proyecto con nombre → Default` al
  (re)crear el frame.

## Import / export con guarda de método

`export_project` etiqueta el `.json` con su método:
`{"method": "cv", "name": ..., "values": {...}}`. `import_project` **rechaza** un
archivo etiquetado con otro método (decisión Q12), mostrando un status claro
("This is a 'cv' project; cannot import into 'eis'."). Un dict plano sin etiqueta
se acepta como fallback tolerante (se filtra a las claves del método destino),
para archivos escritos a mano. `import_project` devuelve
`{"ok": True, "name", "values"}` o `{"ok": False, "error"}`.

## Gap conocido: cambio de método sin guardar (decisión Q13)

Dentro de un frame, cambiar de proyecto en el combobox pregunta "¿descartar
cambios sin guardar?". Pero cambiar el **método** en el combobox del padre
(`ElectrochemicalFrame`) **destruye** el frame hijo, descartando silenciosamente
ediciones no guardadas ni enviadas (solo llegan a `_last_run` al enviar). Se
aceptó **no** poner guarda aquí por ahora, para no reintroducir el acoplamiento
padre↔hijo que el diseño evita. Si molesta, la mejora limpia sería auto-snapshot
a `_last_run` al destruir (no un diálogo).

__author__ = "Edisson A. Naula"
