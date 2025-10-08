# -*- coding: utf-8 -*-
__author__ = "Edisson A. Naula"
__date__ = "$ 08/10/2025  at 01:07 p.m. $"


import ttkbootstrap as ttk
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import random  # Simulación de datos
import time

from templates.constants import font_entry


class PhotoreceptorFrame(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.start_time = 0
        self.parent = parent
        self.columnconfigure(0, weight=1)
        self.rowconfigure((0, 1), weight=1)

        # Variables
        self.running = False
        self.data = []
        self.timestamps = []

        # Controles
        control_frame = ttk.LabelFrame(self, text="Control de Fotoreceptor")
        control_frame.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        control_frame.configure(style="Custom.TLabelframe")

        ttk.Label(control_frame, text="Intervalo (ms):", style="Custom.TLabel").grid(row=0, column=0, padx=5, pady=5, sticky="e")
        self.interval_entry = ttk.Entry(control_frame, width=10, font=font_entry)
        self.interval_entry.insert(0, "500")
        self.interval_entry.grid(row=0, column=1, padx=5, pady=5)

        ttk.Button(control_frame, text="Iniciar", command=self.iniciar_lectura, style="info.TButton").grid(row=1, column=0, padx=5, pady=5)
        ttk.Button(control_frame, text="Detener", command=self.detener_lectura, style="danger.TButton").grid(row=1, column=1, padx=5, pady=5)

        # Gráfico
        self.fig, self.ax = plt.subplots(figsize=(5, 3))
        self.ax.set_title("Lectura del Fotoreceptor")
        self.ax.set_xlabel("Tiempo (s)")
        self.ax.set_ylabel("Intensidad")

        self.canvas = FigureCanvasTkAgg(self.fig, master=self)
        self.canvas.get_tk_widget().grid(row=1, column=0, padx=10, pady=10, sticky="nsew")

    def iniciar_lectura(self):
        print("Iniciar lectura del fotoreceptor")
        if self.running:
            print("Ya se está leyendo")
            return
        try:
            intervalo = int(self.interval_entry.get())
            self.running = True
            self.start_time = time.time()
            self.data.clear()
            self.timestamps.clear()
            self.after(intervalo, self.adquirir_dato)
        except ValueError:
            self.interval_entry.configure(background="salmon")

    def detener_lectura(self):
        print("Detener lectura del fotoreceptor")
        self.running = False

    def adquirir_dato(self):
        if not self.running:
            return

        intensidad = random.uniform(0, 100)
        timestamp = time.time()

        self.data.append(intensidad)
        self.timestamps.append(timestamp - self.start_time)

        self.actualizar_grafico()
        print(f"Intensidad: {intensidad:.2f}, Timestamp: {timestamp:.2f}")

        try:
            intervalo = int(self.interval_entry.get())
            self.after(intervalo, self.adquirir_dato)
        except ValueError:
            self.detener_lectura()
            self.interval_entry.configure(background="salmon")

    def actualizar_grafico(self):
        self.ax.clear()
        self.ax.plot(self.timestamps, self.data, color="blue")
        self.ax.set_title("Lectura del Fotoreceptor")
        self.ax.set_xlabel("Tiempo (s)")
        self.ax.set_ylabel("Intensidad")
        self.canvas.draw()
        print("Gráfico actualizado")


