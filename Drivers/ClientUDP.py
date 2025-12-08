
# -*- coding: utf-8 -*-
import socket
import threading
import time
from typing import Callable, Optional

__author__ = "Edisson Naula"
__date__ = "$ 05/12/2025 at 16:26 $"


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
        buffer_size: int = 4096,
        allow_broadcast: bool = True,
        local_ip: str = "",  # "" => all interfaces; or set to your wlan0 IP
        decode: str = "utf-8",
        recv_timeout_sec: Optional[float] = None,
        on_message: Optional[Callable[[str, tuple], None]] = None,
        parse_float: bool = False,
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

        self._sock = None
        self._thread = None
        self._stop_evt = threading.Event()
        self._latest_text = None
        self._latest_float = None
        self._latest_addr = None

    def _create_socket(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Allow reuse so you can restart without "address already in use"
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        if self.allow_broadcast:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        # Optional receive timeout
        if self.recv_timeout_sec is not None:
            sock.settimeout(self.recv_timeout_sec)

        # Bind: "" means all interfaces; otherwise the given local_ip (e.g., wlan0 IP)
        bind_ip = self.local_ip if self.local_ip else ""
        sock.bind((bind_ip, self.port))
        return sock

    def start(self):
        """Start listening in a background thread."""
        if self._thread and self._thread.is_alive():
            return  # already running
        self._stop_evt.clear()
        self._sock = self._create_socket()  # pyrefly: ignore

        self._thread = threading.Thread(target=self._run_loop, daemon=True) # pyrefly: ignore
        self._thread.start()    # pyrefly: ignore
        print(f"[UdpClient] Listening on {self.local_ip or '0.0.0.0'}:{self.port} (threaded)")

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
        self._sock = self._create_socket()   # pyrefly: ignore
        print(f"[UdpClient] Listening on {self.local_ip or '0.0.0.0'}:{self.port} (blocking)")
        try:
            self._run_loop()
        finally:
            try:
                self._sock.close()      # pyrefly: ignore
            except Exception:
                pass
            self._sock = None

    def _run_loop(self):
        assert self._sock is not None, "Socket must be created before running loop."
        while not self._stop_evt.is_set():
            try:
                data, addr = self._sock.recvfrom(self.buffer_size)
            except socket.timeout:
                # Timeout to check stop flag periodically
                continue
            except OSError:
                # Socket closed while waiting
                break
            except Exception as e:
                print(f"[UdpClient] recv error: {e}")
                continue

            try:
                text = data.decode(self.decode, errors="replace").strip()
            except Exception:
                text = str(data)

            self._latest_text = text    # pyrefly: ignore
            self._latest_addr = addr

            if self.parse_float:
                try:
                    self._latest_float = float(text)    # pyrefly: ignore
                except Exception:
                    self._latest_float = None   # pyrefly: ignore

            # Print basic info
            if self.parse_float and self._latest_float is not None:
                print(f"From {addr[0]}:{addr[1]} -> {self._latest_float:.2f}")
            else:
                print(f"From {addr[0]}:{addr[1]} -> {text}")

            # Call user callback if provided
            if self.on_message:
                try:
                    self.on_message(text, addr)
                except Exception as e:
                    print(f"[UdpClient] on_message error: {e}")

            # Small sleep to avoid burning CPU (optional)
            time.sleep(0.005)

    # ---- Convenience getters ----
    def latest_text(self) -> Optional[str]:
        return self._latest_text

    def latest_float(self) -> Optional[float]:
        return self._latest_float

    def latest_addr(self) -> Optional[tuple]:
        return self._latest_addr


# Example usage
if __name__ == "__main__":
    # Option A: simple blocking listener
    # client = UdpClient(port=5005, allow_broadcast=True, parse_float=True)
    # client.listen_forever()

    # Option B: threaded listener with callback
    def handle_message(text: str, addr: tuple):
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
        buffer_size=4096,
        allow_broadcast=True,    # Important for broadcast payloads
        local_ip="",             # "" listens on all interfaces (wlan0, eth0, etc.)
        recv_timeout_sec=1.0,    # lets loop check stop flag periodically
        on_message=handle_message,
        parse_float=True,        # Arduino sends a numeric string
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

