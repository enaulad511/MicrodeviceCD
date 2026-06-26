# -*- coding: utf-8 -*-
from ttkbootstrap.scrolled import ScrolledFrame

from templates.constants import font_text_combobox

__author__ = "Edisson A. Naula"
__date__ = "$ 28/10/2025 at 10:24 $"

import ttkbootstrap as ttk

from ui.CaFrame import CAFrame
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
        ttk.Label(
            self.content_frame, text="Select Electrochemical Test:", style="Custom.TLabel"
        ).grid(row=0, column=0, padx=10, pady=10, sticky="e")
        self.test_selector = ttk.Combobox(
            self.content_frame,
            values=[
                "Cyclic Voltammetry",
                "Square Wave Voltammetry",
                "Impedance Spectroscopy",
                "Chronoamperometry",
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

        self.current_test_frame: "ttk.Frame | ttk.Label | None" = None  # Track current frame
        # Cache de frames por metodo: se construyen una vez (lazy) y se ocultan con
        # grid_forget en vez de destruirse, para no perder total_data ni el plot al
        # cambiar de metodo. Memoria acotada (~150 MB los 4) -> trivial en la Pi 5.
        self.frame_cache: "dict[str, ttk.Frame | ttk.Label]" = {}
        # Metodo activo: se usa para revertir el combobox si se bloquea el cambio
        # mientras hay una corrida en curso.
        self.current_method: "str | None" = None

    def get_channel(self):
        """Devuelve el canal de electrodo seleccionado (0-7) como int.


        Fuente unica de verdad del canal MCP, independiente del metodo (CV/SQWV).
        Degrada a 0 si la lectura falla.
        """
        try:
            return int(self.channel_selector.get())
        except (ValueError, AttributeError):
            return 0

    def _is_frame_running(self, frame):
        """True si el frame tiene una corrida EmStat en curso (no se debe cambiar)."""
        plotter = getattr(frame, "udp_plotter", None)
        return bool(getattr(plotter, "running", False))

    def _build_test_frame(self, selected_test, ip_sender):
        """Construye el frame del metodo seleccionado (una sola vez, lazy)."""
        match selected_test:
            case "Cyclic Voltammetry":
                return CVFrame(
                    self.test_frame_container,
                    ip_sender=ip_sender,
                    callback_get_ip_sender=self.callback_ip,
                    callback_get_channel=self.get_channel,
                    frame_with_scroll=self.content_frame,
                )
            case "Square Wave Voltammetry":
                return SWVFrame(
                    self.test_frame_container,
                    ip_sender=ip_sender,
                    callback_get_ip_sender=self.callback_ip,
                    callback_get_channel=self.get_channel,
                    frame_with_scroll=self.content_frame,
                )
            case "Impedance Spectroscopy":
                return EISFrame(
                    self.test_frame_container,
                    ip_sender=ip_sender,
                    callback_get_ip_sender=self.callback_ip,
                    callback_get_channel=self.get_channel,
                    frame_with_scroll=self.content_frame,
                )
            case "Chronoamperometry":
                return CAFrame(
                    self.test_frame_container,
                    ip_sender=ip_sender,
                    callback_get_ip_sender=self.callback_ip,
                    callback_get_channel=self.get_channel,
                    frame_with_scroll=self.content_frame,
                )
            case _:
                return ttk.Label(
                    self.test_frame_container, text=f"{selected_test} UI coming soon..."
                )

    def on_test_selected(self, event):
        selected_test = self.test_selector.get()
        if selected_test == self.current_method:
            return
        # No cambiar mientras haya una corrida en curso: dos experimentos sobre la
        # misma cadena EmStat (un solo instrumento) competirian por el hardware.
        # Revertir el combobox al metodo activo y avisar.
        if self.current_test_frame is not None and self._is_frame_running(
            self.current_test_frame
        ):
            if self.current_method is not None:
                self.test_selector.set(self.current_method)
            print("Stop the current run before switching tests.")
            return
        print(f"Selected test: {selected_test}")
        ip_sender = self.callback_ip() if self.callback_ip else "localhost"
        # Ocultar el frame saliente sin destruirlo (conserva total_data y el plot).
        if self.current_test_frame is not None:
            self.current_test_frame.grid_forget()
        # Reusar del cache (lazy) o construir la primera vez.
        frame = self.frame_cache.get(selected_test)
        if frame is None:
            frame = self._build_test_frame(selected_test, ip_sender)
            self.frame_cache[selected_test] = frame
        self.current_test_frame = frame
        self.current_method = selected_test
        self.current_test_frame.grid(row=0, column=0, sticky="nsew", pady=5)


# Example usage
if __name__ == "__main__":
    app = ttk.Window(themename="flatly")
    app.title("Electrochemical Tests")
    app.geometry("900x700")
    ElectrochemicalFrame(app).pack(fill="both", expand=True)
    app.mainloop()
