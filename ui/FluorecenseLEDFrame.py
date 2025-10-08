# -*- coding: utf-8 -*-
__author__ = "Edisson A. Naula"
__date__ = "$ 08/10/2025  at 10:50 a.m. $"

import ttkbootstrap as ttk

from templates.constants import font_entry


def create_widgets_fluorescente_input(parent, callbacks: dict):
    entries = []

    # Control 1: Encender y apagar
    frame1 = ttk.LabelFrame(parent, text="Control Básico")
    frame1.grid(row=0, column=0, padx=10, pady=10, sticky="nswe")
    frame1.configure(style="Custom.TLabelframe")

    ttk.Button(frame1, text="Encender", style="info.TButton", command=callbacks.get("callback_on")).grid(row=0, column=0, padx=5, pady=5)
    ttk.Button(frame1, text="Apagar", style="info.TButton", command=callbacks.get("callback_off")).grid(row=0, column=1, padx=5, pady=5)

    # Control 2: Encender por tiempo
    frame2 = ttk.LabelFrame(parent, text="Encendido Temporizado")
    frame2.grid(row=1, column=0, padx=10, pady=10, sticky="nswe")
    frame2.configure(style="Custom.TLabelframe")

    ttk.Label(frame2, text="Duración (ms):", style="Custom.TLabel").grid(row=0, column=0, padx=5, pady=5, sticky="e")
    duration_entry = ttk.Entry(frame2, font=font_entry)
    duration_entry.grid(row=0, column=1, padx=5, pady=5)
    entries.append(duration_entry)

    ttk.Button(frame2, style="info.TButton", text="Encender por tiempo", command=callbacks.get("callback_on_time")).grid(row=1, column=0, columnspan=2, pady=5)

    return entries


class ControlFluorescenteFrame(ttk.Frame):
    def __init__(self, parent):
        ttk.Frame.__init__(self, parent)
        self.parent = parent
        self.columnconfigure(0, weight=1)

        callbacks = {
            "callback_on": self.callback_on,
            "callback_off": self.callback_off,
            "callback_on_time": self.callback_on_time,
        }
        self.entries = create_widgets_fluorescente_input(self, callbacks)

    def callback_on(self):
        print("Encender LED Fluorescente")

    def callback_off(self):
        print("Apagar LED Fluorescente")

    def callback_on_time(self):
        print("Encender LED Fluorescente por tiempo")