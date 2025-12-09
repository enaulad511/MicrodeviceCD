
# -*- coding: utf-8 -*-
from Drivers.ClientUDP import UdpClient
__author__ = "Edisson A. Naula"
__date__ = "$ 09/12/2025 at 01:07 p.m. $"

import ttkbootstrap as ttk
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import time
import random

from ttkbootstrap.scrolled import ScrolledFrame
from templates.constants import font_entry

class TemperatureFrame(ttk.Frame):
    """
    Frame de Tk para leer y graficar temperatura en tiempo real.
    - Similar a PhotoreceptorFrame, pero leyendo temperatura.
    - Permite inyectar una función lectora de sensor real (sensor_reader)
      que devuelva la temperatura en °C como float.
    """

    def __init__(self, parent, sensor_reader="default", title="Temperature measurement"):
        super().__init__(parent)
        self.parent = parent
        self.start_time = 0.0
        self.running = False
        self.temps = []        # Temperaturas
        self.timestamps = []   # Tiempos relativos (s)
        self.client = None
        # Función para leer temperatura (°C). Si no se pasa, usa simulación.
        self.sensor_reader = self._simulated_reader if sensor_reader == "default" else self._thermocouple_reader
        # Layout base
        self.columnconfigure(0, weight=1)
        self.rowconfigure((0, 1), weight=1)

        content_frame = ScrolledFrame(self, autohide=True)
        content_frame.grid(row=0, column=0, sticky="nsew")
        content_frame.columnconfigure(0, weight=1)

        # --- Controles ---
        control_frame = ttk.LabelFrame(content_frame, text="Temperature control")
        control_frame.grid(row=0, column=0, padx=10, pady=10, sticky="nswe")
        control_frame.configure(style="Custom.TLabelframe")
        control_frame.columnconfigure((0, 1, 2, 3), weight=1)

        ttk.Label(
            control_frame, text="Intervalo muestreo (ms):", style="Custom.TLabel"
        ).grid(row=0, column=0, padx=5, pady=5, sticky="w")

        self.interval_entry = ttk.Entry(control_frame, width=10, font=font_entry)
        self.interval_entry.insert(0, "1000")  # Por defecto 1 segundo
        self.interval_entry.grid(row=0, column=1, padx=5, pady=5, sticky="we")

        ttk.Label(
            control_frame, text="Unidad:", style="Custom.TLabel"
        ).grid(row=0, column=2, padx=5, pady=5, sticky="e")

        self.unit_var = ttk.StringVar(value="°C")
        self.unit_combo = ttk.Combobox(
            control_frame,
            textvariable=self.unit_var,
            values=["°C", "°F"],
            state="readonly",
            font=font_entry,
            width=6,
        )
        self.unit_combo.grid(row=0, column=3, padx=5, pady=5, sticky="we")
        self.unit_combo.bind("<<ComboboxSelected>>", lambda e: self.actualizar_grafico())

        ttk.Button(
            control_frame,
            text="Start",
            command=self.iniciar_lectura,
            style="info.TButton",
        ).grid(row=1, column=0, padx=5, pady=5, sticky="we")

        ttk.Button(
            control_frame,
            text="Stop",
            command=self.detener_lectura,
            style="danger.TButton",
        ).grid(row=1, column=1, padx=5, pady=5, sticky="we")

        ttk.Button(
            control_frame,
            text="Limpiar",
            command=self.limpiar_datos,
            style="secondary.TButton",
        ).grid(row=1, column=2, padx=5, pady=5, sticky="we")

        ttk.Button(
            control_frame,
            text="Guardar CSV",
            command=self.guardar_csv,
            style="success.TButton",
        ).grid(row=1, column=3, padx=5, pady=5, sticky="we")

        # --- Gráfico ---
        self.fig, self.ax = plt.subplots(figsize=(5, 3))
        self.ax.set_title(title)
        self.ax.set_xlabel("Tiempo (s)")
        self.ax.set_ylabel("Temperatura (°C)")
        self.canvas = FigureCanvasTkAgg(self.fig, master=self)
        canvas_widget = self.canvas.get_tk_widget()
        canvas_widget.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")
        canvas_widget.columnconfigure(0, weight=1)
        canvas_widget.rowconfigure(0, weight=1)
        canvas_widget.configure(highlightbackground="lightblue", highlightthickness=2)  # Solo pruebas

    # ----------------- Control -----------------

    def iniciar_lectura(self):
        print("Iniciar lectura de temperatura")
        if self.running:
            print("Ya se está leyendo")
            return
        self.client = UdpClient(
            port=5005,
            buffer_size=4096,
            allow_broadcast=True,  # Important for broadcast payloads
            local_ip="",  # "" listens on all interfaces (wlan0, eth0, etc.)
            recv_timeout_sec=1.0,  # lets loop check stop flag periodically
            on_message=None,
            parse_float=True,  # Arduino sends a numeric string
        )
        try:
            intervalo = int(self.interval_entry.get())
            if intervalo < 100:
                intervalo = 100  # Evita intervalos demasiado cortos
                self.interval_entry.delete(0, "end")
                self.interval_entry.insert(0, str(intervalo))

            self.running = True
            self.start_time = time.time()
            self.temps.clear()
            self.timestamps.clear()
            self.client.start()
            self.after(intervalo, self.adquirir_dato)
        except ValueError:
            self.interval_entry.configure(background="salmon")

    def detener_lectura(self):
        print("Detener lectura de temperatura")
        if self.client is not None:
            self.client.stop()
        self.running = False

    def limpiar_datos(self):
        if self.running:
            self.detener_lectura()
        self.temps.clear()
        self.timestamps.clear()
        self.actualizar_grafico()
        print("Datos limpiados")

    # ----------------- Adquisición -----------------

    def adquirir_dato(self):
        if not self.running:
            return

        # Lee temperatura en °C desde el sensor (o simulador)
        try:
            temp_c = float(self.sensor_reader())
        except Exception as e:
            print(f"Error leyendo el sensor: {e}")
            temp_c = float("nan")

        timestamp = time.time() - self.start_time
        self.timestamps.append(timestamp)
        self.temps.append(temp_c)

        self.actualizar_grafico()

        try:
            intervalo = int(self.interval_entry.get())
            self.after(intervalo, self.adquirir_dato)
        except ValueError:
            self.detener_lectura()
            self.interval_entry.configure(background="salmon")

    # ----------------- Gráfico -----------------

    def _convert_units(self, temp_c):
        """Convierte °C a la unidad seleccionada."""
        if self.unit_var.get() == "°F":
            return temp_c * 9.0 / 5.0 + 32.0
        return temp_c

    def actualizar_grafico(self):
        self.ax.clear()

        # Aplica conversión a la serie completa
        if len(self.temps) > 0:
            temps_conv = [self._convert_units(t) for t in self.temps]
        else:
            temps_conv = []

        unidad = self.unit_var.get()
        self.ax.plot(self.timestamps, temps_conv, color="tomato", linewidth=1.5)
        self.ax.set_title("Lectura de Temperatura")
        self.ax.set_xlabel("Tiempo (s)")
        self.ax.set_ylabel(f"Temperatura ({unidad})")
        self.ax.grid(True, alpha=0.25)
        self.canvas.draw()
        # print("Gráfico actualizado")

    # ----------------- Persistencia -----------------

    def guardar_csv(self):
        """Guarda los datos en un CSV simple en el directorio actual."""
        import csv
        from datetime import datetime

        if not self.timestamps:
            print("No hay datos para guardar.")
            return

        fecha = datetime.now().strftime("%Y%m%d_%H%M%S")
        nombre = f"temperature_log_{fecha}.csv"

        unidad = self.unit_var.get()
        try:
            with open(nombre, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["t (s)", f"Temp ({unidad})"])
                for t, c in zip(self.timestamps, self.temps):
                    writer.writerow([f"{t:.3f}", f"{self._convert_units(c):.3f}"])
            print(f"CSV guardado: {nombre}")
        except Exception as e:
            print(f"Error guardando CSV: {e}")

    # ----------------- Lectores de ejemplo -----------------

    def _simulated_reader(self):
        """
        Simulador de temperatura en °C:
        Oscila alrededor de 25 °C con algo de ruido.
        """
        base = 25.0
        ruido = random.gauss(0, 0.2)
        drift = 0.5 * (time.time() % 60) / 60.0  # variación lenta (0 a 0.5 °C)
        return base + ruido + drift

    def _thermocouple_reader(self) -> float:
        """
        Lector de temperatura del termopar (Thermocouple) en °C.
        Usa socket to pico
        """
        if self.client is None:
            return float("nan")
        lf = self.client.latest_float()
        if lf is None:
            return float("nan")
        return lf


    @staticmethod
    def cpu_temp_reader():
        """
        Lector de temperatura del CPU (Raspberry Pi u otros Linux) en °C.
        Usa /sys/class/thermal/thermal_zone0/temp.
        """
        try:
            with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
                millic = int(f.read().strip())
            return millic / 1000.0
        except Exception:
            # Si no existe ese path, devuelve NaN
            return float("nan")
