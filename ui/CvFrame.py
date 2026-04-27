# -*- coding: utf-8 -*-
from cgitb import enable
from Drivers.DriverStepperSys import spinMotorAngleDriver
import threading
from templates.utils import read_settings_from_file
from Drivers.EmstatUtils import construc_nscans_script_cv
from templates.utils import convert_si_integer_full
from ui.EventEmstatFrame import EventPlotter

__author__ = "Edisson A. Naula"
__date__ = "$ 11/11/2025 at 14:45 p.m. $"

import ttkbootstrap as ttk
from tkinter.scrolledtext import ScrolledText
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from templates.constants import font_entry  # Ajusta si no tienes este archivo


DEFAUL_VALUES_CV = [
    "0",
    "0.0",
    "-1",
    "1",
    "0.1",
    "0.04",
    "3",
    "585954e-6",
    "-1",
    "1",
    "47e-9",
    "47e-9",
    "47e-9",
    "47e-9",
]
LABELS = [
    "t equil. (s):",
    "E begin (V):",
    "E vertex1 (V):",
    "E vertex2 (V):",
    "E step (V):",
    "Scan rate (V/s):",
    "Number of scans:",
    "Max BW:",
    "Min Pot:",
    "Max Pot:",
    "Range Current:",
    "Max Current:",
    "Auto Current 1:",
    "Auto Current 2:",
]
CURRENT_RANGES = {
    "100 nA": 4.7e-8,  # 47 nA
    "2 uA": 917969e-12,  # 917.969 nA
    "4 uA": 4.7e-6,  # 4.7 µA
    "8 uA": 9.7e-6,  # 9.7 µA
    "16 uA": 19e-6,  # ~19 µA
    "32 uA": 47e-6,  # 47 µA
    "63 uA": 100e-6,  # 100 µA
    "125 uA": 190e-6,  # 190 µA
    "250 uA": 470e-6,  # 470 µA
    "500 uA": 918e-6,  # 918 µA
    "1 mA": 1.0e-3,  # 1 mA
}

thread_lock = threading.Lock()


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
            color = "orange" if label == "Forward" else "green" if label == "Reverse" else "purple"
            ax.text(mid_time, mid_potential, label, ha="center", color=color, fontsize=9)

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


def create_widgets_cv(parent, columns=2):
    entries = []
    parent.columnconfigure(0, weight=1)
    inputs_frame = ttk.Frame(parent)
    inputs_frame.grid(row=0, column=0, padx=(5, 20), pady=10, sticky="nswe")
    inputs_frame.columnconfigure(0, weight=1)
    # ===== CV SETTINGS =====
    frame1 = ttk.LabelFrame(inputs_frame, text="Cyclic Voltammetry Settings")
    frame1.grid(row=0, column=0, padx=(5, 10), pady=10, sticky="nswe")
    frame1.configure(style="Custom.TLabelframe")
    frame1.columnconfigure(tuple(range(columns * 2)), weight=1)

    total = len(LABELS)
    per_col = (total + columns - 1) // columns

    for col in range(columns):
        start = col * per_col
        end = min(start + per_col, total)
        subset = LABELS[start:end]

        for i, lbl in enumerate(subset):
            row = i
            ttk.Label(frame1, text=lbl, style="Custom.TLabel").grid(row=row, column=col * 2, padx=5, pady=5, sticky="w")

            entry = ttk.Entry(frame1, font=font_entry)
            entry.insert(0, DEFAUL_VALUES_CV[start + i])
            entry.grid(row=row, column=col * 2 + 1, padx=5, pady=5, sticky="nswe")
            entries.append(entry)

    # ===== CURRENT RANGE SELECTOR =====
    frame_selectors = ttk.LabelFrame(inputs_frame, text="Current Range")
    frame_selectors.grid(row=1, column=0, padx=(5, 20), pady=10, sticky="nswe")
    frame_selectors.configure(style="Custom.TLabelframe")

    # NEW: variable compartida para los radio buttons
    current_range_var = ttk.StringVar(value="4.7e-8")  # valor por defecto

    # NEW: creación horizontal de radio buttons
    for col, (text, value) in enumerate(CURRENT_RANGES.items()):
        ttk.Radiobutton(
            frame_selectors,
            text=text,
            value=value,
            variable=current_range_var,
        ).grid(row=0, column=col, padx=5, pady=5, sticky="nswe")
    # --------------------------------------------------------------------------------
    # -----------------------------Motor Settings-------------------------------------
    entries_motor: list = []
    frame_motor_settings = ttk.LabelFrame(inputs_frame, text="Motor Settings")
    frame_motor_settings.grid(row=2, column=0, padx=(5, 20), pady=10, sticky="nswe")
    frame_motor_settings.columnconfigure((0, 1), weight=1)
    # enable motor checkbox
    enable_motor = ttk.BooleanVar(value=False)
    enable_motor_check = ttk.Checkbutton(frame_motor_settings, text="Enable Motor", variable=enable_motor, style="Custom.TCheckbutton")
    enable_motor_check.grid(row=0, column=0, columnspan=2, padx=5, pady=5, sticky="n")
    entries_motor.append(enable_motor)
    ttk.Label(frame_motor_settings, text="Angle (°, max 30):", style="Custom.TLabel").grid(row=0, column=1, padx=5, pady=5, sticky="w")
    svar_angle = ttk.StringVar(value="30")
    angle_entry = ttk.Entry(frame_motor_settings, font=font_entry, textvariable=svar_angle, width=5)
    angle_entry.grid(row=1, column=1, padx=5, pady=5, sticky="w")
    entries_motor.append(svar_angle)

    ttk.Label(frame_motor_settings, text="Speed (%):", style="Custom.TLabel").grid(row=2, column=0, padx=5, pady=5, sticky="w")
    svar_speed = ttk.StringVar(value="10")
    speed_entry = ttk.Entry(frame_motor_settings, font=font_entry, textvariable=svar_speed, width=5)
    speed_entry.grid(row=1, column=2, padx=5, pady=5, sticky="w")
    entries_motor.append(svar_speed)

    return entries, current_range_var, entries_motor


