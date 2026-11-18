# -*- coding: utf-8 -*-
"""Pestaña "Quick Control" de la ventana de análisis.

Lecturas de Quick Control (`unified_*.xlsx`): temperatura o señal del fotodetector,
una señal a la vez. Superpone trazas (archivo × corrida × canal), sombrea los eventos
de actuador de la corrida seleccionada y calcula estadísticas por ventana (intervalo
[t_a, t_b] de una corrida, elegido con dos clics): n, media, std, std/media, pico a
pico, pendiente; deriva % y nA (si la corrida trae Rf) en el fotodetector; Δ respecto
al termopar en "All (3 temps)". Vocabulario en GLOSSARY.md; diseño en
docs/quick_analisis.md.
"""
import os
import time
from tkinter.filedialog import askopenfilename, askopenfilenames, asksaveasfilename

import numpy as np
import ttkbootstrap as ttk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure
from matplotlib.patches import Patch

from templates.utils import experiment_dir, temp_source_label
from templates.xlsx_io import XLSX_FILETYPES, read_sheets_text, write_workbook, xlsx_path
from ui.analysis.common import plt  # noqa: F401  (fija el backend TkAgg)
from ui.analysis.pcr import PLOT_FIG_W_IN, PLOT_IN_PER_WEIGHT

# Un solo eje con el peso del eje de temperatura de la pestaña PCR (3 × 1.8" ≈ 540 px).
# Constante a propósito: el alto NUNCA sale de winfo_height() (en el Pi quedaba
# diminuto) y es el área con scroll la que deja a la figura superar la ventana
# (docs/pcr_analisis.md §4.4).
PLOT_WEIGHT = 3

SIGNAL_NAME = {"temp": "Temperature", "fluor": "Photodetector"}
SIGNAL_UNIT = {"temp": "°C", "fluor": "V"}
THERMOCOUPLE = temp_source_label("thermocouple")
LIVE_SOURCE = "live"

# Columnas de la tabla de estadísticas: comunes + las de cada señal (decisión Q12).
STATS_COMMON = (
    "file", "run", "win", "channel", "label", "t_a", "t_b", "dur", "n",
    "mean", "std", "cv", "pp", "slope",
)
STATS_EXTRA = {"temp": ("d_tc",), "fluor": ("drift", "mean_na", "std_na")}

# Sombreado de eventos de actuador (solo la corrida seleccionada). El motor va como
# franja al pie del eje para no tapar a los LEDs.
SHADE_SPECS = (
    ("fluor_led", "Fluorescence LED on", "tab:blue", 0.10, 1.0),
    ("heat_led", "Heating LED on", "tab:orange", 0.10, 1.0),
    ("motor", "Motor on", "tab:gray", 0.45, 0.04),
)


def _fmt(x, spec=".4g"):
    """Número para la tabla; NaN/None → celda vacía."""
    if x is None:
        return ""
    try:
        xf = float(x)
    except (TypeError, ValueError):
        return str(x)
    return format(xf, spec) if np.isfinite(xf) else ""


# ---------------------------------------------------------------------------
# Modelo de datos
# ---------------------------------------------------------------------------
class QuickTrace:
    """Un canal de una corrida (GLOSSARY: traza), con su propio eje de tiempo."""

    def __init__(self, channel, times, values):
        self.channel = str(channel)
        self.times = np.asarray(times, dtype=float)
        self.values = np.asarray(values, dtype=float)
        self.visible = True
        # Nombre visible elegido por el usuario (leyenda, árbol, tabla); "" = el de por
        # defecto. Nunca reemplaza a `channel`: el Δ vs termopar y el export lo usan
        # como clave.
        self.name = ""


class QuickWindow:
    """Intervalo [t_a, t_b] de una corrida con etiqueta (GLOSSARY: ventana)."""

    def __init__(self, t_a, t_b, label=""):
        lo, hi = sorted((float(t_a), float(t_b)))
        self.t_a = lo
        self.t_b = hi
        self.label = str(label)


class QuickRun:
    """Una corrida de Quick Control (Start → Stop de una señal) con sus trazas, la
    foto de configuración al Start (`settings`, key → texto) y los eventos de
    actuador `(t_s, actuator, state)`. Los archivos anteriores a esas hojas traen
    ambas vacías: sin nA, sin sombreado y con etiqueta de ventana vacía."""

    def __init__(self, source, run, signal, traces, settings=None, events=None):
        self.source = str(source)  # nombre corto del archivo o "live"
        self.run = int(run)
        self.signal = signal
        self.traces = list(traces)
        self.settings = {str(k): str(v) for k, v in (settings or {}).items()}
        # sorted es estable: dos eventos en el mismo instante conservan su orden.
        self.events = sorted(events or [], key=lambda e: e[0])
        self.windows = []  # list[QuickWindow]
        self.live = False  # sembrada de la memoria de Quick Control ("Reload live" la reemplaza)

    @property
    def name(self):
        return f"{self.source} r{self.run}"

    @property
    def visible(self):
        return any(tr.visible and tr.times.size for tr in self.traces)

    def t_end(self):
        ends = [float(tr.times[-1]) for tr in self.traces if tr.times.size]
        return max(ends) if ends else 0.0

    def sample_times(self):
        """Tiempos de muestra de la corrida (los canales comparten la base; se toma
        la traza más larga). Se usa para que los clics caigan sobre una muestra."""
        best = max(self.traces, key=lambda tr: tr.times.size, default=None)
        return best.times if best is not None else np.asarray([], dtype=float)

    def rf_ohm(self):
        """Rf del TIA guardado al Start (0.0 = desconocido o archivo viejo)."""
        try:
            rf = float(self.settings.get("photoreceptor.rf_ohm", "0") or 0)
        except (TypeError, ValueError):
            return 0.0
        return rf if np.isfinite(rf) and rf > 0 else 0.0

    # --- eventos de actuador ---
    def state_at(self, t):
        """Estado de cada actuador en el instante t (último evento con tiempo ≤ t)."""
        states = {}
        for te, actuator, state in self.events:
            if te > t:
                break
            states[actuator] = state
        return states

    def changes_in(self, t_a, t_b):
        """¿Algún evento de actuador dentro de (t_a, t_b]? → la ventana es "mixed"."""
        return any(t_a < te <= t_b for te, _a, _s in self.events)

    def auto_label(self, t_a, t_b):
        """Etiqueta por defecto de una ventana a partir de los eventos (decisión Q11):
        el estado de los actuadores si no cambia dentro de la ventana, "mixed" si
        cruza un evento, vacía si la corrida no trae eventos."""
        if not self.events:
            return ""
        if self.changes_in(t_a, t_b):
            return "mixed"
        st = self.state_at(t_a)
        parts = []
        if self.signal == "fluor":
            parts.append("LED on" if st.get("fluor_led") == "on" else "LED off")
            if st.get("heat_led") == "on":
                parts.append("heat on")
        else:
            parts.append("heat on" if st.get("heat_led") == "on" else "heat off")
            if st.get("fluor_led") == "on":
                parts.append("LED on")
        motor = st.get("motor", "off")
        if motor and motor != "off":
            parts.append(f"motor {motor}")
        return " · ".join(parts)

    def intervals(self, actuator, t_end):
        """Intervalos [t0, t1] en que el actuador estuvo activo (LED "on"; motor
        cualquier estado distinto de "off", incluido "stopping")."""
        out = []
        start = None
        for te, a, s in self.events:
            if a != actuator:
                continue
            active = s != "off"
            if active and start is None:
                start = te
            elif not active and start is not None:
                out.append((start, te))
                start = None
        if start is not None:
            out.append((start, max(t_end, start)))
        return out


