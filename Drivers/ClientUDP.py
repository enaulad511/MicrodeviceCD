# -*- coding: utf-8 -*-
from dataclasses import dataclass
from templates.constants import secrets
import datetime
import json
import socket
import threading
import time
from typing import Callable, Optional

__author__ = "Edisson Naula"
__date__ = "$ 05/12/2025 at 16:26 $"


@dataclass
class TempSample:
    value: float
    ts: float


class UdpClient:
    """
    Simple UDP client to listen for Arduino messages (broadcast or unicast).
    - Binds to a port (default 5005).
    - Optionally binds to a specific local IP (e.g., interface wlan0).
    - Runs either in blocking mode (listen_forever) or background thread (start/stop).
    - Calls an optional callback with (text, addr) for each received message.
    """

    def __init__(
        self,
        port: int = 5005,
        buffer_size: int = 512,
        allow_broadcast: bool = True,
        local_ip: str = "",  # "" => all interfaces; or set to your wlan0 IP
        decode: str = "utf-8",
        recv_timeout_sec: Optional[float] = None,
        on_message: Callable[[str, tuple, list], None] | None = None,
        parse_float: bool = False,
        save_data=True,
        stop_event=None,
        debug=False,
        prefixCol="",
    ):
        """
        :param port: UDP port to bind.
        :param buffer_size: Maximum packet size to read.
        :param allow_broadcast: Enables SO_BROADCAST to receive broadcast frames.
        :param local_ip: Local interface IP to bind. "" binds to all (0.0.0.0).
        :param decode: Text encoding for payloads.
        :param recv_timeout_sec: Optional socket timeout (seconds). None => blocking.
        :param on_message: Optional callback called for each message: (text, addr).
        :param parse_float: If True, tries to parse payload as float and prints it.
        """
        self.port = port
        self.buffer_size = buffer_size
        self.allow_broadcast = allow_broadcast
        self.local_ip = local_ip
        self.decode = decode
        self.recv_timeout_sec = recv_timeout_sec
        self.on_message = on_message
        self.parse_float = parse_float
        self.save_data = save_data
        self.filename = "data_temps.csv"
        if save_data:
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.filename = f"data_temps-{timestamp}.csv"
            # self.initial_file(self.filename, prefixcolum=prefixCol)
        self._sock = None
        self._thread = None
        self._stop_evt = threading.Event() if stop_event is None else stop_event
        self._latest_text = None
        self._latest_float = 20.0
        self._latest_addr = None
        self.data_temps = [20.0, 20.0, 20.0]
        self.status_disc = False
        self.latest_temp = None
        self.latest_lock = threading.Lock()

        self.debug = debug

    def _create_socket(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # Permite reutilizar la dirección
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        # Habilitar broadcast si es necesario
        if self.allow_broadcast:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        # ⚠️ IMPORTANTE: Reducir buffer interno del kernel
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 512)

        # ⚠️ IMPORTANTE: Modo no bloqueante para leer el paquete más reciente
        sock.setblocking(False)

        # Timeout opcional (afecta solo llamadas blocking, pero lo dejamos)
        if self.recv_timeout_sec is not None:
            sock.settimeout(self.recv_timeout_sec)
            print(f"[UdpClient] Socket timeout set to {self.recv_timeout_sec}s")

        # Bind
        bind_ip = self.local_ip if self.local_ip else ""
        sock.bind((bind_ip, self.port))

        return sock

    def start(self):
        """Start listening in a background thread."""
        if self._thread and self._thread.is_alive():
            return  # already running
        self._stop_evt.clear()
        self._sock = self._create_socket()  # pyrefly: ignore

        self._thread = threading.Thread(
            target=self._run_loop, daemon=True
        )  # pyrefly: ignore
        self._thread.start()  # pyrefly: ignore
        print(
            f"[UdpClient] Listening on {self.local_ip or '0.0.0.0'}:{self.port} (threaded)"
        )

    def stop(self):
        """Stop the background thread and close the socket."""
        self._stop_evt.set()
        if self._sock:
            try:
                # Send a dummy packet to unblock recvfrom if needed (optional)
                # socket.socket(...).sendto(b'', ('127.0.0.1', self.port))
                self._sock.close()
            except Exception:
                pass
            self._sock = None

        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        print("[UdpClient] Stopped.")

    def listen_forever(self):
        """
        Blocking mode: run the receive loop in the current thread.
        Useful for simple scripts.
        """
        self._sock = self._create_socket()  # pyrefly: ignore
        print(
            f"[UdpClient] Listening on {self.local_ip or '0.0.0.0'}:{self.port} (blocking)"
        )
        try:
            self._run_loop()
        finally:
            try:
                self._sock.close()  # pyrefly: ignore
            except Exception:
                pass
            self._sock = None

    def _run_loop(self):
        assert self._sock is not None, "Socket must be created before running loop."

        while not self._stop_evt.is_set():
            try:
                data, addr = self._sock.recvfrom(self.buffer_size)
                text = data.decode(errors="replace")

                if "UDP" not in text:
                    continue

                payload = text.split("UDP:", 1)[-1]
                temps = payload.split(":")
                temp = float(temps[2])

                now = time.time()
                self.status_disc = True

                with self.latest_lock:
                    self.latest_temp = TempSample(value=temp, ts=now)
                    if self.on_message:
                        try:
                            self.on_message(
                                text,
                                ("last_addr",),
                                [0, 0, self.latest_temp.value, self.latest_temp.ts],
                            )
                            
                        except Exception as e:
                            print(f"[UdpClient] on_message error: {e}")

            except BlockingIOError:
                time.sleep(0.0005)
            except Exception as e:
                time.sleep(0.0005)
            # last_data = None
            # last_addr = None

            # # Vaciamos el buffer completo
            # while True:
            #     try:
            #         data, addr = self._sock.recvfrom(self.buffer_size)
            #         last_data = data
            #         last_addr = addr
            #         self.status_disc = True
            #     except BlockingIOError:
            #         # No hay más paquetes pendientes
            #         break
            #     except Exception:
            #         # print(f"[UdpClient] recv error: {e}")
            #         break

            # # Si no llegó ningún paquete en este ciclo, seguimos
            # if last_data is None:
            #     time.sleep(0.0005)
            #     continue

            # # Decodificamos solo el ÚLTIMO paquete
            # try:
            #     text = last_data.decode(self.decode, errors="replace").strip()
            #     if "UDP" in text:
            #         payload = text.split("UDP:", 1)[-1]
            #         self.data_temps = payload.split(":")
            #         self._latest_float = float(self.data_temps[-1])
            #         self.status_disc = True
            #     else:
            #         raise ValueError("Invalid packet")
            # except Exception:
            #     # Si falla el JSON usamos la última temperatura válida
            #     # self.data_temps = {
            #     #     "type": "unknown",
            #     #     "timestamp_ms": time.time_ns() // 1_000_000,
            #     #     "mlx_ambient": 0.0,
            #     #     "mlx_object": 0.0,
            #     #     "max31855": self._latest_float,
            #     #     "unit": "unknown",
            #     # }
            #     self.data_temps = [0.0, 0.0, self._latest_float]
            #     self.status_disc = False
            #     # print("error uod check")
            #     text = str(last_data)

            # self._latest_text = text
            # self._latest_addr = last_addr

            # Ejecutamos callback SOLO una vez por batch
            # if self.on_message:
            #     try:
            #         self.on_message(text, last_addr, self.data_temps)
            #     except Exception as e:
            #         print(f"[UdpClient] on_message error: {e}")

            # # Muy pequeño delay para bajar CPU, sin afectar tiempo real
            # time.sleep(0.0005)

    def initial_file(self, filename="data_temps.csv", prefixcolum=""):
        if secrets.get("environment", "") == "dev":
            return
        # save header in txt
        if prefixcolum:
            header = prefixcolum + "temperature\n"
        else:
            header = "temperature\n"
        with open(filename, "w") as f:
            f.write(header)

    def save_data_file(self, filename=None):
        if secrets.get("environment", "") == "dev":
            return
        # save logs temps in txt
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if filename is None:
            filename = f"data_temps-{timestamp}.csv"
        # line = f"{timestamp} -- {self.data_temps['max31855']}

        with open(filename, "a") as f:
            line = f"{timestamp},{self.data_temps[2]}\n"
            f.write(line)
        # print(f"[UdpClient] Saved data: {filename}")

    # ---- Convenience getters ----
    def latest_text(self) -> Optional[str]:
        return self._latest_text

    def latest_float(self) -> Optional[float]:
        return self._latest_float

    def latest_addr(self) -> Optional[tuple]:
        return self._latest_addr

    def latest_temps(self):
        return self.data_temps

    def get_status_disc(self):
        return self.status_disc


