# -*- coding: utf-8 -*-
import csv
import os
import re
import time
from tkinter.filedialog import askopenfilename, asksaveasfilename

import numpy as np
import ttkbootstrap as ttk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

from templates.utils import experiment_dir
from ui.analysis.common import CycleCurve, Experiment, _apply_filter, plt


# ---------------------------------------------------------------------------
# Detección de picos SWV (múltiples picos, ambas direcciones, con prominencia)
# ---------------------------------------------------------------------------
# Etiquetas de líneas cargadas por EventPlotter desde un CSV SWV: "<base>-r<run>c<cycle>".
_SQWV_LBL_RE = re.compile(r"^(.+)-r(\d+)c(\d+)$")


def _parse_sqwv_label(label):
    """'archivo-r2c0' → ('archivo', 2, 0); si no matchea, ('label', 1, 0)."""
    m = _SQWV_LBL_RE.match(str(label))
    if m:
        return m.group(1), int(m.group(2)), int(m.group(3))
    return str(label), 1, 0


def _detect_dir_indices(ys, want_max, window, min_prom):
    """Índices de máximos (want_max=True) o mínimos locales en ys.

    Un punto es candidato si es el extremo en su ventana ±window y su prominencia
    local (vs el lado menos profundo dentro de esa ventana) supera min_prom. Los
    candidatos a <= window de distancia se fusionan conservando el más extremo, así
    una meseta o un hombro no produce un racimo de picos pegados.
    """
    n = len(ys)
    if n == 0:
        return []
    w = max(1, int(window))
    cand = []
    for i in range(n):
        lo = max(0, i - w)
        hi = min(n, i + w + 1)
        seg = ys[lo:hi]
        v = ys[i]
        if want_max:
            if v == seg.max() and v > seg.min():
                base = max(ys[lo : i + 1].min(), ys[i:hi].min())
                if (v - base) >= min_prom:
                    cand.append(i)
        else:
            if v == seg.min() and v < seg.max():
                base = min(ys[lo : i + 1].max(), ys[i:hi].max())
                if (base - v) >= min_prom:
                    cand.append(i)
    merged = []
    for i in cand:
        if merged and (i - merged[-1]) <= w:
            prev = merged[-1]
            better = (ys[i] > ys[prev]) if want_max else (ys[i] < ys[prev])
            if better:
                merged[-1] = i
        else:
            merged.append(i)
    return merged


def _detect_peaks(xs, ys, direction, window, prom_frac):
    """Devuelve (maxima, minima) como listas de (x, y).

    prom_frac es la prominencia mínima como fracción del span de ys (decisión Q11:
    porcentaje del rango, así escala con el current range de cada corrida).
    """
    ys = np.asarray(ys, dtype=float)
    xs = np.asarray(xs, dtype=float)
    if ys.size == 0:
        return [], []
    span = float(np.max(ys) - np.min(ys)) or 1.0
    min_prom = max(0.0, prom_frac) * span
    maxs, mins = [], []
    if direction in ("max", "both"):
        for i in _detect_dir_indices(ys, True, window, min_prom):
            maxs.append((float(xs[i]), float(ys[i])))
    if direction in ("min", "both"):
        for i in _detect_dir_indices(ys, False, window, min_prom):
            mins.append((float(xs[i]), float(ys[i])))
    return maxs, mins


