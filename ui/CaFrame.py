# -*- coding: utf-8 -*-

import ttkbootstrap as ttk

from Drivers.EmstatUtils import construct_ca_script
from templates.constants import font_entry
from templates.utils import convert_si_integer_full
from ui.ElectrochemProjectBar import ElectrochemProjectBarMixin
from ui.EventEmstatFrame import EventPlotter
from ui.KeyboardFrame import NumericKeyboard
from ui.ShowMethodScript import ShowMethodScript

__author__ = "Edisson A. Naula"
__date__ = "$ 24/06/2026 at 12:00 p.m. $"

# Valores por defecto (receta canónica del ejemplo: escalón a 0.5 V, intervalo
# 0.1 s, 10 s de corrida). max_bw 58505e-3 -> "58505m" (valor de PSTrace; editable).
DEF_T_EQUIL = "0"
DEF_E_DC = "0.5"
DEF_T_INTERVAL = "0.1"
DEF_T_RUN = "10"
DEF_MAX_BW = "58505e-3"

# Mismo selector de rango de corriente que CV/SQWV (radio horizontal).
CURRENT_RANGES = {
    "100 nA": 4.7e-8,  # 47 nA
    "2 uA": 917969e-12,  # 917.969 nA
    "4 uA": 4.7e-6,  # 4.7 µA
    "8 uA": 9.7e-6,  # 9.7 µA
    "16 uA": 19e-6,  # ~19 µA
    "32 uA": 47e-6,  # 47 µA
    "63 uA": 100e-6,  # 100 µA
    "125 uA": 190e-6,  # 190 µA
    "250 uA": 470e-6,  # 470 µA
    "500 uA": 918e-6,  # 918 µA
    "1 mA": 1.0e-3,  # 1 mA
}


