# -*- coding: utf-8 -*-
import csv
import os
import re
import time
from tkinter.filedialog import askopenfilename, asksaveasfilename

import matplotlib

from templates.constants import font_tabs

matplotlib.use("TkAgg")
import tkinter as tk

import matplotlib.pyplot as plt
import numpy as np
import ttkbootstrap as ttk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure


# ---------------------------------------------------------------------------
# Modelo de datos
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
# Ventana
# ---------------------------------------------------------------------------
class AnalysisWindow(ttk.Toplevel):
    """Ventana de análisis: experimentos (archivos) → ciclos → tendencia promedio."""

    FILTERS = ("none", "moving_avg", "median")

    def __init__(self, master, plotter=None, **kwargs):
        super().__init__(master, **kwargs)
        self.title("Curve Analysis")
        self.geometry("1180x820")

        self.parent = master
        self.experiments = []  # list[Experiment]
        # mapeo de iid de Treeview → ("exp", exp) o ("cycle", exp, cycle)
        self._tree_ref = {}
        # estado para picking de X desde la gráfica overlay
        self._pick_cid: int | None = None
        self._pick_kind: str | None = None  # 'max' | 'min' | None

        self._build_ui()
        self.bind("<Control-i>", lambda _e: self.import_analysis())
        self.bind("<Control-l>", lambda _e: self.load_csv())
        if plotter is not None:
            self._snapshot_from_plotter(plotter)
            self._refresh_tree()
            self._refresh_overlay()

        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------------------------------------------------------------------
    # UI
    # ---------------------------------------------------------------------
    def _build_ui(self):
        # --- Menu bar ---
        menubar = tk.Menu(self)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Load CSV", command=self.load_csv, accelerator="Ctrl+L")
        file_menu.add_separator()
        file_menu.add_command(
            label="Import analysis (_curves.csv)",
            command=self.import_analysis,
            accelerator="Ctrl+I",
        )
        file_menu.add_command(label="Export results", command=self.export_results)
        menubar.add_cascade(label="File", menu=file_menu, font=font_tabs)
        self.configure(menu=menubar)
        menubar.configure(font=font_tabs)

        # --- Toolbar fila 1: acciones ---
        toolbar = ttk.Frame(self)
        toolbar.pack(side=ttk.TOP, fill=ttk.X, padx=6, pady=(6, 2))

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

        # Right: figura con 3 ejes
        right = ttk.Frame(main)
        main.add(right, weight=4)
        right.bind("<MouseWheel>", _on_wheel)
        plt.style.use("seaborn-v0_8-darkgrid")
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

        self.canvas = FigureCanvasTkAgg(self.fig, right)
        self.canvas.get_tk_widget().pack(fill=ttk.BOTH, expand=True)
        self.toolbar_mpl = NavigationToolbar2Tk(self.canvas, right, pack_toolbar=False)
        self.toolbar_mpl.pack(fill=ttk.X)

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

    def _refresh_overlay(self):
        """Redibuja overlay: muestra filtrado si filtro activo, sino raw."""
        kind = self.filter_var.get()
        fw = max(1, self.filter_window_var.get() or 1)
        self.ax_overlay.clear()
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
                    self.tree_res.insert(
                        exp_iid,
                        ttk.END,
                        text=c.name,
                        values=(exp_idx, "max", "", f"{x:.6g}", f"{y:.6g}", ""),
                    )
                for x, y in mins:
                    all_min_xy.append((x, y))
                    cycle_min_ys.append(y)
                    self.tree_res.insert(
                        exp_iid,
                        ttk.END,
                        text=c.name,
                        values=(exp_idx, "min", "", f"{x:.6g}", f"{y:.6g}", ""),
                    )
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
        """Resetea el estado completo de la ventana."""
        self.experiments.clear()
        self._tree_ref.clear()
        self.tree_curves.delete(*self.tree_curves.get_children())
        self.tree_res.delete(*self.tree_res.get_children())
        for ax in (self.ax_overlay, self.ax_min, self.ax_max):
            ax.clear()
        self.ax_overlay.set_title("Curves overlay")
        self.ax_min.set_title("Min trend (mean ± std)")
        self.ax_max.set_title("Max trend (mean ± std)")
        self.ax_min.set_xlabel("Experiment index")
        self.ax_max.set_xlabel("Experiment index")
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
                groups: dict[str, dict[str, tuple[list, list]]] = {}
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

    # ---------------------------------------------------------------------
    def on_close(self):
        try:
            if hasattr(self.parent, "_on_analysis_window_closed"):
                self.parent._on_analysis_window_closed()
        except Exception:
            pass
        self.destroy()


__author__ = "Edisson A. Naula"
__date__ = "2026-05-13"
