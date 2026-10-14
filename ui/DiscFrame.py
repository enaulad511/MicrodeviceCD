# -*- coding: utf-8 -*-

import threading
import time

import ttkbootstrap as ttk
from ttkbootstrap.scrolled import ScrolledFrame

from templates.constants import font_entry, serial_port_encoder
from templates.utils import read_settings_from_file
from ui.KeyboardFrame import NumericKeyboard

__author__ = "Edisson A. Naula"
__date__ = "$ 08/10/2025  at 11:11 a.m. $"


def create_widgets_disco_input(parent, callbacks: dict):
    entries = []
    entry_widgets = []
    parent.columnconfigure((0, 1), weight=1)
    parent.rowconfigure((0, 1), weight=1)
    # Mode 1: Continuous rotation CW or CCW with RPM
    frame1 = ttk.LabelFrame(parent, text="Continuous Rotation")
    frame1.grid(row=0, column=0, padx=(2, 20), pady=10, sticky="nswe")
    frame1.configure(style="Custom.TLabelframe")
    frame1.columnconfigure((0, 1), weight=1)

    ttk.Label(frame1, text="Direction:", style="Custom.TLabel").grid(
        row=0, column=0, padx=5, pady=5, sticky="w"
    )
    svar_dir = ttk.StringVar()
    dir_combo = ttk.Combobox(
        frame1, values=["CW", "CCW"], textvariable=svar_dir, font=font_entry, width=5
    )
    dir_combo.grid(row=0, column=1, padx=5, pady=5)
    dir_combo.current(0)
    entries.append(svar_dir)

    ttk.Label(frame1, text="RPM:", style="Custom.TLabel").grid(
        row=1, column=0, padx=5, pady=5, sticky="w"
    )
    svar_rpm = ttk.StringVar(value="700")
    rpm_entry = ttk.Entry(frame1, font=font_entry, textvariable=svar_rpm, width=5)
    rpm_entry.grid(row=1, column=1, padx=5, pady=5, sticky="w")
    entries.append(svar_rpm)
    entry_widgets.append(rpm_entry)

    ttk.Button(
        frame1,
        text="Start Rotation",
        style="info.TButton",
        command=callbacks.get("callback_spin", ()),
    ).grid(row=2, column=0, columnspan=2, pady=5, padx=5, sticky="n")
    frame1.rowconfigure((0, 1, 2), weight=1)
    # Mode 2: On/Off cycle
    frame2 = ttk.LabelFrame(parent, text="On/Off Cycle")
    # frame2.grid(row=1, column=0, padx=(2, 20), pady=10, sticky="nswe")
    frame2.configure(style="Custom.TLabelframe")
    frame2.columnconfigure((0, 1), weight=1)

    ttk.Label(frame2, text="Number of cycles:", style="Custom.TLabel").grid(
        row=0, column=0, padx=5, pady=5, sticky="w"
    )
    svar_cycles = ttk.StringVar()
    cycles_entry = ttk.Entry(frame2, font=font_entry, textvariable=svar_cycles, width=5)
    cycles_entry.grid(row=0, column=1, padx=5, pady=5, sticky="s")
    entries.append(svar_cycles)
    entry_widgets.append(cycles_entry)

    ttk.Label(frame2, text="Acceleration time (ms):", style="Custom.TLabel").grid(
        row=1, column=0, padx=5, pady=5, sticky="w"
    )
    svar_accel = ttk.StringVar()
    accel_entry = ttk.Entry(frame2, font=font_entry, textvariable=svar_accel, width=5)
    accel_entry.grid(row=1, column=1, padx=5, pady=5, sticky="w")
    entries.append(svar_accel)
    entry_widgets.append(accel_entry)

    ttk.Label(frame2, text="Target RPM:", style="Custom.TLabel").grid(
        row=2, column=0, padx=5, pady=5, sticky="w"
    )
    svar_target_rpm = ttk.StringVar()
    target_rpm_entry = ttk.Entry(
        frame2, font=font_entry, textvariable=svar_target_rpm, width=5
    )
    target_rpm_entry.grid(row=2, column=1, padx=5, pady=5, sticky="w")
    entries.append(svar_target_rpm)
    entry_widgets.append(target_rpm_entry)

    ttk.Label(frame2, text="Deceleration time (ms):", style="Custom.TLabel").grid(
        row=3, column=0, padx=5, pady=5, sticky="w"
    )
    svar_decel = ttk.StringVar()
    decel_entry = ttk.Entry(frame2, font=font_entry, textvariable=svar_decel, width=5)
    decel_entry.grid(row=3, column=1, padx=5, pady=5, sticky="w")
    entries.append(svar_decel)
    entry_widgets.append(decel_entry)

    ttk.Button(
        frame2,
        text="Run Cycle",
        style="info.TButton",
        command=callbacks.get("callback_cycle", ()),
    ).grid(row=4, column=0, columnspan=2, pady=5, padx=5, sticky="n")

    # Mode 3: Oscillator
    frame3 = ttk.LabelFrame(parent, text="Oscillator Mode")
    frame3.grid(row=0, column=1, padx=(2, 20), pady=10, sticky="nswe")
    frame3.configure(style="Custom.TLabelframe")
    frame3.columnconfigure((0, 1), weight=1)

    ttk.Label(frame3, text="Angle (°, max 30):", style="Custom.TLabel").grid(
        row=0, column=0, padx=5, pady=5, sticky="w"
    )
    svar_angle = ttk.StringVar(value="30")
    angle_entry = ttk.Entry(frame3, font=font_entry, textvariable=svar_angle, width=5)
    angle_entry.grid(row=0, column=1, padx=5, pady=5, sticky="w")
    entries.append(svar_angle)
    entry_widgets.append(angle_entry)

    ttk.Label(frame3, text="Speed (%):", style="Custom.TLabel").grid(
        row=1, column=0, padx=5, pady=5, sticky="w"
    )
    svar_speed = ttk.StringVar(value="10")
    speed_entry = ttk.Entry(frame3, font=font_entry, textvariable=svar_speed, width=5)
    speed_entry.grid(row=1, column=1, padx=5, pady=5, sticky="w")
    entries.append(svar_speed)
    entry_widgets.append(speed_entry)

    ttk.Button(
        frame3,
        text="Start Oscillation",
        style="info.TButton",
        command=callbacks.get("callback_oscillator", ()),
    ).grid(row=2, column=0, columnspan=2, pady=5, padx=5, sticky="n")

    # mode 4: go to zero require rpm
    frame4 = ttk.LabelFrame(parent, text="Go to Zero")
    frame4.grid(row=1, column=0, padx=(2, 20), pady=10, sticky="nswe")
    frame4.configure(style="Custom.TLabelframe")
    frame4.columnconfigure((0, 1), weight=1)
    ttk.Label(frame4, text="RPM for zeroing:", style="Custom.TLabel").grid(
        row=0, column=0, padx=5, pady=5, sticky="w"
    )
    svar_zero_rpm = ttk.StringVar(value="50")
    zero_rpm_entry = ttk.Entry(
        frame4, font=font_entry, textvariable=svar_zero_rpm, width=5
    )
    zero_rpm_entry.grid(row=0, column=1, padx=5, pady=5, sticky="w")
    entries.append(svar_zero_rpm)
    entry_widgets.append(zero_rpm_entry)
    ttk.Button(
        frame4,
        text="Go to Zero",
        style="info.TButton",
        command=callbacks.get("callback_zero", ()),
    ).grid(row=1, column=0, columnspan=2, pady=5, padx=5, sticky="n")
    # Mode 5: Stop
    ttk.Button(
        parent,
        text="Stop",
        style="danger.TButton",
        command=callbacks.get("callback_stop", ()),
    ).grid(row=1, column=1, pady=10, padx=5, sticky="n")

    return entries, entry_widgets


