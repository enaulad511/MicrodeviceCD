# -*- coding: utf-8 -*-
__author__ = "Edisson A. Naula"
__date__ = "$ 01/oct/2025  at 15:02 $"

from time import sleep, time

import RPi.GPIO as GPIO


class EncoderIncremental:
    def __init__(self, pin_a, pin_b, ppr=600):
        self.pin_a = pin_a
        self.pin_b = pin_b
        self.ppr = ppr
        self.position = 0
        self.last_time = time()
        self.last_position = 0
        self.rpm = 0

        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.pin_a, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(self.pin_b, GPIO.IN, pull_up_down=GPIO.PUD_UP)

        GPIO.add_event_detect(self.pin_a, GPIO.BOTH, callback=self._actualizar, bouncetime=1)

    def _actualizar(self, canal):
        estado_a = GPIO.input(self.pin_a)
        estado_b = GPIO.input(self.pin_b)

        if estado_a == estado_b:
            self.position += 1
        else:
            self.position -= 1

    def leer_posicion(self):
        return self.position

    def calcular_rpm(self):
        ahora = time()
        delta_t = ahora - self.last_time
        delta_p = self.position - self.last_position

        if delta_t > 0:
            revs = delta_p / self.ppr
            self.rpm = (revs / delta_t) * 60

        self.last_time = ahora
        self.last_position = self.position
        return round(self.rpm, 2)

    def limpiar(self):
        GPIO.remove_event_detect(self.pin_a)


if __name__ == "__main__":
    encoder = EncoderIncremental(pin_a=5, pin_b=6)  # Ajusta según tus GPIOs

    try:
        while True:
            print(f"Posición actual: {encoder.leer_posicion()}")
            sleep(0.1)

    except KeyboardInterrupt:
        print("Lectura detenida.")

    finally:
        encoder.limpiar()
