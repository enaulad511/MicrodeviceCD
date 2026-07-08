# -*- coding: utf-8 -*-
from Drivers.ClientUDP import UdpClient

__author__ = "Edisson A. Naula"
__date__ = "$ 09/12/2025 at 01:07 p.m. $"

import os
import random
import time
from tkinter import filedialog

import matplotlib.pyplot as plt
import ttkbootstrap as ttk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from ttkbootstrap.scrolled import ScrolledFrame

from templates.constants import font_entry
from templates.utils import (
    read_temp_source,
    temp_source_index,
    temp_source_key,
    temp_source_label,
    temp_source_labels,
    write_temp_source,
)
from ui.KeyboardFrame import NumericKeyboard


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
        self.temps = []  # Temperaturas
        self.timestamps = []  # Tiempos relativos (s)
        self.client = None
        self.temps_filter = [20.0, 20.0, 20.0, 20.0]  # temps for filtering
        self.latest_temp = 20.0
        self.latest_temp_ts = 0.0
        # Últimas tres temperaturas del disco (IR amb, IR obj, termocupla) y la
        # fuente elegida; el lector usa temp_source_idx. temp_source_bad => sensor
        # ausente (se sostiene el último valor y se avisa en el status).
        self.latest_temps = [20.0, 20.0, 20.0]
        self._field_ok = [True, True, True]  # último broadcast trajo el campo i?
        self.temp_source = read_temp_source()
        self.temp_source_idx = temp_source_index(self.temp_source)
        self.temp_source_bad = False
        # Función para leer temperatura (°C). Si no se pasa, usa simulación.
        self.sensor_reader = (
            self._simulated_reader if sensor_reader == "default" else self._thermocouple_reader
        )
        # Layout base
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        content_frame = ScrolledFrame(self, autohide=True)
        content_frame.grid(row=0, column=0, sticky="nsew")
        content_frame.columnconfigure(0, weight=1)
        content_frame.rowconfigure((0, 1), weight=1)

        # --- Controles ---
        control_frame = ttk.LabelFrame(content_frame, text="Temperature control")
        control_frame.grid(row=0, column=0, padx=10, pady=10, sticky="nswe")
        control_frame.configure(style="Custom.TLabelframe")
        control_frame.columnconfigure((0, 1, 2, 3), weight=1)

        ttk.Label(control_frame, text="Sample time (ms):", style="Custom.TLabel").grid(
            row=0, column=0, padx=5, pady=5, sticky="w"
        )

        self.interval_entry = ttk.Entry(control_frame, width=10, font=font_entry)
        self.interval_entry.insert(0, "500")  # Por defecto 1 segundo
        self.interval_entry.grid(row=0, column=1, padx=5, pady=5, sticky="we")

        ttk.Label(control_frame, text="Unit:", style="Custom.TLabel").grid(
            row=0, column=2, padx=5, pady=5, sticky="e"
        )

        self.unit_var = ttk.StringVar(value="°C")
        self.unit_combo = ttk.Combobox(
            control_frame,
            textvariable=self.unit_var,
            values=["°C", "°F"],
            state="readonly",
            font=font_entry,
            width=6,
        )
        self.unit_combo.grid(row=0, column=3, padx=(2, 20), pady=5, sticky="we")
        self.unit_combo.bind("<<ComboboxSelected>>", lambda e: self.actualizar_grafico())

        ttk.Label(control_frame, text="Temp source:", style="Custom.TLabel").grid(
            row=2, column=0, padx=5, pady=5, sticky="w"
        )
        self.cbo_temp_source = ttk.Combobox(
            control_frame,
            values=temp_source_labels(),
            state="readonly",
            font=font_entry,
            width=14,
        )
        self.cbo_temp_source.set(temp_source_label(self.temp_source))
        self.cbo_temp_source.grid(row=2, column=1, padx=5, pady=5, sticky="we")
        self.cbo_temp_source.bind("<<ComboboxSelected>>", self._on_temp_source_changed)

        self.lbl_status = ttk.Label(control_frame, text="", style="Custom.TLabel", anchor="w")
        self.lbl_status.grid(row=2, column=2, columnspan=2, padx=5, pady=5, sticky="we")

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
            text="Clean",
            command=self.limpiar_datos,
            style="secondary.TButton",
        ).grid(row=1, column=2, padx=5, pady=5, sticky="we")

        ttk.Button(
            control_frame,
            text="Save CSV",
            command=self.guardar_csv,
            style="success.TButton",
        ).grid(row=1, column=3, padx=(2, 20), pady=5, sticky="we")

        # --- Gráfico ---
        self.fig, self.ax = plt.subplots()
        self.ax.set_title(title)
        self.ax.set_xlabel("Time (s)")
        self.ax.set_ylabel("Temperature (°C)")
        self.canvas = FigureCanvasTkAgg(self.fig, master=content_frame)
        canvas_widget = self.canvas.get_tk_widget()
        canvas_widget.grid(row=1, column=0, padx=(2, 20), pady=10, sticky="nsew")
        canvas_widget.columnconfigure(0, weight=1)
        canvas_widget.rowconfigure(0, weight=1)
        canvas_widget.configure(
            highlightbackground="lightblue", highlightthickness=2
        )  # Solo pruebas

        self.keyboard = NumericKeyboard(self, scroll_host=content_frame)
        self.keyboard.attach([self.interval_entry])

    # ----------------- Control -----------------

    def iniciar_lectura(self):
        print("Starting temperature reading")
        if self.running:
            print("Already reading")
            return
        self.client = UdpClient(
            port=5005,
            buffer_size=512,
            allow_broadcast=True,  # Important for broadcast payloads
            local_ip="",  # "" listens on all interfaces (wlan0, eth0, etc.)
            recv_timeout_sec=0.1,  # lets loop check stop flag periodically
            on_message=lambda t, a, t_d: self._on_udp_message(t, a, t_d),
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
            print("Invalid interval")

    def detener_lectura(self):
        print("Stopping temperature reading")
        if self.client is not None:
            self.client.stop()
        self.running = False

    def limpiar_datos(self):
        if self.running:
            self.detener_lectura()
        self.temps.clear()
        self.timestamps.clear()
        self.actualizar_grafico()
        print("Data cleared")

    # ----------------- Adquisición -----------------

    def adquirir_dato(self):
        if not self.running:
            return

        # Lee temperatura en °C desde el sensor (o simulador)
        try:
            temp_c = float(self.sensor_reader())
        except Exception as e:
            print(f"Error reading sensor: {e}")
            temp_c = self.temps_filter[-1]

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
        self.ax.set_title("Readings")
        self.ax.set_xlabel("Time (s)")
        self.ax.set_ylabel(f"Temperature ({unidad})")
        self.ax.grid(True, alpha=0.25)
        self.canvas.draw()
        # print("Gráfico actualizado")
        src_label = temp_source_label(self.temp_source)
        if self.temp_source_bad:
            self.lbl_status.configure(text=f"⚠ {src_label} unavailable — holding last value")
        else:
            self.lbl_status.configure(text=f"Source: {src_label}")

    # ----------------- Persistencia -----------------

    def guardar_csv(self):
        """Guarda los datos en un CSV simple en el directorio actual."""
        import csv
        from datetime import datetime

        if not self.timestamps:
            print("No data to save.")
            return

        os.makedirs("files", exist_ok=True)
        fecha = datetime.now().strftime("%Y%m%d_%H%M%S")
        nombre = filedialog.asksaveasfilename(
            parent=self,
            title="Save temperature data",
            initialdir="files",
            initialfile=f"temperature_log_{fecha}.csv",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All", "*.*")],
        )
        if not nombre:
            print("Save cancelled")
            return
        if not nombre.lower().endswith(".csv"):
            nombre += ".csv"

        unidad = self.unit_var.get()
        try:
            with open(nombre, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["t (s)", f"Temp {temp_source_label(self.temp_source)} ({unidad})"])
                for t, c in zip(self.timestamps, self.temps):
                    writer.writerow([f"{t:.3f}", f"{self._convert_units(c):.3f}"])
            print(f"CSV saved: {nombre}")
        except Exception as e:
            print(f"Error saving CSV: {e}")

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

    def _on_temp_source_changed(self, event=None):
        self.temp_source = temp_source_key(self.cbo_temp_source.get())
        self.temp_source_idx = temp_source_index(self.temp_source)
        self.temp_source_bad = False
        self.temps_filter = [self.latest_temps[self.temp_source_idx]] * 4
        write_temp_source(self.temp_source)
        self.actualizar_grafico()

    def _on_udp_message(self, text, address, temps_list):
        """Callback invocado por UdpClient en su hilo cuando llega un broadcast UDP válido.

        Guarda las tres temperaturas (IR amb, IR obj, termocupla); conserva el
        último valor válido por campo y marca cuáles vinieron ausentes (None)."""
        for i in range(3):
            v = temps_list[i] if i < len(temps_list) else None
            if v is not None:
                self.latest_temps[i] = float(v)
                self._field_ok[i] = True
            else:
                self._field_ok[i] = False
        self.latest_temp = self.latest_temps[2]  # compat con lectores directos
        self.latest_temp_ts = temps_list[3]

    def _thermocouple_reader(self) -> float:
        """
        Lector de la temperatura elegida (termocupla / IR objeto / IR ambiente) en °C.
        Usa el broadcast UDP del disco; promedio móvil de 4 muestras. Si el sensor
        elegido viene ausente, sostiene el último valor y avisa en el status.
        """
        if self.client is None:
            print("Client is None")
            return 20.0
        idx = self.temp_source_idx
        self.temp_source_bad = not self._field_ok[idx]
        lf = self.latest_temps[idx]
        self.temps_filter.pop(0)
        self.temps_filter.append(lf)
        return sum(self.temps_filter) / len(self.temps_filter)

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
