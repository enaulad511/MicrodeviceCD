# -*- coding: utf-8 -*-
from templates.constants import chip_rasp
from Drivers.ClientUDP import UdpClient
from templates.constants import serial_port_encoder
from templates.constants import led_fluorescence_pin
from templates.constants import led_heatin_pin
import time
from Drivers.PIDController import PIDController
from templates.utils import read_settings_from_file
import threading
import ttkbootstrap as ttk
from ttkbootstrap.scrolled import ScrolledFrame
from templates.constants import font_entry
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

__author__ = "Edisson A. Naula"
__date__ = "$ 21/10/2025 at 11:30 a.m. $"


# Variables globales
sistemaMotor = None
thread_motor = None
thread_lock = threading.Lock()
stop_event_motor = threading.Event()

def spinMotorRPMTime(direction, rpm, ts, t_experiment):
    global sistemaMotor
    settings: dict = read_settings_from_file()
    pid_cfg: dict = settings.get("pidControllerRPM", {"kp": 0.1, "ki": 0.01, "kd": 0.005}) 
    pid = PIDController(
        kp=pid_cfg["kp"],
        ki=pid_cfg["ki"],
        kd=pid_cfg["kd"],
        setpoint=rpm,
        output_limits=(pid_cfg.get(min, 10), pid_cfg.get("max", 50)),
        ts=ts,
    )
    start_time = time.perf_counter()
    current_time = time.perf_counter()
    sistemaMotor.avanzar(7) # pyrefly: ignore
    while not stop_event_motor.is_set():
        raw_data = sistemaMotor.leer_encoder()  # pyrefly:ignore
        rpm_actual = sistemaMotor.get_rpm() # pyrefly:ignore
        # print(raw_data)
        control_signal = round(pid.compute(rpm_actual), 2)
        # print(f"Control signal: {control_signal}")
        while (time.perf_counter() - current_time) < ts:
            pass
        if (time.perf_counter() - start_time) > t_experiment:
            stop_event_motor.set()
            break
        current_time = time.perf_counter()

    sistemaMotor.frenar_pasivo() # pyrefly: ignore
    time.sleep(1)
    print("Motor detenido correctamente")

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
    default_values = ["80", "30", "15", "10", "1", "500"]
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
    entries.append(svar_temperature)
    return entries


class PCRFrame(ttk.Frame):
    def __init__(self, parent):
        ttk.Frame.__init__(self, parent)
        self.parent = parent
        self.running_experiment = False
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        content_frame = ScrolledFrame(self, autohide=True)
        content_frame.grid(row=0, column=0, sticky="nsew")
        content_frame.columnconfigure(0, weight=1)

        callbacks = {
            "callback_generate_profile": self.callback_generate_profile,
            "callback_start_experiment": self.callback_start_experiment,
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
        print(msg)
        self.entries[-1].set(msg)

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
        thread_experiment = threading.Thread(target=self.experiment_pcr, args=(high_temp, low_temp, time_high, time_low, rpm))
        thread_experiment.start()
    
    def experiment_pcr(self, high_temp, low_temp, time_high, time_low, rpm):
        global thread_motor, sistemaMotor
        
        # cliente temperature
        self.client_temperature = UdpClient(
            port=5005,
            buffer_size=4096,
            allow_broadcast=True,  # Important for broadcast payloads
            local_ip="",  # "" listens on all interfaces (wlan0, eth0, etc.)
            recv_timeout_sec=1.0,  # lets loop check stop flag periodically
            on_message= lambda t, a: self.update_displayed_temperature(t, a),
            parse_float=True,  # Arduino sends a numeric string
        )
        self.client_temperature.start()
        # rotate motor ar rpm
        from Drivers.DriverEncoder import DriverEncoderSys
        try:
            direction = "CW"
            rpm_setpoint = rpm
            ts = 0.01
            if sistemaMotor is None:
                sistemaMotor = DriverEncoderSys(en_l=12, en_r=13, uart_port=serial_port_encoder, baudrate=57600)
            stop_event_motor.clear()
            spinMotorRPMTime(direction, rpm_setpoint, ts, 5)
            time.sleep(1)
            # turn on HEATING LED
            from Drivers.DriverGPIO import GPIOPin
            pin_heating = GPIOPin(     
                    led_heatin_pin,
                    chip=chip_rasp,
                    consumer="led-heating-ui",
                    active_low=False,
                )
            # Preconfigura como salida en bajo
            pin_heating.set_output(initial_high=False)     # pyrefly: ignore
            pin_heating.write(True)       # pyrefly: ignore
            time.sleep(7)
            pin_heating.write(False)       # pyrefly: ignore
            pin_heating.close()       # pyrefly: ignore
            time.sleep(1)
            # turn on fluorescen LED
            pin_pcr = GPIOPin(     
                    led_fluorescence_pin,
                    chip=chip_rasp,
                    consumer="test_pcr",
                    active_low=False,
                )
            # Preconfigura como salida en bajo
            pin_pcr.set_output(initial_high=False)     # pyrefly: ignore
            pin_pcr.write(True)       # pyrefly: ignore
            time.sleep(1)
            pin_pcr.write(False)       # pyrefly: ignore
            # pin_pcr.close()       # pyrefly: ignore
            time.sleep(1)
            # spin for cooling
            stop_event_motor.clear()
            spinMotorRPMTime("CW", 500, ts, 2)
            
            time.sleep(1)
            sistemaMotor.limpiar()
            
        except Exception as e:
            print(f"exception in experiment: {e}")
        sistemaMotor = None
        self.client_temperature.stop()
        self.running_experiment = False
