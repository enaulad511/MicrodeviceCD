# -*- coding: utf-8 -*-
import time
from templates.constants import serial_port_encoder
from Drivers.EncoderData import EncoderData
from Drivers.DriverMotorDC import MotorBTS7960

__author__ = "Edisson Naula"
__date__ = "$ 28/11/2025 at 15:59 $"

motor = MotorBTS7960(en=23)

if __name__ == "__main__":
    t_test = 10  # seconds
    t_s = 0.01  # seconds
    current_time = time.perf_counter()
    data_encoder = EncoderData(serial_port_encoder, 115200)
    while current_time < t_test:
        raw_data = data_encoder.leer_uart()
        data_encoder.parse_line(raw_data)
        rpm_actual = data_encoder.get_rpm()
        current_time = time.perf_counter()
        print(f"RPM actual: {rpm_actual}")
    print("Test finished")
