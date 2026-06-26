# -*- coding: utf-8 -*-
"""Almacén de "proyectos" electroquímicos: recetas con nombre por método.

Replica el principio de ``templates/pcr_projects.py`` pero parametrizado por
método (``cv`` / ``sqwv`` / ``eis``). A diferencia de PCR (una sola lista de 12
entradas), aquí cada método tiene su PROPIO conjunto de claves canónicas, su
semilla ``Default`` y su snapshot ``_last_run``, porque los formularios de CV,
SQWV y EIS son disjuntos: una receta de CV no puede cargarse en el formulario de
EIS. Los proyectos guardan el ESTADO COMPLETO del formulario (entradas de texto,
selección de rango de corriente, ajustes de motor en CV, flag de medición en
SQWV, y los dos comboboxes de modo en EIS como cadenas legibles).

El canal de electrodo NO se guarda: vive en el selector compartido del padre
``ElectrochemicalFrame`` (es cableado de hardware, no parte de la receta).

Persiste en un único archivo ``resources/electrochem_projects.json`` con una
sección por método (mismo patrón de claves reservadas ``_`` que PCR)::

    {
        "cv":   { "_last_used", "_last_run", "Default", "<proyecto>" },
        "sqwv": { ... },
        "eis":  { ... }
    }

Las claves reservadas empiezan con ``_`` y nunca son nombres de proyecto.
"""

import json

from templates.utils import read_settings_from_file

__author__ = "Edisson A. Naula"
__date__ = "$ 22/06/2026 at 11:30 a.m. $"


PROJECTS_PATH = "resources/electrochem_projects.json"

LAST_USED_KEY = "_last_used"
LAST_RUN_KEY = "_last_run"
LAST_RUN_LABEL = "« Last run »"
DEFAULT_PROJECT_NAME = "Default"


# --------------------------------------------------------------------------- #
# Validadores por método. Cada uno valida SOLO las claves numéricas pertinentes
# (las selecciones/flags se aceptan tal cual). Devuelven (ok, mensaje).
# --------------------------------------------------------------------------- #
def _check_numeric(values: dict, float_keys, int_keys=()) -> tuple[bool, str]:
    for key in float_keys:
        raw = str(values.get(key, "")).strip()
        if raw == "":
            return False, f"Empty value for '{key}'."
        try:
            float(raw)
        except ValueError:
            return False, f"Invalid number for '{key}': '{raw}'."
    for key in int_keys:
        raw = str(values.get(key, "")).strip()
        if raw == "":
            return False, f"Empty value for '{key}'."
        try:
            int(float(raw))
        except ValueError:
            return False, f"Invalid integer for '{key}': '{raw}'."
    return True, ""


# ---- CV ---- #
CV_KEYS = [
    "t_equil",
    "E_begin",
    "E_vertex1",
    "E_vertex2",
    "E_step",
    "scan_rate",
    "n_scans",
    "max_bw",
    "min_pot",
    "max_pot",
    "current_range",
    "motor_enable",
    "motor_angle",
    "motor_speed",
]
CV_DEFAULTS = {
    "t_equil": "0",
    "E_begin": "0.0",
    "E_vertex1": "-0.4",
    "E_vertex2": "0.7",
    "E_step": "0.01",
    "scan_rate": "0.04",
    "n_scans": "4",
    "max_bw": "2937500e-9",
    "min_pot": "-0.4",
    "max_pot": "0.7",
    "current_range": "4.7e-8",
    "motor_enable": "False",
    "motor_angle": "10",
    "motor_speed": "7",
}
_CV_FLOAT = [
    "t_equil",
    "E_begin",
    "E_vertex1",
    "E_vertex2",
    "E_step",
    "scan_rate",
    "max_bw",
    "min_pot",
    "max_pot",
    "current_range",
    "motor_angle",
    "motor_speed",
]


def _validate_cv(values: dict) -> tuple[bool, str]:
    return _check_numeric(values, _CV_FLOAT, int_keys=("n_scans",))


