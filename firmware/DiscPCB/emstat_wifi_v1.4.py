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
_current_period_ms = 500  # ms entre toggles


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
UART_LINK_BAUD = 115200  # debe coincidir con Serial del Wemos
# Nota: si GP8/GP9 no funcionan en tu build, cambia a tx=Pin(0), rx=Pin(1)
uart_link = UART(UART_LINK_ID, baudrate=UART_LINK_BAUD, tx=Pin(8), rx=Pin(9), timeout=0)

# UART1: EmStat Pico
UART_EMSTAT_ID = 0
UART_EMSTAT_BAUD = 230400
uart_emstat = UART(
    UART_EMSTAT_ID, baudrate=UART_EMSTAT_BAUD, tx=Pin(0), rx=Pin(1), timeout=1000
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
sensor_temp = mlx90614.MLX90614(i2c)

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

measuring = False  # medición de temperaturas (telemetría UDP)
sample_ms = 100
last_sample = 0

rx_buffer = bytearray()  # para UART_LINK (desde Wemos)


def now_ms():
    return time.ticks_ms()


# ---- Helpers para enviar con encabezados ----
def send_udp_line(obj: dict):
    """Telemetría general hacia Wemos (broadcast UDP)."""
    try:
        uart_link.write(HDR_UDP + str(obj) + "\n")
        print("Enviado:", obj)
    except Exception as e:
        print("Error enviando UDP:", e)


def send_emstat_line(obj: dict):
    """Resultados/estados del EmStat hacia Wemos (UDP y TCP)."""
    try:
        uart_link.write(HDR_EMSTAT + json.dumps(obj) + "\n")
    except Exception:
        pass


# ---- Payload de temperaturas (igual que antes) ----
def read_temperatures_payload():
    try:
        t_obj = sensor_temp.read_object_temp()
    except Exception:
        t_obj = None
    try:
        t_amb = sensor_temp.read_ambient_temp()
    except Exception:
        t_amb = None

    t_tc = None
    try:
        t_tc = read_temp_max31855()
    except Exception:
        t_tc = None

    # payload = {
    #     "type": "temperature",
    #     "unit": "C",
    #     "mlx_ambient": None if t_amb is None else round(t_amb, 2),
    #     "mlx_object": None if t_obj is None else round(t_obj, 2),
    #     "max31855": None
    #     if t_tc is None
    #     else (round(t_tc, 2) if isinstance(t_tc, float) else None),
    # }
    line = f"{t_amb}:{t_obj}:{t_tc}"
    return line


# ---- Manejo de comandos (desde Wemos, canal EMSTAT) ----
def handle_command(cmd_obj: dict):
    """Procesa comandos recibidos por EMSTAT: desde el Wemos (PC -> TCP -> Wemos -> UART)."""
    global measuring, sample_ms, IS_EMSTAT_CONNECTED

    if not isinstance(cmd_obj, dict):
        # Error de formato -> responde por EMSTAT porque el comando venía por EMSTAT
        send_emstat_line({"error": "BAD_FORMAT"})
        return

    c = cmd_obj.get("cmd")

    # Comandos de telemetría general (temperaturas): responde por UDP
    if c == "START":
        measuring = True
        send_udp_line(
            {"type": "ack", "cmd": "START", "measuring": True, "sample_ms": sample_ms}
        )
    elif c == "STOP":
        measuring = False
        send_udp_line({"type": "ack", "cmd": "STOP", "measuring": False})
    elif c == "SET":
        if "sample_ms" in cmd_obj:
            try:
                v = int(cmd_obj["sample_ms"])
                if v < 10:
                    v = 10
                sample_ms = v
            except Exception:
                send_udp_line(
                    {
                        "type": "ack",
                        "cmd": "SET",
                        "status": "ERR",
                        "detail": "sample_ms_invalid",
                    }
                )
                return
        send_udp_line(
            {"type": "ack", "cmd": "SET", "status": "OK", "sample_ms": sample_ms}
        )
    elif c == "PING":
        # PING general -> responde por UDP
        send_udp_line({"type": "pong", "ts": now_ms()})

    # Comandos de EmStat: responde por EMSTAT
    elif c == "EMSTAT_TEST":
        try:
            flag_emstat, version = emstatpico.test_connection()
            IS_EMSTAT_CONNECTED = bool(flag_emstat)
            send_emstat_line(
                {"type": "emstat_status", "ok": bool(flag_emstat), "version": version}
            )
        except Exception as e:
            IS_EMSTAT_CONNECTED = False
            send_emstat_line({"type": "emstat_status", "ok": False, "error": str(e)})
    elif c == "METHOD":
        # Ejecuta MethodSCRIPT o job en EmStat (según tu driver)
        script = cmd_obj.get("script")
        params = cmd_obj.get("params")
        try:
            # Si tu driver tiene streaming con callback:
            if hasattr(emstatpico, "emstat_job_stream_over_uart"):
                # Callback: cada resultado lo mando por EMSTAT
                emstatpico.emstat_job_stream_over_uart(params, send_emstat_line)
                send_emstat_line({"type": "emstat_done"})
            elif hasattr(emstatpico, "run_method_script"):
                res = emstatpico.run_method_script(script)
                send_emstat_line({"type": "emstat_result", "ok": True, "result": res})
            else:
                send_emstat_line(
                    {"type": "emstat_result", "ok": False, "error": "METHOD_UNIMPL"}
                )
        except Exception as e:
            send_emstat_line({"type": "emstat_result", "ok": False, "error": str(e)})

    else:
        # Comando desconocido -> responde por EMSTAT (porque vino por EMSTAT)
        send_emstat_line({"error": "UNKNOWN_CMD", "cmd": c})


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
