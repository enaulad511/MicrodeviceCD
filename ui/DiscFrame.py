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


stop_event = threading.Event()


def create_widgets_disco_input(parent, callbacks: dict):
    entries = []
    parent.columnconfigure((0, 1), weight=1)
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
    svar_speed = ttk.StringVar(value="50")
    speed_entry = ttk.Entry(frame3, font=font_entry, textvariable=svar_speed, width=5)
    speed_entry.grid(row=1, column=1, padx=5, pady=5, sticky="w")
    entries.append(svar_speed)

    ttk.Button(
        frame3,
        text="Start Oscillation",
        style="info.TButton",
        command=callbacks.get("callback_oscillator", ()),
    ).grid(row=2, column=0, columnspan=2, pady=5, padx=5, sticky="nswe")

    # Mode 4: Stop
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


def spinMotorRPM(direction, rpm, ts):
    print("spin function call")


# def spinMotorRPM(direction, rpm, ts):
#     global sistemaMotor
#     settings: dict = read_settings_from_file()
#     pid_cfg: dict = settings.get("pidControllerRPM", {"kp": 0.1, "ki": 0.01, "kd": 0.005})
#     pid = PIDController(
#         kp=pid_cfg["kp"],
#         ki=pid_cfg["ki"],
#         kd=pid_cfg["kd"],
#         setpoint=rpm,
#         output_limits=(pid_cfg.get(min, 14), pid_cfg.get("max", 50)),
#         ts=ts,
#     )
#     current_time = time.perf_counter()
#     sistemaMotor.avanzar(10) # pyrefly: ignore
#     while not stop_event.is_set():
#         raw_data = sistemaMotor.leer_encoder(ts)  # pyrefly:ignore
#         # print(f"current passed time: {(time.perf_counter() - current_time):.2f}s, ts: {ts}")
#         rpm_actual = sistemaMotor.get_rpm() # pyrefly:ignore
#         estado =  sistemaMotor.get_estado()
#         # print(raw_data)
#         print(f"rpm: {round(rpm_actual, 2)}, counter: {estado['COUNTER']}")
#         control_signal = round(pid.compute(rpm_actual), 2)
#         # control_signal = 10
#         if direction == "CW":
#             print(f"Control signal CW: {control_signal}")
#             sistemaMotor.avanzar(control_signal) # pyrefly: ignore
#         elif direction == "CCW":
#             print(f"Control signal CCW: {control_signal}")
#             sistemaMotor.retroceder(control_signal) # pyrefly: ignore
#         else:
#             print("Dirección no válida")
#             break

#         while (time.perf_counter() - current_time) < ts:
#             pass
#         # print(f"current passed time: {(time.perf_counter() - current_time):.2f}s, ts: {ts}")
#         current_time = time.perf_counter()

#     sistemaMotor.detener() # pyrefly: ignore
#     print("Motor detenido correctamente")


def spinMotorRPM_ramped(
    direction: str,
    setpoint_rpm: float,
    ts: float,
    accel_rpm_s: float = 800.0,  # aceleración (RPM por segundo)
    max_rpm: float = 1000.0,  # límite absoluto
    soft_stop: bool = True,  # rampa suave a 0 cuando paran
    drv_motor=None,
    time_exp=None,
    stop_func=None,  # stop function for checking if stop is required, return boolean
):
    """
    Gira el motor con rampa de aceleración en RPM hasta 'setpoint_rpm' (limitado a 1000 RPM).
    direction: "CW" o "CCW"
    setpoint_rpm: objetivo en RPM (valor positivo; la dirección fija el signo)
    ts: periodo de actualización en segundos (ej. 0.02 a 0.05)
    accel_rpm_s: aceleración/deceleración en RPM/s
    """
    global drv, stop_event
    print(
        direction,
        setpoint_rpm,
        ts,
        accel_rpm_s,
        max_rpm,
        soft_stop,
        drv_motor,
        time_exp,
        stop_func,
        drv,
        stop_event,
    )
    if drv_motor is not None and drv is None:
        drv = drv_motor
    # Validación de dirección
    d = direction.strip().upper()
    if d not in ("CW", "CCW"):
        print("Dirección no válida. Usa 'CW' o 'CCW'.")
        return

    # Define el signo por dirección y limita objetivo
    sign = 1 if d == "CW" else -1
    target_abs = min(abs(setpoint_rpm), max_rpm)
    target = sign * target_abs

    # Punto de arranque (intenta leer del estado, si no asume 0)
    try:
        cur = float(drv.get_status().get("rpm", 0.0))  # pyrefly: ignore
    except Exception:
        cur = 0.0

    # Parametrización
    ts = float(ts)
    if ts <= 0:
        ts = 0.1  # fallback
    step = float(accel_rpm_s) * ts  # incremento/decremento por ciclo

    # Bucle principal: acelera hasta objetivo y mantén
    star_time = time.perf_counter()
    while not stop_event.is_set():
        # Aproximación por rampa
        diff = target - cur
        if abs(diff) <= step:
            cur = target
        else:
            cur += step if diff > 0 else -step

        # Enviar comando
        drv.run_rpm(cur)  # pyrefly: ignore
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
    print(
        "stop_event detectado, iniciando parada suave..."
        if soft_stop
        else "stop_event detectado, deteniendo motor..."
    )
    # Al salir por stop_event, opcionalmente desacelera suave a 0
    if soft_stop:
        while abs(cur) > 0.1:
            if abs(cur) <= step:
                cur = 0.0
            else:
                cur += -step if cur > 0 else step
            drv.run_rpm(cur)  # pyrefly: ignore
            time.sleep(ts)
    if drv is not None:
        drv.stop()  
        print("Parado:", drv.get_status())
        drv = None if drv_motor is not None else drv
    


