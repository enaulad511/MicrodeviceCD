# -*- coding: utf-8 -*-
__author__ = "Edisson A. Naula"
__date__ = "$ 21/10/2025 at 11:30 a.m. $"

import ttkbootstrap as ttk
from ttkbootstrap.scrolled import ScrolledFrame
from templates.constants import font_entry
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg


def create_widgets_pcr(parent, callbacks: dict):
    entries = []

    # Frame: Configuración PCR
    frame1 = ttk.LabelFrame(parent, text="PCR Configuration")
    frame1.grid(row=0, column=0, padx=10, pady=10, sticky="nswe")
    frame1.configure(style="Custom.TLabelframe")

    labels = [
        "High Temp (°C):",
        "Low Temp (°C):",
        "Time High (s):",
        "Time Low (s):",
        "Number of Cycles:",
        "RPM Cooling:"
    ]

    default_values = ["100", "25", "15", "10", "1", "500"]

    for i, lbl in enumerate(labels):
        ttk.Label(frame1, text=lbl, style="Custom.TLabel").grid(
            row=i, column=0, padx=5, pady=5, sticky="e"
        )
        entry = ttk.Entry(frame1, font=font_entry)
        entry.insert(0, default_values[i])
        entry.grid(row=i, column=1, padx=5, pady=5)
        entries.append(entry)

    # Botón para generar perfil
    ttk.Button(
        frame1,
        text="Generate Profile",
        style="info.TButton",
        command=callbacks.get("callback_generate_profile"),
    ).grid(row=len(labels), column=0, columnspan=2, pady=10)

    return entries


class PCRFrame(ttk.Frame):
    def __init__(self, parent):
        ttk.Frame.__init__(self, parent)
        self.parent = parent
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        content_frame = ScrolledFrame(self, autohide=True)
        content_frame.grid(row=0, column=0, sticky="nsew")
        content_frame.columnconfigure(0, weight=1)

        callbacks = {
            "callback_generate_profile": self.callback_generate_profile,
        }
        self.entries = create_widgets_pcr(content_frame, callbacks)

        # Frame para mostrar el gráfico
        self.profile_frame = ttk.LabelFrame(content_frame, text="Profile Preview")
        self.profile_frame.grid(row=1, column=0, padx=10, pady=10, sticky="nswe")
        self.profile_frame.configure(style="Custom.TLabelframe")

        self.canvas = None  # Para almacenar el gráfico incrustado

        self.callback_generate_profile()  # Generar el gráfico inicial

    def callback_generate_profile(self):
        try:
            high_temp = float(self.entries[0].get())
            low_temp = float(self.entries[1].get())
            time_high = float(self.entries[2].get())
            time_low = float(self.entries[3].get())
            cycles = int(self.entries[4].get())
            rpm = float(self.entries[5].get())

            # Generar datos con pendientes proporcionales a RPM
            times = []
            temps = []
            current_time = 0
            transition_const = 10000  # Ajusta la escala de transición
            transition_time_down = transition_const / max(rpm, 1)
            transition_time_up = 15

            # Segmentos para dibujar con colores y etiquetas
            phase_segments = []

            for _ in range(cycles):
                # Transición Low -> High
                start = current_time
                end = current_time + transition_time_up
                phase_segments.append((start, end, None, 'Heating'))
                current_time = end

                # High Temp fase
                start = current_time
                end = current_time + time_high
                phase_segments.append((start, end, high_temp, 'High'))
                current_time = end

                # Transición High -> Low
                start = current_time
                end = current_time + transition_time_down
                phase_segments.append((start, end, None, 'Cooling'))
                current_time = end

                # Low Temp fase
                start = current_time
                end = current_time + time_low
                phase_segments.append((start, end, low_temp, 'Low'))
                current_time = end

            # Crear figura
            fig, ax = plt.subplots(figsize=(7, 4))

            # Dibujar fases con colores y etiquetas
            for seg in phase_segments:
                start, end, temp, label = seg
                if label == 'High':
                    ax.hlines(high_temp, start, end, colors='red', linewidth=2)
                    ax.text((start + end) / 2, high_temp + 1, 'High', ha='center', color='red')
                elif label == 'Low':
                    ax.hlines(low_temp, start, end, colors='blue', linewidth=2)
                    ax.text((start + end) / 2, low_temp + 1, 'Low', ha='center', color='blue')
                else:  # Transiciones
                    if label == 'Cooling':
                        ax.plot([start, end], [high_temp, low_temp], color='green', linestyle='--')
                        ax.text((start + end) / 2, (high_temp + low_temp) / 2, 'Cooling', ha='center', color='green')
                    else:
                        ax.plot([start, end], [low_temp, high_temp], color='orange', linestyle='--')
                        ax.text((start + end) / 2, (high_temp + low_temp) / 2, 'Heating', ha='center', color='orange')

            # Líneas horizontales de referencia
            ax.axhline(high_temp, color='red', linestyle=':', linewidth=1)
            ax.axhline(low_temp, color='blue', linestyle=':', linewidth=1)

            ax.set_xlabel("Tiempo (s)")
            ax.set_ylabel("Temperatura (°C)")
            ax.set_title(f"Perfil PCR - RPM Cooling: {rpm}")
            ax.grid(True)

            # Limpiar canvas previo
            if self.canvas:
                self.canvas.get_tk_widget().destroy()

            # Incrustar nuevo gráfico
            self.canvas = FigureCanvasTkAgg(fig, master=self.profile_frame)
            self.canvas.draw()
            self.canvas.get_tk_widget().pack(fill="both", expand=True)

        except ValueError:
            print("Error: Verifique los valores ingresados.")
    