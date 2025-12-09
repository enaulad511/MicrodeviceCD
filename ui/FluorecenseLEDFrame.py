
# -*- coding: utf-8 -*-
__author__ = "Edisson A. Naula"
__date__ = "$ 08/10/2025  at 10:50 a.m. $"

import ttkbootstrap as ttk
from ttkbootstrap.scrolled import ScrolledFrame

from templates.constants import font_entry


def create_widgets_fluorescente_input(parent, callbacks: dict):
    entries = []

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
    frame2.grid(row=1, column=0, padx=10, pady=10, sticky="nswe")
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
    ).grid(row=1, column=0, columnspan=2, pady=5, padx=5, sticky="nswe")

    return entries


class ControlFluorescenteFrame(ttk.Frame):
    def __init__(
        self,
        parent,
        led_gpio: int = 25,
        chip: str = "/dev/gpiochip0",
        active_low: bool = False,
    ):
        ttk.Frame.__init__(self, parent)
        self.parent = parent
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        content_frame = ScrolledFrame(self, autohide=True)
        content_frame.grid(row=0, column=0, sticky="nsew")
        content_frame.columnconfigure(0, weight=1)

        # ---- Parámetros GPIO ----
        self.led_gpio = int(led_gpio)
        self.chip = chip
        self.active_low = active_low
        self.pin = None  # se inicializa bajo demanda

        # ---- Estado de tareas programadas ----
        self._on_time_job = None

        callbacks = {
            "callback_on": self.callback_on,
            "callback_off": self.callback_off,
            "callback_on_time": self.callback_on_time,
        }
        self.entries = create_widgets_fluorescente_input(content_frame, callbacks)

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
            # Reasegura modo salida si ya existe
            try:
                self.pin.set_output(initial_high=False)
            except Exception:
                # Si hubo algún problema, re-crea el recurso
                from Drivers.DriverGPIO import GPIOPin
                self.pin = GPIOPin(     # pyrefly: ignore
                    self.led_gpio,
                    chip=self.chip,
                    consumer="fluorescent-ui",
                    active_low=self.active_low,
                )
                self.pin.set_output(initial_high=False)

    def _on_destroy(self, event=None):
        """Apaga y libera recursos al destruir el frame."""
        self._cleanup_jobs()
        try:
            if self.pin is not None:
                self.pin.write(False)
        except Exception:
            pass
        try:
            if self.pin is not None:
                self.pin.close()
        except Exception as e:
            print(f"Error al cerrar el GPIO: {e}")
            
        self.pin = None

    # =================== Callbacks ===================
    def init_GPIO(self):
        """Mantén este método si lo estás llamando desde fuera; usa _ensure_pin internamente."""
        self._cleanup_jobs()
        self._ensure_pin()

    def callback_on(self):
        print("Encender LED Fluorescente")
        self._cleanup_jobs()
        self._ensure_pin()
        self.pin.write(True)        # pyrefly: ignore
        print("Encendido")

    def callback_off(self):
        print("Apagar LED Fluorescente")
        self._cleanup_jobs()
        self._ensure_pin()
        self.pin.write(False)       # pyrefly: ignore
        print("Apagado")

    def callback_on_time(self):
        print("Encender LED Fluorescente por tiempo")
        ms = self._read_int_entry(self.entries[0], default=500)  # default 500 ms
        if ms < 0:
            ms = 0

        self._cleanup_jobs()
        self._ensure_pin()

        # Encender inmediatamente
        self.pin.write(True)        # pyrefly: ignore
        print(f"Encendido temporizado: {ms} ms")

        # Agendar apagado
        self._on_time_job = self.after(ms, self._on_time_finish)        # pyrefly: ignore

    def _on_time_finish(self):
        try:
            if self.pin is not None:
                self.pin.write(False)
        finally:
            self._on_time_job = None
