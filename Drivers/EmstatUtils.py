# ------function utilities------------
def construct_header_experiment(
    m_bandwidth,
    min_da,
    max_da,
    ba_range,
    min_ba,
    max_ba,
    i_forward=False,
    i_reverse=False,
):
    script = "e\nvar i\nvar e\n"
    if i_forward:
        script += "var i_forward\n"
    if i_reverse:
        script += "var i_forward\n"
    script += (
        "var i_reverse\n"
        "set_pgstat_chan 1\n"
        "set_pgstat_mode 0\n"
        "set_pgstat_chan 0\n"
        "set_pgstat_mode 2\n"
        f"set_max_bandwidth {m_bandwidth} \n"
        f"set_range_minmax da {min_da} {max_da} \n"
        f"set_range ba {ba_range}\n"
        f"set_autoranging ba {min_ba} {max_ba} \n"
    )
    return script


def construc_nscans_script_cv(
    t_equilibration,
    E_begin,
    E_vertex1,
    E_vertex2,
    E_step,
    scan_rate,
    max_bandwith,
    min_da,
    max_da,
    range_ba,
    auto_ba1,
    auto_ba2,
    n_scans,
):
    script = construct_header_experiment(
        max_bandwith,
        min_da,
        max_da,
        range_ba,
        auto_ba1,
        auto_ba2,
        i_forward=False,
        i_reverse=False,
    )

    script += f"set_e {E_begin}\ncell_on\n"
    if t_equilibration != "":
        script += (
            f"meas_loop_ca e i {E_begin} 200m {t_equilibration}\n"
            "  pck_start\n"
            "    pck_add e\n"
            "    pck_add i\n"
            "  pck_end\n"
            "endloop\n"
        )
    script += f"meas_loop_cv e i {E_begin} {E_vertex1} {E_vertex2} {E_step} {scan_rate}"
    script += f" nscans({n_scans})\n" if float(n_scans) > 1 else "\n"
    script += (
        "pck_start\npck_add e\npck_add i\npck_end\nendloop\non_finished:\ncell_off\n\n"
    )
    return script


def construc_individual_script_sqwv(
    t_equilibration,
    E_begin,
    E_end,
    E_step,
    Amplitude,
    frequency,
    max_bandwith,
    min_da,
    max_da,
    range_ba,
    auto_ba1,
    auto_ba2,
    E_con,
    t_con,
    E_dep,
    t_dep,
):
    e_start = E_begin
    sc_condition = ""
    con_flag = False
    dep_flag = False
    sc_deposition = ""
    if t_dep != "":
        e_start = E_dep
        con_flag = True
        sc_deposition = (
            f"meas_loop_ca e i {E_dep} 200m {t_dep}\n"
            "  pck_start\n"
            "    pck_add e\n"
            "    pck_add i\n"
            "  pck_end\n"
            "endloop\n"
        )
    if t_con != "":
        e_start = E_con
        dep_flag = True
        sc_condition = (
            f"meas_loop_ca e i {E_con} 200m {t_con}\n"
            "  pck_start\n"
            "    pck_add e\n"
            "    pck_add i\n"
            "  pck_end\n"
            "endloop\n"
        )
    sc_equilibrium = ""
    if t_equilibration != "":
        if con_flag or dep_flag:
            sc_equilibrium = (
                f"set_range ba {range_ba}\nset_autoranging ba {auto_ba1} {auto_ba2}\n"
            )
        sc_equilibrium += (
            f"meas_loop_ca e i {E_begin} 200m {t_equilibration}\n"
            "  pck_start\n"
            "    pck_add e\n"
            "    pck_add i\n"
            "  pck_end\n"
            "endloop\n"
        )
    script = construct_header_experiment(
        max_bandwith,
        min_da,
        max_da,
        range_ba,
        auto_ba1,
        auto_ba2,
        i_forward=True,
        i_reverse=True,
    )
    script += f"set_e {e_start}\ncell_on\n"
    script += sc_condition
    script += sc_deposition
    script += sc_equilibrium
    script += (
        f"meas_loop_swv e i i_forward i_reverse {E_begin} {E_end} {E_step} {Amplitude} {frequency}\n"
        "  pck_start\n"
        "    pck_add e\n"
        "    pck_add i\n"
        "    pck_add i_forward\n"
        "    pck_add i_reverse\n"
        "  pck_end\n"
        "endloop\n"
        "on_finished:\n"
        "  cell_off \n"
        "\n"
    )
    return script.strip()


