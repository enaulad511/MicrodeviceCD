# -*- coding: utf-8 -*-
import threading

from Drivers.EmstatUtils import construc_individual_script_sqwv
from templates.utils import convert_si_integer_full, read_settings_from_file
from ui.ElectrochemProjectBar import ElectrochemProjectBarMixin
from ui.EventEmstatFrame import EventPlotter
from ui.ShowMethodScript import ShowMethodScript

__author__ = "Edisson A. Naula"
__date__ = "$ 11/11/2025 at 15:00 p.m. $"

import matplotlib.pyplot as plt
import ttkbootstrap as ttk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from templates.constants import font_entry  # Ajusta si no tienes este archivo
from ui.KeyboardFrame import NumericKeyboard

LABELS = [
    "t equilibration (s):",
    "E begin (V):",
    "E end (V):",
    "E step (V):",
    "Amplitude (V):",
    "Frequency (Hz):",
    "Max bandwidth (Hz):",
    "Min DA (V):",
    "Max DA (V):",
    # "Range BA:",
    # "Auto BA1:",
    # "Auto BA2:",
]
DEFAULT = [
    "0",
    "-0.5",
    "0.5",
    "0.01",
    "0.1",
    "20",
    "234021e-3",
    "-0.6",
    "0.6",
    "47e-9",
    "47e-9",
    "47e-9",
    "47e-9",
]
LABELS_PRE = {
    "E condition": "0",
    "t condition": "0",
    "E deposition": "0",
    "t deposition": "0",
}

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

# Serializa el arranque del hilo del motor (mismo patron que ui/CvFrame.py).
thread_lock = threading.Lock()


