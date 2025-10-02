# -*- coding: utf-8 -*-
__author__ = "Edisson A. Naula"
__date__ = "$ 01/oct/2025  at 09:54 $"

from time import time, sleep

from Drivers.DriverEncoder import EncoderIncremental
from Drivers.DriverMotorDC import MotorDC

if __name__ == "__main__":
    motor = MotorDC(gpio_in1=17, gpio_in2=27, gpio_pwm=18)
    encoder = EncoderIncremental(pin_a=5, pin_b=6, ppr=600)

    try:
        motor.avanzar(100)
        inicio = time()

        while time() - inicio < 5:
            pos = encoder.leer_posicion()
            rpm = encoder.calcular_rpm()
            print(f"Posición: {pos} | RPM: {rpm}")
            sleep(0.2)

        motor.detener()

    except KeyboardInterrupt:
        print("Interrumpido por el usuario.")

    finally:
        motor.limpiar()
        encoder.limpiar()



