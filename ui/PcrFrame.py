# -*- coding: utf-8 -*-

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
stop_event_motor = threading.Event()


def spinMotorRPMTime(direction, rpm_setpoint, ts, t_experiment):
    global sistemaMotor, thread_motor, stop_event_motor
    thread_motor = threading.Thread(
            target=spinMotorRPM_ramped,
            args=(direction, rpm_setpoint, ts, 1000.0, 1000.0, True, sistemaMotor))
    thread_motor.start()
    start_time = time.perf_counter()
    while not stop_event_motor.is_set():
        if (time.perf_counter() - start_time) > t_experiment:
            print("Tiempo de experimento terminado: ", time.perf_counter() - start_time)
            stop_event_motor.set()
            break
        time.sleep(1)
    


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
    ]
    columns = 2
    default_values = ["60", "40", "8", "5", "1", "500"]
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
        row=len(labels) + 1, column=0, padx=5, pady=5, sticky="e"
    )
    entries.append(svar_temperature)    # pyrefly:ignore
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

    def update_displayed_temperature(self, text, address):
        msg = f"Temperature: {text} °C"
        # print(msg)
        self.entries[-1].set(msg)  # pyrefly: ignore
        try:
            self.temp = float(text)
        except Exception as e:
            print(e)
            self.temp = 0.0

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
        print(
            f"High Temp: {high_temp}, Low Temp: {low_temp}, Time High: {time_high}, Time Low: {time_low}, Cycles: {cycles}, RPM: {rpm}"
        )
        thread_experiment = threading.Thread(
            target=self.experiment_pcr,
            args=(high_temp, low_temp, time_high, time_low, rpm, self.ads),
        )
        thread_experiment.start()

    def experiment_pcr(self, high_temp, low_temp, time_high, time_low, rpm, ads):
        global thread_motor, sistemaMotor

        # cliente temperature
        self.client_temperature = UdpClient(
            port=5005,
            buffer_size=4096,
            allow_broadcast=True,  # Important for broadcast payloads
            local_ip="",  # "" listens on all interfaces (wlan0, eth0, etc.)
            recv_timeout_sec=1.0,  # lets loop check stop flag periodically
            on_message=lambda t, a: self.update_displayed_temperature(t, a),
            parse_float=True,  # Arduino sends a numeric string
        )
        self.client_temperature.start()
        # rotate motor ar rpm
        from Drivers.DriverStepperSys import DriverStepperSys

        try:
            direction = "CW"
            rpm_setpoint = rpm
            ts = 0.01
            if sistemaMotor is None:
                sistemaMotor = DriverStepperSys(
                    en_pin=12, enable_active_high=False, uart_port=serial_port_encoder
                )
            stop_event_motor.clear()
            print(f"Starting motor spin at {rpm_setpoint} RPM for 5 seconds")
            # initial spin with expecific time
            spinMotorRPMTime(direction, rpm_setpoint, ts, 5)
            time.sleep(1)
            from Drivers.DriverGPIO import GPIOPin
            print("Motor stopped")
            self.pin_heating = GPIOPin(
                led_heatin_pin,
                chip=chip_rasp,
                consumer="led-heating-ui",
                active_low=False,
            )
            # Preconfigura como salida en bajo
            self.pin_heating.set_output(initial_high=False)  # pyrefly: ignore

            cycles = 2
            current_cycle = 0
            print(f"start cycle {current_cycle}")
            while current_cycle< cycles:
                # init cycle 
                # start heating to reach high_temp value
                self.pin_heating.write(True)  # pyrefly: ignore
                print(f"Heating to reach {high_temp} °C")
                # time.sleep(time_high)
                while self.temp < high_temp:
                    time.sleep(1)
                self.pin_heating.write(False)  # pyrefly: ignore
                print(f"Temperature reached: {self.temp} °C")
                # hold temperature for 10 sec only with heating led
                time_hold = 10
                print(f"Holding temperature for {time_hold} seconds")
                start_time = time.time()
                current_time = time.time()
                while current_time - start_time < time_hold:
                    if self.temp > high_temp:  # si se pasa de la temperatura objetivo
                        self.pin_heating.write(False)  # apagar calor
                    else:
                        self.pin_heating.write(True)  # encender calor
                    time.sleep(0.5)
                    current_time = time.time()
                print(f"Hold complete, cooling down to {low_temp} °C with motor spin")
                # cool down with motor spin
                stop_event_motor.clear()
                spinMotorRPM_ramped(direction, rpm_setpoint, ts, 300.0, 700.0, True, sistemaMotor)
                while self.temp > low_temp:
                    time.sleep(1)
                stop_event_motor.set()
                print(f"Temperature reached: {self.temp} °C")
                # hold temperature for 10 sec with led only
                time_hold = 10
                print(f"Holding temperature for {time_hold} seconds")
                start_time = time.time()
                current_time = time.time()
                while current_time - start_time < time_hold:
                    if self.temp < low_temp:  # si se pasa de la temperatura objetivo
                        self.pin_heating.write(False)  # apagar calor
                    else:
                        self.pin_heating.write(True)  # encender calor
                    time.sleep(0.5)
                    current_time = time.time()
                print(f"Hold complete, end of cycle {current_cycle}")
                current_cycle += 1
                #end of cycle
            self.pin_heating.close()  # pyrefly: ignore
            print("PCR cycles complete, reading fluorescence")
            # turn on fluorescen LED
            self.pin_pcr = GPIOPin(
                led_fluorescence_pin,
                chip=chip_rasp,
                consumer="test_pcr",
                active_low=False,
            )
            # Preconfigura como salida en bajo
            self.pin_pcr.set_output(initial_high=False)  # pyrefly: ignore
            self.pin_pcr.write(True)  # pyrefly: ignore
            print("Reading fluorescence...")
            time.sleep(1)   # tiempo encedido el led de fluorescencia
            self.pin_pcr.write(False)  # pyrefly: ignore
            # read fluorescence
            v_fluo = ads.read_voltage(0, averages=4)
            print(f"fluorescence voltage: {v_fluo}")
        except Exception as e:
            print(f"exception in experiment: {e}")
        if sistemaMotor is not None:
            sistemaMotor.stop() 
            sistemaMotor.close()
        sistemaMotor = None
        ads = None
        self.client_temperature.stop()
        self.running_experiment = False
        self.pin_heating = None
        self.pin_pcr = None

    def callback_stop_experiment(self):
        global sistemaMotor
        print("Experimento detenido")
        stop_event_motor.set()
        # stop motor
        # stop temperature
        self.client_temperature.stop()
        self.running_experiment = False
        time.sleep(1)
        if sistemaMotor is not None:
            sistemaMotor.stop()
            sistemaMotor.close()
        if self.pin_heating is not None:
            self.pin_heating.write(False)  # pyrefly: ignore
            self.pin_heating.close()  # pyrefly: ignore
        if self.pin_pcr is not None:
            self.pin_pcr.write(False)  # pyrefly: ignore
            self.pin_pcr.close()  # pyrefly: ignore
        self.pin_heating = None
        self.pin_pcr = None