def create_buttons_cv(parent, callbacks):
    # ===== CONTROL BUTTONS =====
    frame_controls = ttk.Frame(parent)
    frame_controls.grid(row=0, column=0, pady=10, sticky="nswe")
    frame_controls.columnconfigure((0, 1, 2, 3), weight=1)

    ttk.Button(
        frame_controls,
        text="Generate CV Profile",
        style="info.TButton",
        command=callbacks.get("callback_generate_profile", ()),
    ).grid(row=0, column=0, pady=5, sticky="n")

    ttk.Button(
        frame_controls,
        text="Show MethodScript",
        style="info.TButton",
        command=callbacks.get("callback_show_script", ()),
    ).grid(row=0, column=1, pady=5, sticky="n")

    ttk.Button(
        frame_controls,
        text="Send Script",
        style="info.TButton",
        command=callbacks.get("callback_send_script", ()),
    ).grid(row=0, column=2, pady=5, sticky="n")
    ttk.Button(
        frame_controls,
        text="Show Inputs",
        style="danger.TButton",
        command=callbacks.get("callback_show_inputs", ()),
    ).grid(row=0, column=3, pady=5, sticky="n")


class CVFrame(ttk.Frame):
    def __init__(self, parent, ip_sender="localhost", callback_get_ip_sender=None):
        ttk.Frame.__init__(self, parent)
        self.parent = parent
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.payload = {}
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
        self.callback_ip = callback_get_ip_sender
        self.thread_motor = None

        # ---------------------------------------

        content_frame = ttk.Frame(self)
        content_frame.grid(row=0, column=0, sticky="nsew")
        content_frame.columnconfigure(0, weight=1)

        callbacks = {
            "callback_generate_profile": self.callback_generate_profile,
            "callback_show_script": self.callback_show_methodscript,
            "callback_send_script": self.callback_send_script,
            "callback_show_inputs": self.show_inputs_frame,
        }
        self.frame_entries = ttk.Frame(content_frame)
        self.frame_entries.grid(row=0, column=0, sticky="nsew")
        self.frame_entries.columnconfigure(0, weight=1)
        self.entries, self.current_range, self.entries_motor = create_widgets_cv(self.frame_entries)

        self.frame_buttons = ttk.Frame(content_frame)
        self.frame_buttons.grid(row=1, column=0, sticky="nsew")
        self.frame_buttons.columnconfigure(0, weight=1)
        create_buttons_cv(self.frame_buttons, callbacks)

        self.frame_plotter = ttk.LabelFrame(self, text="Live Data Plotter")
        self.frame_plotter.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")
        self.frame_plotter.columnconfigure(0, weight=1)
        self.frame_plotter.configure(style="Custom.TLabelframe")
        self.udp_plotter = EventPlotter(
            self.frame_plotter,
            "cv",
            tcp_port=5006,
            ip_sender=ip_sender,
            buffer_size=4096,
            max_points=5000,
            update_interval_ms=80,
            payload=self.payload,
            frames_to_hide=[self.frame_entries],
            on_end_expriment=self.on_end_experiment,
        )
        self.udp_plotter.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        self.frame_plotter.grid_forget()

    def show_inputs_frame(self):
        self.frame_entries.grid(row=0, column=0, sticky="nsew")
        self.frame_plotter.grid_forget()

    def create_payload_cv(self):
        try:
            t_e = float(self.entries[0].get())
            t_e = "" if t_e == 0 else convert_si_integer_full(t_e)
        except Exception:
            t_e = ""
        self.payload = {
            "t_e": t_e,
            "E_b": convert_si_integer_full(self.E_begin),
            "E_1": convert_si_integer_full(self.E_vertex1),
            "E_2": convert_si_integer_full(self.E_vertex2),
            "E_s": convert_si_integer_full(self.E_step),
            "sc_r": convert_si_integer_full(self.scan_rate),
            "n_sc": convert_si_integer_full(self.n_scans),
            "m_b": convert_si_integer_full(self.m_band),
            "min_da": convert_si_integer_full(self.min_da),
            "max_da": convert_si_integer_full(self.max_da),
            "range_ba": convert_si_integer_full(self.range_ba),
            "ba_1": convert_si_integer_full(self.ba1),
            "ba_2": convert_si_integer_full(self.ba2),
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
            self.m_band = float(self.entries[7].get())
            self.min_da = float(self.entries[8].get())
            self.max_da = float(self.entries[9].get())
            self.range_ba = float(self.current_range.get())
            self.ba1 = float(self.current_range.get())
            self.ba2 = float(self.current_range.get())
        except ValueError as e:
            print(f"Error: Invalid input. Please enter valid numbers -> {e}")
            self.t_equilibration = float(DEFAUL_VALUES_CV[0])
            self.E_begin = float(DEFAUL_VALUES_CV[1])
            self.E_vertex1 = float(DEFAUL_VALUES_CV[2])
            self.E_vertex2 = float(DEFAUL_VALUES_CV[3])
            self.E_step = float(DEFAUL_VALUES_CV[4])
            self.scan_rate = float(DEFAUL_VALUES_CV[5])
            self.n_scans = int(DEFAUL_VALUES_CV[6])
            self.m_band = float(DEFAUL_VALUES_CV[7])
            self.min_da = float(DEFAUL_VALUES_CV[8])
            self.max_da = float(DEFAUL_VALUES_CV[9])
            self.range_ba = float(DEFAUL_VALUES_CV[10])
            self.ba1 = float(DEFAUL_VALUES_CV[11])
            self.ba2 = float(DEFAUL_VALUES_CV[12])

    def callback_send_script(self):
        try:
            self.update_data_script()
            self.create_payload_cv()
            ip_sender = self.callback_ip() if self.callback_ip else "localhost"
            self.frame_entries.grid_forget()
            self.udp_plotter.update_val_experiment(x_key="E_V", y_key="I_A", payload=self.payload, ip_sender=ip_sender)
            self.frame_plotter.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")
            enable_motor = self.entries_motor[0].get()
            if enable_motor:
                self.start_spin_motor_angle()
        except ValueError:
            self.show_inputs_frame()
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
        self.update_data_script()
        self.create_payload_cv()
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
        script = construc_nscans_script_cv(
            self.payload.get("t_e", DEFAUL_VALUES_CV[0]),
            self.payload.get("E_b", DEFAUL_VALUES_CV[1]),
            self.payload.get("E_1", DEFAUL_VALUES_CV[2]),
            self.payload.get("E_2", DEFAUL_VALUES_CV[3]),
            self.payload.get("E_s", DEFAUL_VALUES_CV[4]),
            self.payload.get("sc_r", DEFAUL_VALUES_CV[5]),
            self.payload.get("m_b", DEFAUL_VALUES_CV[6]),
            self.payload.get("min_da", DEFAUL_VALUES_CV[7]),
            self.payload.get("max_da", DEFAUL_VALUES_CV[8]),
            self.payload.get("range_ba", DEFAUL_VALUES_CV[9]),
            self.payload.get("ba_1", DEFAUL_VALUES_CV[10]),
            self.payload.get("ba_2", DEFAUL_VALUES_CV[11]),
            self.payload.get("n_sc", DEFAUL_VALUES_CV[12]),
        )
        return script

    def start_spin_motor_angle(self):
        settings: dict = read_settings_from_file()
        max_rpm = settings.get("max_rpm", 700)
        print("Iniciar modo oscilador")
        angle = float(self.entries_motor[1])
        speed_percentage = float(self.entries_motor[2].get())
        print(f"Ángulo: {angle}°, Velocidad: {speed_percentage:2f}%")
        if angle > 45:
            print("El ángulo máximo es 45°")
            return
        with thread_lock:
            if self.thread_motor and self.thread_motor.is_alive():
                print("Ya hay un hilo activo, no se puede iniciar otro.")
                return
            self.stop_event = threading.Event() if self.stop_event is None else self.stop_event
            thread_motor = threading.Thread(
                target=spinMotorAngleDriver,
                args=(angle, speed_percentage * max_rpm / 100, max_rpm, None, True, self.stop_event, None),
            )
            thread_motor.start()
            print("Modo oscilador iniciado")

    def on_end_experiment(self):
        self.stop_event.set()
        if self.thread_motor is None:
            print("No motor thread to stop.")
            return
        self.thread_motor.join()
        self.thread_motor = None
        self.stop_event = None
        print("Experimento finalizado. Motor detenido.")


if __name__ == "__main__":
    app = ttk.Window(themename="flatly")
    app.title("EmStatPico CV Configuration")
    app.geometry("900x700")
    CVFrame(app).pack(fill="both", expand=True)
    app.mainloop()
