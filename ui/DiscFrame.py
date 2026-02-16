# -*- coding: utf-8 -*-

from templates.utils import read_settings_from_file
from templates.constants import serial_port_encoder
import ttkbootstrap as ttk
from ttkbootstrap.scrolled import ScrolledFrame

from templates.constants import font_entry
from Drivers.PIDController import PIDController
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
    frame2.grid(row=1, column=0, padx=10, pady=10, sticky="nswe")
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
    target_rpm_entry = ttk.Entry(frame2, font=font_entry, textvariable=svar_target_rpm, width=5)
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

    ttk.Label(frame3, text="Angle (°, max 45):", style="Custom.TLabel").grid(
        row=0, column=0, padx=5, pady=5, sticky="w"
    )
    svar_angle = ttk.StringVar()
    angle_entry = ttk.Entry(frame3, font=font_entry, textvariable=svar_angle, width=5)
    angle_entry.grid(row=0, column=1, padx=5, pady=5, sticky="w")
    entries.append(svar_angle)

    ttk.Label(frame3, text="Speed (°/s):", style="Custom.TLabel").grid(
        row=1, column=0, padx=5, pady=5, sticky="w"
    )
    svar_speed = ttk.StringVar()
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
sistemaMotor = None
thread_motor = None
thread_lock = threading.Lock()


def spinMotorRPM(direction, rpm, ts):
    global sistemaMotor
    settings: dict = read_settings_from_file()
    pid_cfg: dict = settings.get("pidControllerRPM", {"kp": 0.1, "ki": 0.01, "kd": 0.005}) 
    pid = PIDController(
        kp=pid_cfg["kp"],
        ki=pid_cfg["ki"],
        kd=pid_cfg["kd"],
        setpoint=rpm,
        output_limits=(pid_cfg.get(min, 10), pid_cfg.get("max", 50)),
        ts=ts,
    )
    current_time = time.perf_counter()
    sistemaMotor.avanzar(10) # pyrefly: ignore
    while not stop_event.is_set():
        raw_data = sistemaMotor.leer_encoder(ts)  # pyrefly:ignore
        print(f"current passed time: {(time.perf_counter() - current_time):.2f}s, ts: {ts}")
        rpm_actual = sistemaMotor.get_rpm() # pyrefly:ignore
        estado =  sistemaMotor.get_estado()
        # print(raw_data)
        print(f"rpm: {round(rpm_actual, 2)}, counter: {estado['COUNTER']}")
        control_signal = round(pid.compute(rpm_actual), 2)
        # control_signal = 10
        if direction == "CW":
            print(f"Control signal CW: {control_signal}")
            sistemaMotor.avanzar(control_signal) # pyrefly: ignore
        elif direction == "CCW":
            print(f"Control signal CCW: {control_signal}")
            sistemaMotor.retroceder(control_signal) # pyrefly: ignore
        else:
            print("Dirección no válida")
            break

        while (time.perf_counter() - current_time) < ts:
            pass
        print(f"current passed time: {(time.perf_counter() - current_time):.2f}s, ts: {ts}")
        current_time = time.perf_counter()

    sistemaMotor.detener() # pyrefly: ignore
    print("Motor detenido correctamente")


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

    def callback_spin(self):
        global thread_motor, sistemaMotor
        from Drivers.DriverEncoder import DriverEncoderSys
        with thread_lock:
            if thread_motor and thread_motor.is_alive():
                print("Ya hay un hilo activo, no se puede iniciar otro.")
                return
            direction = self.entries[0].get()
            rpm_setpoint = float(self.entries[1].get())
            ts = 0.005
            if sistemaMotor is None:
                sistemaMotor = DriverEncoderSys(en_l=12, en_r=13, uart_port=serial_port_encoder)
            stop_event.clear()
            thread_motor = threading.Thread(
                target=spinMotorRPM, args=(direction, rpm_setpoint, ts)
            )
            thread_motor.start()
            print(f"Motor {direction} a {rpm_setpoint} RPM iniciado")

    def callback_cycle(self):
        print("Ejecutar ciclo de encendido/apagado")

    def callback_oscillator(self):
        print("Iniciar modo oscilador")

    def callback_stop(self):
        global thread_motor
        print("Deteniendo motor...")
        stop_event.set()
        if thread_motor:
            thread_motor.join()
        print("Hilo detenido")
