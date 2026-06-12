# -*- coding: utf-8 -*-
from machine import Pin, UART, Timer
import time, micropython, gc
from rp2 import PIO, StateMachine, asm_pio
import _thread

__author__ = "Edisson Naula"
__date__ = "$ 13/03/2026 at 17:01 $"

micropython.alloc_emergency_exception_buf(128)

# --- CONSTANTES / CONFIG ---
IFR_S_PIN = 22
UART_BAUD = 921600
STEPS_PER_REV = 6400  # Ajusta según microstepping de tu driver
DEFAULT_SPEED_HZ = 1000.0  # Velocidad por defecto para movimientos POS
TELEMETRY_INTERVAL_US = 50_000

led = Pin("LED", Pin.OUT)
sensor_ifr = Pin(IFR_S_PIN, Pin.IN)


# ------------------ CONTROLADOR STEPPER NO BLOQUEANTE ------------------


# PIO: produce N pulsos (si X=steps-1); si X = 0xFFFFFFFF => corre continuo (infinito)
# Ajustamos la frecuencia desde Python con sm.freq(step_hz * 2)
@asm_pio(set_init=PIO.OUT_LOW)
def stepper_pio():
    pull(block)  # pyrefly: ignore Espera primer comando en TX FIFO
    mov(x, osr)  # pyrefly: ignore X = OSR (0 => continuo, N>0 => finito)
    jmp(not_x, "cont")  # pyrefly: ignore Si X == 0 -> ir a modo continuo

    # ---- MODO FINITO (N PULSOS) ----
    label("finite")
    set(pins, 1)  # pyrefly: ignore HIGH
    set(pins, 0)  # pyrefly: ignore LOW
    jmp(x_dec, "finite")  # pyrefly: ignore post-decrementa X y repite mientras X > 0
    irq(0)  # pyrefly: ignore Fin de la secuencia
    jmp("wait_next")  # pyrefly: ignore Espera nuevo comando

    # ---- MODO CONTINUO ----
    label("cont")
    set(pins, 1)  # pyrefly: ignore HIGH
    set(pins, 0)  # pyrefly: ignore LOW
    jmp("cont")  # pyrefly: ignore Repite indefinidamente

    # ---- ESPERAR SIGUIENTE COMANDO ----
    label("wait_next")  # pyrefly: ignore
    pull(block)  # pyrefly: ignore
    mov(x, osr)  # pyrefly: ignore
    jmp(not_x, "cont")  # pyrefly: ignore Si X == 0 -> continuo
    jmp("finite")  # pyrefly: ignore Si X > 0 -> finito


