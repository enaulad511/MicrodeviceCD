# -*- coding: utf-8 -*-
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
