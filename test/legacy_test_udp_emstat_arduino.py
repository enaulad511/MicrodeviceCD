#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cliente TCP para MKR WiFi 1010:
  - Conecta a <IP>:5006
  - Envía comando de medición (LSV/CV)
  - Lee ACK/ERR y líneas de datos durante la sesión
  - (Opcional) parsea p/c y guarda CSV

Ejemplos:
  python ms_tcp_client.py --ip 192.168.1.123 --cmd "RUN,LSV,-500m,500m,10m,40m,2"
  python ms_tcp_client.py --ip 192.168.1.123 --cmd "RUN,CV,-500m,-1,1,10m,40m,2" --csv out.csv

Notas:
  - El comando es una sola línea terminada en '\n'.
  - Si tu firmware cierra el socket al finalizar, el cliente sale limpiamente.
"""

import argparse
import socket
import sys
import time
import re
from typing import Optional, Tuple

# Parámetros TCP por defecto
CONTROL_PORT = 5006
CONNECT_TIMEOUT = 5.0  # segundos para conectar
READ_TIMEOUT = 2.0  # timeout para lectura (renovable en el loop)
IDLE_EXIT_AFTER = (
    None  # si quieres salir tras N segundos sin datos, pon un número (float)
)

# Regex opcional para intentar extraer p/c de líneas
RE_FLOAT = r"[-+]?(?:\d+\.?\d*|\d*\.?\d+)(?:[eE][-+]?\d+)?"
# Intenta capturar formatos tipo: "p: <valor>" / "c: <valor>" / "p=<valor>, c=<valor>"
RE_P = re.compile(rf"(?:^|\W)p(?:[:=])\s*(?P<p>{RE_FLOAT})", re.IGNORECASE)
RE_C = re.compile(rf"(?:^|\W)c(?:[:=])\s*(?P<c>{RE_FLOAT})", re.IGNORECASE)


def parse_pc_from_line(line: str) -> Tuple[Optional[float], Optional[float]]:
    """Intenta extraer p/c de una línea de texto."""
    p_val = None
    c_val = None
    m = RE_P.search(line)
    if m:
        try:
            p_val = float(m.group("p"))
        except Exception:
            pass
    m = RE_C.search(line)
    if m:
        try:
            c_val = float(m.group("c"))
        except Exception:
            pass
    return p_val, c_val


def write_csv_header(fp):
    fp.write("timestamp_iso,p,c,raw_line\n")


def write_csv_row(fp, p, c, raw):
    ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
    # Escapa comas en raw
    safe_raw = raw.replace("\n", "\\n").replace("\r", "")
    fp.write(f'{ts},{"" if p is None else p},{"" if c is None else c},"{safe_raw}"\n')
    fp.flush()


def send_line(sock: socket.socket, line: str):
    if not line.endswith("\n"):
        line = line + "\n"
    sock.sendall(line.encode("utf-8"))


def recv_lines(sock: socket.socket, bufsize: int = 4096):
    """Generador de líneas desde un socket TCP (line-buffered)."""
    buffer = b""
    while True:
        try:
            chunk = sock.recv(bufsize)
        except socket.timeout:
            # Permite a la capa superior decidir continuar o salir
            yield None
            continue
        if not chunk:
            # Conexión cerrada por el servidor
            break
        buffer += chunk
        while b"\n" in buffer:
            line, buffer = buffer.split(b"\n", 1)
            yield line.decode(errors="replace")


def main():
    ap = argparse.ArgumentParser(
        description="Cliente TCP para mediciones MethodSCRIPT."
    )
    ap.add_argument(
        "--ip", required=True, help="IP del MKR WiFi 1010 (WiFiServer en 5006)"
    )
    ap.add_argument(
        "--port", type=int, default=CONTROL_PORT, help="Puerto TCP (defecto 5006)"
    )
    ap.add_argument(
        "--cmd",
        required=True,
        help="Comando a enviar, p.ej. 'RUN,LSV,-500m,500m,10m,40m,2'",
    )
    ap.add_argument(
        "--csv", default=None, help="Ruta CSV para guardar datos (opcional)"
    )
    ap.add_argument(
        "--no-parse",
        action="store_true",
        help="No intentar parsear p/c; sólo imprimir líneas",
    )
    ap.add_argument(
        "--connect-timeout",
        type=float,
        default=CONNECT_TIMEOUT,
        help="Timeout de conexión TCP (s)",
    )
    ap.add_argument(
        "--read-timeout",
        type=float,
        default=READ_TIMEOUT,
        help="Timeout de lectura TCP (s)",
    )
    ap.add_argument(
        "--idle-exit",
        type=float,
        default=IDLE_EXIT_AFTER,
        help="Salir si no llegan datos en N segundos (opcional)",
    )

    args = ap.parse_args()

    csv_fp = None
    if args.csv:
        csv_fp = open(args.csv, "w", encoding="utf-8")
        write_csv_header(csv_fp)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(
        args.connect - timeout
        if hasattr(args, "connect-timeout")
        else args.connect_timeout
    )
    try:
        print(f"[TCP] conectando a {args.ip}:{args.port} ...")
        sock.connect((args.ip, args.port))
        print("[TCP] conectado.")

        # Enviar el comando
        send_line(sock, args.cmd)
        print(f"[TX] {args.cmd}")

        # Leer ACK/ERR y luego datos
        sock.settimeout(args.read_timeout)
        last_data_ts = time.time()

        for line in recv_lines(sock):
            if line is None:
                # Timeout de lectura sin datos
                if args.idle_exit is not None:
                    if time.time() - last_data_ts > args.idle_exit:
                        print(f"[INFO] Sin datos por > {args.idle_exit}s. Saliendo.")
                        break
                continue

            last_data_ts = time.time()
            clean = line.strip()
            if not clean:
                continue

            print(f"[RX] {clean}")
            if "err" in clean.lower():
                break
            # Si el servidor envía "ACK" / "ERR" / "Measurement completed", se verá aquí
            # Intento de parseo p/c (si no deshabilitado)
            p_val = c_val = None
            if not args.no_parse:
                p_val, c_val = parse_pc_from_line(clean)

            # Guardar CSV si corresponde
            if csv_fp:
                write_csv_row(csv_fp, p_val, c_val, clean)

        print("[TCP] conexión cerrada (servidor finalizó o timeout).")

    except (socket.timeout, ConnectionRefusedError) as e:
        print(f"[ERROR] conexión/IO: {e}")
        sys.exit(1)
    finally:
        try:
            sock.close()
            print("closed socket")
        except Exception:
            pass
        if csv_fp:
            csv_fp.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrumpido por el usuario.")
        sys.exit(0)
