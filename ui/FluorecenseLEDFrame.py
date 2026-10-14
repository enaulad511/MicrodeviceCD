
# -*- coding: utf-8 -*-
__author__ = "Edisson A. Naula"
__date__ = "$ 08/10/2025  at 10:50 a.m. $"

from typing import TYPE_CHECKING

import ttkbootstrap as ttk
from ttkbootstrap.scrolled import ScrolledFrame

from templates.constants import font_entry
from ui.KeyboardFrame import NumericKeyboard

# Solo para el type checker: Drivers.DriverGPIO importa gpiod a nivel de módulo
# y rompería el modo dev en Windows; en ejecución se importa bajo demanda.
if TYPE_CHECKING:
    from Drivers.DriverGPIO import GPIOPin


def create_widgets_fluorescente_input(parent, callbacks: dict):
    entries = []

    # Control 1: Encender y apagar
    frame1 = ttk.LabelFrame(parent, text="Basic Control")
    frame1.grid(row=0, column=0, padx=(2, 20), pady=10, sticky="nswe")
    frame1.configure(style="Custom.TLabelframe")
    frame1.columnconfigure((0, 1), weight=1)

    ttk.Button(
        frame1,
        text="On",
        style="info.TButton",
        command=callbacks.get("callback_on", ()),
    ).grid(row=0, column=0, padx=5, pady=5, sticky="n")
    ttk.Button(
        frame1,
        text="Off",
        style="info.TButton",
        command=callbacks.get("callback_off", ()),
    ).grid(row=0, column=1, padx=5, pady=5, sticky="n")

    # Control 2: Encender por tiempo
    frame2 = ttk.LabelFrame(parent, text="Timed On")
    frame2.grid(row=1, column=0, padx=(2, 20), pady=10, sticky="nswe")
    frame2.configure(style="Custom.TLabelframe")
    frame2.columnconfigure((0, 1), weight=1)

    ttk.Label(frame2, text="Duration (ms):", style="Custom.TLabel").grid(
        row=0, column=0, padx=5, pady=5, sticky="e"
    )
    duration_entry = ttk.Entry(frame2, font=font_entry)
    duration_entry.grid(row=0, column=1, padx=5, pady=5)
    entries.append(duration_entry)  # index 0

    ttk.Button(
        frame2,
        style="info.TButton",
        text="Turn On by Time",
        command=callbacks.get("callback_on_time", ()),
    ).grid(row=1, column=0, columnspan=2, pady=5, padx=5, sticky="n")

    entry_widgets = [duration_entry]
    return entries, entry_widgets


