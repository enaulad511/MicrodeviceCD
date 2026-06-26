import json
import math
import os
import re

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
        script += "var i_reverse\n"
    script += (
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
    # Cada bloque requiere TIEMPO y POTENCIAL: con el tiempo pero sin potencial se
    # generaba 'set_e ' / 'meas_loop_ca e i  200m t' (potencial vacío) -> e!4001/e!4008.
    if t_dep != "" and E_dep != "":
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
    if t_con != "" and E_con != "":
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
    scan_type=1,
    bandwidth="",
    E_begin="",
    E_step="",
    E_break="",
    E_dir=1,
    t_run=0,
    t_interval=0,
):
    """EIS (Electrochemical Impedance Spectroscopy). Genera el MethodSCRIPT completo
    para los modos de la Fase 2 (ver docs/eis_impedancia.md, seccion 7).

    Front-end comun (los 5 modos): el de Fase 1 verificado contra el ejemplo oficial
    PalmSens (chan 0, mode 3 high-speed, autorango ba 10u-1m) + dos adopciones del
    export PSTrace: set_e inicial INCONDICIONAL antes de cell_on y set_max_bandwidth
    (10x la frecuencia maxima, calculado por el caller). No reutiliza
    construct_header_experiment.

    scan_type (cuerpo del script):
      1 = Default: un meas_loop_eis directo a E_dc.
      2 = E_dc Scan: loop generico PSTrace (store_var/loop/add_var/breakloop) con el
          potencial en extra1; cada paquete agrega pck_add extra1 (desviacion nuestra
          del export para que los datos sean autodescriptivos). E_step llega CON signo;
          E_break = E_end + signo*E_step/2 (tolerancia de medio paso); E_dir elige la
          comparacion del breakloop (1 ascendente '>', -1 descendente '<').
      3 = Time Scan: UN solo meas_loop_eis con n_freq = t_run/t_interval + 1
          repeticiones, pacificado por timer_start/set_int/await_int (patron exacto
          del export PSTrace); el tiempo transcurrido viaja en extra1 (tipo eb) y el
          script corta con abort al llegar a t_run.

    El tipo de frecuencia NO llega aqui: el caller degenera f_max=f_min=f y n_freq=1
    (o n_meas en Time Scan) para frecuencia fija. Orden de meas_loop_eis:
    f z_r z_i E_ac f_max f_min n_freq E_dc.

    Acondicionamiento: hasta dos bloques meas_loop_ca (E_con1/t_con1, E_con2/t_con2),
    cada uno omitido si su tiempo es "" (0); tras ellos se re-asegura el autorango ba.

    IMPORTANTE: esta funcion vive duplicada byte a byte en DiscPCB/EmstatDrivers.py
    (Pico). Cualquier cambio aqui debe replicarse alla y flashearse.
    """
    # Potencial inicial: primer bloque de acondicionamiento activo, si no el
    # potencial inicial del modo (E_begin en barrido de potencial, E_dc en el resto).
    if t_con1 != "":
        e_start = E_con1
    elif t_con2 != "":
        e_start = E_con2
    elif scan_type == 2:
        e_start = E_begin
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

    # Las variables i/e se declaran para los bloques meas_loop_ca del
    # acondicionamiento; extra1 solo cuando el modo la usa (potencial o tiempo).
    script = "e\nvar f\nvar z_r\nvar z_i\nvar i\nvar e\n"
    if scan_type in (2, 3):
        script += "var extra1\n"
    script += "set_pgstat_chan 0\nset_pgstat_mode 3\n"
    if bandwidth != "":
        script += f"set_max_bandwidth {bandwidth}\n"
    script += "set_autoranging ba 10u 1m\n"
    script += f"set_e {e_start}\n"
    script += "cell_on\n"
    script += sc_con1
    script += sc_con2
    script += sc_reset_ba

    if scan_type == 2:
        cmp_op = ">" if E_dir >= 0 else "<"
        script += (
            f"store_var extra1 {E_begin} da\n"
            "loop 1i == 1i\n"
            f"  meas_loop_eis f z_r z_i {E_ac} {f_max} {f_min} {n_freq} extra1\n"
            "    pck_start\n"
            "      pck_add f\n"
            "      pck_add z_r\n"
            "      pck_add z_i\n"
            "      pck_add extra1\n"
            "    pck_end\n"
            "  endloop\n"
            f"  add_var extra1 {E_step}\n"
            f"  if extra1 {cmp_op} {E_break}\n"
            "    breakloop\n"
            "  endif\n"
            "endloop\n"
        )
    elif scan_type == 3:
        script += (
            "store_var extra1 0 eb\n"
            f"meas_loop_eis f z_r z_i {E_ac} {f_max} {f_min} {n_freq} {E_dc}\n"
            "  if extra1 == 0\n"
            "    timer_start\n"
            f"    set_int {t_interval}\n"
            "  else\n"
            "    timer_get extra1\n"
            "  endif\n"
            "  pck_start\n"
            "    pck_add f\n"
            "    pck_add z_r\n"
            "    pck_add z_i\n"
            "    pck_add extra1\n"
            "  pck_end\n"
            "  if extra1 == 0\n"
            f"    store_var extra1 {t_interval} eb\n"
            "  endif\n"
            f"  if extra1 >= {t_run}\n"
            "    abort\n"
            "  endif\n"
            "  await_int\n"
            "endloop\n"
        )
    else:
        script += (
            f"meas_loop_eis f z_r z_i {E_ac} {f_max} {f_min} {n_freq} {E_dc}\n"
            "  pck_start\n"
            "    pck_add f\n"
            "    pck_add z_r\n"
            "    pck_add z_i\n"
            "  pck_end\n"
            "endloop\n"
        )

    script += "on_finished:\n  cell_off\n\n"
    return script


