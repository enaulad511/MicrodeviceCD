# -*- coding: utf-8 -*-
__author__ = "Edisson A. Naula"
__date__ = "$ 16/10/2025  at 10:47 a.m. $"

from time import time, sleep

from Drivers.DriverEncoder import EncoderIncremental
from Drivers.DriverMotorDC import MotorBTS7960

if __name__ == "__main__":
    # Pines del BTS7960
    motor = MotorBTS7960(en=23)

    # Pines del encoder
    encoder = EncoderIncremental(pin_a=5, pin_b=6, ppr=2400)

    try:
        motor.avanzar(10)  # velocidad entre 0 y 255
        inicio = time()

        while time() - inicio < 10:
            pos = encoder.leer_posicion()
            grados = encoder.leer_grados()
            rpm = encoder.calcular_rpm()
            print(f"Posición: {pos} | Grados: {grados:.2f}° | RPM: {rpm}")
            sleep(0.2)

        motor.detener()

    except KeyboardInterrupt:
        print("Interrumpido por el usuario.")

    finally:
        motor.limpiar()
        encoder.limpiar()