# Example usage
if __name__ == "__main__":
    # Option A: simple blocking listener
    # client = UdpClient(port=5005, allow_broadcast=True, parse_float=True)
    # client.listen_forever()

    # Option B: threaded listener with callback
    def handle_message(text: str, addr: tuple, temps_dict: dict):
        # You can parse JSON, write to CSV, update a plot, etc.
        # For your Arduino, payload is a temperature string like "23.58"
        try:
            value = float(text)
            # Example: filter out nonsense values
            if -200.0 < value < 2000.0:
                print(f"[CB] Temp: {value:.2f} °C from {addr[0]}")
            else:
                print(f"[CB] Out-of-range value: {value}")
        except Exception:
            print(f"[CB] Raw: {text} from {addr[0]}")

    client = UdpClient(
        port=5005,
        buffer_size=512,
        allow_broadcast=True,  # Important for broadcast payloads
        local_ip="",  # "" listens on all interfaces (wlan0, eth0, etc.)
        recv_timeout_sec=1.0,  # lets loop check stop flag periodically
        on_message=handle_message,
        parse_float=True,  # Arduino sends a numeric string
    )

    try:
        client.start()
        print("Client running. Press Ctrl+C to stop.")
        while True:
            time.sleep(1.0)
            # You can read the latest value any time:
            lf = client.latest_float()
            if lf is not None:
                # do something with lf
                pass
    except KeyboardInterrupt:
        print("\nStopping client...")
    finally:
        client.stop()
