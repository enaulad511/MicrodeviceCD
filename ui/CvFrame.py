# -*- coding: utf-8 -*-
__author__ = "Edisson A. Naula"
__date__ = "$ 11/11/2025 at 14:45 p.m. $"

import ttkbootstrap as ttk
from ttkbootstrap.scrolled import ScrolledFrame
from tkinter.scrolledtext import ScrolledText
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from templates.constants import font_entry  # Ajusta si no tienes este archivo


def create_widgets_cv(parent, callbacks: dict):
    entries = []

    frame1 = ttk.LabelFrame(parent, text="Cyclic Voltammetry Settings")
    frame1.grid(row=0, column=0, padx=(5, 20), pady=10, sticky="nswe")
    frame1.configure(style="Custom.TLabelframe")

    labels = [
        "t equilibration (s):",
        "E begin (V):",
        "E vertex1 (V):",
        "E vertex2 (V):",
        "E step (V):",
        "Scan rate (V/s):",
        "Number of scans:"
    ]

    default_values = ["0", "-0.5", "-1.0", "1.0", "0.1", "1.0", "2"]

    for i, lbl in enumerate(labels):
        ttk.Label(frame1, text=lbl, style="Custom.TLabel").grid(
            row=i, column=0, padx=5, pady=5, sticky="e"
        )
        entry = ttk.Entry(frame1, font=font_entry)
        entry.insert(0, default_values[i])
        entry.grid(row=i, column=1, padx=5, pady=5)
        entries.append(entry)

    ttk.Button(
        frame1,
        text="Generate CV Profile & Script",
        style="info.TButton",
        command=callbacks.get("callback_generate_profile"),
    ).grid(row=len(labels), column=0, columnspan=2, pady=10)

    return entries


class CVFrame(ttk.Frame):
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
        self.entries = create_widgets_cv(content_frame, callbacks)

        # Frame para la gráfica
        self.profile_frame = ttk.LabelFrame(content_frame, text="Profile Preview")
        self.profile_frame.grid(row=1, column=0, padx=(5, 20), pady=10, sticky="nswe")
        self.profile_frame.configure(style="Custom.TLabelframe")

        # Área para mostrar el script
        self.script_box = ScrolledText(content_frame, height=15)
        self.script_box.grid(row=2, column=0, padx=(5, 20), pady=10, sticky="nswe")

        self.canvas = None
        self.callback_generate_profile()

    def callback_generate_profile(self):
        try:
            # Leer parámetros
            t_equilibration = float(self.entries[0].get())
            E_begin = float(self.entries[1].get())
            E_vertex1 = float(self.entries[2].get())
            E_vertex2 = float(self.entries[3].get())
            E_step = float(self.entries[4].get())
            scan_rate = float(self.entries[5].get())
            n_scans = int(self.entries[6].get())

            # Calcular intervalo de tiempo
            t_interval = E_step / scan_rate

            # Generar datos para la gráfica
            times = []
            potentials = []
            current_time = 0

            # Equilibración
            times.append(current_time)
            potentials.append(E_begin)
            current_time += t_equilibration
            times.append(current_time)
            potentials.append(E_begin)

            segments = []

            for _ in range(n_scans):
                # Forward sweep
                start_time = current_time
                E = E_begin
                while E <= E_vertex2:
                    times.append(current_time)
                    potentials.append(E)
                    current_time += t_interval
                    E += E_step
                segments.append((start_time, current_time, "Forward"))

                # Reverse sweep
                start_time = current_time
                while E >= E_vertex1:
                    times.append(current_time)
                    potentials.append(E)
                    current_time += t_interval
                    E -= E_step
                segments.append((start_time, current_time, "Reverse"))

                # Return sweep
                start_time = current_time
                while E <= E_begin:
                    times.append(current_time)
                    potentials.append(E)
                    current_time += t_interval
                    E += E_step
                segments.append((start_time, current_time, "Return"))

            # Graficar
            fig, ax = plt.subplots(figsize=(7, 4))
            ax.step(times, potentials, where='post', color='blue', linewidth=2)

            for seg in segments:
                start, end, label = seg
                mid_time = (start + end) / 2
                mid_potential = potentials[int(len(potentials) * mid_time / times[-1])]
                color = "orange" if label == "Forward" else "green" if label == "Reverse" else "purple"
                ax.text(mid_time, mid_potential, label, ha='center', color=color, fontsize=9)

            ax.axhline(E_begin, color='gray', linestyle=':', linewidth=1)
            ax.axhline(E_vertex1, color='red', linestyle=':', linewidth=1)
            ax.axhline(E_vertex2, color='green', linestyle=':', linewidth=1)

            ax.set_xlabel("Time (s)")
            ax.set_ylabel("Potential (V)")
            ax.set_title(f"CV Profile - t_interval = {t_interval:.3f} s")
            ax.grid(True)

            if self.canvas:
                self.canvas.get_tk_widget().destroy()

            self.canvas = FigureCanvasTkAgg(fig, master=self.profile_frame)
            self.canvas.draw()
            self.canvas.get_tk_widget().pack(fill="both", expand=True)

            # Generar MethodSCRIPT
            script = self.generate_methodscript(
                t_equilibration, E_begin, E_vertex1, E_vertex2, E_step, n_scans
            )
            self.script_box.delete("1.0", "end")
            self.script_box.insert("end", script)

        except ValueError:
            print("Error: Check input values.")

    def generate_methodscript(self, t_equilibration, E_begin, E_vertex1, E_vertex2, E_step, n_scans) -> str:
        def to_mV(value):
            return f"{int(value * 1000)}m"
        script = f"""
                        var i
                        var e
                        set_pgstat_chan 1
                        set_pgstat_mode 0
                        set_pgstat_chan 0
                        set_pgstat_mode 2
                        set_max_bandwidth 585054m
                        set_range_minmax da -1 1
                        set_range ba 470u
                        set_autoranging ba 917969p 470u
                        set_e {to_mV(E_begin)}
                        cell_on
                        wait {int(t_equilibration * 1000)}ms
                        meas_loop_cv e i {to_mV(E_begin)} {to_mV(E_vertex1)} {to_mV(E_vertex2)} {to_mV(E_step)} {n_scans}
                        pck_start
                            pck_add e
                            pck_add i
                        pck_end
                        endloop
                        on_finished:
                        cell_off
                        """
        return script.strip()


if __name__ == "__main__":
    app = ttk.Window(themename="flatly")
    app.title("EmStatPico CV Configuration")
    app.geometry("900x700")
    CVFrame(app).pack(fill="both", expand=True)
    app.mainloop()