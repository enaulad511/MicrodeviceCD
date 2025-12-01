
import os
import time
import gpiod
from gpiod.line import Direction, Value

class MotorBTS7960:
    PWM_CHIP = "/sys/class/pwm/pwmchip0"
    PERIOD_NS = 1_000_000  # 1 ms = 1 kHz

    def __init__(self, en=23, pwm_rpwm=0, pwm_lpwm=1, chip="/dev/gpiochip0"):
        """
        Control de motor BTS7960 usando PWM por hardware vía sysfs y EN con gpiod.
        pwm_rpwm y pwm_lpwm son los canales PWM (0 y 1).
        """
        print("Inicializando motor...")
        self.enable = en
        self.rpwm_channel = f"{self.PWM_CHIP}/pwm{pwm_rpwm}"
        self.lpwm_channel = f"{self.PWM_CHIP}/pwm{pwm_lpwm}"

        # Exportar canales PWM si no existen
        self._export_channel(pwm_rpwm)
        self._export_channel(pwm_lpwm)

        # Configurar PWM inicial
        self._setup_pwm(self.rpwm_channel)
        self._setup_pwm(self.lpwm_channel)

        # Configurar línea EN con gpiod
        config = {
            self.enable: gpiod.LineSettings(direction=Direction.OUTPUT, output_value=Value.INACTIVE)
        }
        self.request = gpiod.request_lines(chip, consumer="motor-control", config=config)

        print(f"Motor habilitado con EN={self.enable}, RPWM=pwm{pwm_rpwm}, LPWM=pwm{pwm_lpwm}")

    def _export_channel(self, channel):
        if not os.path.exists(f"{self.PWM_CHIP}/pwm{channel}"):
            with open(f"{self.PWM_CHIP}/export", 'w') as f:
                f.write(str(channel))
            time.sleep(0.1)

    def _setup_pwm(self, channel_path):
        self._write(channel_path, "period", self.PERIOD_NS)
        self._write(channel_path, "duty_cycle", 0)
        self._write(channel_path, "enable", 1)

    def _write(self, channel_path, file, value):
        with open(f"{channel_path}/{file}", 'w') as f:
            f.write(str(value))

    def _activar_en(self):
        self.request.set_value(self.enable, Value.ACTIVE)

    def _desactivar_en(self):
        self.request.set_value(self.enable, Value.INACTIVE)

    def avanzar(self, velocidad):
        print(f"Avanzando a {velocidad}%")
        self._activar_en()
        self._write(self.lpwm_channel, "duty_cycle", 0)
        duty_ns = int(self.PERIOD_NS * max(0, min(100, velocidad)) / 100)
        self._write(self.rpwm_channel, "duty_cycle", duty_ns)

    def retroceder(self, velocidad):
        print(f"Retrocediendo a {velocidad}%")
        self._activar_en()
        self._write(self.rpwm_channel, "duty_cycle", 0)
        duty_ns = int(self.PERIOD_NS * max(0, min(100, velocidad)) / 100)
        self._write(self.lpwm_channel, "duty_cycle", duty_ns)

    def detener(self):
        print("Deteniendo motor")
        self._write(self.rpwm_channel, "duty_cycle", 0)
        self._write(self.lpwm_channel, "duty_cycle", 0)
        self._desactivar_en()

    def frenar(self):
        print("Frenando motor")
        self._activar_en()
        self._write(self.rpwm_channel, "duty_cycle", self.PERIOD_NS)
        self._write(self.lpwm_channel, "duty_cycle", self.PERIOD_NS)
        time.sleep(0.5)
        self.detener()

    def limpiar(self):
        print("Liberando recursos...")
        self.detener()
        self._write(self.rpwm_channel, "enable", 0)
        self._write(self.lpwm_channel, "enable", 0)
        print("Motor deshabilitado.")

# Ejemplo de uso
if __name__ == "__main__":
    motor = MotorBTS7960(en=23, pwm_rpwm=0, pwm_lpwm=1)
    try:
        motor.avanzar(50)
        time.sleep(3)
        motor.avanzar(80)
        time.sleep(3)
        motor.retroceder(60)
        time.sleep(3)
        motor.detener()
    finally:
        motor.limpiar()