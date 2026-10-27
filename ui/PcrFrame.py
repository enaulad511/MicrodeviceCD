# -*- coding: utf-8 -*-

import os
import re
import threading
import time
import traceback
from collections import deque
from datetime import datetime
from tkinter import filedialog

import matplotlib.pyplot as plt
import ttkbootstrap as ttk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from ttkbootstrap.scrolled import ScrolledFrame

from Drivers.ClientUDP import UdpClient
from templates import pcr_projects as pcrp
from templates.constants import (
    chip_rasp,
    font_entry,
    led_fluorescence_pin,
    led_heatin_pin,
    serial_port_encoder,
)
from templates.utils import (
    experiment_dir,
    read_settings_from_file,
    read_temp_source,
    temp_source_index,
    temp_source_key,
    temp_source_label,
    temp_source_label_by_index,
    write_temp_source,
)
from templates.xlsx_io import flatten_settings, kv_rows, write_workbook
from ui.KeyboardFrame import NumericKeyboard

# spinMotorRPM_ramped se importa lazy desde Drivers.DriverStepperSys dentro de
# los métodos que lo usan (el módulo del driver importa gpiod/serial y a nivel
# de módulo rompería el modo dev en Windows).

__author__ = "Edisson A. Naula"
__date__ = "$ 21/10/2025 at 11:30 a.m. $"


# Variables globales
sistemaMotor = None
thread_motor = None
ads = None
thread_lock = threading.Lock()

# Duración de la lectura de fluorescencia. Son solo los DEFAULTS: los efectivos
# vienen de settings.json → pcr_fluorescence (_fluor_cfg) y se leen una vez por
# corrida en self.fluor_cfg, que usan la lectura, la espera previa y la ETA.
FLUOR_PRE_SLEEP_S = 0.5  # pre_sleep_s: espera tras el hold de extensión, antes de muestrear
FLUOR_BASELINE_S = 0.5  # baseline_s: ventana de línea base (luz OFF)
FLUOR_LIGHT_S = 2.0  # light_s: ventana de excitación (luz ON)
FLUOR_POST_S = 0.5  # post_s: ventana de decaimiento (luz OFF)
FLUOR_SAMPLE_DT_S = 0.1  # sample_dt_s: periodo de muestreo dentro de cada ventana
FLUOR_AVERAGES = 4  # averages: lecturas del ADS promediadas por muestra

# Fuentes de temperatura válidas en PCR: IR Ambient queda fuera (no es la
# temperatura de la muestra, solo referencia). El primario regula el PID y el
# secundario capturado/ploteado es el complemento del par {IR Object, Termocupla}.
PCR_TEMP_SOURCE_KEYS = ("thermocouple", "ir_object")

# Colores por canal para las dos curvas del plot (misma convención que Quick
# Control: IR Ambient azul, IR Object naranja, Termocupla rojo).
PCR_TEMP_CHANNEL_COLORS = {
    "IR Ambient": "tab:blue",
    "IR Object": "tab:orange",
    "Thermocouple": "tab:red",
}

# Ventanas del watchdog de sensores (par IR Object/Termocupla) en PCR.
# Espera máxima al inicio por una lectura válida. DEFAULT: el efectivo es
# pidControllerRPM.temp_start_wait_s (se lee en experiment_pcr; <= 0 → default).
PCR_TEMP_START_WAIT_S = 3.0
# Sin lectura fresca de ninguno de los dos → detener. Es solo el DEFAULT: el valor
# efectivo es pidControllerRPM.temp_stale_s de settings.json (_read_temp_dead_s).
PCR_TEMP_DEAD_S = 10.0
# Stop (docs/pcr_fin_corrida.md): si el hilo del experimento no llegó a su cierre en
# PCR_STOP_FORCE_S (colgado en una espera), la UI fuerza el apagado del hardware. Si
# tras PCR_STOP_GIVEUP_S sigue vivo, la UI se restaura igual (Start sigue bloqueado
# mientras viva). Cubre de sobra la reacción al Stop + el guardado (~3 s en el Pi).
PCR_STOP_FORCE_S = 3.0
PCR_STOP_GIVEUP_S = 30.0


def _read_temp_dead_s():
    """Ventana del watchdog 'ambas caídas' desde settings.json (temp_stale_s).

    Cae a PCR_TEMP_DEAD_S si la clave falta o no es un número > 0, para que un
    valor mal tecleado en el ConfigFrame nunca desarme el watchdog.
    """
    pid = read_settings_from_file().get("pidControllerRPM", {})
    try:
        value = float(pid.get("temp_stale_s", PCR_TEMP_DEAD_S))
    except (TypeError, ValueError):
        return PCR_TEMP_DEAD_S
    return value if value > 0 else PCR_TEMP_DEAD_S


# Fases del experimento: código estable → etiqueta del label de estado. El código
# se graba por muestra en la columna `phase` del CSV de temperatura (ancla para
# estadística posterior), así que NO se renombra; la etiqueta sí se puede retocar.
# Toda transición pasa por _enter_phase para que etiqueta y código no diverjan.
PCR_PHASE_LABELS = {
    "initial": "Initial",
    "denat_ramp": "Denaturation",
    "denat_hold": "Denaturation Hold",
    "high_ramp": "Reach High temp",
    "high_hold": "Hold High temp",
    "cooling": "Cooling",
    "low_hold": "LOW temp Hold",
    "ext_ramp": "Reach ext temp",
    "ext_hold": "extension temp Hold ",
    "fluor_read": "Reading Fluorescence",
    "final_ext": "Extension",
    "final_read": "Reading final fluorescence",
    "done": "Final",
    "aborted_start": "Aborted: temp sensors unavailable at start",
    "aborted_sensors": "Aborted: both temp sensors unavailable",
    "aborted_timeouts": "Aborted: too many consecutive cycles with phase timeouts",
}

# Salvaguarda de fases que esperan una temperatura (denat_ramp, high_ramp,
# ext_ramp, cooling): sin ella, un disco que no llega (problema mecánico que el
# ciclo siguiente suele resolver solo) colgaba la corrida. Si la fase dura más de
# max(piso, factor × estimado) se abandona y se pasa a la siguiente. Estos son
# DEFAULTS; los efectivos vienen de settings.json → pidControllerRPM
# (_phase_timeout_cfg). Ver docs/pcr_timeout_fases.md.
PCR_TIMEOUT_FACTOR = 3.0  # phase_timeout_factor (<= 0 desactiva la salvaguarda)
PCR_TIMEOUT_FLOOR_S = 20.0  # phase_timeout_floor_s: cubre la cola de asentamiento del PI
PCR_RAMP_S_PER_C = 0.2  # ramp_s_per_c: estimado de calentamiento (≈5 °C/s); también la preview
# cool_s_per_c: estimado de enfriamiento = ΔT real × s/°C, medido en la corrida Newn1
# (94→60 °C a 700 rpm: 34 s, 1.02 s/°C de mediana, máx 1.19). La cola pasiva tras
# parar el motor (target+9.5 → target+0.5, margen de entonces) es ~2/3 de ese tiempo,
# por eso se dejó la vieja fórmula por rpm (10000 / rpm), que solo veía el giro y se
# quedaba 2.4× corta: con factor 3 dejaba un margen de 7 % y daría timeouts falsos.
# La preview y la ETA usan esta misma tasa (_estimate_cycle_s).
PCR_COOL_S_PER_C = 1.0
# cool_stop_margin_c: el giro del enfriamiento para en target + margen y el resto
# (hasta target + 0.5) baja en pasivo. Más margen = menos undershoot y más cola
# pasiva. Newn1 corrió con 9.5; con un margen distinto cool_s_per_c cambia.
PCR_COOL_STOP_MARGIN_C = 5.5
PCR_MAX_FAILED_CYCLES = 3  # max_failed_cycles: consecutivos con timeout → abortar (0 = nunca)
# Pausa de los lazos de espera que antes giraban sin dormir. La temperatura llega
# cada ~80 ms, así que 10 ms no cambian la reacción y liberan el núcleo.
PCR_POLL_S = 0.01


# Frescura de la temperatura RELATIVA A LA CADENCIA MEDIDA: una lectura sigue
# siendo confiable hasta que la siguiente llega fresh_dt_factor veces tarde. Los
# umbrales absolutos (m_age_* de las rampas, ts_pcr de los holds) quedan como piso.
# Sin esto, con lecturas cada 0.3 s (Newn1) contra umbrales de 0.02–0.2 s, el heater
# quedaba forzado a OFF ~2/3 del tiempo en holds y cerca del setpoint (medido en
# simulación del código: 35 % de duty donde el PI pedía 100 %). Ver
# docs/pcr_temperature_control.md §9 y docs/pcr_pendientes.md punto 1.
PCR_FRESH_DT_FACTOR = 1.5  # fresh_dt_factor (0 desactiva: solo umbrales absolutos)
PCR_FRESH_AGE_CAP_S = 1.0  # fresh_age_cap_s: tope; más allá ya es un stall, no cadencia
# El estimador es un PERCENTIL ALTO de los huecos, no la mediana: con power_save del
# Pi apagado las lecturas llegan en ráfagas (3–4 casi juntas cada ~0.27 s; captura del
# 14/10: rate 12.5/s, mediana 0.023 s, p95 0.27 s), y la mediana mide el espaciado
# DENTRO de la ráfaga, no cuánto hay que confiar en la última lectura.
PCR_CADENCE_WIN = 25  # huecos en la ventana (~2 s a 12.5 lecturas/s)
PCR_CADENCE_PCTL = 0.9  # p90: con 25 huecos descarta los 3 mayores (stalls aislados)
PCR_CADENCE_MIN_N = 10  # huecos medidos antes de relajar nada


def _cfg_num(pid, key, default):
    """float de settings; no numérico o negativo → default (tecleo en ConfigFrame)."""
    try:
        value = float(pid.get(key, default))
    except (TypeError, ValueError):
        return default
    return value if value >= 0 else default


def _phase_timeout_cfg(pid):
    """Parámetros de la salvaguarda desde el dict pidControllerRPM, validados.

    Un valor no numérico o negativo cae a su default (un tecleo erróneo en el
    ConfigFrame no debe desarmar ni volver absurda la salvaguarda). factor 0
    la desactiva a propósito; max_failed 0 = nunca abortar por timeouts.
    """
    return {
        "factor": _cfg_num(pid, "phase_timeout_factor", PCR_TIMEOUT_FACTOR),
        "floor_s": _cfg_num(pid, "phase_timeout_floor_s", PCR_TIMEOUT_FLOOR_S),
        "s_per_c": _cfg_num(pid, "ramp_s_per_c", PCR_RAMP_S_PER_C),
        "cool_s_per_c": _cfg_num(pid, "cool_s_per_c", PCR_COOL_S_PER_C),
        "max_failed": int(_cfg_num(pid, "max_failed_cycles", PCR_MAX_FAILED_CYCLES)),
    }


def _freshness_cfg(pid):
    """Frescura relativa a la cadencia: factor (0 = desactivada) y tope en s."""
    return {
        "factor": _cfg_num(pid, "fresh_dt_factor", PCR_FRESH_DT_FACTOR),
        "cap_s": _cfg_num(pid, "fresh_age_cap_s", PCR_FRESH_AGE_CAP_S),
    }


def _fluor_cfg(fl):
    """Ventanas y muestreo de la lectura de fluorescencia desde el dict pcr_fluorescence.

    No numérico o negativo → default. baseline_s y light_s en 0 también: sin una
    de esas dos ventanas el delta (luz − baseline) pierde sentido. pre_sleep_s y
    post_s sí admiten 0 (sin espera previa / sin ventana de decaimiento), y
    sample_dt_s también (sin pacing: tan rápido como lea el ADS). averages es
    entero >= 1 (0 → default).
    total_s = lo que consume una lectura completa (espera previa + 3 ventanas);
    el muestreo no lo cambia, las ventanas son por tiempo.
    """
    cfg = {
        "pre_sleep_s": _cfg_num(fl, "pre_sleep_s", FLUOR_PRE_SLEEP_S),
        "baseline_s": _cfg_num(fl, "baseline_s", FLUOR_BASELINE_S) or FLUOR_BASELINE_S,
        "light_s": _cfg_num(fl, "light_s", FLUOR_LIGHT_S) or FLUOR_LIGHT_S,
        "post_s": _cfg_num(fl, "post_s", FLUOR_POST_S),
        "sample_dt_s": _cfg_num(fl, "sample_dt_s", FLUOR_SAMPLE_DT_S),
        "averages": int(_cfg_num(fl, "averages", FLUOR_AVERAGES)) or FLUOR_AVERAGES,
    }
    cfg["total_s"] = cfg["pre_sleep_s"] + cfg["baseline_s"] + cfg["light_s"] + cfg["post_s"]
    return cfg


# Control adaptativo de PCR (opcional: settings.json → pcr_adaptive, apagado por
# defecto). Cada experimento usa un disco nuevo y su retraso térmico cambia mucho
# (21/10/2026: el termopar respondía en 0.3–1.25 s según el disco), mientras que la
# potencia para sostener una temperatura es del instrumento (≈0.20 a 90 °C en los tres
# discos). Así que aprende el disco durante la corrida:
#  - rampa: potencia plena hasta setpoint − "calor en vuelo" aprendido por rampa; luego
#    solo el feed-forward mientras la temperatura sigue subiendo, y el pico enseña;
#  - hold: feed-forward (duty de régimen aprendido por hold; inicial ff_slope ×
#    (setpoint − ff_t0)) + PI suave encima. Dentro de la banda se mantiene el
#    feed-forward (el hold clásico fuerza 0).
# Apagado, el control clásico corre intacto. Ver docs/pcr_control_adaptativo.md.
PCR_ADAPT_DEFAULTS = {
    "enabled": 0.0,
    "ff_slope": 0.0043,  # duty por °C sobre ff_t0: 0.21 a 90 °C, 0.04 a 50 °C (medido 21/10)
    "ff_t0": 40.0,
    "ff_learn": 0.5,  # peso del duty medido en cada hold (0 = no aprende)
    "hold_kp": 0.1,
    "hold_ki": 0.03,
    "hold_imax": 3.0,
    "hold_tband": 0.05,
    "hold_win": 0.05,
    "coast_init": 4.0,  # °C de calor en vuelo supuestos en la rampa de denat (una por corrida)
    # Ídem para high y ext, que ya no heredan el de denat: la rampa de denat arranca en
    # frío y su calor en vuelo no se parece (26/10/2026: semilla 2.7–5.5 °C, los dos
    # discos convergieron a 8.4–9.8 °C en high, y el ciclo 2 se pasó +12 °C). Pasarse de
    # alto es barato: el hold termina el acercamiento.
    "coast_init_cycle": 8.0,
    "coast_learn": 0.5,  # ganancia del corte: coast += coast_learn·(pico − setpoint)
    "coast_min": 0.5,
    "coast_max": 12.0,
    "coast_window_s": 8.0,  # espera máxima del pico tras cortar
    # Cambio máximo del corte por rampa (°C; 0 = sin tope). Un salto del termopar que no
    # se detecta (llega ya en el hold) movía el corte hasta 4 °C de golpe (26/10).
    "coast_step_max": 2.0,
    # Subida de la EMA (°C/s) que el heater no puede dar: es un salto del termopar
    # (contacto, por encima de ~70 °C en algunos discos) y esa rampa no enseña. Medido el
    # 26/10: sin salto ≤ 18 °C/s, con salto 17–48. 0 = no se filtra.
    "jump_cps": 20.0,
    # Potencia máxima del hold sobre el feed-forward (0 = sin tope). Tras un corte
    # temprano, el P del hold (×2 del fuzzy lejos del setpoint) calentaba a fondo sin
    # descontar el calor en vuelo y se pasaba hasta +4.5 °C (26/10).
    "hold_pmax": 0.3,
}
# Potencia plena mínima para que un pico POR ENCIMA del setpoint enseñe: con un corte
# inmediato (la rampa arrancó ya pasada del corte) no se midió el calor en vuelo.
# Quedarse corto enseña siempre (atrasar el corte es la dirección segura). Era 1.0 s:
# con la semilla de 8 °C la rampa a ext tiene 0.5–1.0 s de potencia plena y no
# aprendía nunca (simulación y 26/10, disco B).
PCR_ADAPT_MIN_FULL_S = 0.3
PCR_ADAPT_PEAK_DROP_C = 0.15  # caída desde el máximo que marca el pico
# Fin de la subida por calor en vuelo: tasa (°C/s, medida en RATE_WIN_S, que cubre al
# menos una ráfaga UDP de ~0.27 s) por debajo de la cual ya sube solo por el
# feed-forward (≤ ~0.5 °C/s en el modelo; el calor en vuelo sube a varios °C/s).
PCR_ADAPT_RISE_END_CPS = 0.8
PCR_ADAPT_RATE_WIN_S = 0.6
# Lapso mínimo para estimar una tasa: las lecturas de una misma ráfaga llegan con ~1 ms
# de diferencia, y un cociente entre ellas da cientos de °C/s.
PCR_ADAPT_RATE_MIN_SPAN_S = 0.2
# Lapso mínimo de la tasa que se compara con jump_cps. Una ráfaga trae lecturas tomadas
# hasta ~0.24 s antes de llegar, y en lapsos cortos eso infla la tasa. Con 0.45 s,
# emulando el peor caso sobre las 5 corridas del 21 y 26/10: 79 % de los saltos
# detectados y 2 falsos positivos en 287 rampas.
PCR_ADAPT_JUMP_SPAN_S = 0.45
PCR_ADAPT_LEARN_MAX_ERR_C = 0.75  # solo se aprende el duty de un hold cerca del setpoint
PCR_ADAPT_LEARN_MIN_S = 2.0  # segunda mitad mínima del hold para aprender el duty