def window_stats(run, win):
    """Estadísticas de cada canal de `run` dentro de `win` → una fila (dict) por canal.

    std con ddof = 1 (ruido rms alrededor de la media); pendiente por mínimos
    cuadrados en unidad/s (°C/s en temperatura = tasa; V/s en el fotodetector =
    deriva). Fotodetector: deriva % = pendiente × duración / media y, si la corrida
    trae Rf, media y std en nA. Temperatura con varios canales: Δ media respecto al
    termopar en la misma ventana."""
    nan = float("nan")
    dur = win.t_b - win.t_a
    rows = []
    for tr in run.traces:
        m = (tr.times >= win.t_a) & (tr.times <= win.t_b) & np.isfinite(tr.values)
        ts, ys = tr.times[m], tr.values[m]
        n = int(ys.size)
        mean = float(np.mean(ys)) if n else nan
        std = float(np.std(ys, ddof=1)) if n > 1 else nan
        pp = float(np.ptp(ys)) if n else nan
        slope = nan
        if n > 1 and float(np.ptp(ts)) > 0:
            slope = float(np.polyfit(ts, ys, 1)[0])
        cv = std / abs(mean) * 100.0 if n > 1 and mean != 0 else nan
        rows.append(
            {
                "trace": tr, "channel": tr.channel, "t_a": win.t_a, "t_b": win.t_b,
                "dur": dur, "n": n, "mean": mean, "std": std, "cv": cv, "pp": pp,
                "slope": slope, "d_tc": nan, "drift": nan, "mean_na": nan, "std_na": nan,
            }
        )
    if run.signal == "temp" and len(rows) > 1:
        tc = next((r for r in rows if r["channel"] == THERMOCOUPLE), None)
        if tc is not None and np.isfinite(tc["mean"]):
            for r in rows:
                if r is not tc:
                    r["d_tc"] = r["mean"] - tc["mean"]
    if run.signal == "fluor":
        rf = run.rf_ohm()
        for r in rows:
            if r["mean"] != 0 and np.isfinite(r["mean"]):
                r["drift"] = r["slope"] * dur / r["mean"] * 100.0
            if rf:
                r["mean_na"] = r["mean"] / rf * 1e9
                r["std_na"] = r["std"] / rf * 1e9
    return rows


# ---------------------------------------------------------------------------
# Lectura de hojas (filas de texto, como csv.reader)
# ---------------------------------------------------------------------------
def _columns(rows, required):
    """Índices de columna por nombre del encabezado; None si falta alguna requerida."""
    if not rows:
        return None
    header = [h.strip() for h in rows[0]]
    col = {name: i for i, name in enumerate(header)}
    return col if all(r in col for r in required) else None


def _cell(row, col, key):
    i = col.get(key)
    return row[i].strip() if i is not None and i < len(row) else ""


def _run_key(text):
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


def parse_readings(sheets, file_col=False):
    """Corridas de las hojas `data` / `settings` / `events` de Quick Control.

    Con `file_col` (export de esta pestaña) cada hoja trae además la columna `file`
    y las corridas se agrupan por (file, run). Devuelve `{(file, run): dict}` con
    `signal`, `channels` (orden de aparición → (times, values)), `settings` y
    `events`; o un texto de error."""
    req = ("t_s", "value", "channel", "signal", "run") + (("file",) if file_col else ())
    data = sheets.get("data")
    col = _columns(data, req)
    if col is None:
        return "no 'data' sheet with t_s/value/channel/signal/run columns"
    out = {}

    def entry(key):
        if key not in out:
            out[key] = {"signals": [], "channels": {}, "settings": {}, "events": []}
        return out[key]

    for row in data[1:]:
        if not row:
            continue
        run = _run_key(_cell(row, col, "run"))
        if run is None:
            continue
        try:
            t = float(_cell(row, col, "t_s"))
            v = float(_cell(row, col, "value"))
        except (TypeError, ValueError):
            continue
        key = (_cell(row, col, "file") if file_col else "", run)
        e = entry(key)
        sig = _cell(row, col, "signal")
        if sig not in e["signals"]:
            e["signals"].append(sig)
        ch = e["channels"].setdefault(_cell(row, col, "channel") or "value", ([], []))
        ch[0].append(t)
        ch[1].append(v)

    s_col = _columns(sheets.get("settings"), ("run", "key", "value") + (("file",) if file_col else ()))
    if s_col is not None:
        for row in sheets["settings"][1:]:
            run = _run_key(_cell(row, s_col, "run"))
            key = (_cell(row, s_col, "file") if file_col else "", run)
            if run is not None and key in out:
                out[key]["settings"][_cell(row, s_col, "key")] = _cell(row, s_col, "value")

    e_col = _columns(
        sheets.get("events"), ("run", "t_s", "actuator", "state") + (("file",) if file_col else ())
    )
    if e_col is not None:
        for row in sheets["events"][1:]:
            run = _run_key(_cell(row, e_col, "run"))
            key = (_cell(row, e_col, "file") if file_col else "", run)
            if run is None or key not in out:
                continue
            try:
                t = float(_cell(row, e_col, "t_s"))
            except (TypeError, ValueError):
                continue
            out[key]["events"].append(
                (t, _cell(row, e_col, "actuator"), _cell(row, e_col, "state"))
            )
    if not out:
        return "no samples parsed"
    for key, e in out.items():
        if len(e["signals"]) != 1 or e["signals"][0] not in SIGNAL_NAME:
            return f"run {key[1]}: unexpected signal(s) {e['signals']}"
        e["signal"] = e["signals"][0]
    return out