class StepperPWMController:
    def __init__(
        self,
        step_pin=15,
        dir_pin=14,
        steps_per_rev=STEPS_PER_REV,
        dir_setup_us=10,
        sm_id=0,
    ):
        # Pines
        self.step_pin_num = step_pin
        self.dir = Pin(dir_pin, Pin.OUT)
        self.dir.value(1)

        # Parámetros
        self.spr = float(steps_per_rev)
        self.default_speed_hz = float(DEFAULT_SPEED_HZ)
        self._dir_setup_us = int(max(0, dir_setup_us))
        self._sm_id = sm_id

        # Estado externo (mantiene API)
        self.mode = "STOP"  # "POS", "RPM", "HZ", "SWEEP", "STOP", "ZERO"
        self.pos_deg = 0.0
        self.speed_hz = 0.0
        self.speed_rpm = 0.0
        self._dir_sign = 1

        # POS
        self._moving = False
        self._move_end_us = None
        self._pos_before_move = 0.0
        self._planned_increment_deg = 0.0

        # Sweep
        self._sweep_amp_deg = 0.0
        self._sweep_speed_hz = self.default_speed_hz
        self._sweep_dwell_us = 0
        self._sweep_next_inc_deg = 0.0
        self._sweep_wait_until_us = None

        # Internos
        self._last_update_us = time.ticks_us()  # pyrefly: ignore
        self._move_done_pending = False
        self._running_continuous = False

        # ---- ZERO (homing con IFR alto) ----
        # Estados:
        #   0 = CLEARING: salir de la marca (IFR debe pasar a 0)
        #   1 = SEEK_HIGH: buscar la marca (esperar IFR=1 estable)
        self._zero_state = None
        self._zero_dir_pref = 1  # dirección preferida de aproximación (+1 o -1)
        self._zero_start_us = 0
        self._zero_timeout_us = 5_000_000  # 5 s de timeout (ajustable)
        self._zero_debounce_us = 2_000  # 2 ms de estabilidad requerida
        self._zero_edge_t0 = None  # instante de primer detección de IFR=1
        self._zero_done = False

        # PIO StateMachine (inicialmente desactivada)
        self.sm = None
        self._init_sm()

    # ---- PIO / SM helpers ----
    def _init_sm(self, freq_hz=1000):
        if self.sm is not None:
            try:
                self.sm.active(0)
            except Exception:
                pass
        self.sm = StateMachine(
            self._sm_id,
            stepper_pio,
            freq=max(2, int(freq_hz * 2)),  # cada pulso = 2 instrucciones
            set_base=Pin(self.step_pin_num),
        )
        self.sm.irq(self._on_pio_irq)  # IRQ cuando termina una secuencia finita
        self.sm.active(0)

    def _set_sm_freq(self, step_hz):
        target = max(2, int(step_hz * 2))
        try:
            self.sm.freq(target)  # pyrefly: ignore
        except AttributeError:
            self._init_sm(step_hz)

    def _start_continuous(self, step_hz):
        self._set_sm_freq(step_hz)
        self.sm.active(1)  # pyrefly: ignore
        self.sm.put(0xFFFFFFFF)  # pyrefly: ignore
        self._running_continuous = True

    def _start_n_pulses(self, steps, step_hz):
        if steps <= 0:
            return
        self._set_sm_freq(step_hz)
        self.sm.active(1)  # pyrefly: ignore
        self.sm.put((int(steps) - 1) & 0xFFFFFFFF)  # pyrefly: ignore
        self._running_continuous = False

    def _stop_sm(self):
        try:
            self.sm.active(0)  # pyrefly: ignore
        except Exception:
            pass
        self._running_continuous = False

    # ---- Utilidades internas ----
    def _set_dir_from_sign(self, sign):
        new_sign = 1 if sign >= 0 else -1
        if new_sign != self._dir_sign:
            self._dir_sign = new_sign
            self.dir.value(1 if self._dir_sign > 0 else 0)
            time.sleep_us(self._dir_setup_us)  # pyrefly: ignore
        else:
            self._dir_sign = new_sign
            self.dir.value(1 if self._dir_sign > 0 else 0)

    def _on_pio_irq(self, sm):
        self._move_done_pending = True

    # ---- Comandos de alto nivel ----
    def command_sweep(self, amplitude_deg, velocidad_hz=None, dwell_ms=0):
        self.mode = "SWEEP"
        if velocidad_hz is None:
            velocidad_hz = self.default_speed_hz
        # check that vel is not more than 3 times default
        velocidad_hz = min(velocidad_hz, 3 * self.default_speed_hz)
        amp = abs(float(amplitude_deg))
        self._sweep_amp_deg = amp
        self._sweep_speed_hz = float(velocidad_hz)
        self._sweep_dwell_us = int(max(0, dwell_ms) * 1000)
        self._sweep_wait_until_us = None

        self.command_move_degrees(+amp, velocidad_hz=self._sweep_speed_hz)
        self.mode = "SWEEP"
        self._sweep_next_inc_deg = -2.0 * amp

    def set_sweep_dwell_ms(self, dwell_ms):
        self._sweep_dwell_us = int(max(0, dwell_ms) * 1000)

    def command_stop(self):
        self.mode = "STOP"
        self._stop_sm()
        self.speed_hz = 0.0
        self.speed_rpm = 0.0
        self._moving = False
        self._move_end_us = None
        self._sweep_wait_until_us = None
        # Cancelar ZERO si estaba activo
        self._zero_state = None
        self._zero_edge_t0 = None

    def command_speed_rpm(self, rpm):
        self.mode = "RPM"
        self._set_dir_from_sign(rpm)
        hz = abs(rpm) * (self.spr / 60.0)
        if hz <= 0:
            self.command_stop()
            return
        self._start_continuous(hz)
        self.speed_hz = hz
        self.speed_rpm = self._dir_sign * abs(rpm)
        self._moving = False
        self._move_end_us = None

    def command_speed_hz(self, hz_signed):
        self.mode = "HZ"
        self._set_dir_from_sign(hz_signed)
        hz = abs(hz_signed)
        if hz <= 0:
            self.command_stop()
            return
        self._start_continuous(hz)
        self.speed_hz = hz
        self.speed_rpm = self._dir_sign * (hz / self.spr) * 60.0
        self._moving = False
        self._move_end_us = None

    def command_move_degrees(self, grados, velocidad_hz=None):
        self.mode = "POS"
        if velocidad_hz is None:
            velocidad_hz = self.default_speed_hz

        self._set_dir_from_sign(grados)
        steps = int(round((abs(grados) / 360.0) * self.spr))
        if steps <= 0 or velocidad_hz <= 0:
            self._moving = False
            self._move_end_us = None
            self._stop_sm()
            return

        self._start_n_pulses(steps, velocidad_hz)
        self.speed_hz = velocidad_hz
        self.speed_rpm = self._dir_sign * (velocidad_hz / self.spr) * 60.0

        self._moving = True
        self._move_end_us = None
        self._pos_before_move = self.pos_deg
        self._planned_increment_deg = self._dir_sign * (steps * 360.0 / self.spr)

    def command_zero_position(self, rpm):
        """
        Homing a la marca de IFR=1.
        - El signo de rpm define la dirección preferida de aproximación.
        - Si inicia ya sobre la marca, primero sale (dirección opuesta) y luego vuelve a entrar.
        """
        self.mode = "ZERO"
        self._zero_done = False
        self._zero_edge_t0 = None

        self._zero_dir_pref = 1 if rpm >= 0 else -1
        hz = abs(rpm) * (self.spr / 60.0)
        if hz <= 0:
            self.command_stop()
            return
        self._zero_start_us = time.ticks_us()  # pyrefly: ignore

        # Si está sobre la marca, salir primero; si no, buscar directamente
        if sensor_ifr.value() == 1:
            # CLEARING: salir de la marca en dirección opuesta
            self._set_dir_from_sign(-self._zero_dir_pref)
            self._start_continuous(hz)
            self._zero_state = 0  # CLEARING
        else:
            # SEEK_HIGH: aproximar en dirección preferida
            self._set_dir_from_sign(self._zero_dir_pref)
            self._start_continuous(hz)
            self._zero_state = 1  # SEEK_HIGH

        self.speed_hz = hz
        self.speed_rpm = self._dir_sign * (hz / self.spr) * 60.0
        self._moving = True
        self._move_end_us = None

    def set_default_speed_hz(self, hz):
        if hz > 0:
            self.default_speed_hz = float(hz)
    # ---------------------------------------------------
    # ---- Llamar frecuentemente en el bucle principal ----
    # ---------------------------------------------------
    def update(self):
        now = time.ticks_us()  # pyrefly: ignore
        dt_us = time.ticks_diff(now, self._last_update_us)  # pyrefly: ignore
        self._last_update_us = now
        dt_s = dt_us / 1_000_000.0

        # Integración de posición durante continuo
        if self._running_continuous and self.speed_hz > 0:
            self.pos_deg += self._dir_sign * (self.speed_hz * dt_s) * (360.0 / self.spr)

        # Fin de tramo POS por IRQ
        if self._move_done_pending:
            self._move_done_pending = False
            self._stop_sm()
            self.speed_hz = 0.0
            self.speed_rpm = 0.0
            self._moving = False
            self._move_end_us = None
            self.pos_deg = self._pos_before_move + self._planned_increment_deg

            if self.mode == "SWEEP":
                if self._sweep_dwell_us > 0:
                    self._sweep_wait_until_us = time.ticks_add(  # pyrefly: ignore
                        now, self._sweep_dwell_us
                    )
                else:
                    inc = self._sweep_next_inc_deg
                    self.command_move_degrees(inc, velocidad_hz=self._sweep_speed_hz)
                    self.mode = "SWEEP"
                    self._sweep_next_inc_deg = -self._sweep_next_inc_deg
                return

        # Re-lanzar SWEEP tras la pausa
        if (
            self.mode == "SWEEP"
            and (not self._moving)
            and (self._sweep_wait_until_us is not None)
        ):
            if time.ticks_diff(now, self._sweep_wait_until_us) >= 0:  # pyrefly: ignore
                self._sweep_wait_until_us = None
                inc = self._sweep_next_inc_deg
                self.command_move_degrees(inc, velocidad_hz=self._sweep_speed_hz)
                self.mode = "SWEEP"
                self._sweep_next_inc_deg = -self._sweep_next_inc_deg

        # ---------- Lógica de ZERO (homing con IFR alto) ----------
        if (
            self.mode == "ZERO"
            and self._running_continuous
            and self._zero_state is not None
        ):
            # Timeout de seguridad
            if time.ticks_diff(now, self._zero_start_us) >= self._zero_timeout_us:
                # Tiempo excedido; detener.
                self._stop_sm()
                self.speed_hz = 0.0
                self.speed_rpm = 0.0
                self._moving = False
                self._zero_state = None
                self._zero_edge_t0 = None
                self.mode = "STOP"
                return

            ifr = sensor_ifr.value()

            if self._zero_state == 0:
                # CLEARING: esperamos salir de la marca (IFR debe caer a 0)
                if ifr == 0:
                    # Ahora aproximamos en la dirección preferida
                    self._set_dir_from_sign(self._zero_dir_pref)
                    # Mantener misma velocidad (self.speed_hz) y actualizar rpm con signo
                    self._start_continuous(self.speed_hz)
                    self.speed_rpm = self._dir_sign * (self.speed_hz / self.spr) * 60.0
                    self._zero_state = 1
                    self._zero_edge_t0 = None  # limpiar debounce

            elif self._zero_state == 1:
                # SEEK_HIGH: buscamos estable IFR=1
                if ifr == 1:
                    if self._zero_edge_t0 is None:
                        self._zero_edge_t0 = now  # primer visto bueno
                    else:
                        if (
                            time.ticks_diff(now, self._zero_edge_t0)  # pyrefly: ignore
                            >= self._zero_debounce_us
                        ):
                            # Marca encontrada de forma estable: detener y poner cero
                            self._stop_sm()
                            self.speed_hz = 0.0
                            self.speed_rpm = 0.0
                            self._moving = False
                            self.pos_deg = 0.0
                            self._zero_state = None
                            self._zero_edge_t0 = None
                            self._zero_done = True
                            self.mode = "STOP"  # Listo; queda en STOP
                else:
                    # Perdimos el nivel alto antes del debounce: reiniciar ventana
                    self._zero_edge_t0 = None