# ---- SQWV ---- #
SQWV_KEYS = [
    "t_equil",
    "E_begin",
    "E_end",
    "E_step",
    "amplitude",
    "freq",
    "max_bw",
    "min_da",
    "max_da",
    "E_con",
    "t_con",
    "E_dep",
    "t_dep",
    "measure",
    "current_range",
]
SQWV_DEFAULTS = {
    "t_equil": "0",
    "E_begin": "-0.5",
    "E_end": "0.5",
    "E_step": "0.01",
    "amplitude": "0.1",
    "freq": "20",
    "max_bw": "234021e-3",
    "min_da": "-0.6",
    "max_da": "0.6",
    "E_con": "0",
    "t_con": "0",
    "E_dep": "0",
    "t_dep": "0",
    "measure": "False",
    "current_range": "4.7e-8",
}
_SQWV_FLOAT = [
    "t_equil",
    "E_begin",
    "E_end",
    "E_step",
    "amplitude",
    "freq",
    "max_bw",
    "min_da",
    "max_da",
    "E_con",
    "t_con",
    "E_dep",
    "t_dep",
    "current_range",
]


def _validate_sqwv(values: dict) -> tuple[bool, str]:
    return _check_numeric(values, _SQWV_FLOAT)


# ---- EIS ---- #
EIS_KEYS = [
    "E_con1",
    "t_con1",
    "E_con2",
    "t_con2",
    "E_dc",
    "E_ac",
    "E_begin",
    "E_step",
    "E_end",
    "E_ac_edc",
    "E_dc_time",
    "t_run",
    "t_interval",
    "E_ac_time",
    "f_max",
    "f_min",
    "n_freq",
    "freq_fixed",
    "scan_type",
    "freq_type",
]
EIS_DEFAULTS = {
    "E_con1": "0",
    "t_con1": "0",
    "E_con2": "0",
    "t_con2": "0",
    "E_dc": "0.2",
    "E_ac": "0.01",
    "E_begin": "-0.5",
    "E_step": "0.05",
    "E_end": "0.5",
    "E_ac_edc": "0.01",
    "E_dc_time": "0.2",
    "t_run": "60",
    "t_interval": "1",
    "E_ac_time": "0.01",
    "f_max": "100000",
    "f_min": "100",
    "n_freq": "11",
    "freq_fixed": "1000",
    "scan_type": "Default",
    "freq_type": "Scan",
}
# Etiquetas de los comboboxes EIS (deben coincidir con SCAN_TYPES/FREQ_TYPES de
# ui/EisFrame.py). El validador usa estas para decidir qué grupo está activo.
_EIS_SCAN_DEFAULT = "Default"
_EIS_SCAN_EDC = "E_dc Scan"
_EIS_SCAN_TIME = "Time Scan"
_EIS_FREQ_SCAN = "Scan"
_EIS_FREQ_FIXED = "Fixed"


def _validate_eis(values: dict) -> tuple[bool, str]:
    # Pre-acondicionamiento siempre presente.
    float_keys = ["E_con1", "t_con1", "E_con2", "t_con2"]
    int_keys: list[str] = []
    scan = str(values.get("scan_type", _EIS_SCAN_DEFAULT))
    freq = str(values.get("freq_type", _EIS_FREQ_SCAN))
    # Solo el modo activo (decisión Q8): los campos del modo oculto pueden quedar
    # en sus defaults sin invalidar el guardado.
    if scan == _EIS_SCAN_EDC:
        float_keys += ["E_begin", "E_step", "E_end", "E_ac_edc"]
    elif scan == _EIS_SCAN_TIME:
        float_keys += ["E_dc_time", "t_run", "t_interval", "E_ac_time"]
    else:
        float_keys += ["E_dc", "E_ac"]
    if freq == _EIS_FREQ_FIXED:
        float_keys += ["freq_fixed"]
    else:
        float_keys += ["f_max", "f_min"]
        int_keys += ["n_freq"]
    return _check_numeric(values, float_keys, int_keys=int_keys)


