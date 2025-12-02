
import gpiod
from time import sleep
from gpiod.line import Direction, Value
import serial


class DriverEncoderSys:
    def __init__(self, en_l=12, en_r=13, uart_port="/dev/ttyAMA0", baudrate=115200, chip="/dev/gpiochip0"):
        """
        Control seguro de motor BTS7960 con habilitación selectiva de medio puente
        y comunicación UART con Raspberry Pi Pico para PWM y lectura de encoder.
        """
        print("Inicializando sistema motor + encoder...")
        self.en_l = en_l  # EN_L (medio puente izquierdo)
        self.en_r = en_r  # EN_R (medio puente derecho)

        # Configuración GPIO para EN_L y EN_R
        config = {
            self.en_l: gpiod.LineSettings(direction=Direction.OUTPUT, output_value=Value.INACTIVE),
            self.en_r: gpiod.LineSettings(direction=Direction.OUTPUT, output_value=Value.INACTIVE),
        }

        self.request = gpiod.request_lines(chip, consumer="motor-control", config=config)

        # UART para comunicación con Pico
        self.ser = serial.Serial(uart_port, baudrate, timeout=0.5)
        self.ser.reset_input_buffer()
        
        # Variables del encoder
        self.raw_data: str|None = None
        self.rpm = 0.0
        self.counter = 0
        self.direction = "UNKNOWN"

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

    def avanzar(self, velocidad):
        """Avanza en sentido horario con velocidad (0-100%)."""
        velocidad = max(0, min(100, velocidad))
        print(f"Avanzando a {velocidad}%")
        self.habilitar_avance()
        self.ser.write(f"RPWM:{velocidad}\n".encode())

    def retroceder(self, velocidad):
        """Retrocede en sentido antihorario con velocidad (0-100%)."""
        velocidad = max(0, min(100, velocidad))
        print(f"Retrocediendo a {velocidad}%")
        self.habilitar_retroceso()
        self.ser.write(f"LPWM:{velocidad}\n".encode())

    def detener(self):
        """Detiene el motor (PWM = 0 y deshabilita ambos medios puentes)."""
        print("Deteniendo motor...")
        self.ser.write(b"RPWM:0\n")
        self.ser.write(b"LPWM:0\n")
        self.deshabilitar_motor()

    def frenar(self):
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
    def leer_encoder(self):
        """Solicita datos al Pico y los parsea."""
        try:
            self.ser.write(b"GET\n")
            raw_data = self.ser.readline()
            self.raw_data = raw_data.decode('utf-8').strip()
            if raw_data:
                line = raw_data.decode('utf-8').strip()
                self._parse_line(line)
                return line
        except Exception as e:
            print("Error al leer UART:", e)
            return None

    def _parse_line(self, line):
        try:
            parts = line.split("|")
            for part in parts:
                part = part.strip()
                if part.startswith("RPM:"):
                    self.rpm = float(part.replace("RPM:", "").strip())
                elif part.startswith("COUNTER:"):
                    self.counter = int(part.replace("COUNTER:", "").strip())
                elif "Dirección" in part:
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
        print("Sistema apagado y recursos liberados.")


# Ejemplo de uso
if __name__ == "__main__":
    sistema = DriverEncoderSys(en_l=12, en_r=13)
    try:
        sistema.avanzar(50)
        sleep(2)
        print(sistema.leer_encoder())
        sistema.retroceder(70)
        sleep(2)
        print(sistema.leer_encoder())
        sistema.frenar()
        sistema.detener()
    finally:
        sistema.limpiar()