def _adaptive_cfg(d):
    """Parámetros del control adaptativo desde el dict pcr_adaptive, validados.

    No numérico o negativo → default. enabled > 0 lo activa. Los pesos de aprendizaje
    se recortan a [0, 1]; hold_win 0 → default (sin ventana no hay PWM). coast_step_max,
    jump_cps y hold_pmax en 0 desactivan su tope o filtro.
    """
    cfg = {k: _cfg_num(d, k, v) for k, v in PCR_ADAPT_DEFAULTS.items()}
    cfg["enabled"] = cfg["enabled"] > 0
    cfg["ff_learn"] = min(1.0, cfg["ff_learn"])
    cfg["coast_learn"] = min(1.0, cfg["coast_learn"])
    cfg["hold_win"] = cfg["hold_win"] or PCR_ADAPT_DEFAULTS["hold_win"]
    cfg["coast_max"] = max(cfg["coast_max"], cfg["coast_min"])
    return cfg


# Temperatura de partida que asumen la preview y la ETA (no hay lectura todavía).
PCR_ROOM_TEMP_C = 20.0


def _estimate_cycle_s(high_temp, low_temp, ext_temp, time_high, time_low, ext_time, cfg, fluor_s):
    """Duración estimada de UN ciclo en régimen, con el mismo modelo que la
    salvaguarda de fases (ΔT × ramp_s_per_c al subir, ΔT × cool_s_per_c al bajar)
    y las mismas reglas de omisión que _run_cycle. Incluye la lectura de
    fluorescencia (fluor_s = _fluor_cfg(...)["total_s"]). Contra Newn1: 80.3 s
    estimados vs ~83 s medidos.
    """
    # Un ciclo arranca donde terminó el anterior: en ext, o en la última fase activa.
    cur = ext_temp if not _skip(ext_time) else (low_temp if not _skip(time_low) else high_temp)
    total = 0.0
    if not _skip(time_high):
        total += abs(high_temp - cur) * cfg["s_per_c"] + time_high
        cur = high_temp
    cool_target = low_temp if not _skip(time_low) else (ext_temp if not _skip(ext_time) else None)
    if cool_target is not None and cur > cool_target:
        total += (cur - cool_target) * cfg["cool_s_per_c"]
        cur = cool_target
    if not _skip(time_low):
        total += time_low
        cur = low_temp
    if not _skip(ext_time):
        total += abs(ext_temp - cur) * cfg["s_per_c"] + ext_time
    return total + fluor_s


def _estimate_total_s(
    high_temp,
    low_temp,
    ext_temp,
    time_high,
    time_low,
    ext_time,
    cycles,
    denat_temp,
    denat_time,
    ext_time_final,
    initial_spin_time,
    cfg,
    fluor_s,
):
    """Duración estimada de la corrida completa (ETA antes del primer ciclo)."""
    total = max(0.0, initial_spin_time)
    if not _skip(denat_time):
        total += abs(denat_temp - PCR_ROOM_TEMP_C) * cfg["s_per_c"] + denat_time
    total += cycles * _estimate_cycle_s(
        high_temp, low_temp, ext_temp, time_high, time_low, ext_time, cfg, fluor_s
    )
    return total + max(0.0, ext_time_final) + fluor_s


def check_temp_higher(temp, target_temp):
    return temp >= target_temp


def _skip(t):
    """True si una fase debe omitirse: su tiempo es <= 0 (o no numérico).

    Cuando una fase se omite se salta tanto la rampa de alcance como el hold,
    para no calentar hacia un setpoint que luego no se sostiene.
    """
    try:
        return float(t) <= 0
    except (TypeError, ValueError):
        return False


def _project_slug(name):
    """Slug seguro para nombre de archivo a partir del proyecto PCR activo.

    El snapshot implícito (`_last_run`) o un nombre vacío/no nombrado cae a
    "last_run". Cualquier carácter fuera de [A-Za-z0-9._-] se neutraliza a "_"
    (sin transliterar acentos), colapsando repeticiones. Si tras sanear queda
    vacío, también cae a "last_run".
    """
    if not name or name == pcrp.LAST_RUN_KEY:
        return "last_run"
    slug = re.sub(r"[^A-Za-z0-9._-]", "_", str(name))
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug or "last_run"


# Cortes del gain scheduling en |error| (°C), compartidos con _fuzzy_max_age. Las
# interpolaciones se escriben EN FUNCIÓN de estas constantes a propósito: el bug
# corregido el 13/10/2026 fue mover los cortes (15/5 → 7/3 → 5/2 °C, mayo-junio) sin
# reescalar las t, que quedaron negativas en la zona media con un salto en el corte
# alto. Ver docs/pcr_pendientes.md punto 10.
FUZZY_NEAR_C = 2.0
FUZZY_FAR_C = 5.0


def _fuzzy_gains(error: float, base_kp: float, base_ki: float) -> tuple:
    """Escala KP/KI dinámicamente según la magnitud del error (fuzzy gain scheduling).

    Tres zonas, continuas, con interpolación lineal:
      |e| >= FAR (5°C)     → agresivo (kp×2.0, ki×0.2): rampas largas sin windup
      NEAR <= |e| < FAR    → intermedio: kp 1.0→2.0, ki 1.0→0.2
      |e| < NEAR (2°C)     → preciso: kp 0.5→1.0, ki 1.3→1.0 (en el setpoint, 0.5/1.3)

    Los factores de escala operan sobre las ganancias base leídas de settings.json,
    por lo que el punto de operación nominal sigue siendo configurable allí.
    """
    abs_error = abs(error)
    if abs_error >= FUZZY_FAR_C:
        kp_s, ki_s = 2.0, 0.2
    elif abs_error >= FUZZY_NEAR_C:
        t = (abs_error - FUZZY_NEAR_C) / (FUZZY_FAR_C - FUZZY_NEAR_C)  # 0..1 de NEAR a FAR
        kp_s = 1.0 + t * 1.0  # 1.0 → 2.0
        ki_s = 1.0 - t * 0.8  # 1.0 → 0.2
    else:
        t = abs_error / FUZZY_NEAR_C  # 0..1 de 0 °C a NEAR
        kp_s = 0.5 + t * 0.5  # 0.5 → 1.0
        ki_s = 1.3 - t * 0.3  # 1.3 → 1.0
    return base_kp * kp_s, base_ki * ki_s


def _fuzzy_max_age(error: float, m_age_min: float, m_age_max: float) -> float:
    """Escala dinámicamente la edad máxima de temperatura confiable (freshness).

    Reutiliza los mismos umbrales de |error| que `_fuzzy_gains` (2°C y 5°C):
      |e| >= 5°C   → m_age_max (plano): rampa dura, tolera lecturas UDP añejas
      2 <= |e| < 5 → interpolación lineal m_age_min → m_age_max
      |e| < 2°C    → m_age_min (plano): cerca del setpoint, exige frescura

    Monótona: mayor error ⇒ mayor m_age. Solo se usa en la rampa (reach);
    el hold conserva su umbral estricto. Los límites vienen de settings.json
    por fase (m_age_min_<phase> / m_age_max_<phase>).
    """
    abs_error = abs(error)
    if abs_error >= FUZZY_FAR_C:
        return m_age_max
    if abs_error < FUZZY_NEAR_C:
        return m_age_min
    t = (abs_error - FUZZY_NEAR_C) / (FUZZY_FAR_C - FUZZY_NEAR_C)  # 0..1 de NEAR a FAR
    return m_age_min + t * (m_age_max - m_age_min)


def create_widgets_pcr(parent):
    entries = []

    # Frame: Configuración PCR
    frame1 = ttk.LabelFrame(parent, text="PCR Configuration")
    frame1.configure(style="Custom.TLabelframe")
    frame1.grid(row=0, column=0, padx=(5, 25), pady=(5, 5), sticky="nswe")
    # frame1.configure(style="Custom.TLabelframe")

    labels = [
        "High Temp (°C):",
        "Low Temp (°C):",
        "Time High (s):",
        "Time Low (s):",
        "Number of Cycles:",
        "RPM Cooling:",
        "Denaturing time (s):",
        "Denaturing Temp:",
        "Ext. Time:",
        "Ext. Temp:",
        "Ext. Time F.: ",
        "Initial Spin [s]: ",
    ]
    columns = 2
    default_values = ["94", "55", "15", "15", "3", "700", "30", "94", "6", "68", "300", "15"]
    for i, lbl in enumerate(labels):
        row = i // columns
        col = i % columns
        ttk.Label(frame1, text=lbl, style="Custom.TLabel").grid(
            row=row, column=col * 2, padx=5, pady=5, sticky="e"
        )
        entry = ttk.Entry(frame1, font=font_entry)
        entry.insert(0, default_values[i])
        entry.grid(row=row, column=col * 2 + 1, padx=5, pady=5)

        # entry.bind("<FocusIn>", show_numeric_keyboard)

        entries.append(entry)
    # frame1.bind("<FocusOut>", hide_keyboard)
    frame1.columnconfigure(tuple(range(2 * columns)), weight=1)

    return entries


def create_buttons(master, callbacks, svar_status):
    frame_buttons = ttk.Frame(master)
    frame_buttons.grid(row=0, column=0, sticky="nswe")
    frame_buttons.columnconfigure(tuple(range(4)), weight=1)
    # Botón para generar perfil
    ttk.Button(
        frame_buttons,
        text="📈",
        style="info.TButton",
        command=callbacks.get("callback_generate_profile", ()),
    ).grid(row=0, column=0, padx=10, sticky="nswe")
    # Boton para empezar experimento
    ttk.Button(
        frame_buttons,
        text="▶️Start",
        style="success.TButton",
        command=callbacks.get("callback_start_experiment", ()),
    ).grid(row=0, column=1, padx=10, sticky="nswe")

    # save data button
    ttk.Button(
        frame_buttons,
        text="⏹️Stop",
        style="danger.TButton",
        command=callbacks.get("callback_stop_experiment", ()),
    ).grid(row=0, column=2, padx=10, sticky="nswe")

    ttk.Button(
        frame_buttons,
        text="💾Save Data",
        style="info.TButton",
        command=callbacks.get("callback_save_data", ()),
    ).grid(row=0, column=3, padx=10, sticky="nswe")
    frame_label = ttk.Frame(master, style="Custom.TFrame")
    frame_label.grid(row=1, column=0, sticky="nswe")
    frame_label.columnconfigure(0, weight=1)
    ttk.Label(frame_label, textvariable=svar_status, style="Custom.TLabel").grid(
        row=0, column=0, padx=5, pady=5, sticky="nswe"
    )


class _HeaterMeter:
    """Pin del heater que además acumula cuánto tiempo estuvo encendido.

    Toda escritura del heater pasa por aquí (blast, PWM del PI, cortes por lectura
    vieja, teardown), así que el acumulado es lo que de verdad se calentó, no lo
    que pidió el PI. update_displayed_temperature lo graba por muestra (columna
    heater_on_s): el duty de cualquier ventana es Δheater_on_s / Δt_s. Acumulado y
    no un 0/1 instantáneo porque las muestras llegan en ráfagas (~80 ms) y el PWM
    dura 20–90 ms: el 0/1 muestreado sería puro alias. Ver
    docs/pcr_csv_ciclo_fase.md §6.
    """

    def __init__(self, pin):
        self.pin = pin
        # Escribe el hilo del experimento (o el teardown de Stop), lee el hilo UDP.
        self._lock = threading.Lock()
        self._acc_s = 0.0
        self._on_since: "float | None" = None

    def write(self, value: bool):
        self.pin.write(value)  # si falla no cambió nada: no se contabiliza
        with self._lock:
            # El instante se toma dentro del lock: así on_s es monótono aunque el
            # hilo se duerma entre la escritura del pin y la contabilidad.
            now = time.time()
            if value and self._on_since is None:
                self._on_since = now
            elif not value and self._on_since is not None:
                self._acc_s += now - self._on_since
                self._on_since = None

    def on_s(self, t: float) -> float:
        """Segundos encendido acumulados hasta el instante t (time.time())."""
        with self._lock:
            if self._on_since is None:
                return self._acc_s
            return self._acc_s + max(0.0, t - self._on_since)

    def close(self):
        self.pin.close()