class ShowProfileFrame(ttk.Toplevel):
    """Perfil esquematico del SWV en ventana aparte (mismo patron que CvFrame).

    No se dibuja la senal completa (con E_step tipico son ~100 steps y se ve
    como una banda solida): solo los primeros N_SCHEMATIC steps, o todos si el
    experimento tiene <= MAX_FULL_STEPS. Las fases previas (condition,
    deposition, equilibration) se dibujan con ancho fijo si su t > 0. El eje X
    NO esta a escala; los tiempos reales van en las cotas y el titulo.
    """

    MAX_FULL_STEPS = 5
    N_SCHEMATIC = 3

    def __init__(
        self,
        parent,
        t_equilibration,
        e_begin,
        e_end,
        e_step,
        amplitude,
        freq,
        e_con,
        t_con,
        e_dep,
        t_dep,
    ):
        super().__init__(parent)
        self.title("SWV Profile Preview")
        self.parent = parent

        t_interval = 1 / (2 * freq)
        direction = 1 if e_end >= e_begin else -1
        e_step_abs = abs(e_step)
        total_steps = int(round(abs(e_end - e_begin) / e_step_abs)) + 1
        # Escalon dibujado: con valores tipicos (E_step 0.01 V vs pulso 0.2 V
        # pico a pico) la escalera es invisible y el perfil parece una onda
        # cuadrada plana. Si E_step queda chico junto a la amplitud se exagera
        # solo el dibujo; la cota sigue mostrando el valor real.
        step_draw = (
            e_step_abs if amplitude <= 0 else max(e_step_abs, 0.6 * amplitude)
        )
        exaggerated = step_draw > e_step_abs
        # Con escalon exagerado la escalera ya no aterriza en E_end, asi que se
        # usa siempre el modo truncado (pocos steps + flecha de continuacion).
        truncated = total_steps > self.MAX_FULL_STEPS or (
            exaggerated and total_steps > self.N_SCHEMATIC
        )
        n_draw = min(self.N_SCHEMATIC, total_steps) if truncated else total_steps
        w = 2 * t_interval  # un step completo (forward + reverse)

        self.fig, ax = plt.subplots(figsize=(8, 4.5))

        # Orden real del MethodSCRIPT: condition -> deposition -> equilibration
        pre_phases = [
            ("Cond.", e_con, t_con, "darkcyan"),
            ("Dep.", e_dep, t_dep, "saddlebrown"),
            ("Equil.", e_begin, t_equilibration, "purple"),
        ]
        base_last = e_begin + (n_draw - 1) * step_draw * direction
        pot_refs = [e_begin, e_end]
        pot_refs += [pot for _, pot, dur, _ in pre_phases if dur > 0]
        pot_refs += [
            e_begin + amplitude,
            e_begin - amplitude,
            base_last + amplitude,
            base_last - amplitude,
        ]
        span = (max(pot_refs) - min(pot_refs)) or 1.0

        x = 0.0
        prev_pot = None
        for name, pot, dur, color in pre_phases:
            if dur <= 0:
                continue
            if prev_pot is not None:
                ax.plot([x, x], [prev_pot, pot], color="blue", linewidth=2)
            ax.plot([x, x + w], [pot, pot], color="blue", linewidth=2)
            ax.text(
                x + w / 2,
                pot + 0.04 * span,
                f"{name} {dur:g} s @ {pot:g} V",
                ha="center",
                color=color,
                fontsize=8,
            )
            x += w
            prev_pot = pot

        x0 = x  # inicio de los pulsos SWV
        for i in range(n_draw):
            base = e_begin + i * step_draw * direction
            fwd, rev = base + amplitude, base - amplitude
            if prev_pot is not None:
                ax.plot([x, x], [prev_pot, fwd], color="blue", linewidth=2)
            ax.plot([x, x + t_interval], [fwd, fwd], color="blue", linewidth=2)
            ax.plot(
                [x + t_interval, x + t_interval], [fwd, rev], color="blue", linewidth=2
            )
            ax.plot([x + t_interval, x + w], [rev, rev], color="blue", linewidth=2)
            prev_pot = rev
            x += w

        # Etiquetas Forward/Reverse solo en el primer step
        fwd0 = e_begin + amplitude
        rev0 = e_begin - amplitude
        ax.text(
            x0 + t_interval / 2,
            fwd0 + 0.04 * span,
            "Forward",
            ha="center",
            color="orange",
            fontsize=8,
        )
        ax.text(
            x0 + 1.5 * t_interval,
            rev0 - 0.09 * span,
            "Reverse",
            ha="center",
            color="green",
            fontsize=8,
        )

        # Cota 2*Amplitude (altura pico a pico del pulso)
        x_amp = x0 + 1.5 * t_interval
        ax.annotate(
            "",
            xy=(x_amp, fwd0),
            xytext=(x_amp, rev0),
            arrowprops=dict(arrowstyle="<->", color="black"),
        )
        ax.text(
            x_amp + 0.15 * t_interval,
            e_begin,
            f"2·Amp = {2 * amplitude:g} V",
            va="center",
            fontsize=8,
        )

        # Cota E_step: referencia punteada al nivel forward del step 1
        if n_draw >= 2:
            fwd1 = fwd0 + step_draw * direction
            ax.plot(
                [x0, x0 + w + t_interval],
                [fwd0, fwd0],
                color="gray",
                linestyle=":",
                linewidth=1,
            )
            x_es = x0 + w + 0.5 * t_interval
            ax.annotate(
                f"E step = {e_step_abs:g} V" + (" (enlarged)" if exaggerated else ""),
                xy=(x_es, (fwd0 + fwd1) / 2),
                xytext=(x_es + 0.6 * t_interval, fwd1 + 0.12 * span),
                arrowprops=dict(arrowstyle="->", color="black"),
                fontsize=8,
            )

        # Cota t_interval bajo el primer pulso forward
        y_t = min(pot_refs) - 0.12 * span
        ax.annotate(
            "",
            xy=(x0, y_t),
            xytext=(x0 + t_interval, y_t),
            arrowprops=dict(arrowstyle="<->", color="black"),
        )
        ax.text(
            x0 + t_interval / 2,
            y_t - 0.06 * span,
            f"t_interval = {t_interval:.4g} s",
            ha="center",
            fontsize=8,
        )

        # Indicador de continuacion hacia E_end
        if truncated:
            ax.annotate(
                "",
                xy=(x + 1.5 * w, e_end),
                xytext=(x + 0.3 * w, base_last),
                arrowprops=dict(arrowstyle="->", color="red", linestyle="--"),
            )
            ax.text(
                x + 0.9 * w,
                (base_last + e_end) / 2,
                f"+{total_steps - n_draw} steps",
                color="red",
                fontsize=8,
                ha="center",
                va="bottom",
            )

        x_max = x + (2.0 * w if truncated else 0.6 * w)
        ax.set_xlim(-0.3 * w, x_max)
        ax.axhline(e_begin, color="gray", linestyle=":", linewidth=1)
        ax.axhline(e_end, color="red", linestyle=":", linewidth=1)
        ax.text(
            x_max, e_begin, f"E_begin {e_begin:g} V", color="gray", fontsize=8,
            ha="right", va="bottom",
        )
        ax.text(
            x_max, e_end, f"E_end {e_end:g} V", color="red", fontsize=8,
            ha="right", va="bottom",
        )
        ax.set_ylim(min(pot_refs) - 0.25 * span, max(pot_refs) + 0.15 * span)

        dur_total = t_con + t_dep + t_equilibration + total_steps * w
        head = (
            f"SWV Profile (schematic — first {n_draw} of {total_steps} steps)"
            if truncated
            else "SWV Profile (schematic)"
        )
        ax.set_title(
            head + "\n"
            f"{total_steps} steps · t_interval = {t_interval:.4g} s · "
            f"total ≈ {dur_total:.4g} s · E: {e_begin:g} → {e_end:g} V @ {freq:g} Hz",
            fontsize=10,
        )
        ax.set_xlabel("Time (not to scale)")
        ax.set_ylabel("Potential (not to scale)")
        ax.set_xticks([])
        ax.set_yticks([])
        self.fig.tight_layout()

        self.canvas = FigureCanvasTkAgg(self.fig, master=self)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def destroy(self):
        # liberar la figura tambien cuando se destruye sin pasar por on_close
        plt.close(self.fig)
        super().destroy()

    def on_close(self):
        self.parent.on_close_profile_window()
        self.destroy()


