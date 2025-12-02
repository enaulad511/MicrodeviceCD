# -*- coding: utf-8 -*-
from Drivers.DriverEncoder import DriverEncoderSys
import time
from templates.constants import serial_port_encoder
import signal
import sys

__author__ = "Edisson Naula"
__date__ = "$ 28/11/2025 at 15:59 $"


sistemaMotor = DriverEncoderSys(en_l=12, en_r=13, uart_port=serial_port_encoder, baudrate=115200)

def handler(sig, frame):
    sistemaMotor.limpiar()
    sys.exit(0)

signal.signal(signal.SIGINT, handler)
signal.signal(signal.SIGTERM, handler)


if __name__ == "__main__":
    t_test = 10.0  # seconds
    t_s = 0.01  # seconds
    current_time = time.perf_counter()
    passed_time = 0.0
    try:
        sistemaMotor.avanzar(50)
        while passed_time < t_test:
            raw_data = sistemaMotor.leer_encoder()
            rpm_actual = sistemaMotor.get_rpm()
            current_time = time.perf_counter()
            # print(f"RPM actual: {rpm_actual}")
            while time.perf_counter() - current_time < t_s:
                pass
            passed_time += time.perf_counter() - current_time
            print(f"{passed_time:.2f}: {rpm_actual}")
            # print(f"{passed_time:.2f}")
        sistemaMotor.detener()
    except KeyboardInterrupt:
        print("Test interrupted by user")
    sistemaMotor.detener()
    print("Motor stopped")
    print("Test finished")
