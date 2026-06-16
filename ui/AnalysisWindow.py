# -*- coding: utf-8 -*-
import csv
import os
import re
import time
import warnings
from tkinter.filedialog import askopenfilename, asksaveasfilename

import matplotlib

matplotlib.use("TkAgg")

import matplotlib.pyplot as plt
import numpy as np
import ttkbootstrap as ttk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure


# ---------------------------------------------------------------------------
# Modelo de datos (picos CV/SWV)
# ---------------------------------------------------------------------------
class CycleCurve:
    """Un ciclo dentro de un experimento."""

    def __init__(self, name, xs, ys):
        self.name = name
        self.xs = np.asarray(xs, dtype=float)
        self.ys = np.asarray(ys, dtype=float)
        self.visible = True
        # cache de filtrado y picos, recalculados por compute_extrema
        self.ys_filtered = None
        self.max_points = []  # lista de (x, y)
        self.min_points = []  # lista de (x, y)


class Experiment:
    """Un archivo CSV = un experimento con N ciclos."""

    def __init__(self, name):
        self.name = name
        self.cycles = []  # list[CycleCurve]

    @property
    def visible_cycles(self):
        return [c for c in self.cycles if c.visible]

    @property
    def is_visible(self):
        return any(c.visible for c in self.cycles)

    def set_visible(self, flag):
        for c in self.cycles:
            c.visible = bool(flag)


# ---------------------------------------------------------------------------
# Filtros y picos
# ---------------------------------------------------------------------------
_LBL_RE = re.compile(r"^(.+)-c(\d+)$")


def _parse_imported_label(label):
    """Convierte 'file-c3' → ('file', 3); si no matchea, ('label', 0)."""
    m = _LBL_RE.match(str(label))
    if m:
        return m.group(1), int(m.group(2))
    return str(label), 0


