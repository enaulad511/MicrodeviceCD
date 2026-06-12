# Adaptación: Pico W -> Pico 2 + Wemos D1 mini por UART con encabezados
# Autor: Edisson Naula (ajustado)
# Fecha: 11/06/2026
# v1.8: base v1.7 + EIS Fase 2 (ver docs/eis_impedancia.md seccion 7 del repo host).
#   - rama "eis": reenvia las claves nuevas del payload (scan_type, bandwidth,
#     E_begin/E_step/E_break/E_dir, t_run/t_interval) a construct_eis_script, que
#     ahora genera los 5 modos (Default/E_dc Scan/Time Scan x Scan/Fixed).
#   - run_experiment_read_loop acepta max_ms/idle_ms por corrida: la rama eis usa
#     max(max_time_s*1000, MAX_EXPERIMENT_MS) (estimacion x1.5 del host) y
#     max(idle_s*1000, (t_interval+5)*1000, MAX_IDLE_MS) -- idle_s lo calcula el
#     host del punto mas lento del barrido (el EmStat emite un paquete por punto al
#     terminarlo; a baja frecuencia un punto tarda minutos y el idle fijo de 16s
#     abortaba la corrida). Defaults intactos para cv/sqwv. El dead-man del Wemos
#     sigue siendo la red de seguridad.
#   - fin normal reconoce tambien '+' (fin del loop GENERICO de E_dc Scan) ademas
#     de '*': verificado en hardware que el script anidado termina '* + blank' y
#     sin esto la corrida moria por idle timeout en vez de emstat_end.
# v1.7: base v1.6 + soporte de EIS (Electrochemical Impedance Spectroscopy).
#   - rama "eis" en handle_command (scan type Default + frequency Scan)
#   - reusa el loop de lectura unificado run_experiment_read_loop("eis")
#   - canal de electrodo obligatorio + apagado garantizado (igual que cv/sqwv)
#   - "seq" por mensaje EMSTAT en send_emstat_line (reinicia en emstat_start):
#     clave de dedup/cobertura idéntica en TCP y UDP para que el host recupere
#     paquetes perdidos en TCP usando el broadcast UDP paralelo.
#   - fin normal = '*' + línea en blanco (no cualquier blank): con preprocesamiento
#     (varios meas_loop antes del método principal) ya no termina antes de tiempo.
#   - SWV: pacing del UART al EmStat (EmstatDrivers.write_lines, 5ms/línea) -- la ráfaga
#     del script desbordaba el RX del EmStat y lo corrompía (e!#### en líneas aleatorias).
#     + flag DEBUG_ECHO_SCRIPT (default False) que ecoa el script enviado para diagnóstico.
# v1.6: lectura del EmStat robusta ante desconexión/no-respuesta.
#   - idle timeout (resetea con cada dato)  + tope absoluto del experimento
#   - cancelación en caliente vía {"cmd":"ABORT"} (poll del host entre líneas)
#   - aborto del EmStat con 'Z\n' -> salta a on_finished: -> cell_off
#   - drenado limpio tras Z; flush + re-test de conexión si quedó muerto
#   - loop de lectura unificado para cv/sqwv (y métodos futuros) con hook on_data

from machine import UART, Pin, I2C, SPI, Timer
import time
import ujson as json

# --- Sensores externos ---
import mlx90614
from mcp23017 import MCP23017
from EmstatDrivers import EmstatPico, ERROR_TOKEN, construc_individual_script_sqwv

# =========================
# --- Arranque seguro para re-flasheo ---
# =========================
# Como este archivo corre como main.py, la init del UART del EmStat (test_connection bloquea
# hasta ~4 s leyendo el puerto) y el main_loop infinito dejan la placa ocupada al instante,
# y subir firmware nuevo se vuelve difícil. Hay DOS mecanismos para liberar el REPL, ambos
# ANTES de inicializar puertos serie / entrar al bucle:
#
#   1) Pin de safe-boot: si el GPIO elegido está a GND al arrancar, salta la app al instante.
#   2) Ventana de arranque: cuenta regresiva en la que Ctrl-C / botón Stop detiene el programa.

