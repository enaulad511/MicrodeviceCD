# -*- coding: utf-8 -*-

from datetime import datetime
from templates.utils import read_settings_from_file
from templates.constants import chip_rasp
from Drivers.ClientUDP import UdpClient
from templates.constants import serial_port_encoder
from templates.constants import led_fluorescence_pin
from templates.constants import led_heatin_pin
import time
import threading
import ttkbootstrap as ttk
from ttkbootstrap.scrolled import ScrolledFrame
from templates.constants import font_entry
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from ui.DiscFrame import spinMotorRPM_ramped
from ui.KeyboardFrame import NumericKeyboard

__author__ = "Edisson A. Naula"
__date__ = "$ 21/10/2025 at 11:30 a.m. $"


# Variables globales
sistemaMotor = None
thread_motor = None
ads = None
thread_lock = threading.Lock()

# Duración de la lectura de fluorescencia (fuente única de verdad).
# Usadas como defaults de _read_fluorescence, en los sleeps previos a cada
# lectura y en la estimación de tiempo restante del experimento.
FLUOR_PRE_SLEEP_S = 0.5   # espera tras el hold de extensión, antes de muestrear
FLUOR_BASELINE_S = 0.5    # ventana de línea base (luz OFF)
FLUOR_LIGHT_S = 2.0       # ventana de excitación (luz ON)
FLUOR_POST_S = 0.5        # ventana de decaimiento (luz OFF)
# Tiempo total que consume una lectura completa (sleep previo + 3 ventanas).
FLUOR_READ_TOTAL_S = FLUOR_PRE_SLEEP_S + FLUOR_BASELINE_S + FLUOR_LIGHT_S + FLUOR_POST_S


def check_temp_higher(temp, target_temp):
    return temp >= target_temp


def _fuzzy_gains(error: float, base_kp: float, base_ki: float) -> tuple:
    """Escala KP/KI dinámicamente según la magnitud del error (fuzzy gain scheduling).

    Tres zonas con interpolación lineal para transiciones suaves:
      |e| >= 15°C  → agresivo (kp×2.0, ki×0.2): rampas largas sin windup
      5 <= |e| < 15 → intermedio: transición suave
      |e| < 5°C    → preciso  (kp×0.5, ki×1.3): regulación cerca del setpoint

    Los factores de escala operan sobre las ganancias base leídas de settings.json,
    por lo que el punto de operación nominal sigue siendo configurable allí.
    """
    abs_error = abs(error)
    if abs_error >= 5.0:
        kp_s, ki_s = 2.0, 0.2
    elif abs_error >= 2.0:
        t = (abs_error - 5.0) / 10.0  # 0..1 de 3°C a 7°C
        kp_s = 1.0 + t * 1.0  # 1.0 → 2.0
        ki_s = 1.0 - t * 0.8  # 0.2 → 1.0
    else:
        t = abs_error / 5.0  # 0..1 de 0°C a 3°C
        kp_s = 0.5 + t * 0.5  # 0.5 → 1.0
        ki_s = 1.3 - t * 0.3  # 1.0 → 1.3
    return base_kp * kp_s, base_ki * ki_s


def create_widgets_pcr(parent):
    entries = []

    # Frame: Configuración PCR
    frame1 = ttk.LabelFrame(parent, text="PCR Configuration")
    frame1.configure(style="Custom.TLabelframe")
    frame1.grid(row=0, column=0, padx=(5, 25), pady=(5, 5), sticky="nswe")
    # frame1.configure(style="Custom.TLabelframe")

    labels = [
        "High Temp (°C):",
        "Low Temp (°C):",
        "Time High (s):",
        "Time Low (s):",
        "Number of Cycles:",
        "RPM Cooling:",
        "Denaturing time (s):",
        "Denaturing Temp:",
        "Ext. Time:",
        "Ext. Temp:",
        "Ext. Time F.: ",
        "Initial Spin [s]: ",
    ]
    columns = 2
    default_values = ["94", "55", "15", "15", "3", "700", "30", "94", "6", "68", "300", "15"]
    for i, lbl in enumerate(labels):
        row = i // columns
        col = i % columns
        ttk.Label(frame1, text=lbl, style="Custom.TLabel").grid(
            row=row, column=col * 2, padx=5, pady=5, sticky="e"
        )
        entry = ttk.Entry(frame1, font=font_entry)
        entry.insert(0, default_values[i])
        entry.grid(row=row, column=col * 2 + 1, padx=5, pady=5)

        # entry.bind("<FocusIn>", show_numeric_keyboard)

        entries.append(entry)
    # frame1.bind("<FocusOut>", hide_keyboard)
    frame1.columnconfigure(tuple(range(2 * columns)), weight=1)

    return entries


