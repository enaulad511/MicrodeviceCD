# -*- coding: utf-8 -*-
"""Almacén de "proyectos" PCR: recetas con nombre de las 12 entradas visibles.

Un proyecto guarda SOLO los 12 valores que el operador edita en la UI de PCR
(no el tuning PID/ts/accel, que es calibración del equipo y vive en
``resources/settings.json``). Persiste en un archivo dedicado
``resources/pcr_projects.json`` separado de la calibración, de modo que
importar/exportar recetas nunca toque los parámetros de control del hardware.

Estructura del archivo::

    {
        "_last_used": "<nombre>",        # puntero al ultimo proyecto cargado
        "_last_run": { ...12 valores },  # snapshot implicito de la ultima corrida
        "Default": { ...12 valores },    # semilla de fabrica
        "<proyecto>": { ...12 valores }  # recetas con nombre del usuario
    }

Las claves reservadas empiezan con ``_`` y nunca son nombres de proyecto.
"""

import json

from templates.utils import read_settings_from_file

__author__ = "Edisson A. Naula"
__date__ = "$ 15/06/2026 at 11:30 a.m. $"


PROJECTS_PATH = "resources/pcr_projects.json"

LAST_USED_KEY = "_last_used"
LAST_RUN_KEY = "_last_run"
LAST_RUN_LABEL = "« Última corrida »"
DEFAULT_PROJECT_NAME = "Default"

# Orden y claves canonicas de las 12 entradas (mismo orden que los Entry de
# create_widgets_pcr en ui/PcrFrame.py). El indice en esta lista == indice del
# Entry correspondiente.
ENTRY_KEYS = [
    "high_temp",
    "low_temp",
    "time_high",
    "time_low",
    "cycles",
    "rpm_cooling",
    "denat_time",
    "denat_temp",
    "ext_time",
    "ext_temp",
    "ext_time_final",
    "initial_spin",
]

# Valores de fabrica (identicos a default_values en create_widgets_pcr).
DEFAULT_VALUES = ["94", "55", "15", "15", "3", "700", "30", "94", "6", "68", "300", "15"]

# Indice 4 (cycles) es entero; el resto son flotantes.
_INT_KEYS = {"cycles"}


def is_reserved(name: str) -> bool:
    """True si ``name`` es una clave reservada (no es un proyecto del usuario)."""
    return name.startswith("_")


def default_project() -> dict:
    """Diccionario de la receta de fabrica."""
    return dict(zip(ENTRY_KEYS, DEFAULT_VALUES))


def validate_values(values: dict) -> tuple[bool, str]:
    """Valida que los 12 valores sean numericos (int para cycles, float resto).

    :return: (ok, mensaje). Si ok, mensaje == "".
    """
    for key in ENTRY_KEYS:
        raw = str(values.get(key, "")).strip()
        if raw == "":
            return False, f"Empty value for '{key}'."
        try:
            if key in _INT_KEYS:
                int(raw)
            else:
                float(raw)
        except ValueError:
            return False, f"Invalid number for '{key}': '{raw}'."
    return True, ""


def _read() -> dict:
    return read_settings_from_file(PROJECTS_PATH)


