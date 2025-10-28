# -*- coding: utf-8 -*-
__author__ = "Edisson A. Naula"
__date__ = "$ 28/10/2025 at 10:45 a.m. $"

import ttkbootstrap as ttk
from ttkbootstrap.scrolled import ScrolledFrame
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from templates.constants import font_entry


def create_widgets_cv(parent, callbacks: dict):
    entries = []

    frame1 = ttk.LabelFrame(parent, text="Cyclic Voltammetry Configuration")
    frame1.grid(row=0, column=0, padx=10, pady=10, sticky="nswe")
    frame1.configure(style="Custom.TLabelframe")

    labels = [
        "E_begin (V):",
        "E_vertex1 (V):",
        "E_vertex2 (V):",
        "E_step (V):",
        "Scan Rate (V/s):",
        "Number of Scans:",
        "t_equilibration (s):"
    ]

    default_values = ["0.0", "0.6", "-0.6", "0.2", "0.1", "2", "5"]

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
        text="Generate CV Profile",
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

        self.profile_frame = ttk.LabelFrame(content_frame, text="Profile Preview")
        self.profile_frame.grid(row=1, column=0, padx=10, pady=10, sticky="nswe")
        self.profile_frame.configure(style="Custom.TLabelframe")

        self.canvas = None
        self.callback_generate_profile()

    def callback_generate_profile(self):
        try:
            E_begin = float(self.entries[0].get())
            E_vertex1 = float(self.entries[1].get())
            E_vertex2 = float(self.entries[2].get())
            E_step = float(self.entries[3].get())
            scan_rate = float(self.entries[4].get())
            n_scans = int(self.entries[5].get())
            t_equilibration = float(self.entries[6].get())

            t_interval = E_step / scan_rate

            times = []
            potentials = []
            current_time = 0

            # Equilibration
            times.append(current_time)
            potentials.append(E_begin)
            current_time += t_equilibration
            times.append(current_time)
            potentials.append(E_begin)

            # Segments for annotation
            segments = []

            for _ in range(n_scans):
                # Forward sweep
                start_time = current_time
                E = E_begin
                while E <= E_vertex1:
                    times.append(current_time)
                    potentials.append(E)
                    current_time += t_interval
                    E += E_step
                segments.append((start_time, current_time, "Forward"))

                # Reverse sweep
                start_time = current_time
                while E >= E_vertex2:
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

            fig, ax = plt.subplots(figsize=(7, 4))
            ax.step(times, potentials, where='post', color='blue', linewidth=2)

            # Annotate segments
            for seg in segments:
                start, end, label = seg
                mid_time = (start + end) / 2
                mid_potential = (potentials[int(len(potentials) * mid_time / times[-1])])
                color = "orange" if label == "Forward" else "green" if label == "Reverse" else "purple"
                ax.text(mid_time, mid_potential, label, ha='center', color=color, fontsize=9)

            # Reference lines
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

        except ValueError:
            print("Error: Check input values.")


if __name__ == "__main__":
    app = ttk.Window(themename="flatly")
    app.title("EmStatPico CV Configuration")
    app.geometry("800x600")
    CVFrame(app).pack(fill="both", expand=True)
    app.mainloop()