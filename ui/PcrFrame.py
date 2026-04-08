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

__author__ = "Edisson A. Naula"
__date__ = "$ 21/10/2025 at 11:30 a.m. $"


# Variables globales
sistemaMotor = None
thread_motor = None
ads = None
thread_lock = threading.Lock()


def check_temp_higher(temp, target_temp):
    return temp >= target_temp


def create_widgets_pcr(parent, callbacks: dict):
    entries = []

    # Frame: Configuración PCR
    frame1 = ttk.LabelFrame(parent, text="PCR Configuration")
    frame1.grid(row=0, column=0, padx=10, pady=10, sticky="nswe")
    frame1.configure(style="Custom.TLabelframe")

    labels = [
        "High Temp (°C):",
        "Low Temp (°C):",
        "Time High (s):",
        "Time Low (s):",
        "Number of Cycles:",
        "RPM Cooling:",
        "Denaturing time (s):",
        "Denaturing Temp:",
    ]
    columns = 2
    default_values = ["60", "40", "10", "10", "1", "500", "180", "68"]
    for i, lbl in enumerate(labels):
        row = i // columns
        col = i % columns
        ttk.Label(frame1, text=lbl, style="Custom.TLabel").grid(
            row=row, column=col * 2, padx=5, pady=5, sticky="e"
        )
        entry = ttk.Entry(frame1, font=font_entry)
        entry.insert(0, default_values[i])
        entry.grid(row=row, column=col * 2 + 1, padx=5, pady=5)
        entries.append(entry)
    frame1.columnconfigure(tuple(range(2 * columns)), weight=1)
    frame_label = ttk.Frame(parent, style="Custom.TFrame")
    frame_label.grid(row=1, column=0, sticky="nswe")
    frame_label.columnconfigure(0, weight=1)
    svar_temperature = ttk.StringVar(value="")
    ttk.Label(frame_label, textvariable=svar_temperature, style="Custom.TLabel").grid(
        row=0, column=0, padx=5, pady=5, sticky="nswe"
    )
    entries.append(svar_temperature)  # pyrefly:ignore
    frame_buttons = ttk.Frame(parent)
    frame_buttons.grid(row=2, column=0, sticky="nswe")
    frame_buttons.columnconfigure(tuple(range(4)), weight=1)
    # Botón para generar perfil
    ttk.Button(
        frame_buttons,
        text="Generate Profile",
        style="info.TButton",
        command=callbacks.get("callback_generate_profile", ()),
    ).grid(row=0, column=0, padx=10, sticky="nswe")
    # Boton para empezar experimento
    ttk.Button(
        frame_buttons,
        text="Start Experiment",
        style="success.TButton",
        command=callbacks.get("callback_start_experiment", ()),
    ).grid(row=0, column=1, padx=10, sticky="nswe")

    # save data button
    ttk.Button(
        frame_buttons,
        text="Stop Experiment",
        style="danger.TButton",
        command=callbacks.get("callback_stop_experiment", ()),
    ).grid(row=0, column=2, padx=10, sticky="nswe")

    ttk.Button(
        frame_buttons,
        text="Save Data",
        style="info.TButton",
        command=callbacks.get("callback_save_data", ()),
    ).grid(row=0, column=3, padx=10, sticky="nswe")
    return entries


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
        self.stop_event_motor = None
        self.stop_udp_listenner = None
        self.temp_update_counter = 0
        content_frame = ScrolledFrame(self, autohide=True)
        content_frame.grid(row=0, column=0, sticky="nsew")
        content_frame.columnconfigure(0, weight=1)
        self.prefix_row = "temps_pcr"

        callbacks = {
            "callback_generate_profile": self.callback_generate_profile,
            "callback_start_experiment": self.callback_start_experiment,
            "callback_stop_experiment": self.callback_stop_experiment,
            "callback_save_data": self.save_data_temps_file,
        }
        self.entries = create_widgets_pcr(content_frame, callbacks)

        # Frame para mostrar el gráfico
        self.profile_frame = ttk.LabelFrame(content_frame, text="Profile Preview")
        self.profile_frame.grid(row=3, column=0, padx=10, pady=10, sticky="nswe")
        self.profile_frame.configure(style="Custom.TLabelframe")

        self.canvas = None  # Para almacenar el gráfico incrustado

        self.callback_generate_profile()  # Generar el gráfico inicial
        self.data_temperature = []
        self.data_photodetector = []

    def callback_generate_profile(self):
        try:
            high_temp = float(self.entries[0].get())
            low_temp = float(self.entries[1].get())
            time_high = float(self.entries[2].get())
            time_low = float(self.entries[3].get())
            cycles = int(self.entries[4].get())
            rpm = float(self.entries[5].get())

            # Generar datos con pendientes proporcionales a RPM
            current_time = 0.0
            transition_const = 10000  # Ajusta la escala de transición
            transition_time_down = transition_const / max(rpm, 1)
            transition_time_up = 15

            # Segmentos para dibujar con colores y etiquetas
            phase_segments = []

            for _ in range(cycles):
                # Transición Low -> High
                start = current_time
                end = current_time + transition_time_up
                phase_segments.append((start, end, None, "Heating"))
                current_time = end

                # High Temp fase
                start = current_time
                end = current_time + time_high
                phase_segments.append((start, end, high_temp, "High"))
                current_time = end

                # Transición High -> Low
                start = current_time
                end = current_time + transition_time_down
                phase_segments.append((start, end, None, "Cooling"))
                current_time = end

                # Low Temp fase
                start = current_time
                end = current_time + time_low
                phase_segments.append((start, end, low_temp, "Low"))
                current_time = end

            # Crear figura
            fig, ax = plt.subplots(figsize=(7, 4))

            # Dibujar fases con colores y etiquetas
            for seg in phase_segments:
                start, end, temp, label = seg
                if label == "High":
                    ax.hlines(high_temp, start, end, colors="red", linewidth=2)
                    ax.text(
                        (start + end) / 2,
                        high_temp + 1,
                        "High",
                        ha="center",
                        color="red",
                    )
                elif label == "Low":
                    ax.hlines(low_temp, start, end, colors="blue", linewidth=2)
                    ax.text(
                        (start + end) / 2,
                        low_temp + 1,
                        "Low",
                        ha="center",
                        color="blue",
                    )
                else:  # Transiciones
                    if label == "Cooling":
                        ax.plot(
                            [start, end],
                            [high_temp, low_temp],
                            color="green",
                            linestyle="--",
                        )
                        ax.text(
                            (start + end) / 2,
                            (high_temp + low_temp) / 2,
                            "Cooling",
                            ha="center",
                            color="green",
                        )
                    else:
                        ax.plot(
                            [start, end],
                            [low_temp, high_temp],
                            color="orange",
                            linestyle="--",
                        )
                        ax.text(
                            (start + end) / 2,
                            (high_temp + low_temp) / 2,
                            "Heating",
                            ha="center",
                            color="orange",
                        )

            # Líneas horizontales de referencia
            ax.axhline(high_temp, color="red", linestyle=":", linewidth=1)
            ax.axhline(low_temp, color="blue", linestyle=":", linewidth=1)

            ax.set_xlabel("Tiempo (s)")
            ax.set_ylabel("Temperatura (°C)")
            ax.set_title("Perfil PCR")
            ax.grid(True)

            # Limpiar canvas previo
            if self.canvas:
                self.canvas.get_tk_widget().destroy()

            # Incrustar nuevo gráfico
            self.canvas = FigureCanvasTkAgg(fig, master=self.profile_frame)
            self.canvas.draw()
            self.canvas.get_tk_widget().pack(fill="both", expand=True)

        except ValueError:
            print("Error: Verifique los valores ingresados.")

    def update_displayed_temperature(self, text, address, temps_list):
        try:
            lf = float(temps_list[2])
            self.temp_ts = temps_list[3]
        except Exception:
            lf = self.temp
            self.temp_ts = time.time()
        # Filtro rápido y estable
        alpha = 0.3
        self.temp = alpha * lf + (1 - alpha) * self.temp
        # self.temps_filter.pop(0)
        # self.temps_filter.append(lf)
        # lf = sum(self.temps_filter) / len(self.temps_filter)

        # # Actualizar temperatura global de control
        # self.temp = lf
        self.data_temperature.append(self.temp)

        # Actualizar UI solo cuando toca
        if time.time() - self.last_display > self.ts_display:
            msg = f"Temperature: {lf:.2f} °C\nState: {self.fase}"
            self.entries[-1].set(msg)
            self.last_display = time.time()

        # Actualizar gráfica cada N muestras
        self.temp_update_counter += 1
        if self.temp_update_counter >= 10:
            self.temp_update_counter = 0
            self.after(1, lambda: self.update_graph_temperature())

    def init_temperature_graph(self):
        if self.canvas is not None:
            self.canvas.get_tk_widget().destroy()
        self.data_temperature = []  # Datos acumulados

        self.fig, self.ax = plt.subplots()
        (self.line,) = self.ax.plot([], [], marker="o")
        self.ax.set_title("Temperature (°C)")
        self.ax.set_xlabel("Samples")
        self.ax.set_ylabel("°C")

        self.canvas = FigureCanvasTkAgg(self.fig, master=self.profile_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        self.canvas.draw()

    def update_graph_temperature(self):
        if self.canvas is None:
            print("Canvas is not initialized.")
            return
        self.line.set_xdata(range(len(self.data_temperature)))
        self.line.set_ydata(self.data_temperature)
        self.ax.relim()
        self.ax.autoscale_view()
        self.canvas.draw_idle()

    def save_data_temps_file(self):
        import csv

        timestamp = datetime.now()
        filename = f"temperature_data_{timestamp.strftime('%Y%m%d_%H%M%S')}.csv"
        with open(filename, "w", newline="") as file:
            writer = csv.writer(file)
            writer.writerow([self.prefix_row])
            for temp in self.data_temperature:
                writer.writerow([temp])
        print(f"Data saved to {filename}")

    def callback_start_experiment(self):
        if self.running_experiment:
            return
        self.running_experiment = True
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
        msg = (
            f"High Temp: {high_temp}, Low Temp: {low_temp}, Time High: {time_high}, Time Low: {time_low}, Cycles: {cycles}, RPM: {rpm}",
            f"Denaturing Time: {denat_time}, Denaturing Temp: {denat_temp}",
        )
        print(msg)

        self.init_temperature_graph()
        thread_experiment = threading.Thread(
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
            ),
        )
        thread_experiment.start()

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
    ):
        WINDOW = ts  # reutiliza tu ts (100 ms está bien)
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
            integral += error * WINDOW
            integral = max(-I_MAX, min(I_MAX, integral))
            if abs(error) < TEMP_BAND:
                power = 0.0
            else:
                power = KP_HOLD * error + KI * integral
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
        print("passed time: ", time.time() - start_time)

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
    ):
        global thread_motor, sistemaMotor
        # cliente temperature
        self.stop_udp_listenner = (
            threading.Event()
            if self.stop_udp_listenner is None
            else self.stop_udp_listenner
        )
        # write a predix line with al parameters of experiment
        # prefix_col = f" high_temp: {high_temp}-L "
        settings = read_settings_from_file()
        try:
            ts = float(settings.get("pidControllerRPM", {}).get("ts_pcr", 0.05))
        except Exception:
            ts = 0.05
        prefix_col = f"high_temp: {high_temp}-low_temp: {low_temp}-time_high: {time_high}-time_low: {time_low}-cycles: {cycles}-rpm: {rpm}-denat_temp: {denat_temp}-denat_time: {denat_time}-ts: {ts}"
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
        # rotate motor ar rpm
        from Drivers.DriverStepperSys import DriverStepperSys

        try:
            acceleration = float(settings.get("acceleration_spin", 200.0))
            direction = "CW"
            rpm_setpoint = rpm
            if sistemaMotor is None:
                print("Creating new driver instance")
                sistemaMotor = DriverStepperSys(
                    en_pin=12, enable_active_high=False, uart_port=serial_port_encoder
                )
                print(sistemaMotor.get_status())
            self.stop_event_motor = (
                threading.Event()
                if self.stop_event_motor is None
                else self.stop_event_motor
            )
            # -------------------------------------------------------------------
            # initial spin with expecific time
            # -------------------------------------------------------------------
            spinMotorRPM_ramped(
                direction,
                rpm_setpoint,
                ts,
                acceleration,
                900.0,
                True,
                sistemaMotor,
                15,
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
            # Preconfigura como salida en bajo
            self.pin_pcr.set_output(initial_high=False)

            # -------------------------------------------------------------------
            # denaturization  process
            # -------------------------------------------------------------------
            # heat to temp
            self.fase = "Denaturation"
            self.pin_heating.write(True)  # pyrefly: ignore
            self.temp_ts = time.time()
            KP = 0.2  # ajustar
            WINDOW = 0.05  # segundos
            MAX_AGE = 0.09  # s
            while self.temp < denat_temp and not self.stop_udp_listenner.is_set():
                # heat straigh foward to the 75 % of setpoint
                if self.temp <= denat_temp * 0.6:
                    continue
                age = time.time() - self.temp_ts
                if age > MAX_AGE:
                    # Temperatura vieja → no confiar
                    self.pin_heating.write(False)
                    continue
                error = denat_temp - self.temp
                power = max(0.0, min(1.0, KP * error))
                on_time = power * WINDOW
                if on_time > 0:
                    self.pin_heating.write(True)
                    time.sleep(on_time)
                self.pin_heating.write(False)
                time.sleep(WINDOW - on_time)

            # ------------------------------------------------------------
            # Denaturation Hold (control proporcional por ventana)
            # ------------------------------------------------------------
            self.fase = "Denaturation Hold"
            KI = 0.4  # medio
            I_MAX = 0.5
            KP_HOLD = 0.15  # más suave que en calentamiento
            TEMP_BAND = 0.05  # margen muerto muy pequeño
            self.hold_temperature(
                denat_temp,
                denat_time,
                ts,
                self.stop_udp_listenner,
                self.pin_heating,
                KI,
                I_MAX,
                KP_HOLD,
                TEMP_BAND,
            )

            # Asegurar apagado final
            self.pin_heating.write(False)
            print(f"Denaturation complete, temperature: {self.temp} °C")
            # Preconfigura como salida en bajo
            current_cycle = 0
            print(f"start cycle {current_cycle}")
            while current_cycle < cycles:
                # -------------------------------------------------------------------
                # init cycle
                # -------------------------------------------------------------------
                # -------------------------------------------------------------------
                # reach high temp
                self.fase = "Reach High temp"
                KP = 0.1  # ajustar
                WINDOW = 0.2  # segundos
                MAX_AGE = 0.10  # s
                TEMP_BAND = 0.5
                self.pin_heating.write(True)  # pyrefly: ignore
                while (
                    TEMP_BAND < abs(high_temp - self.temp)
                    and not self.stop_udp_listenner.is_set()
                ):
                    # heat straigh foward to the 75 % of setpoint
                    if self.temp <= high_temp * 0.4:
                        continue
                    # print(f"Temperature: {self.temp} °C")

                    age = time.time() - self.temp_ts
                    if age > MAX_AGE:
                        # Temperatura vieja → no confiar
                        self.pin_heating.write(False)
                        continue
                    error = high_temp - self.temp
                    power = max(0.0, min(1.0, KP * error))
                    on_time = power * WINDOW

                    if on_time > 0:
                        self.pin_heating.write(True)
                        time.sleep(on_time)
                    self.pin_heating.write(False)
                    time.sleep(WINDOW - on_time)

                print(f"Temperature reached: {self.temp} °C")
                # -------------------------------------------------------------------
                # hold High temperature
                self.fase = "Hold High temp"
                print(f"Holding temperature for {time_high} seconds")
                KI = 0.4  # medio
                I_MAX = 0.5
                KP_HOLD = 0.1  # más suave que en calentamiento
                TEMP_BAND = 0.05  # margen muerto muy pequeño
                self.hold_temperature(
                    high_temp,
                    time_high,
                    ts,
                    self.stop_udp_listenner,
                    self.pin_heating,
                    KI,
                    I_MAX,
                    KP_HOLD,
                    TEMP_BAND,
                )

                self.pin_heating.write(False)
                print(f"Hold complete, cooling down to {low_temp} °C with motor spin")
                self.pin_heating.write(False)  # encender calor
                # -------------------------------------------------------------------
                # cool down with motor spin
                self.fase = "Cooling"
                self.stop_event_motor.clear()
                spinMotorRPM_ramped(
                    direction,
                    rpm_setpoint,
                    ts,
                    acceleration,
                    900.0,
                    True,
                    sistemaMotor,
                    None,
                    stop_func=lambda: self.stop_event_motor.is_set()
                    or abs(self.temp - low_temp) <= 1.5,
                    stop_event=self.stop_event_motor,
                )
                print(f"Temperature reached: {self.temp} °C")
                # -------------------------------------------------------------------
                # hold LOW temperature
                self.fase = "LOW temp Hold"
                print(f"Holding LOW temperature for {time_low} seconds")
                KI = 0.4  # medio
                I_MAX = 0.5
                KP_HOLD = 0.1  # más suave que en calentamiento
                TEMP_BAND = 0.05  # margen muerto muy pequeño
                self.hold_temperature(
                    low_temp,
                    time_low,
                    ts,
                    self.stop_udp_listenner,
                    self.pin_heating,
                    KI,
                    I_MAX,
                    KP_HOLD,
                    TEMP_BAND,
                )
                # Asegurar apagado final
                self.pin_heating.write(False)
                print(f"Hold complete, end of cycle {current_cycle}")
                current_cycle += 1
                # end of cycle
                self.pin_heating.write(False)
                time.sleep(0.5)
                self.pin_pcr.write(True)
                time.sleep(1)
                print("Reading fluorescence...")
                self.fase = "Reading Fluorescence"
                v_fluo = ads.read_voltage(0, averages=4)
                time.sleep(1)
                self.pin_pcr.write(False)
                print(f"fluorescence voltage: {v_fluo}")

            print("PCR cycles complete, reading fluorescence")
            # passed_time = 0
            self.fase = "Extension"
            time_extension = 30
            KI = 0.4  # medio
            I_MAX = 0.5
            KP_HOLD = 0.1  # más suave que en calentamiento
            TEMP_BAND = 0.05  # margen muerto muy pequeño
            self.hold_temperature(
                low_temp,
                time_extension,
                ts,
                self.stop_udp_listenner,
                self.pin_heating,
                KI,
                I_MAX,
                KP_HOLD,
                TEMP_BAND,
            )
            # Asegurar apagado final
            self.pin_heating.write(False)
            time.sleep(0.5)
            self.pin_pcr.write(True)
            time.sleep(1)
            v_fluo_final = ads.read_voltage(0, averages=4)
            print(f"Final fluorescence voltage: {v_fluo_final}")
            time.sleep(1)
            self.fase = "Final"
            self.pin_pcr.write(False)
            self.pin_heating.close()
            self.pin_pcr.close()
            # save data temps
            self.save_data_temps_file()

        except Exception as e:
            print(f"exception in experiment: {e}")
        if sistemaMotor is not None:
            # sistemaMotor.stop()
            sistemaMotor.close()
        sistemaMotor = None
        self.client_temperature.stop()
        self.running_experiment = False
        self.pin_heating = None
        self.pin_pcr = None

    def callback_stop_experiment(self):
        global sistemaMotor
        print("Experimento detenido")
        if self.stop_event_motor is None:
            print("No experiment running")
            return
        if self.stop_udp_listenner is None:
            print("No experiment running")
            return
        self.stop_event_motor.set()
        self.stop_udp_listenner.set()
        # stop motor
        # stop temperature
        self.client_temperature.stop()
        self.running_experiment = False
        time.sleep(1)
        if sistemaMotor is not None:
            sistemaMotor.stop()
            sistemaMotor.close()
        if self.pin_heating is not None:
            self.pin_heating.write(False)
            self.pin_heating.close()
        if self.pin_pcr is not None:
            self.pin_pcr.write(False)
            self.pin_pcr.close()
        self.pin_heating = None
        self.pin_pcr = None
        self.stop_event_motor = None
        self.stop_udp_listenner = None
