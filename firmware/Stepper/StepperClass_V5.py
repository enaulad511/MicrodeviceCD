# -*- coding: utf-8 -*-
from machine import Pin, UART, Timer
import machine
import time, micropython, gc
from rp2 import PIO, StateMachine, asm_pio
import _thread

__author__ = "Edisson Naula"
__date__ = "$ 10/06/2026 at 17:30 $"

# V5 (basado en main_copy.py / V4):
#   - Rampa de velocidad EN EL FIRMWARE para modos continuos (RPM/HZ):
#     MODO:1:<rpm>:<accel_rpm_s>  (accel 0 = cambio inmediato, comportamiento legado).
#     El slew se hace en update() escribiendo el divisor de reloj del PIO en vivo
#     (sin recrear la StateMachine en cada paso).
#   - STOP:0 = frenado en rampa con la pendiente del último MODO:1 (inmediato si
#     no hubo rampa). STOP:1 = paro de emergencia inmediato.
#   - Hilo de comandos: de 1 línea cada 0.5 s a drenado completo cada 10 ms con
#     buffer de líneas (la causa del frenado de golpe: el RX se desbordaba y el
#     STOP llegaba tarde o se perdía).

micropython.alloc_emergency_exception_buf(128)

# --- CONSTANTES / CONFIG ---
IFR_S_PIN = 22
UART_BAUD = 115200
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
    pull(block)  # Espera primer comando en TX FIFO
    mov(x, osr)  # X = OSR (0 => continuo, N>0 => finito)
    jmp(not_x, "cont")  # Si X == 0 -> ir a modo continuo

    # ---- MODO FINITO (N PULSOS) ----
    label("finite")
    set(pins, 1)  # HIGH
    set(pins, 0)  # LOW
    jmp(x_dec, "finite")  # post-decrementa X y repite mientras X > 0
    irq(0)  # Fin de la secuencia
    jmp("wait_next")  # Espera nuevo comando

    # ---- MODO CONTINUO ----
    label("cont")
    set(pins, 1)  # HIGH
    set(pins, 0)  # LOW
    jmp("cont")  # Repite indefinidamente

    # ---- ESPERAR SIGUIENTE COMANDO ----
    label("wait_next")
    pull(block)
    mov(x, osr)
    jmp(not_x, "cont")  # Si X == 0 -> continuo
    jmp("finite")  # Si X > 0 -> finito