def construct_ca_script(
    t_equilibration,
    E_dc,
    t_interval,
    t_run_main,
    max_bandwith,
    min_da,
    max_da,
    range_ba,
    auto_ba1,
    auto_ba2,
):
    """CA (Chronoamperometry). Genera el MethodSCRIPT de un escalón de potencial a
    ``E_dc`` constante muestreado cada ``t_interval`` durante ``t_run``.

    Reusa ``construct_header_experiment`` igual que CV (mismo modo 2, ``da`` fijado a
    ``min_da``/``max_da`` que el caller pone en E_dc porque el potencial es constante).

    Loops (verificado contra exports PSTrace, ver docs/ca_cronoamperometria.md):
      - Equilibrio (opcional, si ``t_equilibration`` != ""): un ``meas_loop_ca`` a
        ``E_dc`` con intervalo FIJO ``200m`` y duración ``t_equilibration`` exacta
        (convención compartida con CV/SQWV). Es solo acondicionamiento.
      - Principal: ``meas_loop_ca`` a ``E_dc`` con el ``t_interval`` del usuario y
        duración ``t_run_main`` = ``t_run + t_interval`` (un intervalo extra para que
        el loop semiabierto capture el punto en ``t = t_run``; el caller ya hizo la
        suma y la convirtió a SI).

    Cada paquete agrega ``e``/``i`` (potencial/corriente); NO hay campo de tiempo en
    el dato: el eje ``t`` se sintetiza en el host (``índice × t_interval``, parser
    "ca"). El equilibrio se excluye del plot en vivo detectando el marcador ``*`` de
    fin de su ``meas_loop``.

    IMPORTANTE: esta función vive duplicada byte a byte en DiscPCB/EmstatDrivers.py
    (Pico). Cualquier cambio aquí debe replicarse allá y flashearse.
    """
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
    script += f"set_e {E_dc}\ncell_on\n"
    if t_equilibration != "":
        script += (
            f"meas_loop_ca e i {E_dc} 200m {t_equilibration}\n"
            "  pck_start\n"
            "    pck_add e\n"
            "    pck_add i\n"
            "  pck_end\n"
            "endloop\n"
        )
    script += (
        f"meas_loop_ca e i {E_dc} {t_interval} {t_run_main}\n"
        "  pck_start\n"
        "    pck_add e\n"
        "    pck_add i\n"
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
        # CA (cronoamperometria): mismos paquetes que CV (da=potencial, ba=corriente).
        # El eje de tiempo NO viaja en el dato; se sintetiza en el host (ver
        # ca_t_interval/_handle_packet): t_s = indice_del_loop_principal * t_interval.
        "ca": {"da": ("E_V", 1e-6), "ba": ("I_A", 1e-12)},
        "sqwv": {
            "da": ("E_V", 1e-6),
            "ba": ("I_A", 1e-12),
            "ba_1": ("I_A_F", 1e-12),
            "ba_2": ("I_A_R", 1e-12),
        },
        # Códigos de paquete REALES del EmStat en EIS (verificados en salida cruda):
        #   dc = frecuencia, cc = Z_real, cd = Z_imag.
        # Fase 2: da = potencial DC del barrido E_dc Scan (pck_add extra1, tipo da);
        # eb = tiempo transcurrido del Time Scan (pck_add extra1, tipo eb). Ambos
        # pendientes de verificación contra salida cruda en hardware.
        # (La columna 'scale' es vestigial: _decode solo aplica el prefijo de unidad.
        #  La negación de Z_imag para el Nyquist se hace explícita en _decode.)
        "eis": {
            "dc": ("freq_Hz", 1),
            "cc": ("Z_real", 1),
            "cd": ("Z_imag", 1),
            "da": ("E_V", 1),
            "eb": ("t_s", 1),
        },
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
    # Tabla 5 del manual MethodSCRIPT: ID de técnica de medición (marcador M<hex>).
    # 0x06 y 0x0C no están definidos en la tabla.
    TECHNIQUE_IDS = {
        0x00: "LSV",       # Linear Sweep Voltammetry
        0x01: "DPV",       # Differential Pulse Voltammetry
        0x02: "SWV",       # Square Wave Voltammetry
        0x03: "NPV",       # Normal Pulse Voltammetry
        0x04: "ACV",       # AC Voltammetry
        0x05: "CV",        # Cyclic Voltammetry
        0x07: "CA",        # Chronoamperometry
        0x08: "PAD",       # Pulsed Amperometric Detection
        0x09: "FCA",       # Fast Chronoamperometry
        0x0A: "CP",        # Chronopotentiometry
        0x0B: "OCP",       # Open Circuit Potentiometry
        0x0D: "EIS",       # Electrochemical Impedance Spectroscopy
        0x0E: "GEIS",      # Galvanostatic EIS
        0x0F: "LSP",       # Linear Sweep Potentiometry
        0x10: "FCV",       # Fast Cyclic Voltammetry
        0x11: "CA_MUX",    # Chronoamperometry con mux alternante
        0x12: "CP_MUX",    # Chronopotentiometry con mux alternante
        0x13: "OCP_MUX",   # Open Circuit Potentiometry con mux alternante
        0x14: "DUAL_EIS",  # Dual EIS
    }

    def __init__(
        self,
        experiment: str,
        eis_group_by_potential: bool = False,
        ca_t_interval: float | None = None,
        ca_has_equil: bool = False,
    ):
        if experiment not in self.FIELD_MAP:
            raise ValueError(f"Unsupported experiment: {experiment}")

        self.experiment = experiment
        # EIS E_dc Scan + freq Scan: agrupa los paquetes en "espectros" (cycle) por
        # cambio del potencial E_V que viaja en cada paquete -> una curva Nyquist por
        # potencial. Apagado en los demás modos (en Mott-Schottky cada punto trae un
        # potencial distinto y partiría la traza única en N líneas de 1 punto).
        self.eis_group_by_potential = eis_group_by_potential

        # CA: el eje de tiempo se sintetiza aquí (no hay campo de tiempo en el dato).
        # t_s = indice_del_loop_principal * ca_t_interval. El loop de equilibrio
        # (opcional, intervalo 200m) se EXCLUYE del plot: se detecta su fin por el
        # marcador '*' del meas_loop (más robusto que contar paquetes, inmune a la
        # pérdida de un dato). ca_has_equil=False => no hay equilibrio, el principal
        # arranca desde el primer paquete.
        self.ca_t_interval = ca_t_interval
        self._ca_main_started = not ca_has_equil
        self._ca_index = 0

        # Contexto dinámico
        self.context = {"cycle": 0, "direction": +1, "method_id": None}
        # Rastreo de espectros EIS (solo con eis_group_by_potential)
        self._eis_last_e: float | None = None
        self._eis_spectrum = 0

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
            # El marcador M<hex> trae el ID de técnica de medición (Tabla 5 del manual
            # MethodSCRIPT), p.ej. M000D = EIS. Es HEX, no decimal.
            mid = self._safe_hex(raw[1:])
            self.context["method_id"] = mid
            return {
                "type": "method",
                "method_id": mid,
                "method_name": self.TECHNIQUE_IDS.get(mid, "unknown"),
            }

        if kind == "start_method":
            return {"type": "start_method"}

        if kind == "end_block":
            self.finished = True
            # CA con equilibrio: el primer '*' marca el fin del meas_loop de
            # equilibrio; a partir de aquí los paquetes son del loop principal y
            # cuentan para t_s (ver _handle_packet).
            if self.experiment == "ca" and not self._ca_main_started:
                self._ca_main_started = True
            return {"type": "method_end"}
        
        if kind == "syntax_error":
            # e!<hex>: Line L, Col C -> agrega code/description/line/col (Appendix A).
            info = decode_methodscript_error(raw)
            info["type"] = "error"
            return info

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

        decoded.update(
            {
                "type": "data",
                "cycle": self.context["cycle"],
                "direction": self.context["direction"],
                "status": parsed["status"],            # metadata id=1 (estado del punto)
                "current_range": parsed["current_range"],  # metadata id=2 (diagnóstico)
            }
        )

        # EIS: los paquetes de acondicionamiento (da/ba) no traen campos Z; no son
        # puntos del Nyquist. Marcarlos como no-dato evita graficar (0,0) espurios.
        # (Los paquetes del barrido E_dc Scan traen da + dc/cc/cd: pasan el filtro.)
        if self.experiment == "eis" and "Z_real" not in decoded and "Z_imag" not in decoded:
            decoded["type"] = "unknown"

        # CA: síntesis del eje de tiempo. Los paquetes del loop de equilibrio (antes
        # del primer '*') se marcan como no-dato (acondicionamiento, fuera del plot).
        # Los del loop principal reciben t_s = índice * t_interval (t=0 en el escalón).
        if self.experiment == "ca":
            if not self._ca_main_started:
                decoded["type"] = "unknown"
            else:
                ti = self.ca_t_interval or 0.0
                decoded["t_s"] = self._ca_index * ti
                self._ca_index += 1

        # SWV: etiqueta de fase. El pre-tratamiento (condition/deposition/equilibration)
        # son meas_loop_ca que emiten solo e/i; el barrido SWV emite ADEMAS
        # i_forward/i_reverse (ba_1/ba_2 -> I_A_F/I_A_R). Marcamos "sweep" cuando hay
        # corriente forward/reverse, "pretreatment" en caso contrario. Se mantiene
        # type="data" (a diferencia de EIS/CA, que descartan): el host conserva el
        # pre-tratamiento en el CSV pero NO lo grafica (ver EventPlotter).
        if self.experiment == "sqwv":
            is_sweep = "I_A_F" in decoded or "I_A_R" in decoded
            decoded["phase"] = "sweep" if is_sweep else "pretreatment"

        # EIS E_dc Scan + freq Scan: el "cycle" pasa a ser el índice de espectro,
        # detectado por cambio del potencial embebido en el paquete (robusto ante
        # marcadores M/C perdidos en TCP; el potencial sí se recupera vía UDP).
        if (
            self.experiment == "eis"
            and self.eis_group_by_potential
            and decoded["type"] == "data"
            and "E_V" in decoded
        ):
            if self._eis_last_e is not None and decoded["E_V"] != self._eis_last_e:
                self._eis_spectrum += 1
            self._eis_last_e = decoded["E_V"]
            decoded["cycle"] = self._eis_spectrum

        return decoded

    def _parse_packet(self, line: str):
        """Parsea un paquete de medición 'P...'. Cada sub-paquete (separado por ';') es
        '<tipo><valor><unidad>[,<meta>...]', p.ej. 'ba8000800u,10,20B':
          - tipo: 2 chars (da/ba/...); valor: hex con offset 0x8000000; unidad: 1 char.
          - metadata (opcional): cada token es <id><valor_hex>. id=1 -> status del punto;
            id=2 -> current range (diagnóstico, NO interviene en el cálculo del valor).
        Ver manual MethodSCRIPT, "measurement data package". (Antes este método trataba
        la metadata como un 'index'/'state' inexistente; corregido.)
        """
        try:
            bodies = line[1:].split(";")
            fields = {}
            statuses = []
            ranges = []
            for body in bodies:
                parts = body.split(",")
                head = parts[0]
                key_base = head[:2]
                # El valor es SIEMPRE 7 hex (28 bits con offset 0x8000000) + 1 char
                # de unidad. Si la unidad es el espacio (adimensional: eb segundos,
                # da en volts exactos) y el campo cierra la línea sin metadata, el
                # strip() del transporte la pierde -> unidad implícita ' '. Antes se
                # usaba head[-1] como unidad y eso corrompía el valor en ese caso.
                if len(head) >= 10:
                    raw_val = head[2:9]
                    unit = head[9]
                else:
                    raw_val = head[2:]
                    unit = " "
                value = int(raw_val, 16) - 0x8000000
                # Metadata: primer char = id (hex), resto = valor (hex).
                for meta in parts[1:]:
                    if not meta:
                        continue
                    mid, mval = meta[0], meta[1:]
                    if mid == "1":
                        statuses.append(self._safe_hex(mval))
                    elif mid == "2":
                        ranges.append(self._safe_hex(mval))
                key = key_base
                counter = 1
                while key in fields:
                    key = f"{key_base}_{counter}"
                    counter += 1
                fields[key] = {"value": value, "unit": unit, "value_hex": raw_val}

            return {"fields": fields, "status": statuses, "current_range": ranges}

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
            # |Z| derivado para los modos de frecuencia fija (y vs E o vs t). La
            # negación no afecta la magnitud.
            if "Z_real" in out:
                out["Z_mod"] = math.sqrt(out["Z_real"] ** 2 + out["Z_imag"] ** 2)
        return out


# ----------------------------------------------------------------------
# Códigos de error de MethodSCRIPT (Appendix A del manual)
# ----------------------------------------------------------------------
_ERROR_CODES = None


def _load_error_codes():
    """Carga (y cachea) resources/errors_emstat.json -> {code_int: descripción}.
    Ruta relativa a este archivo para no depender del cwd. {} si falla."""
    global _ERROR_CODES
    if _ERROR_CODES is not None:
        return _ERROR_CODES
    path = os.path.join(os.path.dirname(__file__), "..", "resources", "errors_emstat.json")
    table = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for item in data.get("error_codes", []):
            try:
                table[int(item["code"], 16)] = item["description"]
            except (KeyError, ValueError, TypeError):
                continue
    except Exception:
        pass
    _ERROR_CODES = table
    return table


def decode_methodscript_error(raw):
    """Decodifica un error de MethodSCRIPT 'e!<hex>: Line L, Col C' a un dict legible:
    code ('0x4001'), code_int, description (Appendix A), line, col. Tolera la ausencia
    de la ubicación o del prefijo 'e!'. Campos no hallados quedan en None."""
    text = str(raw).strip()
    out = {
        "raw": text,
        "code": None,
        "code_int": None,
        "description": None,
        "line": None,
        "col": None,
    }
    m = re.search(r"e!\s*([0-9A-Fa-f]+)", text)
    if m:
        ci = int(m.group(1), 16)
        out["code_int"] = ci
        out["code"] = "0x%04X" % ci
        out["description"] = _load_error_codes().get(ci)
    loc = re.search(r"[Ll]ine\s+(\d+),\s*[Cc]ol\s+(\d+)", text)
    if loc:
        out["line"] = int(loc.group(1))
        out["col"] = int(loc.group(2))
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
