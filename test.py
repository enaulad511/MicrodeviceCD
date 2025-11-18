# -*- coding: utf-8 -*-
__author__ = "Edisson A. Naula"
__date__ = "$ 01/oct/2025 at 09:54 $"

import serial
import threading
import time
from Drivers.DriverMotorDC import MotorBTS7960

# Configura el puerto UART
ser = serial.Serial('/dev/ttyAMA0', 115200, timeout=0.5)

# Variable compartida
latest_line = ""

# Evento para detener hilos
stop_event = threading.Event()


# Función para leer UART en un hilo separado
def leer_uart():
    global latest_line
    while not stop_event.is_set():
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


# Función para enviar comandos periódicamente
def enviar_comandos():
    while not stop_event.is_set():
        try:
            comando = "GET"
            if comando:
                ser.write(f"{comando}\n".encode())
            time.sleep(0.5)
        except serial.SerialException:
            print("Puerto cerrado, no se puede enviar comando.")
            break


if __name__ == "__main__":
    motor = MotorBTS7960(en=23)
    hilo_uart = threading.Thread(target=leer_uart, daemon=True)
    hilo_comandos = threading.Thread(target=enviar_comandos, daemon=True)

    try:
        # Inicia hilos
        hilo_uart.start()
        # hilo_comandos.start()

        # Control del motor
        motor.avanzar(25)
        print("Motor avanzando...")
        time.sleep(15)  # Simulación de trabajo

        motor.detener()
        print("Motor detenido.")

    except KeyboardInterrupt:
        print("\nInterrumpido por el usuario.")
    finally:
        # Señal para detener hilos
        stop_event.set()

        # Espera a que los hilos terminen
        hilo_uart.join()
        # hilo_comandos.join()

        # Cierra recursos
        ser.close()
        motor.limpiar()
