# -*- coding: utf-8 -*-
import json
__author__ = "Edisson A. Naula"
__date__ = "$ 08/10/2025  at 11:20 a.m. $"


def validar_entero(valor: str|int, minimo: int, maximo: int) -> tuple[bool, int|str]:
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


def validar_flotante(valor: str|float, minimo: float, maximo: float) -> tuple[bool, float|str]:
    """ Validate float value

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


def read_settings_from_file(file_path: str="resources/settings.json") -> dict:
    try:
        with open(file_path, 'r') as file:
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
        with open(file_path, 'w') as file:
            json.dump(settings, file, indent=4)
    except Exception as e:
        print(f"Error writing to settings file '{file_path}': {e}")
        return False
    return True

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
        (1e-9,  "n"),
        (1e-6,  "u"),
        (1e-3,  "m"),
        (1,     ""),     # unidad
        (1e3,   "k"),
        (1e6,   "M"),
        (1e9,   "G"),
        (1e12,  "T"),
        (1e15,  "P"),
        (1e18,  "E"),
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
    if abs(scaled) < 1:
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