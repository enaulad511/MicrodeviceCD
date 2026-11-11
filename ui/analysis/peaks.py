# -*- coding: utf-8 -*-
import os
import re
import time
from tkinter.filedialog import askopenfilename, asksaveasfilename
from typing import TYPE_CHECKING

import numpy as np
import ttkbootstrap as ttk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

from templates.utils import experiment_dir
from templates.xlsx_io import (
    XLSX_FILETYPES,
    num_or_text,
    read_sheet_text,
    write_workbook,
    xlsx_path,
)
from ui.analysis.common import CycleCurve, Experiment, _apply_filter, plt
from ui.analysis.pcr import PLOT_FIG_W_IN, PLOT_IN_PER_WEIGHT

if TYPE_CHECKING:
    from matplotlib.axes import Axes


# ---------------------------------------------------------------------------
# Vistas del área de gráficas (mismo esquema que la pestaña PCR)
# ---------------------------------------------------------------------------
# Cada vista es la lista de ejes que se construyen, por clave. Los que no están en la
# vista **no se crean** (`self.ax_* = None`) y todo el código de dibujo lo tolera.
PLOT_VIEWS = {
    "Overlay": ("overlay",),
    "Trends": ("min", "max"),
    "All (3)": ("overlay", "min", "max"),
}
PLOT_VIEW_NAMES = tuple(PLOT_VIEWS)
PLOT_VIEW_DEFAULT = "Overlay"

# Peso relativo de cada eje: el overlay (el interactivo: hover, Pick X) se lleva 1.5 veces
# lo de las tendencias. El alto de la figura es `PLOT_IN_PER_WEIGHT · Σ pesos`, con la
# MISMA constante que PCR (se importa de ahí): un gráfico mide lo mismo solo o acompañado,
# y en las dos pestañas; la vista solo cambia cuánto scroll hay que recorrer. **No atar
# esto a `winfo_height()`** — en la Raspberry salían diminutos. Ver docs/pcr_analisis.md §4.4.
PLOT_ROW_WEIGHT = {"overlay": 3, "min": 2, "max": 2}


# ---------------------------------------------------------------------------
# Filtros y picos (CV/SWV)
# ---------------------------------------------------------------------------


# Etiquetas de EventPlotter.load_data: 'file-r{run}c{cycle}' (actual, con Keep runs)
# o 'file-c{cycle}' (legado, sin columna run).
_LBL_RUN_RE = re.compile(r"^(.+)-r(\d+)c(\d+)$")
_LBL_RE = re.compile(r"^(.+)-c(\d+)$")


def _parse_imported_label(label):
    """Convierte 'file-r2c3' → ('file', 2, 3) y 'file-c3' → ('file', None, 3);
    si no matchea, ('label', None, None)."""
    s = str(label)
    m = _LBL_RUN_RE.match(s)
    if m:
        return m.group(1), int(m.group(2)), int(m.group(3))
    m = _LBL_RE.match(s)
    if m:
        return m.group(1), None, int(m.group(2))
    return s, None, None


def _run_experiment_name(base, run, n_runs):
    """Un Experiment por corrida: 'file-r{run}' si el archivo trae varias corridas;
    con una sola (o sin columna run) conserva el nombre del archivo."""
    return f"{base}-r{run}" if n_runs > 1 else base


def _global_extrema(xs, ys):
    if len(ys) == 0:
        return [], []
    i_max = int(np.argmax(ys))
    i_min = int(np.argmin(ys))
    return [(float(xs[i_max]), float(ys[i_max]))], [(float(xs[i_min]), float(ys[i_min]))]


def _local_extrema(xs, ys, window=5):
    n = len(ys)
    if n < 2 * window + 1:
        return [], []
    maxima = []
    minima = []
    for i in range(window, n - window):
        seg = ys[i - window : i + window + 1]
        v = ys[i]
        if v == seg.max() and v > seg.min():
            maxima.append((float(xs[i]), float(v)))
        elif v == seg.min() and v < seg.max():
            minima.append((float(xs[i]), float(v)))
    return maxima, minima


def _at_x_extrema(xs, ys, x_max_target, x_min_target):
    """Muestrea y en el punto más cercano a un X dado por el usuario.

    Cada target puede ser None para omitir ese extremo.
    """
    maxs, mins = [], []
    if len(xs) == 0:
        return maxs, mins
    xs = np.asarray(xs, dtype=float)
    if x_max_target is not None:
        i = int(np.argmin(np.abs(xs - x_max_target)))
        maxs.append((float(xs[i]), float(ys[i])))
    if x_min_target is not None:
        i = int(np.argmin(np.abs(xs - x_min_target)))
        mins.append((float(xs[i]), float(ys[i])))
    return maxs, mins


