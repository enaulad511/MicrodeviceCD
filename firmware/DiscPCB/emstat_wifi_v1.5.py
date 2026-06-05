# Adaptación: Pico W -> Pico 2 + Wemos D1 mini por UART con encabezados
# Autor: Edisson Naula (ajustado)
# Fecha: 10/03/2026

from machine import UART, Pin, I2C, SPI, Timer
import time
import ujson as json

# --- Sensores externos ---
import mlx90614
from EmstatDrivers import EmstatPico

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
uart_link = UART(UART_LINK_ID, baudrate=UART_LINK_BAUD, tx=Pin(8), rx=Pin(9), timeout=0)

# UART1: EmStat Pico
UART_EMSTAT_ID = 0
UART_EMSTAT_BAUD = 230400
uart_emstat = UART(
    UART_EMSTAT_ID, baudrate=UART_EMSTAT_BAUD, tx=Pin(0), rx=Pin(1), timeout=2000
)

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
    """Resultados/estados del EmStat hacia Wemos (UDP y TCP)."""
    try:
        uart_link.write(HDR_EMSTAT + json.dumps(obj) + "\n")
    except Exception as e:
        print("error sent")
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


# ---- Manejo de comandos (desde Wemos, canal EMSTAT) ----
def handle_command(cmd_obj: dict):
    """
    Procesa comandos recibidos por EMSTAT:
    - Comandos de control simples (PING, START, STOP, SET)
    - Payloads de experimento EmStat (method=cv)
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
        measuring = False
        send_udp_line({"type": "ack", "cmd": "STOP"})
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
        send_emstat_line({"type": "emstat_start", "method": "cv"})
        counter_timeout=0
        try:
            # 1) Enviar script al EmStat
            msg = emstatpico.send_script(params, method=cmd_obj.get("method"))
            #print(msg)
            if "error" in msg.lower():
                send_emstat_line({"type": "emstat_error", "error": msg})
                return
            # 2) Leer resultados línea a línea
            while True:
                line = emstatpico.readline()
                #print("line: ", line)
                if line is None:
                    continue
                if "e!" in line:
                    send_emstat_line({"type": "emstat_error", "error": line})
                    break
                if line.lower().startswith("error"):
                    send_emstat_line({"type": "emstat_error", "error": line})
                    if "timeout" in line.lower():
                        counter_timeout += 1
                    if counter_timeout>10:
                        printer("timeout")
                        break
                    continue
                if line.strip() == "":
                    break  # fin de medición
                # Reenviar cada línea tal cual
                send_emstat_line({"type": "emstat_data", "raw": line.strip()})
                counter_timeout = 0
            send_emstat_line({"type": "emstat_end"})
        except Exception as e:
            send_emstat_line({"type": "emstat_error", "error": str(e)})

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
            "frequebcy": cmd_obj.get("Freq", "1"),
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
        send_emstat_line({"type": "emstat_start", "method": "sqwv"})
        counter_timeout=0
        try:
            # 1) Enviar script al EmStat
            msg = emstatpico.send_script(params, method=cmd_obj.get("method"))
            if "error" in msg.lower():
                send_emstat_line({"type": "emstat_error", "error": msg})
                return
            # 2) Leer resultados línea a línea
            while True:
                line = emstatpico.readline()
                print(line)
                if line is None:
                    continue
                if "e!" in line:
                    send_emstat_line({"type": "emstat_error", "error": line})
                    break
                if line.lower().startswith("error"):
                    send_emstat_line({"type": "emstat_error", "error": line})
                    if "timeout" in line.lower():
                        counter_timeout += 1
                    if counter_timeout>10:
                        printer("timeout")
                        break
                    continue
                if line.strip() == "":
                    break  # fin de medición
                # Reenviar cada línea tal cual
                send_emstat_line({"type": "emstat_data", "raw": line.strip()})
            send_emstat_line({"type": "emstat_end"})
            #print("end")
        except Exception as e:
            send_emstat_line({"type": "emstat_error", "error": str(e)})
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

