
# -*- coding: utf-8 -*-
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


class UDPIVPlotter(ttk.Frame):
    """
    Frame embebible en ttkbootstrap que:
    - Escucha UDP (broadcast) en un puerto
    - Detecta 'start sent' / 'end sent'
    - Parseo de líneas a (V, I, t, status, range) vía parse_line()
    - Grafica Voltaje vs Corriente en vivo por 'measurement' (cada START incrementa contador)
    - Control de inicio/detención desde botones
    """

    def __init__(self, master, udp_port=5005, buffer_size=4096, max_points=5000,
                 update_interval_ms=80, **kwargs):
        super().__init__(master, **kwargs)

        # --- Parámetros de comunicación y plotting ---
        self.udp_port = udp_port
        self.buffer_size = buffer_size
        self.max_points = max_points
        self.update_interval_ms = update_interval_ms
        self.prefix_legend="M-"
        self.legends_list=None
        self.config_legend = None

        # --- Estado de ejecución ---
        self.q_points = queue.Queue()
        self.storage_dict = {}          # registro parcial de informacion
        self.total_data = []            # registro total de informacion 
        self.stop_event = threading.Event()
        self.reader_th = None
        self.sock = None
        self.running = False
        self.flag_recording = False
        self.count_measurement = 0
        self.after_id = None

        # --- Estado del gráfico ---
        plt.style.use("seaborn-v0_8-darkgrid")
        self.fig, self.ax = plt.subplots(figsize=(10, 6))
        self.ax.set_title("Voltaje vs Corriente (en vivo)")
        self.ax.set_xlabel("Voltaje (V)")
        self.ax.set_ylabel("Corriente (A)")

        # Por medición (m): deques y Line2D
        self.v_by_m = {}
        self.i_by_m = {}
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

        self.btn_start = ttk.Button(controls, text="▶ Start listening",
                                   bootstyle="success", command=self.start)
        self.btn_stop = ttk.Button(controls, text="⏹ Stop",
                                  bootstyle="danger", command=self.stop, state=ttk.DISABLED)
        self.btn_clear = ttk.Button(controls, text="🗑 Clean",
                                   bootstyle="secondary", command=self.clear_plot)
        self.btn_save = ttk.Button(controls, text="💾 Save",
                                   bootstyle="secondary", command=self.save_data)
        self.btn_custom_plot = ttk.Button(controls, text="📊 Custom Plot",
                                          bootstyle="secondary", command=self.custom_plot_axes)
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

    # ---------------------------
    # API pública
    # ---------------------------
    def start(self):
        """Crea socket, levanta hilo lector y programa el loop de actualización."""
        if self.running:
            return
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            self.sock.bind(("", self.udp_port))
            self.sock.settimeout(1.0)  # para cierre limpio
        except OSError as e:
            self._set_status(f"Error de socket: {e}")
            return

        self.stop_event.clear()
        self.reader_th = threading.Thread(target=self._udp_reader, daemon=True)
        self.reader_th.start()
        self.running = True
        self.btn_start.configure(state=ttk.DISABLED)
        self.btn_stop.configure(state=ttk.NORMAL)
        self._set_status(f"Listening for UPD in {self.udp_port} …")
        self._schedule_update()

    def stop(self):
        """Detiene hilo lector, cierra socket y cancela actualizaciones."""
        print("Stopping …")
        
        if not self.running:
            return
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
        if self.reader_th and self.reader_th.is_alive():
            self.reader_th.join(timeout=1.5)

        self.running = False
        self.btn_start.configure(state=ttk.NORMAL)
        self.btn_stop.configure(state=ttk.DISABLED)
        self._cancel_update()
        self._set_status("Estado: detenido")
        print("Stopped")

    def clear_plot(self):
        """Limpia datos y resetea el gráfico."""
        self.storage_dict.clear()
        self.v_by_m.clear()
        self.i_by_m.clear()
        self.lines_by_m.clear()

        self.ax.clear()
        self.ax.set_title("Voltaje vs Corriente (en vivo)")
        self.ax.set_xlabel("Voltaje (V)")
        self.ax.set_ylabel("Corriente (A)")
        self.ax.legend([], [])
        self.canvas.draw_idle()

    def save_data(self):
        """
        Create CSV from data stored
        """
        if self.running:
            self._set_status("Detenga la adquisición antes de guardar.")
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
                f.write("sample,voltage,current,status,range,measurement\n")
                for data in self.total_data:
                    for k, v in data.items():
                        f.write(f"{k},{v['voltage']},{v['current']},{v['status']},{v['range']},{v['measurement']}\n")
            self._set_status(f"Data saved to file: IV_data_{time.strftime('%Y%m%d_%H%M')}.csv")
        except Exception as e:
            self._set_status(f"Error saving data: {e}")
            print(f"Error saving data: {e}")

    def custom_plot_axes(self):
        if self.config_legend is not None:
            # bring to the front
            self.config_legend.lift()
        else:
            self.config_legend = LegendManagerWindow(self, plotter=self)
    
    def on_close_config_legend(self, legend_list, prefix_legend="M-"):
        # self.config_legend.destroy()
        self.config_legend = None
        self.legends_list = legend_list if legend_list and len(legend_list)>0 else None
        self.prefix_legend = prefix_legend
        self._update_legends()
    
    # ---------------------------
    # Hilo lector UDP
    # ---------------------------
    def _udp_reader(self):
        print(f"Listening for UDP on port {self.udp_port} …")
        self.flag_recording = False

        while not self.stop_event.is_set():
            try:
                data, addr = self.sock.recvfrom(self.buffer_size)
            except socket.timeout:
                continue
            except OSError:
                break  # socket cerrado

            try:
                text = data.decode("utf-8", errors="replace")
            except Exception:
                text = str(data)

            # Log opcional:
            print(f"From {addr[0]}:{addr[1]} -> {text}")

            lower = text.lower()
            if "start sent" in lower:
                measurement = lower.split(":")[-1].strip()
                
                print(f"Starting measurement {measurement}")
                self.flag_recording = True
                self.count_measurement += 1
                if len(self.storage_dict)>0:
                    self.total_data.append(self.storage_dict.copy())
                self.storage_dict.clear()
                # si quieres resetear el gráfico en cada medición:
                # self.clear_plot()
                continue

            if "end sent" in lower:
                self.flag_recording = False
                print("Recording stopped.")
                continue

            if self.flag_recording:
                parsed = self.parse_line(text)
                if parsed is not None:
                    v = parsed["voltage"]
                    i = parsed["current"]
                    t = parsed["time_ms"]
                    self.q_points.put((v, i, self.count_measurement))

                    self.storage_dict[str(t)] = {
                        "voltage": v,
                        "current": i,
                        "status": parsed.get("status"),
                        "range": parsed.get("range"),
                        "measurement": self.count_measurement,
                    }
                else:
                    print("Malformed data line, skipping.")

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
            self.v_by_m[m].append(v)
            self.i_by_m[m].append(i)
            drained += 1

        if drained > 0:
            for m, line in self.lines_by_m.items():
                vs = self.v_by_m[m]
                is_ = self.i_by_m[m]
                if len(vs) > 0:
                    line.set_data(vs, is_)
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
                labels = labels + [f"{self.prefix_legend}{m}" for m in range(len(labels)+1, len(handles)+1)]
            elif len(labels) > len(handles):
                labels = labels[:len(handles)]
        else:
            handles = [line for line in self.lines_by_m.values()]
            labels = [f"{self.prefix_legend}{m}" for m in self.lines_by_m.keys()]
        self.ax.legend(handles, labels, loc="best", frameon=True)
        self.canvas.draw_idle()
    
    def _build_style_cycle(self):
        """Genera un ciclo de estilos color/linestyle para distintas mediciones."""
        colors = plt.rcParams["axes.prop_cycle"].by_key().get("color", ["b", "g", "r", "c", "m", "y", "k"])
        linestyles = ["-", "--", "-.", ":"]
        styles = []
        for ls in linestyles:
            for c in colors:
                styles.append((c, ls))
        return styles

    def _get_or_create_line(self, m):
        if m in self.lines_by_m:
            return self.lines_by_m[m]

        self.v_by_m[m] = deque(maxlen=self.max_points)
        self.i_by_m[m] = deque(maxlen=self.max_points)

        idx = (m - 1) % len(self._style_cycle)
        c, ls = self._style_cycle[idx]
        line, = self.ax.plot([], [], linestyle=ls, color=c, marker='o', markersize=3, label=f"M{m}")

        # Si el color es muy claro, mejora visibilidad del marcador:
        line.set_markeredgecolor('0.3')

        self.lines_by_m[m] = line
        return line

    def _set_status(self, msg):
        self.lbl_status.configure(text=msg)

    # ---------------------------
    # Parser de línea (AJUSTAR AL FORMATO REAL)
    # ---------------------------
    def parse_line(self, text):
        """
        Intenta extraer time_ms, voltage_v, current_a, status, range_data de la línea recibida.
        Devuelve dict o None si no se pudo parsear.
        """
        try:
            # Muchas veces llega con tabs; si no, usamos espacios múltiples
            parts = text.strip().split("\t")
            if len(parts) < 4:
                # fallback: separar por varios espacios
                parts = [p for p in text.replace("  ", "\t").split("\t") if p.strip()]

            # Esperamos: [time] [E set[V]: x] [I [A]: y] [status: ...] [Range: ...]
            time_ms = int(parts[0].strip())
            voltage_v = float(parts[1].split(":")[1].strip())
            current_a = float(parts[2].split(":")[1].strip())

            status = None
            range_data = None
            # Busca claves conocidas si existen
            for p in parts[3:]:
                low = p.lower()
                if "status" in low and ":" in p:
                    status = p.split(":")[1].strip()
                if "range" in low and ":" in p:
                    range_data = p.split(":")[1].strip()

            return {
                "time_ms": time_ms,
                "voltage": voltage_v,
                "current": current_a,
                "status": status,
                "range": range_data,
            }
        except Exception:
            return None


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
        self.title("Gestión de Leyendas")
        self.geometry("400x300")
        self.plotter = plotter
        self.parent = master
        self.idx_sel = None
        self.lines_list=None

        # --- Lista de mediciones ---
        self.lbl_title = ttk.Label(self, text="Leyendas actuales:", bootstyle="inverse")
        self.lbl_title.pack(pady=6)

        self.listbox = tk.Listbox(self, height=10)
        self.listbox.pack(fill=ttk.BOTH, expand=True, padx=10, pady=6)
        self.listbox.bind("<Double-1>", self.on_double_clic_line)

        # --- Controles para agregar/eliminar ---
        controls = ttk.Frame(self)
        controls.pack(fill=ttk.X, pady=6)

        self.entry_new = ttk.Entry(controls)
        self.entry_new.pack(side=ttk.LEFT, padx=4)
        self.btn_add = ttk.Button(controls, text="➕ Agregar", bootstyle="success", command=self.add_legend)
        self.btn_remove = ttk.Button(controls, text="🗑 Eliminar", bootstyle="danger", command=self.remove_selected)
        self.btn_edit = ttk.Button(controls, text="✏️ Editar", bootstyle="primary", command=self.on_edit_line)
        self.btn_add.pack(side=ttk.LEFT, padx=4)
        self.btn_remove.pack(side=ttk.LEFT, padx=4)
        self.btn_edit.pack(side=ttk.LEFT, padx=4)

        # --- Botón cerrar ---
        self.btn_close = ttk.Button(self, text="Cerrar", bootstyle="secondary", command=self.on_close)
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
        self.parent.on_close_config_legend(self.lines_list)
        self.destroy()



# ---------------------------
# Ejemplo de integración
# ---------------------------
def demo():
    app = ttk.Window(themename="darkly")  # o "flatly", "cosmo", etc.
    app.title("UDP IV Plotter (ttkbootstrap)")
    plotter = UDPIVPlotter(app, udp_port=5005, buffer_size=4096, max_points=5000, update_interval_ms=80)

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
    plotter = UDPIVPlotter(app, udp_port=5005, buffer_size=4096, max_points=5000, update_interval_ms=80)
    plotter.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
    def on_close():
        plotter.on_close()
        app.quit()
        app.destroy()
    app.protocol("WM_DELETE_WINDOW", on_close)
    app.mainloop()