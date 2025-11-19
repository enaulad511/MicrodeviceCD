import gpiod
import threading
from time import sleep

class MotorBTS7960:
    def __init__(self, en, gpio_rpwm=13, gpio_lpwm=12, chip="/dev/gpiochip0"):
        """
        Inicializa el motor con los pines GPIO especificados.

        :param en: Pin GPIO para habilitar el motor.
        :param gpio_rpwm: Pin GPIO para controlar la velocidad de giro positiva.
        :param gpio_lpwm: Pin GPIO para controlar la velocidad de giro negativa.
        :param chip: Ruta del chip GPIO.
        """
        print("Inicializando motor...")
        self.enable = en
        self.rpwm = gpio_rpwm
        self.lpwm = gpio_lpwm
        self.chip = gpiod.Chip(chip)

        self.line_enable = self.chip.get_line(self.enable)
        self.line_rpwm = self.chip.get_line(self.rpwm)
        self.line_lpwm = self.chip.get_line(self.lpwm)

        self.line_enable.request(consumer="motor_en", type=gpiod.LINE_REQ_DIR_OUT)
        self.line_rpwm.request(consumer="motor_rpwm", type=gpiod.LINE_REQ_DIR_OUT)
        self.line_lpwm.request(consumer="motor_lpwm", type=gpiod.LINE_REQ_DIR_OUT)

        self.line_enable.set_value(1)
        print(f"Motor habilitado en EN={self.enable}, RPWM={self.rpwm}, LPWM={self.lpwm}")

        # Variables para PWM
        self._pwm_thread = None
        self._stop_event = threading.Event()

    def avanzar(self, velocidad):
        """
        Avanza el motor a la velocidad dada (0-100).
        """
        print(f"Avanzando a {velocidad}%")
        self._start_pwm(self.line_rpwm, velocidad, self.line_lpwm)

    def retroceder(self, velocidad):
        """
        Retrocede el motor a la velocidad dada.
        
        :param velocidad: Velocidad del motor (0-100).
        """
        print(f"Retrocediendo a {velocidad}%")
        self._start_pwm(self.line_lpwm, velocidad, self.line_rpwm)

    def detener(self):
        """
        Detiene el motor.
       
        """
        print("Deteniendo motor")
        self._stop_event.set()
        if self._pwm_thread:
            self._pwm_thread.join()
        self.line_rpwm.set_value(0)
        self.line_lpwm.set_value(0)

    def _start_pwm(self, active_line, velocidad, inactive_line):
        """
        Inicia el PWM en la línea activa con la velocidad dada.
            :param active_line: Línea GPIO activa para PWM.
            :param velocidad: Velocidad del motor (0-100).
            :param inactive_line: Línea GPIO inactiva que se apagará.
        """
        # Detener PWM anterior si existe
        self.detener()
        self._stop_event.clear()

        # Apagar la línea opuesta
        inactive_line.set_value(0)

        # Crear hilo para PWM
        self._pwm_thread = threading.Thread(target=self._pwm_loop, args=(active_line, velocidad), daemon=True)
        self._pwm_thread.start()

    def _pwm_loop(self, line, velocidad: float):
        """
        Bucle de PWM para la línea dada.

            :param line: Línea GPIO para PWM.
            :param velocidad: Velocidad del motor (0-100).
        """
        duty = max(0, min(100, velocidad)) / 100.0
        period = 0.01  # 100 Hz
        while not self._stop_event.is_set():
            line.set_value(1)
            sleep(period * duty)
            line.set_value(0)
            sleep(period * (1 - duty))

    def limpiar(self):
        """
            Limpia y libera los recursos del motor.
        """
        self.detener()
        self.line_enable.set_value(0)
        print("Motor deshabilitado y líneas liberadas.")

    def frenar(self):
        """
            Frena el motor inmediatamente. Tiempo de frenado de 5 ms.
        """
        print("Frenando motor (freno activo)")
        # Detener PWM si está activo
        self._stop_event.set()
        if self._pwm_thread:
            self._pwm_thread.join()
        # Ambas líneas en HIGH
        self.line_rpwm.set_value(1)
        self.line_lpwm.set_value(1)
        sleep(0.5)  # Tiempo de frenado
        self.line_rpwm.set_value(0)
        self.line_lpwm.set_value(0)


# Ejemplo de uso
if __name__ == "__main__":
    motor = MotorBTS7960(en=23, gpio_rpwm=13, gpio_lpwm=12)
    try:
        motor.avanzar(50)
        sleep(5)  # Motor avanza 5 segundos
        motor.retroceder(75)
        sleep(5)  # Motor retrocede 5 segundos
        motor.detener()
    finally:
        motor.limpiar()