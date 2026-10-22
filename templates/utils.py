# -*- coding: utf-8 -*-
import copy
import json
import os
import subprocess

__author__ = "Edisson A. Naula"
__date__ = "$ 08/10/2025  at 11:20 a.m. $"


# Esquema por defecto de settings.json. Solo se usa para RELLENAR claves ausentes
# (ver seed_default_settings): los valores locales existentes nunca se sobreescriben.
# Al añadir una clave nueva de configuración, agrégala aquí con su valor por defecto
# para que un dispositivo con un settings.json viejo (conservado tras `git pull` por
# el script update_repo) la auto-repare al arrancar.
# Las ganancias de pidControllerRPM son las AFINADAS EN EL EQUIPO (settings.json del Pi
# al 13/10/2026, docs/pcr_pendientes.md punto 11): un equipo nuevo o un archivo
# corrupto arranca con lo validado, no con valores de desarrollo.
DEFAULT_SETTINGS = {
    "version": "0.1.0",
    "pidControllerRPM": {
        "KP_denat": 1.9,
        "win_denat": 0.1,
        "m_age_denat": 0.2,
        "m_age_min_denat": 0.02,
        "m_age_max_denat": 0.2,
        "KP_h_denat": 1.2,
        "KI_h_denat": 0.5,
        "win_h_denat": 0.09,
        "KI_denat": 1.9,
        "imax_denat": 0.6,
        "tband_denat": 0.01,
        "ff_frac_denat": 0.8,
        "imax_h_denat": 0.55,
        "tband_h_denat": 0.05,
        "KP_high": 0.9,
        "win_high": 0.09,
        "m_age_high": 0.2,
        "m_age_min_high": 0.02,
        "m_age_max_high": 0.3,
        "tband_high": 0.1,
        "KI_high": 1.9,
        "ff_frac_high": 0.8,
        "imax_high": 0.5,
        "KP_h_high": 0.5,
        "win_h_high": 0.05,
        "KI_h_high": 1.3,
        "imax_h_high": 0.5,
        "tband_h_high": 0.02,
        "KP_h_low": 0.1,
        "win_h_low": 0.05,
        "KI_h_low": 0.2,
        "imax_h_low": 0.5,
        "tband_h_low": 0.02,
        # Rampa PI hacia ext_temp (fase "ext"). Valores = los fallbacks de
        # _load_phase_pid que regían cuando estas claves no existían.
        "KP_ext": 0.15,
        "win_ext": 0.09,
        "m_age_min_ext": 0.02,
        "m_age_max_ext": 0.2,
        "tband_ext": 0.05,
        "KI_ext": 0.5,
        "ff_frac_ext": 0.0,
        "imax_ext": 0.5,
        "KP_h_ext": 0.5,
        "win_h_ext": 0.02,
        "KI_h_ext": 1.3,
        "imax_h_ext": 0.5,
        "tband_h_ext": 0.02,
        "kp": 0.0005,
        "ki": 0.0002,
        "kd": 0.001,
        "max": 35.0,
        "min": 14.0,
        "acceleration_spin": 300.0,
        "ts_pcr": 0.1,
        # Ventana del watchdog "ambas caídas" de PCR (s sin lectura fresca de
        # ninguno de los dos sensores del par → detener). Ver PcrFrame.
        "temp_stale_s": 10.0,
        # Start-gate de PCR: espera máxima (s) por una primera lectura válida.
        "temp_start_wait_s": 3.0,
        # Salvaguarda de fases PCR (rampas/enfriamiento): se abandona la fase si
        # dura más de max(floor, factor × estimado), con estimado = ΔT × s/°C
        # (ramp_s_per_c al calentar, cool_s_per_c al enfriar).
        # factor 0 = desactivada; max_failed_cycles 0 = nunca abortar por racha.
        # Ver docs/pcr_timeout_fases.md.
        "phase_timeout_factor": 3.0,
        "phase_timeout_floor_s": 20.0,
        "ramp_s_per_c": 0.2,
        "cool_s_per_c": 1.0,
        "max_failed_cycles": 3.0,
        # Enfriamiento de PCR: el giro del motor para en cool_target + este margen
        # (°C) y el resto baja en pasivo. Ver docs/pcr_temperature_control.md.
        "cool_stop_margin_c": 5.5,
        # Frescura de la temperatura relativa a la cadencia medida: una lectura es
        # confiable hasta que la siguiente llega fresh_dt_factor veces tarde (con
        # tope fresh_age_cap_s). 0 = solo umbrales absolutos (m_age_*, ts_pcr).
        # Ver docs/pcr_temperature_control.md §9.
        "fresh_dt_factor": 1.5,
        "fresh_age_cap_s": 1.0,
    },
    "ads_fsr": 0.256,
    "photoreceptor": {"use_diff": 1.0},
    # Lectura de fluorescencia de PCR. Ventanas (s): espera tras el hold de
    # extensión, línea base (luz OFF), excitación (luz ON) y decaimiento (luz OFF);
    # muestreo: periodo dentro de cada ventana y lecturas del ADS por muestra.
    # Se leen una vez por corrida (PcrFrame._fluor_cfg). Ver docs/cambios_fluorescencia.md.
    "pcr_fluorescence": {
        "pre_sleep_s": 0.5,
        "baseline_s": 0.5,
        "light_s": 2.0,
        "post_s": 0.5,
        "sample_dt_s": 0.1,
        "averages": 4.0,
    },
    "windows_pcr": 1500.0,
    "temp_source": "thermocouple",
    # Control adaptativo de PCR (enabled 1 para activarlo; 0 = control clásico intacto).
    # Feed-forward de la potencia de régimen en los holds + corte de rampa por el calor
    # en vuelo aprendido del disco. Se lee una vez por corrida (PcrFrame._adaptive_cfg).
    # Ver docs/pcr_control_adaptativo.md.
    "pcr_adaptive": {
        "enabled": 0.0,
        "ff_slope": 0.0043,
        "ff_t0": 40.0,
        "ff_learn": 0.5,
        "hold_kp": 0.1,
        "hold_ki": 0.03,
        "hold_imax": 3.0,
        "hold_tband": 0.05,
        "hold_win": 0.05,
        "coast_init": 4.0,
        "coast_learn": 0.5,
        "coast_min": 0.5,
        "coast_max": 12.0,
        "coast_window_s": 8.0,
    },
}


