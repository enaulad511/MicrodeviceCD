# -*- coding: utf-8 -*-
import serial
import threading
import time
import gpiod
from gpiod.line import Direction, Value


__author__ = "Edisson A. Naula"
__date__ = "$ 19/02/2026  at 08:11 a.m. $"

STEPS_PER_REV = 400

class DriverStepperSys:
    """
    Control de motor a pasos con Raspberry Pi Pico por UART.
    - Protocolo de comandos esperado en el Pico:
        MODO:0  -> POS (movimiento relativo en grados)
        MODO:1  -> RPM (velocidad continua en RPM, signo = dirección)
        MODO:2  -> HZ  (velocidad continua en Hz, signo = dirección)
        MODO:3  -> STOP
        SET:x   -> valor según el modo
        VEL:hz  -> velocidad por defecto (Hz) para POS
        STOP:0  -> detener

    - Telemetría periódica (cada ~100 ms):
        STAT:<posicion_deg_estimada>:<rpm_estimada>

    - Soporta manejo de pin ENABLE del driver a través de libgpiod (opcional).
    """

    def __init__(
        self,
        en_pin=None,  # GPIO para ENABLE del driver (opcional)
        enable_active_high=False,  # True si ENABLE activo en alto; default False (activo en bajo)
        uart_port="/dev/ttyAMA0",  # En RPi 4 puedes usar "/dev/ttyAMA0" o "/dev/serial0"
        baudrate=921600,
        chip="/dev/gpiochip0",
        read_timeout=0.20,  # Timeout lectura serial (s)
        ack_timeout=0.50,  # Timeout espera ACK (s)
    ):
        self.en_pin = en_pin
        self.enable_active_high = bool(enable_active_high)
        self.chip = chip
        self.ack_timeout = float(ack_timeout)

        # ---- GPIO (ENABLE) opcional ----
        self._gpio_request = None
        if self.en_pin is not None:
            cfg = {
                self.en_pin: gpiod.LineSettings(
                    direction=Direction.OUTPUT,
                    output_value=Value.ACTIVE
                    if self.enable_active_high
                    else Value.INACTIVE,
                )
            }
            self._gpio_request = gpiod.request_lines(
                chip, consumer="stepper-enable", config=cfg
            )

        # ---- UART ----
        # ¡Asegúrate que coincida con el formato del Pico (8N1)!
        self.ser = serial.Serial(
            uart_port,
            baudrate=baudrate,
            timeout=read_timeout,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,  # 8N1 para coincidir con MicroPython por defecto
            write_timeout=0.2,
        )
        self.ser.reset_input_buffer()

        # ---- Estado y sincronización ----
        self._wlock = threading.Lock()  # lock para escrituras UART
        self._ack_event = threading.Event()  # evento de ACK
        self._last_ack = None  # último ACK completo (str)
        self._last_mode = "STOP"

        self._stat_lock = threading.Lock()
        self._last_status = {
            "pos_deg": 0.0,
            "rpm": 0.0,
            "ts": time.time(),
        }

        self._running = True
        self._rx_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._rx_thread.start()

        # Si usas ENABLE activo en bajo, al iniciar lo ponemos deshabilitado (HIGH)
        if self.en_pin is not None:
            self.enable_driver(False)

    # --------------------- Gestión ENABLE (opcional) ---------------------
    def enable_driver(self, active: bool):
        """
        Habilita o deshabilita el driver de pasos (si en_pin fue configurado).
        active=True -> habilitar motor (pasan pulsos)
        """
        if self._gpio_request is None:
            return
        # Ajusta según polaridad:
        # enable_active_high=False (activo en bajo): activo -> Value.INACTIVE? No.
        # Mapeamos claramente:
        if self.enable_active_high:
            val = Value.ACTIVE if active else Value.INACTIVE
        else:
            # Activo en bajo: active=True => línea a 0 (INACTIVE), active=False => 1 (ACTIVE)
            val = Value.INACTIVE if active else Value.ACTIVE
        self._gpio_request.set_value(self.en_pin, val)

    # --------------------- Comunicación UART ---------------------
    def _send_line(self, s: str):
        if not s.endswith("\n"):
            s += "\n"
        data = s.encode("utf-8", errors="ignore")
        with self._wlock:
            self.ser.write(data)

    def _wait_ack(self, timeout=None):
        """
        Espera un ACK (línea que empieza con 'ACK:') hasta timeout.
        Devuelve la cadena ACK o None si expira.
        """
        self._ack_event.clear()
        # Prevenir caso en que _reader_loop ya leyó un ACK justo antes
        if self._last_ack is not None:
            ack = self._last_ack
            self._last_ack = None
            return ack

        if not self._ack_event.wait(timeout or self.ack_timeout):
            return None
        ack = self._last_ack
        self._last_ack = None
        return ack

    def _handle_line(self, line: str):
        if not line:
            return

        # Normaliza
        line = line.strip()

        # Telemetría: STAT:<pos>:<rpm>
        if line.startswith("STAT:"):
            try:
                _, pos_s, rpm_s = line.split(":")
                pos = float(pos_s)
                rpm = float(rpm_s)
                with self._stat_lock:
                    self._last_status.update(
                        {"pos_deg": pos, "rpm": rpm, "ts": time.time()}
                    )
            except Exception:
                pass
            return

        # ACK:MODE:VAL (del firmware del Pico)
        if line.startswith("ACK:"):
            self._last_ack = line
            # Intentar capturar modo para mantener estado
            try:
                _, mode_s, _ = line.split(":")
                self._last_mode = mode_s
            except Exception:
                pass
            self._ack_event.set()
            return

        # Otras líneas (debug o ruido): ignorar
        return

    def _reader_loop(self):
        buf = bytearray()
        while self._running:
            try:
                raw = self.ser.readline()  # lee hasta '\n' o timeout
                if not raw:
                    continue
                try:
                    line = raw.decode("utf-8", errors="ignore")
                except Exception:
                    line = ""
                self._handle_line(line)
            except Exception:
                # Evitar romper el hilo por un error transitorio de lectura
                time.sleep(0.01)

    # --------------------- Helpers de protocolo ---------------------
    def _cmd_mode(self, mode_code: int):
        """Envía MODO:x y espera ACK."""
        self._send_line(f"MODO:{mode_code}")
        return self._wait_ack()

    def _cmd_set(self, value):
        """Envía SET:x y espera ACK."""
        self._send_line(f"SET:{value}")
        return self._wait_ack()

    def _cmd_vel(self, hz):
        """Envía VEL:hz y espera ACK."""
        self._send_line(f"VEL:{hz}")
        return self._wait_ack()

    def _cmd_stop(self):
        """Envía STOP:0 (y también MODO:3 por robustez)."""
        self._send_line("STOP:0")
        ack1 = self._wait_ack()
        self._send_line("MODO:3")
        ack2 = self._wait_ack()
        return ack2 or ack1

    # --------------------- API pública de control ---------------------
    def set_default_speed_hz(self, hz: float) -> bool:
        """Ajusta la velocidad por defecto (Hz) para movimientos POS."""
        ack = self._cmd_vel(hz)
        return ack is not None

    def move_degrees(
        self,
        grados: float,
        vel_hz: float | None = None,
        wait: bool = False,
        timeout: float | None = None,
    ) -> bool:
        """
        Movimiento relativo en grados (no bloqueante por defecto).
        Si 'wait=True', espera hasta que la velocidad reported (|rpm|) sea ~0 (fin del movimiento).
        """
        ok = True
        # MODO POS
        ok &= self._cmd_mode(0) is not None
        # VEL opcional
        if vel_hz is not None:
            ok &= self._cmd_vel(vel_hz) is not None
        # SET grados
        ok &= self._cmd_set(grados) is not None
        
        if not ok or not wait:
            return ok

        # Esperar a que termine (heurística por rpm ≈ 0)
        t0 = time.time()
        quiet_samples = 0
        while True:
            st = self.get_status()
            rpm = abs(st["rpm"])
            if rpm < 0.01:
                quiet_samples += 1
            else:
                quiet_samples = 0

            if quiet_samples >= 2:  # dos muestras consecutivas ~0 (200ms aprox)
                return True

            if timeout and (time.time() - t0) > timeout:
                return False
            time.sleep(0.1)

    def run_rpm(self, rpm: float) -> bool:
        """Velocidad continua en RPM (signo = dirección)."""
        ok = True
        ok &= self._cmd_mode(1) is not None
        ok &= self._cmd_set(rpm) is not None
        return ok

    def run_hz(self, hz_signed: float) -> bool:
        """Velocidad continua en Hz (signo = dirección)."""
        ok = True
        ok &= self._cmd_mode(2) is not None
        ok &= self._cmd_set(hz_signed) is not None
        return ok

    def stop(self) -> bool:
        """Detiene el movimiento."""
        return self._cmd_stop() is not None

    def get_status(self) -> dict:
        """
        Devuelve un snapshot del último 'STAT' recibido:
        {'pos_deg': float, 'rpm': float, 'ts': epoch_seg}
        """
        with self._stat_lock:
            return dict(self._last_status)

    def close(self):
        """Cierra UART y libera recursos GPIO."""
        self._running = False
        try:
            if self._rx_thread.is_alive():
                self._rx_thread.join(timeout=0.5)
        except Exception:
            pass
        try:
            self.ser.close()
        except Exception:
            pass
        try:
            if self._gpio_request is not None:
                # Deshabilitar el driver al cerrar (seguro)
                self.enable_driver(False)
                self._gpio_request.release()
        except Exception:
            pass

    # Context manager
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


