# -*- coding: utf-8 -*-

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
    # Botón para generar perfil
    ttk.Button(
        frame1,
        text="Generate Profile",
        style="info.TButton",
        command=callbacks.get("callback_generate_profile", ()),
    ).grid(row=len(labels), column=0, columnspan=2, pady=10)
    # Boton para empezar experimento
    ttk.Button(
        frame1,
        text="Start Experiment",
        style="success.TButton",
        command=callbacks.get("callback_start_experiment", ()),
    ).grid(row=len(labels), column=2, columnspan=2, pady=10)
    svar_temperature = ttk.StringVar(value="")
    ttk.Label(frame1, textvariable=svar_temperature, style="Custom.TLabel").grid(
        row=len(labels) + 1, column=0, padx=5, pady=5, sticky="nswe"
    )
    entries.append(svar_temperature)  # pyrefly:ignore
    ttk.Button(
        frame1,
        text="Stop Experiment",
        style="danger.TButton",
        command=callbacks.get("callback_stop_experiment", ()),
    ).grid(row=len(labels) + 1, column=2, columnspan=2, pady=10)
    return entries


class PCRFrame(ttk.Frame):
    def __init__(self, parent, ads_reader):
        ttk.Frame.__init__(self, parent)
        self.parent = parent
        self.running_experiment = False
        self.pin_heating = None
        self.pin_pcr = None
        self.temp = 0.0
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.ads = ads_reader
        self.fase = "Initial"
        self.ts_display = 1
        self.last_display = time.time()
        self.stop_event_motor = None
        self.stop_udp_listenner = None

        content_frame = ScrolledFrame(self, autohide=True)
        content_frame.grid(row=0, column=0, sticky="nsew")
        content_frame.columnconfigure(0, weight=1)

        callbacks = {
            "callback_generate_profile": self.callback_generate_profile,
            "callback_start_experiment": self.callback_start_experiment,
            "callback_stop_experiment": self.callback_stop_experiment,
        }
        self.entries = create_widgets_pcr(content_frame, callbacks)

        # Frame para mostrar el gráfico
        self.profile_frame = ttk.LabelFrame(content_frame, text="Profile Preview")
        self.profile_frame.grid(row=1, column=0, padx=10, pady=10, sticky="nswe")
        self.profile_frame.configure(style="Custom.TLabelframe")

        self.canvas = None  # Para almacenar el gráfico incrustado

        self.callback_generate_profile()  # Generar el gráfico inicial

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

    def update_displayed_temperature(self, text, address, temps_dict):
        # print("temps: ", temps_dict)
        temps = [
            temps_dict["mlx_object"],
            0.0,
            temps_dict["max31855"],
        ]

        # print(msg)
        try:
            self.temp = float(
                temps[2]
            )  # Usamos la temperatura del objeto como referencia
        except Exception as e:
            print(e)
            self.temp = 0.0
        if time.time() - self.last_display > self.ts_display:
            msg = f"Temperature: {self.temp} °C\n" + f"State: {self.fase}"
            self.entries[-1].set(msg)  # pyrefly: ignore

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
        print(
            f"High Temp: {high_temp}, Low Temp: {low_temp}, Time High: {time_high}, Time Low: {time_low}, Cycles: {cycles}, RPM: {rpm}",
            f"Denaturing Time: {denat_time}, Denaturing Temp: {denat_temp}",
        )
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
        self.client_temperature = UdpClient(
            port=5005,
            buffer_size=4096,
            allow_broadcast=True,  # Important for broadcast payloads
            local_ip="",  # "" listens on all interfaces (wlan0, eth0, etc.)
            recv_timeout_sec=0.1,  # lets loop check stop flag periodically
            on_message=lambda t, a, t_d: self.update_displayed_temperature(t, a, t_d),
            parse_float=True,  # Arduino sends a numeric string,
            stop_event=self.stop_udp_listenner,
        )
        self.client_temperature.start()
        # rotate motor ar rpm
        from Drivers.DriverStepperSys import DriverStepperSys

        try:
            settings = read_settings_from_file()
            acceleration = float(settings.get("acceleration_spin", 200.0))
            direction = "CW"
            rpm_setpoint = rpm
            ts = float(settings.get("ts_pcr", 0.1))
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
            while self.temp < denat_temp and not self.stop_udp_listenner.is_set():
                # print(f"Temperature: {self.temp} °C")
                time.sleep(ts)
            # hold temperature for denat_time seconds only coounting time when temp is over temp target
            start_time = time.time()
            current_time = time.time()
            self.fase = "Denaturation Hold"
            while current_time - start_time < denat_time:
                if (
                    self.temp > denat_temp + 0.5
                ):  # si se pasa de la temperatura objetivo
                    self.pin_heating.write(False)  # apagar calor
                else:
                    self.pin_heating.write(True)  # encender calor
                time.sleep(ts)
                current_time = time.time()
                # current_time = time.time()
            self.pin_heating.write(False)  # pyrefly: ignore
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
                self.fase = "High temp"
                while True and not self.stop_udp_listenner.is_set():
                    if (
                        self.temp > high_temp + 1.1
                    ):  # si se pasa de la temperatura objetivo
                        self.pin_heating.write(False)  # apagar calor
                    elif self.temp < high_temp - 5:
                        self.pin_heating.write(True)  # encender calor
                    else:
                        break
                    time.sleep(ts)
                self.pin_heating.write(False)  # pyrefly: ignore
                print(f"Temperature reached: {self.temp} °C")
                # -------------------------------------------------------------------
                # hold High temperature
                self.fase = "Hold High temp"
                print(f"Holding temperature for {time_high} seconds")
                start_time = time.time()
                current_time = time.time()
                passed_time = 0
                while passed_time < time_high and not self.stop_udp_listenner.is_set():
                    if self.temp > high_temp:  # si se pasa de la temperatura objetivo
                        self.pin_heating.write(False)  # apagar calor
                        passed_time += ts
                        # print(f"Temperature: {self.temp} °C, passed_time: {passed_time:.2f} s")
                    else:
                        self.pin_heating.write(True)  # encender calor
                    time.sleep(ts)
                    # current_time = time.time()
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
                    or abs(self.temp - low_temp) <= 7.5,
                    stop_event=self.stop_event_motor
                )
                print(f"Temperature reached: {self.temp} °C")
                # -------------------------------------------------------------------
                # hold LOW temperature
                self.fase = "LOW temp Hold"
                print(f"Holding LOW temperature for {time_low} seconds")
                # start_time = time.time()
                # current_time = time.time()
                passed_time = 0
                while passed_time < time_low and not self.stop_udp_listenner.is_set():
                    if self.temp < low_temp:  # si se pasa de la temperatura objetivo
                        self.pin_heating.write(True)  # encender calor
                    else:
                        self.pin_heating.write(False)  # apagar calor
                        passed_time += ts
                    time.sleep(ts)
                    # current_time = time.time()
                print(f"Hold complete, end of cycle {current_cycle}")
                current_cycle += 1
                # end of cycle
                self.pin_heating.write(False)
                time.sleep(1)
                self.pin_pcr.write(True)
                time.sleep(1)
                print("Reading fluorescence...")
                self.fase = "Reading Fluorescence"
                v_fluo = ads.read_voltage(0, averages=4)
                time.sleep(1)
                self.pin_pcr.write(False)
                print(f"fluorescence voltage: {v_fluo}")

            print("PCR cycles complete, reading fluorescence")
            passed_time = 0
            self.fase = "Extension"
            while passed_time < 30 and not self.stop_udp_listenner.is_set():
                if self.temp < low_temp:  # si se pasa de la temperatura objetivo
                    self.pin_heating.write(True)  # encender calor
                else:
                    self.pin_heating.write(False)  # apagar calor
                    passed_time += ts
                time.sleep(ts)
            self.pin_heating.write(False)
            self.pin_pcr.write(True)
            time.sleep(1)
            v_fluo_final = ads.read_voltage(0, averages=4)
            print(f"Final fluorescence voltage: {v_fluo_final}")
            time.sleep(1)
            self.fase = "Final"
            self.pin_pcr.write(False)
            self.pin_heating.close()
            self.pin_pcr.close()

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
