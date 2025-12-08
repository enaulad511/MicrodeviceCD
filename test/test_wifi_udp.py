# -*- coding: utf-8 -*-
import socket
__author__ = "Edisson Naula"
__date__ = "$ 05/12/2025 at 16:26 $"

UDP_PORT = 5005  # must match Arduino's remotePort
BUFFER_SIZE = 4096
   

if __name__ == "__main__":
    # Bind to all interfaces on the Pi (including wlan0 connected to Arduino AP)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    # Allow receiving broadcast packets
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.bind(("", UDP_PORT))

    print(f"Listening for UDP on port {UDP_PORT} ...")
    try:
        while True:
            data, addr = sock.recvfrom(BUFFER_SIZE)
            try:
                text = data.decode('utf-8', errors='replace')
            except Exception:
                text = str(data)
            print(f"From {addr[0]}:{addr[1]} -> {text}")
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        sock.close()