# --- 1) Pin de safe-boot (editable) ---
# Botón entre el GPIO y GND. Si está presionado al encender, NO arranca la app (REPL libre).
# Pon SAFE_BOOT_PIN = None para desactivarlo. Elige un GPIO LIBRE: en uso están
# GP0,1 (EmStat), GP8,9 (Wemos), GP12,13,14 (SPI), GP20,21 (I2C). Libres: GP2-7,10,11,15-19,22,26-28.
SAFE_BOOT_PIN = 22
if SAFE_BOOT_PIN is not None:
    try:
        if Pin(SAFE_BOOT_PIN, Pin.IN, Pin.PULL_UP).value() == 0:
            print("Safe-boot (GP", SAFE_BOOT_PIN, ") activo -> REPL libre, app NO iniciada")
            raise SystemExit
    except SystemExit:
        raise
    except Exception as e:
        print("Safe-boot: GPIO invalido (", e, ") -> ignorado")

# --- 2) Ventana de arranque (Ctrl-C) ---
# Pon BOOT_DELAY_S = 0 para desactivarla en producción.
BOOT_DELAY_S = 5
try:
    print("Arranque en", BOOT_DELAY_S, "s... Ctrl-C AHORA para detener y actualizar firmware")
    for _i in range(BOOT_DELAY_S, 0, -1):
        print("  ", _i, "...")
        time.sleep(1)
    print("Iniciando aplicacion")
except KeyboardInterrupt:
    print("Detenido por el usuario -> REPL libre para actualizar firmware")
    raise SystemExit

# =========================
# --- LED on-board ---
# =========================
pin_led = Pin("LED", Pin.OUT)
_led_timer = Timer()
_current_period_ms = 400  # ms entre toggles


def _led_cb(timer):
    pin_led.toggle()


def set_led_frequency(period_s: float):
    """Configura frecuencia del LED (periodo entre toggles)."""
    global _current_period_ms
    new_ms = max(10, int(period_s * 1000))
    if new_ms != _current_period_ms:
        _current_period_ms = new_ms
        try:
            _led_timer.deinit()
        except Exception:
            pass
        _led_timer.init(
            mode=Timer.PERIODIC, period=_current_period_ms, callback=_led_cb
        )


# Perfiles
LED_IDLE_S = 0.5
LED_FAST_S = 0.20
LED_VFAST_S = 0.10
set_led_frequency(LED_IDLE_S)
print("LED configurado")

# =========================
# --- UARTs ---
# =========================
# UART0: Enlace con Wemos (comandos/telemetría con encabezados)
UART_LINK_ID = 1
UART_LINK_BAUD = 230400  # debe coincidir con Serial del Wemos
# Nota: si GP8/GP9 no funcionan en tu build, cambia a tx=Pin(0), rx=Pin(1)
# rxbuf=2048: el comando SWV entrante es una linea JSON larga (~350 B). El RX por
# defecto del puerto RP2 (256 B) se desborda cuando el Wemos la vuelca en rafaga
# mientras el Pico esta en la lectura I2C de temperatura -> JSON corrupto ->
# json.loads falla -> el experimento nunca arranca (CV cabia en 256 B, SWV no).
uart_link = UART(
    UART_LINK_ID, baudrate=UART_LINK_BAUD, tx=Pin(8), rx=Pin(9), timeout=0, rxbuf=2048
)

# UART1: EmStat Pico
UART_EMSTAT_ID = 0
UART_EMSTAT_BAUD = 230400
uart_emstat = UART(
    UART_EMSTAT_ID, baudrate=UART_EMSTAT_BAUD, tx=Pin(0), rx=Pin(1), timeout=2000
)

# =========================
# --- Límites de la lectura del EmStat ---
# =========================
# El EmStat puede tardar hasta ~10s en responder en cualquier punto.
# Con uart_emstat.timeout=2000ms, cada readline vacío equivale a 2s sin datos.
MAX_IDLE_MS = 16000        # idle: aborta si pasan >16s SIN ninguna línea nueva (margen sobre 10s)
MAX_EXPERIMENT_MS = 600000 # tope absoluto: 10 min (los experimentos reales llegan a ~5 min)
DRAIN_MS = 6000            # ventana para drenar la cola final tras enviar 'Z'

# DEBUG temporal: si True, antes de medir el Pico ecoa al host el script EXACTO que
# envió al EmStat (type=script_dbg, con line/text) para mapear los e!#### Line/Col.
# Poner en True para diagnosticar el script enviado; ya confirmamos que se genera bien.
DEBUG_ECHO_SCRIPT = False

