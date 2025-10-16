# -*- coding: utf-8 -*-
__author__ = "Edisson A. Naula"
__date__ = "$ 01/oct/2025  at 14:02 $"

from time import sleep
import pigpio


class MotorL298N:
    def __init__(self, gpio_in1, gpio_in2, gpio_pwm):
        """
            Constructor de la clase MotorDC L298N Driver.

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
        self.pi.set_PWM_frequency(self.pwm_pin, 10000)  # Frecuencia de 1 kHz

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


class MotorBTS7960:
    def __init__(self, en, gpio_rpwm=18, gpio_lpwm=12,):
        """
        Constructor para el driver BTS7960 usando PWM por hardware.

        :param en: Pin enable
        :param gpio_rpwm: Pin RPWM (por defecto GPIO 18).
        :param gpio_lpwm: Pin LPWM (por defecto GPIO 12).
        """
        self.enable = en
        self.rpwm = gpio_rpwm
        self.lpwm = gpio_lpwm
        self.pi = pigpio.pi()

        # Configura pines como salida
        self.pi.set_mode(self.rpwm, pigpio.OUTPUT)
        self.pi.set_mode(self.lpwm, pigpio.OUTPUT)
        self.pi.set_mode(self.enable, pigpio.OUTPUT)

        # Configura frecuencia PWM por hardware
        self.pi.set_PWM_frequency(self.rpwm, 10000)
        self.pi.set_PWM_frequency(self.lpwm, 10000)

        # Habilitar ambos lados
        self.pi.write(self.enable, 1)

    def avanzar(self, velocidad):
        duty = self._calcular_duty(velocidad)
        self.pi.set_PWM_dutycycle(self.rpwm, duty)
        self.pi.set_PWM_dutycycle(self.lpwm, 0)

    def retroceder(self, velocidad):
        duty = self._calcular_duty(velocidad)
        self.pi.set_PWM_dutycycle(self.lpwm, duty)
        self.pi.set_PWM_dutycycle(self.rpwm, 0)

    def detener(self):
        self.pi.set_PWM_dutycycle(self.rpwm, 0)
        self.pi.set_PWM_dutycycle(self.lpwm, 0)

    def _calcular_duty(self, velocidad):
        return int(max(0, min(100, velocidad)) * 255 / 100)

    def limpiar(self):
        self.detener()
        self.pi.stop()
        self.pi.write(self.enable, 0)


if __name__ == "__main__":
    # motor = MotorL298N(gpio_in1=17, gpio_in2=27, gpio_pwm=18)  # PWM por hardware en GPIO18
    #
    # try:
    #     print("Avanzando...")
    #     motor.avanzar(60)
    #     sleep(2)
    #
    #     print("Retrocediendo...")
    #     motor.retroceder(40)
    #     sleep(2)
    #
    #     print("Detenido.")
    #     motor.detener()
    #
    # finally:
    #     motor.limpiar()

    # Crear instancia del motor con pines por defecto
    motor = MotorBTS7960()

    try:
        print("Avanzando a 50%...")
        motor.avanzar(50)
        sleep(2)

        print("Avanzando a 100%...")
        motor.avanzar(100)
        sleep(2)

        print("Retrocediendo a 75%...")
        motor.retroceder(75)
        sleep(2)

        print("Deteniendo motor...")
        motor.detener()
        sleep(1)

    finally:
        print("Limpiando recursos...")
        motor.limpiar()

