import gpiod  # pyrefly: ignore
from time import sleep
from gpiod.line import Direction, Value  # pyrefly: ignore
import serial


__author__ = "Edisson A. Naula"
__date__ = "$ 19/02/2026  at 11:11 a.m. $"


class DriverEncoderSys:
    def __init__(
        self,
        en_l=16,
        en_r=26,
        uart_port="/dev/ttyAMA0",
        baudrate=921600,
        chip="/dev/gpiochip0",
    ):
        """
        Control seguro de motor BTS7960 con habilitación selectiva de medio puente
        y comunicación UART con Raspberry Pi Pico para PWM y lectura de encoder.
        """
        print("Inicializando sistema motor + encoder...")
        self.en_l = en_l  # EN_L (medio puente izquierdo)
        self.en_r = en_r  # EN_R (medio puente derecho)

        # Configuración GPIO para EN_L y EN_R
        config = {
            self.en_l: gpiod.LineSettings(
                direction=Direction.OUTPUT, output_value=Value.INACTIVE
            ),
            self.en_r: gpiod.LineSettings(
                direction=Direction.OUTPUT, output_value=Value.INACTIVE
            ),
        }

        self.request = gpiod.request_lines(
            chip, consumer="motor-control", config=config
        )

        # UART para comunicación con Pico
        self.ser = serial.Serial(uart_port, baudrate, timeout=0.5, stopbits=2)
        self.ser.reset_input_buffer()

        # Variables del encoder
        self.raw_data: str | None = None
        self.rpm = 0.0
        self.counter = 0
        self.direction = "UNKNOWN"
        self.old_count = 0.0

    # =========================
    # Control seguro del motor
    # =========================
    def habilitar_avance(self):
        """Habilita solo el medio puente derecho (EN_R) para avanzar."""
        self.request.set_value(self.en_l, Value.ACTIVE)
        self.request.set_value(self.en_r, Value.ACTIVE)

    def habilitar_retroceso(self):
        """Habilita solo el medio puente izquierdo (EN_L) para retroceder."""
        self.request.set_value(self.en_l, Value.ACTIVE)
        self.request.set_value(self.en_r, Value.ACTIVE)

    def deshabilitar_motor(self):
        """Deshabilita ambos medios puentes."""
        self.request.set_value(self.en_l, Value.INACTIVE)
        self.request.set_value(self.en_r, Value.INACTIVE)

    def avanzar(self, velocidad, ignore_answer=True):
        """Avanza en sentido horario con velocidad (0-100%)."""
        count = 0
        velocidad = max(0, min(100, velocidad))
        print(f"Avanzando a {velocidad}%")
        self.habilitar_avance()
        if not ignore_answer:
            count = 0
            while count < 5:
                self.ser.write(f"RPWM:{velocidad}\n".encode())
                answer = self.ser.readline().decode("utf-8").strip()
                print("Respuesta del Pico:", answer)
                if "ok" in answer.lower():
                    break
                count += 1
            return count
        else:
            self.ser.write(f"RPWM:{velocidad}\n".encode())
            return 0

    def retroceder(self, velocidad, ignore_answer=True):
        """Retrocede en sentido antihorario con velocidad (0-100%)."""
        velocidad = max(0, min(100, velocidad))
        print(f"Retrocediendo a {velocidad}%")
        self.habilitar_retroceso()
        count = 0
        if not ignore_answer:
            while count < 5:
                self.ser.write(f"LPWM:{velocidad}\n".encode())
                answer = self.ser.readline().decode("utf-8").strip()
                print("Respuesta del Pico:", answer)
                if "ok" in answer.lower():
                    break
                count += 1
            return count
        else:
            self.ser.write(f"LPWM:{velocidad}\n".encode())
            return 0

    def detener(self):
        """Detiene el motor con freno (PWM = 0 y deshabilita ambos medios puentes)."""
        print("Deteniendo motor...")
        # self.ser.write(b"RPWM:0\n")
        # self.ser.write(b"LPWM:0\n")
        count = 0
        while count < 5:
            self.ser.write(b"STOP\n")
            answer = self.ser.readline().decode("utf-8").strip()
            print("Respuesta del Pico:", answer)
            if "ok" in answer.lower():
                break
            count += 1
        sleep(1)
        self.counter = 0
        self.old_count = 0.0
        self.deshabilitar_motor()

    def frenar_pasivo(self):
        """Freno pasivo: ambos medios puentes habilitados pero PWM = 0."""
        count = 0
        while count < 5:
            self.ser.write(b"STOP\n")
            answer = self.ser.readline().decode("utf-8").strip()
            print("Respuesta del Pico:", answer)
            if "ok" in answer.lower():
                break
            count += 1

    def frenar_activo(self):
        """Freno activo: ambos medios puentes habilitados y PWM alto por breve tiempo."""
        print("Frenando motor...")
        self.request.set_value(self.en_l, Value.ACTIVE)
        self.request.set_value(self.en_r, Value.ACTIVE)
        self.ser.write(b"RPWM:100\n")
        self.ser.write(b"LPWM:100\n")
        sleep(0.3)
        self.detener()

    # =========================
    # Lectura del encoder
    # =========================
    def leer_encoder(self, ts):
        """Solicita datos al Pico y los parsea."""
        try:
            # self.ser.flush()
            self.ser.write(b"GET\n")
            all_data = self.ser.read_all()
            print("Datos recibidos:", all_data)
            lines = all_data.decode("utf-8").split("\n")
            # raw_data = self.ser.readline()
            # self.raw_data = raw_data.decode('utf-8').strip()
            raw_data = lines[0]
            self.raw_data = raw_data.strip()
            if raw_data:
                line = raw_data
                self._parse_line(line, ts)
                return line
        except Exception as e:
            print("Error al leer UART:", e)
            return None

    def _parse_line(self, line, ts):
        try:
            parts = line.split("|")
            for part in parts:
                part = part.strip()
                if part.startswith("COU:"):
                    self.counter = int(part.split(":")[1])
                    delta_counter = self.counter - self.old_count
                    self.rpm = (delta_counter / 600) * (60 / ts) * 2  # Convertir a RPM
                    self.old_count = self.counter
                elif "Dir" in part:
                    self.direction = part.split(":")[1].strip()
        except Exception as e:
            print("Error al parsear línea:", e)
            self.rpm = 0.0
            self.counter = 0
            self.direction = "UNKNOWN"

    def get_estado(self):
        return {"RPM": self.rpm, "COUNTER": self.counter, "DIRECCION": self.direction}

    def get_rpm(self) -> float:
        return self.rpm

    # =========================
    # Limpieza
    # =========================
    def limpiar(self):
        print("Liberando recursos...")
        self.detener()
        self.ser.close()
        self.request.release()
        self.request = None
        self.counter = 0
        self.old_count = 0.0
        print("Sistema apagado y recursos liberados.")


# Ejemplo de uso
if __name__ == "__main__":
    sistema = DriverEncoderSys(en_l=12, en_r=13)
    try:
        sistema.avanzar(50)
        sleep(2)
        print(sistema.leer_encoder(2))
        sistema.retroceder(70)
        sleep(2)
        print(sistema.leer_encoder(2))
        sistema.frenar_activo()
        sistema.detener()
    finally:
        sistema.limpiar()
