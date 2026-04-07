# -*- coding: utf-8 -*-
from templates.utils import convert_si_integer_full
from ui.UDPClientFrame import UDPIVPlotter

__author__ = "Edisson A. Naula"
__date__ = "$ 11/11/2025 at 14:45 p.m. $"

import ttkbootstrap as ttk
from tkinter.scrolledtext import ScrolledText
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from templates.constants import font_entry  # Ajusta si no tienes este archivo


DEFAUL_VALUES_CV = ["0", "-0.5", "-1.0", "1.0", "0.1", "1.0", "2"]


def construc_nscans_script(
    t_equilibration, E_begin, E_vertex1, E_vertex2, E_step, n_scans
):
    script = (
        "var i\n"
        "var e\n"
        "set_pgstat_chan 1\n"
        "set_pgstat_mode 0\n"
        "set_pgstat_chan 0\n"
        "set_pgstat_mode 2\n"
        "set_max_bandwidth 585054m\n"
        "set_range_minmax da -1 1\n"
        "set_range ba 470u\n"
        "set_autoranging ba 917969p 470u\n"
        f"set_e {E_begin}\n"
        "cell_on\n"
        f"wait {t_equilibration} s\n"
        f"meas_loop_cv e i {E_begin} {E_vertex1} {E_vertex2} {E_step} nscans({n_scans})\n"
        "pck_start\n"
        "    pck_add e\n"
        "    pck_add i\n"
        "pck_end\n"
        "endloop\n"
        "on_finished:\n"
        "cell_off\n"
    )
    return script.strip()


def construc_individual_script(t_equilibration, E_begin, E_vertex1, E_vertex2, E_step):
    script = (
        "var i\n"
        "var e\n"
        "set_pgstat_chan 1\n"
        "set_pgstat_mode 0\n"
        "set_pgstat_chan 0\n"
        "set_pgstat_mode 2\n"
        "set_max_bandwidth 585054m\n"
        "set_range_minmax da -1 1\n"
        "set_range ba 470u\n"
        "set_autoranging ba 917969p 470u\n"
        f"set_e {E_begin}\n"
        "cell_on\n"
        f"wait {t_equilibration}s\n"
        f"meas_loop_cv e i {E_begin} {E_vertex1} {E_vertex2} {E_step}\n"
        "pck_start\n"
        "    pck_add e\n"
        "    pck_add i\n"
        "pck_end\n"
        "endloop\n"
        "on_finished:\n"
        "cell_off\n"
    )
    return script.strip()


class ShowMethodScript(ttk.Toplevel):
    def __init__(self, parent, script: str):
        super().__init__(parent)
        self.title("Method Script")
        self.parent = parent
        # self.geometry("600x400")
        self.script_box = ScrolledText(self, height=20)
        self.script_box.pack(fill="both", expand=True, padx=10, pady=10)
        self.script_box.insert("end", script)
        self.script_box.configure(state="disabled")

        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def on_close(self):
        self.parent.on_close_script_window()
        self.destroy()


class ShowProfileFrame(ttk.Toplevel):
    def __init__(
        self,
        parent,
        n_scans,
        t_interval,
        E_begin,
        E_vertex1,
        E_vertex2,
        E_step,
        t_equilibration,
    ):
        super().__init__(parent)
        self.title("CV Profile Preview")
        self.parent = parent
        # Generar datos para la gráfica
        times = []
        potentials = []
        current_time = 0.0
        segments = []
        # Equilibración
        times.append(current_time)
        potentials.append(E_begin)
        current_time += t_equilibration
        times.append(current_time)
        potentials.append(E_begin)

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
        ax.step(times, potentials, where="post", color="blue", linewidth=2)

        for seg in segments:
            start, end, label = seg
            mid_time = (start + end) / 2
            mid_potential = potentials[int(len(potentials) * mid_time / times[-1])]
            color = (
                "orange"
                if label == "Forward"
                else "green"
                if label == "Reverse"
                else "purple"
            )
            ax.text(
                mid_time, mid_potential, label, ha="center", color=color, fontsize=9
            )

        ax.axhline(E_begin, color="gray", linestyle=":", linewidth=1)
        ax.axhline(E_vertex1, color="red", linestyle=":", linewidth=1)
        ax.axhline(E_vertex2, color="green", linestyle=":", linewidth=1)

        ax.set_xlabel("Time (s)")
        ax.set_ylabel("Potential (V)")
        ax.set_title(f"CV Profile - t_interval = {t_interval:.3f} s")
        ax.grid(True)

        # if self.canvas:
        #     self.canvas.get_tk_widget().destroy()

        self.canvas = FigureCanvasTkAgg(fig, master=self)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def on_close(self):
        self.parent.on_close_profile_window()
        self.destroy()