def _short_source(path):
    """`unified_fluor_20261117_123901_fluorledON.xlsx` → `fluor_20261117_123901_fluorledON`."""
    stem = os.path.splitext(os.path.basename(path))[0]
    return stem[len("unified_"):] if stem.startswith("unified_") else stem


# ---------------------------------------------------------------------------
# Pestaña
# ---------------------------------------------------------------------------
class QuickAnalysisFrame(ttk.Frame):
    """Pestaña de análisis de las lecturas de Quick Control (docs/quick_analisis.md).

    Una señal a la vez: el primer archivo (o la siembra en vivo) fija temperatura o
    fotodetector y la otra se rechaza hasta "Clear all". Árbol archivo → corrida →
    canal con visibilidad por traza; un eje de alto fijo dentro del área con scroll;
    ventanas por corrida con dos clics; tabla de estadísticas debajo."""

    def __init__(self, master, owner, quick_frame=None, **kwargs):
        super().__init__(master, **kwargs)
        self.owner = owner
        self.quick_frame = quick_frame
        self.runs: list[QuickRun] = []
        self._focus_run: "QuickRun | None" = None  # corrida seleccionada en el árbol
        self._tree_ref = {}  # iid árbol → ("source", name) | ("run", run) | ("trace", run, tr)
        self._res_ref = {}  # iid tabla → (run, window)
        self._legend_visible = True
        self._add_mode = False
        self._pick_cid: "int | None" = None
        self._pending: "tuple[QuickRun, float] | None" = None  # punto A a la espera de B
        self._label_entry: "ttk.Entry | None" = None  # editor de etiqueta (tabla)
        self._rename_entry: "ttk.Entry | None" = None  # editor de nombre (árbol)
        self._stats_cols: tuple = STATS_COMMON

        self._build_ui()
        if quick_frame is not None:
            self._seed_live(report=False)
        self._refresh_tree()
        self._redraw()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        toolbar = ttk.Frame(self)
        toolbar.pack(side=ttk.TOP, fill=ttk.X, padx=6, pady=(6, 2))
        ttk.Button(toolbar, text="📂 Load", bootstyle="secondary", command=self.load_file).pack(
            side=ttk.LEFT, padx=3
        )
        ttk.Button(
            toolbar, text="📥 Import", bootstyle="secondary", command=self.import_analysis
        ).pack(side=ttk.LEFT, padx=3)
        ttk.Button(
            toolbar, text="💾 Export", bootstyle="secondary", command=self.export_results
        ).pack(side=ttk.LEFT, padx=3)
        self.btn_live = ttk.Button(
            toolbar, text="⟳ Reload live", bootstyle="info-outline", command=self.reload_live
        )
        self.btn_live.pack(side=ttk.LEFT, padx=3)
        if self.quick_frame is None:
            self.btn_live.configure(state=ttk.DISABLED)
        self.btn_legend = ttk.Button(
            toolbar, text="Legend ON", bootstyle="secondary", command=self.toggle_legend
        )
        self.btn_legend.pack(side=ttk.RIGHT, padx=3)
        ttk.Button(
            toolbar, text="Clear all", bootstyle="danger-outline", command=self.clear_all
        ).pack(side=ttk.RIGHT, padx=3)

        toolbar_b = ttk.Frame(self)
        toolbar_b.pack(side=ttk.TOP, fill=ttk.X, padx=6, pady=(0, 2))
        ttk.Button(
            toolbar_b, text="🗑 Remove", bootstyle="danger", command=self.remove_selected
        ).pack(side=ttk.LEFT, padx=3)
        ttk.Button(
            toolbar_b, text="👁 Show/Hide", bootstyle="info", command=self.toggle_visibility
        ).pack(side=ttk.LEFT, padx=3)
        self.lbl_cross = ttk.Label(toolbar_b, text="", anchor="e")
        self.lbl_cross.pack(side=ttk.RIGHT, padx=6)

        toolbar3 = ttk.Frame(self)
        toolbar3.pack(side=ttk.TOP, fill=ttk.X, padx=6, pady=(0, 6))
        self.btn_add = ttk.Button(
            toolbar3, text="➕ Add window", bootstyle="secondary-outline", command=self._toggle_add_mode
        )
        self.btn_add.pack(side=ttk.LEFT, padx=3)
        ttk.Button(
            toolbar3, text="➖ Remove window", bootstyle="warning-outline", command=self.remove_window
        ).pack(side=ttk.LEFT, padx=3)
        ttk.Button(
            toolbar3, text="🧹 Clear windows", bootstyle="warning-outline", command=self.clear_windows
        ).pack(side=ttk.LEFT, padx=3)

        # Barra de matplotlib fuera del scroll (mismo motivo que en la pestaña PCR:
        # el zoom tiene que estar siempre a la vista para picar ventanas con precisión).
        self._mpl_toolbar_host = ttk.Frame(self)
        self._mpl_toolbar_host.pack(side=ttk.TOP, fill=ttk.X, padx=6, pady=(0, 4))

        self.lbl_status = ttk.Label(self, text="Ready.", anchor="w")
        self.lbl_status.pack(side=ttk.BOTTOM, fill=ttk.X, padx=6, pady=(0, 4))

        # --- Área con scroll (árbol + figura + tabla), igual que la pestaña PCR ---
        _wrap = ttk.Frame(self)
        _wrap.pack(fill=ttk.BOTH, expand=True, padx=6, pady=(0, 4))
        _vsb_main = ttk.Scrollbar(_wrap, orient="vertical")
        _vsb_main.pack(side=ttk.RIGHT, fill=ttk.Y)
        self._main_sc = ttk.Canvas(_wrap, bd=0, highlightthickness=0, yscrollcommand=_vsb_main.set)
        self._main_sc.pack(side=ttk.LEFT, fill=ttk.BOTH, expand=True, padx=(5, 20))
        _vsb_main.configure(command=self._main_sc.yview)
        inner = ttk.Frame(self._main_sc)
        _win_id = self._main_sc.create_window((0, 0), window=inner, anchor="nw")

        def _update_sr(_event=None):
            self._main_sc.configure(scrollregion=self._main_sc.bbox("all"))

        def _sync_width(event):
            self._main_sc.itemconfig(_win_id, width=event.width)

        inner.bind("<Configure>", _update_sr)
        self._main_sc.bind("<Configure>", _sync_width)

        def _on_wheel(event):
            self._main_sc.yview_scroll(int(-1 * (event.delta / 120)), "units")

        self._main_sc.bind("<MouseWheel>", _on_wheel)
        inner.bind("<MouseWheel>", _on_wheel)

        main = ttk.PanedWindow(inner, orient=ttk.HORIZONTAL)
        main.pack(fill=ttk.X, padx=0, pady=(0, 6))

        left = ttk.LabelFrame(main, text="Readings")
        main.add(left, weight=1)
        self.tree = ttk.Treeview(left, columns=("info",), show="tree headings", selectmode="extended")
        self.tree.heading("#0", text="File / run / channel", anchor="w")
        self.tree.heading("info", text="Info", anchor="w")
        self.tree.column("#0", width=170, minwidth=80, anchor="w")
        self.tree.column("info", width=70, minwidth=50, anchor="w")
        vsb_t = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb_t.set)
        self.tree.pack(side=ttk.LEFT, fill=ttk.BOTH, expand=True, padx=4, pady=4)
        vsb_t.pack(side=ttk.LEFT, fill=ttk.Y)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.tree.bind("<Double-1>", self._begin_rename)

        right = ttk.Frame(main)
        main.add(right, weight=4)
        right.bind("<MouseWheel>", _on_wheel)
        self._create_plot_canvas(right)

        bottom = ttk.LabelFrame(inner, text="Window stats (visible traces) — double-click Label to edit")
        bottom.pack(fill=ttk.BOTH, pady=(0, 6))
        self.tree_res = ttk.Treeview(bottom, columns=STATS_COMMON, show="headings", height=10)
        vsb_r = ttk.Scrollbar(bottom, orient="vertical", command=self.tree_res.yview)
        hsb_r = ttk.Scrollbar(bottom, orient="horizontal", command=self.tree_res.xview)
        self.tree_res.configure(yscrollcommand=vsb_r.set, xscrollcommand=hsb_r.set)
        vsb_r.pack(side=ttk.RIGHT, fill=ttk.Y)
        hsb_r.pack(side=ttk.BOTTOM, fill=ttk.X)
        self.tree_res.pack(fill=ttk.BOTH, expand=True)
        self.tree_res.bind("<Double-1>", self._begin_label_edit)
        self._configure_stats_columns(None)

    def _create_plot_canvas(self, host):
        self.fig = Figure(
            figsize=(PLOT_FIG_W_IN, PLOT_IN_PER_WEIGHT * PLOT_WEIGHT),
            dpi=100,
            layout="constrained",
        )
        self.ax = self.fig.add_subplot(1, 1, 1)
        self.canvas = FigureCanvasTkAgg(self.fig, host)
        tkw = self.canvas.get_tk_widget()
        # Ignora el <Configure> transitorio de 1 px al abrir (ver pestaña PCR).
        tkw.bind(
            "<Configure>",
            lambda e: self.canvas.resize(e) if e.width > 1 and e.height > 1 else None,
        )
        tkw.pack(fill=ttk.BOTH, expand=True)
        self.toolbar_mpl = NavigationToolbar2Tk(self.canvas, self._mpl_toolbar_host, pack_toolbar=False)
        self.toolbar_mpl.pack(fill=ttk.X)
        self.canvas.mpl_connect("motion_notify_event", self._on_hover)

    def _configure_stats_columns(self, signal):
        unit = SIGNAL_UNIT.get(signal or "", "")
        u = f" ({unit})" if unit else ""
        heads = {
            "file": ("File", 150), "run": ("Run", 40), "win": ("Win", 40),
            "channel": ("Channel", 95), "label": ("Label", 150),
            "t_a": ("t_a (s)", 65), "t_b": ("t_b (s)", 65), "dur": ("Dur (s)", 60),
            "n": ("n", 45), "mean": (f"Mean{u}", 85), "std": (f"Std{u}", 80),
            "cv": ("Std/mean %", 80), "pp": (f"P-P{u}", 80),
            "slope": (f"Slope ({unit}/s)" if unit else "Slope (/s)", 95),
            "d_tc": ("Δ vs TC (°C)", 90), "drift": ("Drift %", 65),
            "mean_na": ("Mean (nA)", 80), "std_na": ("Std (nA)", 75),
        }
        cols = STATS_COMMON + STATS_EXTRA.get(signal or "", ())
        self._stats_cols = cols
        self.tree_res.configure(columns=cols, displaycolumns=cols)
        for c in cols:
            text, width = heads[c]
            self.tree_res.heading(c, text=text, anchor="w")
            self.tree_res.column(c, width=width, minwidth=35, anchor="w", stretch=False)

    # ------------------------------------------------------------ Estado
    def _set_status(self, msg):
        self.lbl_status.configure(text=msg)

    def _signal(self):
        return self.runs[0].signal if self.runs else None

    def _unique_source(self, name, existing=None):
        if existing is None:
            existing = {r.source for r in self.runs}
        if name not in existing:
            return name
        i = 1
        while f"{name}_{i}" in existing:
            i += 1
        return f"{name}_{i}"

    def _signal_conflict(self, signal):
        """Mensaje si `signal` no puede convivir con lo cargado (decisión Q3); None si sí."""
        current = self._signal()
        if current is None or current == signal:
            return None
        return (
            f"This tab holds {SIGNAL_NAME[current]} readings; "
            f"Clear all first to load {SIGNAL_NAME[signal]}."
        )

    def _target_run(self):
        """Corrida sobre la que actuar (sombreado, picado): la seleccionada en el
        árbol o, sin selección, la única corrida visible."""
        if self._focus_run is not None and self._focus_run in self.runs:
            return self._focus_run
        vis = [r for r in self.runs if r.visible]
        return vis[0] if len(vis) == 1 else None

    # ------------------------------------------------------------ Árbol
    def _refresh_tree(self):
        self._cancel_rename()
        self.tree.delete(*self.tree.get_children())
        self._tree_ref = {}
        focus_iid = None
        sources = []
        for r in self.runs:
            if r.source not in sources:
                sources.append(r.source)
        for src in sources:
            runs = [r for r in self.runs if r.source == src]
            s_iid = self.tree.insert("", ttk.END, text=src, values=(f"{len(runs)} run(s)",), open=True)
            self._tree_ref[s_iid] = ("source", src)
            for r in runs:
                n = int(r.sample_times().size)
                r_iid = self.tree.insert(s_iid, ttk.END, text=f"r{r.run}", values=(f"{n} smp",), open=True)
                self._tree_ref[r_iid] = ("run", r)
                if r is self._focus_run:
                    focus_iid = r_iid
                for tr in r.traces:
                    mark = "👁" if tr.visible else "🚫"
                    text = f"{tr.name} ({tr.channel})" if tr.name else tr.channel
                    t_iid = self.tree.insert(r_iid, ttk.END, text=text, values=(mark,))
                    self._tree_ref[t_iid] = ("trace", r, tr)
        if focus_iid is not None:
            self.tree.selection_set(focus_iid)

    def _selected_refs(self):
        return [self._tree_ref[i] for i in self.tree.selection() if i in self._tree_ref]

    # --- renombrado in situ (doble clic en el árbol) ---
    def _begin_rename(self, event):
        """Doble clic sobre un archivo → renombra la fuente; sobre un canal → nombre
        visible de esa traza (leyenda, árbol, tabla). Las corridas no se renombran:
        su número es la clave de settings/events/ventanas en el export."""
        self._cancel_rename()
        iid = self.tree.identify_row(event.y)
        ref = self._tree_ref.get(iid)
        if ref is None or ref[0] == "run" or self.tree.identify_column(event.x) != "#0":
            return None
        bbox = self.tree.bbox(iid, "#0")
        if not bbox:
            return None
        if ref[0] == "source":
            current = ref[1]
        else:
            current = ref[2].name or f"{ref[1].name} {ref[2].channel}"
        x, y, w, h = bbox
        entry = ttk.Entry(self.tree)
        entry.insert(0, current)
        entry.select_range(0, ttk.END)
        entry.place(x=x, y=y, width=max(w, 160), height=h + 16)
        entry.focus_set()
        entry.bind("<Return>", lambda _e: self._commit_rename(ref))
        entry.bind("<Escape>", lambda _e: self._cancel_rename())
        entry.bind("<FocusOut>", lambda _e: self._commit_rename(ref))
        self._rename_entry = entry
        return "break"  # que el doble clic no pliegue/despliegue además el nodo

    def _commit_rename(self, ref):
        entry = self._rename_entry
        if entry is None:
            return
        text = entry.get().strip()
        self._cancel_rename()
        if ref[0] == "source":
            old = ref[1]
            if not text or text == old:
                return
            new = self._unique_source(text, {r.source for r in self.runs if r.source != old})
            for r in self.runs:
                if r.source == old:
                    r.source = new
            msg = f"File renamed to '{new}'."
        else:
            run, tr = ref[1], ref[2]
            # Vacío o igual al de por defecto → vuelve al nombre por defecto.
            new = "" if text in ("", f"{run.name} {tr.channel}") else text
            if new == tr.name:
                return
            tr.name = new
            msg = f"Trace renamed to '{new}'." if new else f"Trace name reset ({tr.channel})."
        self._refresh_tree()
        self._redraw()
        self._set_status(msg)

    def _cancel_rename(self):
        entry = self._rename_entry
        self._rename_entry = None
        if entry is not None:
            try:
                entry.destroy()
            except Exception:
                pass

    def _runs_of(self, refs):
        """Corridas tocadas por la selección (una fuente aporta todas las suyas)."""
        out = []
        for ref in refs:
            if ref[0] == "source":
                cand = [r for r in self.runs if r.source == ref[1]]
            else:
                cand = [ref[1]]
            for r in cand:
                if r not in out:
                    out.append(r)
        return out

    def _on_tree_select(self, _event=None):
        runs = self._runs_of(self._selected_refs())
        new_focus = runs[0] if len(runs) == 1 else None
        if new_focus is not self._focus_run:
            self._focus_run = new_focus
            self._pending = None
            self._redraw()

    # ------------------------------------------------------------ Dibujo
    def _redraw(self):
        ax = self.ax
        ax.clear()
        signal = self._signal()
        unit = SIGNAL_UNIT.get(signal or "", "")
        title = SIGNAL_NAME.get(signal or "", "Quick Control readings")
        if self._add_mode:
            title += " — click two points to add a window"
        ax.set_title(title)
        ax.set_xlabel("Time from run start (s)")
        ax.set_ylabel(f"{SIGNAL_NAME.get(signal or '', 'Value')} ({unit})" if unit else "Value")
        ax.grid(True)

        target = self._target_run()
        handles: list = []  # líneas + parches del sombreado, para una sola leyenda
        gi = 0
        for r in self.runs:
            for tr in r.traces:
                color = f"C{gi % 10}"
                gi += 1
                if not tr.visible or tr.times.size == 0:
                    continue
                (line,) = ax.plot(
                    tr.times, tr.values, linewidth=1.0, color=color,
                    label=tr.name or f"{r.name} {tr.channel}",
                )
                handles.append(line)

        # Eventos de actuador: solo la corrida seleccionada (con varias superpuestas el
        # sombreado de todas sería ilegible — decisión Q17).
        if target is not None and target.events:
            t_end = target.t_end()
            for actuator, text, color, alpha, height in SHADE_SPECS:
                spans = target.intervals(actuator, t_end)
                for t0, t1 in spans:
                    ax.axvspan(t0, t1, ymin=0.0, ymax=height, color=color, alpha=alpha, lw=0)
                if spans:
                    handles.append(Patch(color=color, alpha=max(alpha, 0.25), label=f"{text} ({target.name})"))

        # Ventanas de las corridas visibles; las de la corrida seleccionada, resaltadas y
        # con su número (W1, W2…; etiqueta y corrida se leen en la tabla — con el texto
        # completo las ventanas contiguas se pisaban).
        xform = ax.get_xaxis_transform()
        for r in self.runs:
            if not r.visible:
                continue
            strong = r is target
            for k, w in enumerate(r.windows, start=1):
                ax.axvspan(w.t_a, w.t_b, color="tab:green", alpha=0.18 if strong else 0.07, lw=0)
                for x in (w.t_a, w.t_b):
                    ax.axvline(x, color="tab:green", lw=0.8, alpha=0.8 if strong else 0.3)
                if strong:
                    ax.text(
                        (w.t_a + w.t_b) / 2, 0.98, f"W{k}", transform=xform, ha="center",
                        va="top", fontsize=8, clip_on=True,
                    )
        if self._pending is not None and self._pending[0] in self.runs:
            ax.axvline(self._pending[1], color="black", lw=1.2, ls="--")

        if handles:
            leg = ax.legend(handles=handles, loc="best", fontsize=7, ncol=2)
            if leg is not None:
                leg.set_visible(self._legend_visible)
        self.canvas.draw_idle()
        self._refresh_table()

    def _refresh_table(self):
        self._cancel_label_edit()
        signal = self._signal()
        if self._stats_cols != STATS_COMMON + STATS_EXTRA.get(signal or "", ()):
            self._configure_stats_columns(signal)
        self.tree_res.delete(*self.tree_res.get_children())
        self._res_ref = {}
        for r in self.runs:
            for k, w in enumerate(r.windows, start=1):
                mixed = r.changes_in(w.t_a, w.t_b)
                label = f"⚠ {w.label}" if mixed else w.label
                for st in window_stats(r, w):
                    if not st["trace"].visible:
                        continue
                    vals = {
                        "file": r.source, "run": r.run, "win": f"W{k}",
                        "channel": st["trace"].name or st["channel"],
                        "label": label, "t_a": _fmt(st["t_a"], ".2f"), "t_b": _fmt(st["t_b"], ".2f"),
                        "dur": _fmt(st["dur"], ".2f"), "n": st["n"],
                    }
                    for c in ("mean", "std", "cv", "pp", "slope", "d_tc", "drift", "mean_na", "std_na"):
                        vals[c] = _fmt(st[c])
                    iid = self.tree_res.insert("", ttk.END, values=[vals[c] for c in self._stats_cols])
                    self._res_ref[iid] = (r, w)

    def _on_hover(self, event):
        if event.inaxes is not self.ax or event.xdata is None:
            self.lbl_cross.configure(text="")
            return
        unit = SIGNAL_UNIT.get(self._signal() or "", "")
        self.lbl_cross.configure(text=f"t={event.xdata:.4g} s   y={event.ydata:.4g} {unit}")

    def toggle_legend(self):
        self._legend_visible = not self._legend_visible
        leg = self.ax.get_legend()
        if leg is not None:
            leg.set_visible(self._legend_visible)
        self.btn_legend.configure(
            text="Legend ON" if self._legend_visible else "Legend OFF",
            bootstyle="secondary" if self._legend_visible else "secondary-outline",
        )
        self.canvas.draw_idle()

    # ------------------------------------------------------------ Ventanas
    def _toggle_add_mode(self):
        self._add_mode = not self._add_mode
        self._pending = None
        if self._add_mode:
            if self._pick_cid is None:
                self._pick_cid = self.canvas.mpl_connect("button_press_event", self._on_add_click)
            self.btn_add.configure(bootstyle="success")
            self._set_status(
                "Add-window ON: select ONE run in the tree, then click the start and the end "
                "of the window on the plot (toolbar pan/zoom must be off)."
            )
        else:
            if self._pick_cid is not None:
                try:
                    self.canvas.mpl_disconnect(self._pick_cid)
                except Exception:
                    pass
                self._pick_cid = None
            self.btn_add.configure(bootstyle="secondary-outline")
            self._set_status("Add-window OFF.")
        self._redraw()

    @staticmethod
    def _snap(run, x):
        """Tiempo de la muestra de `run` más cercana a x (None si no hay muestras)."""
        ts = run.sample_times()
        if ts.size == 0:
            return None
        return float(ts[int(np.argmin(np.abs(ts - x)))])

    def _on_add_click(self, event):
        try:
            if getattr(self.toolbar_mpl, "mode", "") not in ("", None):
                return
        except Exception:
            pass
        if event.inaxes is not self.ax or event.xdata is None:
            return
        run = self._target_run()
        if run is None:
            self._set_status("Select exactly one run in the tree first.")
            return
        t = self._snap(run, float(event.xdata))
        if t is None:
            return
        if self._pending is None or self._pending[0] is not run:
            self._pending = (run, t)
            self._set_status(f"Window start at t={t:.2f} s on '{run.name}'. Click the end.")
            self._redraw()
            return
        t_a = self._pending[1]
        self._pending = None
        if t == t_a:
            self._set_status("End equals start; window discarded.")
            self._redraw()
            return
        lo, hi = sorted((t_a, t))
        win = QuickWindow(lo, hi, run.auto_label(lo, hi))
        run.windows.append(win)
        self._redraw()
        note = " — crosses an actuator event (mixed)" if run.changes_in(lo, hi) else ""
        self._set_status(f"Added W{len(run.windows)} on '{run.name}': {lo:.2f}–{hi:.2f} s{note}.")

    def remove_window(self):
        targets = []
        for iid in self.tree_res.selection():
            ref = self._res_ref.get(iid)
            if ref is not None and ref not in targets:
                targets.append(ref)
        if not targets:
            self._set_status("Select window row(s) in the stats table to remove.")
            return
        for run, win in targets:
            if win in run.windows:
                run.windows.remove(win)
        self._redraw()
        self._set_status(f"Removed {len(targets)} window(s).")

    def clear_windows(self):
        runs = self._runs_of(self._selected_refs()) or self.runs
        n = sum(len(r.windows) for r in runs)
        for r in runs:
            r.windows.clear()
        self._pending = None
        self._redraw()
        scope = f"{len(runs)} run(s)" if runs is not self.runs else "all runs"
        self._set_status(f"Cleared {n} window(s) from {scope}.")

    # --- edición in situ de la etiqueta ---
    def _begin_label_edit(self, event):
        self._cancel_label_edit()
        tree = self.tree_res
        iid = tree.identify_row(event.y)
        if not iid or iid not in self._res_ref:
            return
        col_id = tree.identify_column(event.x)  # "#k", 1-based sobre displaycolumns
        try:
            col = self._stats_cols[int(col_id.lstrip("#")) - 1]
        except (ValueError, IndexError):
            return
        if col != "label":
            return
        bbox = tree.bbox(iid, "label")
        if not bbox:
            return
        _run, win = self._res_ref[iid]
        x, y, w, h = bbox
        entry = ttk.Entry(tree)
        entry.insert(0, win.label)
        entry.select_range(0, ttk.END)
        entry.place(x=x, y=y, width=max(w, 120), height=h + 16)
        entry.focus_set()
        entry.bind("<Return>", lambda _e: self._commit_label_edit(win))
        entry.bind("<Escape>", lambda _e: self._cancel_label_edit())
        entry.bind("<FocusOut>", lambda _e: self._commit_label_edit(win))
        self._label_entry = entry

    def _commit_label_edit(self, win):
        entry = self._label_entry
        if entry is None:
            return
        text = entry.get().strip()
        self._cancel_label_edit()
        if text == win.label:
            return
        win.label = text
        self._redraw()
        self._set_status(f"Window label set to '{text}'.")

    def _cancel_label_edit(self):
        entry = self._label_entry
        self._label_entry = None
        if entry is not None:
            try:
                entry.destroy()
            except Exception:
                pass

    # ------------------------------------------------------------ Acciones
    def toggle_visibility(self):
        refs = self._selected_refs()
        if not refs:
            self._set_status("Select traces, runs or files in the tree.")
            return
        traces = []
        for ref in refs:
            if ref[0] == "trace":
                cand = [ref[2]]
            else:
                cand = [tr for r in self._runs_of([ref]) for tr in r.traces]
            traces.extend(tr for tr in cand if tr not in traces)
        # Un nodo con alguna traza visible se oculta entero; si ya estaba oculto, se muestra.
        show = not any(tr.visible for tr in traces)
        for tr in traces:
            tr.visible = show
        self._refresh_tree()
        self._redraw()

    def remove_selected(self):
        refs = [ref for ref in self._selected_refs() if ref[0] != "trace"]
        if not refs:
            self._set_status("Select a run or a file to remove (traces are hidden, not removed).")
            return
        drop = self._runs_of(refs)
        self.runs = [r for r in self.runs if r not in drop]
        if self._focus_run in drop:
            self._focus_run = None
        if self._pending is not None and self._pending[0] in drop:
            self._pending = None
        self._refresh_tree()
        self._redraw()
        self._set_status(f"Removed {len(drop)} run(s).")

    def clear_all(self):
        self.runs.clear()
        self._focus_run = None
        self._pending = None
        self._refresh_tree()
        self._redraw()
        self._set_status("Cleared.")

    # ------------------------------------------------------------ Carga
    def _add_parsed(self, parsed, source_of):
        """Agrega corridas parseadas (`parse_readings`) con nombre de fuente
        `source_of(file)`. Devuelve cuántas corridas entraron."""
        added = 0
        for (file, run_no), e in parsed.items():
            traces = [QuickTrace(ch, ts, vs) for ch, (ts, vs) in e["channels"].items()]
            self.runs.append(
                QuickRun(source_of(file), run_no, e["signal"], traces, e["settings"], e["events"])
            )
            added += 1
        return added

    def load_file(self):
        """Carga uno o varios `unified_*.xlsx` de Quick Control (hojas `data` y, si
        existen, `settings` / `events`)."""
        paths = askopenfilenames(
            title="Select Quick Control readings",
            initialdir=experiment_dir("quick"),
            filetypes=XLSX_FILETYPES,
        )
        if not paths:
            return
        notes = []
        loaded = 0
        for path in paths:
            base = os.path.basename(path)
            try:
                sheets = read_sheets_text(path)
            except Exception as e:
                notes.append(f"{base}: error ({e})")
                continue
            data = sheets.get("data")
            if data and "file" in [h.strip() for h in data[0]]:
                notes.append(f"{base}: analysis export — use Import")
                continue
            parsed = parse_readings(sheets)
            if isinstance(parsed, str):
                notes.append(f"{base}: not recognized ({parsed})")
                continue
            signal = next(iter(parsed.values()))["signal"]
            if any(e["signal"] != signal for e in parsed.values()):
                notes.append(f"{base}: mixed signals")
                continue
            conflict = self._signal_conflict(signal)
            if conflict:
                notes.append(f"{base}: {conflict}")
                continue
            source = self._unique_source(_short_source(path))
            loaded += self._add_parsed(parsed, lambda _f, s=source: s)
        self._refresh_tree()
        self._redraw()
        msg = f"Loaded {loaded} run(s)."
        if notes:
            msg += " Skipped: " + "; ".join(notes)
        self._set_status(msg)

    def _seed_live(self, report=True):
        """Siembra las corridas en memoria de Quick Control como fuente "live" (copia:
        lo que se siga leyendo después no aparece hasta "Reload live")."""
        qf = self.quick_frame
        try:
            live = list(getattr(qf, "runs", []) or [])
        except Exception:
            live = []
        live = [r for r in live if r.get("t")]
        if not live:
            if report:
                self._set_status("No live Quick Control readings in memory.")
            return 0
        signal = live[-1].get("signal")
        if signal not in SIGNAL_NAME:
            return 0
        conflict = self._signal_conflict(signal)
        if conflict:
            if report:
                self._set_status(f"Live readings not loaded: {conflict}")
            return 0
        source = self._unique_source(LIVE_SOURCE)
        added = 0
        for rd in live:
            if rd.get("signal") != signal:
                continue
            times = list(rd["t"])
            rows = list(rd.get("v", []))[: len(times)]
            times = times[: len(rows)]
            cols = rd.get("cols") or ["value"]
            traces = [
                QuickTrace(c, times, [row[ci] if ci < len(row) else float("nan") for row in rows])
                for ci, c in enumerate(cols)
            ]
            settings = {k: v for k, v in rd.get("settings", [])}
            events = list(rd.get("events", []))
            run = QuickRun(source, rd.get("run", added + 1), signal, traces, settings, events)
            run.live = True
            self.runs.append(run)
            added += 1
        if report:
            self._set_status(f"Loaded {added} live run(s).")
        return added

    def reload_live(self):
        """Reemplaza las corridas "live" por lo que Quick Control tiene ahora en memoria
        (sus ventanas se descartan; las de archivos cargados no se tocan)."""
        if self.quick_frame is None:
            self._set_status("Live readings are only available when opened from the main window.")
            return
        old = [r for r in self.runs if r.live]
        self.runs = [r for r in self.runs if r not in old]
        if self._focus_run in old:
            self._focus_run = None
        if self._pending is not None and self._pending[0] in old:
            self._pending = None
        self._seed_live(report=True)
        self._refresh_tree()
        self._redraw()

    # ------------------------------------------------------------ Export / Import
    def export_results(self):
        """Un libro re-importable: `data` / `settings` / `events` (con columna `file`),
        `windows` y `stats` (todas las ventanas y canales, visibles o no)."""
        if not self.runs:
            self._set_status("Nothing to export.")
            return
        path = asksaveasfilename(
            title="Export Quick Control analysis",
            defaultextension=".xlsx",
            initialdir=experiment_dir("quick"),
            initialfile=f"quick_analysis_{time.strftime('%Y%m%d_%H%M')}.xlsx",
            filetypes=XLSX_FILETYPES,
        )
        if not path:
            return
        path = xlsx_path(path)
        signal = self._signal() or ""
        unit = SIGNAL_UNIT.get(signal, "")
        extra = STATS_EXTRA.get(signal, ())
        data: list[list] = [["file", "t_s", "value", "channel", "signal", "run"]]
        settings: list[list] = [["file", "run", "key", "value"]]
        events: list[list] = [["file", "run", "t_s", "actuator", "state"]]
        windows: list[list] = [["file", "run", "label", "t_a", "t_b"]]
        names: list[list] = [["file", "run", "channel", "name"]]  # solo trazas renombradas
        stats: list[list] = [
            ["file", "run", "window", "channel", "name", "label", "mixed", "unit", "t_a_s", "t_b_s",
             "duration_s", "n", "mean", "std", "cv_pct", "pp", "slope_per_s"]
            + [{"d_tc": "d_vs_thermocouple", "drift": "drift_pct",
                "mean_na": "mean_nA", "std_na": "std_nA"}[c] for c in extra]
        ]
        nan = float("nan")
        for r in self.runs:
            for tr in r.traces:
                data.extend(
                    [r.source, float(t), float(v), tr.channel, r.signal, r.run]
                    for t, v in zip(tr.times, tr.values)
                )
                if tr.name:
                    names.append([r.source, r.run, tr.channel, tr.name])
            settings.extend([r.source, r.run, k, v] for k, v in r.settings.items())
            events.extend([r.source, r.run, t, a, s] for t, a, s in r.events)
            for k, w in enumerate(r.windows, start=1):
                windows.append([r.source, r.run, w.label, w.t_a, w.t_b])
                mixed = int(r.changes_in(w.t_a, w.t_b))
                for st in window_stats(r, w):
                    row = [
                        r.source, r.run, f"W{k}", st["channel"], st["trace"].name, w.label,
                        mixed, unit,
                        st["t_a"], st["t_b"], st["dur"], st["n"], st["mean"], st["std"],
                        st["cv"], st["pp"], st["slope"],
                    ]
                    row += [st.get(c, nan) for c in extra]
                    stats.append(row)
        try:
            write_workbook(
                path,
                {"data": data, "settings": settings, "events": events,
                 "windows": windows, "names": names, "stats": stats},
            )
        except Exception as e:
            self._set_status(f"Export error: {e}")
            return
        nwin = sum(len(r.windows) for r in self.runs)
        self._set_status(f"Exported {len(self.runs)} run(s), {nwin} window(s) → {os.path.basename(path)}.")

    def import_analysis(self):
        """Importa un export de esta pestaña: trazas, settings, eventos y ventanas
        con sus etiquetas."""
        path = askopenfilename(
            title="Select Quick Control analysis export",
            initialdir=experiment_dir("quick"),
            filetypes=XLSX_FILETYPES,
        )
        if not path:
            return
        base = os.path.basename(path)
        try:
            sheets = read_sheets_text(path)
        except Exception as e:
            self._set_status(f"Import error: {e}")
            return
        parsed = parse_readings(sheets, file_col=True)
        if isinstance(parsed, str):
            self._set_status(f"Not a Quick Control analysis export: {parsed}.")
            return
        signals = {e["signal"] for e in parsed.values()}
        if len(signals) != 1:
            self._set_status("Export mixes signals; not imported.")
            return
        conflict = self._signal_conflict(signals.pop())
        if conflict:
            self._set_status(conflict)
            return
        # Nombres de fuente únicos frente a lo ya cargado, iguales para todas las
        # corridas de un mismo archivo del export.
        taken = {r.source for r in self.runs}
        names = {}
        for file, _run in parsed:
            if file not in names:
                names[file] = self._unique_source(file or "import", taken)
                taken.add(names[file])
        first = len(self.runs)
        added = self._add_parsed(parsed, lambda f: names[f])
        by_key = {(r.source, r.run): r for r in self.runs[first:]}
        w_col = _columns(sheets.get("windows"), ("file", "run", "label", "t_a", "t_b"))
        nwin = 0
        if w_col is not None:
            for row in sheets["windows"][1:]:
                file = _cell(row, w_col, "file")
                run_no = _run_key(_cell(row, w_col, "run"))
                run = by_key.get((names.get(file, ""), run_no)) if run_no is not None else None
                if run is None:
                    continue
                try:
                    t_a = float(_cell(row, w_col, "t_a"))
                    t_b = float(_cell(row, w_col, "t_b"))
                except (TypeError, ValueError):
                    continue
                if t_a == t_b:
                    continue
                run.windows.append(QuickWindow(t_a, t_b, _cell(row, w_col, "label")))
                nwin += 1
        # Nombres visibles de las trazas renombradas (exports anteriores no traen la hoja).
        n_col = _columns(sheets.get("names"), ("file", "run", "channel", "name"))
        if n_col is not None:
            for row in sheets["names"][1:]:
                run_no = _run_key(_cell(row, n_col, "run"))
                run = by_key.get((names.get(_cell(row, n_col, "file"), ""), run_no)) if run_no is not None else None
                if run is None:
                    continue
                channel = _cell(row, n_col, "channel")
                for tr in run.traces:
                    if tr.channel == channel:
                        tr.name = _cell(row, n_col, "name")
        self._refresh_tree()
        self._redraw()
        self._set_status(f"Imported {added} run(s), {nwin} window(s) from {base}.")


__author__ = "Edisson A. Naula"
__date__ = "2026-11-17"