def create_widgets_swv(parent, callbacks, n_cols=2):
    frame = ttk.LabelFrame(parent, text="Square Wave Voltammetry Settings")
    frame.grid(row=0, column=0, padx=10, pady=10, sticky="nswe")
    frame.columnconfigure(0, weight=1)
    frame.configure(style="Custom.TLabelframe")
    entries_pre = []
    frame_pre = ttk.LabelFrame(frame, text="Pre-treatment")
    frame_pre.grid(row=0, column=0, padx=10, pady=10, sticky="nswe")
    frame_pre.columnconfigure(tuple(range(4)), weight=1)
    frame_pre.configure(style="Custom.TLabelframe")
    for i, (lbl, val) in enumerate(LABELS_PRE.items()):
        row = i // 2
        col = i % 2
        ttk.Label(frame_pre, text=lbl).grid(row=row, column=col * 2, padx=5, pady=5)
        entry = ttk.Entry(frame_pre, font=font_entry)
        entry.insert(0, val)
        entry.grid(row=row, column=col * 2 + 1, padx=5, pady=5, sticky="we")
        entries_pre.append(entry)

    frame_entries = ttk.LabelFrame(frame, text="Parameters")
    frame_entries.grid(row=1, column=0, padx=10, pady=10, sticky="nswe")
    frame_entries.columnconfigure(tuple(range(n_cols * 2)), weight=1)
    frame_entries.configure(style="Custom.TLabelframe")
    entries = []
    for i, lbl in enumerate(LABELS):
        col = i % n_cols
        row = i // n_cols
        # cada parámetro usa 2 columnas reales
        base_col = col * 2
        ttk.Label(frame_entries, text=lbl).grid(
            row=row, column=base_col, padx=5, pady=5, sticky="e"
        )
        entry = ttk.Entry(frame_entries, font=font_entry)
        entry.insert(0, DEFAULT[i])
        entry.grid(row=row, column=base_col + 1, padx=5, pady=5, sticky="we")

        entries.append(entry)
    # hacer que las columnas de Entry se expandan
    for c in range(n_cols * 2):
        frame_entries.columnconfigure(c, weight=1)

    # Checkbox para medir i_forward/i_reverse
    measure_var = ttk.BooleanVar(value=False)
    ttk.Checkbutton(frame_entries, text="Measure i forward/reverse", variable=measure_var).grid(
        row=len(LABELS), column=0, columnspan=2, pady=5
    )
    # ===== CURRENT RANGE SELECTOR =====
    frame_selectors = ttk.LabelFrame(frame, text="Current Range")
    frame_selectors.grid(row=2, column=0, padx=(5, 20), pady=10, sticky="nswe")
    frame_selectors.configure(style="Custom.TLabelframe")
    # NEW: variable compartida para los radio buttons
    current_range_var = ttk.StringVar(value="4.7e-8")  # valor por defecto
    # NEW: creación horizontal de radio buttons
    for col, (text, value) in enumerate(CURRENT_RANGES.items()):
        ttk.Radiobutton(
            frame_selectors,
            text=text,
            value=value,
            variable=current_range_var,
        ).grid(row=0, column=col, padx=5, pady=5, sticky="nswe")
    frame_selectors.columnconfigure(tuple(range(len(CURRENT_RANGES))), weight=1)

    # -----------------------------Motor Settings-------------------------------------
    # Espejo de ui/CvFrame.py: oscilador (±angle) durante el PRE-TRATAMIENTO. A
    # diferencia de CV (motor toda la corrida), aqui el motor solo se mueve en
    # condition + deposition y se detiene en la equilibracion/barrido (ver send_script).
    entries_motor: list = []
    frame_motor_settings = ttk.LabelFrame(frame, text="Motor Settings")
    frame_motor_settings.grid(row=3, column=0, padx=(5, 20), pady=10, sticky="nswe")
    frame_motor_settings.columnconfigure((0, 1), weight=1)
    frame_motor_settings.configure(style="Custom.TLabelframe")
    enable_motor = ttk.BooleanVar(value=False)
    ttk.Checkbutton(
        frame_motor_settings,
        text="Enable Motor (pre-treatment only)",
        variable=enable_motor,
        style="Custom.TCheckbutton",
    ).grid(row=0, column=0, columnspan=2, padx=5, pady=5, sticky="n")
    entries_motor.append(enable_motor)

    ttk.Label(frame_motor_settings, text="Angle (°, max 30):", style="Custom.TLabel").grid(
        row=1, column=0, padx=5, pady=5, sticky="w"
    )
    svar_angle = ttk.StringVar(value="10")
    angle_entry = ttk.Entry(frame_motor_settings, font=font_entry, textvariable=svar_angle, width=5)
    angle_entry.grid(row=1, column=1, padx=5, pady=5, sticky="w")
    entries_motor.append(svar_angle)

    ttk.Label(frame_motor_settings, text="Speed (%):", style="Custom.TLabel").grid(
        row=2, column=0, padx=5, pady=5, sticky="w"
    )
    svar_speed = ttk.StringVar(value="7")
    speed_entry = ttk.Entry(frame_motor_settings, font=font_entry, textvariable=svar_speed, width=5)
    speed_entry.grid(row=2, column=1, padx=5, pady=5, sticky="w")
    entries_motor.append(svar_speed)

    motor_entry_widgets = [angle_entry, speed_entry]
    return entries, measure_var, current_range_var, entries_pre, entries_motor, motor_entry_widgets