# Variables globales
drv = None
thread_motor = None
thread_lock = threading.Lock()


def release_driver():
    """Deshabilita y cierra el driver compartido (UART + GPIO 12 de ENABLE) si
    está abierto. Idempotente y seguro desde cualquier hilo. Mientras siga
    abierto, PCR/CV/SWV no pueden crear el suyo (line busy en GPIO 12) y su
    hilo lector (no daemon) impide que el proceso termine al cerrar la app."""
    global drv
    with thread_lock:
        if drv is None:
            return
        try:
            drv.enable_driver(False)
            drv.close()
            print("Motor driver released (UART/GPIO)")
        except Exception as e:
            print(f"Error releasing motor driver: {e}")
        drv = None


def run_and_release(target, *args):
    """Corre una función de movimiento y, al terminar por cualquier causa (Stop,
    fin natural del go-to-zero, excepción), libera el driver compartido: así el
    driver solo está abierto mientras hay un hilo de motor vivo."""
    try:
        target(*args)
    finally:
        release_driver()


# spinMotorRPM_ramped vive ahora en Drivers/DriverStepperSys.py (centralizado);
# la rampa de velocidad corre en el firmware del Pico (StepperClass_V5).
# Importarlo de forma lazy dentro de cada callback (el módulo del driver
# importa gpiod/serial y rompería el modo dev en Windows a nivel de módulo).


