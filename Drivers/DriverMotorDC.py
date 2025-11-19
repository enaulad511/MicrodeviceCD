import gpiod
import threading
from time import sleep
from gpiod.line import Direction, Value, LineSettings


class MotorBTS7960:
    def __init__(self, en, gpio_rpwm=13, gpio_lpwm=12, chip="/dev/gpiochip0"):
        """
        Inicializa el motor usando la nueva API de gpiod.
        """
        print("Inicializando motor...")
        self.enable = en
        self.rpwm = gpio_rpwm
        self.lpwm = gpio_lpwm

        # Configuración de líneas
        config = {
            self.enable: LineSettings(direction=Direction.OUTPUT, output_value=Value.INACTIVE),
            self.rpwm: LineSettings(direction=Direction.OUTPUT, output_value=Value.INACTIVE),
            self.lpwm: LineSettings(direction=Direction.OUTPUT, output_value=Value.INACTIVE),
        }

        # Solicita las líneas
        self.request = gpiod.request_lines(chip, consumer="motor-control", config=config)

        # Activa la línea EN
        self.request.set_value(self.enable, Value.ACTIVE)
        print(f"Motor habilitado en EN={self.enable}, RPWM={self.rpwm}, LPWM={self.lpwm}")

        # Variables para PWM
        self._pwm_thread = None
        self._stop_event = threading.Event()

    def avanzar(self, velocidad):
        print(f"Avanzando a {velocidad}%")
        self._start_pwm(self.rpwm, velocidad, self.lpwm)

    def retroceder(self, velocidad):
        print(f"Retrocediendo a {velocidad}%")
        self._start_pwm(self.lpwm, velocidad, self.rpwm)

    def detener(self):
        print("Deteniendo motor")
        self._stop_event.set()
        if self._pwm_thread:
            self._pwm_thread.join()
        self.request.set_value(self.rpwm, Value.INACTIVE)
        self.request.set_value(self.lpwm, Value.INACTIVE)

    def _start_pwm(self, active_line, velocidad, inactive_line):
        self.detener()
        self._stop_event.clear()
        self.request.set_value(inactive_line, Value.INACTIVE)
        self._pwm_thread = threading.Thread(target=self._pwm_loop, args=(active_line, velocidad), daemon=True)
        self._pwm_thread.start()

    def _pwm_loop(self, line, velocidad):
        duty = max(0, min(100, velocidad)) / 100.0
        period = 0.01  # 100 Hz
        while not self._stop_event.is_set():
            self.request.set_value(line, Value.ACTIVE)
            sleep(period * duty)
            self.request.set_value(line, Value.INACTIVE)
            sleep(period * (1 - duty))

    def limpiar(self):
        self.detener()
        self.request.set_value(self.enable, Value.INACTIVE)
        print("Motor deshabilitado y líneas liberadas.")

    def frenar(self):
        print("Frenando motor")
        self._stop_event.set()
        if self._pwm_thread:
            self._pwm_thread.join()
        self.request.set_value(self.rpwm, Value.ACTIVE)
        self.request.set_value(self.lpwm, Value.ACTIVE)
        sleep(0.5)
        self.request.set_value(self.rpwm, Value.INACTIVE)
        self.request.set_value(self.lpwm, Value.INACTIVE)


# Ejemplo de uso
if __name__ == "__main__":
    motor = MotorBTS7960(en=23, gpio_rpwm=13, gpio_lpwm=12)
    try:
        motor.avanzar(50)
        sleep(5)
        motor.retroceder(75)
        sleep(5)
        motor.detener()
    finally:
        motor.limpiar()