def spinMotorAngle(angle, rpm, max_rpm, n_times=None, flag_continue=False):
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

    global stop_event, drv  # asumiendo que existen en tu entorno

    try:
        angle = float(angle)
        rpm = float(rpm)
        max_rpm = float(max_rpm)
    except Exception as e:
        raise ValueError(f"Parámetros inválidos: {e}")

    if angle <= 0:
        drv._cmd_stop()
        print("[spinMotorAngle] angle <= 0; STOP.")
        return

    rpm_eff = max(min(abs(rpm), abs(max_rpm)), 0.0)
    speed_hz = rpm_eff * (STEPS_PER_REV / 60.0)
    if speed_hz <= 0.0:
        drv._cmd_stop()
        print("[spinMotorAngle] Velocidad resultante = 0 Hz; STOP.")
        return

    ok = True
    ok &= bool(drv._cmd_mode(4))
    ok &= bool(drv._cmd_vel(f"{speed_hz:.3f}"))
    ok &= bool(drv._cmd_set(f"{float(angle):.3f}"))
    # if not ok:
    #     drv._cmd_stop()
    #     raise RuntimeError("No se recibió ACK en MODO/VEL/SET.")

    vel_deg_s = speed_hz * (360.0 / STEPS_PER_REV)
    if vel_deg_s <= 0:
        drv._cmd_stop()
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
        drv._cmd_stop()
        print("Motor detenido")


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

        callbacks = {
            "callback_spin": self.callback_spin,
            "callback_cycle": self.callback_cycle,
            "callback_oscillator": self.callback_oscillator,
            "callback_stop": self.callback_stop,
        }
        self.entries = create_widgets_disco_input(content_frame, callbacks)

    # def callback_spin(self):
    #     global thread_motor, sistemaMotor
    #     from Drivers.DriverEncoder import DriverEncoderSys
    #     with thread_lock:
    #         if thread_motor and thread_motor.is_alive():
    #             print("Ya hay un hilo activo, no se puede iniciar otro.")
    #             return
    #         direction = self.entries[0].get()
    #         rpm_setpoint = float(self.entries[1].get())
    #         ts = 0.01
    #         if sistemaMotor is None:
    #             sistemaMotor = DriverEncoderSys(en_l=12, en_r=13, uart_port=serial_port_encoder)
    #         stop_event.clear()
    #         thread_motor = threading.Thread(
    #             target=spinMotorRPM, args=(direction, rpm_setpoint, ts)
    #         )
    #         thread_motor.start()
    #         print(f"Motor {direction} a {rpm_setpoint} RPM iniciado")

    def callback_spin(self):
        global thread_motor, drv, stop_event
        from Drivers.DriverStepperSys import DriverStepperSys

        with thread_lock:
            if thread_motor and thread_motor.is_alive():
                print("Ya hay un hilo activo, no se puede iniciar otro.")
                return
            direction = self.entries[0].get()
            rpm_setpoint = float(self.entries[1].get())
            ts = 0.2
            if drv is None:
                drv = DriverStepperSys(
                    en_pin=12, enable_active_high=False, uart_port=serial_port_encoder
                )
                drv.enable_driver(True)
            stop_event.clear()
            thread_motor = threading.Thread(
                target=spinMotorRPM_ramped,
                args=(direction, rpm_setpoint, ts, 1000.0, 1000.0, True),
            )
            thread_motor.start()
            print(f"Motor {direction} a {rpm_setpoint} RPM iniciado")

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
            stop_event.clear()
            thread_motor = threading.Thread(
                target=spinMotorAngle,
                args=(angle, speed_percentage * max_rpm / 100, max_rpm, None, True),
            )
            thread_motor.start()
            print("Modo oscilador iniciado")

    def callback_stop(self):
        global thread_motor, drv, stop_event
        print("Deteniendo motor...")
        stop_event.set()
        if thread_motor:
            thread_motor.join()
        if drv is not None:
            drv.enable_driver(False)
            drv.close()
            drv = None
            print("released resources")
        print("Hilo detenido")
        stop_event.clear()
