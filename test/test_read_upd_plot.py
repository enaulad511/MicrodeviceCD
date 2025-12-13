
# -*- coding: utf-8 -*-
import socket
import threading
import queue
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from collections import deque
import time

__author__ = "Edisson Naula"
__date__ = "$ 05/12/2025 at 16:26 $"

UDP_PORT = 5005       # Debe coincidir con el remotePort del Arduino
BUFFER_SIZE = 4096
PLOT_LIVE = True      # habilitar plot en vivo
PLOT_FINAL = False    # si quieres también graficar al final todos los puntos

# Si el Raspberry Pi no trae un backend interactivo, asegúrate de tener Tk:
# sudo apt-get install python3-tk
# y usa: matplotlib.use('TkAgg') antes de importar pyplot, si fuera necesario.
dict_colors = {
    "1": "b",
    "2": "g",
    "3": "r",
    "4": "c",
    "5": "m",
    "6": "y",
    "7": "k",
    "8": "w",
    "9": "b--",
    "10": "g--",
    "11": "r--",
    "12": "c--",
    "13": "m--",
    "14": "y--",
    "15": "k--",
    "16": "w--", 
}

def parse_line(text):
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


def udp_reader(sock, q_points, storage_dict, stop_event):
    """
    Hilo lector de UDP:
    - escucha paquetes
    - maneja 'start sent' / 'end sent'
    - parsea y empuja (V, I) a la cola para el plot en vivo
    - guarda también en storage_dict (para plot final opcional)
    """
    flag_recording = False
    print(f"Listening for UDP on port {UDP_PORT} ...")
    # Hacer que el socket no bloquee eternamente, para poder cerrar limpio:
    sock.settimeout(1.0)
    count_mesurement = 0
    while not stop_event.is_set():
        try:
            data, addr = sock.recvfrom(BUFFER_SIZE)
        except socket.timeout:
            continue
        except OSError:
            # Socket cerrado
            break

        try:
            text = data.decode('utf-8', errors='replace')
        except Exception:
            text = str(data)

        # Log de cada paquete (puedes silenciar si es mucho):
        print(f"From {addr[0]}:{addr[1]} -> {text}")

        lower = text.lower()
        if "start sent" in lower:
            measurement = lower.split(":")[-1]
            print(f"Starting measurement {measurement}")
            flag_recording = True
            count_mesurement += 1
            storage_dict.clear()
            # Señal de reinicio de cola si quieres
            continue

        if "end sent" in lower:
            flag_recording = False
            print("Recording stopped.")
            # No bloquea el hilo principal; solo sigue leyendo
            continue

        if flag_recording:
            parsed = parse_line(text)
            if parsed is not None:
                # Enviar (V,I) al plot en vivo
                q_points.put((parsed["voltage"], parsed["current"], count_mesurement))
                # Guardar por si quieres graficado final (o logging)
                storage_dict[str(parsed["time_ms"])] = {
                    "voltage": parsed["voltage"],
                    "current": parsed["current"],
                    "status": parsed["status"],
                    "range": parsed["range"],
                    "measurement": count_mesurement
                }
            else:
                print("Malformed data line, skipping.")



