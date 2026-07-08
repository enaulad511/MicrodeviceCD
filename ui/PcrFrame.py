# -*- coding: utf-8 -*-

import re
import threading
import time
from datetime import datetime
from tkinter import filedialog

import matplotlib.pyplot as plt
import ttkbootstrap as ttk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
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
    temp_source_labels,
    write_temp_source,
)
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

# Duración de la lectura de fluorescencia (fuente única de verdad).
# Usadas como defaults de _read_fluorescence, en los sleeps previos a cada
# lectura y en la estimación de tiempo restante del experimento.
FLUOR_PRE_SLEEP_S = 0.5  # espera tras el hold de extensión, antes de muestrear
FLUOR_BASELINE_S = 0.5  # ventana de línea base (luz OFF)
FLUOR_LIGHT_S = 2.0  # ventana de excitación (luz ON)
FLUOR_POST_S = 0.5  # ventana de decaimiento (luz OFF)
# Tiempo total que consume una lectura completa (sleep previo + 3 ventanas).
FLUOR_READ_TOTAL_S = FLUOR_PRE_SLEEP_S + FLUOR_BASELINE_S + FLUOR_LIGHT_S + FLUOR_POST_S


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


def _fuzzy_gains(error: float, base_kp: float, base_ki: float) -> tuple:
    """Escala KP/KI dinámicamente según la magnitud del error (fuzzy gain scheduling).

    Tres zonas con interpolación lineal para transiciones suaves:
      |e| >= 15°C  → agresivo (kp×2.0, ki×0.2): rampas largas sin windup
      5 <= |e| < 15 → intermedio: transición suave
      |e| < 5°C    → preciso  (kp×0.5, ki×1.3): regulación cerca del setpoint

    Los factores de escala operan sobre las ganancias base leídas de settings.json,
    por lo que el punto de operación nominal sigue siendo configurable allí.
    """
    abs_error = abs(error)
    if abs_error >= 5.0:
        kp_s, ki_s = 2.0, 0.2
    elif abs_error >= 2.0:
        t = (abs_error - 5.0) / 10.0  # 0..1 de 3°C a 7°C
        kp_s = 1.0 + t * 1.0  # 1.0 → 2.0
        ki_s = 1.0 - t * 0.8  # 0.2 → 1.0
    else:
        t = abs_error / 5.0  # 0..1 de 0°C a 3°C
        kp_s = 0.5 + t * 0.5  # 0.5 → 1.0
        ki_s = 1.3 - t * 0.3  # 1.0 → 1.3
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
    if abs_error >= 5.0:
        return m_age_max
    if abs_error < 2.0:
        return m_age_min
    t = (abs_error - 2.0) / 3.0  # 0..1 de 2°C a 5°C
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