# ---------------------------------------------------------------------------
# Pestaña: análisis de picos SWV (múltiples picos por corrida, sin tendencia)
# ---------------------------------------------------------------------------
class SqwvAnalysisFrame(ttk.Frame):
    """Pestaña de picos SWV: experimentos (archivo/corrida) → corridas (runs).

    A diferencia de PeakAnalysisFrame, NO calcula tendencia entre experimentos: el
    énfasis es detectar MÚLTIPLES picos por corrida (analitos a distintos potenciales)
    y reportar E_pico / I_pico en cada punto. Detecta máximos y mínimos con control de
    ventana y prominencia (% del span), permite añadir/borrar picos a mano, y un solo
    overlay con los picos marcados y anotados. Reusa Experiment/CycleCurve; el ítem por
    curva es una corrida (SWV = un barrido I vs E por run; un archivo puede traer varios).
    """

    FILTERS = ("none", "moving_avg", "median")

    def __init__(self, master, owner, plotter=None, **kwargs):
        super().__init__(master, **kwargs)
        self.owner = owner
        self.experiments = []  # list[Experiment]
        self._tree_ref = {}  # iid árbol izq → ("exp", exp) | ("run", exp, curve)
        self._res_ref = {}  # iid tabla → ("exp", exp) | ("run", exp, c) | ("peak", exp, c, kind, (x,y))
        self._legend_visible = True
        self._add_mode = False  # captura de clics para añadir picos
        self._pick_cid: int | None = None

        self._build_ui()
        # Siembra: corrida SWV en memoria (total_data, sin pre-tratamiento) + curvas CSV
        # ya cargadas en el plotter (loaded_lines). Solo para un plotter SWV.
        if plotter is not None and getattr(plotter, "method", "") == "sqwv":
            self._seed_from_plotter(plotter)
            self._refresh_tree()
            self._redraw()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        # --- Toolbar fila 1: archivo (izq) + globales (der). Dos filas para que en
        # pantallas chicas (touchscreen del Pi) no se corten Clear all / Legend. ---
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
            toolbar_b, text="📊 Compute", bootstyle="success", command=self.compute_peaks
        ).pack(side=ttk.LEFT, padx=3)

        # --- Toolbar fila 2: dirección + ventana + prominencia + filtro ---
        toolbar2 = ttk.Frame(self)
        toolbar2.pack(side=ttk.TOP, fill=ttk.X, padx=6, pady=(0, 4))
        ttk.Label(toolbar2, text="Peaks:").pack(side=ttk.LEFT, padx=(0, 4))
        self.direction_var = ttk.StringVar(value="both")
        for txt, val in (("Max", "max"), ("Min", "min"), ("Both", "both")):
            ttk.Radiobutton(
                toolbar2, text=txt, variable=self.direction_var, value=val
            ).pack(side=ttk.LEFT)

        ttk.Label(toolbar2, text="Peak window:").pack(side=ttk.LEFT, padx=(12, 4))
        self.peak_window_var = ttk.IntVar(value=5)
        ttk.Spinbox(
            toolbar2, from_=1, to=500, increment=1, width=5, textvariable=self.peak_window_var
        ).pack(side=ttk.LEFT)

        ttk.Label(toolbar2, text="Min prominence (%):").pack(side=ttk.LEFT, padx=(12, 4))
        self.prominence_var = ttk.DoubleVar(value=5.0)
        ttk.Spinbox(
            toolbar2, from_=0, to=100, increment=0.5, width=6, textvariable=self.prominence_var
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

        # --- Toolbar fila 3: edición manual de picos ---
        toolbar3 = ttk.Frame(self)
        toolbar3.pack(side=ttk.TOP, fill=ttk.X, padx=6, pady=(0, 6))
        ttk.Label(toolbar3, text="Manual →").pack(side=ttk.LEFT, padx=(0, 4))
        self.btn_add = ttk.Button(
            toolbar3,
            text="➕ Add peak (click)",
            bootstyle="secondary-outline",
            command=self._toggle_add_mode,
        )
        self.btn_add.pack(side=ttk.LEFT, padx=3)
        ttk.Button(
            toolbar3,
            text="➖ Delete selected",
            bootstyle="warning-outline",
            command=self._delete_selected_peaks,
        ).pack(side=ttk.LEFT, padx=3)
        self.lbl_cross = ttk.Label(toolbar3, text="", anchor="e")
        self.lbl_cross.pack(side=ttk.RIGHT, padx=6)

        # Status bar (fijo abajo, fuera del scroll)
        self.lbl_status = ttk.Label(self, text="Ready.", anchor="w")
        self.lbl_status.pack(side=ttk.BOTTOM, fill=ttk.X, padx=6, pady=(0, 4))

        # --- Área scrollable (árbol + figura + resultados), igual que las otras pestañas ---
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

        # --- Split árbol | figura ---
        main = ttk.PanedWindow(inner, orient=ttk.HORIZONTAL)
        main.pack(fill=ttk.X, padx=0, pady=(0, 6))

        left = ttk.LabelFrame(main, text="Experiments → Runs (double-click to rename)")
        main.add(left, weight=1)
        self.tree_curves = ttk.Treeview(
            left, columns=("info",), show="tree headings", selectmode="extended"
        )
        self.tree_curves.heading("#0", text="Item")
        self.tree_curves.heading("info", text="State")
        self.tree_curves.column("#0", width=260, anchor="w")
        self.tree_curves.column("info", width=80, anchor="w")
        vsb_c = ttk.Scrollbar(left, orient="vertical", command=self.tree_curves.yview)
        self.tree_curves.configure(yscrollcommand=vsb_c.set)
        self.tree_curves.pack(side=ttk.LEFT, fill=ttk.BOTH, expand=True, padx=4, pady=4)
        vsb_c.pack(side=ttk.LEFT, fill=ttk.Y)
        self.tree_curves.bind("<Double-1>", self._begin_rename)
        self._rename_entry: "ttk.Entry | None" = None

        right = ttk.Frame(main)
        main.add(right, weight=4)
        right.bind("<MouseWheel>", _on_wheel)
        plt.style.use("seaborn-v0_8-darkgrid")
        self._plot_host = right
        self._create_plot_canvas()

        # --- Tabla de resultados (un pico por fila) ---
        bottom = ttk.LabelFrame(inner, text="Detected peaks (visible only)")
        bottom.pack(fill=ttk.BOTH, pady=(0, 6))
        cols_r = ("type", "e_peak", "i_peak")
        self.tree_res = ttk.Treeview(bottom, columns=cols_r, show="tree headings", height=14)
        self.tree_res.heading("#0", text="Experiment / Run")
        self.tree_res.column("#0", width=300, anchor="w")
        heads = {"type": "Type", "e_peak": "E peak (V)", "i_peak": "I peak (A)"}
        widths = {"type": 80, "e_peak": 150, "i_peak": 150}
        for c in cols_r:
            self.tree_res.heading(c, text=heads[c])
            self.tree_res.column(c, width=widths[c], anchor="w")
        vsb_r = ttk.Scrollbar(bottom, orient="vertical", command=self.tree_res.yview)
        self.tree_res.configure(yscrollcommand=vsb_r.set)
        vsb_r.pack(side=ttk.RIGHT, fill=ttk.Y)
        self.tree_res.pack(fill=ttk.BOTH, expand=True)
        self.tree_res.bind("<Double-1>", self._begin_rename)

    # --------------------------------------------------- Canvas (recreable)
    def _create_plot_canvas(self):
        self.fig = Figure(figsize=(8, 5), dpi=100, layout="constrained")
        self.ax_overlay = self.fig.add_subplot(1, 1, 1)
        self.ax_overlay.set_title("SWV curves — detected peaks")
        self.ax_overlay.set_xlabel("E (V)")
        self.ax_overlay.set_ylabel("I (A)")
        self.canvas = FigureCanvasTkAgg(self.fig, self._plot_host)
        self.canvas.get_tk_widget().pack(fill=ttk.BOTH, expand=True)
        self.toolbar_mpl = NavigationToolbar2Tk(self.canvas, self._plot_host, pack_toolbar=False)
        self.toolbar_mpl.pack(fill=ttk.X)
        self.canvas.mpl_connect("motion_notify_event", self._on_hover)
        # Re-arma la captura de clics si el modo "Add peak" seguía activo (el canvas
        # se recrea en cada redibujo, invalidando el cid anterior).
        if self._add_mode:
            self._pick_cid = self.canvas.mpl_connect("button_press_event", self._on_add_click)

    def _reset_plot_canvas(self):
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

    # ------------------------------------------------------ Siembra / estado
    def _seed_from_plotter(self, plotter):
        """Corrida SWV en memoria (total_data, sin pre-tratamiento) + curvas CSV ya
        cargadas en el plotter. La corrida en vivo se agrupa por 'run'; el barrido es
        un único ciclo por run, así que el ítem es la corrida."""
        xk = getattr(plotter, "x_key", "E_V") or "E_V"
        yk = getattr(plotter, "y_key", "I_A") or "I_A"
        groups = {}  # run → ([xs], [ys])
        for ev in getattr(plotter, "total_data", []):
            if ev.get("phase") == "pretreatment":
                continue
            x, y = ev.get(xk), ev.get(yk)
            if x is None or y is None:
                continue
            try:
                x, y = float(x), float(y)
            except (TypeError, ValueError):
                continue
            run = ev.get("run", 1)
            groups.setdefault(run, ([], []))
            groups[run][0].append(x)
            groups[run][1].append(y)
        if groups:
            exp = Experiment(name="SWV run")
            for run in sorted(groups.keys(), key=lambda r: (r is None, r)):
                xs, ys = groups[run]
                exp.cycles.append(CycleCurve(name=f"r{run}", xs=xs, ys=ys))
            self.experiments.append(exp)
        self._snapshot_loaded_lines(plotter)

    def _snapshot_loaded_lines(self, plotter):
        """Curvas cargadas desde CSV en el plotter (loaded_lines), agrupadas por archivo."""
        groups = {}  # base → list[(run, cycle, xs, ys)]
        for line in getattr(plotter, "loaded_lines", []):
            try:
                xs = np.asarray(line.get_xdata(), dtype=float)
                ys = np.asarray(line.get_ydata(), dtype=float)
            except Exception:
                continue
            if xs.size == 0:
                continue
            base, run, cyc = _parse_sqwv_label(line.get_label())
            groups.setdefault(base, []).append((run, cyc, xs, ys))
        for base, items in groups.items():
            exp = Experiment(name=base)
            items.sort(key=lambda t: (t[0], t[1]))
            for run, cyc, xs, ys in items:
                exp.cycles.append(CycleCurve(name=f"r{run}", xs=xs, ys=ys))
            self.experiments.append(exp)

    def _refresh_tree(self):
        self.tree_curves.delete(*self.tree_curves.get_children())
        self._tree_ref = {}
        for exp in self.experiments:
            n_vis = sum(1 for c in exp.cycles if c.visible)
            exp_iid = self.tree_curves.insert(
                "", ttk.END, text=exp.name, values=(f"{n_vis}/{len(exp.cycles)} 👁",), open=True
            )
            self._tree_ref[exp_iid] = ("exp", exp)
            for c in exp.cycles:
                mark = "👁" if c.visible else "🚫"
                ciid = self.tree_curves.insert(exp_iid, ttk.END, text=c.name, values=(mark,))
                self._tree_ref[ciid] = ("run", exp, c)

    def _set_status(self, msg):
        self.lbl_status.configure(text=msg)

    # ----------------------------------------------------- Dibujo + tabla
    def _redraw(self):
        """Recrea el canvas, dibuja las curvas visibles (filtradas si hay filtro) con
        sus picos marcados/anotados, y reconstruye la tabla de resultados. NO detecta:
        usa los picos ya almacenados en cada curva (max_points / min_points)."""
        kind = self.filter_var.get()
        fw = max(1, self.filter_window_var.get() or 1)
        self._reset_plot_canvas()
        self.tree_res.delete(*self.tree_res.get_children())
        self._res_ref = {}

        any_visible = False
        all_max, all_min = [], []
        for exp in self.experiments:
            vis = [c for c in exp.cycles if c.visible]
            if not vis:
                continue
            exp_iid = self.tree_res.insert(
                "", ttk.END, text=exp.name, values=("experiment", "", ""), open=True
            )
            self._res_ref[exp_iid] = ("exp", exp)
            for c in vis:
                ys_disp = _apply_filter(c.ys, kind, fw) if kind != "none" else c.ys
                self.ax_overlay.plot(
                    c.xs, ys_disp, linewidth=1.2, marker=".", markersize=2,
                    label=f"{exp.name}/{c.name}",
                )
                any_visible = True
                for x, y in c.max_points:
                    all_max.append((x, y))
                    riid = self.tree_res.insert(
                        exp_iid, ttk.END, text=c.name,
                        values=("max", f"{x:.6g}", f"{y:.6g}"),
                    )
                    self._res_ref[riid] = ("peak", exp, c, "max", (x, y))
                for x, y in c.min_points:
                    all_min.append((x, y))
                    riid = self.tree_res.insert(
                        exp_iid, ttk.END, text=c.name,
                        values=("min", f"{x:.6g}", f"{y:.6g}"),
                    )
                    self._res_ref[riid] = ("peak", exp, c, "min", (x, y))
        if all_max:
            xs, ys = zip(*all_max)
            self.ax_overlay.scatter(xs, ys, marker="^", s=55, color="tab:red", zorder=5)
            for x, y in all_max:
                self.ax_overlay.annotate(
                    f"{x:.3g} V\n{y:.3g} A", (x, y), textcoords="offset points",
                    xytext=(0, 8), ha="center", fontsize=7, color="tab:red",
                )
        if all_min:
            xs, ys = zip(*all_min)
            self.ax_overlay.scatter(xs, ys, marker="v", s=55, color="tab:blue", zorder=5)
            for x, y in all_min:
                self.ax_overlay.annotate(
                    f"{x:.3g} V\n{y:.3g} A", (x, y), textcoords="offset points",
                    xytext=(0, -16), ha="center", fontsize=7, color="tab:blue",
                )
        if any_visible:
            leg = self.ax_overlay.legend(loc="best", fontsize=7, ncol=2)
            if leg is not None:
                leg.set_visible(self._legend_visible)
        self.canvas.draw_idle()

    # -------------------------------------------------------- Renombrado
    def _begin_rename(self, event):
        """Editor in-place sobre la columna #0 (mismo patrón que PeakAnalysisFrame):
        renombra experimento/corrida y refresca leyenda. Funciona en ambos árboles."""
        self._cancel_rename()
        tree = event.widget
        ref_map = self._tree_ref if tree is self.tree_curves else self._res_ref
        iid = tree.identify_row(event.y)
        if not iid or iid not in ref_map:
            return
        if tree.identify_column(event.x) != "#0":
            return
        ref = ref_map[iid]
        if ref[0] == "peak":  # las filas de pico no se renombran
            return
        bbox = tree.bbox(iid, "#0")
        if not bbox:
            return
        x, y, w, h = bbox
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
        self._refresh_tree()
        self._redraw()
        self._set_status(f"Renamed to '{new_name}'.")

    def _cancel_rename(self):
        entry = self._rename_entry
        self._rename_entry = None
        if entry is not None:
            try:
                entry.destroy()
            except Exception:
                pass

    # --------------------------------------------------------- Acciones
    def _selected_refs(self):
        return [self._tree_ref[i] for i in self.tree_curves.selection() if i in self._tree_ref]

    def remove_selected(self):
        refs = self._selected_refs()
        if not refs:
            return
        exps_to_drop = set()
        runs_to_drop = []
        for ref in refs:
            if ref[0] == "exp":
                exps_to_drop.add(id(ref[1]))
            else:
                runs_to_drop.append((ref[1], ref[2]))
        for exp, c in runs_to_drop:
            if id(exp) in exps_to_drop:
                continue
            if c in exp.cycles:
                exp.cycles.remove(c)
        self.experiments = [e for e in self.experiments if id(e) not in exps_to_drop and e.cycles]
        self._refresh_tree()
        self._redraw()
        self._set_status(f"Removed {len(exps_to_drop)} experiment(s), {len(runs_to_drop)} run(s).")

    def toggle_visibility(self):
        refs = self._selected_refs()
        if not refs:
            return
        for ref in refs:
            if ref[0] == "exp":
                target = not ref[1].is_visible
                ref[1].set_visible(target)
            else:
                ref[2].visible = not ref[2].visible
        self._refresh_tree()
        self._redraw()

    def compute_peaks(self):
        """Detecta picos (decisión Q10: borra los previos y re-detecta de cero; la
        edición manual es un retoque posterior). Corre sobre datos filtrados."""
        direction = self.direction_var.get()
        pwin = max(1, self.peak_window_var.get() or 1)
        prom_frac = max(0.0, float(self.prominence_var.get() or 0.0)) / 100.0
        fkind = self.filter_var.get()
        fwin = max(1, self.filter_window_var.get() or 1)
        n_curves = 0
        n_peaks = 0
        for exp in self.experiments:
            for c in exp.cycles:
                if not c.visible:
                    c.max_points, c.min_points = [], []
                    continue
                ys_f = _apply_filter(c.ys, fkind, fwin) if fkind != "none" else c.ys
                c.ys_filtered = ys_f
                maxs, mins = _detect_peaks(c.xs, ys_f, direction, pwin, prom_frac)
                c.max_points, c.min_points = maxs, mins
                n_curves += 1
                n_peaks += len(maxs) + len(mins)
        self._redraw()
        self._set_status(
            f"Detected {n_peaks} peak(s) on {n_curves} run(s) — dir={direction}, "
            f"prom={self.prominence_var.get():g}%, filter={fkind}"
            + (f" (w={fwin})" if fkind != "none" else "")
        )

    # ------------------------------------------------ Edición manual de picos
    def _toggle_add_mode(self):
        self._add_mode = not self._add_mode
        if self._add_mode:
            if self._pick_cid is None:
                self._pick_cid = self.canvas.mpl_connect("button_press_event", self._on_add_click)
            self.btn_add.configure(bootstyle="success")
            self._set_status("Add-peak ON: click near a curve point (toolbar pan/zoom must be off).")
        else:
            if self._pick_cid is not None:
                try:
                    self.canvas.mpl_disconnect(self._pick_cid)
                except Exception:
                    pass
                self._pick_cid = None
            self.btn_add.configure(bootstyle="secondary-outline")
            self._set_status("Add-peak OFF.")

    def _nearest_point(self, event):
        """(exp, curve, x, y) del punto medido más cercano (en píxeles) entre las
        curvas visibles del overlay; None si no hay. Mide en transData para no sesgar
        por las escalas dispares de E (V) e I (A)."""
        best = None  # (dist_px, exp, curve, x, y)
        kind = self.filter_var.get()
        fw = max(1, self.filter_window_var.get() or 1)
        for exp in self.experiments:
            for c in exp.cycles:
                if not c.visible or c.xs.size == 0:
                    continue
                ys = _apply_filter(c.ys, kind, fw) if kind != "none" else c.ys
                try:
                    pts = self.ax_overlay.transData.transform(np.column_stack([c.xs, ys]))
                except Exception:
                    continue
                d = np.hypot(pts[:, 0] - event.x, pts[:, 1] - event.y)
                j = int(np.argmin(d))
                if best is None or d[j] < best[0]:
                    best = (float(d[j]), exp, c, float(c.xs[j]), float(ys[j]))
        if best is None:
            return None
        return best[1], best[2], best[3], best[4]

    def _on_add_click(self, event):
        try:
            if getattr(self.toolbar_mpl, "mode", "") not in ("", None):
                return
        except Exception:
            pass
        if event.inaxes is not self.ax_overlay or event.x is None:
            return
        found = self._nearest_point(event)
        if found is None:
            return
        _exp, c, x, y = found
        # Clasifica como max/min según la forma local alrededor del punto elegido.
        kind = self.filter_var.get()
        fw = max(1, self.filter_window_var.get() or 1)
        ys = _apply_filter(c.ys, kind, fw) if kind != "none" else c.ys
        j = int(np.argmin(np.abs(c.xs - x)))
        w = max(1, self.peak_window_var.get() or 1)
        lo, hi = max(0, j - w), min(len(ys), j + w + 1)
        local_mean = float(np.mean(ys[lo:hi]))
        peak_kind = "max" if y >= local_mean else "min"
        target = c.max_points if peak_kind == "max" else c.min_points
        if not any(abs(px - x) < 1e-12 and abs(py - y) < 1e-30 for px, py in target):
            target.append((x, y))
            target.sort(key=lambda t: t[0])
        self._redraw()
        self._set_status(f"Added {peak_kind} peak at E={x:.4g} V, I={y:.4g} A.")

    def _delete_selected_peaks(self):
        sel = [i for i in self.tree_res.selection() if i in self._res_ref]
        peaks = [self._res_ref[i] for i in sel if self._res_ref[i][0] == "peak"]
        if not peaks:
            self._set_status("Select one or more peak rows in the table to delete.")
            return
        n = 0
        for _tag, _exp, c, kind, (x, y) in peaks:
            lst = c.max_points if kind == "max" else c.min_points
            for k, (px, py) in enumerate(lst):
                if abs(px - x) < 1e-12 and abs(py - y) < 1e-30:
                    lst.pop(k)
                    n += 1
                    break
        self._redraw()
        self._set_status(f"Deleted {n} peak(s).")

    # ------------------------------------------------------------ Hover
    def _on_hover(self, event):
        if event.inaxes is not self.ax_overlay or event.x is None:
            self.lbl_cross.configure(text="")
            return
        best = None
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
                best = (float(d[j]), label, float(xd[j]), float(yd[j]))
        if best is None:
            self.lbl_cross.configure(text="")
            return
        self.lbl_cross.configure(text=f"{best[1]}   E={best[2]:.4g} V   I={best[3]:.4g} A")

    # ------------------------------------------------------------ Legend
    def toggle_legend(self):
        self._legend_visible = not self._legend_visible
        leg = self.ax_overlay.get_legend()
        if leg is not None:
            leg.set_visible(self._legend_visible)
        self.btn_legend.configure(
            text="Legend ON" if self._legend_visible else "Legend OFF",
            bootstyle="secondary" if self._legend_visible else "secondary-outline",
        )
        self.canvas.draw_idle()

    def clear_all(self):
        self.experiments.clear()
        self._tree_ref.clear()
        self._res_ref.clear()
        self.tree_curves.delete(*self.tree_curves.get_children())
        self.tree_res.delete(*self.tree_res.get_children())
        self._reset_plot_canvas()
        self.canvas.draw_idle()
        self._set_status("Cleared.")

    # ------------------------------------------------------ Load / Import
    def load_csv(self):
        """Carga un CSV guardado por EventPlotter.save_data (un archivo = un experimento,
        agrupado por 'run'). Excluye filas de pre-tratamiento (columna 'phase')."""
        path = askopenfilename(
            title="Select SWV CSV (one experiment)",
            initialdir=experiment_dir("sqwv"),
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not path:
            return
        groups = {}  # (run, cycle) → ([xs], [ys])
        try:
            with open(path, newline="") as f:
                reader = csv.reader(f, skipinitialspace=True)
                header = [h.strip() for h in (next(reader, None) or [])]
                col = {name: i for i, name in enumerate(header)}
                xi = col.get("E_V", 1)
                yi = col.get("I_A", 2)
                ci = col.get("cycle", 3)
                ri = col.get("run", 4)
                pi = col.get("phase", None)
                for row in reader:
                    if len(row) <= max(xi, yi):
                        continue
                    if pi is not None and len(row) > pi and row[pi].strip() == "pretreatment":
                        continue
                    try:
                        x = float(row[xi])
                        y = float(row[yi])
                    except (ValueError, IndexError):
                        continue
                    try:
                        cycle = int(float(row[ci])) if len(row) > ci and row[ci].strip() else 0
                    except ValueError:
                        cycle = 0
                    try:
                        run = int(float(row[ri])) if len(row) > ri and row[ri].strip() else 0
                    except ValueError:
                        run = 0
                    groups.setdefault((run, cycle), ([], []))
                    groups[(run, cycle)][0].append(x)
                    groups[(run, cycle)][1].append(y)
        except Exception as e:
            self._set_status(f"Error loading data: {e}")
            return
        if not groups:
            self._set_status("No data parsed from file.")
            return
        exp_name = os.path.splitext(os.path.basename(path))[0]
        exp = Experiment(name=exp_name)
        runs = {r for r, _ in groups}
        for run, cycle in sorted(groups.keys()):
            xs, ys = groups[(run, cycle)]
            name = f"r{run}" if len(runs) == len(groups) else f"r{run}c{cycle}"
            exp.cycles.append(CycleCurve(name=name, xs=xs, ys=ys))
        self.experiments.append(exp)
        self._refresh_tree()
        self._redraw()
        self._set_status(f"Loaded '{exp_name}' with {len(exp.cycles)} run(s).")

    def import_analysis(self):
        """Importa un archivo _curves.csv generado por export_results (espejo de
        PeakAnalysisFrame.import_analysis; agrupa por experiment → run via y_raw)."""
        path = askopenfilename(
            title="Select curves CSV (SWV analysis export)",
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
                groups = {}
                for row in reader:
                    if len(row) <= max(col["x"], col["y_raw"]):
                        continue
                    try:
                        exp_name = row[col["experiment"]].strip()
                        run_name = row[col["run"]].strip()
                        x = float(row[col["x"]])
                        y = float(row[col["y_raw"]])
                    except (ValueError, IndexError, KeyError):
                        continue
                    groups.setdefault(exp_name, {}).setdefault(run_name, ([], []))
                    groups[exp_name][run_name][0].append(x)
                    groups[exp_name][run_name][1].append(y)
        except Exception as e:
            self._set_status(f"Import error: {e}")
            return
        if not groups:
            self._set_status("No data parsed from file.")
            return
        existing = {e.name for e in self.experiments}
        added = 0
        for exp_name, runs in groups.items():
            name = exp_name or "imported"
            suffix = 1
            while name in existing:
                name = f"{exp_name}_{suffix}"
                suffix += 1
            existing.add(name)
            exp = Experiment(name=name)
            for run_name, (xs, ys) in runs.items():
                exp.cycles.append(CycleCurve(name=run_name, xs=xs, ys=ys))
            self.experiments.append(exp)
            added += 1
        self._refresh_tree()
        self._redraw()
        self._set_status(f"Imported {added} experiment(s) from {os.path.basename(path)}.")

    def export_results(self):
        """Exporta dos archivos paralelos (espejo de PeakAnalysisFrame):
        - el path elegido: un pico por fila (experiment, run, type, E_peak, I_peak).
        - "<base>_curves.csv": curvas punto-a-punto (crudo + filtrado) para reimportar.
        """
        rows = []
        for exp in self.experiments:
            for c in exp.cycles:
                if not c.visible:
                    continue
                for x, y in c.max_points:
                    rows.append([exp.name, c.name, "max", f"{x:.9g}", f"{y:.9g}"])
                for x, y in c.min_points:
                    rows.append([exp.name, c.name, "min", f"{x:.9g}", f"{y:.9g}"])
        if not any(c.visible for e in self.experiments for c in e.cycles):
            self._set_status("Nothing to export. Load or seed a run first.")
            return
        path = asksaveasfilename(
            title="Export SWV peaks",
            defaultextension=".csv",
            initialfile=f"sqwv_peaks_{time.strftime('%Y%m%d_%H%M')}.csv",
            filetypes=[("CSV files", "*.csv")],
        )
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["experiment", "run", "type", "E_peak_V", "I_peak_A"])
                w.writerows(rows)
        except Exception as e:
            self._set_status(f"Export error: {e}")
            return

        base, ext = os.path.splitext(path)
        curves_path = f"{base}_curves{ext or '.csv'}"
        fkind = self.filter_var.get()
        fwin = max(1, self.filter_window_var.get() or 1)
        n_pts = 0
        try:
            with open(curves_path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(
                    ["experiment", "run", "point_idx", "x", "y_raw", "y_filtered",
                     "filter", "filter_window"]
                )
                for exp in self.experiments:
                    for c in exp.cycles:
                        if not c.visible:
                            continue
                        ys_f = c.ys_filtered
                        if ys_f is None or len(ys_f) != len(c.ys):
                            ys_f = _apply_filter(c.ys, fkind, fwin) if fkind != "none" else c.ys
                        for i in range(len(c.xs)):
                            w.writerow(
                                [exp.name, c.name, i, f"{c.xs[i]:.9g}", f"{c.ys[i]:.9g}",
                                 f"{ys_f[i]:.9g}", fkind, fwin if fkind != "none" else ""]
                            )
                            n_pts += 1
        except Exception as e:
            self._set_status(f"Peaks exported, but error writing curves file: {e}")
            return
        self._set_status(
            f"Exported {len(rows)} peak(s) → {os.path.basename(path)}; "
            f"{n_pts} curve point(s) → {os.path.basename(curves_path)}."
        )


__author__ = "Edisson A. Naula"
__date__ = "2026-07-03"
