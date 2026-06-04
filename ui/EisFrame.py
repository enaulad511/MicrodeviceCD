# -*- coding: utf-8 -*-
import math
from tkinter.scrolledtext import ScrolledText

import ttkbootstrap as ttk

from Drivers.EmstatUtils import construct_eis_script
from templates.constants import font_entry, font_text_combobox
from templates.utils import convert_si_integer_full
from ui.EventEmstatFrame import EventPlotter
from ui.KeyboardFrame import NumericKeyboard

__author__ = "Edisson A. Naula"
__date__ = "$ 03/06/2026 at 12:00 p.m. $"

# Tipos de barrido (scan type). Fase 1: solo "Default" es funcional; los demas
# tienen sus entradas en la UI pero aun no generan script.
SCAN_TYPES = ["Default (E_dc, E_ac)", "E_dc Scan", "Time Scan"]
# Tipos de frecuencia. Fase 1: solo "Scan" es funcional.
FREQ_TYPES = ["Scan", "Fixed"]

# Valores por defecto (ejemplo canonico: 100 kHz -> 100 Hz, 10 mV, 200 mV DC, 11 pts)
DEF_E_AC = "0.01"
DEF_F_MAX = "100000"
DEF_F_MIN = "100"
DEF_N_FREQ = "11"
DEF_E_DC = "0.2"
# E_dc Scan (inactivo Fase 1)
DEF_E_BEGIN = "-0.5"
DEF_E_STEP = "0.05"
DEF_E_END = "0.5"
# Time Scan (inactivo Fase 1)
DEF_T_RUN = "60"
DEF_T_INTERVAL = "1"
# Fixed frequency (inactivo Fase 1)
DEF_FREQ_FIXED = "1000"
# Pre-acondicionamiento (0 = etapa omitida)
DEF_E_CON = "0"
DEF_T_CON = "0"