# =========================
# --- I2C: MLX90614 ---
# =========================
i2c = I2C(0, sda=Pin(20), scl=Pin(21), freq=100000)
devices = i2c.scan()
if devices:
    print("I2C OK. Dispositivos:", [hex(d) for d in devices])
else:
    print("I2C: No se encontraron dispositivos")
try:
    sensor_temp = mlx90614.MLX90614(i2c)
except Exception:
    sensor_temp = None

# =========================
# --- MCP23017: canales de electrodos del EmStat ---
# =========================
# Comparte el bus I2C0 con el MLX90614 (direcciones distintas: MCP=0x20, MLX≈0x5A).
# Multiplex: un solo canal de electrodo activo a la vez en el puerto A (0-7).
MCP_ADDR = 0x20      # A0-A2 a GND
CH_PORT = "A"        # 8 canales en el puerto A
CH_MIN, CH_MAX = 0, 7
CH_SETTLE_MS = 100   # asentamiento del relé/mux tras conmutar, antes de medir
try:
    mcp = MCP23017(i2c, address=MCP_ADDR, multiplex_mode=True)
    print("MCP23017 OK @", hex(MCP_ADDR))
except Exception as e:
    print("MCP23017 no disponible:", e)
    mcp = None

# =========================
# --- SPI: MAX31855 ---
# =========================
spi = SPI(1, baudrate=1000000, polarity=0, phase=0, sck=Pin(14), miso=Pin(12))
cs = Pin(13, Pin.OUT, value=1)


def read_temp_max31855():
    """Lee termopar desde MAX31855 (manejo correcto de signo y fallos).
    Devuelve float (°C) o None si falla."""
    try:
        cs.value(0)
        data = spi.read(4)
    finally:
        cs.value(1)

    if not data or len(data) != 4:
        return None

    val = int.from_bytes(data, "big")

    # Bits de fallo: D16 (fault) y D2..D0 (detalles)
    if (val & 0x00010000) or (val & 0x7):
        return None

    # Temperatura TC: bits 31..18 (14-bit signed, 0.25°C/LSB)
    tc_raw = (val >> 18) & 0x3FFF
    if tc_raw & 0x2000:  # signo
        tc_raw -= 0x4000
    temp_c = tc_raw * 0.25
    return temp_c


# =========================
# --- EmStat Pico ---
# =========================
IS_EMSTAT_CONNECTED = False
emstatpico = EmstatPico(uart_emstat)
try:
    flag_emstat, version = emstatpico.test_connection()
    if flag_emstat:
        print("EmStat conectado. Versión:", version)
        IS_EMSTAT_CONNECTED = True
        set_led_frequency(LED_IDLE_S)
    else:
        print("Error de conexión con EmStat:", version)
        IS_EMSTAT_CONNECTED = False
        set_led_frequency(LED_FAST_S)
except Exception as e:
    print("Excepción probando EmStat:", e)
    IS_EMSTAT_CONNECTED = False
    set_led_frequency(LED_FAST_S)

time.sleep(0.5)

# =========================
# --- Estado y protocolo UART con Wemos ---
# =========================
# Encabezados
HDR_UDP = "UDP:"
HDR_EMSTAT = "EMSTAT:"

measuring = True  # medición de temperaturas (telemetría UDP)
sample_ms = 80
last_sample = 0

rx_buffer = bytearray()  # para UART_LINK (desde Wemos)
_abort_requested = False  # lo prende poll_stop() al recibir {"cmd":"ABORT"}
_emstat_seq = 0  # secuencia por mensaje EMSTAT; reinicia en cada emstat_start


def now_ms():
    return time.ticks_ms()


# ---- Helpers para enviar con encabezados ----
def send_udp_line(obj: dict):
    """Telemetría general hacia Wemos (broadcast UDP)."""
    try:
        uart_link.write(HDR_UDP + str(obj) + "\n")
        # print("Enviado:", obj)
    except Exception as e:
        print("Error enviando UDP:", e)


def send_emstat_line(obj: dict):
    """Resultados/estados del EmStat hacia Wemos (UDP y TCP).

    Inyecta "seq": contador monotónico por mensaje EMSTAT, único punto de
    bifurcación TCP/UDP -> ambos transportes cargan el MISMO seq, que el host usa
    para deduplicar/rellenar y medir cobertura. Reinicia a 0 en cada 'emstat_start'
    (emstat_start=0, primer dato=1, ...). El campo "raw" no se toca."""
    global _emstat_seq
    if obj.get("type") == "emstat_start":
        _emstat_seq = 0
    obj["seq"] = _emstat_seq
    _emstat_seq += 1
    try:
        uart_link.write(HDR_EMSTAT + json.dumps(obj) + "\n")
    except Exception:
        pass