def create_widgets_cv(parent, callbacks: dict, columns=2):
    entries = []

    # Configurar columnas del contenedor principal
    parent.columnconfigure(tuple(range(columns)), weight=1)

    frame1 = ttk.LabelFrame(parent, text="Cyclic Voltammetry Settings")
    frame1.grid(
        row=0, column=0, columnspan=columns - 1, padx=(5, 20), pady=10, sticky="nswe"
    )
    frame1.configure(style="Custom.TLabelframe")

    # Configurar columnas internas dinámicamente
    frame1.columnconfigure(tuple(range(columns * 2)), weight=1)

    labels = [
        "t equil. (s):",
        "E begin (V):",
        "E vertex1 (V):",
        "E vertex2 (V):",
        "E step (V):",
        "Scan rate (V/s):",
        "Number of scans:",
    ]

    # Calcular cuántos elementos por columna
    total = len(labels)
    per_col = (total + columns - 1) // columns  # redondeo hacia arriba

    for col in range(columns):
        start = col * per_col
        end = min(start + per_col, total)
        subset = labels[start:end]

        for i, lbl in enumerate(subset):
            row = i

            # Etiqueta
            ttk.Label(frame1, text=lbl, style="Custom.TLabel").grid(
                row=row, column=col * 2, padx=5, pady=5, sticky="w"
            )

            # Entry
            entry = ttk.Entry(frame1, font=font_entry)
            entry.insert(0, DEFAUL_VALUES_CV[start + i])
            entry.grid(row=row, column=col * 2 + 1, padx=5, pady=5, sticky="nswe")
            entries.append(entry)

    # Panel de controles a la derecha
    frame_controls = ttk.Frame(parent)
    frame_controls.grid(row=0, column=columns - 1, pady=10, sticky="nswe")
    frame_controls.columnconfigure(0, weight=1)

    ttk.Button(
        frame_controls,
        text="Generate CV Profile",
        style="info.TButton",
        command=callbacks.get("callback_generate_profile", ()),
    ).grid(row=0, column=0, pady=5, sticky="nswe")

    ttk.Button(
        frame_controls,
        text="Show MethodScript",
        style="info.TButton",
        command=callbacks.get("callback_show_script", ()),
    ).grid(row=1, column=0, pady=5, sticky="nswe")

    ttk.Button(
        frame_controls,
        text="Send Script",
        style="info.TButton",
        command=callbacks.get("callback_send_script", ()),
    ).grid(row=2, column=0, pady=5, sticky="nswe")

    return entries


