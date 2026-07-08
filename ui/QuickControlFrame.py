# -*- coding: utf-8 -*-
"""Tab 'Quick Control': vista unificada del control manual.

Reúne en una sola página lo esencial de las demás tabs del Manual Control:
- Motor del disco: giro continuo a n RPM u oscilador de ángulo (continuo hasta
  Stop). Reusa el singleton global de ui.DiscFrame (drv/thread_motor/thread_lock)
  para que nunca haya dos instancias abriendo /dev/ttyAMA0.
- LEDs de calentamiento (GPIO 25) y fluorescencia (GPIO 24) con toggles
  round-toggle. La línea GPIO se mantiene abierta mientras el toggle está ON
  (el bloqueo de tabs evita el 'line busy' con las tabs viejas).
- Lecturas de temperatura (UDP 5005, filtro de 4 muestras) o fluorescencia
  (ADS1115 canal 0) — una señal a la vez por ahora — con plot, retención de
  corridas (Keep data) y guardado a CSV con metadata de actuadores en el nombre.

Mientras haya CUALQUIER actuador o lectura activa se bloquean las demás tabs
(ambos notebooks) vía lock_tabs_callback; se desbloquean solas al quedar todo
apagado/detenido. Ver docs/quick_control.md.
"""

import os
import threading
import time
from tkinter import filedialog
from typing import Any, Optional

import matplotlib.pyplot as plt
import ttkbootstrap as ttk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from ttkbootstrap.scrolled import ScrolledFrame

from Drivers.ClientUDP import UdpClient
from templates.constants import (
    chip_rasp,
    font_entry,
    led_fluorescence_pin,
    led_heatin_pin,
    secrets,
    serial_port_encoder,
)
from templates.utils import (
    read_settings_from_file,
    read_temp_source,
    temp_source_index,
    temp_source_key,
    temp_source_label,
    temp_source_labels,
    write_temp_source,
)
from ui.KeyboardFrame import NumericKeyboard

__author__ = "Edisson A. Naula"
__date__ = "$ 10/06/2026 at 10:00 a.m. $"


