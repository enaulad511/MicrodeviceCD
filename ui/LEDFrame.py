# -*- coding: utf-8 -*-
__author__ = "Edisson A. Naula"
__date__ = "$ 08/10/2025  at 09:32 a.m. $"

import ttkbootstrap as ttk
from ttkbootstrap.scrolled import ScrolledFrame

from templates.constants import font_entry


def create_widgets_input(parent, callbacks: dict):
    entries = []
    # Control 1: Encender y apagar
    frame1 = ttk.LabelFrame(parent, text="Basic Control")
    frame1.grid(row=0, column=0, padx=10, pady=10, sticky="nswe")
    frame1.configure(style="Custom.TLabelframe")

    ttk.Button(
        frame1, text="On", style="info.TButton", command=callbacks.get("callback_on")
    ).grid(row=0, column=0, padx=5, pady=5)
    ttk.Button(
        frame1, text="Off", style="info.TButton", command=callbacks.get("callback_off")
    ).grid(row=0, column=1, padx=5, pady=5)

    # Control 2: Encender por tiempo
    frame2 = ttk.LabelFrame(parent, text="Timed On")
    frame2.grid(row=1, column=0, padx=10, pady=10, sticky="nswe")
    frame2.configure(style="Custom.TLabelframe")

    ttk.Label(frame2, text="Duration (ms):", style="Custom.TLabel").grid(
        row=0, column=0, padx=5, pady=5, sticky="e"
    )
    duration_entry = ttk.Entry(frame2, font=font_entry)
    duration_entry.grid(row=0, column=1, padx=5, pady=5)
    entries.append(duration_entry)

    ttk.Button(
        frame2,
        style="info.TButton",
        text="Turn On by Time",
        command=callbacks.get("callback_on_time"),
    ).grid(row=1, column=0, columnspan=2, pady=5, padx=5, sticky="w")

    # Control 3: Patrón de encendido
    frame3 = ttk.LabelFrame(parent, text="On pattern")
    frame3.grid(row=2, column=0, padx=10, pady=10, sticky="nswe")
    frame3.configure(style="Custom.TLabelframe")

    ttk.Label(frame3, text="Patter type:", style="Custom.TLabel").grid(
        row=0, column=0, padx=5, pady=5, sticky="w"
    )
    svar_pattern = ttk.StringVar()
    pattern_combo = ttk.Combobox(
        frame3,
        values=["Square wave", "Staggered", "Ramp"],
        font=font_entry,
        textvariable=svar_pattern,
    )
    pattern_combo.grid(row=0, column=1, padx=5, pady=5)
    pattern_combo.current(0)
    entries.append(svar_pattern)

    ttk.Label(frame3, text="Cycle duration (ms):", style="Custom.TLabel").grid(
        row=1, column=0, padx=5, pady=5, sticky="w"
    )
    up_duration = ttk.Entry(frame3, font=font_entry)
    up_duration.grid(row=1, column=1, padx=5, pady=5, sticky="w")
    entries.append(up_duration)

    ttk.Label(frame3, text="Frequency (Hz):", style="Custom.TLabel").grid(
        row=2, column=0, padx=5, pady=5, sticky="w"
    )
    frequency_entry = ttk.Entry(frame3, font=font_entry)
    frequency_entry.grid(row=2, column=1, padx=5, pady=5)
    entries.append(frequency_entry)

    ttk.Button(
        frame3,
        text="Play Pattern",
        style="info.TButton",
        command=callbacks.get("callback_pattern"),
    ).grid(row=3, column=0, columnspan=2, pady=5, padx=5, sticky="w")
    return entries


class ControleLEDFrame(ttk.Frame):
    def __init__(self, parent):
        ttk.Frame.__init__(self, parent)
        self.parent = parent
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        content_frame = ScrolledFrame(self, autohide=True)
        content_frame.grid(row=0, column=0, sticky="nsew")
        content_frame.columnconfigure(0, weight=1)
        # self.rowconfigure((0, 1, 2), weight=1)
        callbacks = {
            "callback_on": self.callback_on,
            "callback_off": self.callback_off,
            "callback_on_time": self.callback_on_time,
            "callback_pattern": self.callback_pattern,
        }
        self.entries = create_widgets_input(content_frame, callbacks)

    def callback_on(self):
        print("Encender LED")

    def callback_off(self):
        print("Apagar LED")

    def callback_on_time(self):
        print("Encender LED por tiempo")

    def callback_pattern(self):
        print("Ejecutar patrón de encendido")


