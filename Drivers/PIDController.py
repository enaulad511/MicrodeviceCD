# -*- coding: utf-8 -*-
__author__ = "Edisson Naula"
__date__ = "$ 18/11/2025 at 15:10 $"

from time import perf_counter


class PIDController:
    def __init__(self, kp, ki, kd, setpoint=0.0, output_limits=(None, None), ts=None):
        """
        Controlador PID con opción de tiempo fijo o dinámico.

        :param kp: Ganancia proporcional
        :param ki: Ganancia integral
        :param kd: Ganancia derivativa
        :param setpoint: Punto de referencia
        :param output_limits: Límites de salida (min, max)
        :param ts: Si se define, usa este tiempo fijo en segundos (ej. 0.01)
        """
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.setpoint = setpoint
        self.output_limits = output_limits
        self.fixed_dt = ts  # Si None, usa tiempo dinámico

        self._integral = 0.0
        self._last_error = None
        self._last_time = None

    def compute(self, measurement, current_time=None):
        error = self.setpoint - measurement

        # Tiempo actual con alta resolución
        if current_time is None:
            current_time = perf_counter()

        # Calcula dt
        if self.fixed_dt is not None:
            dt = self.fixed_dt
        else:
            dt = current_time - self._last_time if self._last_time is not None else 0.0

        # Proporcional
        p = self.kp * error

        # Integral
        if dt > 0:
            self._integral += error * dt
        i = self.ki * self._integral

        # Derivativo
        d = 0.0
        if self._last_error is not None and dt > 0:
            d = self.kd * (error - self._last_error) / dt

        # Actualiza estado
        self._last_error = error
        self._last_time = current_time

        # Salida
        output = p + i + d

        # Limitar salida
        if self.output_limits[0] is not None:
            output = max(self.output_limits[0], output)
        if self.output_limits[1] is not None:
            output = min(self.output_limits[1], output)

        return output


if __name__ == "__main__":
    pid = PIDController(kp=1.0, ki=0.1, kd=0.05, setpoint=100, output_limits=(0, 255), ts=0.01)
    ts = 0.01
    medicion = 50.0     
    salida = pid.compute(medicion)
    print(salida)       # tu función para aplicar PWM
