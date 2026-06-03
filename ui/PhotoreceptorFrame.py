# -*- coding: utf-8 -*-


import time

import matplotlib.pyplot as plt
import ttkbootstrap as ttk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from ttkbootstrap.scrolled import ScrolledFrame

from templates.constants import font_entry
from templates.utils import read_settings_from_file
from ui.KeyboardFrame import NumericKeyboard

__author__ = "Edisson A. Naula"
__date__ = "$ 08/10/2025  at 01:07 p.m. $"


class PhotoreceptorFrame(ttk.Frame):
    def __init__(self, parent, ads_reader):
        super().__init__(parent)
        self.start_time = 0.0
        self.parent = parent
        self.ads = ads_reader
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        content_frame = ScrolledFrame(self, autohide=True)
        content_frame.grid(row=0, column=0, sticky="nsew")
        content_frame.columnconfigure(0, weight=1)
        content_frame.rowconfigure(1, weight=1)
        # Variables
        self.running = False
        self.data = []
        self.timestamps = []

        # Controles
        control_frame = ttk.LabelFrame(content_frame, text="Photoreceptor control")
        control_frame.grid(row=0, column=0, padx=5, pady=10, sticky="nswe")
        control_frame.configure(style="Custom.TLabelframe")
        control_frame.rowconfigure((0, 1), weight=1)
        control_frame.columnconfigure((0, 1, 2), weight=1)

        ttk.Label(control_frame, text="Sample time (ms):", style="Custom.TLabel").grid(
            row=0, column=0, padx=5, pady=5, sticky="w"
        )
        self.interval_entry = ttk.Entry(control_frame, width=10, font=font_entry)
        self.interval_entry.insert(0, "500")
        self.interval_entry.grid(row=0, column=1, padx=5, pady=5, sticky="we")

        ttk.Button(
            control_frame,
            text="Start",
            command=self.iniciar_lectura,
            style="info.TButton",
        ).grid(row=1, column=0, padx=5, pady=5, sticky="nswe")
        ttk.Button(
            control_frame,
            text="Stop",
            command=self.detener_lectura,
            style="danger.TButton",
        ).grid(row=1, column=1, padx=5, pady=5, sticky="nswe")
        ttk.Button(
            control_frame,
            text="Save",
            command=self.save_data,
            style="success.TButton",
        ).grid(row=1, column=2, padx=5, pady=5, sticky="nswe")

        # Gráfico
        graphic_frame = ttk.Frame(content_frame)
        graphic_frame.grid(row=1, column=0, sticky="nsew")

        # Muy importante:
        graphic_frame.columnconfigure(0, weight=1)
        graphic_frame.rowconfigure(0, weight=1)

        self.fig, self.ax = plt.subplots()
        self.ax.set_title("Measurement")
        self.ax.set_xlabel("Time (s)")
        self.ax.set_ylabel("Voltage (V)")

        self.canvas = FigureCanvasTkAgg(self.fig, master=graphic_frame)
        canvas_widget = self.canvas.get_tk_widget()

        canvas_widget.grid(row=0, column=0, padx=(2, 20), pady=10, sticky="nsew")
        canvas_widget.columnconfigure(0, weight=1)
        canvas_widget.rowconfigure(0, weight=1)
        canvas_widget.configure(
            highlightbackground="lightblue", highlightthickness=2
        )  # Solo para pruebas
        graphic_frame.pack_propagate(False)

        self.keyboard = NumericKeyboard(self, scroll_host=content_frame)
        self.keyboard.attach([self.interval_entry])

    def _ensure_ads(self) -> bool:
        if self.ads is not None:
            return True
        from templates.constants import secrets
        if secrets.get("environment", "") == "dev":
            return False
        try:
            from templates.utils import read_settings_from_file
            settings = read_settings_from_file()
            ads_fsr = float(settings.get("ads_fsr", 1.024))
            from Drivers.ReaderADS import Ads1115Reader
            self.ads = Ads1115Reader(address=0x48, fsr=ads_fsr, sps=64, single_shot=False)
            return True
        except Exception as e:
            print(f"ADS init failed: {e}")
            return False

    def iniciar_lectura(self):
        print("Iniciar lectura del fotoreceptor")
        if self.running:
            print("Ya se está leyendo")
            return
        if not self._ensure_ads():
            print("ADS1115 not available")
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

    def save_data(self):
        if not self.data:
            print("No hay datos para guardar")
            return
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = f"files/photoreceptor_data_{timestamp}.csv"
        with open(filename, "w") as f:
            f.write("Time (s),Intensity\n")
            for t, d in zip(self.timestamps, self.data):
                f.write(f"{t:.3f},{d}\n")
        print(f"Datos guardados en {filename}")

    def adquirir_dato(self):
        if not self.running:
            return
        settings = read_settings_from_file()
        if settings["photoreceptor"]["use_diff"]:
            intensidad = self.ads.read_voltage_diff(0, 1, averages=8)
        else:
            intensidad = self.ads.read_voltage(0, averages=8)
        timestamp = time.time()

        self.data.append(intensidad)
        self.timestamps.append(timestamp - self.start_time)

        self.actualizar_grafico()
        # print(f"Intensity: {intensidad:.2f}, Timestamp: {timestamp:.2f}")

        try:
            intervalo = int(self.interval_entry.get())
            self.after(intervalo, self.adquirir_dato)
        except ValueError:
            self.detener_lectura()
            self.interval_entry.configure(background="salmon")

    def actualizar_grafico(self):
        self.ax.clear()
        self.ax.plot(self.timestamps, self.data, color="blue")
        self.ax.set_title("Photoreceptor")
        self.ax.set_xlabel("Time (s)")
        self.ax.set_ylabel("Intensity")
        self.canvas.draw()