if __name__ == "__main__":
    # Habilita si tienes pin ENABLE: por ejemplo GPIO17 (BCM)
    # Para DRV8825/A4988 normalmente ENABLE es ACTIVO EN BAJO => enable_active_high=False
    drv = DriverStepperSys(
        en_pin=17, enable_active_high=False, uart_port="/dev/ttyAMA0"
    )

    # Habilitar driver (pone ENABLE a nivel activo según tu hardware)
    drv.enable_driver(True)

    # # 1) Movimiento relativo: 2 vueltas (720°) a 800 Hz, esperar a que termine
    # drv.set_default_speed_hz(800)
    # ok = drv.move_degrees(720, wait=True, timeout=10)
    # print("Movimiento completado:", ok, drv.get_status())

    # # 2) Velocidad continua: +60 RPM por 3 segundos
    # drv.run_rpm(60)
    # time.sleep(3)
    # print("Estado:", drv.get_status())

    # # 3) Cambiar a Hz directo: -1200 Hz por 2 segundos
    # drv.run_hz(-1200)
    # time.sleep(2)
    # print("Estado:", drv.get_status())

    n_time = 10
    #oscilar n veces +-30
    for i in range(n_time):
        print(f"Oscilación {i+1}/{n_time}: +30°")
        drv.move_degrees(30, vel_hz=800, wait=True, timeout=5)
        print(f"Oscilación {i+1}/{n_time}: -30°")
        drv.move_degrees(-30, vel_hz=800, wait=True, timeout=5)

    # 4) Parar
    drv.stop()
    print("Parado:", drv.get_status())

    # 5) Deshabilitar driver y cerrar
    drv.enable_driver(False)
    drv.close()
