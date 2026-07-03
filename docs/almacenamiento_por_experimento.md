# Almacenamiento de datos por experimento

Los CSV generados por la app se ordenan en subcarpetas de `files/` **por método**,
en lugar de caer todos planos en `files/`.

## Estructura

```
files/
  PCR/    ← temperatura + fotodetector del ciclador, y temps UDP crudos
  CV/
  SQWV/
  EIS/
  CA/
```

El nombre de carpeta es el método en **mayúsculas**. Los datos de temperatura del
disco (broadcast UDP) pertenecen conceptualmente a PCR, así que van a `files/PCR/`.

## Helper único

Todo pasa por un solo punto de verdad en
[templates/utils.py](../templates/utils.py):

```python
experiment_dir(method) -> "files/<METODO>"   # crea la carpeta (makedirs) y la devuelve
```

Recibe el método en cualquier caja (`"cv"`, `"sqwv"`, `"eis"`, `"ca"`, `"pcr"`) y
garantiza `os.makedirs(..., exist_ok=True)` antes de devolver la ruta. Si mañana
cambia la estructura, se toca **solo** esta función.

## Puntos de escritura / lectura afectados

| Sitio | Rol | Cambio |
| --- | --- | --- |
| [ui/EventEmstatFrame.py](../ui/EventEmstatFrame.py) `save_data` | guardado CV/SQWV/EIS/CA (diálogo "Save as") | `initialdir=experiment_dir(self.method)`; el diálogo **sigue libre** (el usuario puede navegar a otro lado) |
| [ui/EventEmstatFrame.py](../ui/EventEmstatFrame.py) `load_data` | carga sobre el plot | `initialdir=experiment_dir(self.method)` |
| [ui/PcrFrame.py](../ui/PcrFrame.py) `save_data_temps_file` | 3 CSV PCR (sin diálogo) | prefijo `experiment_dir("pcr")` |
| [Drivers/ClientUDP.py](../Drivers/ClientUDP.py) `initial_file` / `save_data_file` | temps UDP crudos (sin diálogo) | `experiment_dir("pcr")` **después** del guard `dev` (no crea carpeta en dev) |
| [ui/analysis/pcr.py](../ui/analysis/pcr.py) `load_csv` | análisis PCR | `initialdir=experiment_dir("pcr")` |
| [ui/analysis/sqwv.py](../ui/analysis/sqwv.py) `load_csv` | análisis SWV | `initialdir=experiment_dir("sqwv")` |
| [ui/analysis/eis.py](../ui/analysis/eis.py) `load_csv` | análisis EIS | `initialdir=experiment_dir("eis")` |
| [ui/analysis/peaks.py](../ui/analysis/peaks.py) `load_csv` | pestaña "Peaks (CV)" | `initialdir=experiment_dir("cv")` |

## Decisiones (grill-me)

- **Subcarpetas dentro de `files/`**, no carpetas de primer nivel: `files/` ya está
  gitignoreado y es la convención existente.
- **CA incluido** aunque el usuario listó solo PCR/SQWV/CV/EIS: el guardado
  electroquímico es genérico por `self.method`, darle carpeta evita un hueco futuro.
- **Diálogo de guardado NO forzado** (opción A): solo cambia el `initialdir`; el
  usuario conserva libertad para exportar fuera de la carpeta.
- **Nombres de archivo intactos**, con su prefijo de método/slug (`cv_data_…`,
  `<slug>_temperature_data_…`): red de seguridad si un CSV se mueve fuera de su
  carpeta. Solo cambia la carpeta contenedora.
- **Sin migración** de los CSV viejos planos en `files/`: es data cruda gitignoreada;
  mover por prefijo de nombre es arriesgado y queda fuera del alcance del código.
- **Guard `dev` respetado** en `ClientUDP`: no se añaden escrituras (ni `makedirs`)
  que ignoren el flag; en dev el early-return sigue antes de tocar disco.
- `import_analysis` / export de bundles `_curves.csv` quedan **sin** `initialdir`
  forzado: son archivos de análisis que el usuario gestiona aparte.

__author__ = "Edisson A. Naula"
