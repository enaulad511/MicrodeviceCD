# -*- coding: utf-8 -*-
__author__ = "Edisson A. Naula"
__date__ = "$ 01/oct/2025 at 09:54 $"

import serial
import threading
import time
from Drivers.DriverMotorDC import MotorBTS7960

# Configura el puerto UART
ser = serial.Serial('/dev/ttyAMA0', 115200, timeout=0.1)

# Variable compartida
latest_line = ""


# Función para leer UART en un hilo separado
def leer_uart():
    global latest_line
    while True:
        try:
            raw_data = ser.readline()
            if raw_data:
                try:
                    latest_line = raw_data.decode('utf-8').strip()
                    print("Último dato:", latest_line)
                except UnicodeDecodeError as e:
                    print("Error de decodificación:", e)
        except serial.SerialException as e:
            print("Error de puerto serial:", e)
            break
        time.sleep(0.01)  # Evita saturación


# Función para controlar el motor
def controlar_motor(motor):
    try:
        print("Motor avanzando al 50%")
        motor.avanzar(50)
        time.sleep(5)

        print("Motor retrocediendo al 75%")
        motor.retroceder(75)
        time.sleep(5)

        print("Motor detenido")
        motor.detener()
    except Exception as e:
        print("Error en control de motor:", e)


if __name__ == "__main__":
    motor = MotorBTS7960(en=23)

    try:
        # Inicia hilo de lectura UART
        hilo_uart = threading.Thread(target=leer_uart, daemon=True)
        hilo_uart.start()

        # Ejecuta control de motor
        controlar_motor(motor)

        # Mantén el programa vivo para seguir leyendo UART
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("Interrumpido por el usuario.")
    finally:
        ser.close()
        motor.limpiar()
        print("Finalizado correctamente.")