def create_buttons(master, callbacks, svar_status):
    frame_buttons = ttk.Frame(master)
    frame_buttons.grid(row=0, column=0, sticky="nswe")
    frame_buttons.columnconfigure(tuple(range(4)), weight=1)
    # Botón para generar perfil
    ttk.Button(
        frame_buttons,
        text="📈",
        style="info.TButton",
        command=callbacks.get("callback_generate_profile", ()),
    ).grid(row=0, column=0, padx=10, sticky="nswe")
    # Boton para empezar experimento
    ttk.Button(
        frame_buttons,
        text="▶️Start",
        style="success.TButton",
        command=callbacks.get("callback_start_experiment", ()),
    ).grid(row=0, column=1, padx=10, sticky="nswe")

    # save data button
    ttk.Button(
        frame_buttons,
        text="⏹️Stop",
        style="danger.TButton",
        command=callbacks.get("callback_stop_experiment", ()),
    ).grid(row=0, column=2, padx=10, sticky="nswe")

    ttk.Button(
        frame_buttons,
        text="💾Save Data",
        style="info.TButton",
        command=callbacks.get("callback_save_data", ()),
    ).grid(row=0, column=3, padx=10, sticky="nswe")
    frame_label = ttk.Frame(master, style="Custom.TFrame")
    frame_label.grid(row=1, column=0, sticky="nswe")
    frame_label.columnconfigure(0, weight=1)
    ttk.Label(frame_label, textvariable=svar_status, style="Custom.TLabel").grid(
        row=0, column=0, padx=5, pady=5, sticky="nswe"
    )


