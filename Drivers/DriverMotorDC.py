# -*- coding: utf-8 -*-
__author__ = "Edisson A. Naula"
__date__ = "$ 03/nov/2025 at 14:02 $"

import gpiod
from time import sleep


class MotorBTS7960:
    def __init__(self, en, gpio_rpwm=13, gpio_lpwm=12, chip="/dev/gpiochip0"):
        """
        Constructor para el driver BTS7960 usando gpiod.

        :param en: Pin enable
        :param gpio_rpwm: Pin RPWM (por defecto GPIO 18).
        :param gpio_lpwm: Pin LPWM (por defecto GPIO 12).
        :param chip: Ruta al chip GPIO (por defecto /dev/gpiochip0).
        """
        self.enable = en
        self.rpwm = gpio_rpwm
        self.lpwm = gpio_lpwm
        self.chip = gpiod.Chip(chip)

        # Solicita líneas como salida
        self.line_enable = self.chip.get_line(self.enable)
        self.line_rpwm = self.chip.get_line(self.rpwm)
        self.line_lpwm = self.chip.get_line(self.lpwm)

        self.line_enable.request(consumer="motor_en", type=gpiod.LINE_REQ_DIR_OUT)
        self.line_rpwm.request(consumer="motor_rpwm", type=gpiod.LINE_REQ_DIR_OUT)
        self.line_lpwm.request(consumer="motor_lpwm", type=gpiod.LINE_REQ_DIR_OUT)

        # Habilita el motor
        self.line_enable.set_value(1)
        print(f"Motor habilitado en los pines EN={self.enable}, RPWM={self.rpwm}, LPWM={self.lpwm}")

    def avanzar(self, velocidad):
        print(f"Avanzando a {velocidad}%")
        self._set_pwm(self.line_rpwm, velocidad)
        self._set_pwm(self.line_lpwm, 0)

    def retroceder(self, velocidad):
        print(f"Retrocediendo a {velocidad}%")
        self._set_pwm(self.line_lpwm, velocidad)
        self._set_pwm(self.line_rpwm, 0)

    def detener(self):
        print("Deteniendo motor")
        self._set_pwm(self.line_rpwm, 0)
        self._set_pwm(self.line_lpwm, 0)

    def _set_pwm(self, line, velocidad):
        # PWM por software básico (bloqueante)
        duty = max(0, min(100, velocidad)) / 100.0
        period = 0.01  # 10 ms → 100 Hz

        # Simula PWM por software durante 1 segundo
        for _ in range(100):
            line.set_value(1)
            sleep(period * duty)
            line.set_value(0)
            sleep(period * (1 - duty))

    def limpiar(self):
        self.detener()
        self.line_enable.set_value(0)
        print("Motor deshabilitado y líneas liberadas.")


# Ejemplo de uso
if __name__ == "__main__":
    motor = MotorBTS7960(en=23, gpio_rpwm=18, gpio_lpwm=12)

    try:
        motor.avanzar(50)
        sleep(1)
        motor.retroceder(75)
        sleep(1)
        motor.detener()
    finally:
        motor.limpiar()