# ---- Payload de temperaturas (igual que antes) ----
def read_temperatures_payload():
    try:
        t_obj = round(sensor_temp.read_object_temp(), 2) if sensor_temp else "NS"
    except Exception:
        t_obj = None
    try:
        t_amb = round(sensor_temp.read_ambient_temp(), 2) if sensor_temp else "NS"
    except Exception:
        t_amb = None

    t_tc = None
    try:
        t_tc = read_temp_max31855()
        t_tc = round(t_tc, 2)
    except Exception:
        t_tc = None
    line = f"{t_amb}:{t_obj}:{t_tc}"
    return line


# =========================
# --- Cancelación y recuperación del EmStat ---
# =========================
def poll_stop():
    """Lee uart_link en caliente (sin bloquear) durante un experimento y prende
    _abort_requested si llega EMSTAT:{"cmd":"ABORT"}. Reusa rx_buffer / formato JSON.
    NO re-despacha experimentos: cualquier otra línea se ignora mientras está ocupado."""
    global rx_buffer, _abort_requested
    try:
        data = uart_link.read()
    except Exception:
        data = None
    if not data:
        return
    rx_buffer.extend(data)
    while True:
        nl = rx_buffer.find(b"\n")
        if nl == -1:
            if len(rx_buffer) > 4096:
                rx_buffer = bytearray()
            return
        raw = rx_buffer[:nl].rstrip(b"\r")
        rx_buffer = rx_buffer[nl + 1 :]
        if not raw or not raw.startswith(b"EMSTAT:"):
            continue
        body = raw[len(b"EMSTAT:") :]
        try:
            obj = json.loads(body)
        except Exception:
            continue
        if isinstance(obj, dict) and obj.get("cmd") == "ABORT":
            _abort_requested = True
            # no salimos: seguimos vaciando líneas para no acumular basura


def _flush_uart_emstat():
    """Vacía cualquier byte residual del EmStat para no envenenar la próxima lectura."""
    try:
        n = uart_emstat.any()
        while n:
            uart_emstat.read(n)
            n = uart_emstat.any()
    except Exception:
        pass


def _send_abort_to_emstat():
    """'Z\\n' -> el EmStat termina la iteración actual y salta a on_finished: (cell_off)."""
    try:
        uart_emstat.write("Z\n")
    except Exception:
        pass


def _drain_after_z(method, on_data=None):
    """Tras enviar 'Z', reenvía los paquetes finales hasta la línea en blanco que
    genera on_finished (cierre limpio confirmado) o hasta agotar DRAIN_MS.
    Devuelve True si se confirmó el cierre limpio, False si hubo que hacer flush."""
    t0 = now_ms()
    while time.ticks_diff(now_ms(), t0) < DRAIN_MS:
        line = emstatpico.readline()
        if line.lower().startswith(ERROR_TOKEN):
            continue  # timeout/error: seguimos hasta agotar DRAIN_MS
        if line.strip() == "":
            return True  # on_finished completó -> celda apagada
        payload = on_data(line) if on_data else {"type": "emstat_data", "raw": line.strip()}
        if payload:
            send_emstat_line(payload)
    _flush_uart_emstat()
    return False


def _retest_connection():
    """Re-testea el EmStat tras una desconexión y actualiza IS_EMSTAT_CONNECTED + LED."""
    global IS_EMSTAT_CONNECTED
    try:
        ok, _ver = emstatpico.test_connection()
        IS_EMSTAT_CONNECTED = bool(ok)
    except Exception:
        IS_EMSTAT_CONNECTED = False
    set_led_frequency(LED_IDLE_S if IS_EMSTAT_CONNECTED else LED_FAST_S)
    return IS_EMSTAT_CONNECTED