class PCRFrame(ttk.Frame):
    def __init__(self, parent, ads_reader):
        ttk.Frame.__init__(self, parent)
        self.parent = parent
        self.running_experiment = False
        self.pin_heating = None
        self.pin_pcr = None
        self.temp = 0.0
        self.temp_ts = time.time()
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.ads = ads_reader
        self.fase = "Initial"
        self.ts_display = 0.5
        self.last_display = time.time()
        self.start_pcr_time = time.time()
        self.cycles_complete = 0
        self.start_cycle_time = time.time()
        self.time_end_cycle = time.time()
        self.total_cycles = 0
        self.teorical_time_pcr = 0
        self.last_cycle_duration = 0.0
        self.avg_cycle_duration = 0.0
        self.ext_time_final = 0.0
        self.stop_event_motor = None
        self.stop_udp_listenner = None
        self.thread_experiment = None
        self.client_temperature = None
        self.temp_update_counter = 0
        self._ui_poll_graph_counter = 0
        self._ui_poll_active = False
        self.content_frame = ScrolledFrame(self, autohide=True)
        self.content_frame.grid(row=0, column=0, sticky="nsew")
        self.content_frame.columnconfigure(0, weight=1)
        self.frame_entries = ttk.Frame(self.content_frame)
        self.frame_entries.grid(row=0, column=0, sticky="nswe")
        self.frame_entries.columnconfigure(0, weight=1)
        self.prefix_row = "temps_pcr"

        callbacks = {
            "callback_generate_profile": self.callback_generate_profile,
            "callback_start_experiment": self.callback_start_experiment,
            "callback_stop_experiment": self.callback_stop_experiment,
            "callback_save_data": self.save_data_temps_file,
        }
        self.entries = create_widgets_pcr(self.frame_entries)
        self.keyboard = NumericKeyboard(self, scroll_host=self.content_frame, width=260, height=150)
        self.keyboard.attach(self.entries)
        self.svar_status = ttk.StringVar(value="Ready")
        self.frame_buttons = ttk.Frame(self.content_frame)
        self.frame_buttons.grid(row=1, column=0, sticky="nswe", padx=(5, 25))
        self.frame_buttons.columnconfigure(0, weight=1)
        create_buttons(self.frame_buttons, callbacks, self.svar_status)
        # Frame para mostrar el gráfico
        self.profile_frame = ttk.LabelFrame(self.content_frame, text="Profile Preview")
        self.profile_frame.grid(row=3, column=0, padx=(2, 20), pady=10, sticky="nswe")
        self.profile_frame.configure(style="Custom.TLabelframe")

        self.canvas = None  # Para almacenar el gráfico incrustado
        self.callback_generate_profile()  # Generar el gráfico inicial
        self.data_temperature = []
        self.data_photodetector = []
        self.data_photodetector_series = []

    def callback_generate_profile(self):
        try:
            high_temp = float(self.entries[0].get())
            low_temp = float(self.entries[1].get())
            time_high = float(self.entries[2].get())
            time_low = float(self.entries[3].get())
            cycles = int(self.entries[4].get())
            rpm = float(self.entries[5].get())
            denat_time = float(self.entries[6].get())
            denat_temp = float(self.entries[7].get())
            ext_time = float(self.entries[8].get())
            ext_temp = float(self.entries[9].get())
            ext_time_final = float(self.entries[10].get())
            initial_spin_time = float(self.entries[11].get())

            room_temp = 20.0
            transition_const = 10000
            transition_time_down = transition_const / max(rpm, 1)
            transition_time_up = 15

            # (start, end, from_temp, to_temp, label, color)
            phase_segments = []
            current_time = 0.0

            # Initial spin: temperatura ambiente
            phase_segments.append((current_time, current_time + initial_spin_time,
                                    room_temp, room_temp, "Initial Spin", "gray"))
            current_time += initial_spin_time

            # Rampa hacia denaturation
            phase_segments.append((current_time, current_time + transition_time_up,
                                    room_temp, denat_temp, "Ramp Denat", "darkorange"))
            current_time += transition_time_up

            # Hold Denaturation
            phase_segments.append((current_time, current_time + denat_time,
                                    denat_temp, denat_temp, "Denaturation", "purple"))
            current_time += denat_time

            n_display = min(5, cycles)
            prev_temp = denat_temp
            for _ in range(n_display):
                # Rampa hacia High
                phase_segments.append((current_time, current_time + transition_time_up,
                                        prev_temp, high_temp, "Heating", "orange"))
                current_time += transition_time_up

                # Hold High
                phase_segments.append((current_time, current_time + time_high,
                                        high_temp, high_temp, "High", "red"))
                current_time += time_high

                # Cooling hacia Low
                phase_segments.append((current_time, current_time + transition_time_down,
                                        high_temp, low_temp, "Cooling", "green"))
                current_time += transition_time_down

                # Hold Low
                phase_segments.append((current_time, current_time + time_low,
                                        low_temp, low_temp, "Low", "blue"))
                current_time += time_low

                # Rampa hacia Extension
                phase_segments.append((current_time, current_time + transition_time_up,
                                        low_temp, ext_temp, "Ramp Ext", "goldenrod"))
                current_time += transition_time_up

                # Hold Extension
                phase_segments.append((current_time, current_time + ext_time,
                                        ext_temp, ext_temp, "Extension", "darkcyan"))
                current_time += ext_time
                prev_temp = ext_temp

            # Extensión final
            phase_segments.append((current_time, current_time + ext_time_final,
                                    ext_temp, ext_temp, "Final Ext.", "magenta"))
            current_time += ext_time_final

            # Crear figura
            fig, ax = plt.subplots(figsize=(7, 4))
            plt.close("all")
            fig, ax = plt.subplots(figsize=(7, 4))

            labeled = set()
            for seg in phase_segments:
                start, end, t_from, t_to, label, color = seg
                first_occurrence = label not in labeled
                kwargs: dict = {"linewidth": 2.5} if t_from == t_to else {"linestyle": "--", "linewidth": 1.5}
                if first_occurrence:
                    kwargs["label"] = label
                    labeled.add(label)
                if t_from == t_to:
                    ax.hlines(t_from, start, end, colors=color, **kwargs)
                else:
                    ax.plot([start, end], [t_from, t_to], color=color, **kwargs)

            ax.axhline(high_temp, color="red", linestyle=":", linewidth=0.8, alpha=0.5)
            ax.axhline(low_temp, color="blue", linestyle=":", linewidth=0.8, alpha=0.5)
            ax.axhline(denat_temp, color="purple", linestyle=":", linewidth=0.8, alpha=0.5)
            ax.axhline(ext_temp, color="darkcyan", linestyle=":", linewidth=0.8, alpha=0.5)

            ax.legend(loc="upper right", fontsize=7, ncol=2)
            ax.set_xlabel("Tiempo (s)")
            ax.set_ylabel("Temperatura (°C)")
            ax.set_title(f"Perfil PCR ({cycles} ciclos)")
            ax.grid(True)

            if self.canvas:
                self.canvas.get_tk_widget().destroy()

            self.canvas = FigureCanvasTkAgg(fig, master=self.profile_frame)
            self.canvas.draw()
            self.canvas.get_tk_widget().pack(fill="both", expand=True)

        except ValueError:
            print("Error: Verifique los valores ingresados.")

    def update_displayed_temperature(self, text, address, temps_list):
        # Solo actualiza datos Python puros — sin operaciones Tkinter.
        # Tkinter no es thread-safe; toda actualización de UI ocurre en _ui_poll_loop.
        try:
            lf = float(temps_list[2])
            self.temp_ts = temps_list[3]
        except Exception:
            lf = self.temp
            self.temp_ts = 0.8
        alpha = 0.3
        self.temp = alpha * lf + (1 - alpha) * self.temp
        self.data_temperature.append(self.temp)

    def _ui_poll_loop(self):
        """Actualiza la UI desde el hilo principal (scheduled via after). Un solo hilo."""
        if not self._ui_poll_active:
            return
        total_msg = self.svar_status.get().split("\n")
        elapsed_pcr_time = time.time() - self.start_pcr_time
        mins_elapsed = int(elapsed_pcr_time / 60)
        msg_elapsed_time = (
            f"Time passed: {mins_elapsed} m {elapsed_pcr_time % 60:.1f} s "
            f"-- cycles: {self.cycles_complete}/{self.total_cycles}"
        )
        remaining = self._estimate_remaining_time(elapsed_pcr_time)
        msg_elapsed_time += f" -- Estimated finish: {int(remaining / 60)}m {remaining % 60:.1f}s"
        total_msg[0] = f"Temperature: {self.temp:.2f} °C\tState: {self.fase}"
        if len(total_msg) < 2:
            total_msg.append(msg_elapsed_time)
        else:
            total_msg[1] = msg_elapsed_time
        self.svar_status.set("\n".join(total_msg))

        self._ui_poll_graph_counter += 1
        if self._ui_poll_graph_counter >= 5:
            self._ui_poll_graph_counter = 0
            self.update_graph_temperature()

        self.after(500, self._ui_poll_loop)

    def _estimate_remaining_time(self, elapsed_pcr_time):
        # Antes de completar el primer ciclo no hay medición fiable: estima por
        # tiempo teórico restante. Tras un ciclo, proyecta los ciclos pendientes
        # con la duración promedio medida y descuenta lo ya transcurrido del
        # ciclo actual. Suma la extensión final si aún quedan ciclos.
        if self.cycles_complete == 0 or self.avg_cycle_duration <= 0:
            return max(0.0, self.teorical_time_pcr - elapsed_pcr_time)

        cycles_left = max(0, self.total_cycles - self.cycles_complete)
        if cycles_left > 0:
            elapsed_current = max(0.0, time.time() - self.start_cycle_time)
            remaining = (
                self.avg_cycle_duration * cycles_left
                - elapsed_current
                + self.ext_time_final
                + FLUOR_READ_TOTAL_S  # lectura de fluorescencia final pendiente
            )
        else:
            # Ya pasaron todos los ciclos: solo queda la extensión final.
            remaining = self.teorical_time_pcr - elapsed_pcr_time
        return max(0.0, remaining)

    def init_temperature_graph(self):
        if self.canvas is not None:
            self.canvas.get_tk_widget().destroy()
        self.data_temperature = []  # Datos acumulados
        self.data_photodetector = []
        self.data_photodetector_series = []

        # Dos subplots apilados: arriba temperatura (denso), abajo fotodetector (1/ciclo)
        self.fig, (self.ax, self.ax_photo) = plt.subplots(
            2, 1, figsize=(4.5, 5.0), constrained_layout=True
        )

        (self.line,) = self.ax.plot([], [], marker="o", markersize=2)
        self.ax.set_title("Temperature (°C)")
        self.ax.set_xlabel("Samples")
        self.ax.set_ylabel("°C")
        self.ax.grid(True)

        (self.line_photo,) = self.ax_photo.plot([], [], marker="o", color="purple", linewidth=1.2)
        self.ax_photo.set_title("Photodetector (V)")
        self.ax_photo.set_xlabel("Cycle")
        self.ax_photo.set_ylabel("V")
        self.ax_photo.grid(True)

        self.canvas = FigureCanvasTkAgg(self.fig, master=self.profile_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        self.canvas.draw()

    def update_graph_temperature(self, window_size=None):
        if window_size is None:
            settings = read_settings_from_file()
            windows_pcr = settings.get("windows_pcr", 2500)
            window_size = int(windows_pcr)
        if self.canvas is None:
            return

        n = len(self.data_temperature)
        if n == 0:
            return

        # Índice inicial de la ventana
        start = max(0, n - window_size)

        # Datos visibles
        y = self.data_temperature[start:n]
        x = range(start, n)

        self.line.set_xdata(x)
        self.line.set_ydata(y)

        # Mantener ventana deslizante en X
        self.ax.set_xlim(start, n - 1)

        # Recalcular solo el eje Y
        # self.ax.relim()
        # self.ax.autoscale_view(scalex=False, scaley=True)

        # Eje Y fijo
        self.ax.set_ylim(19, 105)

        self.canvas.draw_idle()

    def update_graph_photodetector(self):
        if self.canvas is None or not hasattr(self, "line_photo"):
            return
        n = len(self.data_photodetector)
        if n == 0:
            return
        x = list(range(1, n + 1))
        y = list(self.data_photodetector)
        self.line_photo.set_xdata(x)
        self.line_photo.set_ydata(y)
        self.ax_photo.set_xlim(0.5, max(n + 0.5, 1.5))
        ymin, ymax = min(y), max(y)
        margin = max(0.0001, (ymax - ymin) * 0.1)
        self.ax_photo.set_ylim(ymin - margin, ymax + margin)
        self.canvas.draw_idle()

    def save_data_temps_file(self):
        import csv

        timestamp = datetime.now()
        filename = f"files/temperature_data_{timestamp.strftime('%Y%m%d_%H%M%S')}.csv"
        with open(filename, "w", newline="") as file:
            writer = csv.writer(file)
            writer.writerow([self.prefix_row])
            for temp in self.data_temperature:
                writer.writerow([temp])
        print(f"Data saved to {filename}")
        filename_photo = f"files/photodetector_data_{timestamp.strftime('%Y%m%d_%H%M%S')}.csv"
        with open(filename_photo, "w", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(["photodetector"])
            for phot in self.data_photodetector:
                writer.writerow([phot])
        # Serie temporal cruda en formato largo (una fila por muestra)
        filename_raw = f"files/photodetector_raw_{timestamp.strftime('%Y%m%d_%H%M%S')}.csv"
        with open(filename_raw, "w", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(["cycle", "t_rel_s", "light_on", "voltage"])
            for cycle, samples in enumerate(self.data_photodetector_series, start=1):
                for t_rel, light_on, voltage in samples:
                    writer.writerow([cycle, f"{t_rel:.3f}", light_on, f"{voltage}"])

    def _ensure_ads(self) -> bool:
        if self.ads is not None:
            return True
        from templates.constants import secrets
        if secrets.get("environment", "") == "dev":
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

    def callback_start_experiment(self):
        if self.running_experiment:
            return
        if not self._ensure_ads():
            self.svar_status.set("Error: ADS1115 not available")
            return
        self.running_experiment = True
        # hide entries frame
        self.frame_entries.grid_forget()
        print("Experimento iniciado")
        # retrieve data from entries
        high_temp = float(self.entries[0].get())
        low_temp = float(self.entries[1].get())
        time_high = float(self.entries[2].get())
        time_low = float(self.entries[3].get())
        cycles = int(self.entries[4].get())
        rpm = float(self.entries[5].get())
        denat_time = float(self.entries[6].get())
        denat_temp = float(self.entries[7].get())
        ext_time = float(self.entries[8].get())
        ext_temp = float(self.entries[9].get())
        ext_time_final = float(self.entries[10].get())
        initia_spin_time = float(self.entries[11].get())

        msg = (
            f"High Temp: {high_temp}, Low Temp: {low_temp}, Time High: {time_high},"
            f" Time Low: {time_low}, Cycles: {cycles}, RPM: {rpm}",
            f"Denaturing Time: {denat_time}, Denaturing Temp: {denat_temp},"
            f" initial spin {initia_spin_time} s",
        )
        print(msg)
        self.init_temperature_graph()
        self._ui_poll_graph_counter = 0
        self._ui_poll_active = True
        self.after(500, self._ui_poll_loop)
        self.thread_experiment = threading.Thread(  # pyrefly: ignore
            target=self.experiment_pcr,
            args=(
                high_temp,
                low_temp,
                time_high,
                time_low,
                rpm,
                denat_time,
                denat_temp,
                cycles,
                self.ads,
                ext_time,
                ext_temp,
                ext_time_final,
                initia_spin_time,
            ),
        )
        self.thread_experiment.start()  # pyrefly: ignore

    def hold_temperature(
        self,
        temp_setpoint,
        time_hold,
        ts,
        stop_func,
        pin_heating,
        KI,
        I_MAX,
        KP_HOLD,
        TEMP_BAND,
        WINDOW,
    ):
        MAX_TEMP_AGE = ts  # si es más vieja → no confiar
        integral = 0.0
        start_time = time.time()
        while time.time() - start_time <= time_hold and not stop_func.is_set():
            # Verificar edad de la temperatura
            temp_age = time.time() - self.temp_ts
            if temp_age > MAX_TEMP_AGE:
                # Temperatura vieja → apagar por seguridad
                pin_heating.write(False)
                time.sleep(WINDOW / 2)
                continue
            temp = self.temp
            # Banda muerta mínima para evitar chatter
            error = temp_setpoint - temp
            kp_dyn, ki_dyn = _fuzzy_gains(error, KP_HOLD, KI)
            integral += error * WINDOW
            integral = max(-I_MAX, min(I_MAX, integral))
            if abs(error) < TEMP_BAND:
                power = 0.0
            else:
                power = kp_dyn * error + ki_dyn * integral
            # Saturar potencia
            power = max(0.0, min(1.0, power))
            on_time = power * WINDOW
            off_time = WINDOW - on_time
            if on_time > 0:
                pin_heating.write(True)
                end_on = time.time() + on_time
                while time.time() < end_on:
                    if stop_func.is_set():
                        break
                    time.sleep(WINDOW / 10)
            pin_heating.write(False)
            # Tiempo OFF (permite disipar energía)
            end_off = time.time() + off_time
            while time.time() < end_off:
                if stop_func.is_set():
                    break
                time.sleep(WINDOW / 10)

    def _load_phase_pid(self, phase, ts):
        # Lee parámetros de la fase desde settings.json en cada llamada,
        # para que ediciones de ganancias durante el experimento tomen efecto.
        settings = read_settings_from_file()
        pid = settings.get("pidControllerRPM", {})
        return {
            "KP": pid.get(f"KP_{phase}", 0.15),
            "KI": pid.get(f"KI_{phase}", 0.5),
            "I_MAX": pid.get(f"imax_{phase}", 0.5),
            "TEMP_BAND": pid.get(f"tband_{phase}", 0.05),
            "WINDOW": pid.get(f"win_{phase}", ts * 0.9),
            "MAX_AGE": pid.get(f"m_age_{phase}", 0.09),
            # Fracción del setpoint hasta la que se hace feed-forward a potencia
            # plena antes de entregar el control al PI. 0.0 = sin pre-rampa.
            "FF_FRAC": pid.get(f"ff_frac_{phase}", 0.0),
        }

    def _reach_temperature_pi(
        self, setpoint, params, stop_event, break_if_below=False, tolerance=0.5
    ):
        # Rampa PI hacia setpoint con anti-windup y descarte de temperatura vieja.
        # El heater debe estar pre-armado por el caller; este método modula on/off.
        KP = params["KP"]
        KI = params["KI"]
        I_MAX = params["I_MAX"]
        TEMP_BAND = params["TEMP_BAND"]
        WINDOW = params["WINDOW"]
        MAX_AGE = params["MAX_AGE"]
        FF_FRAC = params.get("FF_FRAC", 0.0)

        # ----- Pre-rampa feed-forward (mismo principio que la desnaturalización):
        # calienta a potencia plena hasta FF_FRAC*setpoint y luego entrega el
        # control al PI para asentar sin sobreimpulso. Se omite cuando venimos
        # ya calientes (break_if_below, p. ej. ciclo 0 tras el hold de denat).
        # A diferencia de la rampa de denaturación, aquí el blast también
        # descarta temperatura vieja: si la lectura UDP envejece, apaga el
        # heater y re-arma en cada lectura fresca para evitar runaway térmico.
        if FF_FRAC > 0.0 and not break_if_below:
            ceiling = setpoint * FF_FRAC
            while self.temp < ceiling and not stop_event.is_set():
                age = time.time() - self.temp_ts
                if age > MAX_AGE:
                    # Temperatura vieja → no confiar; corta y reintenta.
                    self.pin_heating.write(False)  # pyrefly: ignore
                    continue
                self.pin_heating.write(True)  # pyrefly: ignore

        integral = 0.0
        while tolerance < abs(setpoint - self.temp) and not stop_event.is_set():
            if break_if_below and self.temp < setpoint:
                break
            age = time.time() - self.temp_ts
            if age > MAX_AGE:
                # Temperatura vieja → no confiar
                self.pin_heating.write(False)  # pyrefly: ignore
                continue
            error = setpoint - self.temp
            kp_dyn, ki_dyn = _fuzzy_gains(error, KP, KI)
            integral += error * WINDOW
            integral = max(-I_MAX, min(I_MAX, integral))
            if abs(error) < TEMP_BAND:
                power = 0.0
            else:
                power = kp_dyn * error + ki_dyn * integral
            power = max(0.0, min(1.0, power))
            on_time = power * WINDOW
            if on_time > 0:
                self.pin_heating.write(True)  # pyrefly: ignore
                time.sleep(on_time)
            self.pin_heating.write(False)  # pyrefly: ignore
            time.sleep(WINDOW - on_time)

    def _hold_phase(self, phase, setpoint, duration, ts):
        params = self._load_phase_pid(phase, ts)
        self.hold_temperature(
            setpoint,
            duration,
            ts,
            self.stop_udp_listenner,
            self.pin_heating,
            params["KI"],
            params["I_MAX"],
            params["KP"],
            params["TEMP_BAND"],
            params["WINDOW"],
        )
        self.pin_heating.write(False)  # pyrefly: ignore

    def _read_fluorescence(
        self,
        ads,
        baseline_s=FLUOR_BASELINE_S,
        light_s=FLUOR_LIGHT_S,
        post_s=FLUOR_POST_S,
        sample_dt=0.1,
        averages=4,
    ):
        # Muestreo continuo del fotodetector mientras se modula la luz (pin_pcr):
        #   baseline_s  -> luz OFF (línea base oscura)
        #   light_s     -> luz ON  (excitación)
        #   post_s      -> luz OFF (decaimiento)
        # Acumula la serie temporal cruda y agrega el escalar
        #   delta = media(ventana con luz) - media(ventana baseline)
        # a data_photodetector (plot por-ciclo). Soporta lectura diferencial.
        settings = read_settings_from_file()
        use_diff = settings.get("photoreceptor", {}).get("use_diff", False)

        # (t_rel, light_on, voltage) por muestra
        samples = []

        def read_one():
            if use_diff:
                return ads.read_voltage_diff(0, 1, averages=averages)
            return ads.read_voltage(0, averages=averages)

        def sample_window(duration, light_on, t0):
            # Muestrea durante `duration` segundos a ~sample_dt, paceando por
            # tiempo transcurrido. Devuelve True si se abortó (stop).
            t_end = time.time() + duration
            while time.time() < t_end:
                if (
                    self.stop_udp_listenner is not None
                    and self.stop_udp_listenner.is_set()
                ):
                    return True
                t_iter = time.time()
                v = read_one()
                samples.append((t_iter - t0, light_on, v))
                elapsed = time.time() - t_iter
                if elapsed < sample_dt:
                    time.sleep(sample_dt - elapsed)
            return False

        t0 = time.time()
        try:
            self.pin_pcr.write(False)  # pyrefly: ignore
            aborted = sample_window(baseline_s, 0, t0)
            if not aborted:
                self.pin_pcr.write(True)  # pyrefly: ignore
                aborted = sample_window(light_s, 1, t0)
            if not aborted:
                self.pin_pcr.write(False)  # pyrefly: ignore
                sample_window(post_s, 0, t0)
        finally:
            self.pin_pcr.write(False)  # pyrefly: ignore

        baseline_vals = [v for (_, light_on, v) in samples if light_on == 0 and _ < baseline_s]
        light_vals = [v for (_, light_on, v) in samples if light_on == 1]
        mean_baseline = sum(baseline_vals) / len(baseline_vals) if baseline_vals else 0.0
        mean_light = sum(light_vals) / len(light_vals) if light_vals else 0.0
        delta = mean_light - mean_baseline

        # Acumulación (fuente única de verdad)
        self.data_photodetector.append(delta)
        self.data_photodetector_series.append(samples)
        self.after(1, lambda: self.update_graph_photodetector())
        return delta

    def _run_cycle(
        self,
        idx,
        high_temp,
        low_temp,
        time_high,
        time_low,
        rpm,
        direction,
        acceleration,
        ts,
        ext_time,
        ext_temp,
        ads,
    ):
        global sistemaMotor
        if self.stop_udp_listenner is None:
            self.stop_udp_listenner = threading.Event()
        self.start_cycle_time = time.time()

        # Reach High temp: feed-forward a potencia plena hasta ff_frac_high*setpoint
        # y luego PI (tolerancia 0.5). En el ciclo 0 (break_if_below) se omite el
        # blast porque venimos del hold de denaturación ya en temperatura.
        self.fase = "Reach High temp"
        self.pin_heating.write(True)  # pyrefly: ignore
        self._reach_temperature_pi(
            high_temp,
            self._load_phase_pid("high", ts),
            self.stop_udp_listenner,
            break_if_below=(idx == 0),
            tolerance=0.5,
        )
        print(f"Temperature reached: {self.temp} °C")

        # Hold High
        self.fase = "Hold High temp"
        print(f"Holding temperature for {time_high} seconds")
        self._hold_phase("h_high", high_temp, time_high, ts)
        print(f"Hold complete, cooling down to {low_temp} °C with motor spin")

        # Cool down con giro del motor
        self.fase = "Cooling"
        self.stop_event_motor.clear()  # pyrefly: ignore
        spinMotorRPM_ramped(
            direction,
            rpm,
            ts,
            acceleration,
            900.0,
            True,
            sistemaMotor,
            None,
            stop_func=lambda: self.stop_udp_listenner.is_set()  # pyrefly: ignore
            or self.temp <= low_temp
            or self.temp < low_temp + 9.5,
            stop_event=self.stop_event_motor,
        )
        
        print(self.temp, "low temp....dis")
        while (
            self.temp > low_temp + 0.5 and not self.stop_udp_listenner.is_set()
        ):  # pyrefly: ignore
            time.sleep(0.001)
        print(f"Temperature reached: {self.temp} °C")

        # Hold Low
        self.fase = "LOW temp Hold"
        print(f"Holding LOW temperature for {time_low} seconds")
        self._hold_phase("h_low", low_temp, time_low, ts)

        # Reach Ext temp (PI, tolerancia 0.2)
        self.fase = "Reach ext temp"
        self.pin_heating.write(True)  # pyrefly: ignore
        self._reach_temperature_pi(
            ext_temp,
            self._load_phase_pid("ext", ts),
            self.stop_udp_listenner,
            break_if_below=(idx == 0),
            tolerance=0.5,
        )
        print(f"Temperature reached: {self.temp} °C")

        # Hold Ext
        self.fase = "extension temp Hold "
        print(f"Holding extension temperature for {ext_time} seconds")
        self._hold_phase("h_ext", ext_temp, ext_time, ts)
        print(f"Hold ext complete, end of cycle {idx}")

        # Lectura de fluorescencia
        time.sleep(FLUOR_PRE_SLEEP_S)
        self.fase = "Reading Fluorescence"
        print("Reading fluorescence...")
        v_fluo = self._read_fluorescence(ads)
        print(f"fluorescence delta voltage: {v_fluo}")
        self.time_end_cycle = time.time()
        # Estadísticas para la estimación del tiempo restante
        self.last_cycle_duration = self.time_end_cycle - self.start_cycle_time
        self.cycles_complete = idx + 1
        self.avg_cycle_duration = (
            self.avg_cycle_duration * (self.cycles_complete - 1) + self.last_cycle_duration
        ) / self.cycles_complete

    def experiment_pcr(
        self,
        high_temp,
        low_temp,
        time_high,
        time_low,
        rpm,
        denat_time,
        denat_temp,
        cycles,
        ads,
        ext_time,
        ext_temp,
        ext_time_final,
        initial_spin_time,
    ):
        global thread_motor, sistemaMotor

        self.stop_udp_listenner = (
            threading.Event() if self.stop_udp_listenner is None else self.stop_udp_listenner
        )
        self.total_cycles = cycles
        self.cycles_complete = 0
        self.last_cycle_duration = 0.0
        self.avg_cycle_duration = 0.0
        self.ext_time_final = ext_time_final
        self.teorical_time_pcr = (
            (time_high + time_low + ext_time) * 1.2 * cycles
            + denat_time
            + ext_time_final
            + FLUOR_READ_TOTAL_S * cycles  # lectura de fluorescencia por ciclo
            + FLUOR_READ_TOTAL_S  # lectura de fluorescencia final
        )

        settings = read_settings_from_file()
        pidGains = settings.get("pidControllerRPM", {})
        try:
            ts = float(pidGains.get("ts_pcr", 0.05))
        except Exception:
            ts = 0.05

        prefix_col = (
            f"high_temp: {high_temp}-low_temp: {low_temp}-time_high: {time_high}"
            f"-time_low: {time_low}-cycles: {cycles}-rpm: {rpm}"
            f"-denat_temp: {denat_temp}-denat_time: {denat_time}-ts: {ts}"
        )
        self.temp = 20.0
        self.client_temperature = UdpClient(
            port=5005,
            buffer_size=512,
            allow_broadcast=True,  # Important for broadcast payloads
            local_ip="",  # "" listens on all interfaces (wlan0, eth0, etc.)
            recv_timeout_sec=0.1,  # lets loop check stop flag periodically
            on_message=lambda t, a, t_d: self.update_displayed_temperature(t, a, t_d),
            parse_float=True,  # Arduino sends a numeric string,
            stop_event=self.stop_udp_listenner,
            prefixCol=prefix_col,
            save_data=False,
        )
        self.prefix_row = prefix_col
        self.client_temperature.start()
        self.fase = "Initial"
        from Drivers.DriverStepperSys import DriverStepperSys

        self.start_pcr_time = time.time()

        try:
            acceleration = float(pidGains.get("acceleration_spin", 200.0))
            direction = "CW"
            if sistemaMotor is None:
                print("Creating new driver instance")
                sistemaMotor = DriverStepperSys(
                    en_pin=12, enable_active_high=False, uart_port=serial_port_encoder
                )

            self.stop_event_motor = (
                threading.Event() if self.stop_event_motor is None else self.stop_event_motor
            )

            # Spin inicial con tiempo específico
            spinMotorRPM_ramped(
                direction,
                rpm,
                ts,
                acceleration,
                900.0,
                True,
                sistemaMotor,
                time_exp=initial_spin_time,
                stop_func=lambda: self.stop_event_motor.is_set(),
                stop_event=self.stop_event_motor,
            )
            from Drivers.DriverGPIO import GPIOPin

            self.pin_heating = GPIOPin(
                led_heatin_pin,
                chip=chip_rasp,
                consumer="led-heating-ui",
                active_low=False,
            )
            self.pin_pcr = GPIOPin(
                led_fluorescence_pin,
                chip=chip_rasp,
                consumer="test_pcr",
                active_low=False,
            )
            self.pin_pcr.set_output(initial_high=False)

            # ----- Denaturación: mismo principio que "Reach High temp":
            # feed-forward a potencia plena hasta ff_frac_denat*setpoint y luego PI
            # (ganancias difusas + anti-windup + descarte de temperatura vieja).
            self.fase = "Denaturation"
            self.pin_heating.write(True)  # pyrefly: ignore
            self._reach_temperature_pi(
                denat_temp,
                self._load_phase_pid("denat", ts),
                self.stop_udp_listenner,
                break_if_below=False,
                tolerance=0.5,
            )

            # ----- Denaturation Hold
            self.fase = "Denaturation Hold"
            self._hold_phase("h_denat", denat_temp, denat_time, ts)
            print(f"Denaturation complete, temperature: {self.temp} °C")

            # ----- Ciclos PCR
            for idx in range(cycles):
                if self.stop_udp_listenner.is_set():
                    break
                print(f"start cycle {idx}")
                self._run_cycle(
                    idx,
                    high_temp,
                    low_temp,
                    time_high,
                    time_low,
                    rpm,
                    direction,
                    acceleration,
                    ts,
                    ext_time,
                    ext_temp,
                    ads,
                )

            # ----- Extensión final + lectura de fluorescencia (solo si no se detuvo)
            if not self.stop_udp_listenner.is_set():
                print("PCR cycles complete, reading fluorescence")
                self.fase = "Extension"
                self._hold_phase("h_ext", 68, ext_time_final, ts)
                time.sleep(FLUOR_PRE_SLEEP_S)
                v_fluo_final = self._read_fluorescence(ads)
                print(f"Final fluorescence delta voltage: {v_fluo_final}")
                self.fase = "Final"

            self.save_data_temps_file()

        except Exception as e:
            print(f"exception in experiment: {e}")
        finally:
            self._teardown_hardware()

    def _teardown_hardware(self):
        # Cierre idempotente de hardware: motor, UDP, pines GPIO. Seguro de invocar
        # desde el hilo del experimento (en finally) o desde el hilo de UI (Stop).
        global sistemaMotor
        if sistemaMotor is not None:
            try:
                sistemaMotor.stop()
            except Exception as e:
                print(f"error stopping motor: {e}")
            try:
                sistemaMotor.close()
            except Exception as e:
                print(f"error closing motor: {e}")
            sistemaMotor = None
        if self.client_temperature is not None:
            try:
                self.client_temperature.stop()
            except Exception as e:
                print(f"error stopping udp client: {e}")
        if self.pin_heating is not None:
            try:
                self.pin_heating.write(False)  # pyrefly: ignore
                self.pin_heating.close()
            except Exception as e:
                print(f"error closing pin_heating: {e}")
            self.pin_heating = None
        if self.pin_pcr is not None:
            try:
                self.pin_pcr.write(False)  # pyrefly: ignore
                self.pin_pcr.close()
            except Exception as e:
                print(f"error closing pin_pcr: {e}")
            self.pin_pcr = None
        self._ui_poll_active = False
        self.running_experiment = False

    def callback_stop_experiment(self):
        # Restaura UI y dispara la salida ordenada del hilo del experimento.
        # El propio finally del experimento llama a _teardown_hardware; aquí solo
        # señalizamos, esperamos al hilo, y tiramos red de seguridad si se colgó.
        self.frame_entries.grid(row=0, column=0, padx=5, pady=5, sticky="nswe")
        if self.stop_event_motor is None or self.stop_udp_listenner is None:
            print("No experiment running")
            self.running_experiment = False
            return
        self.stop_event_motor.set()
        self.stop_udp_listenner.set()
        if self.thread_experiment is not None:
            self.thread_experiment.join(timeout=3.0)
            if self.thread_experiment.is_alive():
                print("warning: experiment thread did not exit within 3s, forcing teardown")
        # Red de seguridad: si el finally del experimento ya corrió, esto es no-op.
        self._teardown_hardware()
        self.stop_event_motor = None
        self.stop_udp_listenner = None
        self.thread_experiment = None
