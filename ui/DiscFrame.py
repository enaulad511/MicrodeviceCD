# -*- coding: utf-8 -*-
__author__ = "Edisson A. Naula"
__date__ = "$ 08/10/2025  at 11:11 a.m. $"

import ttkbootstrap as ttk
from ttkbootstrap.scrolled import ScrolledFrame

from templates.constants import font_entry


def create_widgets_disco_input(parent, callbacks: dict):
    entries = []

    # Mode 1: Continuous rotation CW or CCW with RPM
    frame1 = ttk.LabelFrame(parent, text="Continuous Rotation")
    frame1.grid(row=0, column=0, padx=10, pady=10, sticky="nswe")
    frame1.configure(style="Custom.TLabelframe")

    ttk.Label(frame1, text="Direction:", style="Custom.TLabel").grid(
        row=0, column=0, padx=5, pady=5, sticky="w"
    )
    svar_dir = ttk.StringVar()
    dir_combo = ttk.Combobox(
        frame1, values=["CW", "CCW"], textvariable=svar_dir, font=font_entry
    )
    dir_combo.grid(row=0, column=1, padx=5, pady=5)
    dir_combo.current(0)
    entries.append(svar_dir)

    ttk.Label(frame1, text="RPM:", style="Custom.TLabel").grid(
        row=1, column=0, padx=5, pady=5, sticky="w"
    )
    rpm_entry = ttk.Entry(frame1, font=font_entry)
    rpm_entry.grid(row=1, column=1, padx=5, pady=5)
    entries.append(rpm_entry)

    ttk.Button(
        frame1,
        text="Start Rotation",
        style="info.TButton",
        command=callbacks.get("callback_spin"),
    ).grid(row=2, column=0, columnspan=2, pady=5, padx=5, sticky="w")

    # Mode 2: On/Off cycle
    frame2 = ttk.LabelFrame(parent, text="On/Off Cycle")
    frame2.grid(row=1, column=0, padx=10, pady=10, sticky="nswe")
    frame2.configure(style="Custom.TLabelframe")

    ttk.Label(frame2, text="Number of cycles:", style="Custom.TLabel").grid(
        row=0, column=0, padx=5, pady=5, sticky="w"
    )
    cycles_entry = ttk.Entry(frame2, font=font_entry)
    cycles_entry.grid(row=0, column=1, padx=5, pady=5)
    entries.append(cycles_entry)

    ttk.Label(frame2, text="Acceleration time (ms):", style="Custom.TLabel").grid(
        row=1, column=0, padx=5, pady=5, sticky="w"
    )
    accel_entry = ttk.Entry(frame2, font=font_entry)
    accel_entry.grid(row=1, column=1, padx=5, pady=5)
    entries.append(accel_entry)

    ttk.Label(frame2, text="Target RPM:", style="Custom.TLabel").grid(
        row=2, column=0, padx=5, pady=5, sticky="w"
    )
    target_rpm_entry = ttk.Entry(frame2, font=font_entry)
    target_rpm_entry.grid(row=2, column=1, padx=5, pady=5)
    entries.append(target_rpm_entry)

    ttk.Label(frame2, text="Deceleration time (ms):", style="Custom.TLabel").grid(
        row=3, column=0, padx=5, pady=5, sticky="w"
    )
    decel_entry = ttk.Entry(frame2, font=font_entry)
    decel_entry.grid(row=3, column=1, padx=5, pady=5)
    entries.append(decel_entry)

    ttk.Button(
        frame2,
        text="Run Cycle",
        style="info.TButton",
        command=callbacks.get("callback_cycle"),
    ).grid(row=4, column=0, columnspan=2, pady=5, padx=5, sticky="w")

    # Mode 3: Oscillator
    frame3 = ttk.LabelFrame(parent, text="Oscillator Mode")
    frame3.grid(row=2, column=0, padx=10, pady=10, sticky="nswe")
    frame3.configure(style="Custom.TLabelframe")

    ttk.Label(frame3, text="Angle (°, max 45):", style="Custom.TLabel").grid(
        row=0, column=0, padx=5, pady=5, sticky="w"
    )
    angle_entry = ttk.Entry(frame3, font=font_entry)
    angle_entry.grid(row=0, column=1, padx=5, pady=5)
    entries.append(angle_entry)

    ttk.Label(frame3, text="Speed (°/s):", style="Custom.TLabel").grid(
        row=1, column=0, padx=5, pady=5, sticky="w"
    )
    speed_entry = ttk.Entry(frame3, font=font_entry)
    speed_entry.grid(row=1, column=1, padx=5, pady=5)
    entries.append(speed_entry)

    ttk.Button(
        frame3,
        text="Start Oscillation",
        style="info.TButton",
        command=callbacks.get("callback_oscillator"),
    ).grid(row=2, column=0, columnspan=2, pady=5, padx=5, sticky="w")

    return entries


class ControlDiscFrame(ttk.Frame):
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
        }
        self.entries = create_widgets_disco_input(content_frame, callbacks)

    def callback_spin(self):
        print("Iniciar giro CW/CCW con RPM")

    def callback_cycle(self):
        print("Ejecutar ciclo de encendido/apagado")

    def callback_oscillator(self):
        print("Iniciar modo oscilador")