def create_buttons_sqwv(parent, callbacks):
    # ===== CONTROL BUTTONS =====
    frame_buttons = ttk.LabelFrame(parent, text="Actions")
    frame_buttons.grid(row=1, column=0, pady=10, sticky="nswe")
    frame_buttons.columnconfigure((0, 1, 2, 3), weight=1)
    frame_buttons.configure(style="Custom.TLabelframe")
    ttk.Button(
        frame_buttons,
        text="📈",
        style="info.TButton",
        command=callbacks["callback_generate_profile"],
    ).grid(row=0, column=0, pady=10, sticky="n")
    ttk.Button(
        frame_buttons,
        text="🗒️MethodScript",
        style="info.TButton",
        command=callbacks["callback_show_script"],
    ).grid(row=0, column=1, pady=10, sticky="n")
    ttk.Button(
        frame_buttons,
        text="⏫Send Script",
        style="info.TButton",
        command=callbacks["callback_send"],
    ).grid(row=0, column=2, pady=10, sticky="n")
    ttk.Button(
        frame_buttons,
        text="Show Inputs",
        style="danger.TButton",
        command=callbacks["callback_show_inputs"],
    ).grid(row=0, column=3, pady=10, sticky="n")


class SWVFrame(ElectrochemProjectBarMixin, ttk.Frame):
    project_method = "sqwv"

    def __init__(
        self,
        parent,
        ip_sender="localhost",
        callback_get_ip_sender=None,
        callback_get_channel=None,
        frame_with_scroll=None,
    ):
        ttk.Frame.__init__(self, parent)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.callback_ip = callback_get_ip_sender
        self.callback_get_channel = callback_get_channel
        self.frame_w_scroll = frame_with_scroll
        self.ShowMethodScrit = None
        self.ShowProfile: ShowProfileFrame | None = None
        # Estado del motor (oscilador durante el pre-tratamiento). Espejo de CvFrame,
        # mas un Timer que corta el motor al terminar condition+deposition.
        self.thread_motor: threading.Thread | None = None
        self.stop_event: threading.Event | None = None
        self.pretreat_timer: threading.Timer | None = None
        self._pretreat_duration = 0.0

        content_frame = ttk.Frame(self)
        content_frame.grid(row=0, column=0, sticky="nsew")
        content_frame.columnconfigure(0, weight=1)

        # Barra de proyecto (row 0, encima de las entradas).
        self.frame_project = self.build_project_bar(content_frame)
        self.frame_project.grid(row=0, column=0, sticky="nswe", padx=10, pady=(5, 0))

        self.frame_entries = ttk.Frame(content_frame)
        self.frame_entries.grid(row=1, column=0, sticky="nsew")
        self.frame_entries.columnconfigure(0, weight=1)
        callbacks = {
            "callback_generate_profile": self.callback_generate_profile,
            "callback_show_script": self.callback_show_methodscript,
            "callback_send": self.send_script,
            "callback_show_inputs": self.show_inputs_frame,
        }
        (
            self.entries,
            self.measure_var,
            self.current_range,
            self.entries_pre,
            self.entries_motor,
            motor_entry_widgets,
        ) = create_widgets_swv(self.frame_entries, callbacks)
        self.keyboard = NumericKeyboard(self, scroll_host=self.frame_w_scroll)
        self.keyboard.attach(list(self.entries) + list(self.entries_pre) + motor_entry_widgets)
        self.frame_buttons = ttk.Frame(content_frame)
        self.frame_buttons.grid(row=2, column=0, sticky="nsew")
        self.frame_buttons.columnconfigure(0, weight=1)
        create_buttons_sqwv(self.frame_buttons, callbacks)

        self.frame_plotter = ttk.LabelFrame(self, text="Live Data Plotter")
        self.frame_plotter.grid(row=4, column=0, padx=10, pady=10, sticky="nsew")
        self.frame_plotter.columnconfigure(0, weight=1)
        self.frame_plotter.configure(style="Custom.TLabelframe")
        self.generate_payload()
        self.udp_plotter = EventPlotter(
            self.frame_plotter,
            "sqwv",
            tcp_port=5006,
            ip_sender=ip_sender,
            buffer_size=4096,
            max_points=5000,
            update_interval_ms=80,
            payload=self.payload,
            frames_to_hide=[self.frame_entries],
            on_end_expriment=self.on_end_experiment,
        )
        self.udp_plotter.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        self.frame_plotter.grid_forget()

        # Auto-carga del proyecto inicial (cascada _last_used -> _last_run -> Default).
        self.load_initial_project()

    def show_inputs_frame(self):
        if self.frame_w_scroll:
            self.frame_w_scroll.yview_moveto(0)
        self.frame_project.grid(row=0, column=0, sticky="nswe", padx=10, pady=(5, 0))
        self.frame_entries.grid(row=1, column=0, sticky="nsew")

    # ----- Hooks de proyecto (ver ui/ElectrochemProjectBar.py) -----
    def collect_values(self):
        """Estado completo del formulario SWV -> dict de claves canónicas."""
        ek = [
            "t_equil", "E_begin", "E_end", "E_step", "amplitude", "freq",
            "max_bw", "min_da", "max_da",
        ]
        pre = ["E_con", "t_con", "E_dep", "t_dep"]
        values = {k: self.entries[i].get() for i, k in enumerate(ek)}
        values.update({k: self.entries_pre[i].get() for i, k in enumerate(pre)})
        values["measure"] = str(bool(self.measure_var.get()))
        values["current_range"] = self.current_range.get()
        values["motor_enable"] = str(bool(self.entries_motor[0].get()))
        values["motor_angle"] = self.entries_motor[1].get()
        values["motor_speed"] = self.entries_motor[2].get()
        return values

    def apply_values(self, values):
        """Vuelca un proyecto SWV en los widgets."""
        ek = [
            "t_equil", "E_begin", "E_end", "E_step", "amplitude", "freq",
            "max_bw", "min_da", "max_da",
        ]
        pre = ["E_con", "t_con", "E_dep", "t_dep"]
        for i, k in enumerate(ek):
            self.entries[i].delete(0, "end")
            self.entries[i].insert(0, str(values.get(k, "")))
        for i, k in enumerate(pre):
            self.entries_pre[i].delete(0, "end")
            self.entries_pre[i].insert(0, str(values.get(k, "")))
        self.measure_var.set(str(values.get("measure", "False")) == "True")
        self.current_range.set(str(values.get("current_range", "4.7e-8")))
        self.entries_motor[0].set(str(values.get("motor_enable", "False")) == "True")
        self.entries_motor[1].set(str(values.get("motor_angle", "10")))
        self.entries_motor[2].set(str(values.get("motor_speed", "7")))

    def callback_generate_profile(self):
        try:
            t_equilibration = float(self.entries[0].get())
            e_begin = float(self.entries[1].get())
            e_end = float(self.entries[2].get())
            e_step = float(self.entries[3].get())
            amplitude = float(self.entries[4].get())
            freq = float(self.entries[5].get())
            e_con = float(self.entries_pre[0].get())
            t_con = float(self.entries_pre[1].get())
            e_dep = float(self.entries_pre[2].get())
            t_dep = float(self.entries_pre[3].get())
        except ValueError:
            print("Error: Check input values.")
            return
        if freq <= 0 or e_step == 0:
            print("Error: Frequency must be > 0 and E step != 0.")
            return
        if self.ShowProfile is not None:
            self.ShowProfile.destroy()
            self.ShowProfile = None
        self.ShowProfile = ShowProfileFrame(
            self,
            t_equilibration,
            e_begin,
            e_end,
            e_step,
            amplitude,
            freq,
            e_con,
            t_con,
            e_dep,
            t_dep,
        )

    def on_close_profile_window(self):
        self.ShowProfile = None

    def callback_show_methodscript(self):
        self.generate_payload()
        script = self.generate_methodscript()
        if self.ShowMethodScrit is not None:
            self.ShowMethodScrit.destroy()
            self.ShowMethodScrit = None
        self.ShowMethodScrit = ShowMethodScript(self, script)

    def on_close_script_window(self):
        self.ShowMethodScrit = None

    def generate_payload(self):
        try:
            t_e = float(self.entries[0].get())
            t_e = "" if t_e == 0 else convert_si_integer_full(t_e)
            t_con = float(self.entries_pre[1].get())
            t_con = "" if t_con == 0 else convert_si_integer_full(t_con)
            t_dep = float(self.entries_pre[3].get())
            t_dep = "" if t_dep == 0 else convert_si_integer_full(t_dep)
        except Exception:
            t_e = ""
            t_con = ""
            t_dep = ""
        self.payload = {
            "t_e": t_e,
            "E_b": convert_si_integer_full(float(self.entries[1].get())),
            "E_e": convert_si_integer_full(float(self.entries[2].get())),
            "E_s": convert_si_integer_full(float(self.entries[3].get())),
            "Amp": convert_si_integer_full(float(self.entries[4].get())),
            "Freq": convert_si_integer_full(float(self.entries[5].get())),
            "m_b": convert_si_integer_full(float(self.entries[6].get())),
            "min_da": convert_si_integer_full(float(self.entries[7].get())),
            "max_da": convert_si_integer_full(float(self.entries[8].get())),
            "range_ba": convert_si_integer_full(float(self.current_range.get())),
            "ba_1": convert_si_integer_full(float(self.current_range.get())),
            "ba_2": convert_si_integer_full(float(self.current_range.get())),
            "E_con": convert_si_integer_full(float(self.entries_pre[0].get())),
            "t_con": t_con,
            "E_dep": convert_si_integer_full(float(self.entries_pre[2].get())),
            "t_dep": t_dep,
            "ch": self._get_channel(),
            "method": "sqwv",
        }

    def _get_channel(self):
        """Canal de electrodo (0-7) para el payload. Degrada a 0 si no hay callback.

        El firmware v1.6 valida el rango; aqui solo garantizamos un int valido.
        """
        if self.callback_get_channel is None:
            return 0
        try:
            return int(self.callback_get_channel())
        except Exception:
            return 0

    def generate_methodscript(self):
        script = construc_individual_script_sqwv(
            self.payload.get("t_e", DEFAULT[0]),
            self.payload.get("E_b", DEFAULT[1]),
            self.payload.get("E_e", DEFAULT[2]),
            self.payload.get("E_s", DEFAULT[3]),
            self.payload.get("Amp", DEFAULT[4]),
            self.payload.get("Freq", DEFAULT[5]),
            self.payload.get("m_b", DEFAULT[6]),
            self.payload.get("min_da", DEFAULT[7]),
            self.payload.get("max_da", DEFAULT[8]),
            self.payload.get("range_ba", DEFAULT[9]),
            self.payload.get("ba_1", DEFAULT[10]),
            self.payload.get("ba_2", DEFAULT[11]),
            self.payload.get("E_con", LABELS_PRE["E condition"]),
            self.payload.get("t_con", LABELS_PRE["t condition"]),
            self.payload.get("E_dep", LABELS_PRE["E deposition"]),
            self.payload.get("t_dep", LABELS_PRE["t deposition"]),
        )
        return script.strip()

    def send_script(self):
        # Validar ANTES de ocultar las entradas (como CV/CA): si generate_payload
        # falla por una entrada invalida, no dejamos los inputs escondidos sin vuelta.
        try:
            self.generate_payload()
        except ValueError as e:
            print(f"Error: check input values -> {e}")
            return
        # Snapshot de lo que se va a correr -> _last_run.
        self.snapshot_current_run()
        self.frame_project.grid_forget()
        self.frame_entries.grid_forget()
        ip_sender = self.callback_ip() if self.callback_ip else "localhost"

        # Motor durante el PRE-TRATAMIENTO (condition + deposition). Arranca con la
        # corrida (momento de envio, como CV) y se corta con un Timer al cumplir
        # t_con + t_dep. El pre-tratamiento SI emite datos, pero la frontera
        # deposition/equilibracion no tiene marcador directo, asi que se deduce por
        # tiempo; el motor NO debe oscilar en la equilibracion ni en el barrido.
        sent_callback = None
        on_first_data = None
        enable_motor = bool(self.entries_motor[0].get())
        try:
            t_con = float(self.entries_pre[1].get())
            t_dep = float(self.entries_pre[3].get())
        except ValueError:
            t_con = t_dep = 0.0
        self._pretreat_duration = max(t_con, 0.0) + max(t_dep, 0.0)
        if enable_motor and self._pretreat_duration > 0:
            sent_callback = self.start_spin_motor_angle
            # Red de seguridad (Q3): si el Timer no cortara, el primer paquete de BARRIDO
            # (phase != pretreatment, ya pasada la equilibracion) tambien detiene el motor.
            on_first_data = self._stop_motor_on_first_data
            filename_meta = {"ang": self.entries_motor[1].get(), "spd": self.entries_motor[2].get()}
        else:
            filename_meta = {"motor": "off"}

        # Indicador de fase en vivo: el pre-tratamiento no grafica, asi que pasamos las
        # fases presentes (mismas condiciones de presencia que el builder del script) con
        # su duracion para que EventPlotter muestre "Pre-treatment — <fase> n/dur s".
        try:
            t_equil = float(self.entries[0].get())
        except ValueError:
            t_equil = 0.0
        e_con = self.entries_pre[0].get().strip()
        e_dep = self.entries_pre[2].get().strip()
        pretreatment_phases = []
        if t_con > 0 and e_con != "":
            pretreatment_phases.append(["Condition", t_con])
        if t_dep > 0 and e_dep != "":
            pretreatment_phases.append(["Deposition", t_dep])
        if t_equil > 0:
            pretreatment_phases.append(["Equilibration", t_equil])

        self.udp_plotter.update_val_experiment(
            x_key="E_V",
            y_key="I_A",
            payload=self.payload,
            ip_sender=ip_sender,
            callback_spin_motor=sent_callback,
            filename_meta=filename_meta,
            on_first_data=on_first_data,
            pretreatment_phases=pretreatment_phases or None,
        )
        self.frame_plotter.grid(row=4, column=0, padx=10, pady=10, sticky="nsew")
        # Lleva el scroll al inicio para ver el plotter desde arriba (como CV/CA).
        if self.frame_w_scroll:
            self.frame_w_scroll.yview_moveto(0)

    def start_spin_motor_angle(self):
        """Arranca el oscilador (±angle) para el pre-tratamiento y arma el Timer que lo
        detiene al cumplir condition+deposition. Espejo de CvFrame.start_spin_motor_angle
        mas el Timer; lo invoca EventPlotter.start() via callback_spin_motor."""
        settings: dict = read_settings_from_file()
        max_rpm = settings.get("max_rpm", 700)
        print("Iniciar modo oscilador (pre-tratamiento SWV)")
        angle = float(self.entries_motor[1].get())
        speed_percentage = float(self.entries_motor[2].get())
        print(
            f"Ángulo: {angle}°, Velocidad: {speed_percentage:2f}%, "
            f"ventana pre-tratamiento: {self._pretreat_duration:.1f}s"
        )
        if angle > 45:
            print("El ángulo máximo es 45°")
            return
        with thread_lock:
            if self.thread_motor and self.thread_motor.is_alive():
                print("Ya hay un hilo activo, no se puede iniciar otro.")
                return
            self.stop_event = threading.Event() if self.stop_event is None else self.stop_event
            from Drivers.DriverStepperSys import spinMotorAngleDriver

            thread_motor = threading.Thread(
                target=spinMotorAngleDriver,
                args=(
                    angle,
                    speed_percentage * max_rpm / 100,
                    max_rpm,
                    None,
                    True,
                    self.stop_event,
                    None,
                ),
            )
            thread_motor.start()
            # Timer que corta el motor en la frontera deposition/equilibracion. El driver
            # sondea stop_event ~cada 20 ms (DriverStepperSys.py), asi que el corte es pronto.
            self.pretreat_timer = threading.Timer(self._pretreat_duration, self.stop_event.set)
            self.pretreat_timer.daemon = True
            self.pretreat_timer.start()
            print(f"Oscilador iniciado; se detendra en {self._pretreat_duration:.1f}s")
            self.thread_motor = thread_motor
            return thread_motor

    def _stop_motor_on_first_data(self):
        """Red de seguridad: el primer paquete de datos marca el inicio del barrido (ya
        pasado el pre-tratamiento). Si el Timer no corto antes, detiene el motor. Corre
        en el hilo procesador del EventPlotter; solo toca stop_event (thread-safe)."""
        if self.stop_event is not None:
            self.stop_event.set()

    def on_end_experiment(self, thread_motor=None):
        """Limpieza al terminar la corrida (terminal del firmware, Stop, o error). Cancela
        el Timer de pre-tratamiento, detiene el motor y hace join para liberar UART/GPIO
        antes de la siguiente corrida. Lo invoca EventPlotter.stop()."""
        if self.pretreat_timer is not None:
            try:
                self.pretreat_timer.cancel()
            except Exception:
                pass
            self.pretreat_timer = None
        if self.stop_event is not None:
            self.stop_event.set()
        th = thread_motor if thread_motor is not None else self.thread_motor
        if th is not None:
            try:
                if th.is_alive():
                    th.join(timeout=3.0)
                if th.is_alive():
                    print("Warning: motor thread did not finish within 3s.")
            except Exception as e:
                print(f"Error joining motor thread: {e}")
        self.thread_motor = None
        self.stop_event = None
        # Restaura las entradas al terminar (como CV/CA); el plotter sigue visible con
        # el resultado del barrido.
        self.show_inputs_frame()
        print("Experimento SWV finalizado. Motor detenido.")


if __name__ == "__main__":
    app = ttk.Window(themename="flatly")
    app.title("Square Wave Voltammetry")
    app.geometry("900x700")
    SWVFrame(app).pack(fill="both", expand=True)
    app.mainloop()
