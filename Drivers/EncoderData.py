# -*- coding: utf-8 -*-
import serial
__author__ = "Edisson Naula"
__date__ = "$ 18/11/2025 at 15:00 $"

class EncoderData:
    def __init__(self, port: str, baudrate: int, stop_event=None):
        self.port = port
        self.baudrate = baudrate
        self.rpm = 0.0
        self.counter = 0
        self.direction = "UNKNOWN"
        self.stop_event = stop_event
        self.ser = serial.Serial(port, baudrate, timeout=0.5)
        self.raw_data: str|None = None
        self.ser.reset_input_buffer()

    def leer_uart(self):
        """
        Lee una línea del UART y la parsea.
        """
        try:
            self.ser.reset_input_buffer()
            raw_data = self.ser.readline()
            if raw_data:
                try:
                    latest_line = raw_data.decode('utf-8').strip()
                    # print("Línea leída:", latest_line)
                    self.raw_data = latest_line
                    return latest_line
                except UnicodeDecodeError as e:
                    print("Error de decodificación:", e)
                    return None
        except Exception as e:
            print("Error al leer UART:", e)
            return None

    def parse_line(self, line: str|None):
        """
        Parsea una línea del UART con formato:
        'RPM: 236.40 | COUNTER: 139635 | Dirección: CCW'
        """
        if line is not None:
            self.raw_data = line
        if not self.raw_data:
            self.rpm = 0.0
            self.counter = 0
            self.direction = "UNKNOWN"
            return
        try:
            parts = self.raw_data.split("|")
            for part in parts:
                part = part.strip()
                if part.startswith("RPM:"):
                    self.rpm = float(part.replace("RPM:", "").strip())
                elif part.startswith("COUNTER:"):
                    self.counter = int(part.replace("COUNTER:", "").strip())
                elif "Dirección" in part:
                    self.direction = part.split(":")[1].strip()
        except Exception as e:
            print(f"Error al parsear línea: {e}")
            self.rpm = 0.0
            self.counter = 0
            self.direction = "UNKNOWN"

    def get_rpm(self):
        return self.rpm

    def get_counter(self):
        return self.counter

    def get_direction(self):
        return self.direction

    def __str__(self):
        return f"RPM={self.rpm:.2f}, COUNTER={self.counter}, Dirección={self.direction}"

    def close(self):
        self.ser.close()
        print("UART cerrado.")
    
if __name__ == "__main__":
    data = EncoderData('/dev/ttyAMA0', 115200)
    uart_line = "RPM: 236.40 | COUNTER: 139635 | Dirección: CCW"
    uart_line = data.leer_uart()
    if uart_line:
        data.parse_line(uart_line)
        print(data.get_rpm())       # 236.40
        print(data.get_counter())   # 139635
        print(data.get_direction()) # CCW
        print(data)                 # RPM=236.40, COUNTER=139635, Dirección=CCW