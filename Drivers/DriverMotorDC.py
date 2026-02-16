import gpiod 
import threading
from time import sleep
from gpiod.line import Direction, Value


class MotorBTS7960:
    def __init__(self, en, gpio_rpwm=13, gpio_lpwm=12, chip="/dev/gpiochip0"):
        """
        Control de motor BTS7960 con un solo hilo PWM.
        """
        print("Inicializando motor...")
        self.enable = en
        self.rpwm: int = gpio_rpwm
        self.lpwm: int = gpio_lpwm

        # Configuración de líneas
        config = {
            self.enable: gpiod.LineSettings(
                direction=Direction.OUTPUT, output_value=Value.INACTIVE
            ),
            self.rpwm: gpiod.LineSettings(
                direction=Direction.OUTPUT, output_value=Value.INACTIVE
            ),
            self.lpwm: gpiod.LineSettings(
                direction=Direction.OUTPUT, output_value=Value.INACTIVE
            ),
        }

        # Solicita las líneas
        self.request = gpiod.request_lines(
            chip, consumer="motor-control", config=config
        )

        # Activa la línea EN
        self.request.set_value(self.enable, Value.ACTIVE)
        print(
            f"Motor habilitado en EN={self.enable}, RPWM={self.rpwm}, LPWM={self.lpwm}"
        )

        # Variables para PWM dinámico
        self._duty = 0.0
        self._active_line: int | None = None
        self._stop_event = threading.Event()
        self._pwm_thread = threading.Thread(target=self._pwm_loop, daemon=True)
        self._pwm_thread.start()

    def avanzar(self, velocidad):
        print(f"Avanzando a {velocidad}%")
        self.request.set_value(self.lpwm, Value.INACTIVE)
        self._active_line = self.rpwm
        self._duty = max(0, min(100, velocidad)) / 100.0

    def retroceder(self, velocidad):
        print(f"Retrocediendo a {velocidad}%")
        self.request.set_value(self.rpwm, Value.INACTIVE)
        self._active_line = self.lpwm
        self._duty = max(0, min(100, velocidad)) / 100.0

    def detener(self):
        print("Deteniendo motor")
        self._duty = 0.0
        self._active_line = None
        self.request.set_value(self.rpwm, Value.INACTIVE)
        self.request.set_value(self.lpwm, Value.INACTIVE)

    def frenar(self):
        print("Frenando motor")
        self._duty = 0.0
        self._active_line = None
        self.request.set_value(self.rpwm, Value.ACTIVE)
        self.request.set_value(self.lpwm, Value.ACTIVE)
        sleep(0.5)
        self.request.set_value(self.rpwm, Value.INACTIVE)
        self.request.set_value(self.lpwm, Value.INACTIVE)

    def limpiar(self):
        print("Liberando recursos...")
        self.detener()
        self._stop_event.set()
        self._pwm_thread.join()
        self.request.set_value(self.enable, Value.INACTIVE)
        print("Motor deshabilitado y líneas liberadas.")

    def _pwm_loop(self):
        period = 0.00005  # 20 000 Hz
        while not self._stop_event.is_set():
            if self._active_line and self._duty > 0:
                self.request.set_value(self._active_line, Value.ACTIVE)
                sleep(period * self._duty)
                self.request.set_value(self._active_line, Value.INACTIVE)
                sleep(period * (1 - self._duty))
            else:
                sleep(period)  # Espera sin señal si no hay movimiento


# Ejemplo de uso
if __name__ == "__main__":
    motor = MotorBTS7960(en=23, gpio_rpwm=13, gpio_lpwm=12)
    try:
        motor.avanzar(50)
        sleep(3)
        motor.avanzar(80)
        sleep(3)
        motor.retroceder(60)
        sleep(3)
        motor.detener()
    finally:
        motor.limpiar()
