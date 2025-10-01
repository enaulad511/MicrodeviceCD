# -*- coding: utf-8 -*-
__author__ = "Edisson A. Naula"
__date__ = "$ 01/oct/2025  at 14:02 $"

import RPi.GPIO as GPIO
from time import sleep

import pigpio


class MotorDC:
    def __init__(self, gpio_in1, gpio_in2, gpio_pwm):
        """
            Constructor de la clase MotorDC.

        :param gpio_in1: Pin de entrada 1 del motor.
        :param gpio_in2: Pin de entrada 2 del motor.
        :param gpio_pwm: Pin de PWM del motor.
        """
        # GPIO.setmode(GPIO.BCM)
        self.in1 = gpio_in1
        self.in2 = gpio_in2
        self.pwm_pin = gpio_pwm
        self.pi = pigpio.pi()

        # Configura pines de dirección
        self.pi.set_mode(self.in1, pigpio.OUTPUT)
        self.pi.set_mode(self.in2, pigpio.OUTPUT)

        # Configura PWM por hardware
        self.pi.set_mode(self.pwm_pin, pigpio.OUTPUT)
        self.pi.set_PWM_frequency(self.pwm_pin, 1000)  # Frecuencia de 1 kHz

    def avanzar(self, velocidad):
        self.pi.write(self.in1, 1)
        self.pi.write(self.in2, 0)
        self._set_velocidad(velocidad)

    def retroceder(self, velocidad):
        self.pi.write(self.in1, 0)
        self.pi.write(self.in2, 1)
        self._set_velocidad(velocidad)

    def detener(self):
        self.pi.write(self.in1, 0)
        self.pi.write(self.in2, 0)
        self._set_velocidad(0)

    def _set_velocidad(self, velocidad):
        # velocidad: 0–100 → duty cycle 0–255
        duty = int(max(0, min(100, velocidad)) * 255 / 100)
        self.pi.set_PWM_dutycycle(self.pwm_pin, duty)

    def limpiar(self):
        self.detener()
        self.pi.stop()


if __name__ == "__main__":
    motor = MotorDC(gpio_in1=17, gpio_in2=27, gpio_pwm=18)  # PWM por hardware en GPIO18

    try:
        print("Avanzando...")
        motor.avanzar(60)
        sleep(2)

        print("Retrocediendo...")
        motor.retroceder(40)
        sleep(2)

        print("Detenido.")
        motor.detener()

    finally:
        motor.limpiar()