# ---- CA ---- #
CA_KEYS = [
    "t_equil",
    "E_dc",
    "t_interval",
    "t_run",
    "max_bw",
    "current_range",
]
CA_DEFAULTS = {
    # Receta canónica del ejemplo (E_dc 0.5 V, intervalo 0.1 s, 10 s de corrida).
    # max_bw 58505e-3 -> "58505m" (valor de PSTrace; editable hasta automatizarlo).
    "t_equil": "0",
    "E_dc": "0.5",
    "t_interval": "0.1",
    "t_run": "10",
    "max_bw": "58505e-3",
    "current_range": "4.7e-8",
}
_CA_FLOAT = [
    "t_equil",
    "E_dc",
    "t_interval",
    "t_run",
    "max_bw",
    "current_range",
]


def _validate_ca(values: dict) -> tuple[bool, str]:
    return _check_numeric(values, _CA_FLOAT)


# --------------------------------------------------------------------------- #
# Registro de métodos: claves canónicas, defaults de fábrica y validador.
# --------------------------------------------------------------------------- #
METHODS: dict = {
    "cv": {"keys": CV_KEYS, "defaults": CV_DEFAULTS, "validate": _validate_cv},
    "sqwv": {"keys": SQWV_KEYS, "defaults": SQWV_DEFAULTS, "validate": _validate_sqwv},
    "eis": {"keys": EIS_KEYS, "defaults": EIS_DEFAULTS, "validate": _validate_eis},
    "ca": {"keys": CA_KEYS, "defaults": CA_DEFAULTS, "validate": _validate_ca},
}


def _spec(method: str) -> dict:
    spec = METHODS.get(method)
    if spec is None:
        raise ValueError(f"Unknown electrochemical method '{method}'.")
    return spec


def entry_keys(method: str) -> list[str]:
    """Claves canónicas (en orden) del método dado."""
    return list(_spec(method)["keys"])


def is_reserved(name: str) -> bool:
    """True si ``name`` es una clave reservada (no es un proyecto del usuario)."""
    return name.startswith("_")


def default_project(method: str) -> dict:
    """Diccionario de la receta de fábrica del método (copia)."""
    defaults = _spec(method)["defaults"]
    return {k: str(defaults[k]) for k in _spec(method)["keys"]}


def _normalize(method: str, values: dict) -> dict:
    """Proyecta ``values`` sobre las claves canónicas del método (relleno con
    el default cuando falte la clave). Garantiza que lo persistido sea cerrado."""
    defaults = _spec(method)["defaults"]
    return {k: str(values.get(k, defaults[k])) for k in _spec(method)["keys"]}


def validate_values(method: str, values: dict) -> tuple[bool, str]:
    """Valida las claves numéricas pertinentes del método (ver validadores)."""
    return _spec(method)["validate"](values)


# --------------------------------------------------------------------------- #
# I/O del archivo (estructura anidada por método)
# --------------------------------------------------------------------------- #
def _read_all() -> dict:
    return read_settings_from_file(PROJECTS_PATH)


