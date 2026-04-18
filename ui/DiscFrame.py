# -*- coding: utf-8 -*-

from templates.utils import read_settings_from_file
from templates.constants import serial_port_encoder
import ttkbootstrap as ttk
from ttkbootstrap.scrolled import ScrolledFrame

from templates.constants import font_entry
import threading
import time

__author__ = "Edisson A. Naula"
__date__ = "$ 08/10/2025  at 11:11 a.m. $"


def create_widgets_disco_input(parent, callbacks: dict):
    entries = []
    parent.columnconfigure((0, 1), weight=1)
    parent.rowconfigure((0, 1), weight=1)
    # Mode 1: Continuous rotation CW or CCW with RPM
    frame1 = ttk.LabelFrame(parent, text="Continuous Rotation")
    frame1.grid(row=0, column=0, padx=10, pady=10, sticky="nswe")
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

    ttk.Button(
        frame1,
        text="Start Rotation",
        style="info.TButton",
        command=callbacks.get("callback_spin", ()),
    ).grid(row=2, column=0, columnspan=2, pady=5, padx=5, sticky="nswe")
    frame1.rowconfigure((0, 1, 2), weight=1)
    # Mode 2: On/Off cycle
    frame2 = ttk.LabelFrame(parent, text="On/Off Cycle")
    # frame2.grid(row=1, column=0, padx=10, pady=10, sticky="nswe")
    frame2.configure(style="Custom.TLabelframe")
    frame2.columnconfigure((0, 1), weight=1)

    ttk.Label(frame2, text="Number of cycles:", style="Custom.TLabel").grid(
        row=0, column=0, padx=5, pady=5, sticky="w"
    )
    svar_cycles = ttk.StringVar()
    cycles_entry = ttk.Entry(frame2, font=font_entry, textvariable=svar_cycles, width=5)
    cycles_entry.grid(row=0, column=1, padx=5, pady=5, sticky="s")
    entries.append(svar_cycles)

    ttk.Label(frame2, text="Acceleration time (ms):", style="Custom.TLabel").grid(
        row=1, column=0, padx=5, pady=5, sticky="w"
    )
    svar_accel = ttk.StringVar()
    accel_entry = ttk.Entry(frame2, font=font_entry, textvariable=svar_accel, width=5)
    accel_entry.grid(row=1, column=1, padx=5, pady=5, sticky="w")
    entries.append(svar_accel)

    ttk.Label(frame2, text="Target RPM:", style="Custom.TLabel").grid(
        row=2, column=0, padx=5, pady=5, sticky="w"
    )
    svar_target_rpm = ttk.StringVar()
    target_rpm_entry = ttk.Entry(
        frame2, font=font_entry, textvariable=svar_target_rpm, width=5
    )
    target_rpm_entry.grid(row=2, column=1, padx=5, pady=5, sticky="w")
    entries.append(svar_target_rpm)

    ttk.Label(frame2, text="Deceleration time (ms):", style="Custom.TLabel").grid(
        row=3, column=0, padx=5, pady=5, sticky="w"
    )
    svar_decel = ttk.StringVar()
    decel_entry = ttk.Entry(frame2, font=font_entry, textvariable=svar_decel, width=5)
    decel_entry.grid(row=3, column=1, padx=5, pady=5, sticky="w")
    entries.append(svar_decel)

    ttk.Button(
        frame2,
        text="Run Cycle",
        style="info.TButton",
        command=callbacks.get("callback_cycle", ()),
    ).grid(row=4, column=0, columnspan=2, pady=5, padx=5, sticky="nswe")

    # Mode 3: Oscillator
    frame3 = ttk.LabelFrame(parent, text="Oscillator Mode")
    frame3.grid(row=0, column=1, padx=10, pady=10, sticky="nswe")
    frame3.configure(style="Custom.TLabelframe")
    frame3.columnconfigure((0, 1), weight=1)

    ttk.Label(frame3, text="Angle (°, max 30):", style="Custom.TLabel").grid(
        row=0, column=0, padx=5, pady=5, sticky="w"
    )
    svar_angle = ttk.StringVar(value="30")
    angle_entry = ttk.Entry(frame3, font=font_entry, textvariable=svar_angle, width=5)
    angle_entry.grid(row=0, column=1, padx=5, pady=5, sticky="w")
    entries.append(svar_angle)

    ttk.Label(frame3, text="Speed (%):", style="Custom.TLabel").grid(
        row=1, column=0, padx=5, pady=5, sticky="w"
    )
    svar_speed = ttk.StringVar(value="10")
    speed_entry = ttk.Entry(frame3, font=font_entry, textvariable=svar_speed, width=5)
    speed_entry.grid(row=1, column=1, padx=5, pady=5, sticky="w")
    entries.append(svar_speed)

    ttk.Button(
        frame3,
        text="Start Oscillation",
        style="info.TButton",
        command=callbacks.get("callback_oscillator", ()),
    ).grid(row=2, column=0, columnspan=2, pady=5, padx=5, sticky="nswe")

    # mode 4: go to zero require rpm
    frame4 = ttk.LabelFrame(parent, text="Go to Zero")
    frame4.grid(row=1, column=0, padx=10, pady=10, sticky="nswe")
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
    ttk.Button(
        frame4,
        text="Go to Zero",
        style="info.TButton",
        command=callbacks.get("callback_zero", ()),
    ).grid(row=1, column=0, columnspan=2, pady=5, padx=5, sticky="nswe")
    # Mode 5: Stop
    ttk.Button(
        parent,
        text="Stop",
        style="danger.TButton",
        command=callbacks.get("callback_stop", ()),
    ).grid(row=1, column=1, pady=10, padx=5, sticky="nswe")

    return entries


