# -*- coding: utf-8 -*-
__author__ = "Edisson A. Naula"
__date__ = "$ 30/10/2025 at 11:30 a.m. $"

import ttkbootstrap as ttk
from ttkbootstrap.scrolled import ScrolledFrame
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from templates.constants import font_entry


def create_widgets_swv(parent, callbacks):
    labels = [
        "E_begin (V):", "E_end (V):", "E_step (V):",
        "Amplitude (V):", "Frequency (Hz):", "t_equilibration (s):"
    ]
    defaults = ["0.1", "0.6", "0.1", "0.2", "4", "1"]
    frame = ttk.LabelFrame(parent, text="Square Wave Voltammetry Configuration")
    frame.grid(row=0, column=0, padx=10, pady=10, sticky="nswe")

    entries = []
    for i, lbl in enumerate(labels):
        ttk.Label(frame, text=lbl).grid(row=i, column=0, padx=5, pady=5, sticky="e")
        entry = ttk.Entry(frame, font=font_entry)
        entry.insert(0, defaults[i])
        entry.grid(row=i, column=1, padx=5, pady=5)
        entries.append(entry)

    ttk.Button(frame, text="Generate SWV Profile", style="info.TButton",
               command=callbacks["callback_generate_profile"]).grid(row=len(labels), column=0, columnspan=2, pady=10)
    return entries


class SWVFrame(ttk.Frame):
    def __init__(self, parent):
        ttk.Frame.__init__(self, parent)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        content_frame = ScrolledFrame(self, autohide=True)
        content_frame.grid(row=0, column=0, sticky="nsew")
        content_frame.columnconfigure(0, weight=1)

        callbacks = {"callback_generate_profile": self.callback_generate_profile}
        self.entries = create_widgets_swv(content_frame, callbacks)

        self.profile_frame = ttk.LabelFrame(content_frame, text="SWV Profile Preview")
        self.profile_frame.grid(row=1, column=0, padx=10, pady=10, sticky="nswe")

        self.canvas = None
        self.callback_generate_profile()

    def callback_generate_profile(self):
        try:
            e_begin = float(self.entries[0].get())
            e_end = float(self.entries[1].get())
            e_step = float(self.entries[2].get())

            amplitude = float(self.entries[3].get())
            freq = float(self.entries[4].get())

            t_equilibration = float(self.entries[5].get())
            t_interval = 1 / (2 * freq)

            times, potentials, segments = [], [], []
            current_time = 0

            # Equilibration segment
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
            for i, s in enumerate(segments):
                start_idx = times.index(s[0])
                end_idx = times.index(s[1])
                color = "purple" if s[2] == "Equilibration" else "orange" if s[2] == "Forward" else "green"
                ax.step(times[start_idx:end_idx+1], potentials[start_idx:end_idx+1], where='post', color=color, linewidth=2)

            # Annotate segments correctly
            if len(segments) <= 20:
                for i, s in enumerate(segments):
                    start_time, end_time, label = s
                    # Find indices for this segment
                    start_idx = times.index(start_time)
                    end_idx = times.index(end_time)
                    mid_time = (start_time + end_time) / 2
                    mid_potential = (potentials[start_idx] + potentials[end_idx]) / 2
                    color = "purple" if label == "Equilibration" else "orange" if label == "Forward" else "green"
                    ax.text(mid_time, mid_potential, label, ha='center', color=color, fontsize=8)

            # Reference lines
            ax.axhline(e_begin, color='gray', linestyle=':')
            ax.axhline(e_end, color='red', linestyle=':')
            ax.set_xlabel("Time (s)")
            ax.set_ylabel("Potential (V)")
            ax.set_title(f"SWV Profile · t_interval = {t_interval:.3f} s")
            ax.grid(True)

            # Update canvas
            if self.canvas:
                self.canvas.get_tk_widget().destroy()
            self.canvas = FigureCanvasTkAgg(fig, master=self.profile_frame)
            self.canvas.draw()
            self.canvas.get_tk_widget().pack(fill="both", expand=True)

        except ValueError:
            print("Error: Check input values.")


# Example usage
if __name__ == "__main__":
    app = ttk.Window(themename="flatly")
    app.title("Square Wave Voltammetry")
    app.geometry("900x600")
    SWVFrame(app).pack(fill="both", expand=True)
    app.mainloop()
