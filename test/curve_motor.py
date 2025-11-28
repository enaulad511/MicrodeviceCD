# -*- coding: utf-8 -*-
import time
from templates.constants import serial_port_encoder
from Drivers.EncoderData import EncoderData
from Drivers.DriverMotorDC import MotorBTS7960
import signal
import sys

__author__ = "Edisson Naula"
__date__ = "$ 28/11/2025 at 15:59 $"


motor = MotorBTS7960(en=23)

def handler(sig, frame):
    motor.limpiar()
    sys.exit(0)

signal.signal(signal.SIGINT, handler)
signal.signal(signal.SIGTERM, handler)


if __name__ == "__main__":
    t_test = 10.0  # seconds
    t_s = 0.01  # seconds
    print ("Test started")
    current_time = time.perf_counter()
    data_encoder = EncoderData(serial_port_encoder, 115200)
    passed_time = 0.0
    try:
        motor.avanzar(10)
        while passed_time < t_test:
            raw_data = data_encoder.leer_uart()
            data_encoder.parse_line(raw_data)
            rpm_actual = data_encoder.get_rpm()
            current_time = time.perf_counter()
            # print(f"RPM actual: {rpm_actual}")
            while time.perf_counter() - current_time < t_s:
                pass
            passed_time += time.perf_counter() - current_time
            print(f"{passed_time:.2f}: {rpm_actual}")
    except KeyboardInterrupt:
        print("Test interrupted by user")
    motor.detener()
    print("Motor stopped")
    print("Test finished")