# ---------------------------------------------------------------------------
# Pestaña: análisis de picos (CV/SWV) — antes era toda la ventana AnalysisWindow
# ---------------------------------------------------------------------------
class PeakAnalysisFrame(ttk.Frame):
    """Pestaña de análisis de picos: experimentos (archivos) → ciclos → tendencia."""

    FILTERS = ("none", "moving_avg", "median")

    def __init__(self, master, owner, plotter=None, **kwargs):
        super().__init__(master, **kwargs)
        self.owner = owner
        self.experiments = []  # list[Experiment]
        # mapeo de iid de Treeview → ("exp", exp) o ("cycle", exp, cycle)
        self._tree_ref = {}
        # mismo mapeo para las filas renombrables de la tabla de resultados
        self._res_ref = {}
        # estado para picking de X desde la gráfica overlay
        self._pick_cid: int | None = None
        self._pick_kind: str | None = None  # 'max' | 'min' | None
        # Resultado dibujable del último Compute (markers, guías At X, tendencias). Se
        # guarda para que cambiar de vista redibuje sin recalcular; None = nada computado
        # o invalidado porque cambiaron los datos (_refresh_overlay).
        self._computed: dict | None = None
        # Ejes de la vista actual; los que la vista no pide quedan en None.
        self.ax_overlay: "Axes | None" = None
        self.ax_min: "Axes | None" = None
        self.ax_max: "Axes | None" = None

        self._build_ui()
        # Solo CV alimenta la tabla de picos desde las líneas cargadas del plotter;
        # EIS y SWV tienen su propia pestaña (SWV → SqwvAnalysisFrame, decisión Q12),
        # así que un plotter de esos métodos deja esta pestaña vacía.
        if plotter is not None and getattr(plotter, "method", "") not in ("eis", "sqwv"):
            self._snapshot_from_plotter(plotter)
            self._refresh_tree()
            self._refresh_overlay()

    # ---------------------------------------------------------------------
    # UI
    # ---------------------------------------------------------------------
    def _build_ui(self):
        # --- Toolbar fila 1: archivo (izq) + globales (der). Dos filas para que en
        # pantallas chicas (touchscreen del Pi) no se corten Clear all / Legend. ---
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
        self._legend_visible = True
        self.btn_legend = ttk.Button(
            toolbar, text="Legend ON", bootstyle="secondary", command=self.toggle_legend
        )
        self.btn_legend.pack(side=ttk.RIGHT, padx=3)
        ttk.Button(
            toolbar, text="Clear all", bootstyle="danger-outline", command=self.clear_all
        ).pack(side=ttk.RIGHT, padx=3)

        # --- Toolbar fila 1b: acciones de selección / cómputo ---
        toolbar_b = ttk.Frame(self)
        toolbar_b.pack(side=ttk.TOP, fill=ttk.X, padx=6, pady=(0, 2))
        ttk.Button(
            toolbar_b, text="🗑 Remove", bootstyle="danger", command=self.remove_selected
        ).pack(side=ttk.LEFT, padx=3)
        ttk.Button(
            toolbar_b, text="👁 Show/Hide", bootstyle="info", command=self.toggle_visibility
        ).pack(side=ttk.LEFT, padx=3)
        ttk.Button(
            toolbar_b, text="📊 Compute", bootstyle="success", command=self.compute_extrema
        ).pack(side=ttk.LEFT, padx=3)

        # Qué ejes se dibujan (como en PCR). Cada gráfico mide siempre lo mismo, así que
        # esto no cambia el tamaño sino cuánto scroll hay que recorrer. Cambiar de vista
        # no recalcula: redibuja el último Compute.
        ttk.Label(toolbar_b, text="View:").pack(side=ttk.LEFT, padx=(12, 4))
        self.view_var = ttk.StringVar(value=PLOT_VIEW_DEFAULT)
        ttk.Combobox(
            toolbar_b,
            textvariable=self.view_var,
            values=PLOT_VIEW_NAMES,
            state="readonly",
            width=10,
        ).pack(side=ttk.LEFT)
        self.view_var.trace_add("write", lambda *_a: self._redraw())

        # --- Toolbar fila 2: selectores de picos + filtro ---
        toolbar2 = ttk.Frame(self)
        toolbar2.pack(side=ttk.TOP, fill=ttk.X, padx=6, pady=(0, 6))

        ttk.Label(toolbar2, text="Peaks:").pack(side=ttk.LEFT, padx=(0, 4))
        self.peak_mode = ttk.StringVar(value="global")
        ttk.Radiobutton(toolbar2, text="Global", variable=self.peak_mode, value="global").pack(
            side=ttk.LEFT
        )
        ttk.Radiobutton(toolbar2, text="Local", variable=self.peak_mode, value="local").pack(
            side=ttk.LEFT
        )
        ttk.Radiobutton(toolbar2, text="At X", variable=self.peak_mode, value="at_x").pack(
            side=ttk.LEFT
        )

        ttk.Label(toolbar2, text="Peak window:").pack(side=ttk.LEFT, padx=(12, 4))
        self.peak_window_var = ttk.IntVar(value=5)
        ttk.Spinbox(
            toolbar2, from_=1, to=500, increment=1, width=5, textvariable=self.peak_window_var
        ).pack(side=ttk.LEFT)

        ttk.Separator(toolbar2, orient=ttk.VERTICAL).pack(side=ttk.LEFT, fill=ttk.Y, padx=8)

        ttk.Label(toolbar2, text="Filter:").pack(side=ttk.LEFT, padx=(0, 4))
        self.filter_var = ttk.StringVar(value="none")
        ttk.Combobox(
            toolbar2,
            textvariable=self.filter_var,
            values=self.FILTERS,
            state="readonly",
            width=12,
        ).pack(side=ttk.LEFT)

        ttk.Label(toolbar2, text="Filter window:").pack(side=ttk.LEFT, padx=(8, 4))
        self.filter_window_var = ttk.IntVar(value=5)
        ttk.Spinbox(
            toolbar2, from_=1, to=500, increment=1, width=5, textvariable=self.filter_window_var
        ).pack(side=ttk.LEFT)

        # --- Toolbar fila 3: entradas para modo "At X" ---
        toolbar3 = ttk.Frame(self)
        toolbar3.pack(side=ttk.TOP, fill=ttk.X, padx=6, pady=(0, 6))

        ttk.Label(toolbar3, text="At X →").pack(side=ttk.LEFT, padx=(0, 4))
        ttk.Label(toolbar3, text="X@max:").pack(side=ttk.LEFT, padx=(0, 4))
        self.x_at_max_var = ttk.StringVar(value="")
        ttk.Entry(toolbar3, textvariable=self.x_at_max_var, width=12).pack(side=ttk.LEFT)
        ttk.Button(
            toolbar3,
            text="Pick X@max",
            bootstyle="secondary-outline",
            command=lambda: self._toggle_pick_mode("max"),
        ).pack(side=ttk.LEFT, padx=(4, 8))

        ttk.Label(toolbar3, text="X@min:").pack(side=ttk.LEFT, padx=(0, 4))
        self.x_at_min_var = ttk.StringVar(value="")
        ttk.Entry(toolbar3, textvariable=self.x_at_min_var, width=12).pack(side=ttk.LEFT)
        ttk.Button(
            toolbar3,
            text="Pick X@min",
            bootstyle="secondary-outline",
            command=lambda: self._toggle_pick_mode("min"),
        ).pack(side=ttk.LEFT, padx=(4, 8))

        ttk.Button(
            toolbar3, text="Clear X", bootstyle="warning-outline", command=self._clear_at_x
        ).pack(side=ttk.LEFT, padx=(0, 4))

        # Lectura por hover (snap al punto medido más cercano del overlay).
        self.lbl_cross = ttk.Label(toolbar3, text="", anchor="e")
        self.lbl_cross.pack(side=ttk.RIGHT, padx=6)

        # Barra de navegación de matplotlib (zoom/pan/home/save) en fila propia, FUERA del
        # área con scroll (como en PCR, docs/pcr_analisis.md §4.3): colgada bajo el canvas
        # quedaba al pie de la figura, que en "All (3)" mide ~1260 px. Sirve a cualquier
        # eje. El contenedor es persistente; _reset_plot_canvas recrea el toolbar dentro.
        self._mpl_toolbar_host = ttk.Frame(self)
        self._mpl_toolbar_host.pack(side=ttk.TOP, fill=ttk.X, padx=6, pady=(0, 4))

        # Status bar anclado al fondo antes de que el área de scroll ocupe el centro
        self.lbl_status = ttk.Label(self, text="Ready.", anchor="w")
        self.lbl_status.pack(side=ttk.BOTTOM, fill=ttk.X, padx=6, pady=(0, 4))

        # --- Frame padre con scroll vertical que envuelve árbol + gráficas + resultados ---
        _wrap = ttk.Frame(self)
        _wrap.pack(fill=ttk.BOTH, expand=True, padx=6, pady=(0, 4))

        _vsb_main = ttk.Scrollbar(_wrap, orient="vertical")
        _vsb_main.pack(side=ttk.RIGHT, fill=ttk.Y)

        self._main_sc = ttk.Canvas(_wrap, bd=0, highlightthickness=0, yscrollcommand=_vsb_main.set)
        self._main_sc.pack(side=ttk.LEFT, fill=ttk.BOTH, expand=True, padx=(5, 20))
        _vsb_main.configure(command=self._main_sc.yview)

        # Frame interior donde vive todo el contenido
        inner = ttk.Frame(self._main_sc)
        _win_id = self._main_sc.create_window((0, 0), window=inner, anchor="nw")

        # Sincronizar scrollregion y ancho del inner con el canvas
        def _update_sr(_event=None):
            self._main_sc.configure(scrollregion=self._main_sc.bbox("all"))

        def _sync_width(event):
            self._main_sc.itemconfig(_win_id, width=event.width)

        inner.bind("<Configure>", _update_sr)
        self._main_sc.bind("<Configure>", _sync_width)

        # Rueda del ratón — no interfiere con Treeviews ni matplotlib porque
        # bind() en esos widgets tiene prioridad sobre bind() aquí
        def _on_wheel(event):
            self._main_sc.yview_scroll(int(-1 * (event.delta / 120)), "units")

        self._main_sc.bind("<MouseWheel>", _on_wheel)
        inner.bind("<MouseWheel>", _on_wheel)

        # --- Split horizontal árbol | gráficas (dentro del frame interior) ---
        main = ttk.PanedWindow(inner, orient=ttk.HORIZONTAL)
        main.pack(fill=ttk.X, padx=0, pady=(0, 6))

        # Left: árbol de experimentos / ciclos
        left = ttk.LabelFrame(main, text="Experiments → Cycles")
        main.add(left, weight=1)

        cols = ("info",)
        self.tree_curves = ttk.Treeview(
            left, columns=cols, show="tree headings", selectmode="extended"
        )
        self.tree_curves.heading("#0", text="Item")
        self.tree_curves.heading("info", text="State")
        self.tree_curves.column("#0", width=290, anchor="w")
        self.tree_curves.column("info", width=90, anchor="w")
        vsb_c = ttk.Scrollbar(left, orient="vertical", command=self.tree_curves.yview)
        self.tree_curves.configure(yscrollcommand=vsb_c.set)
        self.tree_curves.pack(side=ttk.LEFT, fill=ttk.BOTH, expand=True, padx=4, pady=4)
        vsb_c.pack(side=ttk.LEFT, fill=ttk.Y)
        # Doble clic sobre un nombre → editarlo in-place; al confirmar se renombra el
        # experimento/ciclo y, con ello, su etiqueta de leyenda en el overlay.
        self.tree_curves.bind("<Double-1>", self._begin_rename)
        self._rename_entry: "ttk.Entry | None" = None  # Entry overlay activo (None = ninguno)

        # Right: figura con los ejes de la vista (overlay / tendencias min, max)
        right = ttk.Frame(main)
        main.add(right, weight=4)
        right.bind("<MouseWheel>", _on_wheel)
        plt.style.use("seaborn-v0_8-darkgrid")
        # Host de la figura; el canvas se (re)crea en _create_plot_canvas para poder
        # reconstruirlo limpio en cada redibujo (mismo patrón que EISAnalysisFrame).
        self._plot_host = right
        self._create_plot_canvas()

        # --- Tabla de resultados (debajo del split, dentro del frame interior) ---
        bottom = ttk.LabelFrame(inner, text="Results (visible only)")
        bottom.pack(fill=ttk.BOTH, pady=(0, 6))
        cols_r = ("idx", "type", "n", "x", "y", "std")
        self.tree_res = ttk.Treeview(bottom, columns=cols_r, show="tree headings", height=16)
        widths = {"idx": 50, "type": 80, "n": 50, "x": 130, "y": 130, "std": 130}
        self.tree_res.heading("#0", text="Experiment / Cycle")
        self.tree_res.column("#0", width=300, anchor="w")
        for c in cols_r:
            self.tree_res.heading(c, text=c)
            self.tree_res.column(c, width=widths[c], anchor="w")
        vsb_r = ttk.Scrollbar(bottom, orient="vertical", command=self.tree_res.yview)
        hsb_r = ttk.Scrollbar(bottom, orient="horizontal", command=self.tree_res.xview)
        self.tree_res.configure(yscrollcommand=vsb_r.set, xscrollcommand=hsb_r.set)
        vsb_r.pack(side=ttk.RIGHT, fill=ttk.Y)
        hsb_r.pack(side=ttk.BOTTOM, fill=ttk.X)
        self.tree_res.pack(fill=ttk.BOTH, expand=True)
        # Doble clic sobre el nombre de un experimento/ciclo en la tabla de resultados
        # también lo renombra (reusa el editor in-place; comparte _res_ref).
        self.tree_res.bind("<Double-1>", self._begin_rename)

    # ---------------------------------------------------------------------
    # Canvas de la figura (se recrea limpio en cada redibujo)
    # ---------------------------------------------------------------------
    # Título / etiquetas por eje, indexados por la misma clave que PLOT_VIEWS.
    AX_SPECS = {
        "overlay": ("Curves overlay", "", ""),
        "min": ("Min Peaks Trend", "Experiment", ""),
        "max": ("Max Peaks Trend", "Experiment", ""),
    }

    def _current_view(self):
        """Claves de los ejes que pide la vista actual (cae al default si es inválida)."""
        return PLOT_VIEWS.get(self.view_var.get(), PLOT_VIEWS[PLOT_VIEW_DEFAULT])

    def _create_plot_canvas(self):
        # Ejes apilados en una columna, alto proporcional a los de la vista (ver
        # PLOT_ROW_WEIGHT). El ancho es solo el pedido inicial: Tk estira el canvas al
        # ancho del panel y matplotlib reescala.
        keys = self._current_view()
        weights = [PLOT_ROW_WEIGHT[k] for k in keys]
        self.fig = Figure(
            figsize=(PLOT_FIG_W_IN, PLOT_IN_PER_WEIGHT * sum(weights)),
            dpi=100,
            layout="constrained",
        )
        gs = self.fig.add_gridspec(len(keys), 1, height_ratios=weights)
        # Todos arrancan en None: los ejes fuera de la vista no existen y el dibujo los
        # saltea en vez de pintar sobre un eje fantasma.
        self.ax_overlay = self.ax_min = self.ax_max = None
        for row, key in enumerate(keys):
            ax = self.fig.add_subplot(gs[row])
            title, xlabel, ylabel = self.AX_SPECS[key]
            ax.set_title(title)
            ax.set_xlabel(xlabel)
            ax.set_ylabel(ylabel)
            setattr(self, f"ax_{key}", ax)
        self.canvas = FigureCanvasTkAgg(self.fig, self._plot_host)
        tkw = self.canvas.get_tk_widget()
        # Mismo guard que PCR (docs/pcr_analisis.md §4.4): al abrir, Tk manda un
        # <Configure> transitorio de 1 px de alto y constrained_layout avisa "axes sizes
        # collapsed to zero". Se ignora; el siguiente trae el tamaño real.
        tkw.bind(
            "<Configure>",
            lambda e: self.canvas.resize(e) if e.width > 1 and e.height > 1 else None,
        )
        tkw.pack(fill=ttk.BOTH, expand=True)
        # El toolbar cuelga del contenedor fijo, no del área con scroll.
        self.toolbar_mpl = NavigationToolbar2Tk(
            self.canvas, self._mpl_toolbar_host, pack_toolbar=False
        )
        self.toolbar_mpl.pack(fill=ttk.X)
        self.canvas.mpl_connect("motion_notify_event", self._on_hover)
        # Re-arma el Pick X@max/min si seguía pendiente (el canvas se recrea en cada
        # redibujo, invalidando el cid anterior). Sin overlay en la vista queda en
        # espera y se re-arma al volver a una vista que lo traiga.
        if self._pick_kind is not None and self.ax_overlay is not None:
            self._pick_cid = self.canvas.mpl_connect("button_press_event", self._on_pick)

    def _reset_plot_canvas(self):
        # Destruye canvas+toolbar y los recrea desde cero (mismo patrón que
        # EISAnalysisFrame): evita estado residual de constrained_layout en el canvas
        # Tk vivo. El cid del pick apuntaba al canvas viejo; _create_plot_canvas lo re-arma.
        self._pick_cid = None
        try:
            self.toolbar_mpl.destroy()
        except Exception:
            pass
        try:
            self.canvas.get_tk_widget().destroy()
        except Exception:
            pass
        self._create_plot_canvas()

    # ---------------------------------------------------------------------
    # Estado y refresco
    # ---------------------------------------------------------------------
    def _snapshot_from_plotter(self, plotter):
        """Snapshot de loaded_lines del EventPlotter: un Experiment por (archivo, corrida),
        con sus ciclos (mismo criterio que load_file)."""
        # filename → run → list[(cycle_num, xs, ys, raw_label)]
        groups: dict[str, dict[int | None, list]] = {}
        for line in getattr(plotter, "loaded_lines", []):
            try:
                xs = np.asarray(line.get_xdata(), dtype=float)
                ys = np.asarray(line.get_ydata(), dtype=float)
            except Exception:
                continue
            if xs.size == 0:
                continue
            raw = line.get_label()
            base, run, cyc = _parse_imported_label(raw)
            groups.setdefault(base, {}).setdefault(run, []).append((cyc, xs, ys, raw))
        for base, runs in groups.items():
            for run in sorted(runs, key=lambda r: -1 if r is None else r):
                exp = Experiment(name=_run_experiment_name(base, run, len(runs)))
                items = runs[run]
                items.sort(key=lambda t: -1 if t[0] is None else t[0])
                for cyc, xs, ys, raw in items:
                    name = f"c{cyc}" if cyc is not None else raw
                    exp.cycles.append(CycleCurve(name=name, xs=xs, ys=ys))
                self.experiments.append(exp)

    def _refresh_tree(self):
        """Reconstruye el árbol izquierdo y el mapa de iids."""
        self.tree_curves.delete(*self.tree_curves.get_children())
        self._tree_ref = {}
        for exp in self.experiments:
            n_vis = sum(1 for c in exp.cycles if c.visible)
            state = f"{n_vis}/{len(exp.cycles)} 👁"
            exp_iid = self.tree_curves.insert(
                "", ttk.END, text=exp.name, values=(state,), open=True
            )
            self._tree_ref[exp_iid] = ("exp", exp)
            for cycle in exp.cycles:
                mark = "👁" if cycle.visible else "🚫"
                ciid = self.tree_curves.insert(exp_iid, ttk.END, text=cycle.name, values=(mark,))
                self._tree_ref[ciid] = ("cycle", exp, cycle)

    # ---------------------------------------------------------------------
    # Renombrado in-place (doble clic en el árbol)
    # ---------------------------------------------------------------------
    def _begin_rename(self, event):
        """Editor in-place sobre la columna #0 de un árbol: doble clic abre un Entry
        encima de la celda. Enter confirma (renombra exp/ciclo y refresca leyenda),
        Esc/foco-fuera cancela. Solo la columna del nombre (#0) es editable.

        Funciona en ambos árboles: el de la izquierda (tree_curves → _tree_ref) y la
        tabla de resultados (tree_res → _res_ref). Las filas agregadas (⟨max⟩/⟨min⟩)
        no están en _res_ref, así que no son editables."""
        # cancela cualquier editor previo abierto
        self._cancel_rename()
        tree = event.widget
        ref_map = self._tree_ref if tree is self.tree_curves else self._res_ref
        iid = tree.identify_row(event.y)
        if not iid or iid not in ref_map:
            return
        if tree.identify_column(event.x) != "#0":
            return
        bbox = tree.bbox(iid, "#0")
        if not bbox:
            return
        x, y, w, h = bbox
        ref = ref_map[iid]
        current = ref[1].name if ref[0] == "exp" else ref[2].name
        entry = ttk.Entry(tree)
        entry.insert(0, current)
        entry.select_range(0, ttk.END)
        entry.place(x=x, y=y, width=w, height=h + 16)
        entry.focus_set()
        entry.bind("<Return>", lambda _e: self._commit_rename(tree, iid))
        entry.bind("<Escape>", lambda _e: self._cancel_rename())
        entry.bind("<FocusOut>", lambda _e: self._commit_rename(tree, iid))
        self._rename_entry = entry

    def _commit_rename(self, tree, iid):
        entry = self._rename_entry
        if entry is None:
            return
        new_name = entry.get().strip()
        self._cancel_rename()
        ref_map = self._tree_ref if tree is self.tree_curves else self._res_ref
        if not new_name or iid not in ref_map:
            return
        ref = ref_map[iid]
        target = ref[1] if ref[0] == "exp" else ref[2]
        if target.name == new_name:
            return
        target.name = new_name
        # Refresca el árbol de la izquierda y la leyenda siempre; si la tabla de
        # resultados tiene contenido, la recalcula para reflejar el nuevo nombre.
        self._refresh_tree()
        if self.tree_res.get_children():
            self.compute_extrema()  # reconstruye tabla + overlay + tendencias
        else:
            self._refresh_overlay()
        self._set_status(f"Renamed to '{new_name}'.")

    def _cancel_rename(self):
        entry = self._rename_entry
        self._rename_entry = None
        if entry is not None:
            try:
                entry.destroy()
            except Exception:
                pass

    def _refresh_overlay(self):
        """Los datos cambiaron (carga, borrado, visibilidad, import): descarta lo dibujado
        del último Compute y redibuja. Markers y tendencias quedan en blanco hasta el
        siguiente Compute, que es lo correcto porque dependen de datos/filtro que pudieron
        cambiar (la tabla de resultados no se toca, como siempre)."""
        self._computed = None
        self._redraw()

    def _redraw(self):
        """Recrea el canvas (no ax.clear()) y dibuja los ejes de la vista actual: overlay
        + lo guardado del último Compute. No recalcula nada: cambiar de vista solo cambia
        qué se ve."""
        self._reset_plot_canvas()
        comp = self._computed
        self._draw_overlay(comp)
        if comp is not None:
            self._draw_computed(comp)
        self.canvas.draw_idle()

    def _draw_overlay(self, comp):
        """Curvas visibles, filtradas si hay filtro. Con un Compute guardado usa SU filtro,
        no el de la UI: los markers se calcularon sobre esas curvas y un cambio de vista
        no debe separarlos de la línea."""
        ax = self.ax_overlay
        if ax is None:
            return
        if comp is not None:
            kind, fw = comp["filter"], comp["filter_window"]
        else:
            kind = self.filter_var.get()
            fw = max(1, self.filter_window_var.get() or 1)
        # ax.set_title("Curves overlay" + (f" (filtered: {kind})" if kind != "none" else ""))
        ax.set_title("Curves overlay" if kind != "none" else "")
        any_visible = False
        for exp in self.experiments:
            for c in exp.cycles:
                if not c.visible:
                    continue
                ys_disp = _apply_filter(c.ys, kind, fw) if kind != "none" else c.ys
                ax.plot(
                    c.xs,
                    ys_disp,
                    linewidth=1.2,
                    marker=".",
                    markersize=2,
                    label=f"{exp.name}/{c.name}",
                )
                any_visible = True
        if any_visible:
            leg = ax.legend(loc="best", fontsize=7, ncol=2)
            leg.set_visible(self._legend_visible)

    def _draw_computed(self, comp):
        """Markers de picos + guías At X sobre el overlay y tendencias mean ± std, desde
        lo guardado por compute_extrema. Cada parte se saltea si su eje no está en la vista."""
        ax = self.ax_overlay
        if ax is not None:
            # Líneas verticales guía del modo "At X" (None fuera de ese modo).
            for x_target, color in (
                (comp["x_max_target"], "tab:red"),
                (comp["x_min_target"], "tab:blue"),
            ):
                if x_target is not None:
                    ax.axvline(x_target, color=color, linestyle="--", linewidth=1, alpha=0.6)
            if comp["max_xy"]:
                xs, ys = zip(*comp["max_xy"])
                ax.scatter(xs, ys, marker="^", s=40, color="tab:red", zorder=5)
            if comp["min_xy"]:
                xs, ys = zip(*comp["min_xy"])
                ax.scatter(xs, ys, marker="v", s=40, color="tab:blue", zorder=5)
        idx = comp["trend_idx"]
        if not idx:
            return
        for ax, means, stds, color in (
            (self.ax_max, comp["mean_max"], comp["std_max"], "tab:red"),
            (self.ax_min, comp["mean_min"], comp["std_min"], "tab:blue"),
        ):
            if ax is None:
                continue
            ax.errorbar(
                idx, means, yerr=stds, marker="o", linestyle="-", color=color, capsize=4
            )
            ax.set_xticks(idx)  # ticks como índices enteros

    def _set_status(self, msg):
        self.lbl_status.configure(text=msg)

    @staticmethod
    def _parse_float(s):
        s = (s or "").strip()
        if not s:
            return None
        try:
            return float(s)
        except ValueError:
            return None

    def _disarm_pick(self):
        cid = self._pick_cid
        if cid is not None:
            try:
                self.canvas.mpl_disconnect(cid)
            except Exception:
                pass
        self._pick_cid = None
        self._pick_kind = None

    def _toggle_pick_mode(self, kind):
        """Activa la captura de un siguiente clic en la gráfica overlay para
        rellenar X@max o X@min. Un segundo click sobre el mismo botón cancela."""
        # cancelar si ya estaba activo (también si quedó en espera por la vista)
        prev = self._pick_kind
        self._disarm_pick()
        if prev == kind:
            self._set_status("Pick mode cancelled.")
            return
        # El clic se toma sobre el overlay: sin ese eje en la vista no hay dónde. Se
        # avisa en vez de dejar al usuario clickeando sin efecto (como "Add segment" en PCR).
        if self.ax_overlay is None:
            self._set_status("Switch View to 'Overlay' (or 'All') to pick X.")
            return
        self._pick_kind = kind
        self._pick_cid = self.canvas.mpl_connect("button_press_event", self._on_pick)
        # cambia a modo at_x para que el usuario vea el efecto al recomputar
        self.peak_mode.set("at_x")
        self._set_status(f"Click on overlay to set X@{kind} (toolbar pan/zoom must be off).")

    def _on_pick(self, event):
        # ignorar si está activo pan/zoom del toolbar matplotlib
        try:
            if getattr(self.toolbar_mpl, "mode", "") not in ("", None):
                return
        except Exception:
            pass
        if self.ax_overlay is None or event.inaxes is not self.ax_overlay or event.xdata is None:
            return
        x = float(event.xdata)
        if self._pick_kind == "max":
            self.x_at_max_var.set(f"{x:.6g}")
        elif self._pick_kind == "min":
            self.x_at_min_var.set(f"{x:.6g}")
        kind = self._pick_kind
        self._disarm_pick()
        self._set_status(f"X@{kind} = {x:.6g}. Press Compute to apply.")

    def _clear_at_x(self):
        self.x_at_max_var.set("")
        self.x_at_min_var.set("")
        self._set_status("Cleared X@max / X@min.")

    def _on_hover(self, event):
        """Lectura por hover sobre el overlay: snap al punto medido más cercano de
        las curvas visibles. Mide la cercanía en píxeles (transData) para no sesgar
        por las escalas dispares de X (V) e Y (A~1e-5); usa las líneas ya dibujadas,
        así respeta visibilidad y el filtro activo. Las líneas guía (axvline) y los
        markers de picos quedan fuera: solo curvas con label propio (no '_…')."""
        ax = self.ax_overlay
        if ax is None or event.inaxes is not ax or event.x is None:
            self.lbl_cross.configure(text="")
            return
        best: tuple | None = None  # (dist_px, label, x, y)
        for line in ax.get_lines():
            label = str(line.get_label())
            if not label or label.startswith("_") or not line.get_visible():
                continue
            xd = np.asarray(line.get_xdata(), dtype=float)
            yd = np.asarray(line.get_ydata(), dtype=float)
            if xd.size == 0:
                continue
            try:
                pts = ax.transData.transform(np.column_stack([xd, yd]))
            except Exception:
                continue
            d = np.hypot(pts[:, 0] - event.x, pts[:, 1] - event.y)
            j = int(np.argmin(d))
            if best is None or d[j] < best[0]:
                best = (float(d[j]), str(label), float(xd[j]), float(yd[j]))
        if best is None:
            self.lbl_cross.configure(text="")
            return
        self.lbl_cross.configure(text=f"{best[1]}   x={best[2]:.4g}   y={best[3]:.4g}")

    # ---------------------------------------------------------------------
    # Acciones
    # ---------------------------------------------------------------------
    def load_file(self):
        """Carga la hoja `data` de un libro: un Experiment por corrida (columna `run`,
        Keep runs), cada uno con sus ciclos. Sin columna `run` → un solo Experiment."""
        path = askopenfilename(
            title="Select data file",
            initialdir=experiment_dir("cv"),
            filetypes=XLSX_FILETYPES,
        )
        if not path:
            return
        # run → cycle → (xs, ys); el orden de filas del archivo se conserva.
        runs: dict[int, dict[int, tuple[list[float], list[float]]]] = {}
        try:
            rows = read_sheet_text(path, "data") or []
            header = [h.strip() for h in (rows[0] if rows else [])]
            # 'run' se busca por nombre (columna trailing opcional); sin ella → run 0.
            run_col = header.index("run") if "run" in header else None
            for row in rows[1:]:
                if len(row) < 4:
                    continue
                try:
                    x = float(row[1])
                    y = float(row[2])
                    cycle = int(float(row[3]))
                    run = (
                        int(float(row[run_col]))
                        if run_col is not None and run_col < len(row) and row[run_col]
                        else 0
                    )
                except (ValueError, TypeError):
                    continue
                xs, ys = runs.setdefault(run, {}).setdefault(cycle, ([], []))
                xs.append(x)
                ys.append(y)
        except Exception as e:
            self._set_status(f"Error loading data: {e}")
            return
        if not runs:
            self._set_status("No data parsed from file.")
            return
        base = os.path.splitext(os.path.basename(path))[0]
        n_cycles = 0
        for run in sorted(runs):
            exp = Experiment(name=_run_experiment_name(base, run, len(runs)))
            for cyc in sorted(runs[run]):
                xs, ys = runs[run][cyc]
                exp.cycles.append(CycleCurve(name=f"c{cyc}", xs=xs, ys=ys))
            n_cycles += len(exp.cycles)
            self.experiments.append(exp)
        self._refresh_tree()
        self._refresh_overlay()
        self._set_status(
            f"Loaded '{base}': {len(runs)} experiment(s) (runs), {n_cycles} cycle(s)."
        )

    def _selected_refs(self):
        return [self._tree_ref[i] for i in self.tree_curves.selection() if i in self._tree_ref]

    def remove_selected(self):
        refs = self._selected_refs()
        if not refs:
            return
        # Recolecta experimentos a eliminar completos y ciclos individuales
        exps_to_drop = set()
        cycles_to_drop = []  # list of (exp, cycle)
        for ref in refs:
            if ref[0] == "exp":
                exps_to_drop.add(id(ref[1]))
            else:
                cycles_to_drop.append((ref[1], ref[2]))
        # Aplica
        for exp, cycle in cycles_to_drop:
            if id(exp) in exps_to_drop:
                continue  # se eliminará entero
            if cycle in exp.cycles:
                exp.cycles.remove(cycle)
        self.experiments = [e for e in self.experiments if id(e) not in exps_to_drop and e.cycles]
        self._refresh_tree()
        self._refresh_overlay()
        self._set_status(
            f"Removed {len(exps_to_drop)} experiment(s), {len(cycles_to_drop)} cycle(s)."
        )

    def toggle_visibility(self):
        refs = self._selected_refs()
        if not refs:
            return
        for ref in refs:
            if ref[0] == "exp":
                exp = ref[1]
                # toggle basado en estado actual: si hay alguno visible, ocultar todo; sino, mostrar todo
                target = not exp.is_visible
                exp.set_visible(target)
            else:
                _, _exp, cycle = ref
                cycle.visible = not cycle.visible
        self._refresh_tree()
        self._refresh_overlay()

    def compute_extrema(self):
        """Calcula extremos (sobre datos filtrados) y tendencia promedio por experimento."""
        mode = self.peak_mode.get()
        pwin = max(1, self.peak_window_var.get() or 1)
        fkind = self.filter_var.get()
        fwin = max(1, self.filter_window_var.get() or 1)
        x_max_target = self._parse_float(self.x_at_max_var.get()) if mode == "at_x" else None
        x_min_target = self._parse_float(self.x_at_min_var.get()) if mode == "at_x" else None

        self.tree_res.delete(*self.tree_res.get_children())
        self._res_ref = {}  # iid de fila renombrable → ref del modelo

        # Picos para markers globales en overlay
        all_max_xy = []
        all_min_xy = []
        # Tendencia por experimento
        trend_idx = []
        trend_mean_max = []
        trend_std_max = []
        trend_mean_min = []
        trend_std_min = []
        trend_names = []

        exp_idx = 0
        for exp in self.experiments:
            vis = exp.visible_cycles
            if not vis:
                continue
            exp_idx += 1
            cycle_max_ys = []
            cycle_min_ys = []
            exp_iid = self.tree_res.insert(
                "",
                ttk.END,
                text=exp.name,
                values=(exp_idx, "experiment", len(vis), "", "", ""),
                open=False,
            )
            self._res_ref[exp_iid] = ("exp", exp)
            for c in vis:
                ys_f = _apply_filter(c.ys, fkind, fwin) if fkind != "none" else c.ys
                c.ys_filtered = ys_f
                if mode == "global":
                    maxs, mins = _global_extrema(c.xs, ys_f)
                elif mode == "local":
                    maxs, mins = _local_extrema(c.xs, ys_f, window=pwin)
                else:  # at_x
                    maxs, mins = _at_x_extrema(c.xs, ys_f, x_max_target, x_min_target)
                c.max_points = maxs
                c.min_points = mins
                for x, y in maxs:
                    all_max_xy.append((x, y))
                    cycle_max_ys.append(y)
                    riid = self.tree_res.insert(
                        exp_iid,
                        ttk.END,
                        text=c.name,
                        values=(exp_idx, "max", "", f"{x:.6g}", f"{y:.6g}", ""),
                    )
                    self._res_ref[riid] = ("cycle", exp, c)
                for x, y in mins:
                    all_min_xy.append((x, y))
                    cycle_min_ys.append(y)
                    riid = self.tree_res.insert(
                        exp_iid,
                        ttk.END,
                        text=c.name,
                        values=(exp_idx, "min", "", f"{x:.6g}", f"{y:.6g}", ""),
                    )
                    self._res_ref[riid] = ("cycle", exp, c)
            # Aggregate del experimento
            if cycle_max_ys:
                mean_mx = float(np.mean(cycle_max_ys))
                std_mx = float(np.std(cycle_max_ys, ddof=0))
                trend_idx.append(exp_idx)
                trend_mean_max.append(mean_mx)
                trend_std_max.append(std_mx)
                self.tree_res.insert(
                    exp_iid,
                    ttk.END,
                    text="⟨max⟩",
                    values=(
                        exp_idx,
                        "mean_max",
                        len(cycle_max_ys),
                        "",
                        f"{mean_mx:.6g}",
                        f"{std_mx:.6g}",
                    ),
                )
            if cycle_min_ys:
                mean_mn = float(np.mean(cycle_min_ys))
                std_mn = float(np.std(cycle_min_ys, ddof=0))
                # idx ya añadido si max existió; añade aquí solo si no había max
                if not cycle_max_ys:
                    trend_idx.append(exp_idx)
                    trend_mean_max.append(np.nan)
                    trend_std_max.append(0.0)
                trend_mean_min.append(mean_mn)
                trend_std_min.append(std_mn)
                trend_names.append(exp.name)
                self.tree_res.insert(
                    exp_iid,
                    ttk.END,
                    text="⟨min⟩",
                    values=(
                        exp_idx,
                        "mean_min",
                        len(cycle_min_ys),
                        "",
                        f"{mean_mn:.6g}",
                        f"{std_mn:.6g}",
                    ),
                )
            else:
                # mantiene paralelismo si max existía pero min no
                if cycle_max_ys:
                    trend_mean_min.append(np.nan)
                    trend_std_min.append(0.0)
                    trend_names.append(exp.name)

        # La tabla ya quedó llena (no depende de la vista). Se guarda lo dibujable y se
        # redibuja; _draw_computed pinta markers, guías y tendencias en los ejes que haya.
        self._computed = {
            "filter": fkind,
            "filter_window": fwin,
            "x_max_target": x_max_target,
            "x_min_target": x_min_target,
            "max_xy": all_max_xy,
            "min_xy": all_min_xy,
            "trend_idx": trend_idx,
            "mean_max": trend_mean_max,
            "std_max": trend_std_max,
            "mean_min": trend_mean_min,
            "std_min": trend_std_min,
        }
        self._redraw()
        self._set_status(
            f"Computed {mode} on {exp_idx} experiment(s) — filter={fkind}"
            + (f" (w={fwin})" if fkind != "none" else "")
        )

    def export_results(self):
        """Exporta UN libro: hoja `results` (la tabla de resultados) y hoja `curves`
        (las curvas filtradas, reimportables)."""
        rows = []
        for exp_iid in self.tree_res.get_children():
            exp_name = self.tree_res.item(exp_iid, "text")
            exp_vals = self.tree_res.item(exp_iid, "values")
            rows.append([exp_name, None, *map(num_or_text, exp_vals)])
            for ch_iid in self.tree_res.get_children(exp_iid):
                ch_name = self.tree_res.item(ch_iid, "text")
                ch_vals = self.tree_res.item(ch_iid, "values")
                rows.append([exp_name, ch_name, *map(num_or_text, ch_vals)])
        if not rows:
            self._set_status("No results to export. Run Compute first.")
            return
        path = asksaveasfilename(
            title="Export results",
            defaultextension=".xlsx",
            initialfile=f"analysis_{time.strftime('%Y%m%d_%H%M')}.xlsx",
            filetypes=XLSX_FILETYPES,
        )
        if not path:
            return
        path = xlsx_path(path)
        fkind = self.filter_var.get()
        fwin = max(1, self.filter_window_var.get() or 1)
        curves: list[list] = [
            [
                "experiment",
                "cycle",
                "point_idx",
                "x",
                "y_raw",
                "y_filtered",
                "filter",
                "filter_window",
            ]
        ]
        for exp in self.experiments:
            vis = exp.visible_cycles
            if not vis:
                continue
            for c in vis:
                ys_f = c.ys_filtered
                if ys_f is None or len(ys_f) != len(c.ys):
                    ys_f = _apply_filter(c.ys, fkind, fwin) if fkind != "none" else c.ys
                for i in range(len(c.xs)):
                    curves.append(
                        [
                            exp.name,
                            c.name,
                            i,
                            c.xs[i],
                            c.ys[i],
                            ys_f[i],
                            fkind,
                            fwin if fkind != "none" else None,
                        ]
                    )
        try:
            write_workbook(
                path,
                {
                    "results": [["experiment", "cycle", "exp_idx", "type", "n", "x", "y", "std"]]
                    + rows,
                    "curves": curves,
                },
            )
        except Exception as e:
            self._set_status(f"Export error: {e}")
            return
        self._set_status(
            f"Exported {len(rows)} result row(s) and {len(curves) - 1} curve point(s) "
            f"→ {os.path.basename(path)}."
        )

    def toggle_legend(self):
        self._legend_visible = not self._legend_visible
        # Solo los ejes que la vista actual construyó (el resto es None).
        for ax in (self.ax_overlay, self.ax_min, self.ax_max):
            if ax is None:
                continue
            leg = ax.get_legend()
            if leg is not None:
                leg.set_visible(self._legend_visible)
        self.btn_legend.configure(
            text="Legend ON" if self._legend_visible else "Legend OFF",
            bootstyle="secondary" if self._legend_visible else "secondary-outline",
        )
        self.canvas.draw_idle()

    def clear_all(self):
        """Resetea el estado completo de la pestaña."""
        self.experiments.clear()
        self._tree_ref.clear()
        self._res_ref.clear()
        self._computed = None
        self.tree_curves.delete(*self.tree_curves.get_children())
        self.tree_res.delete(*self.tree_res.get_children())
        # Recrea el canvas limpio (los títulos/labels por defecto los pone
        # _create_plot_canvas).
        self._reset_plot_canvas()
        self.canvas.draw_idle()
        self._set_status("Cleared.")

    def import_analysis(self):
        """Importa la hoja `curves` de un export_results."""
        path = askopenfilename(
            title="Select analysis export",
            filetypes=XLSX_FILETYPES,
        )
        if not path:
            return
        try:
            rows = read_sheet_text(path, "curves") or []
            header = [h.strip() for h in (rows[0] if rows else [])]
            if "y_raw" not in header:
                self._set_status("Not an analysis export (missing 'curves' sheet).")
                return
            col = {name: i for i, name in enumerate(header)}
            # group rows by experiment → cycle (preserves insertion order)
            groups = {}
            for row in rows[1:]:
                if len(row) <= max(col["x"], col["y_raw"]):
                    continue
                try:
                    exp_name = row[col["experiment"]].strip()
                    cycle_name = row[col["cycle"]].strip()
                    x = float(row[col["x"]])
                    y = float(row[col["y_raw"]])
                except (ValueError, IndexError):
                    continue
                groups.setdefault(exp_name, {}).setdefault(cycle_name, ([], []))
                groups[exp_name][cycle_name][0].append(x)
                groups[exp_name][cycle_name][1].append(y)
        except Exception as e:
            self._set_status(f"Import error: {e}")
            return

        if not groups:
            self._set_status("No data parsed from file.")
            return

        existing_names = {e.name for e in self.experiments}
        added = 0
        for exp_name, cycles in groups.items():
            # avoid duplicate names
            name = exp_name
            suffix = 1
            while name in existing_names:
                name = f"{exp_name}_{suffix}"
                suffix += 1
            existing_names.add(name)
            exp = Experiment(name=name)
            for cycle_name, (xs, ys) in cycles.items():
                exp.cycles.append(CycleCurve(name=cycle_name, xs=xs, ys=ys))
            self.experiments.append(exp)
            added += 1

        self._refresh_tree()
        self._refresh_overlay()
        self._set_status(f"Imported {added} experiment(s) from {os.path.basename(path)}.")


__author__ = "Edisson A. Naula"
__date__ = "2026-07-03"
