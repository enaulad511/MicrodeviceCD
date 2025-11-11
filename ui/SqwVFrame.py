# -*- coding: utf-8 -*-
__author__ = "Edisson A. Naula"
__date__ = "$ 11/11/2025 at 15:00 p.m. $"

import ttkbootstrap as ttk
from ttkbootstrap.scrolled import ScrolledFrame
from tkinter.scrolledtext import ScrolledText
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from templates.constants import font_entry  # Ajusta si no tienes este archivo


def create_widgets_swv(parent, callbacks):
    labels = [
        "t equilibration (s):",
        "E begin (V):",
        "E end (V):",
        "E step (V):",
        "Amplitude (V):",
        "Frequency (Hz):"
    ]
    defaults = ["0", "-0.5", "0.5", "0.2", "0.5", "2"]

    frame = ttk.LabelFrame(parent, text="Square Wave Voltammetry Settings")
    frame.grid(row=0, column=0, padx=10, pady=10, sticky="nswe")

    entries = []
    for i, lbl in enumerate(labels):
        ttk.Label(frame, text=lbl).grid(row=i, column=0, padx=5, pady=5, sticky="e")
        entry = ttk.Entry(frame, font=font_entry)
        entry.insert(0, defaults[i])
        entry.grid(row=i, column=1, padx=5, pady=5)
        entries.append(entry)

    # Checkbox para medir i_forward/i_reverse
    measure_var = ttk.BooleanVar(value=False)
    ttk.Checkbutton(frame, text="Measure i forward/reverse", variable=measure_var).grid(
        row=len(labels), column=0, columnspan=2, pady=5
    )

    ttk.Button(frame, text="Generate SWV Profile & Script", style="info.TButton",
               command=callbacks["callback_generate_profile"]).grid(row=len(labels)+1, column=0, columnspan=2, pady=10)

    return entries, measure_var


class SWVFrame(ttk.Frame):
    def __init__(self, parent):
        ttk.Frame.__init__(self, parent)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        content_frame = ScrolledFrame(self, autohide=True)
        content_frame.grid(row=0, column=0, sticky="nsew")
        content_frame.columnconfigure(0, weight=1)

        callbacks = {"callback_generate_profile": self.callback_generate_profile}
        self.entries, self.measure_var = create_widgets_swv(content_frame, callbacks)

        self.profile_frame = ttk.LabelFrame(content_frame, text="SWV Profile Preview")
        self.profile_frame.grid(row=1, column=0, padx=(5, 15), pady=10, sticky="nswe")

        self.script_box = ScrolledText(content_frame, height=15)
        self.script_box.grid(row=2, column=0, padx=(5, 15), pady=10, sticky="nswe")

        self.canvas = None
        self.callback_generate_profile()

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
            segments.append((current_time, current_time + t_equilibration, "Equilibration"))
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
            ax.step(times, potentials, where='post', color='blue', linewidth=2)

            # Annotate segments
            if len(segments) <= 20:
                for s in segments:
                    start_time, end_time, label = s
                    mid_time = (start_time + end_time) / 2
                    mid_potential = (potentials[times.index(start_time)] + potentials[times.index(end_time)]) / 2
                    color = "purple" if label == "Equilibration" else "orange" if label == "Forward" else "green"
                    ax.text(mid_time, mid_potential, label, ha='center', color=color, fontsize=8)

            ax.axhline(e_begin, color='gray', linestyle=':')
            ax.axhline(e_end, color='red', linestyle=':')
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
            script = self.generate_methodscript(
                t_equilibration, e_begin, e_end, e_step, amplitude, freq, self.measure_var.get()
            )
            self.script_box.delete("1.0", "end")
            self.script_box.insert("end", script)

        except ValueError:
            print("Error: Check input values.")

    def generate_methodscript(self, t_equilibration, e_begin, e_end, e_step, amplitude, freq, measure_forward_reverse):
        def to_mV(value):
            return f"{int(value * 1000)}m"

        # Variables
        vars_line = "var i\nvar e"
        if measure_forward_reverse:
            vars_line += "\nvar i_forward\nvar i_reverse"

        # Measurement line
        meas_line = "meas_loop_swv e i"
        if measure_forward_reverse:
            meas_line += " i_forward i_reverse"
        meas_line += f" {to_mV(e_begin)} {to_mV(e_end)} {to_mV(e_step)} {to_mV(amplitude)} {int(freq)}"
        script = """
                {vars_line}
                set_pgstat_chan 1
                set_pgstat_mode 0
                set_pgstat_chan 0
                set_pgstat_mode 2
                set_max_bandwidth 234021m
                set_range_minmax da -600m 600m
                set_range ba 470u
                set_autoranging ba 917969p 470u
                set_e {to_mV(e_begin)}
                cell_on
                wait {int(t_equilibration * 1000)}ms
                {meas_line}
                pck_start
                    pck_add e
                    pck_add i
                """
        if measure_forward_reverse:
            script += "    pck_add i_forward\n    pck_add i_reverse\n"
        script += """  pck_end
                    endloop
                    on_finished:
                    cell_off
                """
        return script.strip()


if __name__ == "__main__":
    app = ttk.Window(themename="flatly")
    app.title("Square Wave Voltammetry")
    app.geometry("900x700")
    SWVFrame(app).pack(fill="both", expand=True)
    app.mainloop()
