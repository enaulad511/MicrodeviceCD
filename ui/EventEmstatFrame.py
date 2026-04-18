# -*- coding: utf-8 -*-
from Drivers.EmstatUtils import EmstatStreamParser
from Drivers.EmstatUtils import LineBufferedSocketReader
import json
from tkinter.constants import END
import socket
import threading
import queue
import time
from collections import deque

import matplotlib

matplotlib.use("TkAgg")  # backend para Tk
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from tkinter.filedialog import askdirectory
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
        max_points=5000,
        update_interval_ms=80,
        title="CV",
        x_label="E(V)",
        y_label="I(A)",
        x_key="E_V",
        y_key="I_A",
        payload=None,
        **kwargs,
    ):
        super().__init__(master, **kwargs)
        # payload para el experimento
        self.payload_exp = payload

        # --- Parámetros de comunicación y plotting ---
        self.tcp_port = tcp_port
        self.ip_sender = ip_sender
        self.buffer_size = buffer_size
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
        self.stop_event = threading.Event()
        self.reader_th = None
        self.processor_th = None
        self.sock = None
        self.running = False
        self.flag_recording = False
        self.after_id = None

        # --- Estado del gráfico ---
        plt.style.use("seaborn-v0_8-darkgrid")
        self.fig, self.ax = plt.subplots(figsize=(10, 6))
        self.ax.set_title(self.title)
        self.ax.set_xlabel(self.x_label)
        self.ax.set_ylabel(self.y_label)

        # Por medición (m): deques y Line2D
        self.x_key = x_key
        self.y_key = y_key
        self.x_by_m = {}
        self.y_by_m = {}
        self.lines_by_m = {}
        self._style_cycle = self._build_style_cycle()

        # --- Embedding de Matplotlib en ttkbootstrap ---
        self.canvas = FigureCanvasTkAgg(self.fig, self)
        self.toolbar = NavigationToolbar2Tk(self.canvas, self, pack_toolbar=False)
        self.toolbar.pack(side=ttk.TOP, fill=ttk.X)
        self.canvas.get_tk_widget().pack(side=ttk.TOP, fill=ttk.BOTH, expand=True)

        # --- Controles ---
        controls = ttk.Frame(self)
        controls.pack(side=ttk.TOP, fill=ttk.X, pady=6)

        self.btn_start = ttk.Button(
            controls, text="▶ Start listening", bootstyle="success", command=self.start
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
        self.btn_custom_plot = ttk.Button(
            controls,
            text="📊 Custom Plot",
            bootstyle="secondary",
            command=self.custom_plot_axes,
        )
        self.lbl_status = ttk.Label(controls, text="State: stopped.", anchor="w")

        self.btn_start.pack(side=ttk.LEFT, padx=4)
        self.btn_stop.pack(side=ttk.LEFT, padx=4)
        self.btn_clear.pack(side=ttk.LEFT, padx=4)
        self.btn_save.pack(side=ttk.LEFT, padx=4)
        self.btn_custom_plot.pack(side=ttk.LEFT, padx=4)
        self.lbl_status.pack(side=ttk.RIGHT, padx=4)

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

    # ---------------------------
    # API pública
    # ---------------------------
    def start(self):
        """Crea socket, lanza hilo TCP productor y procesador."""
        if self.running:
            return

        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((self.ip_sender, self.tcp_port))

            # TCP streaming robusto
            self.sock.settimeout(None)  # TCP en modo bloqueante
            self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

        except OSError as e:
            self._set_status(f"Error de socket: {e}")
            return

        # Reset estado
        self.stop_event.clear()
        self.flag_recording = True
        self.running = True

        # Lanza hilo productor (solo lectura TCP)
        self.reader_th = threading.Thread(
            target=self._tcp_reader, daemon=True, name="TCPReader"
        )
        self.reader_th.start()

        # Lanza hilo consumidor (parsing y lógica)
        self.processor_th = threading.Thread(
            target=self._tcp_processor, daemon=True, name="TCPProcessor"
        )
        self.processor_th.start()

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
        self.btn_start.configure(state=ttk.NORMAL)
        self.btn_stop.configure(state=ttk.DISABLED)
        self._cancel_update()
        self._set_status("Estado: detenido")

    def clear_plot(self):
        """Limpia datos y resetea el gráfico."""
        self.storage_dict.clear()
        self.x_by_m.clear()
        self.y_by_m.clear()
        self.lines_by_m.clear()

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
        try:
            with open(f"{path}/IV_data_{time.strftime('%Y%m%d_%H%M')}.csv", "w") as f:
                f.write(f"sample,{self.x_key}, {self.y_key}, cycle\n")
                for index, event in enumerate(self.total_data):
                    f.write(
                        f"{index}, {event.get(self.x_key)}, {event.get(self.y_key)}, {event.get('cycle')}\n"
                    )
            self._set_status(
                f"Data saved to file: IV_data_{time.strftime('%Y%m%d_%H%M')}.csv"
            )
        except Exception as e:
            self._set_status(f"Error saving data: {e}")
            print(f"Error saving data: {e}")

    def update_val_experiment(self, x_key, y_key, payload, ip_sender):
        if self.flag_recording:
            print("not posible to update payload while running experiment")
            return
        self.x_key = x_key
        self.y_key = y_key
        self.payload_exp = payload
        self.ip_sender = ip_sender

    def custom_plot_axes(self):
        if self.config_legend is not None:
            # bring to the front
            self.config_legend.lift()
        else:
            self.config_legend = LegendManagerWindow(self, plotter=self)

    def on_close_config_legend(self, legend_list, prefix_legend="M-"):
        # self.config_legend.destroy()
        self.config_legend = None
        self.legends_list = (
            legend_list if legend_list and len(legend_list) > 0 else None
        )
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
        self.sock.close()
        print("TCP reader stopped.")
        
        self.reader_th=None
        self.stop()

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
            elif msg.get("type") == "emstat_end":
                print("END OF EXPERIMENT")
                self._set_status("End of experiment.")
                self.stop_event.set()
                break
        print("TCP processor stopped.")
        self.processor_th = None

    # def _tcp_reader(self):
    #     print(f"starting tcp on port {self.tcp_port} and address {self.ip_sender} …")
    #     self.flag_recording = False
    #     # s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    #     # s.connect((CD_IP, TCP_PORT))
    #     if self.sock is None:
    #         print("First create a socket")
    #         return
    #     self.sock.sendall((json.dumps(self.payload_exp) + "\n").encode())
    #     self.flag_recording = True
    #     reader = LineBufferedSocketReader(self.sock)
    #     parser = EmstatStreamParser(experiment=self.method)
    #     start_time = time.time()
    #     while not self.stop_event.is_set():
    #         if time.time() - start_time > 120:
    #             self.sock.sendall(b'{"type":"keepalive"}\n')
    #             start_time = time.time()
    #         lines = reader.read_lines()
    #         if lines is None:
    #             print("TCP closed by server")
    #             continue
    #         for line in lines:
    #             if line.startswith("EMSTAT:"):
    #                 raw_json = line[len("EMSTAT:") :]

    #                 try:
    #                     msg = json.loads(raw_json)

    #                 except Exception:
    #                     continue
    #                 print(msg)
    #                 if msg.get("type") == "emstat_data":
    #                     event = parser.feed_raw(msg["raw"])
    #                     print(event)
    #                     if event:
    #                         if event["type"] == "data":
    #                             self.total_data.append(event)
    #                             # print("EVENT:", event)

    #                             self.q_points.put(
    #                                 (
    #                                     event.get(self.x_key, 0.0),
    #                                     event.get(self.y_key, 0.0),
    #                                     event.get("cycle", 0),
    #                                 )
    #                             )
    #                         else:
    #                             print("EVENT:", event)
    #                 elif msg.get("type") == "emstat_end":
    #                     print("END OF EXPERIMENT")
    #                     self.stop_event.set()
    #                     break
    #     self.flag_recording = False
    #     print("Recording stopped.")
    #     self._set_status("End of Experiment")
    #     # self.stop()

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
                    f"{self.prefix_legend}{m}"
                    for m in range(len(labels) + 1, len(handles) + 1)
                ]
            elif len(labels) > len(handles):
                labels = labels[: len(handles)]
        else:
            handles = [line for line in self.lines_by_m.values()]
            labels = [f"{self.prefix_legend}{m}" for m in self.lines_by_m.keys()]
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
            [], [], linestyle=ls, color=c, marker="o", markersize=3, label=f"M{m}"
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
        self.btn_add.pack(side=ttk.LEFT, padx=4)
        self.btn_remove.pack(side=ttk.LEFT, padx=4)
        self.btn_edit.pack(side=ttk.LEFT, padx=4)
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
        """Recarga la lista con las mediciones actuales del plotter."""
        if self.lines_list is None:
            self.listbox.delete(0, END)
            for m in self.plotter.lines_by_m.keys():
                self.listbox.insert(END, f"M{m}")
                self.lines_list = self.listbox.get(0, END)
        else:
            self.listbox.delete(0, END)
            for item in self.lines_list:
                self.listbox.insert(END, item)

    def add_legend(self):
        """Agrega una nueva medición vacía (línea sin datos)."""
        name = self.entry_new.get().strip()
        print(f"Adding legend: {name}")
        if self.lines_list is None:
            self.lines_list = []
        if not name:
            return
        if name in self.plotter.lines_by_m:
            return
        self.lines_list.append(name)
        self.entry_new.delete(0, END)
        self.refresh_list()

    def remove_selected(self):
        """Elimina la medición seleccionada (línea y datos)."""
        sel = self.listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        new_list = [x for i, x in enumerate(self.lines_list) if i != idx]
        self.lines_list = new_list
        self.refresh_list()

    def on_double_clic_line(self, event):
        """Permite editar la medición seleccionada (no implementado)."""
        sel = self.listbox.curselection()
        print(f"Double click: {sel}: {event}")
        if not sel:
            return
        # extraer linea
        self.idx_sel = sel[0]
        text = self.listbox.get(self.idx_sel)
        self.entry_new.delete(0, END)
        self.entry_new.insert(0, text)

    def on_edit_line(self):
        """Guarda el cambio en la medición seleccionada (no implementado)."""
        if self.idx_sel is None:
            return
        new_name = self.entry_new.get().strip()
        if not new_name:
            return
        if not isinstance(self.lines_list, list):
            return
        self.lines_list[self.idx_sel] = new_name
        self.idx_sel = None
        self.entry_new.delete(0, END)
        self.refresh_list()

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
        app, udp_port=5005, buffer_size=4096, max_points=5000, update_interval_ms=80
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
        app, udp_port=5005, buffer_size=4096, max_points=5000, update_interval_ms=80
    )
    plotter.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")

    def on_close():
        plotter.on_close()
        app.quit()
        app.destroy()

    app.protocol("WM_DELETE_WINDOW", on_close)
    app.mainloop()
