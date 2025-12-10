# -*- coding: utf-8 -*-

from templates.constants import led_heatin_pin
from tkinter import StringVar
from tkinter import Entry
import ttkbootstrap as ttk
from ttkbootstrap.scrolled import ScrolledFrame
from templates.constants import font_entry

__author__ = "Edisson A. Naula"
__date__ = "$ 08/10/2025  at 09:32 a.m. $"


def create_widgets_input(parent, callbacks: dict):
    entries: list[Entry| StringVar] = []
    # Control 1: Encender y apagar
    frame1 = ttk.LabelFrame(parent, text="Basic Control")
    frame1.grid(row=0, column=0, padx=10, pady=10, sticky="nswe")
    frame1.configure(style="Custom.TLabelframe")
    frame1.columnconfigure((0, 1), weight=1)

    ttk.Button(
        frame1,
        text="On",
        style="info.TButton",
        command=callbacks.get("callback_on", ()),
    ).grid(row=0, column=0, padx=5, pady=5, sticky="nswe")
    ttk.Button(
        frame1,
        text="Off",
        style="info.TButton",
        command=callbacks.get("callback_off", ()),
    ).grid(row=0, column=1, padx=5, pady=5, sticky="nswe")

    # Control 2: Encender por tiempo
    frame2 = ttk.LabelFrame(parent, text="Timed On")
    frame2.grid(row=0, column=1, padx=10, pady=10, sticky="nswe")
    frame2.configure(style="Custom.TLabelframe")
    frame2.columnconfigure((0, 1), weight=1)

    ttk.Label(frame2, text="Duration (ms):", style="Custom.TLabel").grid(
        row=0, column=0, padx=5, pady=5, sticky="e"
    )
    duration_entry = ttk.Entry(frame2, font=font_entry, width=7)
    duration_entry.grid(row=0, column=1, padx=5, pady=5)
    entries.append(duration_entry)  # index 0

    ttk.Button(
        frame2,
        style="info.TButton",
        text="Turn On by Time",
        command=callbacks.get("callback_on_time", ()),
    ).grid(row=1, column=0, columnspan=2, pady=5, padx=5, sticky="nswe")

    # Control 3: Patrón de encendido
    frame3 = ttk.LabelFrame(parent, text="On pattern")
    frame3.grid(row=1, column=0, padx=10, pady=10, sticky="nswe")
    frame3.configure(style="Custom.TLabelframe")
    frame3.columnconfigure((0, 1), weight=1)

    ttk.Label(frame3, text="Patter type:", style="Custom.TLabel").grid(
        row=0, column=0, padx=5, pady=5, sticky="w"
    )
    svar_pattern = ttk.StringVar()
    pattern_combo = ttk.Combobox(
        frame3,
        values=["Square wave", "Staggered", "Ramp"],
        font=font_entry,
        textvariable=svar_pattern,
        width=8
    )
    pattern_combo.grid(row=0, column=1, padx=5, pady=5, sticky="nswe")
    pattern_combo.current(0)
    entries.append(svar_pattern)  # index 1

    ttk.Label(frame3, text="Cycle duration (ms):", style="Custom.TLabel").grid(
        row=1, column=0, padx=5, pady=5, sticky="w"
    )
    up_duration = ttk.Entry(frame3, font=font_entry, width=7)
    up_duration.grid(row=1, column=1, padx=5, pady=5, sticky="w")
    entries.append(up_duration)  # index 2

    ttk.Label(frame3, text="Frequency (Hz):", style="Custom.TLabel").grid(
        row=2, column=0, padx=5, pady=5, sticky="w"
    )
    frequency_entry = ttk.Entry(frame3, font=font_entry, width=7)
    frequency_entry.grid(row=2, column=1, padx=5, pady=5)
    entries.append(frequency_entry)  # index 3

    ttk.Button(
        frame3,
        text="Play Pattern",
        style="info.TButton",
        command=callbacks.get("callback_pattern", ()),
    ).grid(row=3, column=0, columnspan=2, pady=5, padx=5, sticky="nswe")
    return entries