# --- Fuente de temperatura (payload UDP del disco: t_amb:t_obj:t_tc) ---
# El broadcast trae tres temperaturas en este orden: ambiente y objeto del sensor
# IR (MLX90614) más la termocupla (MAX31855). El usuario elige cuál se usa en los
# experimentos. Se persiste la clave canónica en settings.json ("temp_source"),
# no el índice, para sobrevivir un reordenamiento futuro del payload. La lista está
# en orden de combobox; "thermocouple" primero = comportamiento por defecto previo.
TEMP_SOURCES = [
    ("thermocouple", "Thermocouple", 2),
    ("ir_object", "IR Object", 1),
    ("ir_ambient", "IR Ambient", 0),
]
DEFAULT_TEMP_SOURCE = "thermocouple"


def temp_source_labels() -> list[str]:
    """Etiquetas para el combobox, en orden (Thermocouple, IR Object, IR Ambient)."""
    return [label for _key, label, _idx in TEMP_SOURCES]


def temp_source_index(key_or_label: str) -> int:
    """Índice en el payload UDP (0=amb, 1=obj, 2=tc) para una clave o etiqueta."""
    for key, label, idx in TEMP_SOURCES:
        if key_or_label in (key, label):
            return idx
    return 2  # fallback: termocupla


def temp_source_label(key: str) -> str:
    """Etiqueta visible para una clave canónica."""
    for k, label, _idx in TEMP_SOURCES:
        if k == key:
            return label
    return "Thermocouple"


def temp_source_key(label: str) -> str:
    """Clave canónica para una etiqueta visible del combobox."""
    for key, lbl, _idx in TEMP_SOURCES:
        if lbl == label:
            return key
    return DEFAULT_TEMP_SOURCE


def temp_source_label_by_index(idx: int) -> str:
    """Etiqueta visible para un índice del payload UDP (0=amb, 1=obj, 2=tc).

    Usado por modos que iteran los tres campos a la vez (p. ej. Quick Control
    graficando las 3 temperaturas), donde se parte del índice y no de la clave.
    """
    for _key, label, i in TEMP_SOURCES:
        if i == idx:
            return label
    return "Thermocouple"


