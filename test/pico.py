# -*- coding: utf-8 -*-
__author__ = "Edisson A. Naula"
__date__ = "$ 03/11/2025  at 18:18 $"

from machine import Pin, UART, Timer
import rp2
import time

uart = UART(0, baudrate=9600, tx=Pin(0), rx=Pin(1))
led = Pin(25, Pin.OUT)
timer = Timer()

# Estado del sistema
system_ok = True

# Constantes
PPR = 600
RESET_INTERVAL = 300000  # 5 minutos en milisegundos

# Variables de posición
raw_position = 0
last_raw_position = 0
last_state = None
last_time = time.ticks_ms()
last_reset_time = last_time

# Buffer de lecturas
history = []

# Función para parpadear el LED
def blink(timer):
    led.toggle()

timer.init(freq=2.5, mode=Timer.PERIODIC, callback=blink)

@rp2.asm_pio(sideset_init=rp2.PIO.OUT_LOW)
def quadrature_decoder():
    wrap_target()
    label("read")
    in_(pins, 2)         .side(0)
    push(block)          .side(0)
    wrap()

pin_a = Pin(2, Pin.IN, Pin.PULL_UP)
pin_b = Pin(3, Pin.IN, Pin.PULL_UP)

sm = rp2.StateMachine(0, quadrature_decoder, freq=1000000, in_base=pin_a)
sm.active(1)

def decode_quadrature(state):
    global raw_position, last_state
    if last_state is None:
        last_state = state
        return

    a_last = (last_state >> 1) & 1
    b_last = last_state & 1
    a_now = (state >> 1) & 1
    b_now = state & 1

    transition = (a_last << 3) | (b_last << 2) | (a_now << 1) | b_now
    if transition in [0b0001, 0b0111, 0b1110, 0b1000]:
        raw_position += 1
    elif transition in [0b0010, 0b0100, 0b1101, 0b1011]:
        raw_position -= 1

    last_state = state

def add_to_history(abs_pos, rel_pos, rpm):
    if len(history) >= 10:
        history.pop(0)
    history.append((abs_pos, rel_pos, rpm))

def send_history():
    uart.write("Últimas 10 lecturas:\n")
    for i, (abs_pos, rel_pos, rpm) in enumerate(history):
        uart.write(f"{i+1}: Abs={abs_pos}, Rel={rel_pos}, RPM={rpm:.2f}\n")

while True:
    if sm.rx_fifo():
        state = sm.get() & 0b11
        decode_quadrature(state)

    now = time.ticks_ms()

    # Reinicio periódico del contador
    if time.ticks_diff(now, last_reset_time) >= RESET_INTERVAL:
        raw_position = 0
        last_raw_position = 0
        last_reset_time = now

    # Verifica si hay datos UART entrantes
    if uart.any():
        command = uart.read().decode().strip()
        if command.upper() == "GET":
            send_history()

    # Actualización cada 100 ms
    if time.ticks_diff(now, last_time) >= 100:
        delta_pos = raw_position - last_raw_position
        delta_time = time.ticks_diff(now, last_time) / 1000

        if delta_pos == 0:
            if system_ok:
                timer.init(freq=0.5, mode=Timer.PERIODIC, callback=blink)
                system_ok = False
        else:
            if not system_ok:
                timer.init(freq=2.5, mode=Timer.PERIODIC, callback=blink)
                system_ok = True

        rpm = (delta_pos / PPR) * (60 / delta_time)
        position = raw_position % PPR
        add_to_history(raw_position, position, rpm)

        last_raw_position = raw_position
        last_time = now