class EISFrame(ttk.Frame):
    """Frame de Espectroscopia de Impedancia Electroquimica (EIS).

    Estructura analoga a CvFrame/SqwVFrame: entradas -> payload -> EventPlotter
    (streaming TCP) en modo Nyquist (x=Z_real, y=-Z_imag). El canal de electrodo
    llega via callback_get_channel (igual que CV/SQWV).

    Dos selectores: scan type y frequency type. Fase 1 implementa solo
    Default + Scan; el resto de entradas existen pero no generan script todavia.
    """

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

        # --- StringVars de las entradas ---
        self.var_econ1 = ttk.StringVar(value=DEF_E_CON)
        self.var_tcon1 = ttk.StringVar(value=DEF_T_CON)
        self.var_econ2 = ttk.StringVar(value=DEF_E_CON)
        self.var_tcon2 = ttk.StringVar(value=DEF_T_CON)
        # Scan Default
        self.var_edc = ttk.StringVar(value=DEF_E_DC)
        self.var_eac = ttk.StringVar(value=DEF_E_AC)
        # Scan E_dc (inactivo)
        self.var_ebegin = ttk.StringVar(value=DEF_E_BEGIN)
        self.var_estep = ttk.StringVar(value=DEF_E_STEP)
        self.var_eend = ttk.StringVar(value=DEF_E_END)
        self.var_eac_edc = ttk.StringVar(value=DEF_E_AC)
        # Scan Time (inactivo)
        self.var_edc_time = ttk.StringVar(value=DEF_E_DC)
        self.var_trun = ttk.StringVar(value=DEF_T_RUN)
        self.var_tinterval = ttk.StringVar(value=DEF_T_INTERVAL)
        self.var_eac_time = ttk.StringVar(value=DEF_E_AC)
        # Freq Scan
        self.var_fmax = ttk.StringVar(value=DEF_F_MAX)
        self.var_fmin = ttk.StringVar(value=DEF_F_MIN)
        self.var_nfreq = ttk.StringVar(value=DEF_N_FREQ)
        self.var_valdec = ttk.StringVar(value="—")
        # Freq Fixed (inactivo)
        self.var_freq_fixed = ttk.StringVar(value=DEF_FREQ_FIXED)

        # val/dec se recalcula al cambiar f_max/f_min/n_freq.
        for v in (self.var_fmax, self.var_fmin, self.var_nfreq):
            v.trace_add("write", self._recompute_val_dec)

        # =================== Layout ===================
        content_frame = ttk.Frame(self)
        content_frame.grid(row=0, column=0, sticky="nsew")
        content_frame.columnconfigure(0, weight=1)

        self.frame_entries = ttk.Frame(content_frame)
        self.frame_entries.grid(row=0, column=0, sticky="nsew")
        self.frame_entries.columnconfigure(0, weight=1)

        self.lbl_status = ttk.Label(self.frame_entries, text="", anchor="w")
        self.lbl_status.grid(row=0, column=0, padx=5, pady=(2, 0), sticky="we")

        self._build_selectors(self.frame_entries, row=1)
        self._build_preconditioning(self.frame_entries, row=2)
        self._build_scan_groups(self.frame_entries, row=3)
        self._build_freq_groups(self.frame_entries, row=4)

        # Botones
        self.frame_buttons = ttk.Frame(content_frame)
        self.frame_buttons.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
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

        # Caja de MethodScript (oculta hasta pedirla)
        self.script_box = ScrolledText(content_frame, height=15)
        self.script_box.grid(row=2, column=0, padx=(5, 15), pady=10, sticky="nswe")
        self.script_box.grid_forget()

        # Teclado numerico flotante para todas las entradas editables
        self.keyboard = NumericKeyboard(self, scroll_host=self.frame_w_scroll)
        self._attach_keyboard()

        # Plotter (Nyquist): x=Z_real, y=-Z_imag (zi negado en el parser)
        self.frame_plotter = ttk.LabelFrame(self, text="Live Data Plotter (Nyquist)")
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
        ttk.Label(
            self.frame_freq_scan, textvariable=self.var_valdec, style="Custom.TLabel"
        ).grid(row=3, column=1, padx=5, pady=4, sticky="w")

        # Fixed (inactivo Fase 1)
        self.frame_freq_fixed = ttk.LabelFrame(self.freq_container, text="Frequency: Fixed")
        self.frame_freq_fixed.configure(style="Custom.TLabelframe")
        self.frame_freq_fixed.columnconfigure(1, weight=1)
        ff = self._row_entry(self.frame_freq_fixed, 0, "frequency (Hz):", self.var_freq_fixed)

        self._freq_entries = [f1, f2, f3, ff]
        self.on_freq_type_changed()

    def _attach_keyboard(self):
        editable = (
            self._pre_entries + self._scan_entries + self._freq_entries
        )
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
        self._update_phase1_status()

    def on_freq_type_changed(self, event=None):
        idx = self.freq_selector.current()
        for fr in (self.frame_freq_scan, self.frame_freq_fixed):
            fr.grid_forget()
        target = (self.frame_freq_scan, self.frame_freq_fixed)[idx]
        target.grid(row=0, column=0, sticky="nswe")
        self._update_phase1_status()

    def _update_phase1_status(self):
        if self.scan_selector.current() == 0 and self.freq_selector.current() == 0:
            self._set_status("")
        else:
            self._set_status("Only 'Default' scan + 'Scan' frequency are implemented for now.")

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
        """Fase 1: scan_type=Default (1), freq_type=Scan (1)."""
        self.payload = {
            "method": "eis",
            "scan_type": 1,
            "freq_type": 1,
            "ch": self._get_channel(),
            "E_ac": convert_si_integer_full(float(self.var_eac.get())),
            "f_max": convert_si_integer_full(float(self.var_fmax.get())),
            "f_min": convert_si_integer_full(float(self.var_fmin.get())),
            "n_freq": int(float(self.var_nfreq.get())),
            "E_dc": convert_si_integer_full(float(self.var_edc.get())),
            "E_con1": convert_si_integer_full(float(self.var_econ1.get())),
            "t_con1": self._fmt_time(self.var_tcon1.get()),
            "E_con2": convert_si_integer_full(float(self.var_econ2.get())),
            "t_con2": self._fmt_time(self.var_tcon2.get()),
        }

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
        )

    def callback_show_script(self):
        if not self._phase1_ok():
            return
        try:
            script = self.generate_methodscript()
        except ValueError:
            self._set_status("Error: check input values.")
            return
        self.script_box.grid(row=2, column=0, padx=(5, 15), pady=10, sticky="nswe")
        self.script_box.delete("1.0", "end")
        self.script_box.insert("end", script)

    def _phase1_ok(self):
        if self.scan_selector.current() != 0 or self.freq_selector.current() != 0:
            self._set_status("Only 'Default' scan + 'Scan' frequency are implemented for now.")
            return False
        return True

    def send_script(self):
        if not self._phase1_ok():
            return
        try:
            self.generate_payload()
        except ValueError:
            self._set_status("Error: check input values.")
            return
        self.frame_entries.grid_forget()
        self.script_box.grid_forget()
        ip_sender = self.callback_ip() if self.callback_ip else "localhost"
        self.udp_plotter.update_val_experiment(
            x_key="Z_real",
            y_key="Z_imag",
            payload=self.payload,
            ip_sender=ip_sender,
            callback_spin_motor=None,
        )
        self.frame_plotter.grid(row=1, column=0, padx=5, pady=2, sticky="nsew")
        if self.frame_w_scroll:
            self.frame_w_scroll.yview_moveto(0)

    def show_inputs_frame(self):
        if self.frame_w_scroll:
            self.frame_w_scroll.yview_moveto(0)
        self.frame_entries.grid(row=0, column=0, sticky="nsew")
        self.frame_plotter.grid_forget()

    def on_end_experiment(self, thread_motor=None):
        self.show_inputs_frame()
        print("EIS experiment finished.")

    def _set_status(self, msg):
        self.lbl_status.configure(text=msg)


if __name__ == "__main__":
    app = ttk.Window(themename="flatly")
    app.title("Electrochemical Impedance Spectroscopy")
    app.geometry("900x700")
    EISFrame(app).pack(fill="both", expand=True)
    app.mainloop()