def read_temp_source(file_path: str = "resources/settings.json") -> str:
    """Clave de fuente de temperatura persistida (por defecto termocupla)."""
    key = read_settings_from_file(file_path).get("temp_source", DEFAULT_TEMP_SOURCE)
    if key not in (k for k, _l, _i in TEMP_SOURCES):
        return DEFAULT_TEMP_SOURCE
    return key


def write_temp_source(key: str, file_path: str = "resources/settings.json") -> bool:
    """Persiste la fuente elegida (merge, no pisa otras claves)."""
    if key not in (k for k, _l, _i in TEMP_SOURCES):
        key = DEFAULT_TEMP_SOURCE
    return write_settings_to_file({"temp_source": key}, file_path)


def experiment_dir(method: str) -> str:
    """Devuelve (y crea) el directorio de guardado para un experimento.

    Ordena los CSV por método en subcarpetas de ``files/`` (``files/CV``,
    ``files/SQWV``, ``files/EIS``, ``files/CA``, ``files/PCR``). El nombre de la
    carpeta es el método en mayúsculas; los datos de temperatura del ciclador
    (UDP) pertenecen conceptualmente a PCR.

    :param method: método del experimento (``"cv"``, ``"sqwv"``, ``"eis"``,
        ``"ca"``, ``"pcr"``); no distingue mayúsculas.
    :type method: str
    :return: ruta relativa de la carpeta, ya creada.
    :rtype: str
    """
    folder = os.path.join("files", str(method).upper())
    os.makedirs(folder, exist_ok=True)
    return folder


def validar_entero(valor: str | int, minimo: int, maximo: int) -> tuple[bool, int | str]:
    """Validate integer value

    :param valor: value to validate.
    :type valor: str | int
    :param minimo: minimun value to consider
    :type minimo: int
    :param maximo: maximun value to consider
    :type maximo: int
    :return: tuple with a flag and the value if correct or a message
    :rtype: tuple[bool, int|str]
    """
    try:
        numero = int(valor)
        if minimo <= numero <= maximo:
            return True, numero
        else:
            return False, f"El número debe estar entre {minimo} y {maximo}."
    except ValueError:
        return False, "El valor ingresado no es un número entero válido."


def validar_flotante(valor: str | float, minimo: float, maximo: float) -> tuple[bool, float | str]:
    """Validate float value

    :param valor: value to evaluate
    :type valor: str | float
    :param minimo: lower value to consider
    :type minimo: float
    :param maximo: upper value to consider
    :type maximo: float
    :return: flag and the value or a string
    :rtype: tuple[bool, float|str]
    """
    try:
        numero = float(valor)
        if minimo <= numero <= maximo:
            return True, numero
        else:
            return False, f"El número debe estar entre {minimo} y {maximo}."
    except ValueError:
        return False, "El valor ingresado no es un número decimal válido."


def read_settings_from_file(file_path: str = "resources/settings.json") -> dict:
    try:
        with open(file_path, "r") as file:
            settings: dict = json.load(file)
    except FileNotFoundError:
        print(f"Error: File '{file_path}' not found.")
        return {}
    except json.JSONDecodeError:
        print(f"Error: File '{file_path}' is not a valid JSON.")
        return {}
    return settings


def write_settings_to_file(new_settings: dict, file_path="resources/settings.json") -> bool:
    settings = read_settings_from_file(file_path)
    settings.update(new_settings)
    try:
        with open(file_path, "w") as file:
            json.dump(settings, file, indent=4)
    except Exception as e:
        print(f"Error writing to settings file '{file_path}': {e}")
        return False
    return True


def _merge_missing_defaults(target: dict, defaults: dict) -> bool:
    """Rellena en ``target`` las claves ausentes tomándolas de ``defaults``.

    Recursivo para sub-dicts (p. ej. ``pidControllerRPM``). Los valores locales
    existentes NUNCA se sobreescriben: solo se añaden claves que faltan. Devuelve
    ``True`` si mutó ``target`` (se agregó al menos una clave).
    """
    changed = False
    for key, dval in defaults.items():
        if key not in target:
            target[key] = copy.deepcopy(dval)
            changed = True
        elif isinstance(dval, dict) and isinstance(target[key], dict):
            if _merge_missing_defaults(target[key], dval):
                changed = True
    return changed


