# -*- coding: utf-8 -*-
__author__ = "Edisson A. Naula"
__date__ = "$ 01/oct/2025 at 15:02 $"

from time import time, sleep
import pigpio


class EncoderIncremental:
    def __init__(self, pin_a, pin_b, ppr=600):
        self.state = 0
        self.pin_a = pin_a
        self.pin_b = pin_b
        self.ppr = ppr  # Pulsos por revolución
        self.position = 0
        self.last_time = time()
        self.last_position = 0
        self.rpm = 0
        self.revolutions = 0

        self.pi = pigpio.pi()
        if not self.pi.connected:
            raise IOError("No se pudo conectar con el daemon pigpio. ¿Está corriendo pigpiod?")

        self.pi.set_mode(self.pin_a, pigpio.INPUT)
        self.pi.set_mode(self.pin_b, pigpio.INPUT)
        self.pi.set_pull_up_down(self.pin_a, pigpio.PUD_UP)
        self.pi.set_pull_up_down(self.pin_b, pigpio.PUD_UP)

        self.callback_a = self.pi.callback(self.pin_a, pigpio.EITHER_EDGE, self._actualizar)
        self.callback_b = self.pi.callback(self.pin_b, pigpio.EITHER_EDGE, self._actualizar)

    # def _actualizar(self, gpio, level, tick):
    #     estado_a = self.pi.read(self.pin_a)
    #     estado_b = self.pi.read(self.pin_b)
    #
    #     if estado_a == estado_b:
    #         self.position += 1
    #     else:
    #         self.position -= 1

    def _actualizar(self, gpio, level, tick):
        # Leer los estados actuales de los pines
        s = self.state & 0b11  # Mantener los 2 bits anteriores

        if self.pi.read(self.pin_a):
            s |= 0b100
        if self.pi.read(self.pin_b):
            s |= 0b1000

        # Decodificar el movimiento según la tabla
        if s in [0b0000, 0b0101, 0b1010, 0b1111]:
            pass  # Sin movimiento
        elif s in [0b0001, 0b0111, 0b1000, 0b1110]:
            self.position += 1
        elif s in [0b0010, 0b0100, 0b1011, 0b1101]:
            self.position -= 1
        elif s in [0b0011, 0b1100]:
            self.position += 2
        else:
            self.position -= 2

        # Actualizar el estado anterior (solo los 2 bits más recientes)
        self.state = (s >> 2)

    def leer_posicion(self):
        """Devuelve la posición en pulsos"""
        return self.position

    def leer_grados(self):
        """Convierte la posición a grados en el rango [0, 360)"""
        grados = (self.position / self.ppr) * 360
        return grados % 360

    def leer_revoluciones(self):
        """Devuelve el número de revoluciones completas (puede ser decimal)"""
        return round(self.position / self.ppr, 2)

    def calcular_rpm(self):
        """Calcula las RPM basadas en el cambio de posición y tiempo"""
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
        """Cancela el callback y detiene pigpio"""
        try:
            if self.callback_a:
                self.callback_a.cancel()
            self.pi.stop()
        except Exception as e:
            print(f"Error al limpiar: {e}")


if __name__ == "__main__":
    encoder = EncoderIncremental(pin_a=5, pin_b=6)

    try:
        while True:
            print(f"Posición actual: {encoder.leer_posicion()}")
            sleep(0.1)

    except KeyboardInterrupt:
        print("Lectura detenida.")

    finally:
        encoder.limpiar()