def _apply_filter(ys, kind, window):
    """Pre-procesamiento opcional. Solo numpy."""
    ys = np.asarray(ys, dtype=float)
    n = ys.size
    if n == 0 or kind == "none" or window <= 1:
        return ys
    w = min(window, n)
    if kind == "moving_avg":
        kernel = np.ones(w, dtype=float) / w
        # 'same' produce el mismo tamaño; bordes ligeramente sesgados, aceptable
        return np.convolve(ys, kernel, mode="same")
    if kind == "median":
        half = w // 2
        out = np.empty(n, dtype=float)
        for i in range(n):
            lo = max(0, i - half)
            hi = min(n, i + half + 1)
            out[i] = np.median(ys[lo:hi])
        return out
    return ys


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

        self._build_ui()
        # Solo CV/SWV alimentan la tabla de picos desde las líneas cargadas del
        # plotter; un plotter EIS deja esta pestaña vacía (su tab se siembra aparte).
        if plotter is not None and getattr(plotter, "method", "") != "eis":
            self._snapshot_from_plotter(plotter)
            self._refresh_tree()
            self._refresh_overlay()

    # ---------------------------------------------------------------------
    # UI
    # ---------------------------------------------------------------------
    def _build_ui(self):
        # --- Toolbar fila 1: acciones ---
        toolbar = ttk.Frame(self)
        toolbar.pack(side=ttk.TOP, fill=ttk.X, padx=6, pady=(6, 2))

        ttk.Button(toolbar, text="📂 Load CSV", bootstyle="secondary", command=self.load_csv).pack(
            side=ttk.LEFT, padx=3
        )
        ttk.Button(
            toolbar, text="📥 Import", bootstyle="secondary", command=self.import_analysis
        ).pack(side=ttk.LEFT, padx=3)
        ttk.Button(
            toolbar, text="💾 Export", bootstyle="secondary", command=self.export_results
        ).pack(side=ttk.LEFT, padx=3)
        ttk.Separator(toolbar, orient=ttk.VERTICAL).pack(side=ttk.LEFT, fill=ttk.Y, padx=6)

        ttk.Button(toolbar, text="🗑 Remove", bootstyle="danger", command=self.remove_selected).pack(
            side=ttk.LEFT, padx=3
        )
        ttk.Button(
            toolbar, text="👁 Show/Hide", bootstyle="info", command=self.toggle_visibility
        ).pack(side=ttk.LEFT, padx=3)
        ttk.Button(
            toolbar, text="📊 Compute", bootstyle="success", command=self.compute_extrema
        ).pack(side=ttk.LEFT, padx=3)
        self._legend_visible = True
        self.btn_legend = ttk.Button(
            toolbar, text="Legend ON", bootstyle="secondary", command=self.toggle_legend
        )
        self.btn_legend.pack(side=ttk.RIGHT, padx=3)
        ttk.Button(
            toolbar, text="Clear all", bootstyle="danger-outline", command=self.clear_all
        ).pack(side=ttk.RIGHT, padx=3)

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

        # Status bar anclado al fondo antes de que el área de scroll ocupe el centro
        self.lbl_status = ttk.Label(self, text="Ready.", anchor="w")
        self.lbl_status.pack(side=ttk.BOTTOM, fill=ttk.X, padx=6, pady=(0, 4))

        # --- Frame padre con scroll vertical que envuelve árbol + gráficas + resultados ---
        _wrap = ttk.Frame(self)
        _wrap.pack(fill=ttk.BOTH, expand=True, padx=6, pady=(0, 4))

        _vsb_main = ttk.Scrollbar(_wrap, orient="vertical")
        _vsb_main.pack(side=ttk.RIGHT, fill=ttk.Y)

        self._main_sc = ttk.Canvas(_wrap, bd=0, highlightthickness=0, yscrollcommand=_vsb_main.set)
        self._main_sc.pack(side=ttk.LEFT, fill=ttk.BOTH, expand=True)
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
        self.tree_curves.column("#0", width=240, anchor="w")
        self.tree_curves.column("info", width=90, anchor="w")
        vsb_c = ttk.Scrollbar(left, orient="vertical", command=self.tree_curves.yview)
        self.tree_curves.configure(yscrollcommand=vsb_c.set)
        self.tree_curves.pack(side=ttk.LEFT, fill=ttk.BOTH, expand=True, padx=4, pady=4)
        vsb_c.pack(side=ttk.LEFT, fill=ttk.Y)
        # Doble clic sobre un nombre → editarlo in-place; al confirmar se renombra el
        # experimento/ciclo y, con ello, su etiqueta de leyenda en el overlay.
        self.tree_curves.bind("<Double-1>", self._begin_rename)
        self._rename_entry: "ttk.Entry | None" = None  # Entry overlay activo (None = ninguno)

        # Right: figura con 3 ejes
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
    def _create_plot_canvas(self):
        self.fig = Figure(figsize=(8, 6), dpi=100, layout="constrained")
        gs = self.fig.add_gridspec(2, 2)
        self.ax_overlay = self.fig.add_subplot(gs[0, :])
        self.ax_min = self.fig.add_subplot(gs[1, 0])
        self.ax_max = self.fig.add_subplot(gs[1, 1])
        self.ax_overlay.set_title("Curves overlay")
        self.ax_min.set_title("Min trend (mean ± std)")
        self.ax_max.set_title("Max trend (mean ± std)")
        self.ax_min.set_xlabel("Experiment index")
        self.ax_max.set_xlabel("Experiment index")
        self.canvas = FigureCanvasTkAgg(self.fig, self._plot_host)
        self.canvas.get_tk_widget().pack(fill=ttk.BOTH, expand=True)
        self.toolbar_mpl = NavigationToolbar2Tk(self.canvas, self._plot_host, pack_toolbar=False)
        self.toolbar_mpl.pack(fill=ttk.X)
        self.canvas.mpl_connect("motion_notify_event", self._on_hover)

    def _reset_plot_canvas(self):
        # Destruye canvas+toolbar y los recrea desde cero (mismo patrón que
        # EISAnalysisFrame): evita estado residual de constrained_layout en el canvas
        # Tk vivo. Un pick mode activo queda invalidado: su cid apuntaba al canvas viejo.
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
        """Snapshot de loaded_lines del EventPlotter, agrupando por filename."""
        groups = {}  # filename → list[(cycle_num, xs, ys, raw_label)]
        for line in getattr(plotter, "loaded_lines", []):
            try:
                xs = np.asarray(line.get_xdata(), dtype=float)
                ys = np.asarray(line.get_ydata(), dtype=float)
            except Exception:
                continue
            if xs.size == 0:
                continue
            base, cyc = _parse_imported_label(line.get_label())
            groups.setdefault(base, []).append((cyc, xs, ys, line.get_label()))
        for base, items in groups.items():
            exp = Experiment(name=base)
            items.sort(key=lambda t: t[0])
            for cyc, xs, ys, raw in items:
                exp.cycles.append(CycleCurve(name=f"c{cyc}" if cyc else raw, xs=xs, ys=ys))
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
        entry.place(x=x, y=y, width=w, height=h)
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
        """Redibuja overlay: muestra filtrado si filtro activo, sino raw.

        Recrea el canvas (no ax.clear()): las tendencias (ax_min/ax_max) quedan en
        blanco hasta el siguiente Compute, que es lo correcto porque dependen del
        filtro/datos que pudieron cambiar. compute_extrema redibuja todo tras esto."""
        kind = self.filter_var.get()
        fw = max(1, self.filter_window_var.get() or 1)
        self._reset_plot_canvas()
        self.ax_overlay.set_title(
            "Curves overlay" + (f" (filtered: {kind})" if kind != "none" else "")
        )
        any_visible = False
        for exp in self.experiments:
            for c in exp.cycles:
                if not c.visible:
                    continue
                ys_disp = _apply_filter(c.ys, kind, fw) if kind != "none" else c.ys
                self.ax_overlay.plot(
                    c.xs,
                    ys_disp,
                    linewidth=1.2,
                    marker=".",
                    markersize=2,
                    label=f"{exp.name}/{c.name}",
                )
                any_visible = True
        if any_visible:
            leg = self.ax_overlay.legend(loc="best", fontsize=7, ncol=2)
            leg.set_visible(self._legend_visible)
        self.canvas.draw_idle()

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

    def _toggle_pick_mode(self, kind):
        """Activa la captura de un siguiente clic en la gráfica overlay para
        rellenar X@max o X@min. Un segundo click sobre el mismo botón cancela."""
        # cancelar si ya estaba activo
        cid = self._pick_cid
        if cid is not None:
            try:
                self.canvas.mpl_disconnect(cid)
            except Exception:
                pass
            prev = self._pick_kind
            self._pick_cid = None
            self._pick_kind = None
            if prev == kind:
                self._set_status("Pick mode cancelled.")
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
        if event.inaxes is not self.ax_overlay or event.xdata is None:
            return
        x = float(event.xdata)
        if self._pick_kind == "max":
            self.x_at_max_var.set(f"{x:.6g}")
        elif self._pick_kind == "min":
            self.x_at_min_var.set(f"{x:.6g}")
        cid = self._pick_cid
        if cid is not None:
            try:
                self.canvas.mpl_disconnect(cid)
            except Exception:
                pass
        kind = self._pick_kind
        self._pick_cid = None
        self._pick_kind = None
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
        if event.inaxes is not self.ax_overlay or event.x is None:
            self.lbl_cross.configure(text="")
            return
        best: tuple | None = None  # (dist_px, label, x, y)
        for line in self.ax_overlay.get_lines():
            label = str(line.get_label())
            if not label or label.startswith("_") or not line.get_visible():
                continue
            xd = np.asarray(line.get_xdata(), dtype=float)
            yd = np.asarray(line.get_ydata(), dtype=float)
            if xd.size == 0:
                continue
            try:
                pts = self.ax_overlay.transData.transform(np.column_stack([xd, yd]))
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
    def load_csv(self):
        """Carga un CSV (un experimento) — crea un Experiment con N ciclos."""
        path = askopenfilename(
            title="Select CSV (one experiment)",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not path:
            return
        cycles_x = {}
        cycles_y = {}
        try:
            with open(path, newline="") as f:
                reader = csv.reader(f, skipinitialspace=True)
                next(reader, None)
                for row in reader:
                    if len(row) < 4:
                        continue
                    try:
                        x = float(row[1])
                        y = float(row[2])
                        cycle = int(float(row[3]))
                    except (ValueError, TypeError):
                        continue
                    cycles_x.setdefault(cycle, []).append(x)
                    cycles_y.setdefault(cycle, []).append(y)
        except Exception as e:
            self._set_status(f"Error loading data: {e}")
            return
        if not cycles_x:
            self._set_status("No data parsed from file.")
            return
        exp_name = os.path.splitext(os.path.basename(path))[0]
        exp = Experiment(name=exp_name)
        for cyc in sorted(cycles_x.keys()):
            exp.cycles.append(CycleCurve(name=f"c{cyc}", xs=cycles_x[cyc], ys=cycles_y[cyc]))
        self.experiments.append(exp)
        self._refresh_tree()
        self._refresh_overlay()
        self._set_status(f"Loaded experiment '{exp_name}' with {len(exp.cycles)} cycle(s).")

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

        # Reset overlay (re-aplica filtro visual también)
        self._refresh_overlay()
        self.tree_res.delete(*self.tree_res.get_children())
        self._res_ref = {}  # iid de fila renombrable → ref del modelo

        # Líneas verticales guía en overlay para modo "At X"
        if mode == "at_x":
            if x_max_target is not None:
                self.ax_overlay.axvline(
                    x_max_target, color="tab:red", linestyle="--", linewidth=1, alpha=0.6
                )
            if x_min_target is not None:
                self.ax_overlay.axvline(
                    x_min_target, color="tab:blue", linestyle="--", linewidth=1, alpha=0.6
                )

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

        # Marcadores de picos sobre overlay
        if all_max_xy:
            xs, ys = zip(*all_max_xy)
            self.ax_overlay.scatter(xs, ys, marker="^", s=40, color="tab:red", zorder=5)
        if all_min_xy:
            xs, ys = zip(*all_min_xy)
            self.ax_overlay.scatter(xs, ys, marker="v", s=40, color="tab:blue", zorder=5)

        # Trends con errorbar
        self.ax_min.clear()
        self.ax_max.clear()
        self.ax_min.set_title(f"Min trend ({mode}) \n— mean ± std")
        self.ax_max.set_title(f"Max trend ({mode}) \n— mean ± std")
        self.ax_min.set_xlabel("Experiment")
        self.ax_max.set_xlabel("Experiment")
        if trend_idx:
            self.ax_max.errorbar(
                trend_idx,
                trend_mean_max,
                yerr=trend_std_max,
                marker="o",
                linestyle="-",
                color="tab:red",
                capsize=4,
            )
            self.ax_min.errorbar(
                trend_idx,
                trend_mean_min,
                yerr=trend_std_min,
                marker="o",
                linestyle="-",
                color="tab:blue",
                capsize=4,
            )
            # ticks como índices enteros
            self.ax_max.set_xticks(trend_idx)
            self.ax_min.set_xticks(trend_idx)

        self.canvas.draw_idle()
        self._set_status(
            f"Computed {mode} on {exp_idx} experiment(s) — filter={fkind}"
            + (f" (w={fwin})" if fkind != "none" else "")
        )

    def export_results(self):
        """Exporta la tabla de resultados y, en archivo aparte, las curvas filtradas."""
        rows = []
        for exp_iid in self.tree_res.get_children():
            exp_name = self.tree_res.item(exp_iid, "text")
            exp_vals = self.tree_res.item(exp_iid, "values")
            rows.append((exp_name, "", *exp_vals))
            for ch_iid in self.tree_res.get_children(exp_iid):
                ch_name = self.tree_res.item(ch_iid, "text")
                ch_vals = self.tree_res.item(ch_iid, "values")
                rows.append((exp_name, ch_name, *ch_vals))
        if not rows:
            self._set_status("No results to export. Run Compute first.")
            return
        path = asksaveasfilename(
            title="Export results",
            defaultextension=".csv",
            initialfile=f"analysis_{time.strftime('%Y%m%d_%H%M')}.csv",
            filetypes=[("CSV files", "*.csv")],
        )
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["experiment", "cycle", "exp_idx", "type", "n", "x", "y", "std"])
                w.writerows(rows)
        except Exception as e:
            self._set_status(f"Export error: {e}")
            return

        # Curvas filtradas en archivo paralelo "<path>_curves.csv"
        base, ext = os.path.splitext(path)
        curves_path = f"{base}_curves{ext or '.csv'}"
        fkind = self.filter_var.get()
        fwin = max(1, self.filter_window_var.get() or 1)
        n_pts = 0
        try:
            with open(curves_path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(
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
                )
                exp_idx = 0
                for exp in self.experiments:
                    vis = exp.visible_cycles
                    if not vis:
                        continue
                    exp_idx += 1
                    for c in vis:
                        ys_f = c.ys_filtered
                        if ys_f is None or len(ys_f) != len(c.ys):
                            ys_f = _apply_filter(c.ys, fkind, fwin) if fkind != "none" else c.ys
                        for i in range(len(c.xs)):
                            w.writerow(
                                [
                                    exp.name,
                                    c.name,
                                    i,
                                    f"{c.xs[i]:.9g}",
                                    f"{c.ys[i]:.9g}",
                                    f"{ys_f[i]:.9g}",
                                    fkind,
                                    fwin if fkind != "none" else "",
                                ]
                            )
                            n_pts += 1
        except Exception as e:
            self._set_status(f"Results exported, but error writing curves file: {e}")
            return
        self._set_status(
            f"Exported {len(rows)} result row(s) → {os.path.basename(path)}; "
            f"{n_pts} curve point(s) → {os.path.basename(curves_path)}."
        )

    def toggle_legend(self):
        self._legend_visible = not self._legend_visible
        for ax in (self.ax_overlay, self.ax_min, self.ax_max):
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
        self.tree_curves.delete(*self.tree_curves.get_children())
        self.tree_res.delete(*self.tree_res.get_children())
        # Recrea el canvas limpio (los títulos/labels por defecto los pone
        # _create_plot_canvas).
        self._reset_plot_canvas()
        self.canvas.draw_idle()
        self._set_status("Cleared.")

    def import_analysis(self):
        """Importa un archivo _curves.csv generado por export_results."""
        path = askopenfilename(
            title="Select curves CSV (analysis export)",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, newline="", encoding="utf-8") as f:
                reader = csv.reader(f, skipinitialspace=True)
                header = [h.strip() for h in (next(reader, None) or [])]
                if "y_raw" not in header:
                    self._set_status(
                        "Not a curves file. Export produces two files — select the one ending in _curves.csv."
                    )
                    return
                col = {name: i for i, name in enumerate(header)}
                # group rows by experiment → cycle (preserves insertion order)
                groups = {}
                for row in reader:
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


# ---------------------------------------------------------------------------
# Modelo de datos (EIS)
# ---------------------------------------------------------------------------
# Columnas canónicas que el cargador/siembra entienden (por NOMBRE de header,
# no por posición — el CSV de EIS guarda x_key/y_key + extras con estos nombres).
EIS_KEYS = ("freq_Hz", "Z_real", "Z_imag", "Z_mod", "E_V", "t_s")


class EISSpectrum:
    """Un espectro EIS (un 'cycle'): arrays nombrados por magnitud.

    `data` mapea nombre→np.array. Deriva `Z_mod` (=|Z|) y `phase_deg`
    (=atan2(Z_imag, Z_real)) cuando hay Z_real/Z_imag. Z_imag llega ya negado
    desde el parser (convención Nyquist), así que la fase sale con el signo de
    PSTrace (positiva en zona capacitiva)."""

    def __init__(self, name, data):
        self.name = name
        self.data = {k: np.asarray(v, dtype=float) for k, v in data.items() if len(v)}
        self.visible = True
        # Mediciones Nyquist por espectro (picking manual):
        #   Rs, rct_edge, Rct, warb (lista de hasta 2 puntos), warb_len, warb_angle
        self.meas = {}
        self._derive()

    def _derive(self):
        zr = self.data.get("Z_real")
        zi = self.data.get("Z_imag")
        if zr is not None and zi is not None and zr.size and zr.size == zi.size:
            if "Z_mod" not in self.data:
                self.data["Z_mod"] = np.sqrt(zr**2 + zi**2)
            self.data["phase_deg"] = np.degrees(np.arctan2(zi, zr))

    def has(self, *keys):
        return all(k in self.data and self.data[k].size for k in keys)

    def distinct_freqs(self):
        f = self.data.get("freq_Hz")
        if f is None or f.size == 0:
            return 0
        return len(np.unique(np.round(f, 6)))


class EISExperiment:
    """Un archivo/corrida EIS = N espectros."""

    def __init__(self, name):
        self.name = name
        self.spectra = []  # list[EISSpectrum]

    @property
    def visible_spectra(self):
        return [s for s in self.spectra if s.visible]


# ---------------------------------------------------------------------------
# Pestaña: análisis EIS (Nyquist · Bode · |Z| vs E · |Z| vs t)
# ---------------------------------------------------------------------------
class EISAnalysisFrame(ttk.Frame):
    """Pestaña de análisis EIS: carga CSV (o siembra desde la corrida en memoria),
    elige qué gráficos mostrar (checkboxes + grid dinámico) y mide parámetros del
    Nyquist (Rs, Rct, Warburg) por picking manual sobre el espectro seleccionado."""

    # (clave interna, etiqueta) en orden de presentación.
    PLOTS = (
        ("nyquist", "Nyquist"),
        ("bode", "Bode"),
        ("z_e", "|Z| vs E"),
        ("z_t", "|Z| vs t"),
    )

    def __init__(self, master, owner, plotter=None, **kwargs):
        super().__init__(master, **kwargs)
        self.owner = owner
        self.experiments = []  # list[EISExperiment]
        self._tree_ref = {}  # iid → ("exp", exp) | ("spec", exp, spectrum)
        self._style_cycle = self._build_style_cycle()
        # Estado de picking manual sobre el Nyquist.
        self._pick_kind: str | None = None  # 'rs' | 'rct' | 'warb' | None
        # Ejes activos del grid (se fijan en _refresh_plots para los handlers).
        self._nyquist_ax = None
        self._bode_zax = None  # eje |Z| del Bode (para el crosshair)

        self._build_ui()
        # Siembra desde la corrida EIS en memoria (datos ricos: freq+Z completos).
        if plotter is not None and getattr(plotter, "method", "") == "eis":
            self._seed_from_total_data(getattr(plotter, "total_data", []))

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self):
        # --- Toolbar fila 1: acciones ---
        toolbar = ttk.Frame(self)
        toolbar.pack(side=ttk.TOP, fill=ttk.X, padx=6, pady=(6, 2))
        ttk.Button(toolbar, text="📂 Load CSV", bootstyle="secondary", command=self.load_csv).pack(
            side=ttk.LEFT, padx=3
        )
        ttk.Button(
            toolbar, text="💾 Export", bootstyle="secondary", command=self.export_results
        ).pack(side=ttk.LEFT, padx=3)
        ttk.Separator(toolbar, orient=ttk.VERTICAL).pack(side=ttk.LEFT, fill=ttk.Y, padx=6)
        ttk.Button(
            toolbar, text="🗑 Remove", bootstyle="danger", command=self.remove_selected
        ).pack(side=ttk.LEFT, padx=3)
        ttk.Button(
            toolbar, text="👁 Show/Hide", bootstyle="info", command=self.toggle_visibility
        ).pack(side=ttk.LEFT, padx=3)
        ttk.Button(
            toolbar, text="Clear all", bootstyle="danger-outline", command=self.clear_all
        ).pack(side=ttk.RIGHT, padx=3)

        # --- Toolbar fila 2: checkboxes de qué plots mostrar (deshabilitados si los
        # datos cargados no tienen las columnas que cada uno necesita) ---
        toolbar2 = ttk.Frame(self)
        toolbar2.pack(side=ttk.TOP, fill=ttk.X, padx=6, pady=(0, 4))
        ttk.Label(toolbar2, text="Plots:").pack(side=ttk.LEFT, padx=(0, 6))
        self.plot_vars = {}
        self.plot_checks = {}
        for key, label in self.PLOTS:
            var = ttk.BooleanVar(value=(key in ("nyquist", "bode")))
            chk = ttk.Checkbutton(
                toolbar2,
                text=label,
                variable=var,
                command=self._refresh_plots,
                state=ttk.DISABLED,
                style="Custom.TCheckbutton",
            )
            chk.pack(side=ttk.LEFT, padx=4)
            self.plot_vars[key] = var
            self.plot_checks[key] = chk

        # --- Toolbar fila 3: medición Nyquist (picking manual) ---
        toolbar3 = ttk.Frame(self)
        toolbar3.pack(side=ttk.TOP, fill=ttk.X, padx=6, pady=(0, 4))
        ttk.Label(toolbar3, text="Nyquist measure →").pack(side=ttk.LEFT, padx=(0, 6))
        self.btn_rs = ttk.Button(
            toolbar3,
            text="Pick Rs",
            bootstyle="secondary-outline",
            command=lambda: self._arm_pick("rs"),
        )
        self.btn_rs.pack(side=ttk.LEFT, padx=3)
        self.btn_rct = ttk.Button(
            toolbar3,
            text="Pick Rct edge",
            bootstyle="secondary-outline",
            command=lambda: self._arm_pick("rct"),
        )
        self.btn_rct.pack(side=ttk.LEFT, padx=3)
        self.btn_warb = ttk.Button(
            toolbar3,
            text="Pick Warburg (2)",
            bootstyle="secondary-outline",
            command=lambda: self._arm_pick("warb"),
        )
        self.btn_warb.pack(side=ttk.LEFT, padx=3)
        ttk.Button(
            toolbar3,
            text="Clear measure",
            bootstyle="warning-outline",
            command=self._clear_measure,
        ).pack(side=ttk.LEFT, padx=(8, 3))
        # Lectura crosshair del Bode (freq, |Z|, fase).
        self.lbl_cross = ttk.Label(toolbar3, text="", anchor="e")
        self.lbl_cross.pack(side=ttk.RIGHT, padx=6)

        # Status bar (fijo abajo, fuera del scroll)
        self.lbl_status = ttk.Label(self, text="Ready.", anchor="w")
        self.lbl_status.pack(side=ttk.BOTTOM, fill=ttk.X, padx=6, pady=(0, 4))

        # --- Área scrollable (árbol + figura + resultados), igual que la pestaña Peaks ---
        _wrap = ttk.Frame(self)
        _wrap.pack(fill=ttk.BOTH, expand=True, padx=6, pady=(0, 4))
        _vsb_main = ttk.Scrollbar(_wrap, orient="vertical")
        _vsb_main.pack(side=ttk.RIGHT, fill=ttk.Y)
        self._main_sc = ttk.Canvas(_wrap, bd=0, highlightthickness=0, yscrollcommand=_vsb_main.set)
        self._main_sc.pack(side=ttk.LEFT, fill=ttk.BOTH, expand=True)
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

        # --- Split árbol | figura (dentro del frame interior scrollable) ---
        main = ttk.PanedWindow(inner, orient=ttk.HORIZONTAL)
        main.pack(fill=ttk.X, padx=0, pady=(0, 6))

        left = ttk.LabelFrame(main, text="Experiments → Spectra (double-click to rename)")
        main.add(left, weight=1)
        self.tree = ttk.Treeview(
            left, columns=("info",), show="tree headings", selectmode="browse"
        )
        self.tree.bind("<Double-1>", self._on_tree_double_click)
        self.tree.heading("#0", text="Item")
        self.tree.heading("info", text="State")
        self.tree.column("#0", width=220, anchor="w")
        self.tree.column("info", width=60, anchor="w")
        vsb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=ttk.LEFT, fill=ttk.BOTH, expand=True, padx=4, pady=4)
        vsb.pack(side=ttk.LEFT, fill=ttk.Y)

        right = ttk.Frame(main)
        main.add(right, weight=4)
        right.bind("<MouseWheel>", _on_wheel)
        plt.style.use("seaborn-v0_8-darkgrid")
        # Host de la figura; el canvas se (re)crea en _create_plot_canvas para poder
        # reconstruirlo limpio en cada refresh (ver _reset_plot_canvas).
        self._plot_host = right
        self._create_plot_canvas()

        # --- Tabla de resultados (Nyquist), dentro del frame interior scrollable ---
        bottom = ttk.LabelFrame(inner, text="EIS results (Nyquist)")
        bottom.pack(fill=ttk.BOTH, pady=(0, 6))
        cols = ("rs", "rct", "warb", "angle")
        self.tree_res = ttk.Treeview(bottom, columns=cols, show="tree headings", height=6)
        self.tree_res.heading("#0", text="Spectrum")
        self.tree_res.column("#0", width=220, anchor="w")
        heads = {
            "rs": "Rs (Ω)",
            "rct": "Rct (Ω)",
            "warb": "Warburg L (Ω)",
            "angle": "Warburg ∠ (°)",
        }
        for c in cols:
            self.tree_res.heading(c, text=heads[c])
            self.tree_res.column(c, width=130, anchor="w")
        self.tree_res.pack(fill=ttk.X, padx=4, pady=4)

        self._refresh_plots()

    # ------------------------------------------------------------------
    # Carga / siembra
    # ------------------------------------------------------------------
    def load_csv(self):
        """Carga un CSV de EIS guardado por EventEmstatFrame.save_data. Lee por
        NOMBRE de header (Z_real/Z_imag/freq_Hz/Z_mod/E_V/t_s + cycle/run) y agrupa
        por (run, cycle) en espectros."""
        path = askopenfilename(
            title="Select EIS CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, newline="") as f:
                reader = csv.reader(f, skipinitialspace=True)
                header = [h.strip() for h in (next(reader, None) or [])]
                col = {name: i for i, name in enumerate(header)}
                present = [k for k in EIS_KEYS if k in col]
                if "Z_real" not in present and "Z_mod" not in present:
                    self._set_status(
                        "Not an EIS CSV (no Z_real / Z_mod column). Use the EIS data files."
                    )
                    return
                ci = col.get("cycle")
                ri = col.get("run")
                groups = {}  # (run, cycle) → {key: [vals]}
                e_by_group = {}  # (run, cycle) → primer E_V (para etiqueta)
                for row in reader:
                    try:
                        cyc = int(float(row[ci])) if ci is not None and row[ci] != "" else 0
                        run = int(float(row[ri])) if ri is not None and row[ri] != "" else 0
                    except (ValueError, IndexError):
                        cyc, run = 0, 0
                    bucket = groups.setdefault((run, cyc), {k: [] for k in present})
                    ok = True
                    vals = {}
                    for k in present:
                        try:
                            vals[k] = float(row[col[k]])
                        except (ValueError, IndexError):
                            ok = False
                            break
                    if not ok:
                        continue
                    for k in present:
                        bucket[k].append(vals[k])
                    if "E_V" in vals:
                        e_by_group.setdefault((run, cyc), vals["E_V"])
        except Exception as e:
            self._set_status(f"Error loading data: {e}")
            return
        if not groups:
            self._set_status("No data parsed from file.")
            return
        base = os.path.splitext(os.path.basename(path))[0]
        self._add_experiment(base, groups, e_by_group)
        self._set_status(
            f"Loaded '{base}' with {len(groups)} spectrum(s)."
        )

    def _seed_from_total_data(self, total_data):
        """Siembra la pestaña con los eventos de la corrida EIS en memoria
        (total_data): cada evento trae freq_Hz/Z_real/Z_imag/Z_mod/E_V/t_s según el
        modo. Agrupa por (run, cycle) igual que el CSV."""
        if not total_data:
            return
        groups = {}
        e_by_group = {}
        for ev in total_data:
            if not isinstance(ev, dict):
                continue
            run = int(ev.get("run", 1) or 1)
            cyc = int(ev.get("cycle", 0) or 0)
            bucket = groups.setdefault((run, cyc), {})
            for k in EIS_KEYS:
                if k in ev and ev[k] is not None:
                    bucket.setdefault(k, []).append(float(ev[k]))
            if "E_V" in ev and ev["E_V"] is not None:
                e_by_group.setdefault((run, cyc), float(ev["E_V"]))
        if not groups:
            return
        self._add_experiment("current run", groups, e_by_group)
        self._set_status(f"Seeded {len(groups)} spectrum(s) from the current run.")

    def _add_experiment(self, base, groups, e_by_group):
        """Construye un EISExperiment desde grupos (run, cycle)→{key:[vals]}."""
        multi_run = len({r for r, _ in groups}) > 1
        exp = EISExperiment(name=base)
        for (run, cyc) in sorted(groups):
            data = groups[(run, cyc)]
            if not any(len(v) for v in data.values()):
                continue
            e_val = e_by_group.get((run, cyc))
            if e_val is not None:
                name = f"E={e_val:.3g}V"
                if multi_run:
                    name = f"r{run} {name}"
            elif multi_run:
                name = f"r{run}c{cyc}"
            else:
                name = f"c{cyc}"
            exp.spectra.append(EISSpectrum(name=name, data=data))
        if not exp.spectra:
            return
        self.experiments.append(exp)
        self._update_plot_availability()
        self._refresh_tree()
        self._refresh_plots()

    # ------------------------------------------------------------------
    # Árbol / selección
    # ------------------------------------------------------------------
    def _refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        self._tree_ref = {}
        for exp in self.experiments:
            n_vis = sum(1 for s in exp.spectra if s.visible)
            eiid = self.tree.insert(
                "", ttk.END, text=exp.name, values=(f"{n_vis}/{len(exp.spectra)} 👁",), open=True
            )
            self._tree_ref[eiid] = ("exp", exp)
            for sp in exp.spectra:
                mark = "👁" if sp.visible else "🚫"
                siid = self.tree.insert(eiid, ttk.END, text=sp.name, values=(mark,))
                self._tree_ref[siid] = ("spec", exp, sp)

    def _selected_spectrum(self):
        sel = self.tree.selection()
        if not sel:
            return None
        ref = self._tree_ref.get(sel[0])
        if ref and ref[0] == "spec":
            return ref[2]
        return None

    def remove_selected(self):
        sel = self.tree.selection()
        if not sel:
            return
        ref = self._tree_ref.get(sel[0])
        if not ref:
            return
        if ref[0] == "exp":
            self.experiments = [e for e in self.experiments if e is not ref[1]]
        else:
            _, exp, sp = ref
            if sp in exp.spectra:
                exp.spectra.remove(sp)
            self.experiments = [e for e in self.experiments if e.spectra]
        self._update_plot_availability()
        self._refresh_tree()
        self._refresh_plots()
        self._refresh_results_table()

    def toggle_visibility(self):
        sel = self.tree.selection()
        if not sel:
            return
        ref = self._tree_ref.get(sel[0])
        if not ref:
            return
        if ref[0] == "exp":
            target = not any(s.visible for s in ref[1].spectra)
            for s in ref[1].spectra:
                s.visible = target
        else:
            ref[2].visible = not ref[2].visible
        self._refresh_tree()
        self._refresh_plots()

    def _on_tree_double_click(self, event):
        """Edición inline del nombre de un nodo (experimento o espectro): abre un
        Entry sobre la celda #0 precargado con el nombre actual. Enter/foco-fuera
        confirma, Esc cancela, vacío revierte. Devuelve 'break' para no disparar el
        expand/collapse por defecto del Treeview."""
        iid = self.tree.identify_row(event.y)
        if not iid or iid not in self._tree_ref:
            return None
        bbox = self.tree.bbox(iid, "#0")
        if not bbox:
            return None
        ref = self._tree_ref[iid]
        x, y, w, h = bbox
        # Ancho cómodo: extiende el Entry hasta el borde derecho del árbol (solapa la
        # columna 'State') con un mínimo de 240px, para ver el nombre completo al
        # escribir; un poco más alto que la fila.
        w = max(w, self.tree.winfo_width() - x - 4, 290)
        entry = ttk.Entry(self.tree, font=("", 11))
        entry.insert(0, self.tree.item(iid, "text"))
        entry.select_range(0, "end")
        entry.place(x=x, y=y, width=w, height=h + 16)
        entry.focus_set()
        # Guard para que el FocusOut disparado al destruir el Entry (p.ej. tras Esc)
        # no re-aplique el cambio.
        state = {"done": False}

        def finish(apply):
            if state["done"]:
                return
            state["done"] = True
            new = entry.get().strip()
            entry.destroy()
            if apply and new:
                self._apply_rename(ref, new)

        entry.bind("<Return>", lambda _e: finish(True))
        entry.bind("<FocusOut>", lambda _e: finish(True))
        entry.bind("<Escape>", lambda _e: finish(False))
        return "break"

    def _apply_rename(self, ref, new_name):
        """Aplica el nombre nuevo al experimento o espectro y refresca todo lo que lo
        usa (árbol, leyenda del plot, tabla de resultados). Solo en memoria: el Export
        CSV lo conserva, pero recargar el eis_data_*.csv crudo re-deduce el nombre."""
        if ref[0] == "exp":
            ref[1].name = new_name
        else:
            ref[2].name = new_name
        self._refresh_tree()
        self._refresh_plots()
        self._refresh_results_table()
        self._set_status(f"Renamed to '{new_name}'.")

    def clear_all(self):
        self.experiments.clear()
        self._tree_ref.clear()
        self.tree.delete(*self.tree.get_children())
        self.tree_res.delete(*self.tree_res.get_children())
        self._update_plot_availability()
        self._refresh_plots()
        self._set_status("Cleared.")

    # ------------------------------------------------------------------
    # Canvas de la figura (se recrea limpio en cada refresh)
    # ------------------------------------------------------------------
    def _create_plot_canvas(self):
        # Altura adaptativa: se ajusta por nº de filas del grid en _refresh_plots.
        self.fig = Figure(figsize=(8, 4), dpi=100, layout="constrained")
        self.canvas = FigureCanvasTkAgg(self.fig, self._plot_host)
        self.canvas.get_tk_widget().pack(fill=ttk.BOTH, expand=True)
        self.toolbar_mpl = NavigationToolbar2Tk(self.canvas, self._plot_host, pack_toolbar=False)
        self.toolbar_mpl.pack(fill=ttk.X)
        self.canvas.mpl_connect("button_press_event", self._on_pick)
        self.canvas.mpl_connect("motion_notify_event", self._on_motion)

    def _reset_plot_canvas(self):
        # Destruye canvas+toolbar y los recrea desde cero. Reusar la misma Figure con
        # fig.clear() deja, en el canvas Tk vivo, un subplot fantasma (estado residual
        # de constrained_layout + el eje gemelo twinx del Bode) al redibujar tras
        # togglear un checkbox. Recrear el canvas elimina cualquier estado previo.
        try:
            self.toolbar_mpl.destroy()
        except Exception:
            pass
        try:
            self.canvas.get_tk_widget().destroy()
        except Exception:
            pass
        self._create_plot_canvas()

    # ------------------------------------------------------------------
    # Disponibilidad de plots según columnas cargadas
    # ------------------------------------------------------------------
    def _all_spectra(self):
        for exp in self.experiments:
            for sp in exp.spectra:
                yield sp

    def _plot_available(self, key):
        specs = list(self._all_spectra())
        if not specs:
            return False
        if key == "nyquist":
            return any(s.has("Z_real", "Z_imag") for s in specs)
        if key == "bode":
            # Necesita barrido en frecuencia (>1 punto distinto) y Z completos.
            return any(s.has("freq_Hz", "Z_real", "Z_imag") and s.distinct_freqs() > 1 for s in specs)
        if key == "z_e":
            # Modo de frecuencia fija: E_V + |Z| y a lo sumo una frecuencia.
            return any(s.has("E_V", "Z_mod") and s.distinct_freqs() <= 1 for s in specs)
        if key == "z_t":
            return any(s.has("t_s", "Z_mod") for s in specs)
        return False

    def _update_plot_availability(self):
        for key, _ in self.PLOTS:
            ok = self._plot_available(key)
            self.plot_checks[key].configure(state=ttk.NORMAL if ok else ttk.DISABLED)
            if not ok:
                self.plot_vars[key].set(False)

    # ------------------------------------------------------------------
    # Plotting
    # ------------------------------------------------------------------
    @staticmethod
    def _build_style_cycle():
        colors = (
            plt.rcParams["axes.prop_cycle"].by_key().get("color", ["b", "g", "r", "c", "m", "y", "k"])
        )
        return colors

    def _color(self, idx):
        return self._style_cycle[idx % len(self._style_cycle)]

    def _active_plots(self):
        return [
            key
            for key, _ in self.PLOTS
            if self.plot_vars[key].get() and self._plot_available(key)
        ]

    def _set_fig_height(self, rows):
        """Altura adaptativa de la figura por nº de filas del grid: ~4\" con 1 fila
        (1-2 plots), ~7\" con 2 filas (3-4 plots). Ajusta también el alto del widget Tk
        para que el área scrollable calcule bien su scrollregion."""
        height_in = 4.0 if rows <= 1 else 7.0
        self.fig.set_size_inches(8, height_in)
        try:
            self.canvas.get_tk_widget().configure(height=int(height_in * self.fig.dpi))
        except Exception:
            pass

    def _refresh_plots(self):
        # Recrea el canvas desde cero en vez de fig.clear()+reusar: evita el subplot
        # fantasma que deja constrained_layout + el twinx del Bode en el canvas Tk
        # vivo al redibujar tras togglear un checkbox (ver _reset_plot_canvas).
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            self._reset_plot_canvas()
        self._nyquist_ax = None
        self._bode_zax = None
        active = self._active_plots()
        if not active:
            self._set_fig_height(1)
            ax = self.fig.add_subplot(111)
            ax.set_title("No plot selected")
            self.canvas.draw_idle()
            return
        layout = {1: (1, 1), 2: (1, 2), 3: (2, 2), 4: (2, 2)}[len(active)]
        rows, cols = layout
        self._set_fig_height(rows)
        for i, key in enumerate(active):
            ax = self.fig.add_subplot(rows, cols, i + 1)
            if key == "nyquist":
                self._plot_nyquist(ax)
            elif key == "bode":
                self._plot_bode(ax)
            elif key == "z_e":
                self._plot_xy(ax, "E_V", "Z_mod", "|Z| vs E", "E dc (V)", "|Z| (Ω)")
            elif key == "z_t":
                self._plot_xy(ax, "t_s", "Z_mod", "|Z| vs time", "t (s)", "|Z| (Ω)")
        self.canvas.draw_idle()

    def _visible_indexed(self):
        """Itera (idx_global, spectrum) sobre los espectros visibles, para color estable."""
        idx = 0
        for sp in self._all_spectra():
            if sp.visible:
                yield idx, sp
            idx += 1

    def _plot_nyquist(self, ax):
        self._nyquist_ax = ax
        any_data = False
        for idx, sp in self._visible_indexed():
            if not sp.has("Z_real", "Z_imag"):
                continue
            ax.plot(
                sp.data["Z_real"],
                sp.data["Z_imag"],
                marker="o",
                markersize=3,
                linewidth=1.3,
                color=self._color(idx),
                label=sp.name,
            )
            any_data = True
        ax.set_title("Nyquist")
        ax.set_xlabel("Z_real (Ω)")
        ax.set_ylabel("-Z_imag (Ω)")
        if any_data:
            ax.legend(loc="best", fontsize=7, ncol=2 if len(list(self._all_spectra())) > 6 else 1)
        self._draw_nyquist_measurements(ax)

    def _plot_bode(self, ax):
        self._bode_zax = ax
        ax_ph = ax.twinx()
        any_data = False
        for idx, sp in self._visible_indexed():
            if not (sp.has("freq_Hz", "Z_mod") and sp.distinct_freqs() > 1):
                continue
            f = sp.data["freq_Hz"]
            order = np.argsort(f)
            fo = f[order]
            c = self._color(idx)
            ax.plot(fo, sp.data["Z_mod"][order], marker="o", markersize=3, linewidth=1.3,
                    color=c, label=sp.name)
            if "phase_deg" in sp.data:
                ax_ph.plot(fo, sp.data["phase_deg"][order], marker="s", markersize=2,
                           linewidth=1.0, linestyle="--", color=c, alpha=0.7)
            any_data = True
        ax.set_title("Bode (|Z| solid · phase dashed)")
        ax.set_xlabel("freq (Hz) — log")
        ax.set_ylabel("|Z| (Ω) — log")
        ax_ph.set_ylabel("phase (°)")
        if any_data:
            # Escala log solo con datos: evita el warning de xlim no positivo al
            # limpiar/redibujar un eje log vacío.
            ax.set_xscale("log")
            ax.set_yscale("log")
            ax.legend(loc="best", fontsize=7)

    def _plot_xy(self, ax, xkey, ykey, title, xlabel, ylabel):
        any_data = False
        for idx, sp in self._visible_indexed():
            if not sp.has(xkey, ykey):
                continue
            x = sp.data[xkey]
            order = np.argsort(x)
            ax.plot(x[order], sp.data[ykey][order], marker="o", markersize=3, linewidth=1.3,
                    color=self._color(idx), label=sp.name)
            any_data = True
        ax.set_title(title)
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        if any_data:
            ax.legend(loc="best", fontsize=7)

    def _draw_nyquist_measurements(self, ax):
        for sp in self._all_spectra():
            if not sp.visible or not sp.meas:
                continue
            m = sp.meas
            if "Rs" in m:
                ax.axvline(m["Rs"], color="tab:red", linestyle="--", linewidth=1, alpha=0.7)
            if "rct_edge" in m:
                ax.axvline(m["rct_edge"], color="tab:green", linestyle="--", linewidth=1, alpha=0.7)
                if "Rs" in m:
                    ax.annotate(
                        "", xy=(m["rct_edge"], 0), xytext=(m["Rs"], 0),
                        arrowprops=dict(arrowstyle="<->", color="tab:green"),
                    )
            warb = m.get("warb")
            if warb and len(warb) == 2:
                xs = [warb[0][0], warb[1][0]]
                ys = [warb[0][1], warb[1][1]]
                ax.plot(xs, ys, color="tab:purple", linewidth=2, marker="D", markersize=4)

    # ------------------------------------------------------------------
    # Picking manual (Nyquist)
    # ------------------------------------------------------------------
    def _arm_pick(self, kind):
        sp = self._selected_spectrum()
        if sp is None:
            self._set_status("Select a spectrum in the tree first.")
            return
        if not self.plot_vars["nyquist"].get() or not self._plot_available("nyquist"):
            self._set_status("Enable the Nyquist plot to measure.")
            return
        self._pick_kind = kind
        if kind == "warb":
            sp.meas.pop("warb", None)
        hint = {
            "rs": "Click the high-frequency real-axis intercept (Rs).",
            "rct": "Click the right edge of the semicircle (Rct = x − Rs).",
            "warb": "Click the TWO endpoints of the Warburg segment.",
        }[kind]
        self._set_status(hint + " (toolbar pan/zoom must be off)")

    def _on_pick(self, event):
        if self._pick_kind is None:
            return
        try:
            if getattr(self.toolbar_mpl, "mode", "") not in ("", None):
                return
        except Exception:
            pass
        if event.inaxes is not self._nyquist_ax or event.xdata is None:
            return
        sp = self._selected_spectrum()
        if sp is None or not sp.has("Z_real", "Z_imag"):
            return
        zr = sp.data["Z_real"]
        zi = sp.data["Z_imag"]
        # Snap al punto medido más cercano del espectro seleccionado.
        j = int(np.argmin((zr - event.xdata) ** 2 + (zi - event.ydata) ** 2))
        px, py = float(zr[j]), float(zi[j])
        kind = self._pick_kind
        if kind == "rs":
            sp.meas["Rs"] = px
            self._recompute_rct(sp)
            self._pick_kind = None
            self._set_status(f"Rs = {px:.4g} Ω")
        elif kind == "rct":
            sp.meas["rct_edge"] = px
            self._recompute_rct(sp)
            self._pick_kind = None
            rct = sp.meas.get("Rct")
            self._set_status(
                f"Rct edge = {px:.4g} Ω" + (f" → Rct = {rct:.4g} Ω" if rct is not None else " (pick Rs too)")
            )
        elif kind == "warb":
            pts = sp.meas.setdefault("warb", [])
            pts.append((px, py))
            if len(pts) >= 2:
                pts[:] = pts[-2:]
                dx = pts[1][0] - pts[0][0]
                dy = pts[1][1] - pts[0][1]
                sp.meas["warb_len"] = abs(dx)
                sp.meas["warb_angle"] = float(np.degrees(np.arctan2(dy, dx)))
                self._pick_kind = None
                self._set_status(
                    f"Warburg L (proj. on real axis) = {abs(dx):.4g} Ω, ∠ = {sp.meas['warb_angle']:.1f}°"
                )
            else:
                self._set_status("Warburg: click the second endpoint.")
        self._refresh_plots()
        self._refresh_results_table()

    @staticmethod
    def _recompute_rct(sp):
        if "Rs" in sp.meas and "rct_edge" in sp.meas:
            sp.meas["Rct"] = sp.meas["rct_edge"] - sp.meas["Rs"]

    def _clear_measure(self):
        sp = self._selected_spectrum()
        if sp is None:
            self._set_status("Select a spectrum to clear its measurements.")
            return
        sp.meas.clear()
        self._pick_kind = None
        self._refresh_plots()
        self._refresh_results_table()
        self._set_status(f"Cleared measurements of '{sp.name}'.")

    # ------------------------------------------------------------------
    # Crosshair (Bode)
    # ------------------------------------------------------------------
    def _on_motion(self, event):
        if self._bode_zax is None or event.inaxes is not self._bode_zax or event.xdata is None:
            self.lbl_cross.configure(text="")
            return
        target = np.log10(event.xdata) if event.xdata > 0 else None
        best: tuple | None = None
        for sp in self._all_spectra():
            if not sp.visible or not sp.has("freq_Hz", "Z_mod"):
                continue
            f = sp.data["freq_Hz"]
            with np.errstate(divide="ignore"):
                d = np.abs(np.log10(f) - target) if target is not None else np.abs(f - event.xdata)
            j = int(np.argmin(d))
            dist = float(d[j])
            if best is None or dist < best[0]:
                ph = sp.data["phase_deg"][j] if "phase_deg" in sp.data else float("nan")
                best = (dist, f[j], sp.data["Z_mod"][j], ph)
        if best is not None:
            self.lbl_cross.configure(
                text=f"f={best[1]:.4g} Hz  |Z|={best[2]:.4g} Ω  φ={best[3]:.1f}°"
            )

    # ------------------------------------------------------------------
    # Resultados / export
    # ------------------------------------------------------------------
    def _refresh_results_table(self):
        self.tree_res.delete(*self.tree_res.get_children())
        for sp in self._all_spectra():
            if not sp.meas:
                continue
            m = sp.meas
            self.tree_res.insert(
                "",
                ttk.END,
                text=sp.name,
                values=(
                    f"{m['Rs']:.4g}" if "Rs" in m else "",
                    f"{m['Rct']:.4g}" if "Rct" in m else "",
                    f"{m['warb_len']:.4g}" if "warb_len" in m else "",
                    f"{m['warb_angle']:.1f}" if "warb_angle" in m else "",
                ),
            )

    def export_results(self):
        rows = []
        for exp in self.experiments:
            for sp in exp.spectra:
                if not sp.meas:
                    continue
                m = sp.meas
                rows.append(
                    [
                        exp.name,
                        sp.name,
                        m.get("Rs", ""),
                        m.get("Rct", ""),
                        m.get("warb_len", ""),
                        m.get("warb_angle", ""),
                    ]
                )
        if not rows:
            self._set_status("No measurements to export. Pick Rs/Rct/Warburg first.")
            return
        path = asksaveasfilename(
            title="Export EIS results",
            defaultextension=".csv",
            initialfile=f"eis_analysis_{time.strftime('%Y%m%d_%H%M')}.csv",
            filetypes=[("CSV files", "*.csv")],
        )
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["experiment", "spectrum", "Rs_ohm", "Rct_ohm", "warburg_len_ohm", "warburg_angle_deg"])
                w.writerows(rows)
        except Exception as e:
            self._set_status(f"Export error: {e}")
            return
        self._set_status(f"Exported {len(rows)} measurement(s) → {os.path.basename(path)}.")

    def _set_status(self, msg):
        self.lbl_status.configure(text=msg)


