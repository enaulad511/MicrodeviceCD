# -*- coding: utf-8 -*-
from ttkbootstrap.scrolled import ScrolledFrame

from templates.constants import font_text, font_text_combobox

__author__ = "Edisson A. Naula"
__date__ = "$ 28/10/2025 at 10:24 $"

import ttkbootstrap as ttk

from ui.CvFrame import CVFrame
from ui.EisFrame import EISFrame
from ui.SqwVFrame import SWVFrame


class ElectrochemicalFrame(ttk.Frame):
    def __init__(self, parent, callback_get_ip_sender=None):
        ttk.Frame.__init__(self, parent)
        self.parent = parent
        self.callback_ip = callback_get_ip_sender
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        # Main content frame with scroll
        self.content_frame = ScrolledFrame(self, autohide=False)
        self.content_frame.grid(row=0, column=0, sticky="nsew")
        self.content_frame.columnconfigure((0, 1), weight=1)
        self.content_frame.rowconfigure(2, weight=1)

        # set scroll at top
        

        # Combobox for test selection
        ttk.Label(self.content_frame, text="Select Electrochemical Test:", style="Custom.TLabel").grid(
            row=0, column=0, padx=10, pady=10, sticky="e"
        )
        self.test_selector = ttk.Combobox(
            self.content_frame,
            values=[
                "Cyclic Voltammetry",
                "Square Wave Voltammetry",
                "Electrochemical Impedance",
            ],
            state="readonly",
            width=25,
            font=font_text_combobox,
        )
        self.test_selector.grid(row=0, column=1, padx=10, pady=10, sticky="w")
        self.test_selector.bind("<<ComboboxSelected>>", self.on_test_selected)

        # Combobox para el canal de electrodo (MCP23017, 0-7). Obligatorio en v1.6:
        # el firmware rechaza el experimento si "ch" falta o esta fuera de rango.
        ttk.Label(self.content_frame, text="Electrode channel:", style="Custom.TLabel").grid(
            row=1, column=0, padx=10, pady=(0, 10), sticky="e"
        )
        self.channel_selector = ttk.Combobox(
            self.content_frame,
            values=[str(c) for c in range(8)],
            state="readonly",
            width=5,
            font=font_text_combobox,
        )
        self.channel_selector.set("0")
        self.channel_selector.grid(row=1, column=1, padx=10, pady=(0, 10), sticky="w")

        # Frame to hold the selected test UI
        self.test_frame_container = ttk.Frame(self.content_frame)
        self.test_frame_container.grid(row=2, column=0, columnspan=2, sticky="nsew")
        self.test_frame_container.columnconfigure(0, weight=1)
        self.test_frame_container.rowconfigure(0, weight=1)

        self.current_test_frame = None  # Track current frame

    def get_channel(self):
        """Devuelve el canal de electrodo seleccionado (0-7) como int.


        Fuente unica de verdad del canal MCP, independiente del metodo (CV/SQWV).
        Degrada a 0 si la lectura falla.
        """
        try:
            return int(self.channel_selector.get())
        except (ValueError, AttributeError):
            return 0

    def on_test_selected(self, event):
        selected_test = self.test_selector.get()
        # Clear previous frame
        if self.current_test_frame:
            self.current_test_frame.destroy()
        # Load the selected test frame
        print(f"Selected test: {selected_test}")
        ip_sender = self.callback_ip() if self.callback_ip else "localhost"
        match selected_test:
            case "Cyclic Voltammetry":
                self.current_test_frame = CVFrame(
                    self.test_frame_container,
                    ip_sender=ip_sender,
                    callback_get_ip_sender=self.callback_ip,
                    callback_get_channel=self.get_channel,
                    frame_with_scroll=self.content_frame,
                )
            case "Square Wave Voltammetry":
                self.current_test_frame = SWVFrame(
                    self.test_frame_container,
                    ip_sender=ip_sender,
                    callback_get_ip_sender=self.callback_ip,
                    callback_get_channel=self.get_channel,
                    frame_with_scroll=self.content_frame,
                )
            case "Electrochemical Impedance":
                self.current_test_frame = EISFrame(
                    self.test_frame_container,
                    ip_sender=ip_sender,
                    callback_get_ip_sender=self.callback_ip,
                    callback_get_channel=self.get_channel,
                    frame_with_scroll=self.content_frame,
                )
            case _:
                placeholder = ttk.Label(
                    self.test_frame_container, text=f"{selected_test} UI coming soon..."
                )
                # placeholder.grid(row=0, column=0, sticky="nsew")
                self.current_test_frame = placeholder
        self.current_test_frame.grid(row=0, column=0, sticky="nsew", pady=5)


# Example usage
if __name__ == "__main__":
    app = ttk.Window(themename="flatly")
    app.title("Electrochemical Tests")
    app.geometry("900x700")
    ElectrochemicalFrame(app).pack(fill="both", expand=True)
    app.mainloop()