def construct_eis_script(
    E_ac,
    f_max,
    f_min,
    n_freq,
    E_dc,
    E_con1="",
    t_con1="",
    E_con2="",
    t_con2="",
):
    """EIS (Electrochemical Impedance Spectroscopy) -- scan type Default + barrido
    de frecuencia (frequency Scan). Genera el MethodSCRIPT completo.

    Front-end verificado contra el ejemplo oficial PalmSens (set_pgstat_chan 0,
    set_pgstat_mode 3 high-speed, set_autoranging ba 10u 1m) + acondicionamiento
    opcional. No reutiliza construct_header_experiment.

    Orden de meas_loop_eis: f z_r z_i E_ac f_max f_min n_freq E_dc.

    Acondicionamiento: hasta dos bloques meas_loop_ca (E_con1/t_con1, E_con2/t_con2),
    cada uno omitido si su tiempo es "" (0). Si hay acondicionamiento se hace set_e
    inicial y se re-asegura el autorango ba tras los bloques.
    """
    # Potencial inicial: primer bloque de acondicionamiento activo, si no E_dc.
    if t_con1 != "":
        e_start = E_con1
    elif t_con2 != "":
        e_start = E_con2
    else:
        e_start = E_dc

    sc_con1 = ""
    if t_con1 != "":
        sc_con1 = (
            f"meas_loop_ca e i {E_con1} 200m {t_con1}\n"
            "  pck_start\n"
            "    pck_add e\n"
            "    pck_add i\n"
            "  pck_end\n"
            "endloop\n"
        )
    sc_con2 = ""
    if t_con2 != "":
        sc_con2 = (
            f"meas_loop_ca e i {E_con2} 200m {t_con2}\n"
            "  pck_start\n"
            "    pck_add e\n"
            "    pck_add i\n"
            "  pck_end\n"
            "endloop\n"
        )
    sc_reset_ba = ""
    if t_con1 != "" or t_con2 != "":
        # Tras el acondicionamiento, re-asegura el rango ba del EIS.
        sc_reset_ba = "set_autoranging ba 10u 1m\n"

    # Front-end verificado contra el ejemplo oficial PalmSens: canal 0, modo 3
    # (high speed, requerido por EIS) y autorango ba 10u-1m. set_e solo si hay
    # acondicionamiento (si no, el E_dc lo aplica meas_loop_eis). Las variables
    # i/e se declaran para los bloques meas_loop_ca del acondicionamiento.
    script = (
        "e\n"
        "var f\n"
        "var z_r\n"
        "var z_i\n"
        "var i\n"
        "var e\n"
        "set_pgstat_chan 0\n"
        "set_pgstat_mode 3\n"
        "set_autoranging ba 10u 1m\n"
    )
    if t_con1 != "" or t_con2 != "":
        script += f"set_e {e_start}\n"
    script += "cell_on\n"
    script += sc_con1
    script += sc_con2
    script += sc_reset_ba
    script += (
        f"meas_loop_eis f z_r z_i {E_ac} {f_max} {f_min} {n_freq} {E_dc}\n"
        "  pck_start\n"
        "    pck_add f\n"
        "    pck_add z_r\n"
        "    pck_add z_i\n"
        "  pck_end\n"
        "endloop\n"
        "on_finished:\n"
        "  cell_off\n"
        "\n"
    )
    return script