class QuickControlFrame(ttk.Frame):
    """Frame unificado de control manual (motor + LEDs + lecturas)."""

    def __init__(self, parent, ads_reader=None, lock_tabs_callback=None):
        super().__init__(parent)
        self.parent = parent
        self.ads: Any = ads_reader
        self.lock_tabs_callback = lock_tabs_callback
        self.is_dev = secrets.get("environment", "") == "dev"

        # ---- Estado motor (el hardware vive en ui.DiscFrame: drv/thread_motor) ----
        self.motor_running = False
        self.motor_stopping = False
        self.motor_stop_event: Optional[threading.Event] = None

        # ---- Estado LEDs: línea abierta mientras el toggle está ON ----
        self.led_pins: dict[str, Any] = {"heat": None, "fluor": None}
        self.led_heat_var = ttk.BooleanVar(value=False)
        self.led_fluor_var = ttk.BooleanVar(value=False)

        # ---- Estado lecturas ----
        self.reading_running = False
        self.reading_signal: Optional[str] = None  # "temp" | "fluor" (corrida en curso)
        self.runs: list[dict] = []  # [{"signal", "t", "v", "run", "meta"}]
        self.run_index = 0
        self.start_time = 0.0
        self.udp_client: Optional[UdpClient] = None
        self.temps_filter = [20.0, 20.0, 20.0, 20.0]
        self.latest_temp = 20.0
        # Últimas tres temperaturas del disco (IR amb, IR obj, termocupla) + fuente
        # elegida; _thermocouple_reader usa temp_source_idx, sostiene el último valor
        # y avisa (temp_source_bad) cuando el sensor elegido viene ausente.
        self.latest_temps = [20.0, 20.0, 20.0]
        self._field_ok = [True, True, True]
        self.temp_source = read_temp_source()
        self.temp_source_idx = temp_source_index(self.temp_source)
        self.temp_source_bad = False
        self.sig_temp_var = ttk.BooleanVar(value=False)
        self.sig_fluor_var = ttk.BooleanVar(value=False)
        self.keep_data_var = ttk.BooleanVar(value=False)

        # ---------------- Layout ----------------
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        content = ScrolledFrame(self, autohide=True)
        content.grid(row=0, column=0, sticky="nsew")
        content.columnconfigure((0, 1), weight=1)

        # Aviso de bloqueo de tabs (vacío cuando no hay nada activo)
        self.lbl_lock = ttk.Label(content, text="", style="Custom.TLabel", anchor="w")
        self.lbl_lock.grid(row=0, column=0, columnspan=2, padx=10, pady=(6, 0), sticky="we")

        entry_widgets = []
        self._build_motor_section(content, entry_widgets)
        self._build_led_section(content)
        self._build_reading_section(content, entry_widgets)
        self._build_plot_section(content)

        self.lbl_status = ttk.Label(content, text="Ready.", style="Custom.TLabel", anchor="w")
        self.lbl_status.grid(row=4, column=0, columnspan=2, padx=10, pady=(0, 6), sticky="we")

        self.keyboard = NumericKeyboard(self, scroll_host=content)
        self.keyboard.attach(entry_widgets)

        if self.is_dev:
            self._apply_dev_mode()

        self.bind("<Destroy>", self._on_destroy)

    # ---------------- Construcción de secciones ----------------

    def _build_motor_section(self, parent, entry_widgets):
        frame = ttk.LabelFrame(parent, text="Disc motor")
        frame.grid(row=1, column=0, padx=10, pady=6, sticky="nswe")
        frame.configure(style="Custom.TLabelframe")
        frame.columnconfigure((0, 1, 2, 3), weight=1)

        ttk.Label(frame, text="Mode:", style="Custom.TLabel").grid(
            row=0, column=0, padx=5, pady=5, sticky="w"
        )
        self.motor_mode_var = ttk.StringVar(value="Continuous")
        self.cmb_motor_mode = ttk.Combobox(
            frame,
            textvariable=self.motor_mode_var,
            values=["Continuous", "Oscillator"],
            state="readonly",
            font=font_entry,
            width=12,
        )
        self.cmb_motor_mode.grid(row=0, column=1, padx=5, pady=5, sticky="w")
        self.cmb_motor_mode.bind("<<ComboboxSelected>>", lambda e: self._on_motor_mode_changed())

        # Continuo: dirección + RPM
        ttk.Label(frame, text="Direction:", style="Custom.TLabel").grid(
            row=1, column=0, padx=5, pady=5, sticky="w"
        )
        self.motor_dir_var = ttk.StringVar(value="CW")
        self.cmb_motor_dir = ttk.Combobox(
            frame,
            textvariable=self.motor_dir_var,
            values=["CW", "CCW"],
            state="readonly",
            font=font_entry,
            width=5,
        )
        self.cmb_motor_dir.grid(row=1, column=1, padx=5, pady=5, sticky="w")

        ttk.Label(frame, text="RPM:", style="Custom.TLabel").grid(
            row=1, column=2, padx=5, pady=5, sticky="w"
        )
        self.entry_rpm = ttk.Entry(frame, font=font_entry, width=6)
        self.entry_rpm.insert(0, "700")
        self.entry_rpm.grid(row=1, column=3, padx=5, pady=5, sticky="w")
        entry_widgets.append(self.entry_rpm)

        # Oscilador: ángulo + velocidad %
        ttk.Label(frame, text="Angle (°, max 45):", style="Custom.TLabel").grid(
            row=2, column=0, padx=5, pady=5, sticky="w"
        )
        self.entry_angle = ttk.Entry(frame, font=font_entry, width=6)
        self.entry_angle.insert(0, "30")
        self.entry_angle.grid(row=2, column=1, padx=5, pady=5, sticky="w")
        entry_widgets.append(self.entry_angle)

        ttk.Label(frame, text="Speed (%):", style="Custom.TLabel").grid(
            row=2, column=2, padx=5, pady=5, sticky="w"
        )
        self.entry_speed = ttk.Entry(frame, font=font_entry, width=6)
        self.entry_speed.insert(0, "10")
        self.entry_speed.grid(row=2, column=3, padx=5, pady=5, sticky="w")
        entry_widgets.append(self.entry_speed)

        self.btn_motor_start = ttk.Button(
            frame, text="▶ Start", style="info.TButton", command=self.callback_motor_start
        )
        self.btn_motor_start.grid(row=3, column=0, columnspan=2, padx=5, pady=5, sticky="we")
        self.btn_motor_stop = ttk.Button(
            frame,
            text="⏹ Stop",
            style="danger.TButton",
            command=self.callback_motor_stop,
            state=ttk.DISABLED,
        )
        self.btn_motor_stop.grid(row=3, column=2, columnspan=2, padx=5, pady=5, sticky="we")

        self._on_motor_mode_changed()

    def _build_led_section(self, parent):
        frame = ttk.LabelFrame(parent, text="LEDs")
        frame.grid(row=1, column=1, padx=(5, 20), pady=6, sticky="nswe")
        frame.configure(style="Custom.TLabelframe")
        frame.columnconfigure(0, weight=1)

        self.chk_led_heat = ttk.Checkbutton(
            frame,
            text="Heating LED",
            variable=self.led_heat_var,
            bootstyle="round-toggle",  # pyrefly: ignore
            command=lambda: self._toggle_led("heat"),
            style="Custom.TCheckbutton",
        )
        self.chk_led_heat.grid(row=0, column=0, padx=3, pady=10, sticky="w")

        self.chk_led_fluor = ttk.Checkbutton(
            frame,
            text="Fluorescence LED",
            variable=self.led_fluor_var,
            bootstyle="round-toggle",  # pyrefly: ignore
            command=lambda: self._toggle_led("fluor"),
            style="Custom.TCheckbutton",
        )
        self.chk_led_fluor.grid(row=1, column=0, padx=3, pady=10, sticky="w")

    def _build_reading_section(self, parent, entry_widgets):
        frame = ttk.LabelFrame(parent, text="Readings")
        frame.grid(row=2, column=0, columnspan=2, padx=(3, 20), pady=6, sticky="nswe")
        frame.configure(style="Custom.TLabelframe")
        frame.columnconfigure((0, 1, 2, 3, 4, 5), weight=1)

        # Señales mutuamente excluyentes (por ahora una a la vez; ver docs)
        self.chk_sig_temp = ttk.Checkbutton(
            frame,
            text="Temperature",
            variable=self.sig_temp_var,
            command=self._on_sig_temp,
            style="Custom.TCheckbutton",
        )
        self.chk_sig_temp.grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.chk_sig_fluor = ttk.Checkbutton(
            frame,
            text="Fluorescence",
            variable=self.sig_fluor_var,
            command=self._on_sig_fluor,
            style="Custom.TCheckbutton",
        )
        self.chk_sig_fluor.grid(row=0, column=1, padx=5, pady=5, sticky="w")

        ttk.Label(frame, text="Sample time (ms):", style="Custom.TLabel").grid(
            row=0, column=2, padx=5, pady=5, sticky="e"
        )
        self.interval_entry = ttk.Entry(frame, width=8, font=font_entry)
        self.interval_entry.insert(0, "500")
        self.interval_entry.grid(row=0, column=3, padx=5, pady=5, sticky="w")
        entry_widgets.append(self.interval_entry)

        self.chk_keep = ttk.Checkbutton(
            frame, text="Keep data", style="Custom.TCheckbutton", variable=self.keep_data_var
        )
        self.chk_keep.grid(row=0, column=4, padx=5, pady=5, sticky="w")

        ttk.Label(frame, text="Temp source:", style="Custom.TLabel").grid(
            row=1, column=4, padx=5, pady=5, sticky="e"
        )
        self.cbo_temp_source = ttk.Combobox(
            frame,
            values=temp_source_labels(),
            state="readonly",
            font=font_entry,
            width=14,
        )
        self.cbo_temp_source.set(temp_source_label(self.temp_source))
        self.cbo_temp_source.grid(row=1, column=5, padx=5, pady=5, sticky="w")
        self.cbo_temp_source.bind("<<ComboboxSelected>>", self._on_temp_source_changed)

        self.btn_read_start = ttk.Button(
            frame, text="▶ Start", style="info.TButton", command=self.start_reading
        )
        self.btn_read_start.grid(row=1, column=0, padx=5, pady=5, sticky="we")
        self.btn_read_stop = ttk.Button(
            frame,
            text="⏹ Stop",
            style="danger.TButton",
            command=self.stop_reading,
            state=ttk.DISABLED,
        )
        self.btn_read_stop.grid(row=1, column=1, padx=5, pady=5, sticky="we")
        self.btn_read_clean = ttk.Button(
            frame, text="🗑 Clean", style="secondary.TButton", command=self.clean_data
        )
        self.btn_read_clean.grid(row=1, column=2, padx=5, pady=5, sticky="we")
        self.btn_read_save = ttk.Button(
            frame, text="💾 Save", style="success.TButton", command=self.save_data
        )
        self.btn_read_save.grid(row=1, column=3, padx=5, pady=5, sticky="we")

    def _build_plot_section(self, parent):
        graphic_frame = ttk.Frame(parent)
        graphic_frame.grid(row=3, column=0, columnspan=2, padx=10, pady=6, sticky="nsew")
        graphic_frame.columnconfigure(0, weight=1)
        graphic_frame.rowconfigure(0, weight=1)

        # Figura compacta para la pantalla del Pi (mismo criterio que EventPlotter)
        self.fig, self.ax = plt.subplots(figsize=(6.0, 2.6), dpi=100)
        self.ax.set_title("Quick readings")
        self.ax.set_xlabel("Time (s)")
        self.ax.set_ylabel("Value")
        self.ax.grid(True, alpha=0.25)
        self.canvas = FigureCanvasTkAgg(self.fig, master=graphic_frame)
        canvas_widget = self.canvas.get_tk_widget()
        canvas_widget.grid(row=0, column=0, padx=(2, 20), pady=5, sticky="nsew")

    def _apply_dev_mode(self):
        """En dev (Windows) no hay UART/GPIO/I2C: se deshabilita motor, LEDs y la
        señal de fluorescencia. La temperatura sí funciona (UDP es solo un socket)."""
        for w in (
            self.cmb_motor_mode,
            self.cmb_motor_dir,
            self.entry_rpm,
            self.entry_angle,
            self.entry_speed,
            self.btn_motor_start,
            self.btn_motor_stop,
            self.chk_led_heat,
            self.chk_led_fluor,
            self.chk_sig_fluor,
        ):
            w.configure(state=ttk.DISABLED)
        self._set_status("(dev) Hardware not available: motor, LEDs and fluorescence.")

    # ---------------- Motor ----------------

    def _on_motor_mode_changed(self):
        """Habilita los entries del modo elegido y deshabilita los del otro."""
        if self.is_dev:
            return
        continuous = self.motor_mode_var.get() == "Continuous"
        self.cmb_motor_dir.configure(state="readonly" if continuous else ttk.DISABLED)
        self.entry_rpm.configure(state=ttk.NORMAL if continuous else ttk.DISABLED)
        self.entry_angle.configure(state=ttk.DISABLED if continuous else ttk.NORMAL)
        self.entry_speed.configure(state=ttk.DISABLED if continuous else ttk.NORMAL)

    def callback_motor_start(self):
        import ui.DiscFrame as disc
        from Drivers.DriverStepperSys import DriverStepperSys, spinMotorRPM_ramped

        if self.motor_running or self.motor_stopping:
            self._set_status("Motor already running or stopping.")
            return
        mode = self.motor_mode_var.get()
        rpm = angle = speed_pct = 0.0
        try:
            if mode == "Continuous":
                rpm = float(self.entry_rpm.get())
            else:
                angle = float(self.entry_angle.get())
                speed_pct = float(self.entry_speed.get())
                if angle > 45 or angle <= 0:
                    self._set_status("Invalid angle (0-45°).")
                    return
        except ValueError:
            self._set_status("Invalid motor parameters.")
            return

        settings = read_settings_from_file()
        with disc.thread_lock:
            if disc.thread_motor and disc.thread_motor.is_alive():
                self._set_status("A motor thread is already running (another tab?).")
                return
            drv = disc.drv
            if drv is None:
                drv = DriverStepperSys(
                    en_pin=12, enable_active_high=False, uart_port=serial_port_encoder
                )
                drv.enable_driver(True)
                disc.drv = drv  # pyrefly: ignore  # singleton compartido con DiscFrame
            self.motor_stop_event = threading.Event()
            if mode == "Continuous":
                direction = self.motor_dir_var.get()
                ts = settings.get("ts_spin", 0.1)
                acceleration = settings.get("acceleration_spin", 200.0)
                thread = threading.Thread(
                    target=spinMotorRPM_ramped,
                    args=(
                        direction,
                        rpm,
                        ts,
                        acceleration,
                        1000.0,
                        True,
                        drv,
                        None,
                        None,
                        self.motor_stop_event,
                    ),
                    daemon=True,
                )
                self._set_status(f"Motor {direction} at {rpm:.0f} RPM.")
            else:
                max_rpm = settings.get("max_rpm", 700)
                thread = threading.Thread(
                    target=disc.spinMotorAngle,
                    args=(
                        angle,
                        speed_pct * max_rpm / 100,
                        max_rpm,
                        None,
                        True,
                        self.motor_stop_event,
                        drv,
                    ),
                    daemon=True,
                )
                self._set_status(f"Oscillator ±{angle:.0f}° at {speed_pct:.0f}%.")
            disc.thread_motor = thread  # pyrefly: ignore  # singleton compartido
            thread.start()
        self.motor_running = True
        self.btn_motor_start.configure(state=ttk.DISABLED)
        self.btn_motor_stop.configure(state=ttk.NORMAL)
        self.cmb_motor_mode.configure(state=ttk.DISABLED)
        self._update_lock()

    def callback_motor_stop(self):
        if not self.motor_running or self.motor_stop_event is None:
            return
        self.motor_stopping = True
        self.btn_motor_stop.configure(state=ttk.DISABLED)
        self._set_status("Stopping motor (ramp + go zero)…")
        self.motor_stop_event.set()
        # join + liberación del driver en un hilo aparte para no congelar la UI
        # durante la desaceleración suave y el go_zero (varios segundos).
        threading.Thread(target=self._motor_stop_worker, daemon=True).start()

    def _motor_stop_worker(self):
        import ui.DiscFrame as disc

        th = disc.thread_motor
        if th is not None and th.is_alive():
            th.join()
        with disc.thread_lock:
            drv = disc.drv
            if drv is not None:
                try:
                    drv.enable_driver(False)
                    drv.close()
                except Exception as e:
                    print(f"Error releasing motor driver: {e}")
                disc.drv = None  # pyrefly: ignore  # singleton compartido
        self.after(0, self._on_motor_stopped)

    def _on_motor_stopped(self):
        self.motor_running = False
        self.motor_stopping = False
        self.motor_stop_event = None
        self.btn_motor_start.configure(state=ttk.NORMAL)
        self.cmb_motor_mode.configure(state="readonly")
        self._set_status("Motor stopped.")
        self._update_lock()

    # ---------------- LEDs ----------------

    def _toggle_led(self, which):
        """Enciende/apaga el LED del toggle. La línea gpiod se mantiene abierta
        mientras está ON (las tabs viejas quedan bloqueadas mientras tanto) y se
        libera al apagar."""
        var = self.led_heat_var if which == "heat" else self.led_fluor_var
        gpio = led_heatin_pin if which == "heat" else led_fluorescence_pin
        turn_on = var.get()
        try:
            if turn_on:
                if self.led_pins[which] is None:
                    from Drivers.DriverGPIO import GPIOPin

                    pin = GPIOPin(  # pyrefly: ignore
                        gpio,
                        chip=chip_rasp,
                        consumer="quick-control-ui",
                        active_low=False,
                    )
                    pin.set_output(initial_high=False)
                    self.led_pins[which] = pin
                self.led_pins[which].write(True)
                self._set_status(f"LED {which} ON (GPIO {gpio}).")
            else:
                self._release_led(which)
                self._set_status(f"LED {which} OFF.")
        except Exception as e:
            print(f"Error GPIO LED {which}: {e}")
            var.set(False)
            self._set_status(f"Error GPIO LED {which}: {e}")
        self._update_lock()

    def _release_led(self, which):
        """Apaga y libera la línea del LED si estaba tomada."""
        pin = self.led_pins[which]
        if pin is None:
            return
        try:
            pin.write(False)
        except Exception:
            pass
        try:
            pin.close()
        except Exception as e:
            print(f"Error closing GPIO LED {which}: {e}")
        self.led_pins[which] = None

    # ---------------- Lecturas ----------------

    def _on_sig_temp(self):
        if self.sig_temp_var.get():
            self.sig_fluor_var.set(False)

    def _on_sig_fluor(self):
        if self.sig_fluor_var.get():
            self.sig_temp_var.set(False)

    def _ensure_ads(self) -> bool:
        """Mismo patrón que PhotoreceptorFrame: lazy-init del ADS1115, no-op en dev."""
        if self.ads is not None:
            return True
        if self.is_dev:
            return False
        try:
            settings = read_settings_from_file()
            ads_fsr = float(settings.get("ads_fsr", 1.024))
            from Drivers.ReaderADS import Ads1115Reader

            self.ads = Ads1115Reader(address=0x48, fsr=ads_fsr, sps=64, single_shot=False)
            return True
        except Exception as e:
            print(f"ADS init failed: {e}")
            return False

    def start_reading(self):
        if self.reading_running:
            self._set_status("Already reading.")
            return
        if self.sig_temp_var.get():
            signal = "temp"
        elif self.sig_fluor_var.get():
            signal = "fluor"
        else:
            self._set_status("Select a signal (Temperature or Fluorescence).")
            return
        try:
            interval = int(self.interval_entry.get())
        except ValueError:
            self.interval_entry.configure(background="salmon")
            self._set_status("Invalid interval.")
            return
        if interval < 100:
            interval = 100  # evita intervalos demasiado cortos
            self.interval_entry.delete(0, "end")
            self.interval_entry.insert(0, str(interval))

        if signal == "fluor":
            if not self._ensure_ads():
                self._set_status("ADS1115 not available.")
                return
        else:
            self.udp_client = UdpClient(
                port=5005,
                buffer_size=512,
                allow_broadcast=True,
                local_ip="",
                recv_timeout_sec=0.1,
                on_message=lambda t, a, t_d: self._on_udp_message(t, a, t_d),
                parse_float=True,
            )
            self.udp_client.start()
            self.temps_filter = [20.0, 20.0, 20.0, 20.0]

        # Retención: Keep data solo apila corridas de la MISMA señal; cambiar de
        # señal (o Keep apagado) limpia el plot y reinicia el índice de corrida.
        if not self.keep_data_var.get() or (self.runs and self.runs[-1]["signal"] != signal):
            self.runs.clear()
            self.run_index = 0
        self.run_index += 1
        meta = self._current_actuator_meta()
        if signal == "temp":
            # Documenta qué temperatura del disco se registró (va al nombre del CSV).
            meta["tsrc"] = temp_source_label(self.temp_source)
        self.runs.append(
            {
                "signal": signal,
                "t": [],
                "v": [],
                "run": self.run_index,
                "meta": meta,
            }
        )
        self.reading_signal = signal
        self.reading_running = True
        self.start_time = time.time()

        self.btn_read_start.configure(state=ttk.DISABLED)
        self.btn_read_stop.configure(state=ttk.NORMAL)
        self.chk_sig_temp.configure(state=ttk.DISABLED)
        self.chk_sig_fluor.configure(state=ttk.DISABLED)
        self.chk_keep.configure(state=ttk.DISABLED)
        name = "Temperature" if signal == "temp" else "Fluorescence"
        self._set_status(f"Reading {name} every {interval} ms (R{self.run_index}).")
        self._update_lock()
        self.after(interval, self._acquire)

    def stop_reading(self):
        if not self.reading_running:
            return
        self.reading_running = False
        if self.udp_client is not None:
            self.udp_client.stop()
            self.udp_client = None
        self.btn_read_start.configure(state=ttk.NORMAL)
        self.btn_read_stop.configure(state=ttk.DISABLED)
        self.chk_sig_temp.configure(state=ttk.NORMAL)
        self.chk_sig_fluor.configure(state=ttk.NORMAL if not self.is_dev else ttk.DISABLED)
        self.chk_keep.configure(state=ttk.NORMAL)
        self._set_status("Reading stopped.")
        self._update_lock()

    def _acquire(self):
        if not self.reading_running:
            return
        try:
            if self.reading_signal == "temp":
                value = self._thermocouple_reader()
            else:
                settings = read_settings_from_file()
                if settings.get("photoreceptor", {}).get("use_diff", False):
                    value = self.ads.read_voltage_diff(0, 1, averages=8)
                else:
                    value = self.ads.read_voltage(0, averages=8)
        except Exception as e:
            print(f"Error reading signal: {e}")
            value = None
        if value is not None:
            run = self.runs[-1]
            run["t"].append(time.time() - self.start_time)
            run["v"].append(float(value))
            self._redraw()
        try:
            interval = max(int(self.interval_entry.get()), 100)
            self.after(interval, self._acquire)
        except ValueError:
            self.interval_entry.configure(background="salmon")
            self.stop_reading()

    def _on_temp_source_changed(self, event=None):
        self.temp_source = temp_source_key(self.cbo_temp_source.get())
        self.temp_source_idx = temp_source_index(self.temp_source)
        self.temp_source_bad = False
        self.temps_filter = [self.latest_temps[self.temp_source_idx]] * 4
        write_temp_source(self.temp_source)

    def _on_udp_message(self, text, address, temps_list):
        """Callback del UdpClient (en su hilo) con el broadcast del Arduino.

        Guarda las tres temperaturas del disco (IR amb, IR obj, termocupla),
        conservando el último valor válido por campo y marcando los ausentes."""
        for i in range(3):
            v = temps_list[i] if i < len(temps_list) else None
            if v is not None:
                self.latest_temps[i] = float(v)
                self._field_ok[i] = True
            else:
                self._field_ok[i] = False
        self.latest_temp = self.latest_temps[2]  # compat

    def _thermocouple_reader(self) -> float:
        """Promedio móvil de 4 muestras de la fuente elegida (termocupla / IR
        objeto / IR ambiente). Si el sensor viene ausente, sostiene el último valor
        y lo avisa en el status."""
        idx = self.temp_source_idx
        if not self._field_ok[idx]:
            self.temp_source_bad = True
            self._set_status(f"⚠ {temp_source_label(self.temp_source)} unavailable — holding last value")
        else:
            self.temp_source_bad = False
        self.temps_filter.pop(0)
        self.temps_filter.append(self.latest_temps[idx])
        return sum(self.temps_filter) / len(self.temps_filter)

    # ---------------- Plot ----------------

    def _redraw(self):
        self.ax.clear()
        for run in self.runs:
            self.ax.plot(run["t"], run["v"], linewidth=1.5, label=f"R{run['run']}")
        signal = self.runs[-1]["signal"] if self.runs else None
        if signal == "temp":
            title, ylabel = "Temperature", "Temperature (°C)"
        elif signal == "fluor":
            title, ylabel = "Fluorescence", "Voltage (V)"
        else:
            title, ylabel = "Quick readings", "Value"
        self.ax.set_title(title)
        self.ax.set_xlabel("Time (s)")
        self.ax.set_ylabel(ylabel)
        self.ax.grid(True, alpha=0.25)
        if len(self.runs) > 1:
            self.ax.legend(loc="best", frameon=True)
        self.canvas.draw()

    def clean_data(self):
        if self.reading_running:
            self.stop_reading()
        self.runs.clear()
        self.run_index = 0
        self._redraw()
        self._set_status("Data cleared.")

    # ---------------- Persistencia ----------------

    def _current_actuator_meta(self):
        """Contexto de actuadores al momento de iniciar la corrida; va al nombre
        del CSV para documentar las condiciones del experimento."""
        meta = {}
        if self.motor_running:
            if self.motor_mode_var.get() == "Continuous":
                meta["rpm"] = f"{self.entry_rpm.get()}{self.motor_dir_var.get()}"
            else:
                meta["osc"] = f"{self.entry_angle.get()}deg{self.entry_speed.get()}pct"
        if self.led_heat_var.get():
            meta["heat"] = "ON"
        if self.led_fluor_var.get():
            meta["fluorled"] = "ON"
        return meta

    def _build_filename_suffix(self, meta):
        """Sufijo '_k1v1_k2v2…' (mismo criterio que EventPlotter.filename_meta)."""
        if not meta:
            return ""
        parts = []
        for k, v in meta.items():
            sv = "".join(c if c.isalnum() or c in "-." else "_" for c in str(v))
            sk = "".join(c if c.isalnum() else "_" for c in str(k))
            parts.append(f"{sk}{sv}")
        return "_" + "_".join(parts)

    def save_data(self):
        if self.reading_running:
            self._set_status("Stop reading before saving.")
            return
        if not any(run["t"] for run in self.runs):
            self._set_status("No data to save.")
            return
        os.makedirs("files", exist_ok=True)
        signal = self.runs[-1]["signal"]
        suffix = self._build_filename_suffix(self.runs[-1].get("meta", {}))
        initialfile = f"unified_{signal}_{time.strftime('%Y%m%d_%H%M%S')}{suffix}.csv"
        filename = filedialog.asksaveasfilename(
            parent=self,
            title="Save data",
            initialdir="files",
            initialfile=initialfile,
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not filename:
            self._set_status("Save cancelled.")
            return
        if not filename.lower().endswith(".csv"):
            filename += ".csv"
        try:
            with open(filename, "w", encoding="utf-8") as f:
                f.write("t_s,value,signal,run\n")
                for run in self.runs:
                    for t, v in zip(run["t"], run["v"]):
                        f.write(f"{t:.3f},{v},{run['signal']},{run['run']}\n")
            self._set_status(f"Data saved: {os.path.basename(filename)}")
        except Exception as e:
            self._set_status(f"Error saving CSV: {e}")

    # ---------------- Bloqueo de tabs y estado ----------------

    def _update_lock(self):
        """Bloquea/desbloquea las demás tabs (ambos notebooks) según haya algo
        activo: motor, algún LED ON o lectura corriendo. Auto-unlock al quedar
        todo apagado."""
        active = []
        if self.motor_running or self.motor_stopping:
            active.append("motor")
        if self.led_heat_var.get():
            active.append("heating LED")
        if self.led_fluor_var.get():
            active.append("fluorescence LED")
        if self.reading_running:
            active.append("reading")
        locked = bool(active)
        if locked:
            self.lbl_lock.configure(text=f"🔒 Tabs locked while: {', '.join(active)}.")
        else:
            self.lbl_lock.configure(text="")
        if self.lock_tabs_callback is not None:
            try:
                self.lock_tabs_callback(locked)
            except Exception as e:
                print(f"Error in lock_tabs_callback: {e}")

    def _set_status(self, msg):
        print(f"[QuickControl] {msg}")
        self.lbl_status.configure(text=msg)

    # ---------------- Limpieza ----------------

    def _on_destroy(self, event=None):
        """Apaga LEDs, detiene lectura y señala parada del motor al cerrar la app."""
        if event is not None and event.widget is not self:
            return
        try:
            self.reading_running = False
            if self.udp_client is not None:
                self.udp_client.stop()
                self.udp_client = None
        except Exception:
            pass
        self._release_led("heat")
        self._release_led("fluor")
        if self.motor_stop_event is not None:
            self.motor_stop_event.set()