def spinMotorAngle(
    angle, rpm, max_rpm, n_times=None, flag_continue=False, stop_event=None, drv=None
):
    """
    Versión global que usa los helpers del objeto global 'drv':
      - drv._cmd_mode(4)
      - drv._cmd_vel(hz)
      - drv._cmd_set(angle)
      - drv._cmd_stop()
    Requiere que 'drv' tenga 'steps_per_rev' o usa 400 por defecto.
    Requiere 'stop_event' global si se usa modo continuo.
    """
    import time as _t

    from Drivers.DriverStepperSys import STEPS_PER_REV
    if drv is None:
        print("[spinMotorAngle] drv is not initialized.")
        return
    if stop_event is None:
        print(
            "[spinMotorAngle] stop_event not provided; required for stop control."
        )
        return
    try:
        angle = float(angle)
        rpm = float(rpm)
        max_rpm = float(max_rpm)
    except Exception as e:
        raise ValueError(f"Invalid parameters: {e}")

    if angle <= 0:
        drv.stop()
        print("[spinMotorAngle] angle <= 0; STOP.")
        return

    rpm_eff = max(min(abs(rpm), abs(max_rpm)), 0.0)
    speed_hz = rpm_eff * (STEPS_PER_REV / 60.0)
    if speed_hz <= 0.0:
        drv.stop()
        print("[spinMotorAngle] Resulting speed = 0 Hz; STOP.")
        return

    drv.run_sweep(angle, speed_hz)

    vel_deg_s = speed_hz * (360.0 / STEPS_PER_REV)
    if vel_deg_s <= 0:
        drv.stop()
        return

    T_cycle = (4.0 * abs(angle)) / vel_deg_s
    T_cycle *= 1.03  # 3% de margen

    try:
        if n_times is not None:
            n_times = int(n_times)
            if n_times <= 0:
                print("[spinMotorAngle] n_times<=0; STOP.")
            else:
                total_time = n_times * T_cycle
                print(
                    f"[spinMotorAngle] SWEEP {n_times} cycles: ±{angle}°, "
                    f"Hz={speed_hz:.1f}, T_cycle≈{T_cycle:.3f}s, T_total≈{total_time:.3f}s"
                )
                elapsed = 0.0
                step = 0.01
                while elapsed < total_time:
                    if stop_event.is_set():
                        print("[spinMotorAngle] stop_event detected; aborting.")
                        break
                    _t.sleep(step)
                    elapsed += step
        else:
            if flag_continue:
                print(
                    f"[spinMotorAngle] Continuous SWEEP: ±{angle}° @ {rpm_eff} rpm (Hz={speed_hz:.1f})"
                )
                while not stop_event.is_set():
                    _t.sleep(0.02)
            else:
                print(f"[spinMotorAngle] SWEEP 1 cycle: ±{angle}°, T≈{T_cycle:.3f}s")
                _t.sleep(T_cycle)
    finally:
        drv.stop()
        print("Motor stopped")