def _write_all(data: dict) -> bool:
    """Sobrescribe el archivo completo (no hace merge: permite borrar claves)."""
    try:
        with open(PROJECTS_PATH, "w") as file:
            json.dump(data, file, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Error writing electrochem projects file '{PROJECTS_PATH}': {e}")
        return False
    return True


def _read_section(method: str) -> dict:
    data = _read_all()
    section = data.get(method)
    return section if isinstance(section, dict) else {}


def _write_section(method: str, section: dict) -> bool:
    data = _read_all()
    data[method] = section
    return _write_all(data)


def ensure_seeded(method: str) -> dict:
    """Garantiza que la sección del método exista con al menos ``Default``.

    Devuelve la sección (recién creada o existente).
    """
    data = _read_all()
    section = data.get(method)
    if not isinstance(section, dict):
        section = {DEFAULT_PROJECT_NAME: default_project(method)}
        data[method] = section
        _write_all(data)
    elif DEFAULT_PROJECT_NAME not in section:
        section[DEFAULT_PROJECT_NAME] = default_project(method)
        data[method] = section
        _write_all(data)
    return section


def project_names(method: str) -> list[str]:
    """Nombres de proyectos del usuario (sin reservados), Default primero."""
    section = _read_section(method)
    names = [k for k in section if not is_reserved(k)]
    names.sort(key=lambda n: (n != DEFAULT_PROJECT_NAME, n.lower()))
    return names


def has_last_run(method: str) -> bool:
    return LAST_RUN_KEY in _read_section(method)


def get_project(method: str, name: str) -> dict | None:
    """Receta de ``name`` (o del snapshot si name == LAST_RUN_KEY). None si no existe."""
    return _read_section(method).get(name)


def save_project(method: str, name: str, values: dict) -> bool:
    """Guarda/sobrescribe ``name`` con ``values`` (solo claves canónicas)."""
    if is_reserved(name):
        print(f"Refusing to save reserved project name '{name}'.")
        return False
    section = _read_section(method)
    section[name] = _normalize(method, values)
    return _write_section(method, section)


def delete_project(method: str, name: str) -> bool:
    """Borra ``name``. No permite borrar claves reservadas."""
    if is_reserved(name):
        return False
    section = _read_section(method)
    if name in section:
        del section[name]
        if section.get(LAST_USED_KEY) == name:
            del section[LAST_USED_KEY]
        return _write_section(method, section)
    return False


def set_last_used(method: str, name: str) -> bool:
    section = _read_section(method)
    section[LAST_USED_KEY] = name
    return _write_section(method, section)


def get_last_used(method: str) -> str | None:
    return _read_section(method).get(LAST_USED_KEY)


def snapshot_last_run(method: str, values: dict) -> bool:
    """Vuelca ``values`` al snapshot implícito _last_run (siempre sobrescrito)."""
    section = _read_section(method)
    section[LAST_RUN_KEY] = _normalize(method, values)
    return _write_section(method, section)


def resolve_initial(method: str) -> tuple[str, dict]:
    """Cascada de auto-carga al (re)crear el frame del método.

    Orden: _last_used (si apunta a algo cargable) -> _last_run -> primer proyecto
    con nombre -> Default. Devuelve (nombre, valores). El nombre puede ser
    LAST_RUN_KEY si la última corrida no estaba guardada con nombre.
    """
    section = ensure_seeded(method)
    last_used = section.get(LAST_USED_KEY)
    if last_used and last_used in section:
        return last_used, section[last_used]
    if LAST_RUN_KEY in section:
        return LAST_RUN_KEY, section[LAST_RUN_KEY]
    names = project_names(method)
    if names:
        return names[0], section[names[0]]
    return DEFAULT_PROJECT_NAME, default_project(method)


def export_project(method: str, name: str, dest_path: str) -> bool:
    """Exporta UN proyecto a un .json suelto, etiquetado con su método::

        {"method": "cv", "name": "...", "values": {...}}
    """
    values = get_project(method, name)
    if values is None:
        return False
    payload = {
        "method": method,
        "name": name,
        "values": _normalize(method, values),
    }
    try:
        with open(dest_path, "w") as file:
            json.dump(payload, file, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Error exporting project to '{dest_path}': {e}")
        return False
    return True


def import_project(method: str, src_path: str) -> dict:
    """Lee un .json exportado y valida que coincida el método.

    Devuelve un dict resultado::

        {"ok": True, "name": <sugerido>, "values": {...}}     # éxito
        {"ok": False, "error": "<mensaje legible>"}           # fallo

    Rechaza un archivo etiquetado con OTRO método (decisión Q12). Un dict plano
    sin etiqueta de método se acepta como fallback (se filtra a las claves del
    método destino), para archivos escritos a mano.
    """
    try:
        with open(src_path, "r") as file:
            payload = json.load(file)
    except Exception as e:
        return {"ok": False, "error": f"Invalid project file: {e}"}

    if not isinstance(payload, dict):
        return {"ok": False, "error": "Invalid project file: not an object."}

    if "values" in payload:
        file_method = payload.get("method")
        if file_method is not None and file_method != method:
            return {
                "ok": False,
                "error": (
                    f"This is a '{file_method}' project; cannot import into '{method}'."
                ),
            }
        name = str(payload.get("name", "Imported"))
        raw = payload["values"]
    else:
        # dict plano sin etiqueta: fallback tolerante.
        name = "Imported"
        raw = payload

    if not isinstance(raw, dict):
        return {"ok": False, "error": "Invalid project file: 'values' is not an object."}

    return {"ok": True, "name": name, "values": _normalize(method, raw)}