def plot_live(q_points, max_points=5000):
    """
    Crea figura y actualiza en vivo leyendo de la cola.
    Mantiene una línea por número de measurement, con color/estilo dictado por dict_colors.
    """
    plt.style.use("seaborn-v0_8-darkgrid")
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.set_title("Voltage vs Current (en vivo)")
    ax.set_xlabel("Voltage (V)")
    ax.set_ylabel("Current (A)")

    # Un deque por measurement
    v_by_m = {}  # m -> deque de voltajes
    i_by_m = {}  # m -> deque de corrientes
    # Un Line2D por measurement
    lines_by_m = {}  # m -> Line2D

    # Función auxiliar: crear línea con formato desde dict_colors
    def get_or_create_line_for_measurement(m):
        if m in lines_by_m:
            return lines_by_m[m]

        # Obtén formato desde dict_colors (por ejemplo "b--" o "g")
        fmt = dict_colors.get(str(m), None)

        # Crea deques para este measurement
        v_by_m[m] = deque(maxlen=max_points)
        i_by_m[m] = deque(maxlen=max_points)

        if fmt is None:
            # Formato por defecto si no existe en el dict
            # color gris con línea sólida
            line, = ax.plot([], [], '-', color='0.5', label=f"M{m}")
        else:
            # Si fmt incluye estilo ("--"), podemos pasarlo directo
            # y añadir marcadores para ver puntos en streaming.
            # Matplotlib acepta "b--", "g", etc. como fmt.
            line, = ax.plot([], [], fmt, label=f"M{m}")
            # añade marcador; si el fmt ya incluye estilo de línea, esto no lo rompe
            line.set_marker('o')
            line.set_markersize(3)

            # OJO: si usas "w" (blanco) puede que no se vea con el fondo claro.
            # Puedes añadir borde al marcador para hacerlo visible:
            if 'w' in fmt:
                line.set_markeredgecolor('0.3')
                line.set_markerfacecolor('w')

        lines_by_m[m] = line
        # Actualiza la leyenda cuando aparece una nueva línea
        ax.legend(loc='best', frameon=True)
        return line

    # Límites iniciales (ajústalos a tu rango típico)
    ax.set_xlim(-1, 1)
    ax.set_ylim(-1, 1)

    def update(_frame):
        drained = 0
        # Drenar la cola de puntos recibidos
        while True:
            try:
                v, i, m = q_points.get_nowait()
            except queue.Empty:
                break

            line = get_or_create_line_for_measurement(m)
            v_by_m[m].append(v)
            i_by_m[m].append(i)
            drained += 1

        # Actualiza todas las líneas que tengan datos
        if drained > 0:
            for m, line in lines_by_m.items():
                vs = v_by_m[m]
                is_ = i_by_m[m]
                if len(vs) > 0:
                    line.set_data(vs, is_)
            # Recalcular límites y vista
            ax.relim()
            ax.autoscale_view()

        # No usamos blit (varias líneas) para simplicidad/robustez en distintos backends
        return tuple(lines_by_m.values())

    ani = FuncAnimation(fig, update, interval=80, blit=False)
    return fig, ani


def plot_final(data):
    """Gráfico estático con todos los datos recibidos."""
    print("Plotting final data...")
    v_s = []
    i_s = []
    for _t, values in data.items():
        v_s.append(values["voltage"])
        i_s.append(values["current"])

    plt.figure(figsize=(10, 6))
    plt.plot(v_s, i_s, marker="o", linestyle="-", color="b")
    plt.title("Voltage vs Current (final)")
    plt.xlabel("Voltage (V)")
    plt.ylabel("Current (A)")
    # plt.grid(True)
    plt.show()


def main():
    # 1) Socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    # Recibir broadcast
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.bind(("", UDP_PORT))

    # 2) Estructuras de comunicación
    q_points = queue.Queue()
    storage_dict = {}  # para registro / graficado final
    stop_event = threading.Event()

    # 3) Hilo lector UDP
    reader_th = threading.Thread(
        target=udp_reader,
        args=(sock, q_points, storage_dict, stop_event),
        daemon=True
    )
    reader_th.start()

    try:
        if PLOT_LIVE:
            # 4) Lanzar plot en vivo en el hilo principal (requisito de Matplotlib)
            fig, ani = plot_live(q_points)
            plt.show()  # bloquea hasta cerrar la ventana

        # 5) Opcional: gráfico final con todo lo almacenado
        if PLOT_FINAL and storage_dict:
            plot_final(storage_dict)

    except KeyboardInterrupt:
        print("\nStopped by user.")
    finally:
        # Señal para terminar hilo lector y cerrar socket
        stop_event.set()
        try:
            sock.close()
        except Exception:
            pass
        # Esperar un poco el cierre limpio
        time.sleep(0.2)


if __name__ == "__main__":
   main()