class CVFrame(ttk.Frame):
    def __init__(self, parent):
        ttk.Frame.__init__(self, parent)
        self.parent = parent
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        # ----------------variables--------------
        self.t_equilibration = float(DEFAUL_VALUES_CV[0])
        self.E_begin = float(DEFAUL_VALUES_CV[1])
        self.E_vertex1 = float(DEFAUL_VALUES_CV[2])
        self.E_vertex2 = float(DEFAUL_VALUES_CV[3])
        self.E_step = float(DEFAUL_VALUES_CV[4])
        self.scan_rate = float(DEFAUL_VALUES_CV[5])
        self.n_scans = int(DEFAUL_VALUES_CV[6])
        self.ShowMethodScrit = None
        self.ShowProfile = None
        # ---------------------------------------

        content_frame = ttk.Frame(self)
        content_frame.grid(row=0, column=0, sticky="nsew")
        content_frame.columnconfigure(0, weight=1)

        callbacks = {
            "callback_generate_profile": self.callback_generate_profile,
            "callback_show_script": self.callback_show_methodscript,
            "callback_send_script": self.callback_send_script,
        }
        self.entries = create_widgets_cv(content_frame, callbacks)
        self.frame_plotter = ttk.LabelFrame(self, text="Live Data Plotter")
        self.frame_plotter.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")
        self.frame_plotter.columnconfigure(0, weight=1)
        udp_plotter = UDPIVPlotter(
            self.frame_plotter,
            udp_port=5005,
            buffer_size=4096,
            max_points=5000,
            update_interval_ms=80,
        )
        udp_plotter.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        self.frame_plotter.grid_forget()

    def create_payload_cv(self):
        self.payload = {
            "t_e": convert_si_integer_full(self.t_equilibration),
            "E_b": convert_si_integer_full(self.E_begin),
            "E_1": convert_si_integer_full(self.E_vertex1),
            "E_2": convert_si_integer_full(self.E_vertex2),
            "E_s": convert_si_integer_full(self.E_step),
            "sc_r": convert_si_integer_full(self.scan_rate),
            "n_sc": convert_si_integer_full(self.n_scans),
            "method": "cv",
        }

    def update_data_script(self):
        try:
            # Leer parámetros
            self.t_equilibration = float(self.entries[0].get())
            self.E_begin = float(self.entries[1].get())
            self.E_vertex1 = float(self.entries[2].get())
            self.E_vertex2 = float(self.entries[3].get())
            self.E_step = float(self.entries[4].get())
            self.scan_rate = float(self.entries[5].get())
            self.n_scans = int(self.entries[6].get())
        except ValueError as e:
            print(f"Error: Invalid input. Please enter valid numbers -> {e}")
            self.t_equilibration = float(DEFAUL_VALUES_CV[0])
            self.E_begin = float(DEFAUL_VALUES_CV[1])
            self.E_vertex1 = float(DEFAUL_VALUES_CV[2])
            self.E_vertex2 = float(DEFAUL_VALUES_CV[3])
            self.E_step = float(DEFAUL_VALUES_CV[4])
            self.scan_rate = float(DEFAUL_VALUES_CV[5])
            self.n_scans = int(DEFAUL_VALUES_CV[6])

    def callback_send_script(self):
        try:
            self.update_data_script()
            self.create_payload_cv()
            script = self.generate_methodscript()

            self.frame_plotter.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")
        except ValueError:
            self.frame_plotter.grid_forget()
            print("Error: Check input values.")
            return

    def callback_generate_profile(self):
        try:
            self.update_data_script()
            # Calcular intervalo de tiempo
            t_interval = self.E_step / self.scan_rate
        except ValueError:
            print("Error: Check input values.")
            return
        # Crear ventana de perfil
        if self.ShowProfile is not None:
            self.ShowProfile.destroy()
            self.ShowProfile = None
        self.ShowProfile = ShowProfileFrame(
            self,
            self.n_scans,
            t_interval,
            self.E_begin,
            self.E_vertex1,
            self.E_vertex2,
            self.E_step,
            self.t_equilibration,
        )

    def callback_show_methodscript(self):
        script = self.generate_methodscript()
        if self.ShowMethodScrit is not None:
            self.ShowMethodScrit.destroy()
            self.ShowMethodScrit = None
        self.ShowMethodScrit = ShowMethodScript(self, script)

    def on_close_script_window(self):
        self.ShowMethodScrit = None

    def on_close_profile_window(self):
        self.ShowProfile = None

    def generate_methodscript(self) -> str:
        if self.n_scans > 1:
            script = construc_nscans_script(
                convert_si_integer_full(self.t_equilibration),
                convert_si_integer_full(self.E_begin),
                convert_si_integer_full(self.E_vertex1),
                convert_si_integer_full(self.E_vertex2),
                convert_si_integer_full(self.E_step),
                convert_si_integer_full(self.n_scans),
            )
        else:
            script = construc_individual_script(
                convert_si_integer_full(self.t_equilibration),
                convert_si_integer_full(self.E_begin),
                convert_si_integer_full(self.E_vertex1),
                convert_si_integer_full(self.E_vertex2),
                convert_si_integer_full(self.E_step),
            )
        return script.strip()


if __name__ == "__main__":
    app = ttk.Window(themename="flatly")
    app.title("EmStatPico CV Configuration")
    app.geometry("900x700")
    CVFrame(app).pack(fill="both", expand=True)
    app.mainloop()
