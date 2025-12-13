# -*- coding: utf-8 -*-
import socket
import threading
import matplotlib.pyplot as plt
__author__ = "Edisson Naula"
__date__ = "$ 05/12/2025 at 16:26 $"

UDP_PORT = 5005  # must match Arduino's remotePort
BUFFER_SIZE = 4096


def graph_data(data):
    """
    Matplotlib plot for voltage vs current
    """
    print("Plotting data...")
    # print(data)
    v_s = []
    i_s = []
    for time, values in data.items():
        v_s.append(values["voltage"])
        i_s.append(values["current"])
    plt.figure(figsize=(10, 6))
    plt.plot(v_s, i_s, marker='o', linestyle='-', color='b')
    plt.title('Voltage vs Current')
    plt.xlabel('Voltage (V)')
    plt.ylabel('Current (A)')
    plt.grid(True)
    plt.show()

if __name__ == "__main__":
    # Bind to all interfaces on the Pi (including wlan0 connected to Arduino AP)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    # Allow receiving broadcast packets
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.bind(("", UDP_PORT))
    plot_data = True
    data_cv = {}
    flag_recording = False
    print(f"Listening for UDP on port {UDP_PORT} ...")
    try:
        while True:
            data, addr = sock.recvfrom(BUFFER_SIZE)
            try:
                text = data.decode('utf-8', errors='replace')
            except Exception:
                text = str(data)
            print(f"From {addr[0]}:{addr[1]} -> {text}")
            if "start sent" in text.lower():
                flag_recording = True
                data_cv = {}
                continue
            if flag_recording:
                # 1    E set[V]: 9.919E-01     I [A]: 0.000E+00        status: Underload       Range: 1 mA (High speed)
                parts = text.split("\t")
                if len(parts) >= 4:
                    try:
                        time_ms = int(parts[0].strip())
                        voltage_v = float(parts[1].split(":")[1].strip())
                        current_a = float(parts[2].split(":")[1].strip())
                        status = parts[3].split(":")[1].strip()
                        range_data = parts[4].split(":")[1].strip()
                        data_cv[f"{time_ms}"] = {"voltage": voltage_v, "current": current_a, "status": status, "range": range_data}
                    except ValueError:
                        print("Malformed data line, skipping.")
            if "end sent" in text.lower():
                flag_recording = False
                print("Recording stopped.")
                if plot_data:
                    thread_graph = threading.Thread(target=graph_data, args=(data_cv,))
                    thread_graph.start()                
                continue
    
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        sock.close()