class PCRFrame(ttk.Frame):
    def __init__(self, parent, ads_reader):
        ttk.Frame.__init__(self, parent)
        self.parent = parent
        self.running_experiment = False
        self.pin_heating = None
        self.pin_pcr = None
        self.temp = 0.0
        self.temp_ts = time.time()
        # Fuente de temperatura elegida (termocupla por defecto). El índice apunta
        # al campo del payload UDP (0=IR amb, 1=IR obj, 2=termocupla) y es lo que
        # el lazo PID regula. self.temp_source_bad marca "sensor caído" (se sostiene
        # el último valor y se avisa en el status).
        self.temp_source = read_temp_source()
        self.temp_source_idx = temp_source_index(self.temp_source)
        self.temp_source_bad = False
        self.cbo_temp_source: "ttk.Combobox | None" = None
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.ads = ads_reader
        self.fase = "Initial"
        self.ts_display = 0.5
        self.last_display = time.time()
        self.start_pcr_time = time.time()
        self.cycles_complete = 0
        self.start_cycle_time = time.time()
        self.time_end_cycle = time.time()
        self.total_cycles = 0
        self.teorical_time_pcr = 0
        self.last_cycle_duration = 0.0
        self.avg_cycle_duration = 0.0
        self.ext_time_final = 0.0
        self.stop_event_motor = None
        self.stop_udp_listenner = None
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
        self.prefix_row = "temps_pcr"

        callbacks = {
            "callback_generate_profile": self.callback_generate_profile,
            "callback_start_experiment": self.callback_start_experiment,
            "callback_stop_experiment": self.callback_stop_experiment,
            "callback_save_data": self.save_data_temps_file,
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

        self.canvas = None  # Para almacenar el gráfico incrustado
        self.callback_generate_profile()  # Generar el gráfico inicial
        self.data_temperature = []
        self.data_photodetector = []
        self.data_photodetector_series = []

        # Auto-carga del proyecto inicial (cascada last_used -> last_run -> Default).
        # Al final de __init__: ya existen profile_frame/canvas que usa la preview.
        self._load_initial_project()

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
        self.cbo_temp_source = ttk.Combobox(
            frame,
            values=temp_source_labels(),
            state="readonly",
            font=font_entry,
            width=14,
        )
        self.cbo_temp_source.set(temp_source_label(self.temp_source))
        self.cbo_temp_source.grid(row=0, column=1, padx=5, pady=2, sticky="w")
        self.cbo_temp_source.bind("<<ComboboxSelected>>", self._on_temp_source_changed)

    def _on_temp_source_changed(self, event=None):
        if self.cbo_temp_source is None:
            return
        self.temp_source = temp_source_key(self.cbo_temp_source.get())
        self.temp_source_idx = temp_source_index(self.temp_source)
        self.temp_source_bad = False
        write_temp_source(self.temp_source)

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
            rpm = float(self.entries[5].get())
            denat_time = float(self.entries[6].get())
            denat_temp = float(self.entries[7].get())
            ext_time = float(self.entries[8].get())
            ext_temp = float(self.entries[9].get())
            ext_time_final = float(self.entries[10].get())
            initial_spin_time = float(self.entries[11].get())

            room_temp = 20.0
            transition_const = 10000
            transition_time_down = transition_const / max(rpm, 1)
            # La rampa de calentamiento es proporcional al salto de temperatura
            # (s/°C). Antes era fija (15 s); ahora escala con |ΔT|.
            heating_rate_up = 0.2

            def transition_time_up(t_from, t_to):
                return abs(t_to - t_from) * heating_rate_up

            # Recorte visual de holds largos (denat inicial / ext final): si su
            # duración real supera 1.5x la de un ciclo, se dibujan comprimidos a
            # ese tope para no aplastar los ciclos. Es solo visual: el tiempo real
            # se conserva en la anotación de cada tramo recortado.
            cycle_dur = (
                transition_time_up(ext_temp, high_temp)
                + time_high
                + transition_time_down
                + time_low
                + transition_time_up(low_temp, ext_temp)
                + ext_time
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
                        (current_time, current_time + time_high, high_temp, high_temp, "High", "red")
                    )
                    current_time += time_high
                    current_temp = high_temp

                # Cooling hacia la siguiente fase activa (Low, o Extension si Low se
                # omite). Solo si hay algo más frío hacia lo que enfriar.
                cool_target = (
                    low_temp
                    if not _skip(time_low)
                    else (ext_temp if not _skip(ext_time) else None)
                )
                if cool_target is not None and current_temp > cool_target:
                    phase_segments.append(
                        (
                            current_time,
                            current_time + transition_time_down,
                            current_temp,
                            cool_target,
                            "Cooling",
                            "green",
                        )
                    )
                    current_time += transition_time_down
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

            if self.canvas:
                self.canvas.get_tk_widget().destroy()

            self.canvas = FigureCanvasTkAgg(fig, master=self.profile_frame)
            self.canvas.draw()
            self.canvas.get_tk_widget().pack(fill="both", expand=True)

        except ValueError:
            print("Error: Verifique los valores ingresados.")

    def update_displayed_temperature(self, text, address, temps_list):
        # Solo actualiza datos Python puros — sin operaciones Tkinter.
        # Tkinter no es thread-safe; toda actualización de UI ocurre en _ui_poll_loop.
        # Se lee la fuente elegida (temp_source_idx); si ese sensor viene ausente
        # (None) se sostiene el último valor y se marca temp_source_bad para avisar.
        try:
            raw = temps_list[self.temp_source_idx]
            if raw is None:
                raise ValueError("sensor unavailable")
            lf = float(raw)
            self.temp_ts = temps_list[3]
            self.temp_source_bad = False
        except Exception:
            lf = self.temp
            self.temp_ts = 0.8
            self.temp_source_bad = True
        alpha = 0.3
        self.temp = alpha * lf + (1 - alpha) * self.temp
        self.data_temperature.append(self.temp)

    def _ui_poll_loop(self):
        """Actualiza la UI desde el hilo principal (scheduled via after). Un solo hilo."""
        if not self._ui_poll_active:
            return
        total_msg = self.svar_status.get().split("\n")
        elapsed_pcr_time = time.time() - self.start_pcr_time
        mins_elapsed = int(elapsed_pcr_time / 60)
        msg_elapsed_time = (
            f"Time passed: {mins_elapsed} m {elapsed_pcr_time % 60:.1f} s "
            f"-- cycles: {self.cycles_complete}/{self.total_cycles}"
        )
        remaining = self._estimate_remaining_time(elapsed_pcr_time)
        msg_elapsed_time += f" -- Estimated finish: {int(remaining / 60)}m {remaining % 60:.1f}s"
        src_label = temp_source_label(self.temp_source)
        warn = (
            f"  ⚠ {src_label} unavailable — holding last value" if self.temp_source_bad else ""
        )
        total_msg[0] = (
            f"Temperature: {self.temp:.2f} °C [{src_label}]{warn}\tState: {self.fase}"
        )
        if len(total_msg) < 2:
            total_msg.append(msg_elapsed_time)
        else:
            total_msg[1] = msg_elapsed_time
        self.svar_status.set("\n".join(total_msg))

        self._ui_poll_graph_counter += 1
        if self._ui_poll_graph_counter >= 5:
            self._ui_poll_graph_counter = 0
            self.update_graph_temperature()

        if not self.running_experiment:
            # El experimento terminó por sí mismo (finally del hilo) — no vía Stop.
            # Restaura los inputs aquí, en el hilo principal (Tkinter no es
            # thread-safe), igual que hace Stop, y detén el poll.
            self._ui_poll_active = False
            self.update_graph_temperature()
            self._restore_input_ui()
            return

        self.after(500, self._ui_poll_loop)

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
                + FLUOR_READ_TOTAL_S  # lectura de fluorescencia final pendiente
            )
        else:
            # Ya pasaron todos los ciclos: solo queda la extensión final.
            remaining = self.teorical_time_pcr - elapsed_pcr_time
        return max(0.0, remaining)

    def init_temperature_graph(self):
        if self.canvas is not None:
            self.canvas.get_tk_widget().destroy()
        self.data_temperature = []  # Datos acumulados
        self.data_photodetector = []
        self.data_photodetector_series = []

        # Dos subplots apilados: arriba temperatura (denso), abajo fotodetector (1/ciclo)
        self.fig, (self.ax, self.ax_photo) = plt.subplots(
            2, 1, figsize=(4.5, 5.0), constrained_layout=True
        )

        (self.line,) = self.ax.plot([], [], marker="o", markersize=2)
        self.ax.set_title("Temperature (°C)")
        self.ax.set_xlabel("Samples")
        self.ax.set_ylabel("°C")
        self.ax.grid(True)

        (self.line_photo,) = self.ax_photo.plot([], [], marker="o", color="purple", linewidth=1.2)
        self.ax_photo.set_title("Photodetector (V)")
        self.ax_photo.set_xlabel("Cycle")
        self.ax_photo.set_ylabel("V")
        self.ax_photo.grid(True)

        self.canvas = FigureCanvasTkAgg(self.fig, master=self.profile_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        self.canvas.draw()

    def update_graph_temperature(self, window_size=None):
        if window_size is None:
            settings = read_settings_from_file()
            windows_pcr = settings.get("windows_pcr", 2500)
            window_size = int(windows_pcr)
        if self.canvas is None:
            return

        n = len(self.data_temperature)
        if n == 0:
            return

        # Índice inicial de la ventana
        start = max(0, n - window_size)

        # Datos visibles
        y = self.data_temperature[start:n]
        x = range(start, n)

        self.line.set_xdata(x)
        self.line.set_ydata(y)

        # Mantener ventana deslizante en X
        self.ax.set_xlim(start, n - 1)

        # Recalcular solo el eje Y
        # self.ax.relim()
        # self.ax.autoscale_view(scalex=False, scaley=True)

        # Eje Y fijo
        self.ax.set_ylim(19, 105)

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

    def save_data_temps_file(self):
        import csv

        timestamp = datetime.now()
        # Prefijo con el nombre del protocolo (proyecto PCR activo) saneado.
        slug = _project_slug(self.active_project_name)
        ts = timestamp.strftime("%Y%m%d_%H%M%S")
        save_dir = experiment_dir("pcr")
        filename = f"{save_dir}/{slug}_temperature_data_{ts}.csv"
        with open(filename, "w", newline="") as file:
            writer = csv.writer(file)
            writer.writerow([self.prefix_row])
            for temp in self.data_temperature:
                writer.writerow([temp])
        print(f"Data saved to {filename}")
        filename_photo = f"{save_dir}/{slug}_photodetector_data_{ts}.csv"
        with open(filename_photo, "w", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(["photodetector"])
            for phot in self.data_photodetector:
                writer.writerow([phot])
        # Serie temporal cruda en formato largo (una fila por muestra)
        filename_raw = f"{save_dir}/{slug}_photodetector_raw_{ts}.csv"
        with open(filename_raw, "w", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(["cycle", "t_rel_s", "light_on", "voltage"])
            for cycle, samples in enumerate(self.data_photodetector_series, start=1):
                for t_rel, light_on, voltage in samples:
                    writer.writerow([cycle, f"{t_rel:.3f}", light_on, f"{voltage}"])

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
        self.init_temperature_graph()
        self._ui_poll_graph_counter = 0
        self._ui_poll_active = True
        self.after(500, self._ui_poll_loop)
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
        MAX_TEMP_AGE = ts  # si es más vieja → no confiar
        integral = 0.0
        start_time = time.time()
        while time.time() - start_time <= time_hold and not stop_func.is_set():
            # Verificar edad de la temperatura
            temp_age = time.time() - self.temp_ts
            if temp_age > MAX_TEMP_AGE:
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

    def _reach_temperature_pi(
        self, setpoint, params, stop_event, break_if_below=False, tolerance=0.5
    ):
        # Rampa PI hacia setpoint con anti-windup y descarte de temperatura vieja.
        # El heater debe estar pre-armado por el caller; este método modula on/off.
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
        if FF_FRAC > 0.0 and not break_if_below:
            ceiling = setpoint * FF_FRAC
            while self.temp < ceiling and not stop_event.is_set():
                age = time.time() - self.temp_ts
                max_age = _fuzzy_max_age(setpoint - self.temp, MAX_AGE_MIN, MAX_AGE_MAX)
                if age > max_age:
                    # Temperatura vieja → no confiar; corta y reintenta.
                    self.pin_heating.write(False)  # pyrefly: ignore
                    continue
                self.pin_heating.write(True)  # pyrefly: ignore

        integral = 0.0
        while tolerance < abs(setpoint - self.temp) and not stop_event.is_set():
            if break_if_below and self.temp < setpoint:
                break
            age = time.time() - self.temp_ts
            error = setpoint - self.temp
            if age > _fuzzy_max_age(error, MAX_AGE_MIN, MAX_AGE_MAX):
                # Temperatura vieja → no confiar
                self.pin_heating.write(False)  # pyrefly: ignore
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

    def _hold_phase(self, phase, setpoint, duration, ts):
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

    def _read_fluorescence(
        self,
        ads,
        baseline_s=FLUOR_BASELINE_S,
        light_s=FLUOR_LIGHT_S,
        post_s=FLUOR_POST_S,
        sample_dt=0.1,
        averages=4,
    ):
        # Muestreo continuo del fotodetector mientras se modula la luz (pin_pcr):
        #   baseline_s  -> luz OFF (línea base oscura)
        #   light_s     -> luz ON  (excitación)
        #   post_s      -> luz OFF (decaimiento)
        # Acumula la serie temporal cruda y agrega el escalar
        #   delta = media(ventana con luz) - media(ventana baseline)
        # a data_photodetector (plot por-ciclo). Soporta lectura diferencial.
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
        self.after(1, lambda: self.update_graph_photodetector())
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

        # Reach High temp: feed-forward a potencia plena hasta ff_frac_high*setpoint
        # y luego PI (tolerancia 0.5). En el ciclo 0 (break_if_below) se omite el
        # blast porque venimos del hold de denaturación ya en temperatura, salvo
        # que la desnaturalización se haya omitido (denat_skipped): en ese caso
        # arrancamos en frío y hay que alcanzar High de verdad.
        if not _skip(time_high):
            self.fase = "Reach High temp"
            self.pin_heating.write(True)  # pyrefly: ignore
            self._reach_temperature_pi(
                high_temp,
                self._load_phase_pid("high", ts),
                self.stop_udp_listenner,
                break_if_below=(idx == 0 and not denat_skipped),
                tolerance=0.5,
            )
            print(f"Temperature reached: {self.temp} °C")

            # Hold High
            self.fase = "Hold High temp"
            print(f"Holding temperature for {time_high} seconds")
            self._hold_phase("h_high", high_temp, time_high, ts)
        else:
            print("Skipping High phase: time <= 0")

        # Cool down con giro del motor hacia la siguiente fase activa del ciclo.
        # Si Low se omite (time_low <= 0) se enfría hacia la extensión; si ambas
        # se omiten no hay nada que enfriar (la próxima fase es calentamiento).
        cool_target = (
            low_temp
            if not _skip(time_low)
            else (ext_temp if not _skip(ext_time) else None)
        )
        if cool_target is not None and self.temp > cool_target + 0.5:
            print(f"Cooling down to {cool_target} °C with motor spin")
            self.fase = "Cooling"
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
                or self.temp < cool_target + 9.5,
                stop_event=self.stop_event_motor,
            )

            print(self.temp, "cool target....dis")
            while (
                self.temp > cool_target + 0.5 and not self.stop_udp_listenner.is_set()
            ):  # pyrefly: ignore
                time.sleep(0.001)
            print(f"Temperature reached: {self.temp} °C")

        # Hold Low
        if not _skip(time_low):
            self.fase = "LOW temp Hold"
            print(f"Holding LOW temperature for {time_low} seconds")
            self._hold_phase("h_low", low_temp, time_low, ts)
        else:
            print("Skipping Low phase: time <= 0")

        # Reach Ext temp (PI, tolerancia 0.5) + Hold Ext
        if not _skip(ext_time):
            self.fase = "Reach ext temp"
            self.pin_heating.write(True)  # pyrefly: ignore
            self._reach_temperature_pi(
                ext_temp,
                self._load_phase_pid("ext", ts),
                self.stop_udp_listenner,
                break_if_below=(idx == 0),
                tolerance=0.5,
            )
            print(f"Temperature reached: {self.temp} °C")

            # Hold Ext
            self.fase = "extension temp Hold "
            print(f"Holding extension temperature for {ext_time} seconds")
            self._hold_phase("h_ext", ext_temp, ext_time, ts)
            print(f"Hold ext complete, end of cycle {idx}")
        else:
            print("Skipping Extension phase: time <= 0")

        # Lectura de fluorescencia
        time.sleep(FLUOR_PRE_SLEEP_S)
        self.fase = "Reading Fluorescence"
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

    def experiment_pcr(
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
        global thread_motor, sistemaMotor

        self.stop_udp_listenner = (
            threading.Event() if self.stop_udp_listenner is None else self.stop_udp_listenner
        )
        self.total_cycles = cycles
        self.cycles_complete = 0
        self.last_cycle_duration = 0.0
        self.avg_cycle_duration = 0.0
        self.ext_time_final = ext_time_final
        self.teorical_time_pcr = (
            (time_high + time_low + ext_time) * 1.2 * cycles
            + denat_time
            + ext_time_final
            + FLUOR_READ_TOTAL_S * cycles  # lectura de fluorescencia por ciclo
            + FLUOR_READ_TOTAL_S  # lectura de fluorescencia final
        )

        settings = read_settings_from_file()
        pidGains = settings.get("pidControllerRPM", {})
        try:
            ts = float(pidGains.get("ts_pcr", 0.05))
        except Exception:
            ts = 0.05

        # Nombre del proyecto activo para trazabilidad receta->datos. Si corrió con
        # entradas editadas a mano (snapshot implícito), se marca como sin guardar.
        if self.active_project_name in (None, pcrp.LAST_RUN_KEY):
            project_label = "_last_run (sin guardar)"
        else:
            project_label = self.active_project_name
        prefix_col = (
            f"project: {project_label}"
            f"-high_temp: {high_temp}-low_temp: {low_temp}-time_high: {time_high}"
            f"-time_low: {time_low}-cycles: {cycles}-rpm: {rpm}"
            f"-denat_temp: {denat_temp}-denat_time: {denat_time}-ts: {ts}"
            f"-temp_source: {temp_source_label(self.temp_source)}"
        )
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
            prefixCol=prefix_col,
            save_data=False,
        )
        self.prefix_row = prefix_col
        self.client_temperature.start()
        self.fase = "Initial"
        from Drivers.DriverStepperSys import DriverStepperSys, spinMotorRPM_ramped

        self.start_pcr_time = time.time()

        try:
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

            self.pin_heating = GPIOPin(
                led_heatin_pin,
                chip=chip_rasp,
                consumer="led-heating-ui",
                active_low=False,
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
                self.fase = "Denaturation"
                self.pin_heating.write(True)  # pyrefly: ignore
                self._reach_temperature_pi(
                    denat_temp,
                    self._load_phase_pid("denat", ts),
                    self.stop_udp_listenner,
                    break_if_below=False,
                    tolerance=0.5,
                )

                # ----- Denaturation Hold
                self.fase = "Denaturation Hold"
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

            # ----- Extensión final + lectura de fluorescencia (solo si no se detuvo).
            # El hold final se omite si ext_time_final <= 0, pero la lectura de
            # fluorescencia final SIEMPRE se realiza (la medición no se salta).
            if not self.stop_udp_listenner.is_set():
                print("PCR cycles complete, reading fluorescence")
                self.fase = "Extension"
                if not _skip(ext_time_final):
                    self._hold_phase("h_ext", ext_temp, ext_time_final, ts)
                else:
                    print("Skipping Final Extension hold: time <= 0")
                time.sleep(FLUOR_PRE_SLEEP_S)
                v_fluo_final = self._read_fluorescence(ads)
                print(f"Final fluorescence delta voltage: {v_fluo_final}")
                self.fase = "Final"

            self.save_data_temps_file()

        except Exception as e:
            print(f"exception in experiment: {e}")
        finally:
            self._teardown_hardware()

    def _teardown_hardware(self):
        # Cierre idempotente de hardware: motor, UDP, pines GPIO. Seguro de invocar
        # desde el hilo del experimento (en finally) o desde el hilo de UI (Stop).
        global sistemaMotor
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
        # No se toca _ui_poll_active aquí: dejamos que _ui_poll_loop detecte el fin
        # (running_experiment=False) y restaure los inputs en el hilo principal.
        self.running_experiment = False

    def _restore_input_ui(self):
        # Vuelve a mostrar los inputs y la barra de proyectos (ocultados al iniciar).
        # Debe invocarse desde el hilo principal (Tkinter no es thread-safe).
        self.frame_entries.grid(row=1, column=0, padx=5, pady=5, sticky="nswe")
        self.frame_project.grid(row=0, column=0, sticky="nswe", padx=(5, 25), pady=(5, 0))
        if self.cbo_temp_source is not None:
            self.cbo_temp_source.configure(state="readonly")
        self._refresh_project_list()

    def callback_stop_experiment(self):
        # Restaura UI y dispara la salida ordenada del hilo del experimento.
        # El propio finally del experimento llama a _teardown_hardware; aquí solo
        # señalizamos, esperamos al hilo, y tiramos red de seguridad si se colgó.
        self._restore_input_ui()
        if self.stop_event_motor is None or self.stop_udp_listenner is None:
            print("No experiment running")
            self.running_experiment = False
            return
        self.stop_event_motor.set()
        self.stop_udp_listenner.set()
        if self.thread_experiment is not None:
            self.thread_experiment.join(timeout=3.0)
            if self.thread_experiment.is_alive():
                print("warning: experiment thread did not exit within 3s, forcing teardown")
        # Red de seguridad: si el finally del experimento ya corrió, esto es no-op.
        self._teardown_hardware()
        self.stop_event_motor = None
        self.stop_udp_listenner = None
        self.thread_experiment = None
