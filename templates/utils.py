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


def read_settings_from_file(file_path: str="resources/settings.json") -> dict[str, int|float|str|dict[str, int|float|str]]:
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