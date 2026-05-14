# -*- coding: utf-8 -*-
from matplotlib.figure import Figure
from Drivers.EmstatUtils import EmstatStreamParser
from Drivers.EmstatUtils import LineBufferedSocketReader
import csv
import json
import os
import socket
import threading
import queue
import time
from collections import deque

import matplotlib

matplotlib.use("TkAgg")  # backend para Tk
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from tkinter.filedialog import askdirectory, askopenfilename
import ttkbootstrap as ttk
import tkinter as tk


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
        ip_sender="localhost",
        buffer_size=4096,
        max_points=10000,
        update_interval_ms=80,
        title="CV",
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
        self.max_points = max_points
        self.update_interval_ms = update_interval_ms
        self.prefix_legend = "M-"
        self.legends_list = None
        self.config_legend = None
        self.title = title
        self.method = method
        self.x_label = x_label
        self.y_label = y_label
        # --- Estado de ejecución ---
        self.q_points = queue.Queue(maxsize=20000)  # grande, pero finita
        self.q_tcp_lines = queue.Queue(maxsize=20000)  # grande, pero finita
        self.storage_dict = {}  # registro parcial de informacion
        self.total_data = []  # registro total de informacion
        self.loaded_lines = []  # Line2D agregadas desde archivos CSV cargados
        self.filename_meta = {}  # metadatos (motor, etc.) para incluir en el nombre del CSV
        self.stop_event = threading.Event()
        self.reader_th = None
        self.processor_th = None
        self.sock = None
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
            command=self.stop,
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

        # Lanza hilo productor (solo lectura TCP)
        self.reader_th = threading.Thread(target=self._tcp_reader, daemon=True, name="TCPReader")
        self.reader_th.start()

        # Lanza hilo consumidor (parsing y lógica)
        self.processor_th = threading.Thread(
            target=self._tcp_processor, daemon=True, name="TCPProcessor"
        )
        self.processor_th.start()
        if self.callback_motor is not None:
            self.thread_motor = self.callback_motor()
        # UI
        self.btn_start.configure(state=ttk.DISABLED)
        self.btn_stop.configure(state=ttk.NORMAL)
        self._set_status(f"TCP connected to {self.ip_sender}:{self.tcp_port}")
        self._schedule_update()

    def stop(self):
        """Detiene hilo lector, cierra socket y cancela actualizaciones."""

        if not self.running:
            return
        print("Stopping …")
        self.total_data.append(self.storage_dict.copy())
        self.storage_dict.clear()
        self.stop_event.set()
        try:
            if self.sock:
                self.sock.close()
        except Exception:
            pass
        self.sock = None

        # Esperar hilo (rápido gracias al timeout del socket)
        try:
            if self.reader_th and self.reader_th.is_alive():
                self.reader_th.join(timeout=0.5)
        except Exception:
            pass
        try:
            if self.processor_th and self.processor_th.is_alive():
                self.processor_th.join(timeout=0.5)
        except Exception:
            pass
        self.running = False
        self.flag_recording = False
        self.btn_start.configure(state=ttk.NORMAL)
        self.btn_stop.configure(state=ttk.DISABLED)
        self._cancel_update()
        self._set_status("Estado: detenido")
        self.on_end_experiment(self.thread_motor)
        self.thread_motor = None

    def clear_plot(self):
        """Limpia datos y resetea el gráfico."""
        self.storage_dict.clear()
        self.x_by_m.clear()
        self.y_by_m.clear()
        self.lines_by_m.clear()
        self.loaded_lines.clear()

        self.ax.clear()
        self.ax.set_title("V vs A (online)")
        self.ax.set_xlabel("Potential (V)")
        self.ax.set_ylabel("Current (A)")
        self.ax.legend([], [])
        self.canvas.draw_idle()

    def save_data(self):
        """
        Create CSV from data stored
        """
        if self.running:
            self._set_status("Stop aquisition before saving data.")
            return
        if not self.total_data:
            self._set_status("No hay datos para guardar.")
            return
        print("Saving data …")
        path = askdirectory(title="Select directory to save data")
        if not path:
            self._set_status("No directory selected.")
            return
        suffix = self._build_filename_suffix()
        filename = f"IV_data_{time.strftime('%Y%m%d_%H%M')}{suffix}.csv"
        try:
            with open(f"{path}/{filename}", "w") as f:
                f.write(f"sample,{self.x_key}, {self.y_key}, cycle\n")
                for index, event in enumerate(self.total_data):
                    f.write(
                        f"{index}, {event.get(self.x_key)}, {event.get(self.y_key)}, {event.get('cycle')}\n"
                    )
            self._set_status(f"Data saved to file: {filename}")
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
                    except (ValueError, TypeError):
                        continue
                    cycles_x.setdefault(cycle, []).append(x)
                    cycles_y.setdefault(cycle, []).append(y)
        except Exception as e:
            self._set_status(f"Error loading data: {e}")
            print(f"Error loading data: {e}")
            return
        if not cycles_x:
            self._set_status("No data parsed from file.")
            return
        label_base = os.path.splitext(os.path.basename(path))[0]
        for cycle in sorted(cycles_x.keys()):
            (line,) = self.ax.plot(
                cycles_x[cycle],
                cycles_y[cycle],
                linestyle="--",
                linewidth=1.5,
                alpha=0.7,
                marker="x",
                markersize=3,
                label=f"{label_base}-c{cycle}",
            )
            self.loaded_lines.append(line)
        self.ax.relim()
        self.ax.autoscale_view()
        self._update_legends()
        self._set_status(
            f"Loaded {len(cycles_x)} cycle(s) from {os.path.basename(path)}"
        )

    def update_val_experiment(
        self, x_key, y_key, payload, ip_sender, callback_spin_motor, filename_meta=None
    ):
        if self.flag_recording:
            print("not posible to update payload while running experiment")
            return
        self.x_key = x_key
        self.y_key = y_key
        self.payload_exp = payload
        self.ip_sender = ip_sender
        self.callback_motor = callback_spin_motor
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
        from ui.AnalysisWindow import AnalysisWindow
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
    # Hilo lector UDP
    # ---------------------------
    def _tcp_reader(self):
        print(f"starting tcp on port {self.tcp_port} and address {self.ip_sender} …")
        self.flag_recording = False
        if self.sock is None:
            print("First create a socket")
            return
        self.sock.sendall((json.dumps(self.payload_exp) + "\n").encode())
        self.flag_recording = True
        reader = LineBufferedSocketReader(self.sock)
        start_time = time.time()
        while not self.stop_event.is_set():
            # Keepalive SOLO para mantener control TCP
            if time.time() - start_time > 120:
                try:
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
        self.sock.close() if self.sock else None
        print("TCP reader stopped.")
        self.reader_th = None
        self.stop_event.set()

    def _tcp_processor(self):
        parser = EmstatStreamParser(experiment=self.method)
        while not self.stop_event.is_set():
            try:
                line = self.q_tcp_lines.get(timeout=0.1)
            except Exception:
                continue
            if not line.startswith("EMSTAT:"):
                continue
            raw_json = line[len("EMSTAT:") :]
            try:
                msg = json.loads(raw_json)
            except Exception:
                if "e!4" in raw_json.lower():
                    print(f"Error in the methodscript: {raw_json.strip()}")
                else:
                    print(f"JSON decode error: {raw_json}")
                continue
            if msg.get("type") == "emstat_data":
                event = parser.feed_raw(msg["raw"])
                if not event:
                    continue
                if event["type"] == "data":
                    self.total_data.append(event)
                    try:
                        self.q_points.put_nowait(
                            (
                                event.get(self.x_key, 0.0),
                                event.get(self.y_key, 0.0),
                                event.get("cycle", 0),
                            )
                        )
                    except Exception:
                        pass
                if "method" in event["type"]:
                    if event["type"] == "method":
                        self._set_status(f"Method: {event['type']} {event['method_id']}")
                        print("Method:", event["method_id"])
                    elif event["type"] == "method_end":
                        self._set_status(f"Method: {event['type']}")

                    else:
                        print("Event method unknow: ", event)
            elif msg.get("type") == "emstat_end":
                print("END OF EXPERIMENT")
                self._set_status("End of experiment.")
                self.stop_event.set()
                break
        print("TCP processor stopped.")
        self.processor_th = None
        self.stop()

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

        # Reprogramar si seguimos corriendo
        if self.running:
            self._schedule_update()

    # ---------------------------
    # Utilidades de plotting
    # ---------------------------
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
            labels = [f"{self.prefix_legend}{m}" for m in self.lines_by_m.keys()]
        # Agrega líneas cargadas desde CSV (usa su propio label, omite ocultas)
        for line in self.loaded_lines:
            if not line.get_visible():
                continue
            handles.append(line)
            labels.append(line.get_label())
        self.ax.legend(handles, labels, loc="best", frameon=True)
        self.canvas.draw_idle()

    def _build_style_cycle(self):
        """Genera un ciclo de estilos color/linestyle para distintas mediciones."""
        colors = (
            plt.rcParams["axes.prop_cycle"]
            .by_key()
            .get("color", ["b", "g", "r", "c", "m", "y", "k"])
        )
        linestyles = ["-", "--", "-.", ":"]
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
            [], [], linestyle=ls, linewidth=4.5, color=c, marker="o", markersize=3, label=f"M{m}"
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