class EmstatStreamParser:
    """
    Parser general de streams EmStat (CV, SWV, EIS, etc.)

    - Entrada: raw string (una línea del EmStat)
    - Salida: dict estructurado (dato o evento) o None
    """

    FIELD_MAP = {
        "cv": {"da": ("E_V", 1e-6), "ba": ("I_A", 1e-12)},
        "sqwv": {
            "da": ("E_V", 1e-6),
            "ba": ("I_A", 1e-12),
            "ba_1": ("I_A_F", 1e-12),
            "ba_2": ("I_A_R", 1e-12),
        },
        # Códigos de paquete REALES del EmStat en EIS (verificados en salida cruda):
        #   dc = frecuencia, cc = Z_real, cd = Z_imag.
        # (La columna 'scale' es vestigial: _decode solo aplica el prefijo de unidad.
        #  La negación de Z_imag para el Nyquist se hace explícita en _decode.)
        "eis": {"dc": ("freq_Hz", 1), "cc": ("Z_real", 1), "cd": ("Z_imag", 1)},
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
            self.context["cycle"] = self._safe_hex(raw[1:])
            return {"type": "cycle", "cycle": self.context["cycle"]}

        if kind == "method":
            # El índice del marcador (p.ej. M000D) es HEX, no decimal.
            self.context["method_id"] = self._safe_hex(raw[1:])
            return {"type": "method", "method_id": self.context["method_id"]}

        if kind == "start_method":
            return {"type": "start_method"}

        if kind == "end_block":
            self.finished = True
            return {"type": "method_end"}
        
        if kind =="syntax_error":
            return {"type": "error", "raw": raw}

        # ruido o mensajes no relevantes
        return {"type": "unknown", "raw": raw}

    # ------------------------------------------------------------------
    # Clasificador
    # ------------------------------------------------------------------
    @staticmethod
    def _safe_hex(s: str):
        """Convierte un índice hex (marcadores M/C del EmStat) a int. 0 si falla."""
        try:
            return int(s, 16)
        except (ValueError, TypeError):
            return 0

    def _classify(self, raw: str):
        if raw.startswith("P"):
            return "packet"
        if raw.startswith("e!"):
            return "syntax_error"
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
        self.context["point"] = int(parsed["index"][0])

        decoded.update(
            {
                "type": "data",
                "cycle": self.context["cycle"],
                "direction": self.context["direction"],
                "point": parsed["index"],
                "state": parsed["state"],
            }
        )

        # EIS: los paquetes de acondicionamiento (da/ba) no traen campos Z; no son
        # puntos del Nyquist. Marcarlos como no-dato evita graficar (0,0) espurios.
        if self.experiment == "eis" and "Z_real" not in decoded and "Z_imag" not in decoded:
            decoded["type"] = "unknown"

        return decoded

    def _parse_packet(self, line: str):
        try:
            bodies = line[1:].split(";")
            indexes = []
            states = []
            fields = {}
            for body in bodies:
                parts = body.split(",")
                key_base = parts[0][:2]
                unit = parts[0][-1]
                raw_val = parts[0][2:-1]
                if len(parts) > 1:
                    indexes.append(int(parts[-1][:-1]))
                    states.append(parts[-2])
                value = int(raw_val, 16) - 0x8000000
                key = key_base
                counter = 1
                while key in fields:
                    key = f"{key_base}_{counter}"
                    counter += 1
                fields[key] = {"value": value, "unit": unit, "value_hex": raw_val}

            return {"fields": fields, "state": states, "index": indexes}

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
        # Nyquist: el eje Y es -Z_imag por convención (semicírculos hacia arriba).
        if self.experiment == "eis" and "Z_imag" in out:
            out["Z_imag"] = -out["Z_imag"]
        return out


class LineBufferedSocketReader:
    def __init__(self, sock, encoding="utf-8", max_buffer=65536):
        self.sock = sock
        self.encoding = encoding
        self.buffer = bytearray()
        self.max_buffer = max_buffer

    def read_lines(self):
        try:
            data = self.sock.recv(4096)
        except Exception:
            return None
        if not data:
            return None  # conexión cerrada

        self.buffer.extend(data)

        # protección contra runaway buffer
        if len(self.buffer) > self.max_buffer:
            raise RuntimeError("RX buffer overflow: receiver too slow")

        lines = []
        while True:
            nl = self.buffer.find(b"\n")
            if nl == -1:
                break

            line = self.buffer[:nl]
            del self.buffer[: nl + 1]

            try:
                lines.append(line.decode(self.encoding, errors="replace").strip())
            except Exception:
                continue

        return lines


# class LineBufferedSocketReader:
#     def __init__(self, sock, encoding="utf-8"):
#         self.sock = sock
#         self.encoding = encoding
#         self.buffer = ""

#     def read_lines(self):
#         """
#         Lee del socket y devuelve una lista de líneas completas (sin '\n').
#         Puede devolver lista vacía si aún no hay líneas completas.
#         """
#         data = self.sock.recv(2048)
#         if not data:
#             return None  # conexión cerrada

#         self.buffer += data.decode(self.encoding, errors="replace")

#         lines = []
#         while "\n" in self.buffer:
#             line, self.buffer = self.buffer.split("\n", 1)
#             lines.append(line.strip())

#         return lines


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
