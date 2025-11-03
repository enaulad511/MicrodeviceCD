# -*- coding: utf-8 -*-
__author__ = "Edisson A. Naula"
__date__ = "$ 01/oct/2025  at 09:54 $"

import time

import serial

from Drivers.DriverMotorDC import MotorBTS7960


if __name__ == "__main__":
    # Pines del BTS7960
    latest_line = ""

    # Configura el puerto UART (ajusta '/dev/ttyS0' o '/dev/serial0' según tu configuración)
    ser = serial.Serial('/dev/ttyAMA0', 115200, timeout=0.1)
    # flush the buffer
    ser.flush()
    motor = MotorBTS7960(en=23)
    print("Iniciado correctamente.")
    time.sleep(.5)
    try:
        motor.avanzar(50)
        print("Avanzando a 50%...")
        while True:
            print("leyendo...")
            # Lee todos los datos disponibles en el buffer
            while ser.in_waiting:
                raw_data = ser.readline()
                latest_line = raw_data.decode('utf-8').strip()
                print("Dato:", latest_line)
            if latest_line:
                print("Último dato:", latest_line)
                # Aquí puedes procesar solo el dato más reciente
                latest_line = ""  # Reinicia para la próxima lectura
            time.sleep(0.1)  # Pequeña pausa para no saturar el CPU
    except KeyboardInterrupt:
        print("Interrumpido por el usuario.")
    finally:
        ser.close()
        motor.limpiar()
        print("Finalizado correctamente.")


