# -*- coding: utf-8 -*-

import json
import time
import _thread

__author__ = "Edisson Naula"
__date__ = "$ 24/02/2026 at 10:10 $"

# --- Utilidades UART / EmStat ---
ERROR_TOKEN = "error-->"
LED_IDLE_MS = int(0.5)
LED_VERY_FAST_MS = int(0.05)


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

    IMPORTANTE: esta función vive duplicada byte a byte en Drivers/EmstatUtils.py
    (host). Cualquier cambio aquí debe replicarse allá.
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


_emstat_running = False
_emstat_lock = _thread.allocate_lock()


def _set_emstat_running(v: bool):
    global _emstat_running
    with _emstat_lock:
        _emstat_running = v


def _is_emstat_running():
    with _emstat_lock:
        return _emstat_running


class EmstatPico:
    def __init__(self, uart):
        self.uart = uart

    def get_emstat_version(self):
        try:
            # Enviar comando de versión según MethodSCRIPT (habitual: 't' devuelve versión/identificación)
            self.uart.write("t\n")
            # print("command sent")
            # Leer las dos líneas esperadas
            line1 = self.uart.readline()
            line2 = self.uart.readline()
            if not line1 or not line2:
                return f"{ERROR_TOKEN}No responde EmStat (timeout)"
            # ¡OJO! Usar posicionales en decode para evitar TypeError
            l1 = line1.decode("utf-8", "replace").strip()
            l2 = line2.decode("utf-8", "replace").strip()
            version = l1[1:].strip() + " " + l2.replace("*", "").strip()
            return version if version else "EmStat (versión no parseada)"
        except Exception as e:
            return f"{ERROR_TOKEN}UART: {str(e)}"

    def test_connection(self):
        version = self.get_emstat_version()
        if version.lower().startswith(ERROR_TOKEN):
            print("Error de conexión con EmStat:", version)
            _set_emstat_running(False)
            return False, version
        _set_emstat_running(True)
        return True, version

    def write_lines(self, lines):
        # Pacing: enviar las líneas en ráfaga (26 writes seguidos a 230400) desborda el
        # RX del EmStat y corrompe el script -> e!#### en líneas aleatorias e
        # inconsistentes. Una pausa corta entre líneas deja que el EmStat drene su buffer.
        for i, line in enumerate(lines):
            # MethodSCRIPT usa LF; si tu firmware requiere CRLF, cambia a "\r\n"
            self.uart.write(line + "\n")
            time.sleep_ms(5)
            # print(f"Sent {i}:", line)
        self.uart.write("\n")  # Envía un salto de línea adicional al final
        # print("Sent all lines")

    def readline(self):
        try:
            data = self.uart.readline()
            if not data:
                return f"{ERROR_TOKEN}comunication timeout"
            # Usar posicionales, sin kwargs
            line = data.decode("utf-8", "replace")
            # Aceptamos LF o CR como fin de línea
            if not (line.endswith("\n") or line.endswith("\r")):
                return f"{ERROR_TOKEN}comunication error: no EOL character received."
            return line
        except Exception as e:
            return f"{ERROR_TOKEN}Error at reading line: {e}"

    def read_lines_until_end(
        self, sock, logging=False, send_data=True, udp_ip=None, udp_port=None
    ):
        lines = []
        while True:
            line = self.readline()
            if line is None:
                # Lectura fallida inesperada, intentamos continuar
                continue

            # Gestionamos errores de lectura
            if line.lower().startswith(ERROR_TOKEN):
                if logging:
                    print(line)
                # Si hay un error de UART, seguimos intentando hasta cierre
                continue

            # Línea en blanco (solo '\n' o vacía) marca fin de bloque
            if line.strip() == "":
                break

            if logging:
                # 'line' ya contiene '\n'
                print(line, end="")

            # Envío UDP si está habilitado
            if (
                send_data
                and sock is not None
                and udp_port is not None
                and udp_ip is not None
            ):
                try:
                    sock.sendto(line.encode("utf-8"), (udp_ip, udp_port))
                except Exception as e:
                    print("Error socket:", e)
            lines.append(line)
        return lines

    def send_script(self, parameters, method="cv"):
        script = ""
        if method == "cv":
            script = construc_nscans_script_cv(
                parameters.get("t_equilibration", ""),
                parameters.get("E_begin", "0"),
                parameters.get("E_vertex1", "-1"),
                parameters.get("E_vertex2", "1"),
                parameters.get("E_step", "400m"),
                parameters.get("scan_rate", "1"),
                parameters.get("max_bandwith", "585054m"),
                parameters.get("min_da", "-1"),
                parameters.get("max_da", "1"),
                parameters.get("range_ba", "470u"),
                parameters.get("auto_ba1", "2937500p"),
                parameters.get("auto_ba2", "470u"),
                parameters.get("nscans", "1"),
            )
        elif method == "sqwv":
            script = construc_individual_script_sqwv(
                parameters.get("t_equilibration", 1),
                parameters.get("E_begin", 0),
                parameters.get("E_end", 1),
                parameters.get("E_step", 0.04),
                parameters.get("Amplitude", 0.04),
                parameters.get("frequency", 10),
                parameters.get("max_bandwith", "585054m"),
                parameters.get("min_da", -1),
                parameters.get("max_da", 1),
                parameters.get("range_ba", "470u"),
                parameters.get("auto_ba1", "2937500p"),
                parameters.get("auto_ba2", "470u"),
                parameters.get("E_con", "0"),
                parameters.get("t_con", "0"),
                parameters.get("E_dep", "0"),
                parameters.get("t_dep", "0"),
            )
        elif method == "eis":
            script = construct_eis_script(
                parameters.get("E_ac", "10m"),
                parameters.get("f_max", "100k"),
                parameters.get("f_min", "100"),
                parameters.get("n_freq", 11),
                parameters.get("E_dc", "0"),
                parameters.get("E_con1", ""),
                parameters.get("t_con1", ""),
                parameters.get("E_con2", ""),
                parameters.get("t_con2", ""),
                scan_type=parameters.get("scan_type", 1),
                bandwidth=parameters.get("bandwidth", ""),
                E_begin=parameters.get("E_begin", ""),
                E_step=parameters.get("E_step", ""),
                E_break=parameters.get("E_break", ""),
                E_dir=parameters.get("E_dir", 1),
                t_run=parameters.get("t_run", 0),
                t_interval=parameters.get("t_interval", 0),
            )
        elif method == "ca":
            script = construct_ca_script(
                parameters.get("t_equilibration", ""),
                parameters.get("E_dc", "0"),
                parameters.get("t_interval", "100m"),
                parameters.get("t_run_main", "10100m"),
                parameters.get("max_bandwith", "58505m"),
                parameters.get("min_da", "0"),
                parameters.get("max_da", "0"),
                parameters.get("range_ba", "470u"),
                parameters.get("auto_ba1", "470u"),
                parameters.get("auto_ba2", "470u"),
            )
        else:
            return "Error method not recognized"
        self.write_lines(script.split("\n"))
        return "Script sent"

    def emstat_job_stream_over_tcp(self, params: dict, conn, led_fun=None):
        """
        Corre la medición y va enviando línea a línea por 'conn' (TCP).
        Aquí NO formateamos nosotros; tu clase EmstatPico lo hace en read_lines_until_end(sock=conn, ...).
        """
        if _is_emstat_running():
            # Si llegara a dispararse en paralelo, cerramos la conexión con error
            try:
                conn.send(b'{"ok":false,"error":"emstat_busy"}\n')
            except Exception as e:
                print("Error enviando mensaje de ocupado:", str(e))
            try:
                conn.close()
            except Exception as e:
                print("Error cerrando conexión tras ocupado:", str(e))
            return

        _set_emstat_running(True)
        if led_fun is not None:
            led_fun(LED_VERY_FAST_MS)
        try:
            # 1) Enviar script
            self.send_script(parameters=params)

            # 2) Leer hasta el fin y ENVIAR LÍNEA A LÍNEA por la MISMA CONEXIÓN TCP
            #    Tu clase EmstatPico deberá usar 'conn.send(...)' internamente.
            self.read_lines_until_end(
                sock=conn, logging=True
            )  # <-- tú controlas el envío

            # 3) (Opcional) Al final puedes mandar un marcador de fin
            try:
                conn.send(b'{"type":"emstat_end"}\n')
            except Exception as e:
                print("Error enviando marcador de fin:", str(e))

        except Exception as e:
            # Notificar error por la misma conexión
            try:
                msg = json.dumps({"type": "emstat_error", "error": str(e)}) + "\n"
                conn.send(msg.encode())
            except Exception as e:
                print("Error enviando error:", str(e))
        finally:
            # Limpieza
            try:
                conn.close()
            except Exception as e:
                print("Error cerrando conexión:", str(e))
            # set_led_frequency(LED_IDLE)
            if led_fun is not None:
                led_fun(LED_IDLE_MS)
            _set_emstat_running(False)