# Variables globales
drv = None
thread_motor = None
thread_lock = threading.Lock()


def spinMotorRPM_ramped(
    direction: str,
    setpoint_rpm: float,
    ts: float,
    accel_rpm_s: float = 200.0,  # aceleración (RPM por segundo)
    max_rpm: float = 1000.0,  # límite absoluto
    soft_stop: bool = True,  # rampa suave a 0 cuando paran
    drv_motor=None,
    time_exp=None,
    stop_func=None,  # stop function for checking if stop is required, return boolean
    stop_event=None,
):
    """
    Gira el motor con rampa de aceleración en RPM hasta 'setpoint_rpm' (limitado a 1000 RPM).
    direction: "CW" o "CCW"
    setpoint_rpm: objetivo en RPM (valor positivo; la dirección fija el signo)
    ts: periodo de actualización en segundos (ej. 0.02 a 0.05)
    accel_rpm_s: aceleración/deceleración en RPM/s
    """
    if drv_motor is not None:
        drv = drv_motor
    else:
        print("Error drv not initialized")
        return False
    if stop_event is None:
        print("Error: stop_event no proporcionado, se requiere para control de parada.")
        return False

    # Validación de dirección
    d = direction.strip().upper()
    if d not in ("CW", "CCW"):
        print("Dirección no válida. Usa 'CW' o 'CCW'.")
        return

    # Define el signo por dirección y limita objetivo
    sign = 1 if d == "CW" else -1
    target_abs = min(abs(setpoint_rpm), max_rpm)
    target = sign * target_abs
    if drv is None:
        print("Error: drv no está inicializado.")
        return
    drv.set_init_vals(pos_deg=0.0, rpm=0.0)
    # Punto de arranque (intenta leer del estado, si no asume 0)
    try:
        cur = float(drv.get_status().get("rpm", 0.0))
    except Exception:
        cur = 0.0

    # Parametrización
    ts = float(ts)
    if ts <= 0:
        ts = 0.1  # fallback
    step = float(accel_rpm_s) / 1  # incremento/decremento por ciclo
    # Bucle principal: acelera hasta objetivo y mantén
    star_time = time.perf_counter()
    while not stop_event.is_set():
        # Aproximación por rampa
        diff = target - cur
        if abs(diff) <= step:
            cur = target
        else:
            cur += step if diff > 0 else -step
        # Enviar comando solo si aun no estamos en target
        if diff != 0:
            drv.run_rpm(cur)
        # Si ya estamos en target, mantiene velocidad y sigue escuchando stop_event
        if time_exp is not None:
            elapsed = time.perf_counter() - star_time
            if elapsed >= time_exp:
                print(f"Tiempo de ejecución {time_exp}s alcanzado, deteniendo motor.")
                break
        if stop_func is not None:
            if stop_func():
                print("stop_func indicó que se debe detener, iniciando parada...")
                break
        time.sleep(ts)
    # Al salir por stop_event, opcionalmente desacelera suave a 0
    if soft_stop:
        while abs(cur) > 0.1:
            diff = 0 - cur
            if abs(cur) <= step:
                cur = 0.0
            else:
                cur += -step if cur > 0 else step
            drv.run_rpm(cur)
            status = drv.get_status()
            while abs(status.get("rpm")) >= cur * 1.1:
                status = drv.get_status()
                if int(status.get("rpm")) < 100:
                    break
                time.sleep(ts)

    # # detec position and go to 0°
    # got to zero position
    drv.go_zero(50)
    status = drv.get_status()
    rpm_status = [1, 1, abs(status.get("rpm", 1))]
    while sum(abs(x) for x in rpm_status) > 0:
        time.sleep(0.5)
        # rotate rpm status
        rpm_status = rpm_status[1:] + [abs(drv.get_status().get("rpm", 1))]
    if drv is not None:
        drv.stop()
        status = drv.get_status()
        print(
            f"Parado--> pos: {status.get('pos_deg'):.2f}°, rpm: {status.get('rpm'):.2f}"
        )
        drv = None if drv_motor is not None else drv


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
        print("[spinMotorAngle] drv no está inicializado.")
        return
    if stop_event is None:
        print(
            "[spinMotorAngle] stop_event no proporcionado, se requiere para control de parada."
        )
        return
    try:
        angle = float(angle)
        rpm = float(rpm)
        max_rpm = float(max_rpm)
    except Exception as e:
        raise ValueError(f"Parámetros inválidos: {e}")

    if angle <= 0:
        drv.stop()
        print("[spinMotorAngle] angle <= 0; STOP.")
        return

    rpm_eff = max(min(abs(rpm), abs(max_rpm)), 0.0)
    speed_hz = rpm_eff * (STEPS_PER_REV / 60.0)
    if speed_hz <= 0.0:
        drv.stop()
        print("[spinMotorAngle] Velocidad resultante = 0 Hz; STOP.")
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
                    f"[spinMotorAngle] SWEEP {n_times} ciclos: ±{angle}°, "
                    f"Hz={speed_hz:.1f}, T_ciclo≈{T_cycle:.3f}s, T_total≈{total_time:.3f}s"
                )
                elapsed = 0.0
                step = 0.01
                while elapsed < total_time:
                    if stop_event.is_set():
                        print("[spinMotorAngle] stop_event detectado; abortando.")
                        break
                    _t.sleep(step)
                    elapsed += step
        else:
            if flag_continue:
                print(
                    f"[spinMotorAngle] SWEEP continuo: ±{angle}° @ {rpm_eff} rpm (Hz={speed_hz:.1f})"
                )
                while not stop_event.is_set():
                    _t.sleep(0.02)
            else:
                print(f"[spinMotorAngle] SWEEP 1 ciclo: ±{angle}°, T≈{T_cycle:.3f}s")
                _t.sleep(T_cycle)
    finally:
        drv.stop()
        print("Motor detenido")


