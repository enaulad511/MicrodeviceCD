# -*- coding: utf-8 -*-
__author__ = "Edisson A. Naula"
__date__ = "$ 01/oct/2025  at 09:54 $"

import serial

from Drivers.DriverMotorDC import MotorBTS7960

# Configura el puerto UART (ajusta '/dev/ttyS0' o '/dev/serial0' según tu configuración)
ser = serial.Serial('/dev/ttyAMA0', 115200, timeout=0.1)


if __name__ == "__main__":
    # Pines del BTS7960
    latest_line = ""
    motor = MotorBTS7960(en=23)
    try:
        motor.avanzar(50)
        while True:
            # Lee todos los datos disponibles en el buffer
            while ser.in_waiting:
                raw_data = ser.readline()
                print("Dato crudo:", raw_data)
                try:
                    latest_line = raw_data.decode('utf-8').strip()
                    print("Último dato:", latest_line)
                except UnicodeDecodeError as e:
                    print("Error de decodificación:", e)

            if latest_line:
                print("Último dato:", latest_line)
                # Aquí puedes procesar solo el dato más reciente
                latest_line = ""  # Reinicia para la próxima lectura
    except KeyboardInterrupt:
        print("Interrumpido por el usuario.")
    finally:
        ser.close()
        motor.limpiar()
        print("Finalizado correctamente.")