def run_experiment_read_loop(method, on_data=None, max_ms=None, idle_ms=None):
    """Lee la respuesta del EmStat línea a línea y la reenvía al host. Unificado para
    cv/sqwv y métodos futuros (on_data permite reformatear cada línea por método).

    max_ms / idle_ms (v1.8): topes POR CORRIDA; None -> los defaults globales
    (MAX_EXPERIMENT_MS / MAX_IDLE_MS). La rama eis los calcula del payload
    (max_time_s estimado por el host; t_interval del Time Scan).

    Termina por uno de cuatro caminos y avisa al host con un tipo distinto:
      - fin normal ('*' + línea en blanco)  -> emstat_end
      - {"cmd":"ABORT"} del host             -> Z, drena limpio  -> emstat_aborted
      - tope absoluto (max_ms)               -> Z, drena limpio  -> emstat_maxtime
      - idle timeout (EmStat sin responder)  -> Z, drena corto, flush, re-test -> emstat_timeout

    Fin normal: el fin REAL del script es un '*' (fin de meas_loop) seguido de una línea
    en blanco. Con preprocesamiento (varios meas_loop antes del método principal, p.ej.
    acondicionamiento antes de EIS) cada sub-loop emite su '*' seguido del siguiente
    bloque de datos -> NO termina. Solo termina la blank que viene JUSTO tras un '*'.
    """
    global _abort_requested
    _abort_requested = False
    if max_ms is None:
        max_ms = MAX_EXPERIMENT_MS
    if idle_ms is None:
        idle_ms = MAX_IDLE_MS
    start = now_ms()
    last_data = start
    last_was_star = False  # ¿la última línea de datos fue '*'? (fin de meas_loop)

    while True:
        # 1) ¿el host pidió abortar?
        poll_stop()
        if _abort_requested:
            _send_abort_to_emstat()
            clean = _drain_after_z(method, on_data)
            send_emstat_line({"type": "emstat_aborted", "method": method, "clean": clean})
            return

        # 2) ¿se pasó del tope absoluto?
        if time.ticks_diff(now_ms(), start) > max_ms:
            _send_abort_to_emstat()
            clean = _drain_after_z(method, on_data)
            send_emstat_line({"type": "emstat_maxtime", "method": method, "clean": clean})
            return

        # 3) leer una línea del EmStat (timeout de 2s por readline)
        line = emstatpico.readline()

        if line.lower().startswith(ERROR_TOKEN):
            # timeout o error de lectura: NO resetea idle
            if time.ticks_diff(now_ms(), last_data) > idle_ms:
                # desconexión: intento de aborto (probablemente inútil), limpieza y re-test
                _send_abort_to_emstat()
                _drain_after_z(method, on_data)
                _flush_uart_emstat()
                connected = _retest_connection()
                send_emstat_line(
                    {"type": "emstat_timeout", "method": method, "connected": connected}
                )
                return
            continue

        stripped = line.strip()
        if stripped == "":
            # Blank: solo es fin REAL si viene justo tras un marcador de fin de loop.
            # Una blank sin marcador previo es un separador entre meas_loops
            # (preprocesamiento) -> se ignora.
            if last_was_star:
                send_emstat_line({"type": "emstat_end", "method": method})
                return
            continue

        # dato válido -> reenviar y reiniciar el contador idle
        # Marcadores de fin de loop: '*' = meas_loop; '+' = loop generico (E_dc Scan:
        # el script termina con '*' del ultimo meas_loop_eis y '+' del loop externo,
        # verificado en hardware -- sin el '+' aqui, el fin nunca se reconocia y la
        # corrida moria por idle con un Z!0006 del EmStat al abortar nada).
        last_data = now_ms()
        last_was_star = stripped in ("*", "+")
        payload = on_data(line) if on_data else {"type": "emstat_data", "raw": stripped}
        if payload:
            send_emstat_line(payload)


# =========================
# --- Canales de electrodos (MCP23017) ---
# =========================
def _activate_channel(ch):
    """Valida y activa un canal de electrodo (0-7) en multiplex (apaga el resto).
    Devuelve (ok, err). Estricto: sin MCP o ch inválido -> no se corre el experimento."""
    if mcp is None:
        return False, "mcp_no_disponible"
    try:
        ch_i = int(ch)
    except Exception:
        return False, "ch_invalido"
    if ch_i < CH_MIN or ch_i > CH_MAX:
        return False, "ch_fuera_de_rango"
    try:
        mcp.write_pin(CH_PORT, ch_i, 1)  # multiplex_mode=True -> deja solo este activo
    except Exception as e:
        return False, "mcp_error:" + str(e)
    time.sleep_ms(CH_SETTLE_MS)
    return True, None