class ControleLEDFrame(ttk.Frame):
    def __init__(
        self,
        parent,
        led_gpio: int = 25,
        chip: str = "/dev/gpiochip0",
        active_low: bool = False,
    ):
        ttk.Frame.__init__(self, parent)
        self.parent = parent
        self.led_gpio = led_gpio
        self.chip = chip
        self.active_low = active_low
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        content_frame = ScrolledFrame(self, autohide=True)
        content_frame.grid(row=0, column=0, sticky="nsew")
        content_frame.columnconfigure((0, 1), weight=1)
        self.pin = None
        # ---- Estado para tareas programadas ----
        self._on_time_job = None
        self._pattern_job = None
        self._running_pattern = False
        self._pattern_state = {}  # dict para guardar variables del patrón

        callbacks = {
            "callback_on": self.callback_on,
            "callback_off": self.callback_off,
            "callback_on_time": self.callback_on_time,
            "callback_pattern": self.callback_pattern,
        }
        self.entries = create_widgets_input(content_frame, callbacks)

        # Limpieza al destruir
        self.bind("<Destroy>", self._on_destroy)

    def init_GPIO(
        self,
    ):
        from Drivers.DriverGPIO import GPIOPin

        if self.pin is not None:
            self._cleanup_jobs()
        else:
            print(f"Creando pin GPIO {led_heatin_pin}")
            self.pin = GPIOPin(     # pyrefly: ignore
                led_heatin_pin,
                chip=self.chip,
                consumer="led-ui",
                active_low=self.active_low,
            )
            # Preconfigura como salida en bajo
            self.pin.set_output(initial_high=False)     # pyrefly: ignore

    # ----------------- Helpers GUI/GPIO -----------------
    def _cleanup_jobs(self):
        """Cancela tareas programadas."""
        try:
            if self._on_time_job is not None:
                self.after_cancel(self._on_time_job)
                self._on_time_job = None        # pyrefly: ignore
        except Exception:
            self._on_time_job = None

        try:
            if self._pattern_job is not None:
                self.after_cancel(self._pattern_job)
                self._pattern_job = None        # pyrefly: ignore
        except Exception:
            self._pattern_job = None

        self._running_pattern = False
        self._pattern_state.clear()

    def _read_int_entry(self, entry, default: int) -> int:
        """Lee entero de un Entry; si falla, devuelve default."""
        try:
            v = int(entry.get())
            return v
        except Exception:
            return default

    def _read_float_entry(self, entry, default: float) -> float:
        """Lee float de un Entry; si falla, devuelve default."""
        try:
            v = float(entry.get())
            return v
        except Exception:
            return default

    def _on_destroy(self, event=None):
        # Apaga el LED y libera recursos
        self._cleanup_jobs()
        try:
            self.pin.write(False)       # pyrefly: ignore
            self.pin.close()        # pyrefly: ignore
        except Exception as e:
            print(f"Error al cerrar el GPIO heating led: {e}")        

    # ----------------- Callbacks públicos -----------------
    def callback_on(self):
        self.init_GPIO()
        self._cleanup_jobs()
        self.pin.write(True)        # pyrefly: ignore
        print("Encender LED")

    def callback_off(self):
        if self.pin is None:
            print("No se ha inicializado el GPIO")
            return
        # Parar cualquier programación y apagar
        self._cleanup_jobs()
        self.pin.write(False)
        print("Apagar LED")
        self.pin.close()       # pyrefly: ignore
        self.pin = None

    def callback_on_time(self):
        self.init_GPIO()
        # Lee duración en ms (entries[0])
        ms = self._read_int_entry(self.entries[0], default=2000)  # default 500 ms
        if ms < 0:
            ms = 0
        self._cleanup_jobs()
        self.pin.write(True)        # pyrefly: ignore
        print(f"Encender LED por tiempo: {ms} ms")

        # Agenda apagado
        self._on_time_job = self.after(ms, self._on_time_finish)        # pyrefly: ignore

    def _on_time_finish(self):
        self.pin.write(False)       # pyrefly: ignore
        self._on_time_job = None
        print("Tiempo finalizado: LED apagado")
        self.pin.close()       # pyrefly: ignore
        self.pin = None

    def callback_pattern(self):
        print("Iniciando patrón")
