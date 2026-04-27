# -*- coding: utf-8 -*-
from Drivers.EmstatUtils import construc_individual_script_sqwv
from templates.utils import convert_si_integer_full
from ui.EventEmstatFrame import EventPlotter

__author__ = "Edisson A. Naula"
__date__ = "$ 11/11/2025 at 15:00 p.m. $"

import ttkbootstrap as ttk
from tkinter.scrolledtext import ScrolledText
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from templates.constants import font_entry  # Ajusta si no tienes este archivo

LABELS = [
    "t equilibration (s):",
    "E begin (V):",
    "E end (V):",
    "E step (V):",
    "Amplitude (V):",
    "Frequency (Hz):",
    "Max bandwidth (Hz):",
    "Min DA (V):",
    "Max DA (V):",
    # "Range BA:",
    # "Auto BA1:",
    # "Auto BA2:",
]
DEFAULT = [
    "0",
    "-0.5",
    "0.5",
    "0.01",
    "0.1",
    "20",
    "234021e-3",
    "-0.6",
    "0.6",
    "47e-9",
    "47e-9",
    "47e-9",
    "47e-9",
]
LABELS_PRE = {
    "E condition": "0",
    "t condition": "0",
    "E deposition": "0",
    "t deposition": "0",
}

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


def create_widgets_swv(parent, callbacks, n_cols=2):
    frame = ttk.LabelFrame(parent, text="Square Wave Voltammetry Settings")
    frame.grid(row=0, column=0, padx=10, pady=10, sticky="nswe")
    frame.columnconfigure(0, weight=1)
    frame.configure(style="Custom.TLabelframe")
    entries_pre = []
    frame_pre = ttk.LabelFrame(frame, text="Pre-treatment")
    frame_pre.grid(row=0, column=0, padx=10, pady=10, sticky="nswe")
    frame_pre.columnconfigure(tuple(range(4)), weight=1)
    frame_pre.configure(style="Custom.TLabelframe")
    for i, (lbl, val) in enumerate(LABELS_PRE.items()):
        row = i // 2
        col = i % 2
        ttk.Label(frame_pre, text=lbl).grid(row=row, column=col * 2, padx=5, pady=5)
        entry = ttk.Entry(frame_pre, font=font_entry)
        entry.insert(0, val)
        entry.grid(row=row, column=col * 2 + 1, padx=5, pady=5, sticky="we")
        entries_pre.append(entry)

    frame_entries = ttk.LabelFrame(frame, text="Parameters")
    frame_entries.grid(row=1, column=0, padx=10, pady=10, sticky="nswe")
    frame_entries.columnconfigure(tuple(range(n_cols * 2)), weight=1)
    frame_entries.configure(style="Custom.TLabelframe")
    entries = []
    for i, lbl in enumerate(LABELS):
        col = i % n_cols
        row = i // n_cols
        # cada parámetro usa 2 columnas reales
        base_col = col * 2
        ttk.Label(frame_entries, text=lbl).grid(
            row=row, column=base_col, padx=5, pady=5, sticky="e"
        )
        entry = ttk.Entry(frame_entries, font=font_entry)
        entry.insert(0, DEFAULT[i])
        entry.grid(row=row, column=base_col + 1, padx=5, pady=5, sticky="we")

        entries.append(entry)
    # hacer que las columnas de Entry se expandan
    for c in range(n_cols * 2):
        frame_entries.columnconfigure(c, weight=1)

    # Checkbox para medir i_forward/i_reverse
    measure_var = ttk.BooleanVar(value=False)
    ttk.Checkbutton(
        frame_entries, text="Measure i forward/reverse", variable=measure_var
    ).grid(row=len(LABELS), column=0, columnspan=2, pady=5)
    # ===== CURRENT RANGE SELECTOR =====
    frame_selectors = ttk.LabelFrame(frame, text="Current Range")
    frame_selectors.grid(row=2, column=0, padx=(5, 20), pady=10, sticky="nswe")
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
    frame_selectors.columnconfigure(tuple(range(len(CURRENT_RANGES))), weight=1)

    return entries, measure_var, current_range_var, entries_pre

def create_buttons_sqwv(parent, callbacks):
    # ===== CONTROL BUTTONS =====
    frame_buttons = ttk.LabelFrame(parent, text="Actions")
    frame_buttons.grid(row=1, column=0, pady=10, sticky="nswe")
    frame_buttons.columnconfigure((0, 1, 2), weight=1)
    frame_buttons.configure(style="Custom.TLabelframe")
    ttk.Button(
        frame_buttons,
        text="Generate Profile & Script",
        style="info.TButton",
        command=callbacks["callback_generate_profile"],
    ).grid(row=0, column=0, pady=10, sticky="n")
    ttk.Button(
        frame_buttons,
        text="Send Script",
        style="info.TButton",
        command=callbacks["callback_send"],
    ).grid(row=0, column=1, pady=10, sticky="n")
    ttk.Button(
        frame_buttons,
        text="Show Inputs",
        style="danger.TButton",
        command=callbacks["callback_show_inputs"],
    ).grid(row=0, column=2, pady=10, sticky="n")
    

