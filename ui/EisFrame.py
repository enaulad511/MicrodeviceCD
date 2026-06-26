# -*- coding: utf-8 -*-

__author__ = "Edisson A. Naula"
__date__ = "$ 03/06/2026 at 12:00 p.m. $"

import math

import ttkbootstrap as ttk

from Drivers.EmstatUtils import construct_eis_script
from templates.constants import font_entry, font_text_combobox
from templates.utils import convert_si_integer_full
from ui.ElectrochemProjectBar import ElectrochemProjectBarMixin
from ui.EventEmstatFrame import EventPlotter
from ui.KeyboardFrame import NumericKeyboard
from ui.ShowMethodScript import ShowMethodScript

# Tipos de barrido (scan type) y de frecuencia. Fase 2: todas las combinaciones
# funcionan EXCEPTO Time Scan + Scan (excluida por duracion, ver doc seccion 7.1).
# El indice del combobox + 1 es el scan_type/freq_type del payload (1-based).
SCAN_TYPES = ["Default", "E_dc Scan", "Time Scan"]
FREQ_TYPES = ["Scan", "Fixed"]

# Valores por defecto (ejemplo canonico: 100 kHz -> 100 Hz, 10 mV, 200 mV DC, 11 pts)
DEF_E_AC = "0.01"
DEF_F_MAX = "100000"
DEF_F_MIN = "100"
DEF_N_FREQ = "11"
DEF_E_DC = "0.2"
# E_dc Scan
DEF_E_BEGIN = "-0.5"
DEF_E_STEP = "0.05"
DEF_E_END = "0.5"
# Time Scan
DEF_T_RUN = "60"
DEF_T_INTERVAL = "1"
# Fixed frequency
DEF_FREQ_FIXED = "1000"
# Pre-acondicionamiento (0 = etapa omitida)
DEF_E_CON = "0"
DEF_T_CON = "0"