class PCRFrame(ttk.Frame):
    def __init__(self, parent, ads_reader, lock_tabs_callback=None):
        ttk.Frame.__init__(self, parent)
        self.parent = parent
        # Exclusión mutua con Electrochemical y los controles manuales: bloquea
        # sus tabs mientras corre (MainGUI.set_tabs_locked, dueño "pcr").
        self.lock_tabs_callback = lock_tabs_callback
        self.running_experiment = False
        self.pin_heating: "_HeaterMeter | None" = None
        self.pin_pcr = None
        self.temp = 0.0
        self.temp_ts = time.time()
        # Últimas tres temperaturas crudas del disco por índice del payload UDP
        # (0=IR amb, 1=IR obj, 2=termocupla). El primario y el secundario del par
        # se muestran suavizados en el label; IR Ambient se muestra crudo (solo
        # referencia). None = ese sensor no reportó (se muestra "N/A").
        self.temps_raw: list = [None, None, None]
        # Fuente de temperatura elegida. El índice apunta al campo del payload UDP
        # (0=IR amb, 1=IR obj, 2=termocupla) y es lo que el lazo PID regula.
        # En PCR IR Ambient no es válido como primario (no es temp de la muestra):
        # si el valor global persistido fuese ir_ambient, cae a termocupla.
        self.temp_source = read_temp_source()
        if self.temp_source not in PCR_TEMP_SOURCE_KEYS:
            self.temp_source = "thermocouple"
        self.temp_source_idx = temp_source_index(self.temp_source)
        self.temp_source_bad = False
        self.cbo_temp_source: "ttk.Combobox | None" = None
        # Canal secundario (complemento del par): se captura, suaviza y plotea
        # junto al primario. Seed 20° (aparece solo si nunca llegó lectura);
        # ante sensor caído sostiene el último valor (igual que el primario).
        self.temp_secondary = 20.0
        self.data_temperature_secondary: list = []
        # Visibilidad de la curva secundaria: SOLO vista. El canal se sigue
        # leyendo, suavizando y escribiendo en la columna 1 del CSV aunque esté
        # oculto (el lector del análisis lee esa columna por posición). Arranca
        # visible —el comportamiento de siempre— y no se persiste.
        self.show_secondary = ttk.BooleanVar(value=True)
        # Timestamp de la última lectura VÁLIDA por canal (para el watchdog de
        # "ambas caídas") y bandera de que ya llegó al menos una lectura buena.
        self._chan_last_good: list = [0.0, 0.0, 0.0]
        self._temp_ever_valid = False
        self._temp_abort_triggered = False
        # Ventana del watchdog; se relee de settings.json al arrancar cada corrida.
        self.temp_dead_s = PCR_TEMP_DEAD_S
        # Salvaguarda de fases: config (se relee en experiment_pcr) y registro por
        # corrida (se reinicia en init_temperature_graph).
        self.timeout_cfg = _phase_timeout_cfg({})
        self.cool_margin_c = PCR_COOL_STOP_MARGIN_C  # se relee en experiment_pcr
        self.phase_timeouts: list = []  # (cycle, phase, elapsed_s, limit_s, temp, target)
        self._cycle_timeouts: list = []  # códigos de fase con timeout del ciclo en curso
        self.failed_cycles: list = []
        self.consec_failed_cycles = 0
        self.data_photo_timeouts: list = []  # lockstep con data_photodetector
        # Frescura relativa a la cadencia (_note_rx): periodos recientes entre
        # lecturas válidas del primario y el umbral derivado que leen los lazos.
        # 0.0 = sin medición aún → solo rigen los umbrales absolutos.
        self.fresh_cfg = _freshness_cfg({})
        # Ventanas de la lectura de fluorescencia (se relee en experiment_pcr).
        self.fluor_cfg = _fluor_cfg({})
        # Control adaptativo (opcional): config por corrida y lo aprendido del disco,
        # que se reinicia en cada corrida (el disco cambia).
        self.adapt_cfg = _adaptive_cfg({})
        self._adapt_bias: dict = {}  # hold (h_high...) → duty de régimen aprendido
        self._adapt_coast: dict = {}  # rampa (high, ext, denat) → calor en vuelo (°C)
        self._rx_dts: deque = deque(maxlen=PCR_CADENCE_WIN)
        self._last_good_rx: "float | None" = None
        self.fresh_age_s = 0.0
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.ads = ads_reader
        self.fase = "Initial"
        # Ancla por muestra (columnas cycle/phase del CSV): código de la fase en
        # curso (PCR_PHASE_LABELS) y ciclo en curso — 1..N dentro del ciclado, 0
        # fuera de él (antes: initial/denat_*; después: final_*/done).
        self.phase_code = "initial"
        self.cycle_current = 0
        self.ts_display = 0.5
        self.last_display = time.time()
        self.start_pcr_time = time.time()
        self.cycles_complete = 0
        self.start_cycle_time = time.time()
        self.time_end_cycle = time.time()
        self.total_cycles = 0
        self.teorical_time_pcr = 0.0
        self.last_cycle_duration = 0.0
        self.avg_cycle_duration = 0.0
        self.ext_time_final = 0.0
        # Marca del arranque de la extensión final (0.0 = aún no empieza; el reloj
        # de pared nunca es 0). La estimación la usa para contar hacia abajo el
        # segmento final en vez de caer al tiempo teórico ya agotado por el error
        # acumulado entre ciclos.
        self.start_final_ext_time = 0.0
        self.stop_event_motor: "threading.Event | None" = None
        self.stop_udp_listenner: "threading.Event | None" = None
        self.thread_experiment = None
        self.client_temperature = None
        self.temp_update_counter = 0
        self._ui_poll_graph_counter = 0
        self._ui_poll_active = False
        self.content_frame = ScrolledFrame(self, autohide=True)
        self.content_frame.grid(row=0, column=0, sticky="nsew")
        self.content_frame.columnconfigure(0, weight=1)

        # Proyecto PCR activo y baseline para detectar cambios sin guardar.
        # active_project_name puede ser un nombre de usuario o pcrp.LAST_RUN_KEY.
        self.active_project_name = None
        self._loaded_snapshot: dict = {}
        self.cbo_project: "ttk.Combobox | None" = None

        self.frame_entries = ttk.Frame(self.content_frame)
        self.frame_entries.grid(row=1, column=0, sticky="nswe")
        self.frame_entries.columnconfigure(0, weight=1)
        # Metadata de la corrida (pares clave/valor, fijados al arrancar), snapshot de
        # settings.json leído al arrancar y encabezado de la hoja temperature.
        self.meta_pairs: list = []
        self.run_settings: dict = {}
        self.temp_cols = ["primary", "secondary", "t_s", "cycle", "phase", "heater_on_s"]
        # Resultado del guardado automático de fin de corrida, para mostrarlo en la UI.
        self._save_note = ""
        # Cierre de la corrida (docs/pcr_fin_corrida.md): cómo terminó (fila "end" de
        # la metadata), si pasó el start-gate (solo entonces hay datos que guardar), si
        # el hilo ya está en su cierre (apagar + guardar) y el Stop pedido (cuándo y
        # por qué). running_experiment sigue True hasta que el hilo terminó TODO.
        self._run_end = ""
        self._run_started = False
        self._run_closing = False
        self._stop_requested_at = 0.0
        self._stop_reason = ""
        self._stop_forced = False
        self._photo_plotted_n = 0
        # Tick pendiente de _ui_poll_loop (se cancela al cerrar la app).
        self._poll_after_id: "str | None" = None
        # Teardown desde dos hilos (cierre del experimento y red de seguridad del Stop).
        self._teardown_lock = threading.Lock()

        callbacks = {
            "callback_generate_profile": self.callback_generate_profile,
            "callback_start_experiment": self.callback_start_experiment,
            "callback_stop_experiment": self.callback_stop_experiment,
            "callback_save_data": self._on_save_button,
        }
        self.entries = create_widgets_pcr(self.frame_entries)
        self.keyboard = NumericKeyboard(self, scroll_host=self.content_frame, width=260, height=150)
        self.keyboard.attach(self.entries)
        self.svar_status = ttk.StringVar(value="Ready")

        # Barra de proyecto (row 0, arriba de las entradas). Se oculta junto con
        # las entradas durante la corrida.
        self.frame_project = self._build_project_bar(self.content_frame)
        self.frame_project.grid(row=0, column=0, sticky="nswe", padx=(5, 25), pady=(5, 0))

        self.frame_buttons = ttk.Frame(self.content_frame)
        self.frame_buttons.grid(row=2, column=0, sticky="nswe", padx=(5, 25))
        self.frame_buttons.columnconfigure(0, weight=1)
        create_buttons(self.frame_buttons, callbacks, self.svar_status)
        self._build_source_selector(self.frame_buttons)
        # Frame para mostrar el gráfico
        self.profile_frame = ttk.LabelFrame(self.content_frame, text="Profile Preview")
        self.profile_frame.grid(row=3, column=0, padx=(2, 20), pady=10, sticky="nswe")
        self.profile_frame.configure(style="Custom.TLabelframe")

        self.canvas: "FigureCanvasTkAgg | None" = None  # Para almacenar el gráfico incrustado
        # Barra de navegación de matplotlib (zoom/pan/save) y las dos curvas del
        # eje de temperatura. Las curvas solo existen mientras esté montada la
        # figura EN VIVO: la preview del perfil no las tiene (ver _mount_canvas).
        self.toolbar: "NavigationToolbar2Tk | None" = None
        self.line: "plt.Line2D | None" = None
        self.line_secondary: "plt.Line2D | None" = None
        self.callback_generate_profile()  # Generar el gráfico inicial
        self.data_temperature = []
        # Eje temporal real de la curva: segundos transcurridos desde el inicio de
        # la corrida, uno por muestra (ver docs/pcr_eje_tiempo.md). Se anexa en
        # lockstep con las dos curvas de temperatura.
        self.data_time: list = []
        # Ciclo y fase en curso al recibir cada muestra (lockstep con las de arriba).
        self.data_cycle: list = []
        self.data_phase: list = []
        # Segundos de heater encendido acumulados al recibir cada muestra (lockstep).
        self.data_heater_on: list = []
        self.data_photodetector = []
        self.data_photodetector_series = []

        # Auto-carga del proyecto inicial (cascada last_used -> last_run -> Default).
        # Al final de __init__: ya existen profile_frame/canvas que usa la preview.
        self._load_initial_project()
        self.bind("<Destroy>", self._on_destroy)

    def _build_source_selector(self, master):
        """Combobox 'Temp source:' que fija qué temperatura del disco regula el PID.

        Vive en la barra de botones (visible durante la corrida) y se deshabilita
        mientras el experimento corre — la fuente se elige antes de Start. El valor
        es global (settings.json) y se comparte con las tabs de control manual.
        """
        frame = ttk.Frame(master)
        frame.grid(row=2, column=0, sticky="nswe", pady=(0, 5))
        ttk.Label(frame, text="Temp source:", style="Custom.TLabel").grid(
            row=0, column=0, padx=(10, 5), pady=2, sticky="w"
        )
        # Solo Termocupla e IR Object: IR Ambient no es primario válido en PCR.
        pcr_labels = [temp_source_label(k) for k in PCR_TEMP_SOURCE_KEYS]
        self.cbo_temp_source = ttk.Combobox(
            frame,
            values=pcr_labels,
            state="readonly",
            font=font_entry,
            width=14,
        )
        self.cbo_temp_source.set(temp_source_label(self.temp_source))
        self.cbo_temp_source.grid(row=0, column=1, padx=5, pady=2, sticky="w")
        self.cbo_temp_source.bind("<<ComboboxSelected>>", self._on_temp_source_changed)
        # Visibilidad de la curva secundaria, pegada al selector porque primario y
        # secundario son el mismo par. A diferencia del combobox, NO se deshabilita
        # durante la corrida: es vista, y corriendo es cuando más se usa.
        ttk.Checkbutton(
            frame,
            text="Show secondary",
            variable=self.show_secondary,
            command=self._on_show_secondary_changed,
            style="Custom.TCheckbutton",
        ).grid(row=0, column=2, padx=(15, 5), pady=2, sticky="w")

    def _on_temp_source_changed(self, event=None):
        if self.cbo_temp_source is None:
            return
        key = temp_source_key(self.cbo_temp_source.get())
        # Guardarraíl: el combobox ya excluye IR Ambient, pero si por cualquier
        # vía llegara, cae a termocupla para no dejar el par sin sentido.
        if key not in PCR_TEMP_SOURCE_KEYS:
            key = "thermocouple"
            self.cbo_temp_source.set(temp_source_label(key))
        self.temp_source = key
        self.temp_source_idx = temp_source_index(self.temp_source)
        self.temp_source_bad = False
        write_temp_source(self.temp_source)

    def _on_show_secondary_changed(self):
        """Muestra/oculta la curva secundaria del eje de temperatura.

        Es puramente vista: el canal se sigue leyendo, suavizando, mostrando en
        el status label y guardando en el CSV. Solo aplica sobre la figura EN
        VIVO (la preview del perfil no tiene curvas de datos).
        """
        if self.canvas is None or self.line_secondary is None:
            return
        self.line_secondary.set_visible(self.show_secondary.get())
        self._refresh_temp_legend()
        # Ver la nota de update_graph_temperature: sin visible_only la curva
        # escondida seguiría fijando el rango del eje Y.
        self.ax.relim(visible_only=True)
        self.ax.autoscale_view(scalex=False, scaley=True)
        self.canvas.draw_idle()

    def _refresh_temp_legend(self):
        """Leyenda del eje de temperatura, solo con las curvas visibles: anunciar
        un canal que no se está dibujando confunde más que ayuda."""
        handles = [
            ln for ln in (self.line, self.line_secondary) if ln is not None and ln.get_visible()
        ]
        if handles:
            self.ax.legend(handles=handles, fontsize=7, loc="upper right")

    def _mount_canvas(self, fig):
        """Monta `fig` en el panel de la gráfica, reemplazando lo que hubiera.

        `self.canvas` lo comparten dos figuras —la preview teórica del perfil y
        la gráfica en vivo— y cada una destruía el widget de la otra por su
        cuenta. Centralizarlo aquí evita que la barra de navegación quede
        huérfana al cambiar de figura (destruir el canvas no destruye su
        toolbar) y da un único sitio donde montar ambos widgets.
        """
        if self.toolbar is not None:
            self.toolbar.destroy()
            self.toolbar = None
        if self.canvas is not None:
            self.canvas.get_tk_widget().destroy()
        self.canvas = FigureCanvasTkAgg(fig, master=self.profile_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        # Barra debajo del canvas (mismo orden que EventEmstatFrame). OJO: durante
        # la corrida el zoom se pierde en la siguiente muestra, porque
        # update_graph_temperature reimpone la ventana deslizante en cada tick;
        # es un compromiso aceptado (ver docs/pcr_eje_tiempo.md).
        self.toolbar = NavigationToolbar2Tk(self.canvas, self.profile_frame, pack_toolbar=False)
        self.toolbar.pack(fill="x")
        self.canvas.draw()

    def _secondary_idx(self) -> int:
        """Índice del canal secundario: el complemento del par {IR Object(1),
        Termocupla(2)}. Si el primario es termocupla, el secundario es IR Object;
        en cualquier otro caso (IR Object o el guardarraíl) el secundario es la
        termocupla — el canal que el usuario siempre quiere capturar."""
        return 1 if self.temp_source_idx == 2 else 2

    # ------------------------------------------------------------------ #
    # Proyectos PCR (recetas con nombre de las 12 entradas)
    # ------------------------------------------------------------------ #
    def _build_project_bar(self, master):
        frame = ttk.LabelFrame(master, text="PCR Project")
        frame.configure(style="Custom.TLabelframe")
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="Project:", style="Custom.TLabel").grid(
            row=0, column=0, padx=5, pady=5, sticky="w"
        )
        self.cbo_project = ttk.Combobox(frame, state="readonly", font=font_entry)
        self.cbo_project.grid(row=0, column=1, padx=5, pady=5, sticky="we")
        self.cbo_project.bind("<<ComboboxSelected>>", self._on_project_selected)

        ttk.Button(frame, text="💾Save", style="success.TButton", command=self._on_save_as).grid(
            row=0, column=2, padx=3, pady=5, sticky="we"
        )
        ttk.Button(frame, text="📁Import", style="info.TButton", command=self._on_import).grid(
            row=0, column=3, padx=3, pady=5, sticky="we"
        )
        ttk.Button(frame, text="📤Export", style="info.TButton", command=self._on_export).grid(
            row=0, column=4, padx=3, pady=5, sticky="we"
        )
        ttk.Button(frame, text="🗑️Delete", style="danger.TButton", command=self._on_delete).grid(
            row=0, column=5, padx=3, pady=5, sticky="we"
        )
        return frame

    def _display_name(self, name):
        # El snapshot implicito se muestra con etiqueta amigable en el combobox.
        return pcrp.LAST_RUN_LABEL if name == pcrp.LAST_RUN_KEY else name

    def _internal_name(self, display):
        return pcrp.LAST_RUN_KEY if display == pcrp.LAST_RUN_LABEL else display

    def _refresh_project_list(self, select=None):
        # Construye la lista del combobox: «Última corrida» (si existe) primero,
        # luego los proyectos con nombre. `select` es un nombre interno a marcar.
        names = []
        if pcrp.has_last_run():
            names.append(pcrp.LAST_RUN_KEY)
        names.extend(pcrp.project_names())
        if self.cbo_project is None:
            return
        self.cbo_project["values"] = [self._display_name(n) for n in names]
        target = select if select is not None else self.active_project_name
        if target in names:
            self.cbo_project.set(self._display_name(target))

    def _entries_to_dict(self):
        return {key: self.entries[i].get() for i, key in enumerate(pcrp.ENTRY_KEYS)}

    def _apply_values_to_entries(self, values):
        for i, key in enumerate(pcrp.ENTRY_KEYS):
            self.entries[i].delete(0, "end")
            self.entries[i].insert(0, str(values.get(key, "")))

    def _has_unsaved_changes(self):
        if not self._loaded_snapshot:
            return False
        return self._entries_to_dict() != self._loaded_snapshot

    def _do_load_project(self, name, values, persist_last_used=True):
        self._apply_values_to_entries(values)
        self.active_project_name = name
        self._loaded_snapshot = {k: str(values.get(k, "")) for k in pcrp.ENTRY_KEYS}
        if persist_last_used:
            pcrp.set_last_used(name)
        self._refresh_project_list(select=name)
        self.callback_generate_profile()
        self.svar_status.set(f"Project loaded: {self._display_name(name)}")

    def _load_initial_project(self):
        name, values = pcrp.resolve_initial()
        # No persistimos last_used aqui: solo refleja lo que ya estaba elegido.
        self._do_load_project(name, values, persist_last_used=False)

    def _on_project_selected(self, _event=None):
        if self.cbo_project is None:
            return
        display = self.cbo_project.get()
        name = self._internal_name(display)
        if name == self.active_project_name:
            return
        if self._has_unsaved_changes():
            from tkinter import messagebox

            if not messagebox.askyesno(
                "Unsaved changes",
                f"Discard unsaved changes and load '{display}'?",
                parent=self,
            ):
                # Revertir la seleccion del combobox al proyecto activo.
                self._refresh_project_list(select=self.active_project_name)
                return
        values = pcrp.get_project(name)
        if values is None:
            self.svar_status.set(f"Project not found: {display}")
            return
        self._do_load_project(name, values)

    def _on_save_as(self):
        values = self._entries_to_dict()
        ok, msg = pcrp.validate_values(values)
        if not ok:
            self.svar_status.set(f"Cannot save: {msg}")
            return
        # Sugerir el nombre activo salvo que sea el snapshot implicito.
        suggested = (
            ""
            if self.active_project_name in (None, pcrp.LAST_RUN_KEY)
            else self.active_project_name
        )
        name = self._ask_project_name(suggested)
        if not name:
            return
        name = name.strip()
        if not name or pcrp.is_reserved(name):
            self.svar_status.set("Invalid project name.")
            return
        if pcrp.get_project(name) is not None:
            from tkinter import messagebox

            if not messagebox.askyesno(
                "Overwrite project",
                f"Project '{name}' already exists. Overwrite?",
                parent=self,
            ):
                return
        if pcrp.save_project(name, values):
            self._do_load_project(name, values)
            self.svar_status.set(f"Project saved: {name}")
        else:
            self.svar_status.set("Error saving project.")

    def _on_delete(self):
        name = self.active_project_name
        if name is None or pcrp.is_reserved(name):
            self.svar_status.set("Select a saved project to delete.")
            return
        from tkinter import messagebox

        if not messagebox.askyesno("Delete project", f"Delete project '{name}'?", parent=self):
            return
        if pcrp.delete_project(name):
            # Tras borrar, recargar el proyecto inicial de la cascada.
            n, v = pcrp.resolve_initial()
            self._do_load_project(n, v, persist_last_used=False)
            self.svar_status.set(f"Project deleted: {name}")
        else:
            self.svar_status.set("Error deleting project.")

    def _on_import(self):
        path = filedialog.askopenfilename(
            title="Import PCR project",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            parent=self,
        )
        if not path:
            return
        result = pcrp.import_project(path)
        if result is None:
            self.svar_status.set("Error: invalid project file.")
            return
        suggested, values = result
        ok, msg = pcrp.validate_values(values)
        if not ok:
            self.svar_status.set(f"Cannot import: {msg}")
            return
        name = self._ask_project_name(suggested)
        if not name:
            return
        name = name.strip()
        if not name or pcrp.is_reserved(name):
            self.svar_status.set("Invalid project name.")
            return
        if pcrp.get_project(name) is not None:
            from tkinter import messagebox

            if not messagebox.askyesno(
                "Overwrite project",
                f"Project '{name}' already exists. Overwrite?",
                parent=self,
            ):
                return
        if pcrp.save_project(name, values):
            self._do_load_project(name, values)
            self.svar_status.set(f"Project imported: {name}")
        else:
            self.svar_status.set("Error importing project.")

    def _on_export(self):
        name = self.active_project_name
        if name is None:
            self.svar_status.set("No project to export.")
            return
        default_name = "last_run" if name == pcrp.LAST_RUN_KEY else name
        path = filedialog.asksaveasfilename(
            title="Export PCR project",
            defaultextension=".json",
            initialfile=f"{default_name}.json",
            filetypes=[("JSON files", "*.json")],
            parent=self,
        )
        if not path:
            return
        if pcrp.export_project(name, path):
            self.svar_status.set(f"Project exported: {self._display_name(name)}")
        else:
            self.svar_status.set("Error exporting project.")

    def _ask_project_name(self, suggested=""):
        # Diálogo modal "Guardar como": campo de nombre + onboard (teclado del SO)
        # al enfocar. Devuelve el nombre o None si se cancela.
        dialog = ttk.Toplevel(self)
        dialog.title("Save project as")
        dialog.transient(self.winfo_toplevel())
        result: dict = {"name": None}

        ttk.Label(dialog, text="Project name:", style="Custom.TLabel").grid(
            row=0, column=0, columnspan=2, padx=10, pady=(10, 5), sticky="w"
        )
        entry = ttk.Entry(dialog, font=font_entry, width=28)
        entry.grid(row=1, column=0, columnspan=2, padx=10, pady=5, sticky="we")
        entry.insert(0, suggested)
        entry.bind("<FocusIn>", lambda _e: self._launch_os_keyboard())

        def _accept():
            result["name"] = entry.get()
            dialog.destroy()

        def _cancel():
            dialog.destroy()

        ttk.Button(dialog, text="OK", style="success.TButton", command=_accept).grid(
            row=2, column=0, padx=10, pady=10, sticky="we"
        )
        ttk.Button(dialog, text="Cancel", style="secondary.TButton", command=_cancel).grid(
            row=2, column=1, padx=10, pady=10, sticky="we"
        )
        entry.bind("<Return>", lambda _e: _accept())
        dialog.columnconfigure(0, weight=1)
        dialog.columnconfigure(1, weight=1)
        entry.focus_set()
        dialog.grab_set()
        self.wait_window(dialog)
        return result["name"]

    def _launch_os_keyboard(self):
        # onboard solo existe en el Pi; en dev (Windows) falla silenciosamente.
        try:
            from templates.utils import show_keyboard

            show_keyboard()
        except Exception:
            pass

    def callback_generate_profile(self):
        try:
            high_temp = float(self.entries[0].get())
            low_temp = float(self.entries[1].get())
            time_high = float(self.entries[2].get())
            time_low = float(self.entries[3].get())
            cycles = int(self.entries[4].get())
            # RPM solo se valida: el enfriamiento ya se estima por ΔT, no por rpm.
            float(self.entries[5].get())
            denat_time = float(self.entries[6].get())
            denat_temp = float(self.entries[7].get())
            ext_time = float(self.entries[8].get())
            ext_temp = float(self.entries[9].get())
            ext_time_final = float(self.entries[10].get())
            initial_spin_time = float(self.entries[11].get())

            room_temp = PCR_ROOM_TEMP_C
            # Rampas y enfriamiento proporcionales al salto de temperatura (s/°C),
            # con las MISMAS tasas que la salvaguarda de fases (ramp_s_per_c,
            # cool_s_per_c): perfil dibujado, ETA y plazo de cada fase salen del
            # mismo modelo. El enfriamiento antes era 10000 / rpm, que solo
            # ve el giro y lo dibujaba 2.4× más corto que el real (Newn1).
            settings = read_settings_from_file()
            est_cfg = _phase_timeout_cfg(settings.get("pidControllerRPM", {}))
            fluor_s = _fluor_cfg(settings.get("pcr_fluorescence", {}))["total_s"]
            heating_rate_up = est_cfg["s_per_c"]

            def transition_time_up(t_from, t_to):
                return abs(t_to - t_from) * heating_rate_up

            def transition_time_down(t_from, t_to):
                return abs(t_from - t_to) * est_cfg["cool_s_per_c"]

            # Recorte visual de holds largos (denat inicial / ext final): si su
            # duración real supera 1.5x la de un ciclo, se dibujan comprimidos a
            # ese tope para no aplastar los ciclos. Es solo visual: el tiempo real
            # se conserva en la anotación de cada tramo recortado.
            cycle_dur = _estimate_cycle_s(
                high_temp, low_temp, ext_temp, time_high, time_low, ext_time, est_cfg, fluor_s
            )
            clip_cap = 1.5 * cycle_dur if cycle_dur > 0 else float("inf")

            def clip_hold(real_dur):
                """Devuelve (ancho_dibujado, duracion_real, recortado?)."""
                disp = min(real_dur, clip_cap)
                return disp, real_dur, real_dur > clip_cap

            clip_marks = []  # (x_corte, temp, duracion_real) de tramos comprimidos

            # (start, end, from_temp, to_temp, label, color)
            # Las fases con tiempo <= 0 se omiten (misma regla que la ejecución):
            # ni rampa de alcance ni hold, para que la preview refleje lo real.
            phase_segments = []
            current_time = 0.0
            current_temp = room_temp

            # Initial spin: temperatura ambiente
            phase_segments.append(
                (
                    current_time,
                    current_time + initial_spin_time,
                    room_temp,
                    room_temp,
                    "Initial Spin",
                    "gray",
                )
            )
            current_time += initial_spin_time

            # Rampa + hold de denaturation (omitible)
            if not _skip(denat_time):
                ramp_denat = transition_time_up(current_temp, denat_temp)
                phase_segments.append(
                    (
                        current_time,
                        current_time + ramp_denat,
                        current_temp,
                        denat_temp,
                        "Ramp Denat",
                        "darkorange",
                    )
                )
                current_time += ramp_denat

                disp_denat, real_denat, clipped_denat = clip_hold(denat_time)
                phase_segments.append(
                    (
                        current_time,
                        current_time + disp_denat,
                        denat_temp,
                        denat_temp,
                        "Denaturation",
                        "purple",
                    )
                )
                current_time += disp_denat
                if clipped_denat:
                    clip_marks.append((current_time, denat_temp, real_denat))
                current_temp = denat_temp

            n_display = min(5, cycles)
            for _ in range(n_display):
                # Rampa + hold High (omitible)
                if not _skip(time_high):
                    ramp_high = transition_time_up(current_temp, high_temp)
                    phase_segments.append(
                        (
                            current_time,
                            current_time + ramp_high,
                            current_temp,
                            high_temp,
                            "Heating",
                            "orange",
                        )
                    )
                    current_time += ramp_high

                    phase_segments.append(
                        (
                            current_time,
                            current_time + time_high,
                            high_temp,
                            high_temp,
                            "High",
                            "red",
                        )
                    )
                    current_time += time_high
                    current_temp = high_temp

                # Cooling hacia la siguiente fase activa (Low, o Extension si Low se
                # omite). Solo si hay algo más frío hacia lo que enfriar.
                cool_target = (
                    low_temp if not _skip(time_low) else (ext_temp if not _skip(ext_time) else None)
                )
                if cool_target is not None and current_temp > cool_target:
                    ramp_down = transition_time_down(current_temp, cool_target)
                    phase_segments.append(
                        (
                            current_time,
                            current_time + ramp_down,
                            current_temp,
                            cool_target,
                            "Cooling",
                            "green",
                        )
                    )
                    current_time += ramp_down
                    current_temp = cool_target

                # Hold Low (omitible)
                if not _skip(time_low):
                    phase_segments.append(
                        (current_time, current_time + time_low, low_temp, low_temp, "Low", "blue")
                    )
                    current_time += time_low
                    current_temp = low_temp

                # Rampa + hold Extension (omitible)
                if not _skip(ext_time):
                    ramp_ext = transition_time_up(current_temp, ext_temp)
                    phase_segments.append(
                        (
                            current_time,
                            current_time + ramp_ext,
                            current_temp,
                            ext_temp,
                            "Ramp Ext",
                            "goldenrod",
                        )
                    )
                    current_time += ramp_ext

                    phase_segments.append(
                        (
                            current_time,
                            current_time + ext_time,
                            ext_temp,
                            ext_temp,
                            "Extension",
                            "darkcyan",
                        )
                    )
                    current_time += ext_time
                    current_temp = ext_temp

            # Extensión final (omitible; recortable si es muy larga)
            if not _skip(ext_time_final):
                disp_ext_final, real_ext_final, clipped_ext_final = clip_hold(ext_time_final)
                phase_segments.append(
                    (
                        current_time,
                        current_time + disp_ext_final,
                        ext_temp,
                        ext_temp,
                        "Final Ext.",
                        "magenta",
                    )
                )
                current_time += disp_ext_final
                if clipped_ext_final:
                    clip_marks.append((current_time, ext_temp, real_ext_final))

            # Crear figura
            fig, ax = plt.subplots(figsize=(7, 4))
            plt.close("all")
            fig, ax = plt.subplots(figsize=(7, 4))

            labeled = set()
            for seg in phase_segments:
                start, end, t_from, t_to, label, color = seg
                first_occurrence = label not in labeled
                kwargs: dict = (
                    {"linewidth": 2.5} if t_from == t_to else {"linestyle": "--", "linewidth": 1.5}
                )
                if first_occurrence:
                    kwargs["label"] = label
                    labeled.add(label)
                if t_from == t_to:
                    ax.hlines(t_from, start, end, colors=color, **kwargs)
                else:
                    ax.plot([start, end], [t_from, t_to], color=color, **kwargs)

            ax.axhline(high_temp, color="red", linestyle=":", linewidth=0.8, alpha=0.5)
            ax.axhline(low_temp, color="blue", linestyle=":", linewidth=0.8, alpha=0.5)
            ax.axhline(denat_temp, color="purple", linestyle=":", linewidth=0.8, alpha=0.5)
            ax.axhline(ext_temp, color="darkcyan", linestyle=":", linewidth=0.8, alpha=0.5)

            # Marca de discontinuidad + duración real en los holds recortados
            for x_cut, temp, real_dur in clip_marks:
                ax.axvline(x_cut, color="black", linestyle=(0, (2, 2)), linewidth=1.0, alpha=0.6)
                ax.annotate(
                    f"≈{real_dur:.0f}s",
                    xy=(x_cut, temp),
                    xytext=(0, 8),
                    textcoords="offset points",
                    ha="right",
                    va="bottom",
                    fontsize=7,
                    fontweight="bold",
                    color="black",
                )

            ax.legend(loc="upper right", fontsize=7, ncol=2)
            ax.set_xlabel("Time (s) — long holds compressed" if clip_marks else "Time (s)")
            # Eje X sin valores: tras el recorte ya no son segundos reales
            ax.set_xticks([])
            ax.set_ylabel("Temperature (°C)")
            ax.set_title(f"PCR Profile ({cycles} cycles)")
            ax.grid(True)

            # La preview no tiene curvas de datos: soltar las referencias evita
            # que el checkbox o el poll de la gráfica toquen Line2D de una figura
            # ya destruida.
            self.line = None
            self.line_secondary = None
            self._mount_canvas(fig)

        except ValueError:
            print("Error: Verifique los valores ingresados.")

    def update_displayed_temperature(self, text, address, temps_list):
        # Solo actualiza datos Python puros — sin operaciones Tkinter.
        # Tkinter no es thread-safe; toda actualización de UI ocurre en _ui_poll_loop.
        # Se leen dos canales: el primario (temp_source_idx, regula el PID) y el
        # secundario del par (complemento). Ausente (None) → se sostiene el último
        # valor; el primario además marca temp_source_bad para avisar.
        now = time.time()

        def _valid(i):
            # float válido del canal i, o None. Al ser válido, registra el
            # timestamp de última lectura buena (para el watchdog de "ambas caídas").
            try:
                v = temps_list[i]
                if v is None:
                    return None
                f = float(v)
            except (IndexError, TypeError, ValueError):
                return None
            self._chan_last_good[i] = now
            return f

        p_idx = self.temp_source_idx
        p_val = _valid(p_idx)
        if p_val is None:
            lf = self.temp
            self.temp_ts = 0.8
            self.temp_source_bad = True
        else:
            lf = p_val
            self.temp_ts = temps_list[3]
            self.temp_source_bad = False
            self._note_rx(temps_list[3])

        # Secundario: float válido o sostener último valor (seed 20°, solo aparece
        # si nunca llegó lectura de ese canal).
        s_val = _valid(self._secondary_idx())
        s_lf = self.temp_secondary if s_val is None else s_val

        if p_val is not None or s_val is not None:
            self._temp_ever_valid = True

        # Guardar los tres canales crudos para el label (IR Ambient se muestra
        # crudo como referencia). None se conserva para mostrar "N/A".
        try:
            self.temps_raw = [temps_list[0], temps_list[1], temps_list[2]]
        except (IndexError, TypeError):
            pass
        alpha = 0.3
        self.temp = alpha * lf + (1 - alpha) * self.temp
        self.temp_secondary = alpha * s_lf + (1 - alpha) * self.temp_secondary
        # Anexados alineados por índice (misma longitud): primario, secundario y
        # el instante de recepción del datagrama.
        #
        # El tiempo sale de temps_list[3] —que estampa ClientUDP al recibir— y NO
        # de self.temp_ts: cuando el sensor primario falla, temp_ts se fija arriba
        # en 0.8 como centinela de "lectura antiquísima" para que el PID desconfíe,
        # y usarlo aquí mandaría ese punto a 1970.
        try:
            t_rx = float(temps_list[3])
        except (IndexError, TypeError, ValueError):
            t_rx = time.time()
        self.data_temperature.append(self.temp)
        self.data_temperature_secondary.append(self.temp_secondary)
        self.data_time.append(t_rx - self.start_pcr_time)
        # Etiqueta de la muestra con lo que el hilo del experimento declaró en
        # curso al llegar el datagrama (lecturas atómicas de atributos).
        self.data_cycle.append(self.cycle_current)
        self.data_phase.append(self.phase_code)
        heater = self.pin_heating
        if heater is not None:
            heater_on = heater.on_s(t_rx)
        else:
            # Sin pin (antes de armarlo o tras el teardown) el heater está apagado:
            # el acumulado no cambia.
            heater_on = self.data_heater_on[-1] if self.data_heater_on else 0.0
        self.data_heater_on.append(heater_on)

    def _note_rx(self, rx_ts):
        """Actualiza el umbral de frescura con los huecos reales entre lecturas válidas.

        Percentil alto (p90) de los últimos PCR_CADENCE_WIN huecos, no mediana: si
        las lecturas llegan en ráfagas, la mediana es el espaciado dentro de la
        ráfaga (~0.02 s) y dejaría el heater apagado en cada hueco entre ráfagas
        (~0.27 s). El p90 mide ese hueco y, a la vez, descarta los 2–3 mayores de la
        ventana: un stall aislado no lo mueve, así que un corte real sigue apagando
        el heater; solo una degradación SOSTENIDA relaja el umbral, y nunca más allá
        de fresh_age_cap_s. Corre en el hilo UDP, una vez por lectura.
        """
        try:
            rx = float(rx_ts)
        except (TypeError, ValueError):
            return
        if self._last_good_rx is not None and rx > self._last_good_rx:
            self._rx_dts.append(rx - self._last_good_rx)
        self._last_good_rx = rx
        k = self.fresh_cfg["factor"]
        if k > 0 and len(self._rx_dts) >= PCR_CADENCE_MIN_N:
            gaps = sorted(self._rx_dts)
            gap_hi = gaps[int(PCR_CADENCE_PCTL * (len(gaps) - 1))]
            self.fresh_age_s = min(self.fresh_cfg["cap_s"], k * gap_hi)
        else:
            self.fresh_age_s = 0.0

    def _enter_phase(self, code):
        """Declara la fase en curso: código grabado por muestra + etiqueta visible.

        Se invoca desde el hilo del experimento (y desde el watchdog, hilo
        principal); update_displayed_temperature lee phase_code al anexar cada
        muestra. Asignaciones simples de atributo: atómicas bajo el GIL.
        """
        self.phase_code = code
        self.fase = PCR_PHASE_LABELS[code]

    def _check_temp_watchdog(self):
        """Detiene el experimento si ni el primario ni el secundario del par
        entregan lectura fresca por temp_dead_s seguidos ('ambas caídas').

        Solo se arma tras la primera lectura válida (_temp_ever_valid); antes de
        eso es el start-gate quien decide no arrancar. Idempotente: dispara una
        sola vez (_temp_abort_triggered). Se ejecuta en el hilo principal, así que
        solo señaliza los stop-events y marca la fase — el finally del hilo del
        experimento desmonta y _ui_poll_loop restaura la UI al ver running=False.
        """
        # _run_closing: el UDP ya se cerró a propósito (apagar + guardar); no es una caída.
        if (
            not self.running_experiment
            or not self._temp_ever_valid
            or self._temp_abort_triggered
            or self._run_closing
        ):
            return
        last_fresh = max(
            self._chan_last_good[self.temp_source_idx],
            self._chan_last_good[self._secondary_idx()],
        )
        if time.time() - last_fresh > self.temp_dead_s:
            self._temp_abort_triggered = True
            self._enter_phase("aborted_sensors")
            print(
                f"Aborting PCR: both pair sensors stale > {self.temp_dead_s}s — stopping experiment"
            )
            # El motivo va aparte: el hilo puede pasar a otra fase antes de ver el
            # stop y sobrescribir phase_code (la fila "end" lo perdía).
            self.request_stop("aborted_sensors")

    def _ui_poll_loop(self):
        """Actualiza la UI desde el hilo principal (scheduled via after). Un solo hilo."""
        if not self._ui_poll_active:
            return
        elapsed_pcr_time = time.time() - self.start_pcr_time
        mins_elapsed = int(elapsed_pcr_time / 60)
        msg_elapsed_time = (
            f"Time passed: {mins_elapsed} m {elapsed_pcr_time % 60:.1f} s "
            f"-- cycles: {self.cycles_complete}/{self.total_cycles}"
        )
        remaining = self._estimate_remaining_time(elapsed_pcr_time)
        msg_elapsed_time += f" -- Estimated finish: {int(remaining / 60)}m {remaining % 60:.1f}s"
        # Watchdog de "ambas caídas": si ni el primario ni el secundario del par
        # entregan lectura fresca por temp_dead_s seguidos, detener ordenadamente.
        # Solo se arma tras la primera lectura válida (_temp_ever_valid) — antes de
        # eso el start-gate de experiment_pcr es quien decide no arrancar. Señaliza
        # los stop-events y deja que el hilo del experimento desmonte; el propio
        # loop restaurará la UI al detectar running_experiment=False.
        self._check_temp_watchdog()

        src_label = temp_source_label(self.temp_source)
        warn = f"  ⚠ {src_label} unavailable — holding last value" if self.temp_source_bad else ""
        # Secundario del par (suavizado, hold-last): siempre muestra su valor
        # sostenido porque está en la curva. IR Ambient va crudo como referencia
        # ("N/A" si viene ausente); no se plotea ni se guarda.
        sec_label = temp_source_label_by_index(self._secondary_idx())
        amb_raw = self.temps_raw[0] if self.temps_raw else None
        if amb_raw is None:
            amb_shown = "N/A"
        else:
            try:
                amb_shown = f"{float(amb_raw):.1f}"
            except (TypeError, ValueError):
                amb_shown = "N/A"
        extras = f"  ({sec_label} {self.temp_secondary:.1f}, IR Ambient {amb_shown})"
        # Fases abandonadas por la salvaguarda: visibles todo el resto de la corrida
        # (no solo un instante), con la última para saber dónde está fallando.
        timeout_note = ""
        if self.phase_timeouts:
            cyc, code = self.phase_timeouts[-1][0], self.phase_timeouts[-1][1]
            timeout_note = (
                f"  ⚠ {len(self.phase_timeouts)} phase timeout(s), last: {code} (cycle {cyc})"
            )
        # Reconstruir el status completo cada tick: este loop es el único escritor
        # de svar_status durante la corrida, así que no hace falta leer/partir el
        # valor previo. El patrón anterior (get().split("\n") + parchar índices)
        # asumía "una línea por slot"; al mover State a su propia línea, las líneas
        # viejas dejaban de sobreescribirse y el label crecía sin límite.
        # Cierre en curso: el hilo ya apaga y guarda (~3 s en el Pi) o aún sale tras Stop.
        closing_note = ""
        if self.running_experiment:
            if self._run_closing and self._run_started:
                closing_note = "\nSaving data…"
            elif self._stop_requested_at:
                closing_note = "\nStopping…"
        self.svar_status.set(
            f"Temperature: {self.temp:.2f} °C [{src_label}]{extras}{warn}\n"
            f"State: {self.fase}{timeout_note}\n"
            f"{msg_elapsed_time}{closing_note}"
        )

        self._ui_poll_graph_counter += 1
        if self._ui_poll_graph_counter >= 5:
            self._ui_poll_graph_counter = 0
            self.update_graph_temperature()
        # La gráfica del fotodetector se refresca aquí y no desde el hilo del
        # experimento: ese hilo nunca toca Tk (tras cerrar la ventana, eso lanza
        # RuntimeError y la corrida se perdía).
        if len(self.data_photodetector) != self._photo_plotted_n:
            self._photo_plotted_n = len(self.data_photodetector)
            self.update_graph_photodetector()

        gave_up = self._check_stop_timeouts()
        if not self.running_experiment or gave_up:
            # El hilo terminó TODO (apagó y guardó; experiment_pcr pone
            # running_experiment=False al final), sea fin natural, Stop, aborto o
            # error. Restaura los inputs aquí, en el hilo principal (Tkinter no es
            # thread-safe), y detén el poll.
            self._ui_poll_active = False
            self.update_graph_temperature()
            self._restore_input_ui()
            if gave_up:
                print("warning: experiment thread still alive, restoring the UI anyway")
                self._save_note = "Warning: the run did not finish cleanly; data may not be saved"
            self._stop_requested_at = 0.0
            if self._save_note:
                self.svar_status.set(f"{self.svar_status.get()}\n{self._save_note}")
                self._save_note = ""
            return

        self._poll_after_id = self.after(500, self._ui_poll_loop)  # pyrefly: ignore

    def _estimate_remaining_time(self, elapsed_pcr_time):
        # Antes de completar el primer ciclo no hay medición fiable: estima por
        # tiempo teórico restante. Tras un ciclo, proyecta los ciclos pendientes
        # con la duración promedio medida y descuenta lo ya transcurrido del
        # ciclo actual. Suma la extensión final si aún quedan ciclos.
        if self.cycles_complete == 0 or self.avg_cycle_duration <= 0:
            return max(0.0, self.teorical_time_pcr - elapsed_pcr_time)

        cycles_left = max(0, self.total_cycles - self.cycles_complete)
        if cycles_left > 0:
            elapsed_current = max(0.0, time.time() - self.start_cycle_time)
            remaining = (
                self.avg_cycle_duration * cycles_left
                - elapsed_current
                + self.ext_time_final
                + self.fluor_cfg["total_s"]  # lectura de fluorescencia final pendiente
            )
        else:
            # Ya pasaron todos los ciclos: solo queda el segmento final (hold de
            # extensión + lectura de fluorescencia final). NO usar el tiempo
            # teórico aquí: para este punto el error acumulado entre ciclos suele
            # dejar elapsed_pcr_time > teorical_time_pcr, y el max(0,...) mostraría
            # 0 durante toda la extensión final. En su lugar se cuenta hacia abajo
            # un cronómetro fresco anclado al inicio de la extensión final. Si la
            # extensión final está desactivada (ext_time_final<=0), el max(0,...)
            # deja solo la lectura final. start_final_ext_time puede ser 0.0 (no
            # fijado) en la ventana mínima entre el fin de los ciclos y el arranque
            # del segmento; ahí se muestra el total sin descontar.
            total_final = max(0.0, self.ext_time_final) + self.fluor_cfg["total_s"]
            if self.start_final_ext_time > 0.0:
                remaining = total_final - (time.time() - self.start_final_ext_time)
            else:
                remaining = total_final
        return max(0.0, remaining)

    def init_temperature_graph(self):
        self.data_temperature = []  # Datos acumulados
        self.data_temperature_secondary = []
        self.data_time = []
        self.data_cycle = []
        self.data_phase = []
        self.data_heater_on = []
        self.data_photodetector = []
        self.data_photodetector_series = []
        # Reset del estado de captura/watchdog del par para la nueva corrida.
        self.temp_secondary = 20.0
        self._chan_last_good = [0.0, 0.0, 0.0]
        self._temp_ever_valid = False
        self._temp_abort_triggered = False
        self.cycle_current = 0
        self._enter_phase("initial")
        self.phase_timeouts = []
        self._cycle_timeouts = []
        self.failed_cycles = []
        self.consec_failed_cycles = 0
        self.data_photo_timeouts = []
        # La cadencia se mide de nuevo en cada corrida (la de la anterior no aplica).
        self._rx_dts.clear()
        self._last_good_rx = None
        self.fresh_age_s = 0.0

        # Dos subplots apilados: arriba temperatura (denso), abajo fotodetector (1/ciclo)
        self.fig, (self.ax, self.ax_photo) = plt.subplots(
            2, 1, figsize=(4.5, 5.0), constrained_layout=True
        )

        # Dos curvas: primario (regula el PID) y secundario del par, con color por
        # canal (Termocupla rojo, IR Object naranja) y leyenda para distinguirlos.
        p_label = temp_source_label(self.temp_source)
        s_label = temp_source_label_by_index(self._secondary_idx())
        (self.line,) = self.ax.plot(
            [],
            [],
            marker="o",
            markersize=2,
            color=PCR_TEMP_CHANNEL_COLORS.get(p_label),
            label=p_label,
        )
        (self.line_secondary,) = self.ax.plot(
            [],
            [],
            marker="o",
            markersize=2,
            color=PCR_TEMP_CHANNEL_COLORS.get(s_label),
            label=s_label,
        )
        # Las Line2D se recrean en cada corrida: hay que re-aplicarles el estado
        # del checkbox o la secundaria reaparecería al pulsar Start.
        self.line_secondary.set_visible(self.show_secondary.get())
        self.ax.set_title("Temperature (°C)")
        self.ax.set_xlabel("Time (s)")
        self.ax.set_ylabel("°C")
        self._refresh_temp_legend()
        self.ax.grid(True)

        (self.line_photo,) = self.ax_photo.plot([], [], marker="o", color="purple", linewidth=1.2)
        self.ax_photo.set_title("Photodetector (V)")
        self.ax_photo.set_xlabel("Cycle")
        self.ax_photo.set_ylabel("V")
        self.ax_photo.grid(True)

        self._mount_canvas(self.fig)

    def update_graph_temperature(self, window_size=None):
        if window_size is None:
            settings = read_settings_from_file()
            windows_pcr = settings.get("windows_pcr", 2500)
            window_size = int(windows_pcr)
        # self.line es None mientras esté montada la preview del perfil (que no
        # tiene curvas de datos): regenerarla a media corrida no debe reventar
        # el poll de la gráfica.
        if self.canvas is None or self.line is None:
            return

        n = len(self.data_temperature)
        if n == 0:
            return

        # Índice inicial de la ventana. La ventana sigue contándose en MUESTRAS:
        # windows_pcr es un tope de puntos dibujados (costo de render), no una
        # duración. Lo único que cambia respecto al eje por índice es la escala.
        start = max(0, n - window_size)

        # Datos visibles. data_time se anexa junto a las curvas, pero el paro puede
        # caer entre appends: se recorta al mínimo común en vez de asumir igualdad.
        y = self.data_temperature[start:n]
        x = self.data_time[start:n]
        m = min(len(x), len(y))
        if m == 0:
            return
        x, y = x[:m], y[:m]

        self.line.set_xdata(x)
        self.line.set_ydata(y)

        # Curva secundaria del par (misma ventana; se anexa alineada al primario).
        # Se le siguen poniendo datos aunque esté oculta: así el checkbox la
        # devuelve al instante, sin esperar a la siguiente muestra.
        if self.line_secondary is not None:
            ys = self.data_temperature_secondary[start:n][:m]
            self.line_secondary.set_xdata(x[: len(ys)])
            self.line_secondary.set_ydata(ys)

        # Ventana deslizante en X: extremos de tiempo REAL del tramo visible. El
        # guard evita el warning de matplotlib con límites idénticos (1 muestra, o
        # dos datagramas fechados en el mismo instante).
        if x[-1] > x[0]:
            self.ax.set_xlim(x[0], x[-1])

        # Recalcular solo el eje Y. visible_only=True porque relim() cuenta por
        # defecto las líneas ocultas: sin esto, esconder la secundaria dejaría
        # el eje estirado por ella (IR Ambient ~25 °C vs primario ~95 °C).
        self.ax.relim(visible_only=True)
        self.ax.autoscale_view(scalex=False, scaley=True)

        # Eje Y fijo
        # self.ax.set_ylim(19, 105)

        self.canvas.draw_idle()

    def update_graph_photodetector(self):
        if self.canvas is None or not hasattr(self, "line_photo"):
            return
        n = len(self.data_photodetector)
        if n == 0:
            return
        x = list(range(1, n + 1))
        y = list(self.data_photodetector)
        self.line_photo.set_xdata(x)
        self.line_photo.set_ydata(y)
        self.ax_photo.set_xlim(0.5, max(n + 0.5, 1.5))
        ymin, ymax = min(y), max(y)
        margin = max(0.0001, (ymax - ymin) * 0.1)
        self.ax_photo.set_ylim(ymin - margin, ymax + margin)
        self.canvas.draw_idle()

    def _cadence_meta(self):
        """Pares de la cadencia real de muestreo, para la hoja de metadata.

        La cadencia no es un parámetro del host: la fija el firmware del disco
        (sample_ms) y la degradan las pérdidas del broadcast UDP — el cliente
        descarta datagramas viejos a propósito (SO_RCVBUF chico en ClientUDP).
        Se mide de la propia serie y se archiva pegada al dato para no volver a
        suponerla. dt_max es el que delata stalls largos: si sale en segundos,
        hay huecos reales en la curva y toca revisar el buffer de recepción.
        """
        t = self.data_time
        if len(t) < 2:
            return [("n", len(t))]
        deltas = sorted(t[i + 1] - t[i] for i in range(len(t) - 1))
        dt_mean = (t[-1] - t[0]) / (len(t) - 1)
        p95 = deltas[min(len(deltas) - 1, int(0.95 * len(deltas)))]
        return [
            ("dt_mean", round(dt_mean, 4)),
            ("dt_p95", round(p95, 4)),
            ("dt_max", round(deltas[-1], 4)),
            ("n", len(t)),
            ("span", round(t[-1] - t[0], 1)),
        ]

    def _timeouts_meta(self):
        """Salvaguarda de fases para la hoja de metadata: config efectiva + cada
        timeout (ciclo, fase, duración/límite, temperatura alcanzada/objetivo).

        Archivar el límite junto a lo que de verdad tardó es lo que permite
        reajustar factor/piso con datos en vez de a ojo.
        """
        cfg = self.timeout_cfg
        events = "|".join(
            f"c{c} {code} {el:.1f}/{lim:.1f}s {temp:.1f}/{target:g}C"
            for c, code, el, lim, temp, target in self.phase_timeouts
        )
        # Frescura: config + último umbral efectivo (0 = no llegó a medirse cadencia).
        fc = self.fresh_cfg
        return [
            (
                "timeout_cfg",
                f"x{cfg['factor']:g} floor {cfg['floor_s']:g}s "
                f"{cfg['s_per_c']:g}s/C cool {cfg['cool_s_per_c']:g}s/C "
                f"stop +{self.cool_margin_c:g}C max_failed {cfg['max_failed']}",
            ),
            ("failed_cycles", "|".join(str(c) for c in self.failed_cycles) or "none"),
            ("timeouts", events or "none"),
            ("fresh", f"x{fc['factor']:g} cap {fc['cap_s']:g}s eff {self.fresh_age_s:.3f}s"),
        ]

    def _run_meta(self):
        """Metadata completa de la corrida: receta/config (fijada al arrancar) +
        lo medido al final (cómo terminó, cadencia, timeouts, frescura, adaptativo)."""
        return (
            list(self.meta_pairs)
            + [("end", self._run_end)]
            + self._cadence_meta()
            + self._timeouts_meta()
            + [("adaptive", self._adaptive_summary())]
        )

    def save_data_temps_file(self):
        """Guarda la corrida en UN libro ``<slug>_pcr_data_<ts>.xlsx`` (hojas
        metadata, settings, temperature, photodetector, photodetector_raw).

        Si el xlsx falla (openpyxl ausente en el Pi, error de escritura) se cae a
        los 3 CSV de siempre para no perder una corrida de una hora; tools/
        csv_to_xlsx.py los convierte después. Devuelve el mensaje para la UI (no
        toca Tk: se llama también desde el hilo del experimento).
        """
        from itertools import zip_longest

        # Prefijo con el nombre del protocolo (proyecto PCR activo) saneado.
        slug = _project_slug(self.active_project_name)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_dir = experiment_dir("pcr")
        meta = self._run_meta()
        # Seis columnas alineadas por muestra: [primario, secundario, t_s, cycle,
        # phase, heater_on_s]. Se anexan juntas en update_displayed_temperature;
        # zip_longest cubre un desfase de a lo más una muestra si el paro cayó entre
        # los append. El loader del análisis lee las cols 0–2 por posición, así que
        # agregar columnas al final es seguro.
        temp_rows = [
            [
                p,
                s,
                round(t, 4) if t is not None else None,
                c,
                ph,
                round(h, 4) if h is not None else None,
            ]
            for p, s, t, c, ph, h in zip_longest(
                self.data_temperature,
                self.data_temperature_secondary,
                self.data_time,
                self.data_cycle,
                self.data_phase,
                self.data_heater_on,
            )
        ]
        # timeouts: fases abandonadas por la salvaguarda en el ciclo de esa lectura
        # ("high_ramp|cooling"; vacía = ciclo limpio). Fila k = ciclo k, la última =
        # lectura final. El loader del análisis lee solo la columna photodetector.
        photo_rows = [
            [k, phot, tos or None]
            for k, (phot, tos) in enumerate(
                zip_longest(self.data_photodetector, self.data_photo_timeouts), start=1
            )
        ]
        # Serie temporal cruda en formato largo (una fila por muestra)
        raw_rows = [
            [cycle, round(t_rel, 3), int(light_on), voltage]
            for cycle, samples in enumerate(self.data_photodetector_series, start=1)
            for t_rel, light_on, voltage in samples
        ]
        filename = f"{save_dir}/{slug}_pcr_data_{ts}.xlsx"
        try:
            write_workbook(
                filename,
                {
                    "metadata": kv_rows(meta),
                    "settings": kv_rows(flatten_settings(self.run_settings)),
                    "temperature": [self.temp_cols] + temp_rows,
                    "photodetector": [["cycle", "photodetector", "timeouts"]] + photo_rows,
                    "photodetector_raw": [["cycle", "t_rel_s", "light_on", "voltage"]] + raw_rows,
                },
            )
        except Exception as e:
            print(f"xlsx save failed ({e}); falling back to CSV")
            try:
                self._save_csv_fallback(save_dir, slug, ts, meta, temp_rows, photo_rows, raw_rows)
            except Exception as e2:
                print(f"CSV fallback failed: {e2}")
                return f"Error: data NOT saved (xlsx: {e}; csv: {e2})"
            return f"Saved as CSV in {save_dir} (xlsx failed: {e})"
        print(f"Data saved to {filename}")
        return f"Data saved to {os.path.basename(filename)}"

    @staticmethod
    def _save_csv_fallback(save_dir, slug, ts, meta, temp_rows, photo_rows, raw_rows):
        """Respaldo: los 3 CSV del formato anterior (metadata en una celda)."""
        import csv

        def blank(v):
            return "" if v is None else v

        with open(f"{save_dir}/{slug}_temperature_data_{ts}.csv", "w", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(["-".join(f"{k}: {v}" for k, v in meta)])
            writer.writerows([blank(v) for v in row] for row in temp_rows)
        with open(f"{save_dir}/{slug}_photodetector_data_{ts}.csv", "w", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(["photodetector", "timeouts"])
            writer.writerows([blank(phot), blank(tos)] for _k, phot, tos in photo_rows)
        with open(f"{save_dir}/{slug}_photodetector_raw_{ts}.csv", "w", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(["cycle", "t_rel_s", "light_on", "voltage"])
            writer.writerows(raw_rows)

    def _on_save_button(self):
        self.svar_status.set(self.save_data_temps_file())

    def _ensure_ads(self) -> bool:
        if self.ads is not None:
            return True
        from templates.constants import secrets

        if secrets.get("environment", "") == "dev":
            return False
        try:
            settings = read_settings_from_file()
            ads_fsr = float(settings.get("ads_fsr", 1.024))
            from Drivers.ReaderADS import Ads1115Reader

            self.ads = Ads1115Reader(address=0x48, fsr=ads_fsr, sps=64, single_shot=False)
            return True
        except Exception as e:
            print(f"ADS init failed: {e}")
            return False

    def callback_start_experiment(self):
        if self.running_experiment:
            # Con la UI ya restaurada solo pasa si el hilo anterior no terminó
            # (PCR_STOP_GIVEUP_S): no arrancar otro encima del que sigue vivo.
            if not self._ui_poll_active:
                self.svar_status.set(
                    "The previous run is still finishing; try again or restart the app"
                )
            return
        if not self._ensure_ads():
            self.svar_status.set("Error: ADS1115 not available")
            return
        self.running_experiment = True
        # Fuente de temperatura bloqueada mientras corre (cambiar de sensor a mitad
        # de un experimento cambiaría el setpoint efectivo del PID). Se relee por si
        # el selector cambió sin disparar el evento.
        if self.cbo_temp_source is not None:
            self.temp_source = temp_source_key(self.cbo_temp_source.get())
            self.temp_source_idx = temp_source_index(self.temp_source)
            self.temp_source_bad = False
            self.cbo_temp_source.configure(state=ttk.DISABLED)
        # Auto-snapshot de las settings que se van a correr: «Última corrida»
        # siempre refleja lo último ejecutado, aunque no se guardara con nombre.
        pcrp.snapshot_last_run(self._entries_to_dict())
        # hide entries frame + barra de proyecto (no hay nada que hacer con ellas
        # mientras corre; el proyecto activo se muestra en svar_status).
        self.frame_entries.grid_forget()
        self.frame_project.grid_forget()
        print("Experimento iniciado")
        # retrieve data from entries
        high_temp = float(self.entries[0].get())
        low_temp = float(self.entries[1].get())
        time_high = float(self.entries[2].get())
        time_low = float(self.entries[3].get())
        cycles = int(self.entries[4].get())
        rpm = float(self.entries[5].get())
        denat_time = float(self.entries[6].get())
        denat_temp = float(self.entries[7].get())
        ext_time = float(self.entries[8].get())
        ext_temp = float(self.entries[9].get())
        ext_time_final = float(self.entries[10].get())
        initia_spin_time = float(self.entries[11].get())

        msg = (
            f"High Temp: {high_temp}, Low Temp: {low_temp}, Time High: {time_high},"
            f" Time Low: {time_low}, Cycles: {cycles}, RPM: {rpm}",
            f"Denaturing Time: {denat_time}, Denaturing Temp: {denat_temp},"
            f" initial spin {initia_spin_time} s",
        )
        print(msg)
        # Origen único del eje temporal (plot, label de estado y estimación de
        # tiempo restante comparten este reloj). Se fija AQUÍ, en el hilo principal
        # y antes de que existan el hilo del experimento y el cliente UDP: si se
        # fijara dentro de experiment_pcr —que arranca el cliente antes— un
        # datagrama que llegara en esa ventana se fecharía contra el origen de la
        # corrida anterior y dejaría un punto a miles de segundos, ya grabado en
        # el CSV. Ver docs/pcr_eje_tiempo.md.
        self.start_pcr_time = time.time()
        # Una lectura por corrida (no en el watchdog, que corre a ritmo de UI): un
        # cambio en el ConfigFrame aplica a partir de la siguiente corrida.
        self.temp_dead_s = _read_temp_dead_s()
        print(f"Temp watchdog window: {self.temp_dead_s} s")
        self.init_temperature_graph()
        self._ui_poll_graph_counter = 0
        self._save_note = ""  # no arrastrar el de una corrida anterior
        self._run_end = ""
        self._run_started = False
        self._run_closing = False
        self._stop_requested_at = 0.0
        self._stop_reason = ""
        self._stop_forced = False
        self._photo_plotted_n = 0
        # Eventos nuevos en cada corrida: un aborto (watchdog, timeouts) los deja
        # activados y la corrida siguiente los heredaba, con lo que paraba al arrancar.
        self.stop_udp_listenner = threading.Event()
        self.stop_event_motor = threading.Event()
        self._ui_poll_active = True
        self._poll_after_id = self.after(500, self._ui_poll_loop)  # pyrefly: ignore
        # Aquí y no al poner running_experiment: si leer las entradas fallara, las
        # tabs no quedan bloqueadas. Se desbloquea en _restore_input_ui.
        self._set_tabs_locked(True)
        self.thread_experiment = threading.Thread(  # pyrefly: ignore
            target=self.experiment_pcr,
            args=(
                high_temp,
                low_temp,
                time_high,
                time_low,
                rpm,
                denat_time,
                denat_temp,
                cycles,
                self.ads,
                ext_time,
                ext_temp,
                ext_time_final,
                initia_spin_time,
            ),
        )
        self.thread_experiment.start()  # pyrefly: ignore

    def hold_temperature(
        self,
        temp_setpoint,
        time_hold,
        ts,
        stop_func,
        pin_heating,
        KI,
        I_MAX,
        KP_HOLD,
        TEMP_BAND,
        WINDOW,
    ):
        MAX_TEMP_AGE = ts  # si es más vieja → no confiar (piso; ver _note_rx)
        integral = 0.0
        start_time = time.time()
        while time.time() - start_time <= time_hold and not stop_func.is_set():
            # Verificar edad de la temperatura contra el umbral efectivo: el piso
            # absoluto o 1.5× la cadencia medida, lo mayor (se relee cada vuelta:
            # la cadencia puede cambiar a mitad del hold).
            temp_age = time.time() - self.temp_ts
            if temp_age > max(MAX_TEMP_AGE, self.fresh_age_s):
                # Temperatura vieja → apagar por seguridad
                pin_heating.write(False)
                time.sleep(WINDOW / 2)
                continue
            temp = self.temp
            # Banda muerta mínima para evitar chatter
            error = temp_setpoint - temp
            kp_dyn, ki_dyn = _fuzzy_gains(error, KP_HOLD, KI)
            integral += error * WINDOW
            integral = max(-I_MAX, min(I_MAX, integral))
            if abs(error) < TEMP_BAND:
                power = 0.0
            else:
                power = kp_dyn * error + ki_dyn * integral
            # Saturar potencia
            power = max(0.0, min(1.0, power))
            on_time = power * WINDOW
            off_time = WINDOW - on_time
            if on_time > 0:
                pin_heating.write(True)
                end_on = time.time() + on_time
                while time.time() < end_on:
                    if stop_func.is_set():
                        break
                    time.sleep(WINDOW / 10)
            pin_heating.write(False)
            # Tiempo OFF (permite disipar energía)
            end_off = time.time() + off_time
            while time.time() < end_off:
                if stop_func.is_set():
                    break
                time.sleep(WINDOW / 10)

    def _load_phase_pid(self, phase, ts):
        # Lee parámetros de la fase desde settings.json en cada llamada,
        # para que ediciones de ganancias durante el experimento tomen efecto.
        settings = read_settings_from_file()
        pid = settings.get("pidControllerRPM", {})
        return {
            "KP": pid.get(f"KP_{phase}", 0.15),
            "KI": pid.get(f"KI_{phase}", 0.5),
            "I_MAX": pid.get(f"imax_{phase}", 0.5),
            "TEMP_BAND": pid.get(f"tband_{phase}", 0.05),
            "WINDOW": pid.get(f"win_{phase}", ts * 0.9),
            "MAX_AGE": pid.get(f"m_age_{phase}", 0.09),
            # Límites de la edad-máxima dinámica (fuzzy) usada solo en la rampa.
            # m_age_max cae al viejo m_age_<phase> si no hay clave nueva.
            "MAX_AGE_MIN": pid.get(f"m_age_min_{phase}", 0.02),
            "MAX_AGE_MAX": pid.get(f"m_age_max_{phase}", pid.get(f"m_age_{phase}", 0.2)),
            # Fracción del setpoint hasta la que se hace feed-forward a potencia
            # plena antes de entregar el control al PI. 0.0 = sin pre-rampa.
            "FF_FRAC": pid.get(f"ff_frac_{phase}", 0.0),
        }

    def _phase_deadline(self, est_s):
        """(t_inicio, deadline, límite) de una fase que espera una temperatura.

        límite = max(piso, factor × estimado). Con factor 0 la salvaguarda está
        desactivada y deadline es None (la fase espera sin límite, como antes).
        """
        cfg = self.timeout_cfg
        t0 = time.time()
        if cfg["factor"] <= 0:
            return t0, None, None
        limit = max(cfg["floor_s"], cfg["factor"] * est_s)
        return t0, t0 + limit, limit

    def _record_timeout(self, code, t0, limit, target):
        """Registra una fase abandonada; el ciclo en curso cuenta como fallido."""
        elapsed = time.time() - t0
        self.phase_timeouts.append((self.cycle_current, code, elapsed, limit, self.temp, target))
        self._cycle_timeouts.append(code)
        print(
            f"Phase timeout: {code} (cycle {self.cycle_current}) {elapsed:.1f}s > "
            f"{limit:.1f}s at {self.temp:.1f} °C (target {target} °C) — skipping to next phase"
        )

    def _reach_phase(self, code, setpoint, pid_phase, ts, break_if_below):
        """Rampa de calentamiento (denat/high/ext_ramp) con salvaguarda de tiempo.

        El estimado sale del salto REAL al entrar a la fase (no del nominal): si
        la fase anterior se abandonó y el disco quedó lejos, el plazo crece con
        él. Si vence, se sigue al hold, que continúa empujando hacia el setpoint
        durante su propio tiempo.
        """
        self._enter_phase(code)
        est = abs(setpoint - self.temp) * self.timeout_cfg["s_per_c"]
        t0, deadline, limit = self._phase_deadline(est)
        if self.adapt_cfg["enabled"]:
            reached = self._ramp_adaptive(setpoint, pid_phase, ts, break_if_below, deadline)
        else:
            self.pin_heating.write(True)  # pyrefly: ignore
            reached = self._reach_temperature_pi(
                setpoint,
                self._load_phase_pid(pid_phase, ts),
                self.stop_udp_listenner,
                break_if_below=break_if_below,
                tolerance=0.5,
                deadline=deadline,
            )
        if not reached:
            self._record_timeout(code, t0, limit, setpoint)
        elif not self.stop_udp_listenner.is_set():  # pyrefly: ignore
            print(f"Temperature reached: {self.temp} °C")

    def _reach_temperature_pi(
        self, setpoint, params, stop_event, break_if_below=False, tolerance=0.5, deadline=None
    ):
        # Rampa PI hacia setpoint con anti-windup y descarte de temperatura vieja.
        # El heater debe estar pre-armado por el caller; este método modula on/off.
        # deadline (time.time() absoluto, None = sin límite): si vence, apaga el
        # heater y devuelve False. True en cualquier otro final (llegó o stop).
        KP = params["KP"]
        KI = params["KI"]
        I_MAX = params["I_MAX"]
        TEMP_BAND = params["TEMP_BAND"]
        WINDOW = params["WINDOW"]
        MAX_AGE_MIN = params["MAX_AGE_MIN"]
        MAX_AGE_MAX = params["MAX_AGE_MAX"]
        FF_FRAC = params.get("FF_FRAC", 0.0)

        # ----- Pre-rampa feed-forward (mismo principio que la desnaturalización):
        # calienta a potencia plena hasta FF_FRAC*setpoint y luego entrega el
        # control al PI para asentar sin sobreimpulso. Se omite cuando venimos
        # ya calientes (break_if_below, p. ej. ciclo 0 tras el hold de denat).
        # A diferencia de la rampa de denaturación, aquí el blast también
        # descarta temperatura vieja: si la lectura UDP envejece, apaga el
        # heater y re-arma en cada lectura fresca para evitar runaway térmico.
        #
        # Ambos lazos chequean el mismo deadline (un reloj por fase), y sus ramas
        # sin trabajo duermen PCR_POLL_S: antes giraban sin pausa (un núcleo al
        # 100 % durante el blast, y también mientras la lectura estaba vieja).
        if FF_FRAC > 0.0 and not break_if_below:
            ceiling = setpoint * FF_FRAC
            while self.temp < ceiling and not stop_event.is_set():
                if deadline is not None and time.time() > deadline:
                    self.pin_heating.write(False)  # pyrefly: ignore
                    return False
                age = time.time() - self.temp_ts
                max_age = max(
                    _fuzzy_max_age(setpoint - self.temp, MAX_AGE_MIN, MAX_AGE_MAX),
                    self.fresh_age_s,
                )
                if age > max_age:
                    # Temperatura vieja → no confiar; corta y reintenta.
                    self.pin_heating.write(False)  # pyrefly: ignore
                    time.sleep(PCR_POLL_S)
                    continue
                self.pin_heating.write(True)  # pyrefly: ignore
                time.sleep(PCR_POLL_S)

        integral = 0.0
        while tolerance < abs(setpoint - self.temp) and not stop_event.is_set():
            if deadline is not None and time.time() > deadline:
                self.pin_heating.write(False)  # pyrefly: ignore
                return False
            if break_if_below and self.temp < setpoint:
                break
            age = time.time() - self.temp_ts
            error = setpoint - self.temp
            if age > max(_fuzzy_max_age(error, MAX_AGE_MIN, MAX_AGE_MAX), self.fresh_age_s):
                # Temperatura vieja → no confiar
                self.pin_heating.write(False)  # pyrefly: ignore
                time.sleep(PCR_POLL_S)
                continue
            kp_dyn, ki_dyn = _fuzzy_gains(error, KP, KI)
            integral += error * WINDOW
            integral = max(-I_MAX, min(I_MAX, integral))
            if abs(error) < TEMP_BAND:
                power = 0.0
            else:
                power = kp_dyn * error + ki_dyn * integral
            power = max(0.0, min(1.0, power))
            on_time = power * WINDOW
            if on_time > 0:
                self.pin_heating.write(True)  # pyrefly: ignore
                time.sleep(on_time)
            self.pin_heating.write(False)  # pyrefly: ignore
            time.sleep(WINDOW - on_time)
        return True

    def _pwm_window(self, power, window):
        """Una ventana de PWM del heater: encendido power·window, apagado el resto."""
        pin = self.pin_heating
        stop = self.stop_udp_listenner
        if pin is None or stop is None:
            return
        on_time = max(0.0, min(1.0, power)) * window
        if on_time > 0:
            pin.write(True)
            end_on = time.time() + on_time
            while time.time() < end_on and not stop.is_set():
                time.sleep(window / 10)
        pin.write(False)
        end_off = time.time() + (window - on_time)
        while time.time() < end_off and not stop.is_set():
            time.sleep(window / 10)

    def _adapt_bias_for(self, key, setpoint):
        """Duty de régimen de un hold: el aprendido en esta corrida o el modelo inicial."""
        cfg = self.adapt_cfg
        bias = self._adapt_bias.get(key)
        if bias is None:
            bias = cfg["ff_slope"] * (setpoint - cfg["ff_t0"])
        return max(0.0, min(1.0, bias))

    def _ramp_adaptive(self, setpoint, pid_phase, ts, break_if_below, deadline):
        """Rampa del control adaptativo. True si terminó (pico o stop), False si venció.

        1) Potencia plena hasta setpoint − calor en vuelo aprendido para esta rampa,
           con el mismo descarte de lectura vieja que el blast clásico.
        2) Corte: solo el feed-forward del hold siguiente (apagar del todo haría caer
           la temperatura tras el pico: a 90 °C se pierden ~2.7 °C/s) mientras dure la
           subida RÁPIDA, la del calor en vuelo. Termina cuando la temperatura baja del
           máximo, cuando la subida cae de PCR_ADAPT_RISE_END_CPS, o a coast_window_s.
           El resto del acercamiento lo hace el hold, cuyo P empuja más que el
           feed-forward solo.
        Aprendizaje: si hubo potencia plena suficiente, coast += coast_learn·(máximo de
        la subida rápida − setpoint): pasarse adelanta el corte y quedarse corto lo
        atrasa. Absorbe también el desfase sistemático de corte (ráfagas, EMA). Tiene
        que ser el máximo de la subida RÁPIDA: con el feed-forward encendido la
        temperatura sigue subiendo despacio hasta el setpoint, así que con el pico
        completo un corte demasiado temprano también "acertaba", y el aprendizaje
        quedaba clavado en coast_max (verificado en simulación). El paso se limita a
        coast_step_max, y una rampa con una subida imposible para el heater (jump_cps:
        salto del termopar) no enseña.
        """
        cfg = self.adapt_cfg
        pin = self.pin_heating
        stop = self.stop_udp_listenner
        if pin is None or stop is None:
            return True
        if break_if_below and self.temp < setpoint:
            return True  # como el clásico: venimos calientes del hold de denat
        params = self._load_phase_pid(pid_phase, ts)
        seed = cfg["coast_init"] if pid_phase == "denat" else cfg["coast_init_cycle"]
        coast = self._adapt_coast.get(pid_phase, min(cfg["coast_max"], max(cfg["coast_min"], seed)))
        t_full = time.time()
        seen: deque = deque()  # (temp_ts, temp) de las lecturas recientes, para la tasa
        max_rate = 0.0  # subida más rápida vista en la rampa (°C/s), para detectar saltos
        while not stop.is_set():
            now = time.time()
            if deadline is not None and now > deadline:
                pin.write(False)
                return False
            if not seen or seen[-1][0] != self.temp_ts:
                seen.append((self.temp_ts, self.temp))
                while self.temp_ts - seen[0][0] > PCR_ADAPT_RATE_WIN_S:
                    seen.popleft()
            # Las lecturas llegan en ráfagas cada ~0.27 s y a ~10 °C/s cada una salta
            # ~3 °C: sin extrapolar, el corte llega una ráfaga tarde.
            span = seen[-1][0] - seen[0][0]
            rate = (seen[-1][1] - seen[0][1]) / span if span >= PCR_ADAPT_RATE_MIN_SPAN_S else 0.0
            if span >= PCR_ADAPT_JUMP_SPAN_S:
                max_rate = max(max_rate, rate)
            y_est = self.temp + max(0.0, rate) * min(max(now - self.temp_ts, 0.0), 0.5)
            if y_est >= setpoint - coast:
                break
            max_age = max(
                _fuzzy_max_age(setpoint - self.temp, params["MAX_AGE_MIN"], params["MAX_AGE_MAX"]),
                self.fresh_age_s,
            )
            pin.write(now - self.temp_ts <= max_age)  # lectura vieja → apagado
            time.sleep(PCR_POLL_S)
        full_s = time.time() - t_full
        y_cut = y_max = self.temp
        t_cut = time.time()
        bias = self._adapt_bias_for("h_" + pid_phase, setpoint)
        recent: deque = deque()  # (t, temp) de la última PCR_ADAPT_RATE_WIN_S
        while not stop.is_set():
            now = time.time()
            if deadline is not None and now > deadline:
                pin.write(False)
                return False
            y = self.temp
            y_max = max(y_max, y)
            recent.append((now, y))
            while now - recent[0][0] > PCR_ADAPT_RATE_WIN_S:
                recent.popleft()
            rate = (y - recent[0][1]) / max(now - recent[0][0], 1e-3)
            if now - recent[0][0] >= PCR_ADAPT_JUMP_SPAN_S:
                max_rate = max(max_rate, rate)
            slow = now - t_cut >= PCR_ADAPT_RATE_WIN_S and rate < PCR_ADAPT_RISE_END_CPS
            if y_max - y >= PCR_ADAPT_PEAK_DROP_C or slow or now - t_cut >= cfg["coast_window_s"]:
                break
            self._pwm_window(bias, cfg["hold_win"])
        pin.write(False)
        if (full_s >= PCR_ADAPT_MIN_FULL_S or y_max < setpoint) and not stop.is_set():
            head = f"Adaptive {pid_phase} ramp: cut at {y_cut:.1f} °C (coast {coast:.1f}), peak {y_max:.1f} °C"
            if cfg["jump_cps"] > 0 and max_rate > cfg["jump_cps"]:
                # El termopar saltó (subida que el heater no puede dar): el pico no es
                # de la muestra y enseñaría un corte equivocado.
                self._adapt_coast[pid_phase] = coast
                print(f"{head}, rise {max_rate:.0f} °C/s (thermocouple jump) → coast kept")
                return True
            step = cfg["coast_learn"] * (y_max - setpoint)
            if cfg["coast_step_max"] > 0:
                step = max(-cfg["coast_step_max"], min(cfg["coast_step_max"], step))
            self._adapt_coast[pid_phase] = min(cfg["coast_max"], max(cfg["coast_min"], coast + step))
            print(f"{head} → coast {self._adapt_coast[pid_phase]:.1f} °C")
        return True

    def _hold_adaptive(self, key, setpoint, duration, ts):
        """Hold del control adaptativo: feed-forward + PI suave, y aprende el duty.

        Dentro de la banda se mantiene feed-forward + I (el clásico fuerza 0). El duty
        aprendido es el que mide el _HeaterMeter en la segunda mitad del hold, y solo
        si la temperatura estuvo cerca del setpoint: un hold pasado de temperatura mide
        0, y eso no es el duty de régimen.
        """
        cfg = self.adapt_cfg
        pin = self.pin_heating
        stop = self.stop_udp_listenner
        if pin is None or stop is None:
            return
        bias = self._adapt_bias_for(key, setpoint)
        window = cfg["hold_win"]
        integ = 0.0
        t0 = time.time()
        mid: "tuple | None" = None  # (instante, heater_on_s) al pasar la mitad
        err_sum, err_n = 0.0, 0
        while time.time() - t0 <= duration and not stop.is_set():
            now = time.time()
            if mid is None and now >= t0 + duration / 2:
                mid = (now, pin.on_s(now))
            if now - self.temp_ts > max(ts, self.fresh_age_s):
                pin.write(False)  # temperatura vieja → apagar por seguridad
                time.sleep(window / 2)
                continue
            error = setpoint - self.temp
            if mid is not None:
                err_sum += error
                err_n += 1
            kp_dyn, ki_dyn = _fuzzy_gains(error, cfg["hold_kp"], cfg["hold_ki"])
            integ = max(-cfg["hold_imax"], min(cfg["hold_imax"], integ + error * window))
            p_term = 0.0 if abs(error) < cfg["hold_tband"] else kp_dyn * error
            power = bias + ki_dyn * integ + p_term
            if cfg["hold_pmax"] > 0:  # freno: sin él, un corte temprano se pasaba
                power = min(power, bias + cfg["hold_pmax"])
            self._pwm_window(power, window)
        pin.write(False)
        if mid is None or err_n == 0 or stop.is_set() or cfg["ff_learn"] <= 0:
            return
        t_end = time.time()
        span = t_end - mid[0]
        mean_err = err_sum / err_n
        if span >= PCR_ADAPT_LEARN_MIN_S and abs(mean_err) <= PCR_ADAPT_LEARN_MAX_ERR_C:
            duty = (pin.on_s(t_end) - mid[1]) / span
            self._adapt_bias[key] = (1 - cfg["ff_learn"]) * bias + cfg["ff_learn"] * duty
            print(f"Adaptive {key}: duty {duty:.3f} (mean err {mean_err:+.2f} °C) → bias {self._adapt_bias[key]:.3f}")
        else:
            print(f"Adaptive {key}: duty not learned (mean err {mean_err:+.2f} °C over {span:.1f} s)")

    def _adaptive_summary(self):
        """Control adaptativo para la metadata: off, o la config y lo aprendido al final."""
        cfg = self.adapt_cfg
        if not cfg["enabled"]:
            return "off"
        bias = " ".join(f"{k} {v:.3f}" for k, v in sorted(self._adapt_bias.items())) or "none"
        coast = " ".join(f"{k} {v:.1f}" for k, v in sorted(self._adapt_coast.items())) or "none"
        return (
            f"on ff {cfg['ff_slope']:g}/{cfg['ff_t0']:g}C learn {cfg['ff_learn']:g}"
            f" hold kp {cfg['hold_kp']:g} ki {cfg['hold_ki']:g} imax {cfg['hold_imax']:g}"
            f" pmax {cfg['hold_pmax']:g}"
            f" coast init {cfg['coast_init']:g}/{cfg['coast_init_cycle']:g}C learn {cfg['coast_learn']:g}"
            f" step {cfg['coast_step_max']:g}C jump {cfg['jump_cps']:g}C/s"
            f" | bias {bias} | coast {coast}"
        )

    def _hold_phase(self, phase, setpoint, duration, ts):
        if self.adapt_cfg["enabled"]:
            self._hold_adaptive(phase, setpoint, duration, ts)
            return
        params = self._load_phase_pid(phase, ts)
        self.hold_temperature(
            setpoint,
            duration,
            ts,
            self.stop_udp_listenner,
            self.pin_heating,
            params["KI"],
            params["I_MAX"],
            params["KP"],
            params["TEMP_BAND"],
            params["WINDOW"],
        )
        self.pin_heating.write(False)  # pyrefly: ignore

    def _read_fluorescence(self, ads):
        # Muestreo continuo del fotodetector mientras se modula la luz (pin_pcr):
        #   baseline_s  -> luz OFF (línea base oscura)
        #   light_s     -> luz ON  (excitación)
        #   post_s      -> luz OFF (decaimiento)
        # Acumula la serie temporal cruda y agrega el escalar
        #   delta = media(ventana con luz) - media(ventana baseline)
        # a data_photodetector (plot por-ciclo). Soporta lectura diferencial.
        # Ventanas y muestreo salen de self.fluor_cfg (una lectura por corrida):
        # todas las lecturas de una corrida usan los mismos, aunque se edite
        # settings.json.
        baseline_s = self.fluor_cfg["baseline_s"]
        light_s = self.fluor_cfg["light_s"]
        post_s = self.fluor_cfg["post_s"]
        sample_dt = self.fluor_cfg["sample_dt_s"]
        averages = self.fluor_cfg["averages"]
        settings = read_settings_from_file()
        use_diff = settings.get("photoreceptor", {}).get("use_diff", False)

        # (t_rel, light_on, voltage) por muestra
        samples = []

        def read_one():
            if use_diff:
                return ads.read_voltage_diff(0, 1, averages=averages)
            return ads.read_voltage(0, averages=averages)

        def sample_window(duration, light_on, t0):
            # Muestrea durante `duration` segundos a ~sample_dt, paceando por
            # tiempo transcurrido. Devuelve True si se abortó (stop).
            t_end = time.time() + duration
            while time.time() < t_end:
                if self.stop_udp_listenner is not None and self.stop_udp_listenner.is_set():
                    return True
                t_iter = time.time()
                v = read_one()
                samples.append((t_iter - t0, light_on, v))
                elapsed = time.time() - t_iter
                if elapsed < sample_dt:
                    time.sleep(sample_dt - elapsed)
            return False

        t0 = time.time()
        try:
            self.pin_pcr.write(False)  # pyrefly: ignore
            aborted = sample_window(baseline_s, 0, t0)
            if not aborted:
                self.pin_pcr.write(True)  # pyrefly: ignore
                aborted = sample_window(light_s, 1, t0)
            if not aborted:
                self.pin_pcr.write(False)  # pyrefly: ignore
                sample_window(post_s, 0, t0)
        finally:
            self.pin_pcr.write(False)  # pyrefly: ignore

        baseline_vals = [v for (_, light_on, v) in samples if light_on == 0 and _ < baseline_s]
        light_vals = [v for (_, light_on, v) in samples if light_on == 1]
        mean_baseline = sum(baseline_vals) / len(baseline_vals) if baseline_vals else 0.0
        mean_light = sum(light_vals) / len(light_vals) if light_vals else 0.0
        delta = mean_light - mean_baseline

        # Acumulación (fuente única de verdad)
        self.data_photodetector.append(delta)
        self.data_photodetector_series.append(samples)
        # Ancla para estadística: fases abandonadas en el ciclo de esta lectura.
        self.data_photo_timeouts.append("|".join(self._cycle_timeouts))
        # La gráfica la refresca _ui_poll_loop: este hilo no toca Tk.
        return delta

    def _run_cycle(
        self,
        idx,
        high_temp,
        low_temp,
        time_high,
        time_low,
        rpm,
        direction,
        acceleration,
        ts,
        ext_time,
        ext_temp,
        ads,
        denat_skipped=False,
    ):
        global sistemaMotor
        from Drivers.DriverStepperSys import spinMotorRPM_ramped

        if self.stop_udp_listenner is None:
            self.stop_udp_listenner = threading.Event()
        self.start_cycle_time = time.time()
        # Columna cycle del CSV: 1-based, igual que photodetector_raw y que la
        # fila k del photodetector_data (lectura de fin del ciclo k).
        self.cycle_current = idx + 1
        # Timeouts de ESTE ciclo (un timeout de denat_ramp no cuenta para el 1).
        self._cycle_timeouts = []

        # Reach High temp: feed-forward a potencia plena hasta ff_frac_high*setpoint
        # y luego PI (tolerancia 0.5). En el ciclo 0 (break_if_below) se omite el
        # blast porque venimos del hold de denaturación ya en temperatura, salvo
        # que la desnaturalización se haya omitido (denat_skipped): en ese caso
        # arrancamos en frío y hay que alcanzar High de verdad.
        if not _skip(time_high):
            self._reach_phase(
                "high_ramp", high_temp, "high", ts, break_if_below=(idx == 0 and not denat_skipped)
            )

            # Hold High
            self._enter_phase("high_hold")
            print(f"Holding temperature for {time_high} seconds")
            self._hold_phase("h_high", high_temp, time_high, ts)
        else:
            print("Skipping High phase: time <= 0")

        # Cool down con giro del motor hacia la siguiente fase activa del ciclo.
        # Si Low se omite (time_low <= 0) se enfría hacia la extensión; si ambas
        # se omiten no hay nada que enfriar (la próxima fase es calentamiento).
        cool_target = (
            low_temp if not _skip(time_low) else (ext_temp if not _skip(ext_time) else None)
        )
        if cool_target is not None and self.temp > cool_target + 0.5:
            print(f"Cooling down to {cool_target} °C with motor spin")
            self._enter_phase("cooling")
            # Un solo reloj para giro + espera pasiva. Aquí casi nunca vence (solo
            # con un objetivo inalcanzable por mala configuración): es una red, no
            # el caso principal. Estimado por ΔT real, como las rampas (ver
            # PCR_COOL_S_PER_C: la fórmula por rpm de la preview se queda corta).
            t0, deadline, limit = self._phase_deadline(
                abs(self.temp - cool_target) * self.timeout_cfg["cool_s_per_c"]
            )

            def _expired():
                return deadline is not None and time.time() > deadline

            self.stop_event_motor.clear()  # pyrefly: ignore
            spinMotorRPM_ramped(
                direction,
                rpm,
                ts,
                acceleration,
                900.0,
                True,
                sistemaMotor,
                None,
                stop_func=lambda: self.stop_udp_listenner.is_set()  # pyrefly: ignore
                or self.temp <= cool_target
                or self.temp < cool_target + self.cool_margin_c
                or _expired(),
                stop_event=self.stop_event_motor,
            )

            print(self.temp, "cool target....dis")
            while (
                self.temp > cool_target + 0.5
                and not self.stop_udp_listenner.is_set()  # pyrefly: ignore
                and not _expired()
            ):
                time.sleep(PCR_POLL_S)
            if self.temp > cool_target + 0.5 and _expired():
                self._record_timeout("cooling", t0, limit, cool_target)
            else:
                print(f"Temperature reached: {self.temp} °C")

        # Hold Low
        if not _skip(time_low):
            self._enter_phase("low_hold")
            print(f"Holding LOW temperature for {time_low} seconds")
            self._hold_phase("h_low", low_temp, time_low, ts)
        else:
            print("Skipping Low phase: time <= 0")

        # Reach Ext temp (PI, tolerancia 0.5) + Hold Ext
        if not _skip(ext_time):
            # Sin break_if_below: a ext se llega desde low (debajo), así que en el
            # ciclo 1 la rampa salía de inmediato y el hold calentaba solo. Era una
            # copia del caso de high (que sí viene caliente del hold de denat),
            # presente desde antes del refactor de mayo; quitada el 13/10/2026.
            self._reach_phase("ext_ramp", ext_temp, "ext", ts, break_if_below=False)

            # Hold Ext
            self._enter_phase("ext_hold")
            print(f"Holding extension temperature for {ext_time} seconds")
            self._hold_phase("h_ext", ext_temp, ext_time, ts)
            print(f"Hold ext complete, end of cycle {idx}")
        else:
            print("Skipping Extension phase: time <= 0")

        # Lectura de fluorescencia. La fase se declara ANTES de la espera previa:
        # esos pre_sleep_s ya no son hold (el lazo terminó y la temperatura
        # deriva), y etiquetarlos ext_hold ensuciaría la estadística del hold.
        self._enter_phase("fluor_read")
        time.sleep(self.fluor_cfg["pre_sleep_s"])
        print("Reading fluorescence...")
        v_fluo = self._read_fluorescence(ads)
        print(f"fluorescence delta voltage: {v_fluo}")
        self.time_end_cycle = time.time()
        # Estadísticas para la estimación del tiempo restante
        self.last_cycle_duration = self.time_end_cycle - self.start_cycle_time
        self.cycles_complete = idx + 1
        self.avg_cycle_duration = (
            self.avg_cycle_duration * (self.cycles_complete - 1) + self.last_cycle_duration
        ) / self.cycles_complete
        # Racha de ciclos fallidos: un ciclo con algún timeout la alarga, uno limpio
        # la corta. Lo que importa es la racha (fallo persistente = problema real),
        # no el total: los fallos aislados se arreglan solos en el ciclo siguiente.
        if self._cycle_timeouts:
            self.failed_cycles.append(self.cycle_current)
            self.consec_failed_cycles += 1
        else:
            self.consec_failed_cycles = 0

    def experiment_pcr(self, *args):
        """Hilo del experimento (``args`` = los de ``_run_pcr``).

        Termine como termine la corrida —fin natural, Stop, aborto, excepción
        (incluso en la preparación) o cierre de la app— apaga el hardware PRIMERO,
        después guarda lo medido y al final pone ``running_experiment = False``, que
        es la señal para que ``_ui_poll_loop`` restaure la UI y muestre el resultado.
        Antes una excepción saltaba el guardado y la corrida se perdía entera. Nunca
        toca Tk. Ver docs/pcr_fin_corrida.md.
        """
        error = None
        try:
            self._run_pcr(*args)
        except Exception as e:
            print(f"exception in experiment: {e}")
            traceback.print_exc()
            error = e
        self._run_closing = True
        try:
            self._teardown_hardware()
            self._run_end = self._end_reason(error)
            print(f"PCR run end: {self._run_end}")
            note = self.save_data_temps_file() if self._run_started else ""
            self._save_note = self._end_note(note)
        except Exception as e:
            traceback.print_exc()
            self._save_note = f"Error closing the run: {e}"
        finally:
            self.running_experiment = False

    def _end_reason(self, error):
        """Cómo terminó la corrida (fila ``end`` de la metadata).

        Primero el motivo del paro pedido (Stop, cierre de la app, abortos del
        watchdog o de la salvaguarda), aunque luego salte una excepción: es
        consecuencia del paro (p. ej. el teardown forzado cerró un pin) y la traza
        queda en el log. aborted_start no pide paro: solo deja su fase.
        """
        if self._stop_reason:
            return self._stop_reason
        if self.phase_code.startswith("aborted"):
            return self.phase_code
        if error is not None:
            return f"error: {type(error).__name__}: {error}"
        return self.phase_code

    def _end_note(self, save_note):
        """Mensaje final para el status: cómo terminó + resultado del guardado."""
        end = self._run_end
        if end.startswith("error"):
            prefix = f"Run failed ({end[len('error: '):]}). "
        elif end == "stopped":
            prefix = "Stopped. "
        elif end.startswith("aborted") and end in PCR_PHASE_LABELS:
            # El State puede mostrar una fase posterior al aborto: decirlo aquí.
            prefix = f"{PCR_PHASE_LABELS[end]}. "
        else:
            prefix = ""
        if not prefix and not save_note:
            return ""
        return f"{prefix}{save_note or 'No data saved.'}"

    def _run_pcr(
        self,
        high_temp,
        low_temp,
        time_high,
        time_low,
        rpm,
        denat_time,
        denat_temp,
        cycles,
        ads,
        ext_time,
        ext_temp,
        ext_time_final,
        initial_spin_time,
    ):
        # Cuerpo de la corrida. El cierre (apagar, guardar, marcar el fin) es de
        # experiment_pcr: aquí no hay try/finally, una excepción simplemente sube.
        global thread_motor, sistemaMotor

        self.stop_udp_listenner = (
            threading.Event() if self.stop_udp_listenner is None else self.stop_udp_listenner
        )
        self.total_cycles = cycles
        self.cycles_complete = 0
        self.last_cycle_duration = 0.0
        self.avg_cycle_duration = 0.0
        self.ext_time_final = ext_time_final
        # Reset para esta corrida: se fija al iniciar la extensión final (más abajo).
        self.start_final_ext_time = 0.0

        settings = read_settings_from_file()
        # Snapshot de la configuración con la que corre (hoja "settings" del xlsx):
        # cada archivo dice con qué sintonización se midió.
        self.run_settings = settings
        pidGains = settings.get("pidControllerRPM", {})
        try:
            ts = float(pidGains.get("ts_pcr", 0.02))
        except Exception:
            ts = 0.02
        # Salvaguarda de fases, frescura y ventanas de fluorescencia: una lectura por
        # corrida (van a la metadata del CSV).
        self.timeout_cfg = _phase_timeout_cfg(pidGains)
        self.fresh_cfg = _freshness_cfg(pidGains)
        self.fluor_cfg = _fluor_cfg(settings.get("pcr_fluorescence", {}))
        self.cool_margin_c = _cfg_num(pidGains, "cool_stop_margin_c", PCR_COOL_STOP_MARGIN_C)
        self.adapt_cfg = _adaptive_cfg(settings.get("pcr_adaptive", {}))
        self._adapt_bias, self._adapt_coast = {}, {}  # disco nuevo → se aprende de cero
        # 0 no tiene sentido (abortaría si la primera lectura no llegó ya) → default.
        start_wait_s = (
            _cfg_num(pidGains, "temp_start_wait_s", PCR_TEMP_START_WAIT_S) or PCR_TEMP_START_WAIT_S
        )
        print(
            f"Phase timeout config: {self.timeout_cfg} | cool stop: +{self.cool_margin_c} C"
            f" | freshness: {self.fresh_cfg}"
            f" | start wait: {start_wait_s} s | fluorescence: {self.fluor_cfg}"
        )
        print(f"Adaptive control: {self.adapt_cfg if self.adapt_cfg['enabled'] else 'off'}")
        # ETA antes del primer ciclo: mismo modelo que la preview y la salvaguarda
        # (rampas y enfriamiento por ΔT). El anterior, holds × 1.2, ignoraba rampas y
        # enfriamiento y daba ~1.9 ks para Newn1 contra 3.27 ks reales. Desde el
        # primer ciclo la ETA pasa a la duración medida (_estimate_remaining_time).
        self.teorical_time_pcr = _estimate_total_s(
            high_temp,
            low_temp,
            ext_temp,
            time_high,
            time_low,
            ext_time,
            cycles,
            denat_temp,
            denat_time,
            ext_time_final,
            initial_spin_time,
            self.timeout_cfg,
            self.fluor_cfg["total_s"],
        )
        print(f"Estimated run time: {self.teorical_time_pcr / 60:.1f} min")

        # Nombre del proyecto activo para trazabilidad receta->datos. Si corrió con
        # entradas editadas a mano (snapshot implícito), se marca como sin guardar.
        if self.active_project_name in (None, pcrp.LAST_RUN_KEY):
            project_label = "_last_run (sin guardar)"
        else:
            project_label = self.active_project_name
        # Identidad de columnas de la hoja temperature: col0=primario, col1=secundario.
        primary_label = temp_source_label(self.temp_source)
        secondary_label = temp_source_label_by_index(self._secondary_idx())
        self.temp_cols = [primary_label, secondary_label, "t_s", "cycle", "phase", "heater_on_s"]
        fc = self.fluor_cfg
        # OJO: "ts" es el periodo del lazo PI, NO la cadencia de muestreo (esa la
        # manda el firmware del disco y ahora se mide: ver _cadence_meta).
        # "start" ancla el eje t_s —que es relativo— al reloj de pared, para poder
        # correlacionar esta corrida con otros logs sin pagar una columna por muestra.
        self.meta_pairs = [
            ("project", project_label),
            ("high_temp", high_temp),
            ("low_temp", low_temp),
            ("time_high", time_high),
            ("time_low", time_low),
            ("cycles", cycles),
            ("rpm", rpm),
            ("denat_temp", denat_temp),
            ("denat_time", denat_time),
            # La receta completa: sin estos, la extensión de Newn1 hubo que deducirla
            # de la curva (docs/pcr_pendientes.md punto 5).
            ("ext_temp", ext_temp),
            ("ext_time", ext_time),
            ("ext_time_final", ext_time_final),
            ("initial_spin", initial_spin_time),
            ("ts", ts),
            ("temp_source", primary_label),
            # Ventanas de fluorescencia efectivas (configurables en settings.json).
            ("fluor_pre_s", fc["pre_sleep_s"]),
            ("fluor_baseline_s", fc["baseline_s"]),
            ("fluor_light_s", fc["light_s"]),
            ("fluor_post_s", fc["post_s"]),
            ("fluor_sample_dt_s", fc["sample_dt_s"]),
            ("fluor_averages", fc["averages"]),
            ("start", datetime.fromtimestamp(self.start_pcr_time).isoformat(timespec="seconds")),
            ("cols", "|".join(self.temp_cols)),
        ]
        self.temp = 20.0
        self.client_temperature = UdpClient(
            port=5005,
            buffer_size=512,
            allow_broadcast=True,  # Important for broadcast payloads
            local_ip="",  # "" listens on all interfaces (wlan0, eth0, etc.)
            recv_timeout_sec=0.1,  # lets loop check stop flag periodically
            on_message=lambda t, a, t_d: self.update_displayed_temperature(t, a, t_d),
            parse_float=True,  # Arduino sends a numeric string,
            stop_event=self.stop_udp_listenner,
            save_data=False,
        )
        self.client_temperature.start()
        self._enter_phase("initial")
        from Drivers.DriverStepperSys import DriverStepperSys, spinMotorRPM_ramped

        # start_pcr_time NO se fija aquí: lo hace callback_start_experiment antes
        # de crear este hilo y el cliente UDP (ver allí el porqué).

        # Start-gate: no arrancar el ciclado si al inicio ninguno de los dos
        # sensores del par entrega lectura válida dentro de temp_start_wait_s.
        # El cliente UDP ya corre; esperamos a _temp_ever_valid (lo marca
        # update_displayed_temperature en la primera lectura buena). Al retornar
        # aquí, experiment_pcr desmonta el hardware (sin guardar: no hubo corrida) y
        # _ui_poll_loop restaura la UI.
        gate_deadline = time.time() + start_wait_s
        while not self._temp_ever_valid and time.time() < gate_deadline:
            if self.stop_udp_listenner.is_set():
                return
            time.sleep(0.05)
        if not self._temp_ever_valid:
            self._enter_phase("aborted_start")
            print("PCR not started: both pair sensors unavailable at start")
            return
        # Pasó el start-gate: desde aquí hay una corrida que guardar (experiment_pcr).
        self._run_started = True

        acceleration = float(pidGains.get("acceleration_spin", 200.0))
        direction = "CW"
        if sistemaMotor is None:
            print("Creating new driver instance")
            sistemaMotor = DriverStepperSys(
                en_pin=12, enable_active_high=False, uart_port=serial_port_encoder
            )

        self.stop_event_motor = (
            threading.Event() if self.stop_event_motor is None else self.stop_event_motor
        )

        # Spin inicial con tiempo específico
        spinMotorRPM_ramped(
            direction,
            rpm,
            ts,
            acceleration,
            900.0,
            True,
            sistemaMotor,
            time_exp=initial_spin_time,
            stop_func=lambda: self.stop_event_motor.is_set(),
            stop_event=self.stop_event_motor,
        )
        from Drivers.DriverGPIO import GPIOPin

        # Envuelto en _HeaterMeter: cada escritura se contabiliza para la
        # columna heater_on_s. Nunca escribir el GPIOPin crudo.
        self.pin_heating = _HeaterMeter(
            GPIOPin(
                led_heatin_pin,
                chip=chip_rasp,
                consumer="led-heating-ui",
                active_low=False,
            )
        )
        self.pin_pcr = GPIOPin(
            led_fluorescence_pin,
            chip=chip_rasp,
            consumer="test_pcr",
            active_low=False,
        )
        self.pin_pcr.set_output(initial_high=False)

        # ----- Denaturación: mismo principio que "Reach High temp":
        # feed-forward a potencia plena hasta ff_frac_denat*setpoint y luego PI
        # (ganancias difusas + anti-windup + descarte de temperatura vieja).
        # Si denat_time <= 0 se omite por completo (arrancamos en frío); en ese
        # caso el primer ciclo debe alcanzar High de verdad (denat_skipped).
        denat_skipped = _skip(denat_time)
        if not denat_skipped:
            self._reach_phase("denat_ramp", denat_temp, "denat", ts, break_if_below=False)

            # ----- Denaturation Hold
            self._enter_phase("denat_hold")
            self._hold_phase("h_denat", denat_temp, denat_time, ts)
            print(f"Denaturation complete, temperature: {self.temp} °C")
        else:
            print("Skipping Denaturation phase: time <= 0")

        # ----- Ciclos PCR
        for idx in range(cycles):
            if self.stop_udp_listenner.is_set():
                break
            print(f"start cycle {idx}")
            self._run_cycle(
                idx,
                high_temp,
                low_temp,
                time_high,
                time_low,
                rpm,
                direction,
                acceleration,
                ts,
                ext_time,
                ext_temp,
                ads,
                denat_skipped=denat_skipped,
            )
            # Fallos aislados se toleran (el ciclo siguiente suele recuperarse);
            # una racha de max_failed ciclos seguidos ya es un problema real
            # (heater o motor muertos) y seguir solo gasta tiempo y muestra.
            # Mismo apagado que el watchdog: los stop-events cortan el resto y
            # los datos se guardan igual (experiment_pcr).
            max_failed = self.timeout_cfg["max_failed"]
            if 0 < max_failed <= self.consec_failed_cycles:
                self._enter_phase("aborted_timeouts")
                print(
                    f"Aborting PCR: {self.consec_failed_cycles} consecutive cycles "
                    f"with phase timeouts (max_failed_cycles={max_failed})"
                )
                self.request_stop("aborted_timeouts")
                break

        # ----- Extensión final + lectura de fluorescencia (solo si no se detuvo).
        # El hold final se omite si ext_time_final <= 0, pero la lectura de
        # fluorescencia final SIEMPRE se realiza (la medición no se salta).
        if not self.stop_udp_listenner.is_set():
            print("PCR cycles complete, reading fluorescence")
            # Fuera del ciclado: cycle vuelve a 0 (la fase dice que es el cierre).
            self.cycle_current = 0
            self._cycle_timeouts = []  # la lectura final no hereda los del último ciclo
            self._enter_phase("final_ext")
            # Ancla del cronómetro del segmento final (hold + lectura final).
            # Se pone siempre, incluso si el hold se omite (ext_time_final<=0),
            # para que la lectura final igual cuente hacia abajo.
            self.start_final_ext_time = time.time()
            if not _skip(ext_time_final):
                self._hold_phase("h_ext", ext_temp, ext_time_final, ts)
            else:
                print("Skipping Final Extension hold: time <= 0")
            self._enter_phase("final_read")
            time.sleep(self.fluor_cfg["pre_sleep_s"])
            v_fluo_final = self._read_fluorescence(ads)
            print(f"Final fluorescence delta voltage: {v_fluo_final}")
            self._enter_phase("done")

    def _teardown_hardware(self):
        # Cierre idempotente de hardware: motor, UDP, pines GPIO. Lo invoca el hilo
        # del experimento al cerrar (experiment_pcr) y, como red de seguridad, el de
        # UI (_check_stop_timeouts); el lock evita que los dos cierren a la vez. No
        # toca running_experiment: el fin lo marca experiment_pcr tras guardar.
        global sistemaMotor
        with self._teardown_lock:
            if sistemaMotor is not None:
                try:
                    sistemaMotor.stop()
                except Exception as e:
                    print(f"error stopping motor: {e}")
                try:
                    sistemaMotor.close()
                except Exception as e:
                    print(f"error closing motor: {e}")
                sistemaMotor = None
            if self.client_temperature is not None:
                try:
                    self.client_temperature.stop()
                except Exception as e:
                    print(f"error stopping udp client: {e}")
            if self.pin_heating is not None:
                try:
                    self.pin_heating.write(False)  # pyrefly: ignore
                    self.pin_heating.close()
                except Exception as e:
                    print(f"error closing pin_heating: {e}")
                self.pin_heating = None
            if self.pin_pcr is not None:
                try:
                    self.pin_pcr.write(False)  # pyrefly: ignore
                    self.pin_pcr.close()
                except Exception as e:
                    print(f"error closing pin_pcr: {e}")
                self.pin_pcr = None

    def _restore_input_ui(self):
        # Vuelve a mostrar los inputs y la barra de proyectos (ocultados al iniciar).
        # Debe invocarse desde el hilo principal (Tkinter no es thread-safe).
        self.frame_entries.grid(row=1, column=0, padx=5, pady=5, sticky="nswe")
        self.frame_project.grid(row=0, column=0, sticky="nswe", padx=(5, 25), pady=(5, 0))
        if self.cbo_temp_source is not None:
            self.cbo_temp_source.configure(state="readonly")
        self._refresh_project_list()
        # Fin de corrida (natural o Stop): las otras tabs vuelven a estar
        # disponibles. Idempotente.
        self._set_tabs_locked(False)

    def _set_tabs_locked(self, locked):
        if self.lock_tabs_callback is not None:
            try:
                self.lock_tabs_callback(locked)
            except Exception as e:
                print(f"Error in lock_tabs_callback: {e}")

    def callback_stop_experiment(self):
        # Solo señaliza: el hilo sale, apaga, guarda y _ui_poll_loop restaura la UI
        # cuando terminó (status "Stopping…" / "Saving data…" mientras tanto). Antes
        # esperaba al hilo aquí (join de 3 s) con la UI congelada; con el guardado
        # .xlsx (~3 s en el Pi) el poll acababa antes que el guardado y su mensaje se
        # perdía. Las redes de seguridad (hilo colgado) están en _check_stop_timeouts.
        thread = self.thread_experiment
        if thread is None or not thread.is_alive():
            print("No experiment running")
            self.running_experiment = False
            self._restore_input_ui()
            return
        self.request_stop("stopped")

    def request_stop(self, reason):
        """Pide al hilo del experimento que termine. ``reason`` va a la fila ``end``
        de la metadata: "stopped" (botón Stop), "app_closed" (cierre de la app),
        "aborted_sensors" (watchdog), "aborted_timeouts" (salvaguarda de fases).
        Idempotente: gana el primer motivo."""
        if not self._stop_requested_at:
            self._stop_requested_at = time.time()
            self._stop_reason = reason
        for event in (self.stop_event_motor, self.stop_udp_listenner):
            if event is not None:
                event.set()

    def _check_stop_timeouts(self):
        """Redes de seguridad del Stop, desde _ui_poll_loop (hilo de UI).

        Si el hilo no llegó a su cierre en PCR_STOP_FORCE_S (colgado en una espera),
        apaga el hardware desde aquí, como hacía el Stop de antes tras su join. True
        si pasó PCR_STOP_GIVEUP_S y el hilo sigue vivo: la UI se restaura igual.
        """
        if not self._stop_requested_at or not self.running_experiment:
            return False
        waited = time.time() - self._stop_requested_at
        if waited > PCR_STOP_FORCE_S and not self._run_closing and not self._stop_forced:
            self._stop_forced = True
            print(
                f"warning: experiment thread did not exit within {PCR_STOP_FORCE_S:g}s,"
                " forcing teardown"
            )
            self._teardown_hardware()
        return waited > PCR_STOP_GIVEUP_S

    def _on_destroy(self, event=None):
        """Cierre de la app con una corrida activa: pide el paro. El hilo (no daemon)
        apaga el hardware y guarda aunque la ventana ya no exista, y el proceso sale
        cuando termina. MainGUI.on_close_window ya pide confirmación y espera al
        guardado; esto cubre cualquier otro camino de cierre."""
        if event is not None and event.widget is not self:
            return
        self._ui_poll_active = False
        if self._poll_after_id is not None:
            try:
                # Un tick pendiente dispararía contra un comando Tcl ya borrado.
                self.after_cancel(self._poll_after_id)
            except Exception:
                pass
            self._poll_after_id = None
        if self.running_experiment:
            self.request_stop("app_closed")