def _deactivate_channel():
    """Apaga todos los canales de electrodos (estado seguro al terminar)."""
    if mcp is None:
        return
    try:
        mcp.clear_all()
    except Exception as e:
        print("Error apagando canales MCP:", e)


# ---- Manejo de comandos (desde Wemos, canal EMSTAT) ----
def handle_command(cmd_obj: dict):
    """
    Procesa comandos recibidos por EMSTAT:
    - Comandos de control simples (PING, START, STOP, SET)
    - Payloads de experimento EmStat (method=cv | sqwv)
    """
    global measuring, sample_ms, IS_EMSTAT_CONNECTED

    if not isinstance(cmd_obj, dict):
        send_emstat_line({"error": "BAD_FORMAT"})
        return

    # ======================================================
    # 1. COMANDOS SIMPLES (opcional, siguen funcionando)
    # ======================================================
    c = cmd_obj.get("cmd")

    if c == "PING":
        send_udp_line({"type": "pong", "ts": now_ms()})
        return

    if c == "START":
        measuring = True
        send_udp_line({"type": "ack", "cmd": "START"})
        return

    if c == "STOP":
        # STOP detiene SOLO la telemetría de temperatura (no un experimento en curso;
        # para abortar un experimento se usa {"cmd":"ABORT"} detectado por poll_stop()).
        measuring = False
        send_udp_line({"type": "ack", "cmd": "STOP"})
        return

    if c == "ABORT":
        # Fuera de un experimento no hay nada que abortar.
        send_emstat_line({"type": "ack", "cmd": "ABORT", "note": "no_experiment_running"})
        return

    if c == "SET":
        if "sample_ms" in cmd_obj:
            try:
                sample_ms = max(10, int(cmd_obj["sample_ms"]))
                send_udp_line({"type": "ack", "cmd": "SET", "sample_ms": sample_ms})
            except Exception:
                send_udp_line({"type": "ack", "cmd": "SET", "error": "bad_sample_ms"})
        return

    # ======================================================
    # 2. EXPERIMENTO EMSTAT (payload directo desde Raspberry)
    # ======================================================
    if cmd_obj.get("method") == "cv":
        # ---- Mapear nombres Raspberry -> EmStat ----
        t_equil = cmd_obj.get("t_e", "")
        t_equil = t_equil if t_equil != "0" else ""
        params = {
            "t_equilibration": t_equil,
            "E_begin": cmd_obj.get("E_b", "0"),
            "E_vertex1": cmd_obj.get("E_1", "-1"),
            "E_vertex2": cmd_obj.get("E_2", "1"),
            "E_step": cmd_obj.get("E_s", "0.04"),
            "scan_rate": cmd_obj.get("sc_r", "1"),
            "nscans": cmd_obj.get("n_sc", "1"),
            "max_bandwith": cmd_obj.get("m_b", "23402m"),
            "min_da": cmd_obj.get("min_da", "-200m"),
            "max_da": cmd_obj.get("max_da", "600m"),
            "range_ba": cmd_obj.get("range_ba", "47n"),
            "auto_ba1": cmd_obj.get("ba_1", "47n"),
            "auto_ba2": cmd_obj.get("ba_2", "47n"),
        }
        # ---- Canal de electrodo (obligatorio) ----
        ch = cmd_obj.get("ch")
        ok, err = _activate_channel(ch)
        if not ok:
            send_emstat_line({"type": "emstat_error", "error": err, "ch": ch})
            return
        try:
            send_emstat_line(
                {"type": "emstat_start", "method": "cv", "ch": ch, "params": params}
            )
            # 1) Enviar script al EmStat
            msg = emstatpico.send_script(params, method="cv")
            if "error" in msg.lower():
                send_emstat_line({"type": "emstat_error", "error": msg})
                return
            # 2) Leer resultados con el loop unificado (idle + tope + ABORT + Z)
            run_experiment_read_loop("cv")
        except Exception as e:
            send_emstat_line({"type": "emstat_error", "error": str(e)})
        finally:
            _deactivate_channel()  # apaga el canal en TODAS las salidas
        return

    elif cmd_obj.get("method") == "sqwv":
        t_equil = cmd_obj.get("t_e", "")
        t_equil = t_equil if t_equil != "0" else ""
        t_con = cmd_obj.get("t_con", "")
        t_con = t_con if t_con != "0" else ""
        t_dep = cmd_obj.get("t_dep", "")
        t_dep = t_dep if t_dep != "0" else ""

        params = {
            "t_equilibration": t_equil,
            "E_begin": cmd_obj.get("E_b", "0"),
            "E_end": cmd_obj.get("E_e", "-1"),
            "E_step": cmd_obj.get("E_s", "1"),
            "Amplitude": cmd_obj.get("Amp", "0.04"),
            "frequency": cmd_obj.get("Freq", "1"),
            "max_bandwith": cmd_obj.get("m_b", "23402m"),
            "min_da": cmd_obj.get("min_da", "-200m"),
            "max_da": cmd_obj.get("max_da", "600m"),
            "range_ba": cmd_obj.get("range_ba", "47n"),
            "auto_ba1": cmd_obj.get("ba_1", "47n"),
            "auto_ba2": cmd_obj.get("ba_2", "47n"),
            "E_con": cmd_obj.get("E_con", ""),
            "t_con": t_con,
            "E_dep": cmd_obj.get("E_dep", ""),
            "t_dep": t_dep,
        }
        # ---- Canal de electrodo (obligatorio) ----
        ch = cmd_obj.get("ch")
        ok, err = _activate_channel(ch)
        if not ok:
            send_emstat_line({"type": "emstat_error", "error": err, "ch": ch})
            return
        try:
            send_emstat_line(
                {"type": "emstat_start", "method": "sqwv", "ch": ch, "params": params}
            )
            # DEBUG temporal: ecoa al host el script EXACTO que se enviará al EmStat,
            # numerado, para mapear los e!#### Line/Col al comando real (y detectar
            # corrupción en tránsito). Quitar poniendo DEBUG_ECHO_SCRIPT = False.
            if DEBUG_ECHO_SCRIPT:
                _dbg = construc_individual_script_sqwv(
                    params["t_equilibration"], params["E_begin"], params["E_end"],
                    params["E_step"], params["Amplitude"], params["frequency"],
                    params["max_bandwith"], params["min_da"], params["max_da"],
                    params["range_ba"], params["auto_ba1"], params["auto_ba2"],
                    params["E_con"], params["t_con"], params["E_dep"], params["t_dep"],
                )
                for _i, _ln in enumerate(_dbg.split("\n"), 1):
                    send_emstat_line({"type": "script_dbg", "line": _i, "text": _ln})
            # 1) Enviar script al EmStat
            msg = emstatpico.send_script(params, method="sqwv")
            if "error" in msg.lower():
                send_emstat_line({"type": "emstat_error", "error": msg})
                return
            # 2) Leer resultados con el loop unificado (idle + tope + ABORT + Z)
            run_experiment_read_loop("sqwv")
        except Exception as e:
            send_emstat_line({"type": "emstat_error", "error": str(e)})
        finally:
            _deactivate_channel()  # apaga el canal en TODAS las salidas
        return

    elif cmd_obj.get("method") == "eis":
        # EIS Fase 2: 5 modos (scan_type 1=Default, 2=E_dc Scan, 3=Time Scan;
        # la frecuencia fija llega ya degenerada del host: f_max=f_min, n_freq
        # calculado). Tiempos de acondicionamiento "0"/"" -> "" (etapa omitida).
        t_con1 = cmd_obj.get("t_con1", "")
        t_con1 = t_con1 if t_con1 not in ("0", 0) else ""
        t_con2 = cmd_obj.get("t_con2", "")
        t_con2 = t_con2 if t_con2 not in ("0", 0) else ""
        params = {
            "E_ac": cmd_obj.get("E_ac", "10m"),
            "f_max": cmd_obj.get("f_max", "100k"),
            "f_min": cmd_obj.get("f_min", "100"),
            "n_freq": cmd_obj.get("n_freq", 11),
            "E_dc": cmd_obj.get("E_dc", "0"),
            "E_con1": cmd_obj.get("E_con1", ""),
            "t_con1": t_con1,
            "E_con2": cmd_obj.get("E_con2", ""),
            "t_con2": t_con2,
            # ---- Fase 2 (calculados por el host, solo se reenvian) ----
            "scan_type": cmd_obj.get("scan_type", 1),
            "bandwidth": cmd_obj.get("bandwidth", ""),
            "E_begin": cmd_obj.get("E_begin", ""),
            "E_step": cmd_obj.get("E_step", ""),
            "E_break": cmd_obj.get("E_break", ""),
            "E_dir": cmd_obj.get("E_dir", 1),
            "t_run": cmd_obj.get("t_run", 0),
            "t_interval": cmd_obj.get("t_interval", 0),
        }
        # Topes por corrida: max_time_s ya viene estimado x1.5 desde el host. El
        # idle_s tambien lo calcula el host: el EmStat emite UN paquete por punto
        # AL TERMINARLO, asi que el hueco maximo legitimo es el punto mas lento del
        # barrido (~30/f_min + 3 s) o t_interval en Time Scan -- con el idle fijo
        # de 16 s, cualquier punto bajo ~1 Hz abortaba la corrida por timeout.
        try:
            max_ms = max(int(cmd_obj.get("max_time_s", 0)) * 1000, MAX_EXPERIMENT_MS)
        except Exception:
            max_ms = MAX_EXPERIMENT_MS
        try:
            idle_ms = max(
                int(cmd_obj.get("idle_s", 0)) * 1000,
                (int(cmd_obj.get("t_interval", 0)) + 5) * 1000,
                MAX_IDLE_MS,
            )
        except Exception:
            idle_ms = MAX_IDLE_MS
        # ---- Canal de electrodo (obligatorio) ----
        ch = cmd_obj.get("ch")
        ok, err = _activate_channel(ch)
        if not ok:
            send_emstat_line({"type": "emstat_error", "error": err, "ch": ch})
            return
        try:
            send_emstat_line(
                {"type": "emstat_start", "method": "eis", "ch": ch, "params": params}
            )
            # 1) Enviar script al EmStat
            msg = emstatpico.send_script(params, method="eis")
            if "error" in msg.lower():
                send_emstat_line({"type": "emstat_error", "error": msg})
                return
            # 2) Leer resultados con el loop unificado (idle + tope + ABORT + Z)
            run_experiment_read_loop("eis", max_ms=max_ms, idle_ms=idle_ms)
        except Exception as e:
            send_emstat_line({"type": "emstat_error", "error": str(e)})
        finally:
            _deactivate_channel()  # apaga el canal en TODAS las salidas
        return

    # ======================================================
    # 3. COMANDO DESCONOCIDO
    # ======================================================
    send_emstat_line({"error": "UNKNOWN_COMMAND", "payload": cmd_obj})