class EISFrame(ElectrochemProjectBarMixin, ttk.Frame):
    """Frame de Espectroscopia de Impedancia Electroquimica (EIS).

    Estructura analoga a CvFrame/SqwVFrame: entradas -> payload -> EventPlotter
    (streaming TCP) en modo Nyquist (x=Z_real, y=-Z_imag). El canal de electrodo
    llega via callback_get_channel (igual que CV/SQWV).

    Dos selectores: scan type y frequency type (Fase 2: 5 combinaciones; Time Scan
    exige frecuencia Fixed). El plot cambia por modo: Nyquist (Default y E_dc Scan
    + freq Scan, este ultimo con una curva por potencial), |Z| vs E (E_dc Scan +
    Fixed) y |Z| vs t (Time Scan). Ver docs/eis_impedancia.md seccion 7.
    """

    project_method = "eis"

    def __init__(
        self,
        parent,
        ip_sender="localhost",
        callback_get_ip_sender=None,
        callback_get_channel=None,
        frame_with_scroll=None,
    ):
        ttk.Frame.__init__(self, parent)
        self.parent = parent
        self.callback_ip = callback_get_ip_sender
        self.callback_get_channel = callback_get_channel
        self.frame_w_scroll = frame_with_scroll
        self.columnconfigure(0, weight=1)
        self.rowconfigure((0, 1), weight=1)
        self.payload = {}
        self.ShowMethodScrit = None

        # --- StringVars de las entradas ---
        self.var_econ1 = ttk.StringVar(value=DEF_E_CON)
        self.var_tcon1 = ttk.StringVar(value=DEF_T_CON)
        self.var_econ2 = ttk.StringVar(value=DEF_E_CON)
        self.var_tcon2 = ttk.StringVar(value=DEF_T_CON)
        # Scan Default
        self.var_edc = ttk.StringVar(value=DEF_E_DC)
        self.var_eac = ttk.StringVar(value=DEF_E_AC)
        # Scan E_dc
        self.var_ebegin = ttk.StringVar(value=DEF_E_BEGIN)
        self.var_estep = ttk.StringVar(value=DEF_E_STEP)
        self.var_eend = ttk.StringVar(value=DEF_E_END)
        self.var_eac_edc = ttk.StringVar(value=DEF_E_AC)
        # Scan Time
        self.var_edc_time = ttk.StringVar(value=DEF_E_DC)
        self.var_trun = ttk.StringVar(value=DEF_T_RUN)
        self.var_tinterval = ttk.StringVar(value=DEF_T_INTERVAL)
        self.var_eac_time = ttk.StringVar(value=DEF_E_AC)
        # Freq Scan
        self.var_fmax = ttk.StringVar(value=DEF_F_MAX)
        self.var_fmin = ttk.StringVar(value=DEF_F_MIN)
        self.var_nfreq = ttk.StringVar(value=DEF_N_FREQ)
        self.var_valdec = ttk.StringVar(value="—")
        # Freq Fixed
        self.var_freq_fixed = ttk.StringVar(value=DEF_FREQ_FIXED)
        # Duracion estimada del experimento (solo lectura, se recalcula en vivo)
        self.var_est_time = ttk.StringVar(value="—")

        # val/dec se recalcula al cambiar f_max/f_min/n_freq.
        for v in (self.var_fmax, self.var_fmin, self.var_nfreq):
            v.trace_add("write", self._recompute_val_dec)
        # La duracion estimada depende de todas las entradas de tiempo/barrido.
        for v in (
            self.var_fmax,
            self.var_fmin,
            self.var_nfreq,
            self.var_freq_fixed,
            self.var_ebegin,
            self.var_estep,
            self.var_eend,
            self.var_trun,
            self.var_tinterval,
            self.var_tcon1,
            self.var_tcon2,
        ):
            v.trace_add("write", self._recompute_estimate)

        # =================== Layout ===================
        content_frame = ttk.Frame(self)
        content_frame.grid(row=0, column=0, sticky="nsew")
        content_frame.columnconfigure(0, weight=1)

        # Barra de proyecto (row 0, encima de las entradas).
        self.frame_project = self.build_project_bar(content_frame)
        self.frame_project.grid(row=0, column=0, sticky="nswe", padx=(5, 20), pady=(5, 0))

        self.frame_entries = ttk.Frame(content_frame)
        self.frame_entries.grid(row=1, column=0, sticky="nsew")
        self.frame_entries.columnconfigure(0, weight=1)

        self.lbl_status = ttk.Label(self.frame_entries, text="", anchor="w")
        self.lbl_status.grid(row=0, column=0, padx=5, pady=(2, 0), sticky="we")

        # Pre-acondicionamiento primero (comun a todos los modos); los selectores
        # van justo encima de los grupos que muestran/ocultan.
        self._build_preconditioning(self.frame_entries, row=1)
        self._build_selectors(self.frame_entries, row=2)
        self._build_scan_groups(self.frame_entries, row=3)
        self._build_freq_groups(self.frame_entries, row=4)

        # Botones
        self.frame_buttons = ttk.Frame(content_frame)
        self.frame_buttons.grid(row=2, column=0, sticky="nsew", pady=(6, 0))
        self.frame_buttons.columnconfigure((0, 1, 2), weight=1)
        ttk.Button(
            self.frame_buttons,
            text="🗒️ Script",
            style="info.TButton",
            command=self.callback_show_script,
        ).grid(row=0, column=0, pady=8, sticky="n")
        ttk.Button(
            self.frame_buttons,
            text="⏫ Send Script",
            style="info.TButton",
            command=self.send_script,
        ).grid(row=0, column=1, pady=8, sticky="n")
        ttk.Button(
            self.frame_buttons,
            text="Show Inputs",
            style="danger.TButton",
            command=self.show_inputs_frame,
        ).grid(row=0, column=2, pady=8, sticky="n")

        # Teclado numerico flotante para todas las entradas editables
        self.keyboard = NumericKeyboard(self, scroll_host=self.frame_w_scroll)
        self._attach_keyboard()

        # Plotter: Nyquist por defecto (x=Z_real, y=-Z_imag, zi negado en el parser);
        # send_script() reconfigura ejes/leyenda segun el modo (ver _plot_config).
        self.frame_plotter = ttk.LabelFrame(self, text="Live Data Plotter")
        self.frame_plotter.grid(row=1, column=0, padx=5, pady=2, sticky="nsew")
        self.frame_plotter.columnconfigure(0, weight=1)
        self.frame_plotter.rowconfigure(0, weight=1)
        self.frame_plotter.configure(style="Custom.TLabelframe")
        self.udp_plotter = EventPlotter(
            self.frame_plotter,
            "eis",
            tcp_port=5006,
            ip_sender=ip_sender,
            buffer_size=4096,
            max_points=5000,
            update_interval_ms=80,
            title="EIS (Nyquist)",
            x_label="Z_real (Ω)",
            y_label="-Z_imag (Ω)",
            x_key="Z_real",
            y_key="Z_imag",
            payload=self.payload,
            frames_to_hide=[self.frame_entries],
            on_end_expriment=self.on_end_experiment,
        )
        self.udp_plotter.grid(row=0, column=0, padx=(5, 15), sticky="nsew")
        self.frame_plotter.grid_forget()

        self._recompute_val_dec()
        self._recompute_estimate()

        # Auto-carga del proyecto inicial (cascada _last_used -> _last_run -> Default).
        self.load_initial_project()

    # ----------------------------------------------------------------
    # Construccion de widgets
    # ----------------------------------------------------------------
    def _build_selectors(self, parent, row):
        frame = ttk.LabelFrame(parent, text="Experiment type")
        frame.grid(row=row, column=0, padx=(5, 20), pady=6, sticky="nswe")
        frame.configure(style="Custom.TLabelframe")
        frame.columnconfigure((1, 3), weight=1)

        ttk.Label(frame, text="Scan type:", style="Custom.TLabel").grid(
            row=0, column=0, padx=5, pady=5, sticky="e"
        )
        self.scan_selector = ttk.Combobox(
            frame, values=SCAN_TYPES, state="readonly", width=18, font=font_text_combobox
        )
        self.scan_selector.current(0)
        self.scan_selector.grid(row=0, column=1, padx=5, pady=5, sticky="w")
        self.scan_selector.bind("<<ComboboxSelected>>", self.on_scan_type_changed)

        ttk.Label(frame, text="Frequency type:", style="Custom.TLabel").grid(
            row=0, column=2, padx=5, pady=5, sticky="e"
        )
        self.freq_selector = ttk.Combobox(
            frame, values=FREQ_TYPES, state="readonly", width=10, font=font_text_combobox
        )
        self.freq_selector.current(0)
        self.freq_selector.grid(row=0, column=3, padx=5, pady=5, sticky="w")
        self.freq_selector.bind("<<ComboboxSelected>>", self.on_freq_type_changed)

        # Duracion estimada (solo lectura): modelo _point_s x espectros +
        # acondicionamiento, sin el margen de seguridad de max_time_s.
        ttk.Label(frame, text="Est. duration:", style="Custom.TLabel").grid(
            row=1, column=0, padx=5, pady=(0, 5), sticky="e"
        )
        ttk.Label(frame, textvariable=self.var_est_time, style="Custom.TLabel").grid(
            row=1, column=1, padx=5, pady=(0, 5), sticky="w"
        )

    def _row_entry(self, parent, row, label, var, width=12):
        ttk.Label(parent, text=label, style="Custom.TLabel").grid(
            row=row, column=0, padx=5, pady=4, sticky="e"
        )
        entry = ttk.Entry(parent, font=font_entry, textvariable=var, width=width)
        entry.grid(row=row, column=1, padx=5, pady=4, sticky="we")
        return entry

    def _build_preconditioning(self, parent, row):
        frame = ttk.LabelFrame(parent, text="Pre-conditioning (t=0 → skipped)")
        frame.grid(row=row, column=0, padx=(5, 20), pady=6, sticky="nswe")
        frame.configure(style="Custom.TLabelframe")
        frame.columnconfigure((1, 3), weight=1)
        # Bloque 1
        ttk.Label(frame, text="E cond 1 (V):", style="Custom.TLabel").grid(
            row=0, column=0, padx=5, pady=4, sticky="e"
        )
        e1 = ttk.Entry(frame, font=font_entry, textvariable=self.var_econ1, width=10)
        e1.grid(row=0, column=1, padx=5, pady=4, sticky="we")
        ttk.Label(frame, text="t cond 1 (s):", style="Custom.TLabel").grid(
            row=0, column=2, padx=5, pady=4, sticky="e"
        )
        e2 = ttk.Entry(frame, font=font_entry, textvariable=self.var_tcon1, width=10)
        e2.grid(row=0, column=3, padx=5, pady=4, sticky="we")
        # Bloque 2
        ttk.Label(frame, text="E cond 2 (V):", style="Custom.TLabel").grid(
            row=1, column=0, padx=5, pady=4, sticky="e"
        )
        e3 = ttk.Entry(frame, font=font_entry, textvariable=self.var_econ2, width=10)
        e3.grid(row=1, column=1, padx=5, pady=4, sticky="we")
        ttk.Label(frame, text="t cond 2 (s):", style="Custom.TLabel").grid(
            row=1, column=2, padx=5, pady=4, sticky="e"
        )
        e4 = ttk.Entry(frame, font=font_entry, textvariable=self.var_tcon2, width=10)
        e4.grid(row=1, column=3, padx=5, pady=4, sticky="we")
        self._pre_entries = [e1, e2, e3, e4]

    def _build_scan_groups(self, parent, row):
        self.scan_container = ttk.Frame(parent)
        self.scan_container.grid(row=row, column=0, padx=(5, 20), pady=6, sticky="nswe")
        self.scan_container.columnconfigure(0, weight=1)

        # Default (E_dc, E_ac)
        self.frame_scan_default = ttk.LabelFrame(self.scan_container, text="Scan: Default")
        self.frame_scan_default.configure(style="Custom.TLabelframe")
        self.frame_scan_default.columnconfigure(1, weight=1)
        d1 = self._row_entry(self.frame_scan_default, 0, "E dc (V):", self.var_edc)
        d2 = self._row_entry(self.frame_scan_default, 1, "E ac (V):", self.var_eac)

        # E_dc Scan (inactivo Fase 1)
        self.frame_scan_edc = ttk.LabelFrame(self.scan_container, text="Scan: E_dc Scan")
        self.frame_scan_edc.configure(style="Custom.TLabelframe")
        self.frame_scan_edc.columnconfigure(1, weight=1)
        s1 = self._row_entry(self.frame_scan_edc, 0, "E begin (V):", self.var_ebegin)
        s2 = self._row_entry(self.frame_scan_edc, 1, "E step (V):", self.var_estep)
        s3 = self._row_entry(self.frame_scan_edc, 2, "E end (V):", self.var_eend)
        s4 = self._row_entry(self.frame_scan_edc, 3, "E ac (V):", self.var_eac_edc)

        # Time Scan (inactivo Fase 1)
        self.frame_scan_time = ttk.LabelFrame(self.scan_container, text="Scan: Time Scan")
        self.frame_scan_time.configure(style="Custom.TLabelframe")
        self.frame_scan_time.columnconfigure(1, weight=1)
        t1 = self._row_entry(self.frame_scan_time, 0, "E dc (V):", self.var_edc_time)
        t2 = self._row_entry(self.frame_scan_time, 1, "t run (s):", self.var_trun)
        t3 = self._row_entry(self.frame_scan_time, 2, "t interval (s):", self.var_tinterval)
        t4 = self._row_entry(self.frame_scan_time, 3, "E ac (V):", self.var_eac_time)

        self._scan_entries = [d1, d2, s1, s2, s3, s4, t1, t2, t3, t4]
        self.on_scan_type_changed()

    def _build_freq_groups(self, parent, row):
        self.freq_container = ttk.Frame(parent)
        self.freq_container.grid(row=row, column=0, padx=(5, 20), pady=6, sticky="nswe")
        self.freq_container.columnconfigure(0, weight=1)

        # Scan
        self.frame_freq_scan = ttk.LabelFrame(self.freq_container, text="Frequency: Scan")
        self.frame_freq_scan.configure(style="Custom.TLabelframe")
        self.frame_freq_scan.columnconfigure(1, weight=1)
        f1 = self._row_entry(self.frame_freq_scan, 0, "f max (Hz):", self.var_fmax)
        f2 = self._row_entry(self.frame_freq_scan, 1, "f min (Hz):", self.var_fmin)
        f3 = self._row_entry(self.frame_freq_scan, 2, "n frequencies:", self.var_nfreq)
        ttk.Label(self.frame_freq_scan, text="val/dec:", style="Custom.TLabel").grid(
            row=3, column=0, padx=5, pady=4, sticky="e"
        )
        ttk.Label(self.frame_freq_scan, textvariable=self.var_valdec, style="Custom.TLabel").grid(
            row=3, column=1, padx=5, pady=4, sticky="w"
        )

        # Fixed (inactivo Fase 1)
        self.frame_freq_fixed = ttk.LabelFrame(self.freq_container, text="Frequency: Fixed")
        self.frame_freq_fixed.configure(style="Custom.TLabelframe")
        self.frame_freq_fixed.columnconfigure(1, weight=1)
        ff = self._row_entry(self.frame_freq_fixed, 0, "frequency (Hz):", self.var_freq_fixed)

        self._freq_entries = [f1, f2, f3, ff]
        self.on_freq_type_changed()

    def _attach_keyboard(self):
        editable = self._pre_entries + self._scan_entries + self._freq_entries
        self.keyboard.attach(editable)

    # ----------------------------------------------------------------
    # Selectores: muestran/ocultan el grupo de entradas correspondiente
    # ----------------------------------------------------------------
    def on_scan_type_changed(self, event=None):
        idx = self.scan_selector.current()
        for fr in (self.frame_scan_default, self.frame_scan_edc, self.frame_scan_time):
            fr.grid_forget()
        target = (self.frame_scan_default, self.frame_scan_edc, self.frame_scan_time)[idx]
        target.grid(row=0, column=0, sticky="nswe")
        self._update_combo_status()
        self._recompute_estimate()

    def on_freq_type_changed(self, event=None):
        idx = self.freq_selector.current()
        for fr in (self.frame_freq_scan, self.frame_freq_fixed):
            fr.grid_forget()
        target = (self.frame_freq_scan, self.frame_freq_fixed)[idx]
        target.grid(row=0, column=0, sticky="nswe")
        self._update_combo_status()
        self._recompute_estimate()

    def _update_combo_status(self):
        if self._combo_supported():
            self._set_status("")
        else:
            self._set_status("Time Scan requires 'Fixed' frequency type.")

    def _combo_supported(self):
        """Unica combinacion excluida: Time Scan + frequency Scan (doc seccion 7.1)."""
        return not (self.scan_selector.current() == 2 and self.freq_selector.current() == 0)

    def _recompute_val_dec(self, *args):
        try:
            fmax = float(self.var_fmax.get())
            fmin = float(self.var_fmin.get())
            nfreq = float(self.var_nfreq.get())
            if fmax > 0 and fmin > 0 and fmax != fmin and nfreq > 0:
                decades = abs(math.log10(fmax / fmin))
                if decades > 0:
                    self.var_valdec.set(str(round(nfreq / decades, 1)))
                    return
        except Exception:
            pass
        self.var_valdec.set("—")

    # ----------------------------------------------------------------
    # Payload / script
    # ----------------------------------------------------------------
    def _get_channel(self):
        """Canal de electrodo (0-7) para el payload. Degrada a 0 si no hay callback.

        El firmware valida el rango; aqui solo garantizamos un int valido.
        """
        if self.callback_get_channel is None:
            return 0
        try:
            return int(self.callback_get_channel())
        except Exception:
            return 0

    @staticmethod
    def _fmt_time(value):
        """Tiempo en segundos -> SI, o '' si es 0 (etapa de acondicionamiento omitida)."""
        try:
            v = float(value)
        except Exception:
            return ""
        return "" if v == 0 else convert_si_integer_full(v)

    def generate_payload(self):
        """Construye el payload del modo activo (scan_type/freq_type 1-based).

        Claves canonicas para el generador de script: f_max/f_min/n_freq SIEMPRE.
        La frecuencia fija se degenera aqui (f_max=f_min=f, n_freq=1) y el Time Scan
        calcula n_freq = t_run//t_interval + 1 (numero de mediciones del loop).
        Tambien se calculan aqui los auxiliares numericos que el firmware solo
        reenvia: bandwidth (10x f_max), E_step con signo, E_break (umbral del
        breakloop con tolerancia de medio paso), E_dir y max_time_s (tope dinamico).
        Lanza ValueError ante entradas invalidas.
        """
        scan_type = self.scan_selector.current() + 1
        freq_type = self.freq_selector.current() + 1
        if scan_type == 3 and freq_type != 2:
            raise ValueError("Time Scan requires Fixed frequency")

        if freq_type == 1:
            f_hi = float(self.var_fmax.get())
            f_lo = float(self.var_fmin.get())
            n_freq = int(float(self.var_nfreq.get()))
            if f_hi <= 0 or f_lo <= 0 or f_hi < f_lo or n_freq < 1:
                raise ValueError("invalid frequency scan")
        else:
            f_fix = float(self.var_freq_fixed.get())
            if f_fix <= 0:
                raise ValueError("invalid fixed frequency")
            f_hi = f_lo = f_fix
            n_freq = 1

        e_ac_var = (self.var_eac, self.var_eac_edc, self.var_eac_time)[scan_type - 1]
        payload = {
            "method": "eis",
            "scan_type": scan_type,
            "freq_type": freq_type,
            "ch": self._get_channel(),
            "E_ac": convert_si_integer_full(float(e_ac_var.get())),
            "E_con1": convert_si_integer_full(float(self.var_econ1.get())),
            "t_con1": self._fmt_time(self.var_tcon1.get()),
            "E_con2": convert_si_integer_full(float(self.var_econ2.get())),
            "t_con2": self._fmt_time(self.var_tcon2.get()),
            # Regla PSTrace verificada en los 4 exports: bandwidth = 10x f_max.
            "bandwidth": convert_si_integer_full(10 * f_hi),
        }

        n_spectra = 1
        if scan_type == 2:
            e_begin = float(self.var_ebegin.get())
            e_step = abs(float(self.var_estep.get()))
            e_end = float(self.var_eend.get())
            if e_step <= 0 or e_begin == e_end:
                raise ValueError("invalid potential scan")
            direction = 1 if e_end > e_begin else -1
            n_spectra = round(abs(e_end - e_begin) / e_step) + 1
            payload.update(
                {
                    "E_dc": "0",  # no lo usa el generador en este modo
                    "E_begin": convert_si_integer_full(e_begin),
                    # add_var aplica el paso CON signo; el breakloop compara contra
                    # E_end +- medio paso (tolerancia de acumulacion flotante).
                    "E_step": convert_si_integer_full(direction * e_step),
                    "E_break": convert_si_integer_full(round(e_end + direction * e_step / 2, 9)),
                    "E_dir": direction,
                }
            )
        elif scan_type == 3:
            t_run = int(float(self.var_trun.get()))
            t_int = int(float(self.var_tinterval.get()))
            if t_int < 1 or t_run < t_int:
                raise ValueError("invalid time scan")
            n_freq = t_run // t_int + 1
            payload.update(
                {
                    "E_dc": convert_si_integer_full(float(self.var_edc_time.get())),
                    "t_run": t_run,
                    "t_interval": t_int,
                }
            )
        else:
            payload["E_dc"] = convert_si_integer_full(float(self.var_edc.get()))

        payload["f_max"] = convert_si_integer_full(f_hi)
        payload["f_min"] = convert_si_integer_full(f_lo)
        payload["n_freq"] = n_freq
        payload["max_time_s"] = self._estimate_max_time_s(scan_type, f_hi, f_lo, n_freq, n_spectra)
        # Idle por corrida: el EmStat emite UN paquete por punto AL TERMINARLO, asi
        # que el hueco maximo entre paquetes es el punto mas lento (el de f_min) --
        # o t_interval en Time Scan. Con el idle fijo del Pico (16 s) cualquier
        # punto bajo ~1 Hz mataba la corrida con emstat_timeout a medias.
        worst_gap = self._point_s(f_lo)
        if scan_type == 3:
            worst_gap = max(worst_gap, float(payload.get("t_interval", 0)))
        payload["idle_s"] = int(worst_gap * 1.5 + 15)
        self.payload = payload

    @staticmethod
    def _point_s(freq):
        """Duracion estimada (s) de UN punto EIS a la frecuencia dada: ~30 periodos
        de integracion/autorango + 3 s de overhead. Calibrado conservador contra
        corridas reales (~20 min para 51 puntos con cola de baja frecuencia)."""
        return 30.0 / freq + 3.0

    def _estimate_duration_s(self, scan_type, f_hi, f_lo, n_freq, n_spectra):
        """Duracion estimada (s) del experimento, SIN margen de seguridad: modelo
        _point_s por punto (la cola de baja frecuencia domina) x espectros, o
        t_run + t_interval en Time Scan; mas el acondicionamiento."""
        t_con = 0.0
        for var in (self.var_tcon1, self.var_tcon2):
            try:
                t_con += max(0.0, float(var.get()))
            except ValueError:
                pass
        if scan_type == 3:
            est = float(self.var_trun.get()) + float(self.var_tinterval.get())
        else:
            # Puntos log-espaciados
            if n_freq <= 1 or f_hi == f_lo:
                freqs = [f_lo] * n_freq
            else:
                ratio = (f_lo / f_hi) ** (1.0 / (n_freq - 1))
                freqs = [f_hi * ratio**i for i in range(n_freq)]
            est = sum(self._point_s(fq) for fq in freqs) * n_spectra
        return est + t_con

    def _estimate_max_time_s(self, scan_type, f_hi, f_lo, n_freq, n_spectra):
        """Tope dinamico para el firmware (v1.8 usa max(max_time_s, 10 min)):
        la duracion estimada con margen de seguridad."""
        return int(self._estimate_duration_s(scan_type, f_hi, f_lo, n_freq, n_spectra) * 1.5 + 60)

    def _recompute_estimate(self, *args):
        """Refresca el indicador de duracion estimada (en vivo, via trace_add y al
        cambiar de modo). Entradas invalidas o combo no soportada -> '—'."""
        try:
            scan_type = self.scan_selector.current() + 1
            freq_type = self.freq_selector.current() + 1
            if scan_type == 3 and freq_type != 2:
                self.var_est_time.set("—")
                return
            if freq_type == 1:
                f_hi = float(self.var_fmax.get())
                f_lo = float(self.var_fmin.get())
                n_freq = int(float(self.var_nfreq.get()))
                if f_hi <= 0 or f_lo <= 0 or f_hi < f_lo or n_freq < 1:
                    raise ValueError
            else:
                f_hi = f_lo = float(self.var_freq_fixed.get())
                if f_hi <= 0:
                    raise ValueError
                n_freq = 1
            n_spectra = 1
            if scan_type == 2:
                e_begin = float(self.var_ebegin.get())
                e_step = abs(float(self.var_estep.get()))
                e_end = float(self.var_eend.get())
                if e_step <= 0 or e_begin == e_end:
                    raise ValueError
                n_spectra = round(abs(e_end - e_begin) / e_step) + 1
            elif scan_type == 3:
                if float(self.var_tinterval.get()) < 1 or float(self.var_trun.get()) < float(
                    self.var_tinterval.get()
                ):
                    raise ValueError
            est = self._estimate_duration_s(scan_type, f_hi, f_lo, n_freq, n_spectra)
            self.var_est_time.set("~" + self._fmt_duration(est))
        except (ValueError, AttributeError, ZeroDivisionError):
            self.var_est_time.set("—")

    @staticmethod
    def _fmt_duration(seconds):
        """Segundos -> texto legible: '45 s', '8 min 20 s', '1 h 05 min'."""
        s = int(round(seconds))
        if s < 60:
            return f"{s} s"
        m, s = divmod(s, 60)
        if m < 60:
            return f"{m} min {s:02d} s"
        h, m = divmod(m, 60)
        return f"{h} h {m:02d} min"

    def generate_methodscript(self):
        self.generate_payload()
        return construct_eis_script(
            self.payload["E_ac"],
            self.payload["f_max"],
            self.payload["f_min"],
            self.payload["n_freq"],
            self.payload["E_dc"],
            self.payload.get("E_con1", ""),
            self.payload.get("t_con1", ""),
            self.payload.get("E_con2", ""),
            self.payload.get("t_con2", ""),
            scan_type=self.payload["scan_type"],
            bandwidth=self.payload.get("bandwidth", ""),
            E_begin=self.payload.get("E_begin", ""),
            E_step=self.payload.get("E_step", ""),
            E_break=self.payload.get("E_break", ""),
            E_dir=self.payload.get("E_dir", 1),
            t_run=self.payload.get("t_run", 0),
            t_interval=self.payload.get("t_interval", 0),
        )

    def callback_show_script(self):
        if not self._combo_ok():
            return
        try:
            script = self.generate_methodscript()
        except ValueError:
            self._set_status("Error: check input values.")
            return
        if self.ShowMethodScrit is not None:
            self.ShowMethodScrit.destroy()
            self.ShowMethodScrit = None
        self.ShowMethodScrit = ShowMethodScript(self, script)

    def on_close_script_window(self):
        self.ShowMethodScrit = None

    def _combo_ok(self):
        if not self._combo_supported():
            self._set_status("Time Scan requires 'Fixed' frequency type.")
            return False
        return True

    def _plot_config(self):
        """Configuracion de plot del modo activo (segun self.payload):
        (x_key, y_key, title, x_label, y_label, parser_kwargs, cycle_legend)."""
        scan_type = self.payload["scan_type"]
        freq_type = self.payload["freq_type"]
        if scan_type == 3:
            return ("t_s", "Z_mod", "EIS |Z| vs time", "t (s)", "|Z| (Ω)", {}, None)
        if scan_type == 2 and freq_type == 2:
            return ("E_V", "Z_mod", "EIS |Z| vs E", "E dc (V)", "|Z| (Ω)", {}, None)
        if scan_type == 2:
            # Nyquist superpuestos: una curva (cycle) por potencial, detectado por el
            # E_V embebido en cada paquete; leyenda con el potencial del espectro.
            return (
                "Z_real",
                "Z_imag",
                "EIS (Nyquist)",
                "Z_real (Ω)",
                "-Z_imag (Ω)",
                {"eis_group_by_potential": True},
                ("E_V", "E={:.3g}V"),
            )
        return ("Z_real", "Z_imag", "EIS (Nyquist)", "Z_real (Ω)", "-Z_imag (Ω)", {}, None)

    def send_script(self):
        if not self._combo_ok():
            return
        try:
            self.generate_payload()
        except ValueError:
            self._set_status("Error: check input values.")
            return
        # Snapshot de lo que se va a correr -> _last_run (decisión Q7).
        self.snapshot_current_run()
        x_key, y_key, title, x_label, y_label, parser_kwargs, cycle_legend = self._plot_config()
        self.frame_project.grid_forget()
        self.frame_entries.grid_forget()
        ip_sender = self.callback_ip() if self.callback_ip else "localhost"
        # Watchdog de inactividad del plotter: derivado del idle de ESTA corrida
        # (idle_s ya cubre el punto mas lento del barrido y t_interval) + drenado
        # (6 s) + margen, para que el terminal del firmware (emstat_end/timeout)
        # SIEMPRE le gane al watchdog del host (visto en hardware: con el host por
        # debajo del idle del Pico, la corrida cerraba con "watchdog" generico antes
        # de que el Pico alcanzara a reportar).
        self.udp_plotter.watchdog_timeout = float(self.payload["idle_s"]) + 15.0
        self.udp_plotter.change_axes_text(title, x_label, y_label)
        self.udp_plotter.update_val_experiment(
            x_key=x_key,
            y_key=y_key,
            payload=self.payload,
            ip_sender=ip_sender,
            callback_spin_motor=None,
            parser_kwargs=parser_kwargs,
            cycle_legend=cycle_legend,
        )
        self.frame_plotter.grid(row=1, column=0, padx=5, pady=2, sticky="nsew")
        if self.frame_w_scroll:
            self.frame_w_scroll.yview_moveto(0)

    def show_inputs_frame(self):
        if self.frame_w_scroll:
            self.frame_w_scroll.yview_moveto(0)
        self.frame_project.grid(row=0, column=0, sticky="nswe", padx=(5, 20), pady=(5, 0))
        self.frame_entries.grid(row=1, column=0, sticky="nsew")
        # self.frame_plotter.grid_forget()

    # ----- Hooks de proyecto (ver ui/ElectrochemProjectBar.py) -----
    def collect_values(self):
        """Estado completo del formulario EIS -> dict de claves canónicas.

        Guarda TODAS las variables (lossless, sin importar el modo activo) y los
        dos comboboxes como cadenas legibles (decisión Q10).
        """
        return {
            "E_con1": self.var_econ1.get(),
            "t_con1": self.var_tcon1.get(),
            "E_con2": self.var_econ2.get(),
            "t_con2": self.var_tcon2.get(),
            "E_dc": self.var_edc.get(),
            "E_ac": self.var_eac.get(),
            "E_begin": self.var_ebegin.get(),
            "E_step": self.var_estep.get(),
            "E_end": self.var_eend.get(),
            "E_ac_edc": self.var_eac_edc.get(),
            "E_dc_time": self.var_edc_time.get(),
            "t_run": self.var_trun.get(),
            "t_interval": self.var_tinterval.get(),
            "E_ac_time": self.var_eac_time.get(),
            "f_max": self.var_fmax.get(),
            "f_min": self.var_fmin.get(),
            "n_freq": self.var_nfreq.get(),
            "freq_fixed": self.var_freq_fixed.get(),
            "scan_type": self.scan_selector.get(),
            "freq_type": self.freq_selector.get(),
        }

    def apply_values(self, values):
        """Vuelca un proyecto EIS: vars -> comboboxes -> handlers -> recompute.

        Orden importante (decisión Q10): primero las StringVars (sus traces
        recalculan val/dec y la duración), luego los comboboxes por etiqueta, y
        por último los handlers de cambio para mostrar el grupo correcto.
        """
        self.var_econ1.set(str(values.get("E_con1", "")))
        self.var_tcon1.set(str(values.get("t_con1", "")))
        self.var_econ2.set(str(values.get("E_con2", "")))
        self.var_tcon2.set(str(values.get("t_con2", "")))
        self.var_edc.set(str(values.get("E_dc", "")))
        self.var_eac.set(str(values.get("E_ac", "")))
        self.var_ebegin.set(str(values.get("E_begin", "")))
        self.var_estep.set(str(values.get("E_step", "")))
        self.var_eend.set(str(values.get("E_end", "")))
        self.var_eac_edc.set(str(values.get("E_ac_edc", "")))
        self.var_edc_time.set(str(values.get("E_dc_time", "")))
        self.var_trun.set(str(values.get("t_run", "")))
        self.var_tinterval.set(str(values.get("t_interval", "")))
        self.var_eac_time.set(str(values.get("E_ac_time", "")))
        self.var_fmax.set(str(values.get("f_max", "")))
        self.var_fmin.set(str(values.get("f_min", "")))
        self.var_nfreq.set(str(values.get("n_freq", "")))
        self.var_freq_fixed.set(str(values.get("freq_fixed", "")))

        scan = str(values.get("scan_type", SCAN_TYPES[0]))
        freq = str(values.get("freq_type", FREQ_TYPES[0]))
        self.scan_selector.current(SCAN_TYPES.index(scan) if scan in SCAN_TYPES else 0)
        self.freq_selector.current(FREQ_TYPES.index(freq) if freq in FREQ_TYPES else 0)
        self.on_scan_type_changed()
        self.on_freq_type_changed()
        self._recompute_val_dec()
        self._recompute_estimate()

    def on_end_experiment(self, thread_motor=None):
        self.show_inputs_frame()
        print("EIS experiment finished.")

    def _set_status(self, msg):
        self.lbl_status.configure(text=msg)


if __name__ == "__main__":
    app = ttk.Window(themename="flatly")
    app.title("Impedance Spectroscopy")
    app.geometry("900x700")
    EISFrame(app).pack(fill="both", expand=True)
    app.mainloop()
