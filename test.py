# -*- coding: utf-8 -*-
__author__ = "Edisson A. Naula"
__date__ = "$ 01/oct/2025 at 09:54 $"

import serial
import threading
import time

from Drivers.DriverMotorDC import MotorBTS7960

# from Drivers.DriverMotorDC import MotorBTS7960  # Descomenta si usas el motor
# Configura el puerto UART
ser = serial.Serial('/dev/ttyAMA0', 9600, timeout=0.5)

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
                    print(">>", latest_line)
                except UnicodeDecodeError as e:
                    print("Error de decodificación:", e)
        except serial.SerialException as e:
            print("Error de puerto serial:", e)
            break
        time.sleep(0.01)


# Función para enviar comandos desde consola
def enviar_comandos():
    while True:
        try:
            # comando = input("Ingresa comando UART (ej. GET): ").strip()
            comando = "GET"
            time.sleep(0.5)
            if comando:

                ser.write(f"{comando}\n".encode())
        except KeyboardInterrupt:
            print("\nInterrumpido por el usuario.")
            break


if __name__ == "__main__":
    motor = MotorBTS7960(en=23)  # Descomenta si usas el motor
    hilo_uart = threading.Thread(target=leer_uart, daemon=True)
    try:

        # Inicia hilo de lectura UART
        # hilo_uart = threading.Thread(target=leer_uart, daemon=True)
        hilo_uart.start()
        time.sleep(1)

        hilo_comandos = threading.Thread(target=enviar_comandos, daemon=True)
        hilo_comandos.start()

        # Inicia entrada de comandos por consola
        motor.avanzar(35)
        print("Motor avanzando...")
        # enviar_comandos()
        # while True:
        #     # Ejemplo de uso del motor
        #     motor.avanzar(15)
        #     time.sleep(1)
        #     motor.retroceder(25)
        #     time.sleep(1)
        #     motor.detener()
        #     time.sleep(1)
    except KeyboardInterrupt:
        print("\nInterrumpido por el usuario.")
    finally:

        ser.close()
        motor.limpiar()
        print("Finalizado correctamente.")