# ---------------- UART + HILO DE COMANDOS ----------------
gc.collect()
stepper = StepperPWMController(step_pin=15, dir_pin=14, steps_per_rev=STEPS_PER_REV)
uart = UART(0, baudrate=UART_BAUD, tx=Pin(0), rx=Pin(1))

uart_lock = _thread.allocate_lock()


def uart_write_line(s):
    with uart_lock:
        uart.write(s)


def handle_commands():
    if uart.any():
        try:
            line = uart.readline()
            if not line:
                return
            # modo:<int:mode>:<float:val>
            parts = line.decode().strip().split(":")
            if len(parts) < 4:
                return
            cmd = parts[0].upper()
            val_str = parts[1]
            val_state = parts[2]
            val_amplitude = parts[3]
            # Permite valores con coma o punto
            val_str = val_str.replace(",", ".")
            try:
                val_mode = float(val_str)
                val_state = float(val_state)
                val_amplitude = float(val_amplitude)
            except Exception as e:
                print("error parse: vals: ", str(e))
                val_mode = 0.0
                val_state = 0.0
                val_amplitude = 0.0

            if cmd == "MODO":
                # 0=POS, 1=RPM, 2=HZ, 3=STOP, 4=SWEEP
                if val_mode == 0:
                    stepper.mode = "POS"
                    stepper.command_move_degrees(val_state)
                elif val_mode == 1:
                    stepper.mode = "RPM"
                    stepper.command_speed_rpm(val_state)
                elif val_mode == 2:
                    stepper.mode = "HZ"
                    stepper.command_speed_hz(val_state)
                elif val_mode == 4:
                    stepper.mode = "SWEEP"
                    stepper.command_sweep(
                        val_amplitude,
                        velocidad_hz=val_state,
                        dwell_ms=(
                            stepper._sweep_dwell_us // 1000
                            if stepper._sweep_dwell_us
                            else 0
                        ),
                    )
                elif val_mode == 6:
                    stepper.mode = "ZERO"
                else:
                    stepper.command_stop()
            elif cmd == "VEL":
                stepper.set_default_speed_hz(val_state)
                # Si estamos en SWEEP, actualizar su velocidad también
                if stepper.mode == "SWEEP":
                    stepper.command_sweep(
                        stepper._sweep_amp_deg,
                        velocidad_hz=val_state,
                        dwell_ms=(
                            stepper._sweep_dwell_us // 1000
                            if stepper._sweep_dwell_us
                            else 0
                        ),
                    )
            elif cmd == "DWELL":
                # Pausa en ms en los extremos de la oscilación
                stepper.set_sweep_dwell_ms(val_state)

            elif cmd == "STOP":
                stepper.mode = "STOP"
                stepper.command_stop()

        except Exception:
            # Evita ruido si llega algo malformado
            pass


def commands_thread(led_ref):
    import time

    while True:
        handle_commands()
        led_ref.toggle()
        # print("command: ")
        time.sleep(0.5)


try:
    _thread.start_new_thread(commands_thread, (led,))
except Exception:
    pass

# -------------------- Bucle principal --------------------
next_tele = time.ticks_us()  # pyrefly: ignore
while True:
    # Servicio del stepper (no bloqueante)
    stepper.update()

    # Telemetría cada 100 ms
    now = time.ticks_us()  # pyrefly: ignore
    if time.ticks_diff(now, next_tele) >= 0:  # pyrefly: ignore
        msg = f"STAT:{stepper.pos_deg}:{stepper.speed_rpm}\n"
        uart_write_line(msg)
        next_tele = time.ticks_add(next_tele, TELEMETRY_INTERVAL_US)  # pyrefly: ignore

    time.sleep_us(300)  # pyrefly: ignore
