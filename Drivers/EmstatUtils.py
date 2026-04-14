class EmstatStreamParser:
    """
    Parser general de streams EmStat (CV, SWV, EIS, etc.)

    - Entrada: raw string (una línea del EmStat)
    - Salida: dict estructurado (dato o evento) o None
    """

    FIELD_MAP = {
        "cv": {"da": ("E_V", 1e-6), "ba": ("I_A", 1e-12)},
        "swv": {"da": ("E_V", 1e-6), "ba": ("I_A", 1e-12), "fr": ("freq_Hz", 1)},
        "eis": {"fr": ("freq_Hz", 1), "zr": ("Z_real", 1e-3), "zi": ("Z_imag", 1e-3)},
    }
    UNIT_MAP = {
        "a": 1e-18,
        "f": 1e-15,
        "p": 1e-12,
        "n": 1e-9,
        "u": 1e-6,
        "m": 1e-3,
        " ": 1,
        "k": 1e3,
        "M": 1e6,
        "G": 1e9,
        "T": 1e12,
    }

    def __init__(self, experiment: str):
        if experiment not in self.FIELD_MAP:
            raise ValueError(f"Unsupported experiment: {experiment}")

        self.experiment = experiment

        # Contexto dinámico
        self.context = {"cycle": 0, "direction": +1, "point": 0, "method_id": None}

        self.finished = False

    # ------------------------------------------------------------------
    # API principal
    # ------------------------------------------------------------------
    def feed_raw(self, raw: str):
        """
        Procesa una línea cruda del EmStat.
        Retorna un dict estructurado o None.
        """
        raw = raw.strip()
        if not raw:
            return None

        kind = self._classify(raw)

        if kind == "packet":
            return self._handle_packet(raw)

        if kind == "scan_switch":
            self.context["direction"] *= -1
            return {"type": "scan_switch", "direction": self.context["direction"]}

        if kind == "cycle":
            self.context["cycle"] = int(raw[1:])
            return {"type": "cycle", "cycle": self.context["cycle"]}

        if kind == "method":
            self.context["method_id"] = int(raw[1:])
            return {"type": "method", "method_id": self.context["method_id"]}

        if kind == "start_method":
            return {"type": "start_method"}

        if kind == "end_block":
            self.finished = True
            return {"type": "method_end"}

        # ruido o mensajes no relevantes
        return {"type": "unknown", "raw": raw}

    # ------------------------------------------------------------------
    # Clasificador
    # ------------------------------------------------------------------
    def _classify(self, raw: str):
        if raw.startswith("P"):
            return "packet"
        if raw == "-":
            return "scan_switch"
        if raw.startswith("C"):
            return "cycle"
        if raw.startswith("M"):
            return "method"
        if raw == "*":
            return "end_block"
        if raw == "e":
            return "start_method"
        return "unknown"

    # ------------------------------------------------------------------
    # Packet parsing
    # ------------------------------------------------------------------
    def _handle_packet(self, raw: str):
        parsed = self._parse_packet(raw)
        if parsed is None:
            return None
        decoded = self._decode(parsed)
        self.context["point"] = parsed["index"]

        decoded.update(
            {
                "type": "data",
                "cycle": self.context["cycle"],
                "direction": self.context["direction"],
                "point": parsed["index"],
                "state": parsed["state"],
            }
        )

        return decoded

    def _parse_packet(self, line: str):
        try:
            body, state, idx_end = line[1:].rsplit(",", 2)
            index = int(idx_end[:-1])
            fields = {}

            for part in body.split(";"):
                key = part[:2]
                unit = part[-1]
                raw_val = part[2:-1]

                value = int(raw_val, 16) - 0x8000000
                # value = (
                #     int(raw_val, 16)
                #     if any(c in raw_val for c in "ABCDEF")
                #     else int(raw_val)
                # )
                fields[key] = {"value": value, "unit": unit, "value_hex": raw_val}

            return {"fields": fields, "state": int(state), "index": index}

        except Exception:
            return None

    # ------------------------------------------------------------------
    # Decodificador por experimento
    # ------------------------------------------------------------------
    def _decode(self, parsed):
        schema = self.FIELD_MAP[self.experiment]
        out = {}

        for key, (name, scale) in schema.items():
            f = parsed["fields"].get(key)
            if f:
                out[name] = f["value"] * self.UNIT_MAP.get(f["unit"], 1)

        return out


class LineBufferedSocketReader:
    def __init__(self, sock, encoding="utf-8"):
        self.sock = sock
        self.encoding = encoding
        self.buffer = ""

    def read_lines(self):
        """
        Lee del socket y devuelve una lista de líneas completas (sin '\n').
        Puede devolver lista vacía si aún no hay líneas completas.
        """
        data = self.sock.recv(2048)
        if not data:
            return None  # conexión cerrada

        self.buffer += data.decode(self.encoding, errors="replace")

        lines = []
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            lines.append(line.strip())

        return lines


if __name__ == "__main__":
    parser = EmstatStreamParser(experiment="cv")
    raw = 'EMSTAT:{"raw": "Pda7FCF2C0m;ba7F77482p,14,20B", "type": "emstat_data"}'
    while True:
        # raw = get_raw_line_somehow()
        event = parser.feed_raw(raw)
        if event is None:
            continue
        if event["type"] == "data":
            print(event["E_V"], event["I_A"])
        elif event["type"] == "scan_switch":
            print("Cambio de barrido")
        elif event["type"] == "cycle":
            print("Scan:", event["cycle"])
        elif event["type"] == "method_end":
            print("Experimento terminado")
            break