class SWVFrame(ttk.Frame):
    def __init__(self, parent, ip_sender="localhost", callback_get_ip_sender=None):
        ttk.Frame.__init__(self, parent)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.callback_ip = callback_get_ip_sender

        content_frame = ttk.Frame(self)
        content_frame.grid(row=0, column=0, sticky="nsew")
        content_frame.columnconfigure(0, weight=1)
        
        self.frame_entries = ttk.Frame(content_frame)
        self.frame_entries.grid(row=0, column=0, sticky="nsew")
        self.frame_entries.columnconfigure(0, weight=1)
        callbacks = {
            "callback_generate_profile": self.callback_generate_profile,
            "callback_send": self.send_script,
            "callback_show_inputs": self.show_inputs_frame,
        }
        self.entries, self.measure_var, self.current_range, self.entries_pre = (
            create_widgets_swv(self.frame_entries, callbacks)
        )
        self.frame_buttons = ttk.Frame(content_frame)
        self.frame_buttons.grid(row=1, column=0, sticky="nsew")
        self.frame_buttons.columnconfigure(0, weight=1)
        create_buttons_sqwv(self.frame_buttons, callbacks)
        
        self.profile_frame = ttk.LabelFrame(content_frame, text="SWV Profile Preview")
        self.profile_frame.grid(row=2, column=0, padx=(5, 15), pady=10, sticky="nswe")
        self.profile_frame.configure(style="Custom.TLabelframe")
        self.profile_frame.grid_forget()

        self.script_box = ScrolledText(content_frame, height=15)
        self.script_box.grid(row=3, column=0, padx=(5, 15), pady=10, sticky="nswe")
        self.script_box.grid_forget()

        self.canvas = None
        self.frame_plotter = ttk.LabelFrame(self, text="Live Data Plotter")
        self.frame_plotter.grid(row=4, column=0, padx=10, pady=10, sticky="nsew")
        self.frame_plotter.columnconfigure(0, weight=1)
        self.frame_plotter.configure(style="Custom.TLabelframe")
        self.generate_payload()
        self.callback_generate_profile()
        self.udp_plotter = EventPlotter(
            self.frame_plotter,
            "sqwv",
            tcp_port=5006,
            ip_sender=ip_sender,
            buffer_size=4096,
            max_points=5000,
            update_interval_ms=80,
            payload=self.payload,
        )
        self.udp_plotter.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        self.frame_plotter.grid_forget()

    def show_inputs_frame(self):
        self.frame_entries.grid(row=0, column=0, sticky="nsew")
        self.frame_plotter.grid_forget()

    def callback_generate_profile(self):
        try:
            t_equilibration = float(self.entries[0].get())
            e_begin = float(self.entries[1].get())
            e_end = float(self.entries[2].get())
            e_step = float(self.entries[3].get())
            amplitude = float(self.entries[4].get())
            freq = float(self.entries[5].get())

            t_interval = 1 / (2 * freq)

            times, potentials, segments = [], [], []
            current_time = 0

            # Equilibration
            times += [current_time, current_time + t_equilibration]
            potentials += [e_begin, e_begin]
            segments.append(
                (current_time, current_time + t_equilibration, "Equilibration")
            )
            current_time += t_equilibration

            # Generate SWV pulses
            e_i = e_begin
            while e_i <= e_end:
                # Forward pulse
                start = current_time
                times.append(current_time)
                potentials.append(e_i + amplitude)
                current_time += t_interval
                times.append(current_time)
                potentials.append(e_i + amplitude)
                segments.append((start, current_time, "Forward"))

                # Reverse pulse
                start = current_time
                times.append(current_time)
                potentials.append(e_i - amplitude)
                current_time += t_interval
                times.append(current_time)
                potentials.append(e_i - amplitude)
                segments.append((start, current_time, "Reverse"))
                e_i += e_step

            # Plot
            fig, ax = plt.subplots(figsize=(7, 4))
            ax.step(times, potentials, where="post", color="blue", linewidth=2)

            # Annotate segments
            if len(segments) <= 20:
                for s in segments:
                    start_time, end_time, label = s
                    mid_time = (start_time + end_time) / 2
                    mid_potential = (
                        potentials[times.index(start_time)]
                        + potentials[times.index(end_time)]
                    ) / 2
                    color = (
                        "purple"
                        if label == "Equilibration"
                        else "orange"
                        if label == "Forward"
                        else "green"
                    )
                    ax.text(
                        mid_time,
                        mid_potential,
                        label,
                        ha="center",
                        color=color,
                        fontsize=8,
                    )

            ax.axhline(e_begin, color="gray", linestyle=":")
            ax.axhline(e_end, color="red", linestyle=":")
            ax.set_xlabel("Time (s)")
            ax.set_ylabel("Potential (V)")
            ax.set_title(f"SWV Profile · t_interval = {t_interval:.3f} s")
            ax.grid(True)

            if self.canvas:
                self.canvas.get_tk_widget().destroy()
            self.canvas = FigureCanvasTkAgg(fig, master=self.profile_frame)
            self.canvas.draw()
            self.canvas.get_tk_widget().pack(fill="both", expand=True)

            # Generate MethodSCRIPT
            script = self.generate_methodscript()
            self.script_box.delete("1.0", "end")
            self.script_box.insert("end", script)
            self.profile_frame.grid(
                row=2, column=0, padx=(5, 15), pady=10, sticky="nswe"
            )
            self.script_box.grid(row=3, column=0, padx=(5, 15), pady=10, sticky="nswe")
            self.frame_plotter.grid_forget()
        except ValueError:
            print("Error: Check input values.")

    def generate_payload(self):
        try:
            t_e = float(self.entries[0].get())
            t_e = "" if t_e == 0 else convert_si_integer_full(t_e)
            t_con = float(self.entries_pre[1].get())
            t_con = "" if t_con == 0 else convert_si_integer_full(t_con)
            t_dep = float(self.entries_pre[3].get())
            t_dep = "" if t_dep == 0 else convert_si_integer_full(t_dep)
        except Exception:
            t_e = ""
            t_con = ""
            t_dep = ""
        self.payload = {
            "t_e": t_e,
            "E_b": convert_si_integer_full(float(self.entries[1].get())),
            "E_e": convert_si_integer_full(float(self.entries[2].get())),
            "E_s": convert_si_integer_full(float(self.entries[3].get())),
            "Amp": convert_si_integer_full(float(self.entries[4].get())),
            "Freq": convert_si_integer_full(float(self.entries[5].get())),
            "m_b": convert_si_integer_full(float(self.entries[6].get())),
            "min_da": convert_si_integer_full(float(self.entries[7].get())),
            "max_da": convert_si_integer_full(float(self.entries[8].get())),
            "range_ba": convert_si_integer_full(float(self.current_range.get())),
            "ba_1": convert_si_integer_full(float(self.current_range.get())),
            "ba_2": convert_si_integer_full(float(self.current_range.get())),
            "E_con": convert_si_integer_full(float(self.entries_pre[0].get())),
            "t_con": t_con,
            "E_dep": convert_si_integer_full(float(self.entries_pre[2].get())),
            "t_dep": t_dep,
            "method": "sqwv",
        }

    def generate_methodscript(self):
        script = construc_individual_script_sqwv(
            self.payload.get("t_e", DEFAULT[0]),
            self.payload.get("E_b", DEFAULT[1]),
            self.payload.get("E_e", DEFAULT[2]),
            self.payload.get("E_s", DEFAULT[3]),
            self.payload.get("Amp", DEFAULT[4]),
            self.payload.get("Freq", DEFAULT[5]),
            self.payload.get("m_b", DEFAULT[6]),
            self.payload.get("min_da", DEFAULT[7]),
            self.payload.get("max_da", DEFAULT[8]),
            self.payload.get("range_ba", DEFAULT[9]),
            self.payload.get("ba_1", DEFAULT[10]),
            self.payload.get("ba_2", DEFAULT[11]),
            self.payload.get("E_con", LABELS_PRE["E condition"]),
            self.payload.get("t_con", LABELS_PRE["t condition"]),
            self.payload.get("E_dep", LABELS_PRE["E deposition"]),
            self.payload.get("t_dep", LABELS_PRE["t deposition"]),
        )
        return script.strip()

    def send_script(self):
        self.frame_entries.grid_forget()
        self.generate_payload()
        ip_sender = self.callback_ip() if self.callback_ip else "localhost"
        self.udp_plotter.update_val_experiment(
            x_key="E_V",
            y_key="I_A",
            payload=self.payload,
            ip_sender=ip_sender,
        )
        self.frame_plotter.grid(row=4, column=0, padx=10, pady=10, sticky="nsew")
        self.profile_frame.grid_forget()
        self.script_box.grid_forget()


if __name__ == "__main__":
    app = ttk.Window(themename="flatly")
    app.title("Square Wave Voltammetry")
    app.geometry("900x700")
    SWVFrame(app).pack(fill="both", expand=True)
    app.mainloop()
