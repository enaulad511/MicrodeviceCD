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
DEFAULT_SETTINGS = {
    "version": "0.1.0",
    "pidControllerRPM": {
        "KP_denat": 1.2,
        "win_denat": 0.05,
        "m_age_denat": 0.1,
        "m_age_min_denat": 0.02,
        "m_age_max_denat": 0.2,
        "KP_h_denat": 0.2,
        "win_h_denat": 0.09,
        "KI_denat": 0.6,
        "imax_denat": 0.6,
        "tband_denat": 0.01,
        "ff_frac_denat": 0.8,
        "imax_h_denat": 0.55,
        "tband_h_denat": 0.05,
        "KP_high": 0.9,
        "win_high": 0.09,
        "m_age_high": 0.09,
        "m_age_min_high": 0.02,
        "m_age_max_high": 0.2,
        "tband_high": 0.02,
        "KI_high": 0.9,
        "ff_frac_high": 0.8,
        "imax_high": 0.5,
        "KP_h_high": 0.5,
        "win_h_high": 0.05,
        "KI_h_high": 0.9,
        "imax_h_high": 0.5,
        "tband_h_high": 0.03,
        "KP_h_low": 0.1,
        "win_h_low": 0.05,
        "KI_h_low": 0.2,
        "imax_h_low": 0.5,
        "tband_h_low": 0.02,
        "KP_h_ext": 0.1,
        "win_h_ext": 0.09,
        "KI_h_ext": 0.5,
        "imax_h_ext": 0.5,
        "tband_h_ext": 0.02,
        "kp": 0.0005,
        "ki": 0.0002,
        "kd": 0.001,
        "max": 35.0,
        "min": 14.0,
        "acceleration_spin": 300.0,
        "ts_pcr": 0.1,
    },
    "ads_fsr": 0.256,
    "photoreceptor": {"use_diff": 1.0},
    "windows_pcr": 1500.0,
}


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