def spinMotorToZero(rpm, drv_motor=None, stop_event=None):
    global drv
    if drv_motor is not None and drv is None:
        drv = drv_motor
    if stop_event is None:
        print("[spinMotorToZero] stop_event no proporcionado.")
        return
    if drv is None:
        print("[spinMotorToZero] drv no está inicializado.")
        return
    print(f"Spin to zero a {rpm} RPM...")
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
            f"Parado--> pos: {status.get('pos_deg'):.2f}°, rpm: {status.get('rpm'):.2f}"
        )
        drv = None if drv_motor is not None else drv


class ControlDiscFrame(ttk.Frame):
    """UI class for manual disc control.

    :param parent: parent frame to be placed
    :type parent: ttk.Frame
    """

    def __init__(self, parent):
        ttk.Frame.__init__(self, parent)
        self.parent = parent
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
        self.entries = create_widgets_disco_input(content_frame, callbacks)
        self.stop_event = None

    def callback_spin(self):
        global thread_motor, drv
        from Drivers.DriverStepperSys import DriverStepperSys

        with thread_lock:
            if thread_motor and thread_motor.is_alive():
                print("Ya hay un hilo activo, no se puede iniciar otro.")
                return
            settings = read_settings_from_file()

            direction = self.entries[0].get()
            rpm_setpoint = float(self.entries[1].get())
            ts = settings.get("ts_spin", 0.1)
            if drv is None:
                drv = DriverStepperSys(
                    en_pin=12, enable_active_high=False, uart_port=serial_port_encoder
                )
                drv.enable_driver(True)
            self.stop_event = (
                threading.Event() if self.stop_event is None else self.stop_event
            )
            settings = read_settings_from_file()
            acceleration = settings.get("acceleration_spin", 200.0)
            thread_motor = threading.Thread(
                target=spinMotorRPM_ramped,
                args=(
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
            thread_motor.start()
            print(
                f"Motor {direction} a {rpm_setpoint} RPM iniciado",
                f"con aceleración {acceleration} RPM/s",
            )

    def callback_zero(self):
        print("Ejecutar función de ir a cero")
        global thread_motor, drv
        from Drivers.DriverStepperSys import DriverStepperSys

        rpm_zero = float(self.entries[8].get())
        with thread_lock:
            if thread_motor and thread_motor.is_alive():
                print("Ya hay un hilo activo, no se puede iniciar otro.")
                return
            if drv is None:
                drv = DriverStepperSys(
                    en_pin=12, enable_active_high=False, uart_port=serial_port_encoder
                )
                drv.enable_driver(True)
            self.stop_event = (
                threading.Event() if self.stop_event is None else self.stop_event
            )
            thread_motor = threading.Thread(
                target=spinMotorToZero,
                args=(rpm_zero, None, self.stop_event),
            )
            thread_motor.start()
            print(f"Motor a {rpm_zero} RPM iniciado")

    def callback_cycle(self):
        print("Ejecutar ciclo de encendido/apagado")

    def callback_oscillator(self):
        global thread_motor, drv
        from Drivers.DriverStepperSys import DriverStepperSys

        settings: dict = read_settings_from_file()
        max_rpm = settings.get("max_rpm", 700)
        print("Iniciar modo oscilador")
        angle = float(self.entries[6].get())
        speed_percentage = float(self.entries[7].get())
        print(f"Ángulo: {angle}°, Velocidad: {speed_percentage:2f}%")
        if angle > 45:
            print("El ángulo máximo es 45°")
            return
        with thread_lock:
            if thread_motor and thread_motor.is_alive():
                print("Ya hay un hilo activo, no se puede iniciar otro.")
                return
            # Aquí se iniciaría el modo oscilador con los parámetros dados
            if drv is None:
                drv = DriverStepperSys(
                    en_pin=12, enable_active_high=False, uart_port=serial_port_encoder
                )
                drv.enable_driver(True)
            self.stop_event = (
                threading.Event() if self.stop_event is None else self.stop_event
            )
            thread_motor = threading.Thread(
                target=spinMotorAngle,
                args=(
                    angle,
                    speed_percentage * max_rpm / 100,
                    max_rpm,
                    None,
                    True,
                    self.stop_event,
                    drv
                ),
            )
            thread_motor.start()
            print("Modo oscilador iniciado")

    def callback_stop(self):
        global thread_motor, drv
        print("Deteniendo motor...")
        if self.stop_event is None:
            print("No hay evento de parada definido.")
            return
        self.stop_event.set()
        if thread_motor:
            thread_motor.join()
        if drv is not None:
            drv.enable_driver(False)
            drv.close()
            drv = None
            print("released resources")
        print("Hilo detenido")
        self.stop_event = None
