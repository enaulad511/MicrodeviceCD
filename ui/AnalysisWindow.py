# -*- coding: utf-8 -*-
import csv
import os
import re
import time
from tkinter.filedialog import askopenfilename, asksaveasfilename

import matplotlib

matplotlib.use("TkAgg")
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

        self._build_ui()
        if plotter is not None:
            self._snapshot_from_plotter(plotter)
            self._refresh_tree()
            self._refresh_overlay()

        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------------------------------------------------------------------
    # UI
    # ---------------------------------------------------------------------
    def _build_ui(self):
        # --- Toolbar fila 1: acciones ---
        toolbar = ttk.Frame(self)
        toolbar.pack(side=ttk.TOP, fill=ttk.X, padx=6, pady=(6, 2))

        ttk.Button(
            toolbar, text="📂 Load CSV", bootstyle="secondary", command=self.load_csv
        ).pack(side=ttk.LEFT, padx=3)
        ttk.Button(
            toolbar, text="🗑 Remove", bootstyle="danger", command=self.remove_selected
        ).pack(side=ttk.LEFT, padx=3)
        ttk.Button(
            toolbar, text="👁 Show/Hide", bootstyle="info", command=self.toggle_visibility
        ).pack(side=ttk.LEFT, padx=3)
        ttk.Button(
            toolbar, text="📊 Compute", bootstyle="success", command=self.compute_extrema
        ).pack(side=ttk.LEFT, padx=3)
        ttk.Button(
            toolbar, text="💾 Export", bootstyle="primary", command=self.export_results
        ).pack(side=ttk.LEFT, padx=3)

        # --- Toolbar fila 2: selectores de picos + filtro ---
        toolbar2 = ttk.Frame(self)
        toolbar2.pack(side=ttk.TOP, fill=ttk.X, padx=6, pady=(0, 6))

        ttk.Label(toolbar2, text="Peaks:").pack(side=ttk.LEFT, padx=(0, 4))
        self.peak_mode = ttk.StringVar(value="global")
        ttk.Radiobutton(
            toolbar2, text="Global", variable=self.peak_mode, value="global"
        ).pack(side=ttk.LEFT)
        ttk.Radiobutton(
            toolbar2, text="Local", variable=self.peak_mode, value="local"
        ).pack(side=ttk.LEFT)

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

        # --- Split (tree | plots) ---
        main = ttk.PanedWindow(self, orient=ttk.HORIZONTAL)
        main.pack(fill=ttk.BOTH, expand=True, padx=6, pady=(0, 6))

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
        plt.style.use("seaborn-v0_8-darkgrid")
        self.fig = Figure(figsize=(8, 6), dpi=100, layout="constrained")
        gs = self.fig.add_gridspec(2, 2)
        self.ax_overlay = self.fig.add_subplot(gs[0, :])
        self.ax_min = self.fig.add_subplot(gs[1, 0])
        self.ax_max = self.fig.add_subplot(gs[1, 1])
        self.ax_overlay.set_title("Curves overlay")
        self.ax_min.set_title("Min trend (mean ± std per experiment)")
        self.ax_max.set_title("Max trend (mean ± std per experiment)")
        self.ax_min.set_xlabel("Experiment index")
        self.ax_max.set_xlabel("Experiment index")

        self.canvas = FigureCanvasTkAgg(self.fig, right)
        self.canvas.get_tk_widget().pack(fill=ttk.BOTH, expand=True)
        self.toolbar_mpl = NavigationToolbar2Tk(self.canvas, right, pack_toolbar=False)
        self.toolbar_mpl.pack(fill=ttk.X)

        # --- Tabla de resultados (jerárquica) ---
        bottom = ttk.LabelFrame(self, text="Results (visible only)")
        bottom.pack(fill=ttk.X, padx=6, pady=(0, 6))
        cols_r = ("idx", "type", "n", "x", "y", "std")
        self.tree_res = ttk.Treeview(
            bottom, columns=cols_r, show="tree headings", height=8
        )
        widths = {"idx": 50, "type": 80, "n": 50, "x": 130, "y": 130, "std": 130}
        self.tree_res.heading("#0", text="Experiment / Cycle")
        self.tree_res.column("#0", width=300, anchor="w")
        for c in cols_r:
            self.tree_res.heading(c, text=c)
            self.tree_res.column(c, width=widths[c], anchor="w")
        vsb_r = ttk.Scrollbar(bottom, orient="vertical", command=self.tree_res.yview)
        self.tree_res.configure(yscrollcommand=vsb_r.set)
        self.tree_res.pack(side=ttk.LEFT, fill=ttk.X, expand=True)
        vsb_r.pack(side=ttk.LEFT, fill=ttk.Y)

        self.lbl_status = ttk.Label(self, text="Ready.", anchor="w")
        self.lbl_status.pack(side=ttk.BOTTOM, fill=ttk.X, padx=6, pady=(0, 4))

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
                ciid = self.tree_curves.insert(
                    exp_iid, ttk.END, text=cycle.name, values=(mark,)
                )
                self._tree_ref[ciid] = ("cycle", exp, cycle)

    def _refresh_overlay(self):
        """Redibuja overlay: muestra filtrado si filtro activo, sino raw."""
        kind = self.filter_var.get()
        fw = max(1, self.filter_window_var.get() or 1)
        self.ax_overlay.clear()
        self.ax_overlay.set_title("Curves overlay" + (f" (filtered: {kind})" if kind != "none" else ""))
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
            self.ax_overlay.legend(loc="best", fontsize=7, ncol=2)
        self.canvas.draw_idle()

    def _set_status(self, msg):
        self.lbl_status.configure(text=msg)

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
        self._set_status(
            f"Loaded experiment '{exp_name}' with {len(exp.cycles)} cycle(s)."
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
        self._set_status(f"Removed {len(exps_to_drop)} experiment(s), {len(cycles_to_drop)} cycle(s).")

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

        # Reset overlay (re-aplica filtro visual también)
        self._refresh_overlay()
        self.tree_res.delete(*self.tree_res.get_children())

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
                else:
                    maxs, mins = _local_extrema(c.xs, ys_f, window=pwin)
                c.max_points = maxs
                c.min_points = mins
                for (x, y) in maxs:
                    all_max_xy.append((x, y))
                    cycle_max_ys.append(y)
                    self.tree_res.insert(
                        exp_iid,
                        ttk.END,
                        text=c.name,
                        values=(exp_idx, "max", "", f"{x:.6g}", f"{y:.6g}", ""),
                    )
                for (x, y) in mins:
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
                    values=(exp_idx, "mean_max", len(cycle_max_ys), "", f"{mean_mx:.6g}", f"{std_mx:.6g}"),
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
                    values=(exp_idx, "mean_min", len(cycle_min_ys), "", f"{mean_mn:.6g}", f"{std_mn:.6g}"),
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
        self.ax_min.set_title(f"Min trend ({mode}) — mean ± std")
        self.ax_max.set_title(f"Max trend ({mode}) — mean ± std")
        self.ax_min.set_xlabel("Experiment index")
        self.ax_max.set_xlabel("Experiment index")
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
            with open(path, "w", newline="") as f:
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
            with open(curves_path, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(
                    ["experiment", "cycle", "point_idx", "x", "y_raw", "y_filtered", "filter", "filter_window"]
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
            self._set_status(
                f"Results exported, but error writing curves file: {e}"
            )
            return
        self._set_status(
            f"Exported {len(rows)} result row(s) → {os.path.basename(path)}; "
            f"{n_pts} curve point(s) → {os.path.basename(curves_path)}."
        )

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