class ControlFluorescenteFrame(ttk.Frame):
    def __init__(
        self,
        parent,
        led_gpio: int = 24,
        chip: str = "/dev/gpiochip0",
        active_low: bool = False,
        lock_tabs_callback=None,
    ):
        ttk.Frame.__init__(self, parent)
        self.parent = parent
        # Bloquea PCR/Electrochemical mientras esta tab deja el LED encendido
        # (solo una cosa a la vez); lo provee MainGUI.
        self.lock_tabs_callback = lock_tabs_callback
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        content_frame = ScrolledFrame(self, autohide=True)
        content_frame.grid(row=0, column=0, sticky="nsew")
        content_frame.columnconfigure(0, weight=1)

        # ---- Parámetros GPIO ----
        self.led_gpio = int(led_gpio)
        self.chip = chip
        self.active_low = active_low
        # La línea gpiod solo se abre durante cada escritura (ver _set_led), así
        # nunca queda tomada y PCR puede pedirla. _led_on recuerda si esta tab
        # dejó el LED encendido, para apagarlo al cerrar la app.
        self.pin: "GPIOPin | None" = None
        self._led_on = False

        # ---- Estado de tareas programadas ----
        self._on_time_job = None

        callbacks = {
            "callback_on": self.callback_on,
            "callback_off": self.callback_off,
            "callback_on_time": self.callback_on_time,
        }
        self.entries, entry_widgets = create_widgets_fluorescente_input(content_frame, callbacks)
        self.keyboard = NumericKeyboard(self, scroll_host=content_frame)
        self.keyboard.attach(entry_widgets)

        # Limpieza al destruir el frame
        self.bind("<Destroy>", self._on_destroy)

    # =================== Helpers ===================
    def _cleanup_jobs(self):
        """Cancela tareas programadas (encendido por tiempo)."""
        try:
            if self._on_time_job is not None:
                self.after_cancel(self._on_time_job)
                self._on_time_job = None        # pyrefly: ignore
        except Exception:
            self._on_time_job = None

    def _read_int_entry(self, entry, default: int) -> int:
        """Lee un int desde Entry; si algo falla, devuelve default."""
        try:
            v = int(entry.get())
            return v
        except Exception:
            return default

    def _ensure_pin(self):
        """Crea el GPIOPin si no existe y lo configura como salida en bajo."""
        if self.pin is None:
            # Importa aquí para evitar dependencias circulares al cargar módulos
            from Drivers.DriverGPIO import GPIOPin
            self.pin = GPIOPin(     # pyrefly: ignore
                self.led_gpio,
                chip=self.chip,
                consumer="fluorescent-ui",
                active_low=self.active_low,
            )
            self.pin.set_output(initial_high=False)     # pyrefly: ignore
        else:
            print(f"Pin {self.led_gpio} already exists.")

    def _release_pin(self):
        """Libera la línea gpiod (el nivel escrito queda en el pin)."""
        if self.pin is None:
            return
        try:
            self.pin.close()        # pyrefly: ignore
        except Exception as e:
            print(f"Error closing GPIO: {e}")
        self.pin = None

    def _set_led(self, value: bool) -> bool:
        """Abre la línea, escribe y la libera en el acto, para no dejarla tomada
        y que PCR pueda pedirla. Devuelve False si no se pudo, p. ej. línea
        ocupada porque PCR corre."""
        try:
            self._ensure_pin()
            self.pin.write(value)       # pyrefly: ignore
            return True
        except Exception as e:
            print(f"Error GPIO fluorescent LED: {e}")
            return False
        finally:
            self._release_pin()

    def _update_lock(self):
        """Tabs de PCR/Electrochemical bloqueadas mientras el LED quede encendido."""
        if self.lock_tabs_callback is not None:
            self.lock_tabs_callback(self._led_on)

    def _on_destroy(self, event=None):
        """Apaga el LED al destruir el frame, solo si esta tab lo dejó encendido;
        si no, no toca la línea (podría tenerla PCR)."""
        self._cleanup_jobs()
        if self._led_on:
            self._set_led(False)

    # =================== Callbacks ===================
    def callback_on(self):
        print("Fluorescent LED ON")
        self._cleanup_jobs()
        if self._set_led(True):
            self._led_on = True
            print("ON")
        self._update_lock()

    def callback_off(self):
        print("Fluorescent LED OFF")
        self._cleanup_jobs()
        if self._set_led(False):
            self._led_on = False
            print("OFF")
        self._update_lock()

    def callback_on_time(self):
        print("Fluorescent LED timed ON")
        ms = self._read_int_entry(self.entries[0], default=500)  # default 500 ms
        if ms < 0:
            ms = 0

        self._cleanup_jobs()

        # Encender inmediatamente (la línea queda libre mientras corre el tiempo)
        if not self._set_led(True):
            self._update_lock()
            return
        self._led_on = True
        print(f"Timed ON: {ms} ms")
        self._update_lock()

        # Agendar apagado
        self._on_time_job = self.after(ms, self._on_time_finish)        # pyrefly: ignore

    def _on_time_finish(self):
        self._on_time_job = None
        if self._set_led(False):
            self._led_on = False
            print("Timed OFF")
        self._update_lock()