# ---- Parser de UART0: espera líneas EMSTAT:<json> ----
def process_uart_rx():
    """Lee UART_LINK y procesa SOLO líneas con prefijo 'EMSTAT:' (comandos desde Wemos)."""
    global rx_buffer
    try:
        data = uart_link.read()
    except Exception:
        data = None

    if not data:
        return

    rx_buffer.extend(data)

    while True:
        nl = rx_buffer.find(b"\n")
        if nl == -1:
            if len(rx_buffer) > 4096:
                rx_buffer = bytearray()
            return

        raw = rx_buffer[:nl].rstrip(b"\r")
        rx_buffer = rx_buffer[nl + 1 :]

        if not raw:
            continue

        # Verificar encabezado EMSTAT:
        if raw.startswith(b"EMSTAT:"):
            line = raw[len(b"EMSTAT:") :]
        else:
            # Ignora cualquier otra cosa (p.ej., ECOs o ruido)
            continue

        # Parsear JSON y manejar comando
        try:
            obj = json.loads(line)
        except Exception:
            send_emstat_line(
                {"error": "JSON_PARSE", "line": line.decode("utf-8", "ignore")[:120]}
            )
            continue

        handle_command(obj)


# ---- Telemetría periódica (UDP) ----
def maybe_send_temperature(ts_ms: int):
    global last_sample
    if not measuring:
        return
    if time.ticks_diff(ts_ms, last_sample) >= sample_ms:
        last_sample = ts_ms
        pkt = read_temperatures_payload()
        send_udp_line(pkt)


# ---- Main loop ----
def main_loop():
    # Mensaje inicial por UDP
    send_udp_line(
        {
            "hello": "PICO2_READY",
            "baud_link": UART_LINK_BAUD,
            "baud_emstat": UART_EMSTAT_BAUD,
            "sample_ms": sample_ms,
            "emstat_connected": IS_EMSTAT_CONNECTED,
        }
    )
    while True:
        ts = now_ms()
        process_uart_rx()  # recibe comandos EMSTAT desde Wemos
        maybe_send_temperature(ts)  # telemetría de temperaturas por UDP
        time.sleep_ms(2)


# Entrar al bucle principal
main_loop()
