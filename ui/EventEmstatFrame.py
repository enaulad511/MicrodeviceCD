# -*- coding: utf-8 -*-
import csv
import json
import os
import queue
import re
import socket
import threading
import time
from collections import deque
from typing import Callable

import matplotlib
from matplotlib.figure import Figure

from Drivers.EmstatUtils import (
    EmstatStreamParser,
    LineBufferedSocketReader,
    decode_methodscript_error,
)

matplotlib.use("TkAgg")  # backend para Tk
import tkinter as tk
from tkinter.filedialog import askopenfilename, asksaveasfilename

import matplotlib.pyplot as plt
import ttkbootstrap as ttk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk


class EventPlotter(ttk.Frame):
    """
    Frame embebible en ttkbootstrap que:
    - Envia un scritp de methodscript por tcp
    - Detecta inicio y final del experimento del EMSTAT
    - Parseo de líneas
    - Grafica las variables recibidas en los eventos detectados.
    - Control de inicio/detención desde botones
    """

    def __init__(
        self,
        master,
        method,
        tcp_port=5006,
        udp_port=5005,
        ip_sender="localhost",
        buffer_size=4096,
        max_points=10000,
        update_interval_ms=80,
        title=None,
        x_label="E(V)",
        y_label="I(A)",
        x_key="E_V",
        y_key="I_A",
        payload=None,
        frames_to_hide=None,
        on_end_expriment=lambda x: print(f"Experiment finished: {str(x)}"),
        **kwargs,
    ):
        super().__init__(master, **kwargs)
        # payload para el experimento
        self.payload_exp = payload
        self.on_end_experiment = on_end_expriment
        self.frames_to_hide = [] if frames_to_hide is None else frames_to_hide
        # --- Parámetros de comunicación y plotting ---
        self.tcp_port = tcp_port
        self.ip_sender = ip_sender
        self.buffer_size = buffer_size
        self.callback_motor = None
        self.thread_motor = None
        # Hook opcional disparado UNA vez al llegar el primer emstat_data de la corrida
        # (inicio del barrido). Lo usa SWV como red de seguridad para cortar el motor
        # si el Timer de pre-tratamiento fallara. Se fija en update_val_experiment y se
        # anula tras dispararse (one-shot por corrida).
        self.on_first_data: Callable[[], None] | None = None
        # Indicador de fase del pre-tratamiento (SWV): lista [[nombre, dur_s], ...] de las
        # fases presentes (condition/deposition/equilibration). Mientras el pre-tratamiento
        # corre, el plot no cambia (esos puntos no se grafican), así que mostramos la fase y
        # un contador en la etiqueta de estado para no parecer congelado. Se fija en
        # update_val_experiment; el contador se ancla en emstat_start (_acq_t0) y la
        # transición a barrido la confirma el primer paquete 'sweep' (_sweep_t0).
        self.pretreatment_phases: list | None = None
        self._acq_t0: float | None = None
        self._sweep_t0: float | None = None
        self.max_points = max_points
        self.update_interval_ms = update_interval_ms
        self.prefix_legend = "M-"
        self.legends_list = None
        self.config_legend = None
        # Título por defecto según el método si el llamador no lo fija. cv y sqwv comparten
        # ejes (E vs I) y antes ambos caían en el default "CV", así que el SWV mostraba "CV";
        # eis pasa su propio título. Centralizar aquí evita que cada frame deba recordarlo.
        if title is None:
            title = {"cv": "CV", "sqwv": "SWV", "eis": "EIS (Nyquist)"}.get(
                method, str(method).upper()
            )
        self.title = title
        self.method = method
        self.x_label = x_label
        self.y_label = y_label
        # --- Estado de ejecución ---
        self.q_points = queue.Queue(maxsize=20000)  # grande, pero finita
        self.q_tcp_lines = queue.Queue(maxsize=20000)  # grande, pero finita
        self.q_udp_lines = queue.Queue(maxsize=20000)  # tap UDP paralelo
        self.storage_dict = {}  # registro parcial de informacion
        self.total_data = []  # registro total de informacion
        self.loaded_lines = []  # Line2D agregadas desde archivos CSV cargados
        self.filename_meta = {}  # metadatos (motor, etc.) para incluir en el nombre del CSV
        self.stop_event = threading.Event()
        self._send_lock = threading.Lock()  # serializa sock.sendall entre hilos
        self.reader_th = None
        self.processor_th = None
        self.sock = None
        # --- Tap UDP (recuperación de paquetes perdidos en TCP) ---
        self.udp_port = udp_port
        self.udp_sock = None
        self.udp_reader_th = None
        # Selector de transporte que alimenta la gráfica/CSV (default TCP).
        self.transport_var = tk.StringVar(value="TCP")
        # Retención de datos entre corridas (checkbox). OFF (default): cada Start limpia
        # la corrida anterior. ON: apila cada corrida como traza(s) separada(s).
        self.keep_data_var = tk.BooleanVar(value=False)
        # Copia plana del transporte elegido, fijada en start() (hilo UI) y leída por
        # el hilo procesador: evita acceso cross-thread al StringVar de Tk.
        self._plot_source = "tcp"
        # Cobertura por transporte: set de 'seq' de paquetes emstat_data vistos.
        self.seq_seen = {"tcp": set(), "udp": set()}
        # Diagnóstico: últimas líneas EMSTAT crudas recibidas (cualquier transporte);
        # se vuelca al cerrar para ver CÓMO terminó el stream (p.ej. si tras el último
        # '*' llegó la blank/terminal o la corrida murió por watchdog).
        self._raw_tail = deque(maxlen=20)
        # Merge (Fase 2): seq -> evento data (primer transporte que lo trae gana).
        # Al cerrar se reconstruye la unión ordenada por seq (rellena lo que el
        # transporte primario perdió con lo que trajo el otro).
        self.merged_by_seq = {}
        # Watchdog de inactividad total (s) para cerrar si nadie manda terminal.
        # Bajo el idle de 16s del Pico, con margen sobre huecos legítimos entre paquetes.
        self.watchdog_timeout = 10.0
        self._last_rx = None  # ts del último mensaje EMSTAT (cualquier transporte)
        self._run_started = False  # gate anti-rezago: visto emstat_start/data
        self._terminated = False  # primer terminal gana (cualquier transporte)
        self._coverage_printed = False
        self.running = False
        self.flag_recording = False
        self.after_id = None
        # --- Estado del gráfico ---
        DPI = 100
        WIDTH_PX = 600
        HEIGHT_PX = 250  # ✅ más bajo para pantallas pequeñas
        self.fig = Figure(figsize=(WIDTH_PX / DPI, HEIGHT_PX / DPI), dpi=DPI, layout="compressed")
        plt.style.use("seaborn-v0_8-darkgrid")
        self.ax = self.fig.add_subplot(111)
        self.ax.set_title(self.title)
        self.ax.set_xlabel(self.x_label)
        self.ax.set_ylabel(self.y_label)

        # --- Controles (packed antes que el canvas para que aparezcan arriba) ---
        controls = ttk.Frame(self)
        controls.pack(side=ttk.TOP, fill=ttk.X, pady=(6, 2))
        controls2 = ttk.Frame(self)
        controls2.pack(side=ttk.TOP, fill=ttk.X, pady=(0, 6))

        self.btn_start = ttk.Button(
            controls, text="▶ Start", bootstyle="success", command=self.start
        )
        self.btn_stop = ttk.Button(
            controls,
            text="⏹ Stop",
            bootstyle="danger",
            command=lambda: self.stop(send_abort=True),
            state=ttk.DISABLED,
        )
        self.btn_clear = ttk.Button(
            controls, text="🗑 Clean", bootstyle="secondary", command=self.clear_plot
        )
        self.btn_save = ttk.Button(
            controls, text="💾 Save", bootstyle="secondary", command=self.save_data
        )
        self.btn_load = ttk.Button(
            controls2, text="📂 Load", bootstyle="secondary", command=self.load_data
        )
        self.btn_custom_plot = ttk.Button(
            controls2,
            text="📊 Custom Plot",
            bootstyle="secondary",
            command=self.custom_plot_axes,
        )
        self.btn_analyze = ttk.Button(
            controls2,
            text="🔬 Analyze",
            bootstyle="info",
            command=self.open_analysis_window,
        )
        # Retención de datos entre corridas: si está activo, cada Start apila la nueva
        # corrida en lugar de limpiar la anterior (ver start()/_reconcile_merge()).
        self.chk_keep = ttk.Checkbutton(
            controls2,
            text="Keep runs",
            variable=self.keep_data_var,
            style="Custom.TCheckbutton",
        )
        self.analysis_window = None
        self.lbl_status = ttk.Label(self, text="State: stopped.", anchor="w")
        self.lbl_status.pack(side=ttk.TOP, padx=4)

        self.btn_start.pack(side=ttk.LEFT, padx=4)
        self.btn_stop.pack(side=ttk.LEFT, padx=4)
        self.btn_clear.pack(side=ttk.LEFT, padx=4)
        self.btn_save.pack(side=ttk.LEFT, padx=4)
        self.btn_load.pack(side=ttk.LEFT, padx=4)
        self.btn_custom_plot.pack(side=ttk.LEFT, padx=4)
        self.btn_analyze.pack(side=ttk.LEFT, padx=4)
        self.chk_keep.pack(side=ttk.LEFT, padx=8)

        # Selector de transporte de lectura (TCP/UDP). Fijado antes de Start; ambos
        # transportes se leen y cuentan cobertura siempre, esto solo elige cuál grafica.
        self.cmb_transport = ttk.Combobox(
            controls,
            textvariable=self.transport_var,
            values=["TCP", "UDP"],
            state="readonly",
            width=5,
        )
        self.cmb_transport.pack(side=ttk.RIGHT, padx=4)
        ttk.Label(controls, text="Read:").pack(side=ttk.RIGHT, padx=(8, 0))

        self.canvas_frame = ttk.Frame(self, height=380)
        self.canvas_frame.pack(side=ttk.TOP, fill=ttk.X, padx=1)
        self.canvas_frame.pack_propagate(False)

        self.canvas = FigureCanvasTkAgg(self.fig, self.canvas_frame)
        self.canvas.get_tk_widget().pack(fill=ttk.BOTH, expand=True)

        self.toolbar = NavigationToolbar2Tk(self.canvas, self, pack_toolbar=False)
        self.toolbar.pack(side=ttk.TOP, fill=ttk.X)

        # Por medición (m): deques y Line2D
        self.x_key = x_key
        self.y_key = y_key
        self.x_by_m = {}
        self.y_by_m = {}
        self.lines_by_m = {}
        # Retención entre corridas: clave de línea -> (run, cycle) para etiquetas
        # adaptativas, desplazamiento de clave por corrida e índice de corrida.
        self.key_meta = {}
        # Kwargs extra para construir los parsers de la corrida (p.ej. EIS E_dc Scan
        # pasa eis_group_by_potential=True). Se fijan en update_val_experiment.
        self.parser_kwargs = {}
        # Leyenda por valor de evento: (clave, formato), p.ej. ("E_V", "E={:.3g}V")
        # para etiquetar cada espectro EIS con su potencial. None -> R{run}c{cycle}.
        self.cycle_legend = None
        self.cycle_label_values = {}  # clave de línea -> valor para la leyenda
        self.plot_run_offset = 0
        self.run_index = 0
        self._run_td_start = 0  # offset en total_data donde empieza la corrida actual
        self._style_cycle = self._build_style_cycle()

        # self.pack(fill=ttk.BOTH, expand=True)

    def on_close(self):
        """Limpia y detiene hilo lector."""
        self.stop()
        # self.clear_plot()
        self.destroy()

    def change_axes_text(self, title, x_label, y_label):
        """Cambia títulos y etiquetas del gráfico."""
        self.title = title
        self.x_label = x_label
        self.y_label = y_label
        self.ax.set_title(self.title)
        self.ax.set_xlabel(self.x_label)
        self.ax.set_ylabel(self.y_label)
        self.canvas.draw_idle()

    def hide_frames(self, flag=True):
        if flag:
            for item in self.frames_to_hide:
                item.grid_remove()
        else:
            for item in self.frames_to_hide:
                item.grid()

    # ---------------------------
    # API pública
    # ---------------------------
    def start(self):
        """Crea socket, lanza hilo TCP productor y procesador."""
        print("Starting TCP reader")
        if self.running:
            self._set_status("Already running.")
            return

        try:
            print(self.ip_sender, self.tcp_port)
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((self.ip_sender, self.tcp_port))

            # TCP streaming robusto
            self.sock.settimeout(None)  # TCP en modo bloqueante
            self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self.hide_frames(flag=True)
        except OSError as e:
            self._set_status(f"Socket Error: {e}")
            return
        print("reseting states")
        # Reset estado
        self.stop_event.clear()
        self.flag_recording = True
        self.running = True

        # Reset cobertura/estado del tap para esta corrida
        self.seq_seen = {"tcp": set(), "udp": set()}
        self._raw_tail.clear()
        self.merged_by_seq = {}
        self._last_rx = None
        self._run_start_ts = time.time()  # para el watchdog de "nunca arranco"
        self._run_started = False
        self._terminated = False
        self._coverage_printed = False
        self._acq_t0 = None  # ancla del contador de fase (se fija en emstat_start)
        self._sweep_t0 = None  # marca de inicio del barrido (primer paquete 'sweep')
        self._plot_source = self.transport_var.get().lower()  # fija el transporte a graficar
        with self.q_udp_lines.mutex:
            self.q_udp_lines.queue.clear()
        with self.q_tcp_lines.mutex:
            self.q_tcp_lines.queue.clear()

        # Retención entre corridas. OFF: limpia la corrida anterior (conserva las líneas
        # cargadas de CSV); la nueva arranca con offset 0. ON: apila la nueva corrida
        # sobre lo que ya esté graficado (offset = clave máxima + 1, sin limpiar).
        if not self.keep_data_var.get():
            self._reset_live_plot()
            self.plot_run_offset = 0
        else:
            self.plot_run_offset = (max(self.lines_by_m) + 1) if self.lines_by_m else 0
        self.run_index += 1
        self._run_td_start = len(self.total_data)

        # Socket UDP del tap (broadcast 5005, paralelo al control TCP). Si falla el
        # bind (p.ej. dev/Windows sin red), degrada a TCP-only sin abortar la corrida.
        self.udp_sock = self._create_udp_tap()

        # Lanza hilo productor (solo lectura TCP)
        self.reader_th = threading.Thread(target=self._tcp_reader, daemon=True, name="TCPReader")
        self.reader_th.start()

        # Lanza hilo lector UDP del tap (si hay socket)
        if self.udp_sock is not None:
            self.udp_reader_th = threading.Thread(
                target=self._udp_reader, daemon=True, name="UDPReader"
            )
            self.udp_reader_th.start()

        # Lanza hilo consumidor unificado (parsea ambos transportes y aplica la lógica)
        self.processor_th = threading.Thread(
            target=self._processor, daemon=True, name="EmstatProcessor"
        )
        self.processor_th.start()
        if self.callback_motor is not None:
            self.thread_motor = self.callback_motor()
        # UI
        self.btn_start.configure(state=ttk.DISABLED)
        self.btn_stop.configure(state=ttk.NORMAL)
        self.cmb_transport.configure(state=ttk.DISABLED)
        self.chk_keep.configure(state=ttk.DISABLED)
        tap = "TCP+UDP" if self.udp_sock is not None else "TCP-only"
        self._set_status(
            f"{tap} | plot={self.transport_var.get()} | {self.ip_sender}:{self.tcp_port}"
        )
        self._schedule_update()

    def stop(self, send_abort=False):
        """Detiene hilo lector, cierra socket y cancela actualizaciones.

        send_abort=True (clic del usuario en ⏹ Stop) envia primero
        ``{"cmd":"ABORT"}`` al Pico para cancelar en caliente el experimento del
        EmStat (el Pico responde con ``Z\\n`` -> ``on_finished:`` -> celda apagada
        y libera el canal MCP). En las salidas disparadas por el firmware
        (emstat_end/error/aborted/maxtime/timeout) el experimento ya termino, asi
        que send_abort=False y no se envia ABORT.
        """

        if not self.running:
            return
        print("Stopping …")
        # Aborto en caliente del experimento (solo si lo pide el usuario y sigue vivo)
        if send_abort and self.sock is not None:
            try:
                with self._send_lock:
                    self.sock.sendall(b'{"cmd":"ABORT"}\n')
                print("ABORT enviado al Pico")
            except Exception as e:
                print(f"No se pudo enviar ABORT: {e}")
        self.total_data.append(self.storage_dict.copy())
        self.storage_dict.clear()
        self.stop_event.set()
        try:
            if self.sock:
                self.sock.close()
        except Exception:
            pass
        self.sock = None
        try:
            if self.udp_sock:
                self.udp_sock.close()
        except Exception:
            pass
        self.udp_sock = None

        # Esperar hilos (rápido gracias al timeout de los sockets)
        try:
            if self.reader_th and self.reader_th.is_alive():
                self.reader_th.join(timeout=0.5)
        except Exception:
            pass
        try:
            if self.udp_reader_th and self.udp_reader_th.is_alive():
                self.udp_reader_th.join(timeout=0.5)
        except Exception:
            pass
        try:
            if self.processor_th and self.processor_th.is_alive():
                self.processor_th.join(timeout=0.5)
        except Exception:
            pass
        self.running = False
        self.flag_recording = False
        self._print_coverage()  # resumen de cobertura TCP vs UDP (Fase 0)
        # Fase 2: reconcilia TCP+UDP por seq y redibuja en el hilo UI (matplotlib/Tk
        # no son thread-safe; stop() puede venir del hilo procesador).
        try:
            self.after(0, self._reconcile_merge)
        except Exception:
            pass
        self.btn_start.configure(state=ttk.NORMAL)
        self.btn_stop.configure(state=ttk.DISABLED)
        self.cmb_transport.configure(state="readonly")
        self.chk_keep.configure(state=ttk.NORMAL)
        self._cancel_update()
        # No pisar el estado final ya publicado por un terminal/watchdog
        # (end/error/aborted/maxtime/timeout); solo el stop manual reporta aquí.
        if not self._terminated:
            self._set_status("Stopped by user.")
        self.on_end_experiment(self.thread_motor)
        self.thread_motor = None

    def clear_plot(self):
        """Limpia datos y resetea el gráfico (wipe total: incluye líneas cargadas)."""
        self.storage_dict.clear()
        self.total_data.clear()
        self.merged_by_seq.clear()
        self.x_by_m.clear()
        self.y_by_m.clear()
        self.lines_by_m.clear()
        self.loaded_lines.clear()
        self.key_meta.clear()
        self.cycle_label_values.clear()
        self.plot_run_offset = 0
        self.run_index = 0
        self._run_td_start = 0
        with self.q_points.mutex:
            self.q_points.queue.clear()

        self.ax.clear()
        self.ax.set_title(self.title)
        self.ax.set_xlabel(self.x_label)
        self.ax.set_ylabel(self.y_label)
        self.ax.legend([], [])
        self.canvas.draw_idle()

    def _reset_live_plot(self):
        """Limpia SOLO los datos de experimento en vivo (deja las líneas cargadas de
        CSV en self.loaded_lines). Lo usa start() cuando 'Keep runs' está apagado para
        empezar una corrida en limpio sin borrar las trazas de referencia."""
        for ln in self.lines_by_m.values():
            try:
                ln.remove()
            except Exception:
                pass
        self.lines_by_m.clear()
        self.x_by_m.clear()
        self.y_by_m.clear()
        self.key_meta.clear()
        self.cycle_label_values.clear()
        self.total_data.clear()
        self.merged_by_seq.clear()
        with self.q_points.mutex:
            self.q_points.queue.clear()
        self.plot_run_offset = 0
        self.run_index = 0

    def save_data(self):
        """
        Create CSV from data stored
        """
        if self.running:
            self._set_status("Stop aquisition before saving data.")
            return
        if not self.total_data:
            self._set_status("No data to save.")
            return
        print("Saving data …")
        os.makedirs("files", exist_ok=True)
        suffix = self._build_filename_suffix()
        initialfile = f"{self.method}_data_{time.strftime('%Y%m%d_%H%M%S')}{suffix}.csv"
        filename = asksaveasfilename(
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
        # Columnas extra TRAILING (Load solo lee las 5 primeras, así que no rompen
        # la recarga): campos EIS presentes en los eventos que no sean ya x/y, mas la
        # fase SWV ("pretreatment"/"sweep") para distinguir el pre-tratamiento conservado.
        extra_keys = [
            k
            for k in ("freq_Hz", "E_V", "t_s", "Z_mod", "phase")
            if k not in (self.x_key, self.y_key) and any(k in ev for ev in self.total_data)
        ]
        try:
            with open(filename, "w") as f:
                header = f"sample,{self.x_key}, {self.y_key}, cycle, run"
                header += "".join(f", {k}" for k in extra_keys)
                f.write(header + "\n")
                for index, event in enumerate(self.total_data):
                    row = (
                        f"{index}, {event.get(self.x_key)}, {event.get(self.y_key)},"
                        f" {event.get('cycle')}, {event.get('run', 1)}"
                    )
                    row += "".join(f", {event.get(k, '')}" for k in extra_keys)
                    f.write(row + "\n")
            self._set_status(f"Data saved to file: {os.path.basename(filename)}")
        except Exception as e:
            self._set_status(f"Error saving data: {e}")

    def _build_filename_suffix(self):
        """Construye un sufijo '_k1v1_k2v2…' a partir de self.filename_meta."""
        if not self.filename_meta:
            return ""
        parts = []
        for k, v in self.filename_meta.items():
            sv = "".join(c if c.isalnum() or c in "-." else "_" for c in str(v))
            sk = "".join(c if c.isalnum() else "_" for c in str(k))
            parts.append(f"{sk}{sv}")
        return "_" + "_".join(parts) if parts else ""

    def load_data(self):
        """Carga un CSV previamente guardado por save_data y lo grafica como
        líneas adicionales (una por ciclo) sobre el mismo eje, sin tocar las
        mediciones live almacenadas en self.lines_by_m."""
        path = askopenfilename(
            title="Select CSV to load",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not path:
            self._set_status("No file selected.")
            return
        # Agrupa por (run, cycle): un CSV multi-corrida recarga como trazas distintas.
        # La columna 'run' es opcional (trailing); si falta se asume run=0 (compat).
        cycles_x = {}
        cycles_y = {}
        try:
            with open(path, newline="") as f:
                reader = csv.reader(f, skipinitialspace=True)
                next(reader, None)  # descarta header
                for row in reader:
                    if len(row) < 4:
                        continue
                    try:
                        x = float(row[1])
                        y = float(row[2])
                        cycle = int(float(row[3]))
                        run = int(float(row[4])) if len(row) >= 5 else 0
                    except (ValueError, TypeError):
                        continue
                    cycles_x.setdefault((run, cycle), []).append(x)
                    cycles_y.setdefault((run, cycle), []).append(y)
        except Exception as e:
            self._set_status(f"Error loading data: {e}")
            print(f"Error loading data: {e}")
            return
        if not cycles_x:
            self._set_status("No data parsed from file.")
            return
        label_base = os.path.splitext(os.path.basename(path))[0]
        for run, cycle in sorted(cycles_x.keys()):
            (line,) = self.ax.plot(
                cycles_x[(run, cycle)],
                cycles_y[(run, cycle)],
                linestyle="--",
                linewidth=1.5,
                alpha=0.7,
                marker="x",
                markersize=3,
                label=f"{label_base}-r{run}c{cycle}",
            )
            self.loaded_lines.append(line)
        self.ax.relim()
        self.ax.autoscale_view()
        self._update_legends()
        self._set_status(f"Loaded {len(cycles_x)} trace(s) from {os.path.basename(path)}")

    def update_val_experiment(
        self,
        x_key,
        y_key,
        payload,
        ip_sender,
        callback_spin_motor,
        filename_meta=None,
        parser_kwargs=None,
        cycle_legend=None,
        on_first_data=None,
        pretreatment_phases=None,
    ):
        if self.flag_recording:
            print("not posible to update payload while running experiment")
            return
        self.x_key = x_key
        self.y_key = y_key
        self.payload_exp = payload
        self.ip_sender = ip_sender
        self.callback_motor = callback_spin_motor
        # Se reasignan SIEMPRE (incluido None) para no arrastrar el hook / las fases de una
        # corrida anterior a una nueva sin motor / sin pre-tratamiento.
        self.on_first_data = on_first_data
        self.pretreatment_phases = pretreatment_phases
        # Se reasignan SIEMPRE (no solo si vienen): el mismo plotter alterna modos
        # entre corridas (EIS) y un valor viejo contaminaría la corrida nueva.
        self.parser_kwargs = dict(parser_kwargs) if parser_kwargs else {}
        self.cycle_legend = cycle_legend
        if filename_meta is not None:
            self.filename_meta = dict(filename_meta)

    def custom_plot_axes(self):
        if self.config_legend is not None:
            # bring to the front
            self.config_legend.lift()
        else:
            self.config_legend = LegendManagerWindow(self, plotter=self)

    def open_analysis_window(self):
        if self.analysis_window is not None:
            try:
                if self.analysis_window.winfo_exists():
                    self.analysis_window.lift()
                    return
            except Exception:
                pass
        from ui.analysis import AnalysisWindow

        self.analysis_window = AnalysisWindow(self, plotter=self)

    def _on_analysis_window_closed(self):
        self.analysis_window = None

    def on_close_config_legend(self, legend_list, prefix_legend="M-"):
        # self.config_legend.destroy()
        self.config_legend = None
        self.legends_list = legend_list if legend_list and len(legend_list) > 0 else None
        self.prefix_legend = prefix_legend
        self._update_legends()

    # ---------------------------
    # Hilo lector TCP (control + datos) y tap UDP paralelo
    # ---------------------------
    def _tcp_reader(self):
        print(f"starting tcp on port {self.tcp_port} and address {self.ip_sender} …")
        self.flag_recording = False
        if self.sock is None:
            print("First create a socket")
            return
        with self._send_lock:
            self.sock.sendall((json.dumps(self.payload_exp) + "\n").encode())
        self.flag_recording = True
        reader = LineBufferedSocketReader(self.sock)
        start_time = time.time()
        while not self.stop_event.is_set():
            # Keepalive SOLO para mantener control TCP
            if time.time() - start_time > 120:
                try:
                    with self._send_lock:
                        self.sock.sendall(b'{"type":"keepalive"}\n')
                    start_time = time.time()
                except Exception:
                    pass  # si falla, TCP ya murió y no es crítico
            lines = reader.read_lines()
            if lines is None:
                print("TCP closed by server (expected for long runs)")
                break
            for line in lines:
                try:
                    self.q_tcp_lines.put_nowait(line)
                except Exception:
                    # si la cola se llena, descarta (mejor que bloquear TCP)
                    pass
        self.flag_recording = False
        # IMPORTANTE: el cierre de TCP NO termina la corrida. Antes aquí se hacía
        # stop_event.set(), lo que mataba el tap UDP justo cuando se necesita para
        # recuperar paquetes/terminal perdidos en TCP. Ahora solo muere el lector
        # TCP; la corrida la cierra un terminal (cualquier transporte), Stop o el
        # watchdog de inactividad del procesador. El socket lo cierra stop().
        print("TCP reader detenido (control TCP cerrado; el tap UDP sigue vivo).")
        self.reader_th = None

    def _create_udp_tap(self):
        """Crea el socket UDP del tap (broadcast 5005, paralelo al control TCP).

        SO_REUSEADDR + (SO_REUSEPORT donde exista) para convivir con el UdpClient de
        temperatura en el mismo puerto; SO_BROADCAST para recibir los broadcasts del
        Wemos; RCVBUF grande para no perder paquetes en ráfagas. Devuelve None y
        degrada a TCP-only si el bind falla (p.ej. dev/Windows sin red)."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if hasattr(socket, "SO_REUSEPORT"):
                try:
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                except OSError:
                    pass
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            try:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 20)
            except OSError:
                pass
            s.bind(("", self.udp_port))
            s.settimeout(0.2)
            print(f"UDP tap escuchando en :{self.udp_port}")
            return s
        except OSError as e:
            print(f"UDP tap no disponible ({e}); sigo en TCP-only")
            return None

    def _udp_reader(self):
        """Lee el broadcast UDP y encola las líneas EMSTAT: (descarta temperatura/beacons).
        1 datagrama = 1 mensaje; tolera prefijos basura buscando 'EMSTAT:' por substring."""
        sock = self.udp_sock
        if sock is None:
            return
        while not self.stop_event.is_set():
            try:
                data, _addr = sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break
            text = data.decode("utf-8", errors="replace")
            idx = text.find("EMSTAT:")
            if idx < 0:
                continue  # temperatura (UDP:...) / beacon (CD_DISCOVERY:...) / ruido
            try:
                self.q_udp_lines.put_nowait(text[idx:].strip())
            except Exception:
                pass
        print("UDP reader detenido.")
        self.udp_reader_th = None

    def _processor(self):
        """Consumidor unificado: drena ambas colas (TCP y UDP), cada una con su propio
        parser (stateful), aplica la lógica y mantiene la cobertura por transporte.
        La corrida termina por: primer terminal de cualquier transporte (Fase 1),
        Stop, o watchdog de inactividad total."""
        parsers = {
            "tcp": EmstatStreamParser(experiment=self.method, **self.parser_kwargs),
            "udp": EmstatStreamParser(experiment=self.method, **self.parser_kwargs),
        }
        while not self.stop_event.is_set():
            got = False
            for _ in range(256):
                try:
                    line = self.q_tcp_lines.get_nowait()
                except queue.Empty:
                    break
                got = True
                self._handle_emstat_line(line, "tcp", parsers["tcp"])
                if self.stop_event.is_set():
                    break
            for _ in range(256):
                try:
                    line = self.q_udp_lines.get_nowait()
                except queue.Empty:
                    break
                got = True
                self._handle_emstat_line(line, "udp", parsers["udp"])
                if self.stop_event.is_set():
                    break
            if self.stop_event.is_set():
                break
            if not got:
                # Watchdog: si arrancó la corrida y nadie manda nada por un rato,
                # cerramos (red de seguridad ante un terminal perdido en ambos).
                if (
                    self._run_started
                    and self._last_rx is not None
                    and (time.time() - self._last_rx) > self.watchdog_timeout
                    and not self._terminated
                ):
                    self._terminated = True
                    print(f"WATCHDOG: sin paquetes por {self.watchdog_timeout}s; cierro corrida")
                    self._set_status("Watchdog: total inactivity, run closed.")
                    self.stop_event.set()
                    break
                # Watchdog de arranque: conecto el TCP, mando el payload, pero el Pico
                # nunca respondio (ni emstat_start ni JSON_PARSE) -> el comando se perdio
                # corrupto/entero en el UART_LINK. Sin esto la corrida se cuelga para
                # siempre tras "starting tcp". Doblamos el timeout normal como margen.
                if (
                    not self._run_started
                    and not self._terminated
                    and (time.time() - self._run_start_ts) > (2 * self.watchdog_timeout)
                ):
                    self._terminated = True
                    print("WATCHDOG: el experimento nunca arranco; cierro corrida")
                    self._set_status("Watchdog: Pico did not respond (lost command?); retry.")
                    self.stop_event.set()
                    break
                time.sleep(0.01)
        print("Processor detenido.")
        self.processor_th = None
        self.stop(send_abort=False)

    def _handle_emstat_line(self, line, source, parser):
        """Procesa una "línea" EMSTAT de un transporte. Una línea puede traer VARIOS
        mensajes pegados: si el buffer RX del UART del Wemos se desborda en un mensaje
        largo (p.ej. emstat_start, que lleva todos los params) se pierde el '\\n' y el
        siguiente mensaje queda concatenado. Partimos por el marcador 'EMSTAT:' y
        procesamos cada segmento por separado, así un segmento truncado no se traga al
        mensaje válido que viene pegado."""
        if "EMSTAT:" not in line:
            return
        # Guard temporal (hardcode): un error de MethodSCRIPT (e!####:) en CUALQUIER
        # parte del payload se maneja como fatal, aunque venga en un mensaje truncado/
        # pegado que no parsea como JSON. Independiente del framing; el split de abajo
        # no siempre lo rescata si el segmento del error quedó cortado.
        m = re.search(r'e!\d{3,}:[^"}]*', line)
        if m:
            self._handle_methodscript_error(m.group(0), source)
            return
        for seg in line.split("EMSTAT:"):
            seg = seg.strip()
            if not seg:
                continue
            try:
                msg = json.loads(seg)
            except Exception:
                # Segmento truncado/corrupto. Si trae un error de MethodSCRIPT (e!####)
                # lo surfaceamos igual; si no, lo registramos y seguimos con el resto.
                if "e!" in seg.lower():
                    self._handle_methodscript_error(seg, source)
                else:
                    print(f"JSON parcial/corrupto descartado [{source}]: {seg[:80]}")
                continue
            if isinstance(msg, dict):
                self._handle_emstat_msg(msg, source, parser)

    def _handle_emstat_msg(self, msg, source, parser):
        """Aplica la lógica de un mensaje EMSTAT ya parseado. Cuenta cobertura por 'seq'
        (ambos transportes) pero solo grafica/almacena el transporte seleccionado
        (Fase 0). Cierra con el primer terminal/error de cualquier transporte (Fase 1)."""
        self._last_rx = time.time()
        mtype = msg.get("type")
        seq = msg.get("seq")
        selected = source == self._plot_source

        # Cola de diagnóstico (se imprime al cerrar): datos con su raw recortado,
        # el resto solo con su type — suficiente para ver cómo terminó el stream.
        if mtype == "emstat_data":
            self._raw_tail.append(f"{source} seq={seq} {str(msg.get('raw', ''))[:70]}")
        else:
            self._raw_tail.append(f"{source} seq={seq} <{mtype}>")

        if mtype is None:
            # Mensaje EMSTAT sin 'type' reconocido. El Pico emite
            # {"error":"JSON_PARSE", ...} cuando el comando ENTRANTE llego corrupto por
            # el UART_LINK (p.ej. el JSON largo de SWV desbordo su RX). Antes esto se
            # descartaba en silencio y la corrida quedaba colgada esperando datos que
            # nunca llegarian (el watchdog solo dispara tras _run_started). Lo
            # surfaceamos y cerramos: el experimento no va a arrancar, hay que reintentar.
            err = msg.get("error")
            if err and not self._terminated:
                self._terminated = True
                detail = f"Pico rechazo el comando ({err}); reintenta (via {source.upper()})."
                print(f"PICO ERROR [{source}]: {msg}")
                self._set_status(detail)
                self.stop_event.set()
            return

        if mtype == "emstat_start":
            self._run_started = True
            if self._acq_t0 is None:
                self._acq_t0 = time.time()  # ancla del contador de fase del pre-tratamiento
            return

        if mtype == "script_dbg":
            # Eco de diagnóstico del script enviado al EmStat (DEBUG_ECHO_SCRIPT en el Pico).
            print(f"  SCRIPT[{msg.get('line')}]: {msg.get('text')!r}")
            return

        if isinstance(mtype, str) and mtype.endswith("_dbg"):
            # Debug del firmware (p.ej. wemos_dbg: ciclo de vida del cliente TCP). Llega
            # por el broadcast UDP; lo imprimimos para diagnosticar sin acceso al serial
            # del Wemos/Pico. Apagar con DEBUG_TCP=false (Wemos) cuando ya no se necesite.
            print(f"  DBG[{source}/{mtype}]: {msg.get('msg', msg)}")
            return

        if mtype == "emstat_data":
            self._run_started = True
            if seq is not None:
                self.seq_seen[source].add(seq)
            raw = msg.get("raw", "")
            event = parser.feed_raw(raw)
            if not event:
                return
            etype = event.get("type")
            if etype == "error":
                # Error de MethodSCRIPT (e!####) embebido en un emstat_data: el EmStat
                # rechazó el script. Fatal -> mostrar y cerrar la corrida.
                self._handle_methodscript_error(event.get("raw", raw), source)
                return
            if etype == "data":
                if self._acq_t0 is None:
                    self._acq_t0 = time.time()  # fallback si se perdió emstat_start
                # Inicio real del barrido = primer paquete cuya fase != "pretreatment".
                # Marca _sweep_t0 (corta el contador de fase) y dispara la red de
                # seguridad del motor (el pre-tratamiento TAMBIEN emite datos, así que el
                # 1er emstat_data NO es el barrido). One-shot, desde cualquier transporte;
                # los handlers solo deben tocar cosas thread-safe.
                if self._sweep_t0 is None and event.get("phase") != "pretreatment":
                    self._sweep_t0 = time.time()
                    if self.pretreatment_phases:
                        self._set_status("Sweep — acquiring…")
                    if self.on_first_data is not None:
                        cb = self.on_first_data
                        self.on_first_data = None
                        try:
                            cb()
                        except Exception as e:
                            print(f"on_first_data hook error: {e}")
                # Fase 2: guarda el evento por seq (ambos transportes; el primero que
                # llega gana). Al cerrar se reconstruye la unión ordenada -> rellena lo
                # que el primario perdió con lo que trajo el otro.
                if seq is not None:
                    event["seq"] = seq
                    event["source"] = source
                    self.merged_by_seq.setdefault(seq, event)
                if selected:  # el transporte elegido alimenta la gráfica en vivo
                    event["run"] = self.run_index
                    # El pre-tratamiento SWV (phase="pretreatment") se CONSERVA en
                    # total_data (CSV) pero NO se grafica: solo aporta ruido (clusters a
                    # E constante). Solo los puntos del barrido alimentan la gráfica.
                    self.total_data.append(event)
                    if event.get("phase") != "pretreatment":
                        # Clave de línea desplazada por corrida (retención): cycle crudo se
                        # conserva en el evento; run etiqueta la corrida para leyenda/CSV.
                        cyc = event.get("cycle", 0)
                        m = self.plot_run_offset + cyc
                        self.key_meta.setdefault(m, (self.run_index, cyc))
                        self._capture_cycle_label(m, event)
                        try:
                            self.q_points.put_nowait(
                                (
                                    event.get(self.x_key, 0.0),
                                    event.get(self.y_key, 0.0),
                                    m,
                                )
                            )
                        except Exception:
                            pass
            elif "method" in etype and selected:
                if etype == "method":
                    name = event.get("method_name", "")
                    self._set_status(f"Method: {name} (id {event['method_id']})")
                    print("Method:", event["method_id"], name)
                elif etype == "method_end":
                    self._set_status(f"Method: {etype}")
            return

        if mtype in (
            "emstat_end",
            "emstat_error",
            "emstat_aborted",
            "emstat_maxtime",
            "emstat_timeout",
        ):
            # Fase 1: el primer terminal de CUALQUIER transporte cierra limpio
            # (send_abort=False; el experimento ya terminó en el Pico). Gate
            # anti-rezago: solo se honra tras ver start/data de la corrida actual,
            # para que un broadcast viejo no corte una corrida nueva.
            if not self._run_started or self._terminated:
                return
            self._terminated = True
            if mtype == "emstat_end":
                status = f"End of experiment (via {source.upper()})."
            else:
                status = f"{self._format_terminal_status(msg)} (via {source.upper()})"
            print(f"TERMINAL [{source}]: {status}")
            self._set_status(status)
            self.stop_event.set()

    def _handle_methodscript_error(self, raw, source):
        """Surface + cierre ante un error de MethodSCRIPT (e!####) del EmStat. Es fatal:
        el script fue rechazado y no vendrán datos. NO se manda ABORT (ante un error de
        parseo la celda no llegó a encenderse). Idempotente: cierra una sola vez.
        Decodifica el código (Appendix A) y la ubicación para un mensaje legible."""
        info = decode_methodscript_error(raw)
        if info.get("code"):
            desc = info.get("description") or "código desconocido"
            loc = ""
            if info.get("line") is not None:
                loc = f" @ L{info['line']}:C{info.get('col', '?')}"
            detail = f"{info['code']} ({desc}){loc}"
        else:
            detail = str(raw).strip()
        print(f"METHODSCRIPT ERROR [{source}]: {detail}")
        if self._terminated:
            return
        self._terminated = True
        self._set_status(f"MethodSCRIPT error: {detail} (via {source.upper()})")
        self.stop_event.set()

    def _print_coverage(self):
        """Resumen en consola de cobertura TCP vs UDP por 'seq' de paquetes data (Fase 0).
        El 'solo-UDP' es la evidencia de pérdida en TCP; el 'solo-TCP' mide si UDP también
        pierde; 'perdidos por AMBOS' = huecos en la unión sobre [min,max] (el seq de los
        emstat_data es contiguo en corrida), que es lo que el merge TCP+UDP NO podría
        recuperar -> si es 0, la unión es el dataset completo."""
        if self._coverage_printed:
            return
        self._coverage_printed = True
        # Cola de diagnóstico: cómo terminó el stream (¿llegó '*'? ¿terminal?).
        if self._raw_tail:
            print(f"TAIL (últimos {len(self._raw_tail)} mensajes EMSTAT):")
            for entry in self._raw_tail:
                print("   ", entry)
        tcp = self.seq_seen["tcp"]
        udp = self.seq_seen["udp"]
        only_udp = sorted(udp - tcp)
        only_tcp = sorted(tcp - udp)
        union = tcp | udp
        cap = 60

        def _fmt(xs):
            return f"{xs[:cap]}{' …(+%d)' % (len(xs) - cap) if len(xs) > cap else ''}"

        lost_both = []
        if union:
            lo, hi = min(union), max(union)
            lost_both = [s for s in range(lo, hi + 1) if s not in union]

        print("=" * 56)
        print(f"COBERTURA EMSTAT '{self.method}' (paquetes data por seq)")
        print(f"  TCP={len(tcp)}  UDP={len(udp)}  union={len(union)}")
        print(f"  solo-UDP (perdidos en TCP): {len(only_udp)} -> {_fmt(only_udp)}")
        print(f"  solo-TCP (perdidos en UDP): {len(only_tcp)} -> {_fmt(only_tcp)}")
        print(f"  perdidos por AMBOS (huecos en la unión): {len(lost_both)} -> {_fmt(lost_both)}")
        if union:
            print(
                f"  pérdida TCP={100 * len(only_udp) / len(union):.1f}%  "
                f"pérdida UDP={100 * len(only_tcp) / len(union):.1f}%"
            )
            if not lost_both:
                print("  => MERGE TCP+UDP = dataset COMPLETO (unión sin huecos)")
            else:
                print(f"  => merge dejaría {len(lost_both)} hueco(s) reales (perdidos por ambos)")
        print("=" * 56)

    def _reconcile_merge(self):
        """Fase 2 (al cerrar): fusiona TCP+UDP por 'seq'. El transporte primario ya
        graficó en vivo; aquí se reconstruye la UNIÓN ordenada por seq -> rellena los
        seq que el primario perdió con los que trajo el otro transporte, reordena, redibuja
        el dataset completo y lo deja en total_data para Save. Corre en el hilo UI."""
        if not self.merged_by_seq:
            return
        primary = self.seq_seen.get(self._plot_source, set())
        ordered_seq = sorted(self.merged_by_seq)
        filled = sum(1 for s in ordered_seq if s not in primary)
        ordered = [self.merged_by_seq[s] for s in ordered_seq]
        for ev in ordered:
            ev["run"] = self.run_index

        # Reemplaza SOLO la porción de esta corrida en total_data (para Save) — con
        # retención ON conserva las corridas anteriores ya almacenadas.
        self.total_data[self._run_td_start :] = ordered

        # Limpia/reconstruye SOLO las líneas de esta corrida (claves >= offset); las
        # corridas anteriores (claves < offset) quedan intactas en el gráfico.
        for m in [k for k in list(self.lines_by_m) if k >= self.plot_run_offset]:
            try:
                self.lines_by_m[m].remove()
            except Exception:
                pass
            self.lines_by_m.pop(m, None)
            self.x_by_m.pop(m, None)
            self.y_by_m.pop(m, None)
            self.key_meta.pop(m, None)
            self.cycle_label_values.pop(m, None)

        for ev in ordered:
            # El pre-tratamiento SWV queda en total_data (CSV) pero fuera del plot,
            # igual que en vivo (ver _handle_emstat_msg).
            if ev.get("phase") == "pretreatment":
                continue
            cyc = ev.get("cycle", 0)
            m = self.plot_run_offset + cyc
            self.key_meta.setdefault(m, (self.run_index, cyc))
            self._capture_cycle_label(m, ev)
            self._get_or_create_line(m)  # crea deque + Line2D para esta corrida/ciclo
            self.x_by_m[m].append(ev.get(self.x_key, 0.0))
            self.y_by_m[m].append(ev.get(self.y_key, 0.0))
        for m, line in self.lines_by_m.items():
            line.set_data(self.x_by_m[m], self.y_by_m[m])
        self.ax.relim()
        self.ax.autoscale_view()
        self._update_legends()
        self.canvas.draw_idle()
        print(f"MERGE: dataset={len(ordered)} puntos; recuperados del otro transporte: {filled}")
        # Anexa el resumen al estado terminal en vez de reemplazarlo, p.ej.
        # "End of experiment (via TCP). Merge: 250 pts (+3 recovered)".
        self._set_status(
            f"{self.lbl_status.cget('text')} Merge: {len(ordered)} pts (+{filled} recovered)"
        )

    @staticmethod
    def _format_terminal_status(msg):
        """Construye un texto legible para los cierres terminales del firmware."""
        mtype = msg.get("type")
        if mtype == "emstat_error":
            err = msg.get("error", "unknown")
            ch = msg.get("ch")
            return f"EmStat error: {err}" + (f" (ch={ch})" if ch is not None else "")
        if mtype == "emstat_aborted":
            clean = msg.get("clean")
            return f"Experiment aborted (cell {'off' if clean else 'unknown'})."
        if mtype == "emstat_maxtime":
            return "Experiment stopped: max time exceeded."
        if mtype == "emstat_timeout":
            connected = msg.get("connected")
            return f"EmStat timeout (reconnected={connected})."
        return f"Experiment ended: {mtype}"

    # ---------------------------
    # Loop de actualización (UI)
    # ---------------------------
    def _schedule_update(self):
        self.after_id = self.after(self.update_interval_ms, self._update_plot)

    def _cancel_update(self):
        if self.after_id is not None:
            try:
                self.after_cancel(self.after_id)
            except Exception:
                pass
            self.after_id = None

    def _update_plot(self):
        """Drena la cola y actualiza las líneas; reprograma con after()."""
        drained = 0
        while True:
            try:
                v, i, m = self.q_points.get_nowait()
            except queue.Empty:
                break
            line = self._get_or_create_line(m)
            self.x_by_m[m].append(v)
            self.y_by_m[m].append(i)
            drained += 1

        if drained > 0:
            for m, line in self.lines_by_m.items():
                xs = self.x_by_m[m]
                ys_ = self.y_by_m[m]
                if len(xs) > 0:
                    line.set_data(xs, ys_)
            self.ax.relim()
            self.ax.autoscale_view()
            # Actualiza leyenda por si hay nuevas líneas

            self._update_legends()

        # Indicador de fase del pre-tratamiento (el plot no cambia ahí; evita parecer
        # congelado). Se ejecuta en el mismo loop UI, sin timer aparte.
        self._refresh_phase_status()

        # Reprogramar si seguimos corriendo
        if self.running:
            self._schedule_update()

    def _refresh_phase_status(self):
        """Mientras corre el pre-tratamiento SWV, muestra la fase actual y un contador en
        la etiqueta de estado (p.ej. 'Pre-treatment — Deposition  34/60 s'). Time-based:
        usa las duraciones de self.pretreatment_phases ancladas en _acq_t0 (emstat_start).
        Se apaga al llegar el primer paquete de barrido (_sweep_t0) — esa transición es
        data-driven, así que el desfase de latencia solo afecta a las cotas intermedias."""
        if not self.pretreatment_phases or self._acq_t0 is None or self._sweep_t0 is not None:
            return
        elapsed = time.time() - self._acq_t0
        acc = 0.0
        for name, dur in self.pretreatment_phases:
            if elapsed < acc + dur:
                self._set_status(f"Pre-treatment — {name}  {elapsed - acc:.0f}/{dur:.0f} s")
                return
            acc += dur
        # Pasada la duración estimada del pre-tratamiento pero aún sin paquete de barrido.
        self._set_status("Pre-treatment done — waiting for sweep…")

    # ---------------------------
    # Utilidades de plotting
    # ---------------------------
    def _capture_cycle_label(self, m, event):
        """Captura (una vez por línea) el valor de leyenda configurado en
        cycle_legend, p.ej. el potencial E_V del primer paquete de cada espectro EIS."""
        if self.cycle_legend is None or m in self.cycle_label_values:
            return
        val = event.get(self.cycle_legend[0])
        if val is not None:
            self.cycle_label_values[m] = val

    def _update_legends(self):
        """Actualiza las leyendas del gráfico según las líneas actuales."""
        if self.legends_list is not None:
            handles = [line for line in self.lines_by_m.values()]
            labels = self.legends_list
            if len(labels) < len(handles):
                labels = labels + [
                    f"{self.prefix_legend}{m}" for m in range(len(labels) + 1, len(handles) + 1)
                ]
            elif len(labels) > len(handles):
                labels = labels[: len(handles)]
        else:
            handles = [line for line in self.lines_by_m.values()]
            # Etiqueta adaptativa por corrida: R{run} si la corrida aporta un solo ciclo
            # (SWV/EIS), R{run}c{cycle} si aporta varios (CV multi-scan).
            cycles_per_run = {}
            for m in self.lines_by_m:
                run, cyc = self.key_meta.get(m, (1, m))
                cycles_per_run.setdefault(run, set()).add(cyc)
            multi_run = len({r for r, _ in self.key_meta.values()}) > 1
            labels = []
            for m in self.lines_by_m:
                run, cyc = self.key_meta.get(m, (1, m))
                # Leyenda por valor (p.ej. "E=0.1V" por espectro EIS); el prefijo
                # R{run} solo cuando hay varias corridas retenidas (Keep runs).
                if self.cycle_legend is not None and m in self.cycle_label_values:
                    label = self.cycle_legend[1].format(self.cycle_label_values[m])
                    labels.append(f"R{run} {label}" if multi_run else label)
                elif len(cycles_per_run.get(run, {cyc})) > 1:
                    labels.append(f"R{run}c{cyc}")
                else:
                    labels.append(f"R{run}")
        # Agrega líneas cargadas desde CSV (usa su propio label, omite ocultas)
        for line in self.loaded_lines:
            if not line.get_visible():
                continue
            handles.append(line)
            labels.append(line.get_label())
        # Leyenda compacta: con muchas trazas (p.ej. un espectro EIS por potencial)
        # la leyenda a tamaño normal colapsa los ejes de la figura chica (warning
        # "axes sizes collapsed to zero" del constrained layout).
        ncol = 2 if len(labels) > 6 else 1
        self.ax.legend(handles, labels, loc="best", frameon=True, fontsize="small", ncol=ncol)
        self.canvas.draw_idle()

    def _build_style_cycle(self):
        """Genera un ciclo de estilos color/linestyle para distintas mediciones."""
        colors = (
            plt.rcParams["axes.prop_cycle"]
            .by_key()
            .get("color", ["b", "g", "r", "c", "m", "y", "k"])
        )
        linestyles = ["--", "-", "-.", ":"]
        styles = []
        for ls in linestyles:
            for c in colors:
                styles.append((c, ls))
        return styles

    def _get_or_create_line(self, m):
        if m in self.lines_by_m:
            return self.lines_by_m[m]

        self.x_by_m[m] = deque(maxlen=self.max_points)
        self.y_by_m[m] = deque(maxlen=self.max_points)

        idx = (m - 1) % len(self._style_cycle)
        c, ls = self._style_cycle[idx]
        (line,) = self.ax.plot(
            [], [], linestyle=ls, linewidth=4.5, color=c, marker="+", markersize=3, label=f"M{m}"
        )

        # Si el color es muy claro, mejora visibilidad del marcador:
        line.set_markeredgecolor("0.3")

        self.lines_by_m[m] = line
        return line

    def _set_status(self, msg):
        self.lbl_status.configure(text=msg)


class LegendManagerWindow(ttk.Toplevel):
    """
    Ventana Toplevel para gestionar leyendas del gráfico:
    - Mostrar lista de mediciones actuales
    - Permitir agregar nuevas mediciones (líneas vacías)
    - Permitir eliminar mediciones existentes
    """

    def __init__(self, master, plotter, **kwargs):
        """
        :param master: ventana principal (Tk o Frame)
        :param plotter: instancia de UDPIVPlotter
        """
        super().__init__(master, **kwargs)
        self.title("Legends")
        # self.geometry("400x300")
        self.plotter = plotter
        self.parent = master
        self.idx_sel = None
        self.lines_list = None
        # paralelo al listbox: ("live", idx_en_lines_list) o ("loaded", Line2D)
        self.entry_refs = []

        # --- Lista de mediciones ---
        frame_legends = ttk.LabelFrame(self, text="Legends")
        frame_legends.pack(fill=ttk.BOTH, expand=True, padx=10, pady=10)

        self.listbox = tk.Listbox(frame_legends, height=10)
        self.listbox.pack(fill=ttk.BOTH, expand=True, padx=10, pady=6)
        self.listbox.bind("<Double-1>", self.on_double_clic_line)

        # --- Controles para agregar/eliminar ---
        controls = ttk.Frame(frame_legends)
        controls.pack(fill=ttk.X, pady=6)

        self.entry_new = ttk.Entry(controls)
        self.entry_new.pack(side=ttk.LEFT, padx=4)
        self.btn_add = ttk.Button(
            controls, text="➕ Add", bootstyle="success", command=self.add_legend
        )
        self.btn_remove = ttk.Button(
            controls, text="🗑 Delete", bootstyle="danger", command=self.remove_selected
        )
        self.btn_edit = ttk.Button(
            controls, text="✏️ Editar", bootstyle="primary", command=self.on_edit_line
        )
        self.btn_toggle = ttk.Button(
            controls, text="👁 Show/Hide", bootstyle="info", command=self.toggle_visibility
        )
        self.btn_add.pack(side=ttk.LEFT, padx=4)
        self.btn_remove.pack(side=ttk.LEFT, padx=4)
        self.btn_edit.pack(side=ttk.LEFT, padx=4)
        self.btn_toggle.pack(side=ttk.LEFT, padx=4)
        # --- Prefix handlers
        prefix_frame = ttk.LabelFrame(self, text="Prefix")
        prefix_frame.pack(fill=ttk.X, padx=10, pady=6)
        self.entry_prefix = ttk.Entry(prefix_frame)
        self.entry_prefix.insert(0, "M-")
        self.entry_prefix.pack(fill=ttk.X, padx=10, pady=6)

        # --- Botón cerrar ---
        self.btn_close = ttk.Button(
            self, text="Close", bootstyle="secondary", command=self.on_close
        )
        self.btn_close.pack(pady=6)

        # Cargar leyendas actuales
        self.refresh_list()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def refresh_list(self):
        """Recarga la lista con mediciones live y líneas cargadas desde CSV."""
        self.listbox.delete(0, ttk.END)
        self.entry_refs = []
        # Buffer diferido para legends live (commit al cerrar)
        if self.lines_list is None:
            self.lines_list = [f"M{m}" for m in self.plotter.lines_by_m.keys()]
        for i, name in enumerate(self.lines_list):
            self.listbox.insert(ttk.END, f"[live] {name}")
            self.entry_refs.append(("live", i))
        # Líneas cargadas desde CSV: editar/eliminar/ocultar inmediato
        for line in self.plotter.loaded_lines:
            mark = "👁" if line.get_visible() else "🚫"
            self.listbox.insert(ttk.END, f"[csv {mark}] {line.get_label()}")
            self.entry_refs.append(("loaded", line))

    def add_legend(self):
        """Agrega una nueva entrada de legend live (sin datos asociados)."""
        name = self.entry_new.get().strip()
        print(f"Adding legend: {name}")
        if not name:
            return
        if self.lines_list is None:
            self.lines_list = []
        if name in self.lines_list:
            return
        self.lines_list.append(name)
        self.entry_new.delete(0, ttk.END)
        self.refresh_list()

    def remove_selected(self):
        """Elimina la entrada seleccionada — live del buffer, loaded del eje."""
        sel = self.listbox.curselection()
        if not sel or not self.entry_refs:
            return
        idx = sel[0]
        kind, ref = self.entry_refs[idx]
        if kind == "live":
            if not isinstance(self.lines_list, list):
                return
            if 0 <= ref < len(self.lines_list):
                self.lines_list.pop(ref)
        else:
            try:
                ref.remove()
            except (NotImplementedError, ValueError):
                pass
            if ref in self.plotter.loaded_lines:
                self.plotter.loaded_lines.remove(ref)
            self.plotter._update_legends()
        self.refresh_list()

    def on_double_clic_line(self, event):
        """Carga el nombre actual de la entrada seleccionada en el entry."""
        sel = self.listbox.curselection()
        print(f"Double click: {sel}: {event}")
        if not sel or not self.entry_refs:
            return
        self.idx_sel = sel[0]
        kind, ref = self.entry_refs[self.idx_sel]
        if kind == "live":
            text = self.lines_list[ref] if self.lines_list and ref < len(self.lines_list) else ""
        else:
            text = ref.get_label()
        self.entry_new.delete(0, ttk.END)
        self.entry_new.insert(0, text)

    def on_edit_line(self):
        """Aplica el nuevo nombre — live al buffer, loaded directo al Line2D."""
        if self.idx_sel is None or not self.entry_refs:
            return
        new_name = self.entry_new.get().strip()
        if not new_name:
            return
        kind, ref = self.entry_refs[self.idx_sel]
        if kind == "live":
            if not isinstance(self.lines_list, list):
                return
            if 0 <= ref < len(self.lines_list):
                self.lines_list[ref] = new_name
        else:
            ref.set_label(new_name)
            self.plotter._update_legends()
        self.idx_sel = None
        self.entry_new.delete(0, ttk.END)
        self.refresh_list()

    def toggle_visibility(self):
        """Oculta/muestra la línea seleccionada (live o loaded)."""
        sel = self.listbox.curselection()
        if not sel or not self.entry_refs:
            return
        idx = sel[0]
        kind, ref = self.entry_refs[idx]
        if kind == "live":
            keys = list(self.plotter.lines_by_m.keys())
            if not (0 <= ref < len(keys)):
                return
            line = self.plotter.lines_by_m[keys[ref]]
        else:
            line = ref
        line.set_visible(not line.get_visible())
        self.plotter._update_legends()
        self.refresh_list()
        if idx < self.listbox.size():
            self.listbox.selection_set(idx)

    def on_close(self):
        """Limpia la referencia al plotter."""
        prefix = self.entry_prefix.get().strip()
        if not prefix:
            prefix = "M-"
        if prefix == "":
            prefix = "M-"
        self.parent.on_close_config_legend(self.lines_list, prefix)
        self.destroy()


# ---------------------------
# Ejemplo de integración
# ---------------------------
def demo():
    app = ttk.Window(themename="darkly")  # o "flatly", "cosmo", etc.
    app.title("UDP IV Plotter (ttkbootstrap)")
    plotter = EventPlotter(
        app, "cv", udp_port=5005, buffer_size=4096, max_points=5000, update_interval_ms=80
    )

    # Cierre limpio
    def on_close():
        plotter.on_close()
        app.quit()
        app.destroy()

    app.protocol("WM_DELETE_WINDOW", on_close)

    app.mainloop()


if __name__ == "__main__":
    #    demo()
    app = ttk.Window(themename="litera")
    app.title("UDP IV Plotter (ttkbootstrap)")
    plotter = EventPlotter(
        app, "cv", udp_port=5005, buffer_size=4096, max_points=5000, update_interval_ms=80
    )
    plotter.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")

    def on_close():
        plotter.on_close()
        app.quit()
        app.destroy()

    app.protocol("WM_DELETE_WINDOW", on_close)
    app.mainloop()
