# -*- coding: utf-8 -*-
import json
__author__ = "Edisson A. Naula"
__date__ = "$ 08/10/2025  at 11:20 a.m. $"


def validar_entero(valor, minimo, maximo):
    try:
        numero = int(valor)
        if minimo <= numero <= maximo:
            return True, numero
        else:
            return False, f"El número debe estar entre {minimo} y {maximo}."
    except ValueError:
        return False, "El valor ingresado no es un número entero válido."


def validar_flotante(valor, minimo, maximo):
    try:
        numero = float(valor)
        if minimo <= numero <= maximo:
            return True, numero
        else:
            return False, f"El número debe estar entre {minimo} y {maximo}."
    except ValueError:
        return False, "El valor ingresado no es un número decimal válido."


def read_settings_from_file(file_path="./resources/settings.json"):
    try:
        with open(file_path, 'r') as file:
            settings = json.load(file)
    except FileNotFoundError:
        print(f"Error: File '{file_path}' not found.")
        return {}
    except json.JSONDecodeError:
        print(f"Error: File '{file_path}' is not a valid JSON.")
        return {}
    return settings

def write_settings_to_file(new_settings: dict, file_path="./resources/settings.json"):
    settings = read_settings_from_file(file_path)
    settings.update(new_settings)
    try:
        with open(file_path, 'w') as file:
            json.dump(settings, file, indent=4)
    except Exception as e:
        print(f"Error writing to settings file '{file_path}': {e}")
        return False
    return True