class CAFrame(ElectrochemProjectBarMixin, ttk.Frame):
    """Frame de Cronoamperometría (CA).

    Escalón de potencial a ``E_dc`` constante, muestreado cada ``t_interval`` durante
    ``t_run`` (con un pre-loop de equilibrio opcional a 200m). Estructura análoga a
    CV/SQWV/EIS: entradas -> payload -> EventPlotter (streaming TCP). El plot es
    corriente vs tiempo (I vs t); el eje ``t`` se sintetiza en el host (el dato solo
    trae potencial/corriente). El canal de electrodo llega vía callback_get_channel.

    CA se usa típicamente como paso intermedio de acondicionamiento entre corridas de
    SQWV. Ver docs/ca_cronoamperometria.md.
    """

    project_method = "ca"

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
        self.var_tequil = ttk.StringVar(value=DEF_T_EQUIL)
        self.var_edc = ttk.StringVar(value=DEF_E_DC)
        self.var_tinterval = ttk.StringVar(value=DEF_T_INTERVAL)
        self.var_trun = ttk.StringVar(value=DEF_T_RUN)
        self.var_maxbw = ttk.StringVar(value=DEF_MAX_BW)
        self.current_range = ttk.StringVar(value="4.7e-8")
        # Duración estimada (solo lectura): t_equilibrium + t_run.
        self.var_est_time = ttk.StringVar(value="—")
        for v in (self.var_tequil, self.var_trun):
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

        self._build_inputs(self.frame_entries, row=1)
        self._build_current_range(self.frame_entries, row=2)

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

        # Teclado numérico flotante para todas las entradas editables
        self.keyboard = NumericKeyboard(self, scroll_host=self.frame_w_scroll)
        self.keyboard.attach(self._editable_entries)

        # Plotter: I vs t (x=t_s, y=I_A).
        self.frame_plotter = ttk.LabelFrame(self, text="Live Data Plotter")
        self.frame_plotter.grid(row=1, column=0, padx=5, pady=2, sticky="nsew")
        self.frame_plotter.columnconfigure(0, weight=1)
        self.frame_plotter.rowconfigure(0, weight=1)
        self.frame_plotter.configure(style="Custom.TLabelframe")
        self.udp_plotter = EventPlotter(
            self.frame_plotter,
            "ca",
            tcp_port=5006,
            ip_sender=ip_sender,
            buffer_size=4096,
            max_points=5000,
            update_interval_ms=80,
            title="Chronoamperometry (I vs t)",
            x_label="t (s)",
            y_label="I (A)",
            x_key="t_s",
            y_key="I_A",
            payload=self.payload,
            frames_to_hide=[self.frame_entries],
            on_end_expriment=self.on_end_experiment,
        )
        self.udp_plotter.grid(row=0, column=0, padx=(5, 15), sticky="nsew")
        self.frame_plotter.grid_forget()

        self._recompute_estimate()

        # Auto-carga del proyecto inicial (cascada _last_used -> _last_run -> Default).
        self.load_initial_project()

    # ----------------------------------------------------------------
    # Construcción de widgets
    # ----------------------------------------------------------------
    def _row_entry(self, parent, row, label, var, width=12):
        ttk.Label(parent, text=label, style="Custom.TLabel").grid(
            row=row, column=0, padx=5, pady=4, sticky="e"
        )
        entry = ttk.Entry(parent, font=font_entry, textvariable=var, width=width)
        entry.grid(row=row, column=1, padx=5, pady=4, sticky="we")
        return entry

    def _build_inputs(self, parent, row):
        frame = ttk.LabelFrame(parent, text="Chronoamperometry Settings")
        frame.grid(row=row, column=0, padx=(5, 20), pady=6, sticky="nswe")
        frame.configure(style="Custom.TLabelframe")
        frame.columnconfigure(1, weight=1)
        e1 = self._row_entry(frame, 0, "t equilibrium (s):", self.var_tequil)
        e2 = self._row_entry(frame, 1, "E dc (V):", self.var_edc)
        e3 = self._row_entry(frame, 2, "t interval (s):", self.var_tinterval)
        e4 = self._row_entry(frame, 3, "t run (s):", self.var_trun)
        e5 = self._row_entry(frame, 4, "Max bandwidth (Hz):", self.var_maxbw)
        # Duración estimada (solo lectura): t_equilibrium + t_run.
        ttk.Label(frame, text="Est. duration:", style="Custom.TLabel").grid(
            row=5, column=0, padx=5, pady=(0, 5), sticky="e"
        )
        ttk.Label(frame, textvariable=self.var_est_time, style="Custom.TLabel").grid(
            row=5, column=1, padx=5, pady=(0, 5), sticky="w"
        )
        self._editable_entries = [e1, e2, e3, e4, e5]

    def _build_current_range(self, parent, row):
        frame = ttk.LabelFrame(parent, text="Current Range")
        frame.grid(row=row, column=0, padx=(5, 20), pady=6, sticky="nswe")
        frame.configure(style="Custom.TLabelframe")
        frame.columnconfigure(tuple(range(len(CURRENT_RANGES))), weight=1)
        for col, (text, value) in enumerate(CURRENT_RANGES.items()):
            ttk.Radiobutton(
                frame,
                text=text,
                value=value,
                variable=self.current_range,
                style="Custom.TRadiobutton",
            ).grid(row=0, column=col, padx=5, pady=5, sticky="nswe")

    # ----------------------------------------------------------------
    # Duración estimada
    # ----------------------------------------------------------------
    def _recompute_estimate(self, *args):
        """Refresca el indicador de duración estimada (t_equilibrium + t_run)."""
        try:
            t_eq = max(0.0, float(self.var_tequil.get()))
            t_run = float(self.var_trun.get())
            if t_run <= 0:
                raise ValueError
            self.var_est_time.set("~" + self._fmt_duration(t_eq + t_run))
        except (ValueError, AttributeError):
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

    # ----------------------------------------------------------------
    # Payload / script
    # ----------------------------------------------------------------
    def _get_channel(self):
        """Canal de electrodo (0-7) para el payload. Degrada a 0 si no hay callback.

        El firmware valida el rango; aquí solo garantizamos un int válido.
        """
        if self.callback_get_channel is None:
            return 0
        try:
            return int(self.callback_get_channel())
        except Exception:
            return 0

    def generate_payload(self):
        """Construye el payload de CA. Lanza ValueError ante entradas inválidas.

        Calcula aquí los auxiliares que el firmware solo reenvía: el potencial fijo
        del ``da`` (= E_dc), la duración del loop principal (``t_run + t_interval``,
        un intervalo extra para incluir el punto en t=t_run), y los topes max_time_s
        / idle_s del watchdog (CA con t_interval chico genera muchos paquetes).
        """
        t_eq = float(self.var_tequil.get())
        e_dc = float(self.var_edc.get())
        t_int = float(self.var_tinterval.get())
        t_run = float(self.var_trun.get())
        m_bw = float(self.var_maxbw.get())
        cr = float(self.current_range.get())
        if t_int <= 0 or t_run <= 0 or t_eq < 0:
            raise ValueError("invalid CA timing")

        e_dc_si = convert_si_integer_full(e_dc)
        cr_si = convert_si_integer_full(cr)
        # Duración del loop principal = t_run + t_interval (endpoint inclusivo del
        # loop semiabierto). round() evita que el error flotante de la suma deje a
        # convert_si_integer_full sin un prefijo entero.
        t_run_main = round(t_run + t_int, 9)
        max_time_s = int((t_eq + t_run) * 1.5 + 60)
        # Idle entre paquetes: el EmStat emite uno por punto cada t_interval (y 200m
        # en el equilibrio). idle_s cubre el hueco más grande con margen.
        worst_gap = max(t_int, 0.2 if t_eq > 0 else 0.0)
        idle_s = int(worst_gap * 1.5 + 15)

        self.payload = {
            "method": "ca",
            "t_e": "" if t_eq == 0 else convert_si_integer_full(t_eq),
            "E_dc": e_dc_si,
            "t_i": convert_si_integer_full(t_int),
            "t_r": convert_si_integer_full(t_run_main),
            "m_b": convert_si_integer_full(m_bw),
            "min_da": e_dc_si,
            "max_da": e_dc_si,
            "range_ba": cr_si,
            "ba_1": cr_si,
            "ba_2": cr_si,
            "ch": self._get_channel(),
            "max_time_s": max_time_s,
            "idle_s": idle_s,
        }

    def generate_methodscript(self):
        self.generate_payload()
        return construct_ca_script(
            self.payload["t_e"],
            self.payload["E_dc"],
            self.payload["t_i"],
            self.payload["t_r"],
            self.payload["m_b"],
            self.payload["min_da"],
            self.payload["max_da"],
            self.payload["range_ba"],
            self.payload["ba_1"],
            self.payload["ba_2"],
        )

    def callback_show_script(self):
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

    def send_script(self):
        try:
            self.generate_payload()
        except ValueError:
            self._set_status("Error: check input values.")
            return
        # Snapshot de lo que se va a correr -> _last_run.
        self.snapshot_current_run()
        self.frame_project.grid_forget()
        self.frame_entries.grid_forget()
        ip_sender = self.callback_ip() if self.callback_ip else "localhost"
        # Watchdog del plotter: derivado del idle de ESTA corrida + margen, para que
        # el terminal del firmware (emstat_end/timeout) SIEMPRE le gane al watchdog.
        self.udp_plotter.watchdog_timeout = float(self.payload["idle_s"]) + 15.0
        # parser "ca": eje de tiempo sintetizado en el host. ca_has_equil le dice al
        # parser que hay un loop de equilibrio que excluir (detectado por el '*').
        try:
            t_int = float(self.var_tinterval.get())
            t_eq = float(self.var_tequil.get())
        except ValueError:
            t_int, t_eq = 0.0, 0.0
        self.udp_plotter.update_val_experiment(
            x_key="t_s",
            y_key="I_A",
            payload=self.payload,
            ip_sender=ip_sender,
            callback_spin_motor=None,
            parser_kwargs={"ca_t_interval": t_int, "ca_has_equil": t_eq > 0},
        )
        self.frame_plotter.grid(row=1, column=0, padx=5, pady=2, sticky="nsew")
        if self.frame_w_scroll:
            self.frame_w_scroll.yview_moveto(0)

    def show_inputs_frame(self):
        if self.frame_w_scroll:
            self.frame_w_scroll.yview_moveto(0)
        self.frame_project.grid(row=0, column=0, sticky="nswe", padx=(5, 20), pady=(5, 0))
        self.frame_entries.grid(row=1, column=0, sticky="nsew")

    # ----- Hooks de proyecto (ver ui/ElectrochemProjectBar.py) -----
    def collect_values(self):
        """Estado completo del formulario CA -> dict de claves canónicas."""
        return {
            "t_equil": self.var_tequil.get(),
            "E_dc": self.var_edc.get(),
            "t_interval": self.var_tinterval.get(),
            "t_run": self.var_trun.get(),
            "max_bw": self.var_maxbw.get(),
            "current_range": self.current_range.get(),
        }

    def apply_values(self, values):
        """Vuelca un proyecto CA en los widgets."""
        self.var_tequil.set(str(values.get("t_equil", "")))
        self.var_edc.set(str(values.get("E_dc", "")))
        self.var_tinterval.set(str(values.get("t_interval", "")))
        self.var_trun.set(str(values.get("t_run", "")))
        self.var_maxbw.set(str(values.get("max_bw", "")))
        self.current_range.set(str(values.get("current_range", "4.7e-8")))
        self._recompute_estimate()

    def on_end_experiment(self, thread_motor=None):
        self.show_inputs_frame()
        print("CA experiment finished.")

    def _set_status(self, msg):
        self.lbl_status.configure(text=msg)


if __name__ == "__main__":
    app = ttk.Window(themename="flatly")
    app.title("Chronoamperometry")
    app.geometry("900x700")
    CAFrame(app).pack(fill="both", expand=True)
    app.mainloop()