def spinMotorToZero(rpm, drv_motor=None, stop_event=None):
    global drv
    if drv_motor is not None and drv is None:
        drv = drv_motor
    if stop_event is None:
        print("[spinMotorToZero] stop_event not provided.")
        return
    if drv is None:
        print("[spinMotorToZero] drv is not initialized.")
        return
    print(f"Spin to zero at {rpm} RPM...")
    while not stop_event.is_set():
        drv.go_zero(rpm)
        status = drv.get_status()
        rpm_status = [1, 1, abs(status.get("rpm", 1))]
        while sum(abs(x) for x in rpm_status) > 0:
            time.sleep(0.5)
            status = drv.get_status()
            rpm_status = rpm_status[1:] + [abs(status.get("rpm", 1))]
            print(rpm_status)
        break
    if drv is not None:
        drv.stop()
        status = drv.get_status()
        print(
            f"Stopped--> pos: {status.get('pos_deg'):.2f}°, rpm: {status.get('rpm'):.2f}"
        )
        drv = None if drv_motor is not None else drv


class ControlDiscFrame(ttk.Frame):
    """UI class for manual disc control.

    :param parent: parent frame to be placed
    :type parent: ttk.Frame
    """

    def __init__(self, parent, lock_tabs_callback=None):
        ttk.Frame.__init__(self, parent)
        self.parent = parent
        # Bloquea PCR/Electrochemical mientras el motor de esta tab gira (ver
        # _lock_while_running); lo provee MainGUI.
        self.lock_tabs_callback = lock_tabs_callback
        self._motor_thread: threading.Thread | None = None
        self._lock_job: str | None = None
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        content_frame = ScrolledFrame(self, autohide=True)
        content_frame.grid(row=0, column=0, sticky="nsew")
        content_frame.columnconfigure(0, weight=1)
        content_frame.rowconfigure(0, weight=1)

        callbacks = {
            "callback_spin": self.callback_spin,
            "callback_cycle": self.callback_cycle,
            "callback_oscillator": self.callback_oscillator,
            "callback_stop": self.callback_stop,
            "callback_zero": self.callback_zero,
        }
        self.entries, entry_widgets = create_widgets_disco_input(content_frame, callbacks)
        self.keyboard = NumericKeyboard(self, scroll_host=content_frame)
        self.keyboard.attach(entry_widgets)
        self.stop_event = None

        # Al cerrar la app: detener el motor y liberar el driver
        self.bind("<Destroy>", self._on_destroy)

    # ----------------- Helpers motor -----------------
    def _ensure_driver(self) -> bool:
        """Crea el driver compartido si no existe. Llamar con thread_lock tomado.
        False si el motor lo tiene otro dueño (p. ej. una corrida de PCR o el
        oscilador de CV/SWV crean su propio driver)."""
        global drv
        if drv is not None:
            return True
        from Drivers.DriverStepperSys import DriverStepperSys

        try:
            d = DriverStepperSys(
                en_pin=12, enable_active_high=False, uart_port=serial_port_encoder
            )
        except Exception as e:
            print(f"Motor not available (PCR/Electrochemical running?): {e}")
            return False
        d.enable_driver(True)
        drv = d
        return True

    def _lock_while_running(self, thread):
        """Bloquea PCR/Electrochemical mientras este hilo de motor vive (crean su
        propio driver y chocarían en GPIO 12) y desbloquea al terminar, sea por
        Stop o porque el go-to-zero acabó solo. Sondeo con after(): el hilo del
        motor no toca Tk."""
        self._motor_thread = thread
        if self.lock_tabs_callback is not None:
            self.lock_tabs_callback(True)
        if self._lock_job is None:
            self._poll_motor_thread()

    def _poll_motor_thread(self):
        if self._motor_thread is not None and self._motor_thread.is_alive():
            self._lock_job = self.after(200, self._poll_motor_thread)  # pyrefly: ignore
            return
        self._lock_job = None
        self._motor_thread = None
        if self.lock_tabs_callback is not None:
            self.lock_tabs_callback(False)

    def _on_destroy(self, event=None):
        """Al cerrar la app con el motor girando: lo detiene como Stop (rampa +
        go_zero) y el hilo libera el driver al terminar, así el proceso puede
        salir (antes quedaba colgado por el hilo lector no-daemon del driver y
        el Pico seguía girando)."""
        if event is not None and event.widget is not self:
            return
        if self._lock_job is not None:
            try:
                self.after_cancel(self._lock_job)
            except Exception:
                pass
            self._lock_job = None
        if self.stop_event is not None:
            self.stop_event.set()
        # Si hay un hilo vivo (de esta tab o de Quick Control) él libera al
        # terminar; si no, se libera un driver que hubiera quedado abierto.
        if not (thread_motor is not None and thread_motor.is_alive()):
            release_driver()

    # ----------------- Callbacks -----------------
    def callback_spin(self):
        global thread_motor
        from Drivers.DriverStepperSys import spinMotorRPM_ramped

        with thread_lock:
            if thread_motor and thread_motor.is_alive():
                print("A thread is already active; cannot start another.")
                return
            settings = read_settings_from_file()

            direction = self.entries[0].get()
            rpm_setpoint = float(self.entries[1].get())
            ts = settings.get("ts_spin", 0.1)
            if not self._ensure_driver():
                return
            self.stop_event = (
                threading.Event() if self.stop_event is None else self.stop_event
            )
            settings = read_settings_from_file()
            acceleration = settings.get("acceleration_spin", 200.0)
            th = threading.Thread(
                target=run_and_release,
                args=(
                    spinMotorRPM_ramped,
                    direction,
                    rpm_setpoint,
                    ts,
                    acceleration,
                    1000.0,
                    True,
                    drv,
                    None,
                    None,
                    self.stop_event,
                ),
            )
            thread_motor = th
            th.start()
            print(
                f"Motor {direction} at {rpm_setpoint} RPM started",
                f"with acceleration {acceleration} RPM/s",
            )
        self._lock_while_running(th)

    def callback_zero(self):
        print("Run go-to-zero function")
        global thread_motor

        rpm_zero = float(self.entries[8].get())
        with thread_lock:
            if thread_motor and thread_motor.is_alive():
                print("A thread is already active; cannot start another.")
                return
            if not self._ensure_driver():
                return
            self.stop_event = (
                threading.Event() if self.stop_event is None else self.stop_event
            )
            # Termina solo al llegar a cero: run_and_release suelta el driver
            # (antes quedaba abierto hasta pulsar Stop y bloqueaba a PCR/CV).
            th = threading.Thread(
                target=run_and_release,
                args=(spinMotorToZero, rpm_zero, None, self.stop_event),
            )
            thread_motor = th
            th.start()
            print(f"Motor at {rpm_zero} RPM started")
        self._lock_while_running(th)

    def callback_cycle(self):
        print("Run on/off cycle")

    def callback_oscillator(self):
        global thread_motor

        settings: dict = read_settings_from_file()
        max_rpm = settings.get("max_rpm", 700)
        print("Starting oscillator mode")
        angle = float(self.entries[6].get())
        speed_percentage = float(self.entries[7].get())
        print(f"Angle: {angle}°, Speed: {speed_percentage:2f}%")
        if angle > 45:
            print("Maximum angle is 45°")
            return
        with thread_lock:
            if thread_motor and thread_motor.is_alive():
                print("A thread is already active; cannot start another.")
                return
            # Aquí se iniciaría el modo oscilador con los parámetros dados
            if not self._ensure_driver():
                return
            self.stop_event = (
                threading.Event() if self.stop_event is None else self.stop_event
            )
            th = threading.Thread(
                target=run_and_release,
                args=(
                    spinMotorAngle,
                    angle,
                    speed_percentage * max_rpm / 100,
                    max_rpm,
                    None,
                    True,
                    self.stop_event,
                    drv
                ),
            )
            thread_motor = th
            th.start()
            print("Oscillator mode started")
        self._lock_while_running(th)

    def callback_stop(self):
        global thread_motor
        print("Stopping motor...")
        if self.stop_event is None:
            print("No stop event defined.")
            return
        self.stop_event.set()
        if thread_motor:
            thread_motor.join()
        # El hilo ya liberó el driver al terminar (run_and_release); esto cubre
        # un driver que hubiera quedado abierto sin hilo.
        release_driver()
        print("Thread stopped")
        self.stop_event = None
