# -*- coding: utf-8 -*-

from tkinter import Entry, StringVar
from typing import TYPE_CHECKING

import ttkbootstrap as ttk
from ttkbootstrap.scrolled import ScrolledFrame

from templates.constants import font_entry, led_heatin_pin
from ui.KeyboardFrame import NumericKeyboard

# Solo para el type checker: Drivers.DriverGPIO importa gpiod a nivel de módulo
# y rompería el modo dev en Windows; en ejecución se importa bajo demanda.
if TYPE_CHECKING:
    from Drivers.DriverGPIO import GPIOPin

__author__ = "Edisson A. Naula"
__date__ = "$ 08/10/2025  at 09:32 a.m. $"


def create_widgets_input(parent, callbacks: dict):
    entries: list[Entry | StringVar] = []
    # Control 1: Encender y apagar
    frame1 = ttk.LabelFrame(parent, text="Basic Control")
    frame1.grid(row=0, column=0, padx=(5, 25), pady=10, sticky="nswe")
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
    frame2.grid(row=0, column=1, padx=(2, 20), pady=10, sticky="nswe")
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
    frame3.grid(row=1, column=0, padx=(2, 20), pady=10, sticky="nswe")
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
        width=8,
    )
    pattern_combo.grid(row=0, column=1, padx=5, pady=5, sticky="nswe")
    pattern_combo.current(0)
    entries.append(svar_pattern)  # index 1

    ttk.Label(frame3, text="Cycle duration (ms):", style="Custom.TLabel").grid(
        row=1, column=0, padx=5, pady=5, sticky="nswe"
    )
    up_duration = ttk.Entry(frame3, font=font_entry, width=7)
    up_duration.grid(row=1, column=1, padx=5, pady=5, sticky="nswe")
    entries.append(up_duration)  # index 2

    ttk.Label(frame3, text="Frequency (Hz):", style="Custom.TLabel").grid(
        row=2, column=0, padx=5, pady=5, sticky="w"
    )
    frequency_entry = ttk.Entry(frame3, font=font_entry, width=7)
    frequency_entry.grid(row=2, column=1, padx=5, pady=5, sticky="nswe")
    entries.append(frequency_entry)  # index 3

    ttk.Button(
        frame3,
        text="Play Pattern",
        style="info.TButton",
        command=callbacks.get("callback_pattern", ()),
    ).grid(row=3, column=0, columnspan=2, pady=5, padx=5, sticky="nswe")
    entry_widgets = [duration_entry, up_duration, frequency_entry]
    return entries, entry_widgets


class ControleLEDFrame(ttk.Frame):
    def __init__(
        self,
        parent,
        led_gpio: int = 25,
        chip: str = "/dev/gpiochip0",
        active_low: bool = False,
        lock_tabs_callback=None,
    ):
        ttk.Frame.__init__(self, parent)
        self.parent = parent
        # Bloquea PCR/Electrochemical mientras esta tab deja el LED encendido
        # (solo una cosa a la vez); lo provee MainGUI.
        self.lock_tabs_callback = lock_tabs_callback
        self.led_gpio = led_gpio
        self.chip = chip
        self.active_low = active_low
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        content_frame = ScrolledFrame(self, autohide=True)
        content_frame.grid(row=0, column=0, sticky="nsew")
        content_frame.columnconfigure((0, 1), weight=1)
        # La línea gpiod solo se abre durante cada escritura (ver _set_led), así
        # nunca queda tomada y PCR puede pedirla. _led_on recuerda si esta tab
        # dejó el LED encendido, para apagarlo al cerrar la app.
        self.pin: "GPIOPin | None" = None
        self._led_on = False
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
        self.entries, entry_widgets = create_widgets_input(content_frame, callbacks)
        self.keyboard = NumericKeyboard(self, scroll_host=content_frame)
        self.keyboard.attach(entry_widgets)

        # Limpieza al destruir
        self.bind("<Destroy>", self._on_destroy)

    def init_GPIO(
        self,
    ):
        from Drivers.DriverGPIO import GPIOPin

        if self.pin is None:
            print(f"Creating GPIO pin {led_heatin_pin}")
            self.pin = GPIOPin(  # pyrefly: ignore
                led_heatin_pin,
                chip=self.chip,
                consumer="led-ui",
                active_low=self.active_low,
            )
            # Preconfigura como salida en bajo
            self.pin.set_output(initial_high=False)  # pyrefly: ignore

    # ----------------- Helpers GUI/GPIO -----------------
    def _cleanup_jobs(self):
        """Cancela tareas programadas."""
        try:
            if self._on_time_job is not None:
                self.after_cancel(self._on_time_job)
                self._on_time_job = None  # pyrefly: ignore
        except Exception:
            self._on_time_job = None

        try:
            if self._pattern_job is not None:
                self.after_cancel(self._pattern_job)
                self._pattern_job = None  # pyrefly: ignore
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

    def _release_pin(self):
        """Libera la línea gpiod (el nivel escrito queda en el pin)."""
        if self.pin is None:
            return
        try:
            self.pin.close()  # pyrefly: ignore
        except Exception as e:
            print(f"Error closing heating LED GPIO: {e}")
        self.pin = None

    def _set_led(self, value: bool) -> bool:
        """Abre la línea, escribe y la libera en el acto (mismo patrón que
        FluorecenseLEDFrame), para no dejarla tomada y que PCR pueda pedirla.
        Devuelve False si no se pudo, p. ej. línea ocupada porque PCR corre."""
        try:
            self.init_GPIO()
            self.pin.write(value)  # pyrefly: ignore
            return True
        except Exception as e:
            print(f"Error GPIO heating LED: {e}")
            return False
        finally:
            self._release_pin()

    def _update_lock(self):
        """Tabs de PCR/Electrochemical bloqueadas mientras el LED quede encendido."""
        if self.lock_tabs_callback is not None:
            self.lock_tabs_callback(self._led_on)

    def _on_destroy(self, event=None):
        # Apaga el LED solo si esta tab lo dejó encendido; si no, no toca la
        # línea (podría tenerla PCR) y no hay nada que liberar.
        self._cleanup_jobs()
        if self._led_on:
            self._set_led(False)

    # ----------------- Callbacks públicos -----------------
    def callback_on(self):
        self._cleanup_jobs()
        if self._set_led(True):
            self._led_on = True
            print("LED ON")
        self._update_lock()

    def callback_off(self):
        # Parar cualquier programación y apagar
        self._cleanup_jobs()
        if self._set_led(False):
            self._led_on = False
            print("LED OFF")
        self._update_lock()

    def callback_on_time(self):
        # Lee duración en ms (entries[0])
        ms = self._read_int_entry(self.entries[0], default=2000)  # default 500 ms
        if ms < 0:
            ms = 0
        self._cleanup_jobs()
        if not self._set_led(True):
            self._update_lock()
            return
        self._led_on = True
        print(f"LED ON for {ms} ms")
        self._update_lock()

        # Agenda apagado (la línea queda libre mientras corre el tiempo)
        self._on_time_job = self.after(ms, self._on_time_finish)  # pyrefly: ignore

    def _on_time_finish(self):
        self._on_time_job = None
        if self._set_led(False):
            self._led_on = False
            print("Time finished: LED OFF")
        self._update_lock()

    def callback_pattern(self):
        print("Starting pattern")