# ---------------------------------------------------------------------------
# Ventana: shell con notebook por método (Peaks CV/SWV · EIS)
# ---------------------------------------------------------------------------
class AnalysisWindow(ttk.Toplevel):
    """Ventana de análisis con un notebook por método: pestaña de picos (CV/SWV) y
    pestaña EIS. La pestaña activa por defecto la decide el método del plotter que
    la lanzó (EIS → pestaña EIS)."""

    def __init__(self, master, plotter=None, **kwargs):
        super().__init__(master, **kwargs)
        self.title("Curve Analysis")
        self.geometry("1180x860")
        self.parent = master

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=ttk.BOTH, expand=True)
        self.peaks = PeakAnalysisFrame(self.notebook, owner=self, plotter=plotter)
        self.eis = EISAnalysisFrame(self.notebook, owner=self, plotter=plotter)
        self.notebook.add(self.peaks, text="Peaks (CV/SWV)")
        self.notebook.add(self.eis, text="EIS")
        if plotter is not None and getattr(plotter, "method", "") == "eis":
            self.notebook.select(self.eis)

        # Atajos de teclado para la pestaña de picos (compatibilidad).
        self.bind("<Control-l>", lambda _e: self.peaks.load_csv())
        self.bind("<Control-i>", lambda _e: self.peaks.import_analysis())
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def on_close(self):
        try:
            if hasattr(self.parent, "_on_analysis_window_closed"):
                self.parent._on_analysis_window_closed()
        except Exception:
            pass
        self.destroy()


__author__ = "Edisson A. Naula"
__date__ = "2026-06-15"