def _write(data: dict) -> bool:
    """Sobrescribe el archivo completo (no hace merge: permite borrar claves)."""
    try:
        with open(PROJECTS_PATH, "w") as file:
            json.dump(data, file, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Error writing PCR projects file '{PROJECTS_PATH}': {e}")
        return False
    return True


def ensure_seeded() -> dict:
    """Garantiza que el archivo exista con al menos el proyecto Default.

    Devuelve el contenido (recien creado o existente).
    """
    data = _read()
    if not data:
        data = {DEFAULT_PROJECT_NAME: default_project()}
        _write(data)
    elif DEFAULT_PROJECT_NAME not in data:
        # El archivo existe pero perdio la semilla: la reponemos sin tocar lo demas.
        data[DEFAULT_PROJECT_NAME] = default_project()
        _write(data)
    return data


def project_names() -> list[str]:
    """Nombres de proyectos del usuario (sin claves reservadas), ordenados.

    Default siempre primero; el resto alfabetico.
    """
    data = _read()
    names = [k for k in data if not is_reserved(k)]
    names.sort(key=lambda n: (n != DEFAULT_PROJECT_NAME, n.lower()))
    return names


def has_last_run() -> bool:
    return LAST_RUN_KEY in _read()


def get_project(name: str) -> dict | None:
    """Receta de ``name`` (o del snapshot si name == LAST_RUN_KEY). None si no existe."""
    return _read().get(name)


def save_project(name: str, values: dict) -> bool:
    """Guarda/sobrescribe ``name`` con ``values`` (solo las claves canonicas)."""
    if is_reserved(name):
        print(f"Refusing to save reserved project name '{name}'.")
        return False
    data = _read()
    data[name] = {k: str(values.get(k, "")) for k in ENTRY_KEYS}
    return _write(data)


def delete_project(name: str) -> bool:
    """Borra ``name``. No permite borrar claves reservadas."""
    if is_reserved(name):
        return False
    data = _read()
    if name in data:
        del data[name]
        if data.get(LAST_USED_KEY) == name:
            del data[LAST_USED_KEY]
        return _write(data)
    return False


def set_last_used(name: str) -> bool:
    data = _read()
    data[LAST_USED_KEY] = name
    return _write(data)


def get_last_used() -> str | None:
    return _read().get(LAST_USED_KEY)


def snapshot_last_run(values: dict) -> bool:
    """Vuelca ``values`` al snapshot implicito _last_run (siempre sobrescrito)."""
    data = _read()
    data[LAST_RUN_KEY] = {k: str(values.get(k, "")) for k in ENTRY_KEYS}
    return _write(data)


def resolve_initial() -> tuple[str, dict]:
    """Cascada de auto-carga al abrir la pestaña PCR.

    Orden: _last_used (si apunta a algo cargable) -> _last_run -> primer proyecto
    con nombre -> Default. Devuelve (nombre, valores). El nombre puede ser
    LAST_RUN_KEY si la ultima corrida no estaba guardada con nombre.
    """
    data = ensure_seeded()
    last_used = data.get(LAST_USED_KEY)
    if last_used and last_used in data:
        return last_used, data[last_used]
    if LAST_RUN_KEY in data:
        return LAST_RUN_KEY, data[LAST_RUN_KEY]
    names = project_names()
    if names:
        return names[0], data[names[0]]
    return DEFAULT_PROJECT_NAME, default_project()


def export_project(name: str, dest_path: str) -> bool:
    """Exporta UN proyecto a un .json suelto: {"name": ..., "values": {...}}."""
    values = get_project(name)
    if values is None:
        return False
    payload = {"name": name, "values": {k: str(values.get(k, "")) for k in ENTRY_KEYS}}
    try:
        with open(dest_path, "w") as file:
            json.dump(payload, file, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Error exporting project to '{dest_path}': {e}")
        return False
    return True


def import_project(src_path: str) -> tuple[str, dict] | None:
    """Lee un .json de un proyecto exportado. Devuelve (nombre_sugerido, valores).

    Tolera tanto el formato {"name", "values"} como un dict plano de valores.
    NO escribe nada: el caller resuelve choque de nombre y luego llama save_project.
    """
    try:
        with open(src_path, "r") as file:
            payload = json.load(file)
    except Exception as e:
        print(f"Error importing project from '{src_path}': {e}")
        return None
    if isinstance(payload, dict) and "values" in payload:
        name = str(payload.get("name", "Imported"))
        raw = payload["values"]
    elif isinstance(payload, dict):
        name = "Imported"
        raw = payload
    else:
        return None
    values = {k: str(raw.get(k, "")) for k in ENTRY_KEYS}
    return name, values