def seed_default_settings(file_path: str = "resources/settings.json") -> bool:
    """Auto-repara ``settings.json`` sembrando claves ausentes de DEFAULT_SETTINGS.

    Pensado para correr al arrancar la app: tras un ``git pull`` que conserva el
    ``settings.json`` local del dispositivo (ver script ``update_repo``, "local
    siempre gana"), las claves nuevas que trajo el update aparecen aquí con su
    valor por defecto —sin tocar ningún valor ya afinado localmente— para que
    sean visibles/editables en el archivo. Reescribe solo si faltaba algo (o si el
    archivo no existía / estaba corrupto, en cuyo caso siembra el set completo).
    Devuelve ``True`` si reescribió el archivo.
    """
    settings = read_settings_from_file(file_path)
    if not settings:
        # Ausente o corrupto → siembra el esquema completo por defecto.
        settings = copy.deepcopy(DEFAULT_SETTINGS)
        changed = True
    else:
        changed = _merge_missing_defaults(settings, DEFAULT_SETTINGS)
    if changed:
        try:
            with open(file_path, "w") as file:
                json.dump(settings, file, indent=4)
        except Exception as e:
            print(f"Error seeding settings file '{file_path}': {e}")
            return False
    return changed


def convert_si_integer_full(value):
    """
    Convierte cualquier número a la notación SI manteniendo SIEMPRE
    un entero antes del prefijo SI.

    - Usa TODOS los prefijos SI (a, f, p, n, u, m, , k, M, G, T, P, E)
    - Ajusta prefijo hacia arriba o hacia abajo hasta que el número sea entero.
    """

    if value == 0:
        return "0"

    # Tabla completa de prefijos SI
    PREFIXES = [
        (1e-18, "a"),
        (1e-15, "f"),
        (1e-12, "p"),
        (1e-9, "n"),
        (1e-6, "u"),
        (1e-3, "m"),
        (1, ""),  # unidad
        (1e3, "k"),
        (1e6, "M"),
        (1e9, "G"),
        (1e12, "T"),
        (1e15, "P"),
        (1e18, "E"),
    ]

    abs_v = abs(value)

    # Encontrar el prefijo SI inicial más razonable
    # el que deja el número entre 1 y 1000
    best_factor = 1
    best_prefix = ""

    for factor, prefix in PREFIXES:
        scaled = abs_v / factor
        if 1 <= scaled < 1000:
            best_factor = factor
            best_prefix = prefix
            break

    # Convertimos usando prefijo inicial
    scaled = value / best_factor
    # Si ya es entero → listo
    if abs(scaled - round(scaled)) < 1e-12:
        return f"{int(round(scaled))}{best_prefix}"
    # Si NO es entero → mover prefijo hacia algún lado hasta que lo sea
    index = [f for f, _ in PREFIXES].index(best_factor)
    # Elegir dirección según si scaled < 1 o > 1
    if abs(scaled) > 1:
        # usar prefijos más pequeños (m → u → n → p…)
        step = -1
    else:
        # usar prefijos más grandes ( → k → M → G…)
        step = 1
    # Ajustar hasta encontrar entero
    i = index
    while 0 <= i < len(PREFIXES):
        factor, prefix = PREFIXES[i]
        scaled = value / factor
        if abs(scaled - round(scaled)) < 1e-12:
            return f"{int(round(scaled))}{prefix}"
        i += step

    # Si no se encontró (extremadamente raro)
    # usar el prefijo más extremo posible
    factor, prefix = PREFIXES[-1 if step > 0 else 0]
    scaled = value / factor
    return f"{int(round(scaled))}{prefix}"


def show_keyboard(event=None):
    subprocess.Popen(["onboard"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


keyboard_process = None
keyboard_opening = False


def show_numeric_keyboard(event=None):
    global keyboard_process, keyboard_opening

    # Si ya está abierto o en proceso de abrirse, no hacer nada
    if keyboard_process and keyboard_process.poll() is None:
        return

    if keyboard_opening:
        return

    keyboard_opening = True

    try:
        keyboard_process = subprocess.Popen(
            ["onboard", "--layout", "Numeric"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    finally:
        keyboard_opening = False


def hide_keyboard(event=None):
    global keyboard_process
    if keyboard_process:
        keyboard_process.terminate()
        keyboard_process = None