class StepperPWMController:
    def __init__(
        self,
        step_pin=17,
        dir_pin=16,
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
        self._last_update_us = time.ticks_us()
        self._move_done_pending = False
        self._running_continuous = False

        # ---- Rampa (modos continuos RPM/HZ) ----
        # El slew corre en update(); _ramp_cur_hz lleva Hz CON SIGNO.
        # El PIO no puede generar pasos por debajo de sysclk/(2*65536)
        # (~954 Hz a 125 MHz ≈ 9 RPM con 6400 spr): bajo ese umbral la SM se
        # pausa (zona muerta) y la rampa sigue integrando hasta cruzar 0 o
        # volver a superar el umbral (cambio de dirección incluido).
        self._sys_hz = float(machine.freq())
        self._min_step_hz = self._sys_hz / (2.0 * 65536.0) + 1.0
        pio_base = 0x50200000 if sm_id < 4 else 0x50300000
        self._clkdiv_addr = pio_base + 0x0C8 + (sm_id % 4) * 0x18
        self._ramp_active = False
        self._ramp_cur_hz = 0.0
        self._ramp_target_hz = 0.0
        self._ramp_accel_hz_s = 0.0  # pendiente en Hz/s (0 = sin rampa)

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

    def _write_clkdiv(self, step_hz):
        # Cambio de frecuencia EN VIVO escribiendo SMx_CLKDIV (INT[31:16].FRAC[15:8])
        # sin recrear la StateMachine (la SM sigue corriendo el lazo continuo).
        div = self._sys_hz / (2.0 * step_hz)
        if div < 1.0:
            div = 1.0
        elif div > 65535.99:
            div = 65535.99
        machine.mem32[self._clkdiv_addr] = int(div * 256.0) << 8

    def _start_continuous(self, step_hz):
        # Reinicia la SM (PC en pull(block), FIFOs limpios): un put por arranque.
        # Sin esto, re-activar una SM pausada retoma el lazo "cont" sin hacer
        # pull y los put repetidos acabarían llenando (y bloqueando) el FIFO.
        self._init_sm(step_hz)
        self.sm.active(1)
        self.sm.put(0xFFFFFFFF)  # continuo
        self._running_continuous = True

    def _start_n_pulses(self, steps, step_hz):
        if steps <= 0:
            return
        self._init_sm(step_hz)
        self.sm.active(1)
        self.sm.put((int(steps) - 1) & 0xFFFFFFFF)
        self._running_continuous = False

    def _stop_sm(self):
        try:
            self.sm.active(0)
        except Exception:
            pass
        self._running_continuous = False

    # ---- Utilidades internas ----
    def _set_dir_from_sign(self, sign):
        new_sign = 1 if sign >= 0 else -1
        if new_sign != self._dir_sign:
            self._dir_sign = new_sign
            self.dir.value(1 if self._dir_sign > 0 else 0)
            time.sleep_us(self._dir_setup_us)
        else:
            self._dir_sign = new_sign
            self.dir.value(1 if self._dir_sign > 0 else 0)

    def _on_pio_irq(self, sm):
        self._move_done_pending = True

    # ---- Rampa (slew de Hz con signo en modos continuos) ----
    def _ramp_cancel(self):
        self._ramp_active = False
        self._ramp_cur_hz = 0.0
        self._ramp_target_hz = 0.0

    def _ramp_to(self, hz_signed_target, accel_hz_s):
        # Programa la rampa; el avance ocurre en update().
        if not self._ramp_active:
            # Partir de la velocidad real actual (0 si está detenido)
            self._ramp_cur_hz = (
                self._dir_sign * self.speed_hz if self._running_continuous else 0.0
            )
        self._ramp_target_hz = hz_signed_target
        self._ramp_accel_hz_s = accel_hz_s
        self._ramp_active = True
        self._moving = False
        self._move_end_us = None

    def _apply_continuous_hz(self, hz_signed):
        mag = abs(hz_signed)
        if mag < self._min_step_hz:
            # Zona muerta del divisor PIO: pausa los pulsos cerca de 0
            if self._running_continuous:
                self._stop_sm()
            self.speed_hz = 0.0
            self.speed_rpm = 0.0
            return
        self._set_dir_from_sign(hz_signed)
        if not self._running_continuous:
            self._start_continuous(mag)
        else:
            self._write_clkdiv(mag)
        self.speed_hz = mag
        self.speed_rpm = self._dir_sign * (mag / self.spr) * 60.0

    # ---- Comandos de alto nivel ----
    def command_sweep(self, amplitude_deg, velocidad_hz=None, dwell_ms=0):
        self.mode = "SWEEP"
        if velocidad_hz is None:
            velocidad_hz = self.default_speed_hz
        # check that vel is not more than 10 times default
        velocidad_hz = min(velocidad_hz, 10 * self.default_speed_hz)
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

    def command_stop(self, ramped=False):
        # STOP:0 (ramped=True): frenado suave con la pendiente del último
        # MODO:1/2 si el motor está en modo continuo; de lo contrario (o con
        # STOP:1) paro inmediato.
        if (
            ramped
            and self._ramp_accel_hz_s > 0.0
            and self.mode in ("RPM", "HZ")
            and (self._ramp_active or self._running_continuous)
        ):
            if not self._ramp_active:
                self._ramp_cur_hz = self._dir_sign * self.speed_hz
                self._ramp_active = True
            self._ramp_target_hz = 0.0
            return
        self.mode = "STOP"
        self._stop_sm()
        self._ramp_cancel()
        self.speed_hz = 0.0
        self.speed_rpm = 0.0
        self._moving = False
        self._move_end_us = None
        self._sweep_wait_until_us = None
        # Cancelar ZERO si estaba activo
        self._zero_state = None
        self._zero_edge_t0 = None

    def command_speed_rpm(self, rpm, accel_rpm_s=0.0):
        self.mode = "RPM"
        if accel_rpm_s > 0.0:
            self._ramp_to(
                rpm * (self.spr / 60.0), abs(accel_rpm_s) * (self.spr / 60.0)
            )
            return
        # Cambio inmediato (comportamiento legado)
        self._ramp_cancel()
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

    def command_speed_hz(self, hz_signed, accel_hz_s=0.0):
        self.mode = "HZ"
        if accel_hz_s > 0.0:
            self._ramp_to(float(hz_signed), abs(accel_hz_s))
            return
        # Cambio inmediato (comportamiento legado)
        self._ramp_cancel()
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
        self._ramp_cancel()
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
        self._ramp_cancel()
        self._zero_done = False
        self._zero_edge_t0 = None

        self._zero_dir_pref = 1 if rpm >= 0 else -1
        hz = abs(rpm) * (self.spr / 60.0)
        if hz <= 0:
            self.command_stop()
            return
        self._zero_start_us = time.ticks_us()

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
        now = time.ticks_us()
        dt_us = time.ticks_diff(now, self._last_update_us)
        self._last_update_us = now
        dt_s = dt_us / 1_000_000.0

        # ---------- Rampa de velocidad (modos continuos) ----------
        if self._ramp_active:
            cur = self._ramp_cur_hz
            tgt = self._ramp_target_hz
            step = self._ramp_accel_hz_s * dt_s
            if abs(tgt - cur) <= step:
                cur = tgt
            else:
                cur += step if tgt > cur else -step
            self._ramp_cur_hz = cur
            self._apply_continuous_hz(cur)
            if cur == tgt:
                self._ramp_active = False
                if tgt == 0.0:
                    self._stop_sm()
                    self.speed_hz = 0.0
                    self.speed_rpm = 0.0
                    self.mode = "STOP"

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
                    self._sweep_wait_until_us = time.ticks_add(
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
            if time.ticks_diff(now, self._sweep_wait_until_us) >= 0:
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
                            time.ticks_diff(now, self._zero_edge_t0)
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
stepper = StepperPWMController(step_pin=17, dir_pin=16, steps_per_rev=STEPS_PER_REV)
uart = UART(0, baudrate=UART_BAUD, tx=Pin(0), rx=Pin(1), rxbuf=512)

uart_lock = _thread.allocate_lock()


def uart_write_line(s):
    with uart_lock:
        uart.write(s)


def _process_command(line):
    try:
        # <cmd>:<float>:<float>:<float>  (4 campos siempre)
        parts = line.decode().strip().split(":")
        if len(parts) < 4:
            return
        cmd = parts[0].upper()
        # Permite valores con coma o punto
        try:
            val_mode = float(parts[1].replace(",", "."))
            val_state = float(parts[2].replace(",", "."))
            val_amplitude = float(parts[3].replace(",", "."))
        except Exception as e:
            print("error parse: vals: ", str(e))
            return

        if cmd == "MODO":
            # 0=POS, 1=RPM, 2=HZ, 3=STOP, 4=SWEEP, 6=ZERO
            if val_mode == 0:
                stepper.command_move_degrees(val_state)
            elif val_mode == 1:
                # MODO:1:<rpm>:<accel_rpm_s>  (accel 0 = inmediato)
                stepper.command_speed_rpm(val_state, accel_rpm_s=val_amplitude)
            elif val_mode == 2:
                # MODO:2:<hz>:<accel_hz_s>  (accel 0 = inmediato)
                stepper.command_speed_hz(val_state, accel_hz_s=val_amplitude)
            elif val_mode == 4:
                stepper.command_sweep(
                    val_state,
                    velocidad_hz=val_amplitude,
                    dwell_ms=(
                        stepper._sweep_dwell_us // 1000
                        if stepper._sweep_dwell_us
                        else 0
                    ),
                )
            elif val_mode == 6:
                stepper.command_zero_position(val_state)
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
            # STOP:0 = frenado en rampa (si hubo MODO:1/2 con accel);
            # STOP:1 = paro de emergencia inmediato.
            stepper.command_stop(ramped=(val_mode == 0))

    except Exception:
        # Evita ruido si llega algo malformado
        pass


_rx_buf = b""


def handle_commands():
    # Drena TODO lo pendiente del UART y procesa cada línea completa.
    # (V4 leía 1 línea cada 0.5 s: el RX se desbordaba durante las rampas
    # del host y el STOP llegaba tarde o se perdía.)
    global _rx_buf
    n = uart.any()
    if n:
        data = uart.read(n)
        if data:
            _rx_buf += data
            if len(_rx_buf) > 1024:
                _rx_buf = _rx_buf[-256:]  # protección ante desborde
    while b"\n" in _rx_buf:
        line, _rx_buf = _rx_buf.split(b"\n", 1)
        if line:
            _process_command(line)


def commands_thread(led_ref):
    blink = 0
    while True:
        handle_commands()
        blink += 1
        if blink >= 50:  # parpadeo ~0.5 s como antes
            blink = 0
            led_ref.toggle()
        time.sleep_ms(10)


try:
    _thread.start_new_thread(commands_thread, (led,))
except Exception:
    pass

# -------------------- Bucle principal --------------------
next_tele = time.ticks_us()
while True:
    # Servicio del stepper (no bloqueante)
    stepper.update()

    # Telemetría cada 50 ms
    now = time.ticks_us()
    if time.ticks_diff(now, next_tele) >= 0:
        msg = f"STAT:{stepper.pos_deg}:{stepper.speed_rpm}\n"
        uart_write_line(msg)
        next_tele = time.ticks_add(next_tele, TELEMETRY_INTERVAL_US)

    time.sleep_us(300)
