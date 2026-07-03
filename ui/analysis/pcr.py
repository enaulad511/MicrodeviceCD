# -*- coding: utf-8 -*-
import csv
import os
import time
from tkinter.filedialog import askopenfilename, asksaveasfilename

import numpy as np
import ttkbootstrap as ttk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

from templates.utils import experiment_dir
from ui.analysis.common import plt


# ---------------------------------------------------------------------------
# Modelo de datos (PCR)
# ---------------------------------------------------------------------------
class PcrSegment:
    """Un tramo de dos puntos (por índice de muestra) sobre la curva de temperatura.

    La tasa se deriva con el dt global de la pestaña: rate = ΔT / (Δidx·dt) [°C/s].
    Signo positivo → calentamiento; negativo → enfriamiento (clasificación por signo,
    decisión Q7).
    """

    def __init__(self, ia, ib):
        self.ia = int(ia)
        self.ib = int(ib)


class PcrExperiment:
    """Una corrida PCR: serie de temperatura (densa) + fotodetector por ciclo.

    La temperatura guardada por PcrFrame no lleva eje temporal (solo muestras); aquí
    el tiempo se sintetiza con el dt global (X = idx·dt, decisión Q1). Los segmentos de
    tasa se pican a mano sobre la curva de temperatura y se guardan como pares de índices.
    """

    def __init__(self, name, temps, photo=None):
        self.name = name
        self.temps = np.asarray(temps, dtype=float)
        self.photo = np.asarray(photo if photo is not None else [], dtype=float)
        self.visible = True
        self.segments = []  # list[PcrSegment]

    def seg_metrics(self, seg, dt):
        """(t_a, t_b, T_a, T_b, dT, dt_s, rate) o None si los índices no son válidos."""
        n = self.temps.size
        ia, ib = seg.ia, seg.ib
        if n == 0 or not (0 <= ia < n) or not (0 <= ib < n) or ia == ib:
            return None
        t_a, t_b = ia * dt, ib * dt
        t_from, t_to = float(self.temps[ia]), float(self.temps[ib])
        d_temp = t_to - t_from
        d_time = (ib - ia) * dt
        rate = d_temp / d_time if d_time != 0 else float("nan")
        return (t_a, t_b, t_from, t_to, d_temp, d_time, rate)


# ---------------------------------------------------------------------------
# Pestaña: análisis PCR (temperatura + fotodetector · tasas de calentamiento/enfriamiento)
# ---------------------------------------------------------------------------
class PcrAnalysisFrame(ttk.Frame):
    """Pestaña de análisis PCR: carga corridas guardadas por PcrFrame (temperatura +
    fotodetector) o siembra la corrida en memoria, dibuja las curvas y mide tasas de
    calentamiento/enfriamiento picando dos puntos sobre la curva de temperatura.

    Cuatro ejes apilados (temperatura, fotodetector, tasa de calentamiento, tasa de
    enfriamiento) dentro del área con scroll vertical, igual que las otras pestañas.
    """

    def __init__(self, master, owner, plotter=None, pcr_frame=None, **kwargs):
        super().__init__(master, **kwargs)
        self.owner = owner
        self.experiments = []  # list[PcrExperiment]
        self._tree_ref = {}  # iid árbol izq → ("exp", exp)
        self._res_ref = {}  # iid tabla → ("exp", exp) | ("seg", exp, seg)
        self._legend_visible = True
        self._add_mode = False  # captura de clics para añadir segmentos
        self._pick_cid: int | None = None
        self._pending_ia: int | None = None  # primer punto de un segmento pendiente
        self._pending_exp: "PcrExperiment | None" = None
        self._temp_lines = {}  # id(exp) → Line2D (para snapping del pick)
        self._rename_entry: "ttk.Entry | None" = None

        self._build_ui()
        self.dt_var.set(f"{self._default_dt():.9g}")
        # Siembra: corrida PCR en memoria (data_temperature / data_photodetector).
        # pcr_frame es None cuando la ventana se abre desde electroquímica.
        if pcr_frame is not None:
            self._seed_from_pcr(pcr_frame)
        self._refresh_tree()
        self._redraw()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        # --- Toolbar fila 1: archivo (izq) + globales (der) ---
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

        # --- Toolbar fila 1b: acciones sobre experimentos ---
        toolbar_b = ttk.Frame(self)
        toolbar_b.pack(side=ttk.TOP, fill=ttk.X, padx=6, pady=(0, 2))
        ttk.Button(
            toolbar_b, text="🗑 Remove exp", bootstyle="danger", command=self.remove_selected
        ).pack(side=ttk.LEFT, padx=3)
        ttk.Button(
            toolbar_b, text="👁 Show/Hide", bootstyle="info", command=self.toggle_visibility
        ).pack(side=ttk.LEFT, padx=3)

        # --- Toolbar fila 2: dt global + edición de segmentos ---
        toolbar2 = ttk.Frame(self)
        toolbar2.pack(side=ttk.TOP, fill=ttk.X, padx=6, pady=(0, 6))
        ttk.Label(toolbar2, text="Sampling dt (s):").pack(side=ttk.LEFT, padx=(0, 4))
        self.dt_var = ttk.StringVar(value="0.05")
        dt_entry = ttk.Entry(toolbar2, textvariable=self.dt_var, width=8)
        dt_entry.pack(side=ttk.LEFT)
        dt_entry.bind("<Return>", lambda _e: self._redraw())
        ttk.Button(
            toolbar2, text="↻ Apply dt", bootstyle="secondary-outline", command=self._redraw
        ).pack(side=ttk.LEFT, padx=(4, 0))

        ttk.Separator(toolbar2, orient=ttk.VERTICAL).pack(side=ttk.LEFT, fill=ttk.Y, padx=8)

        self.btn_add = ttk.Button(
            toolbar2,
            text="➕ Add segment",
            bootstyle="secondary-outline",
            command=self._toggle_add_mode,
        )
        self.btn_add.pack(side=ttk.LEFT, padx=3)
        ttk.Button(
            toolbar2, text="➖ Remove segment", bootstyle="warning-outline", command=self.remove_segment
        ).pack(side=ttk.LEFT, padx=3)
        ttk.Button(
            toolbar2, text="🧹 Clear segments", bootstyle="warning-outline", command=self.clear_segments
        ).pack(side=ttk.LEFT, padx=3)

        # Lectura por hover (tiempo / temperatura del eje de temperatura).
        self.lbl_cross = ttk.Label(toolbar2, text="", anchor="e")
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

        left = ttk.LabelFrame(main, text="Experiments (double-click to rename)")
        main.add(left, weight=1)
        self.tree_curves = ttk.Treeview(
            left, columns=("info",), show="tree headings", selectmode="extended"
        )
        self.tree_curves.heading("#0", text="Experiment")
        self.tree_curves.heading("info", text="State")
        self.tree_curves.column("#0", width=240, anchor="w")
        self.tree_curves.column("info", width=120, anchor="w")
        vsb_c = ttk.Scrollbar(left, orient="vertical", command=self.tree_curves.yview)
        self.tree_curves.configure(yscrollcommand=vsb_c.set)
        self.tree_curves.pack(side=ttk.LEFT, fill=ttk.BOTH, expand=True, padx=4, pady=4)
        vsb_c.pack(side=ttk.LEFT, fill=ttk.Y)
        self.tree_curves.bind("<Double-1>", self._begin_rename)

        right = ttk.Frame(main)
        main.add(right, weight=4)
        right.bind("<MouseWheel>", _on_wheel)
        plt.style.use("seaborn-v0_8-darkgrid")
        self._plot_host = right
        self._create_plot_canvas()

        # --- Tabla de resultados (un segmento por fila + agregados por experimento) ---
        bottom = ttk.LabelFrame(inner, text="Rate segments (visible only)")
        bottom.pack(fill=ttk.BOTH, pady=(0, 6))
        cols_r = ("type", "dtemp", "dtime", "rate")
        self.tree_res = ttk.Treeview(bottom, columns=cols_r, show="tree headings", height=12)
        self.tree_res.heading("#0", text="Experiment / Segment")
        self.tree_res.column("#0", width=300, anchor="w")
        heads = {"type": "Type", "dtemp": "ΔT (°C)", "dtime": "Δt (s)", "rate": "Rate (°C/s)"}
        widths = {"type": 90, "dtemp": 110, "dtime": 110, "rate": 150}
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
        # Figura alta (6 ejes apilados) para que el área con scroll vertical del
        # contenedor haga scroll en la pantalla pequeña del Pi (decisión Q8). Los
        # dos ejes de "slices extraídos" (calentamiento/enfriamiento) van entre el
        # fotodetector y las tasas.
        self.fig = Figure(figsize=(7, 17), dpi=100, layout="constrained")
        gs = self.fig.add_gridspec(6, 1, height_ratios=[3, 2, 2, 2, 2, 2])
        self.ax_temp = self.fig.add_subplot(gs[0])
        self.ax_photo = self.fig.add_subplot(gs[1])
        self.ax_ext_heat = self.fig.add_subplot(gs[2])
        self.ax_ext_cool = self.fig.add_subplot(gs[3])
        self.ax_heat = self.fig.add_subplot(gs[4])
        self.ax_cool = self.fig.add_subplot(gs[5])
        self.ax_temp.set_title("Temperature (°C) — click-pick two points to add a segment")
        self.ax_temp.set_xlabel("Time (s)")
        self.ax_temp.set_ylabel("°C")
        self.ax_temp.grid(True)
        self.ax_photo.set_title("Photodetector (Δ V) vs cycle")
        self.ax_photo.set_xlabel("Cycle")
        self.ax_photo.set_ylabel("Δ V")
        self.ax_photo.grid(True)
        self.ax_ext_heat.set_title("Extracted heating slices (T vs time from A)")
        self.ax_ext_heat.set_xlabel("Time from start of segment (s)")
        self.ax_ext_heat.set_ylabel("°C")
        self.ax_ext_heat.grid(True)
        self.ax_ext_cool.set_title("Extracted cooling slices (T vs time from A)")
        self.ax_ext_cool.set_xlabel("Time from start of segment (s)")
        self.ax_ext_cool.set_ylabel("°C")
        self.ax_ext_cool.grid(True)
        self.ax_heat.set_title("Heating rate (°C/s)")
        self.ax_heat.set_xlabel("Experiment")
        self.ax_heat.set_ylabel("°C/s")
        self.ax_heat.grid(True)
        self.ax_cool.set_title("Cooling rate (°C/s)")
        self.ax_cool.set_xlabel("Experiment")
        self.ax_cool.set_ylabel("°C/s")
        self.ax_cool.grid(True)
        self.canvas = FigureCanvasTkAgg(self.fig, self._plot_host)
        self.canvas.get_tk_widget().pack(fill=ttk.BOTH, expand=True)
        self.toolbar_mpl = NavigationToolbar2Tk(self.canvas, self._plot_host, pack_toolbar=False)
        self.toolbar_mpl.pack(fill=ttk.X)
        self.canvas.mpl_connect("motion_notify_event", self._on_hover)
        # Re-arma la captura de clics si "Add segment" seguía activo (el canvas se
        # recrea en cada redibujo, invalidando el cid anterior).
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
    def _seed_from_pcr(self, pcr):
        """Siembra la corrida PCR en memoria como un experimento (decisión Q3)."""
        try:
            temps = list(getattr(pcr, "data_temperature", []) or [])
            photo = list(getattr(pcr, "data_photodetector", []) or [])
        except Exception:
            return
        if not temps and not photo:
            return
        base = getattr(pcr, "active_project_name", None) or "last_run"
        name = self._unique_name(f"{base} (live)")
        self.experiments.append(PcrExperiment(name=name, temps=temps, photo=photo))

    def _default_dt(self):
        # dt por defecto: ts del lazo PCR en settings.json (decisión Q1); editable.
        try:
            from templates.utils import read_settings_from_file

            settings = read_settings_from_file()
            v = float(settings.get("pidControllerRPM", {}).get("ts_pcr", 0.05))
            return v if v > 0 else 0.05
        except Exception:
            return 0.05

    def _dt(self):
        try:
            v = float(self.dt_var.get())
            return v if v > 0 else 0.05
        except (ValueError, TypeError):
            return 0.05

    def _unique_name(self, name):
        existing = {e.name for e in self.experiments}
        if name not in existing:
            return name
        i = 1
        while f"{name}_{i}" in existing:
            i += 1
        return f"{name}_{i}"

    def _refresh_tree(self):
        self.tree_curves.delete(*self.tree_curves.get_children())
        self._tree_ref = {}
        for exp in self.experiments:
            mark = "👁" if exp.visible else "🚫"
            info = f"{exp.temps.size}t · {exp.photo.size}c {mark}"
            iid = self.tree_curves.insert("", ttk.END, text=exp.name, values=(info,))
            self._tree_ref[iid] = ("exp", exp)

    def _set_status(self, msg):
        self.lbl_status.configure(text=msg)

    # ----------------------------------------------------- Dibujo + tabla
    def _redraw(self):
        """Recrea el canvas y redibuja los 4 ejes + la tabla de segmentos/tasas."""
        self._reset_plot_canvas()
        dt = self._dt()
        self._temp_lines = {}

        # --- Eje 1: temperatura + segmentos ---
        any_t = False
        for exp in self.experiments:
            if not exp.visible or exp.temps.size == 0:
                continue
            xs = np.arange(exp.temps.size) * dt
            (line,) = self.ax_temp.plot(xs, exp.temps, linewidth=1.0, label=exp.name)
            self._temp_lines[id(exp)] = line
            any_t = True
            for seg in exp.segments:
                m = exp.seg_metrics(seg, dt)
                if m is None:
                    continue
                t_a, t_b, T_a, T_b, _dT, _dts, rate = m
                col = "tab:red" if rate >= 0 else "tab:blue"
                self.ax_temp.plot([t_a, t_b], [T_a, T_b], color=col, linewidth=2.2, alpha=0.9, zorder=5)
                self.ax_temp.scatter([t_a, t_b], [T_a, T_b], color=col, s=28, zorder=6)
        # Marcador del punto A pendiente (primer clic a la espera del segundo).
        if (
            self._pending_ia is not None
            and self._pending_exp is not None
            and self._pending_exp.visible
            and 0 <= self._pending_ia < self._pending_exp.temps.size
        ):
            xa = self._pending_ia * dt
            ya = float(self._pending_exp.temps[self._pending_ia])
            self.ax_temp.scatter([xa], [ya], marker="x", color="black", s=90, zorder=7)
        if any_t:
            leg = self.ax_temp.legend(loc="best", fontsize=7, ncol=2)
            if leg is not None:
                leg.set_visible(self._legend_visible)

        # --- Eje 2: fotodetector (delta por ciclo) ---
        any_p = False
        for exp in self.experiments:
            if not exp.visible or exp.photo.size == 0:
                continue
            xs = np.arange(1, exp.photo.size + 1)
            self.ax_photo.plot(xs, exp.photo, marker="o", markersize=3, linewidth=1.0, label=exp.name)
            any_p = True
        if any_p:
            leg = self.ax_photo.legend(loc="best", fontsize=7, ncol=2)
            if leg is not None:
                leg.set_visible(self._legend_visible)

        # --- Ejes 3 y 4: slices extraídos (real, tiempo re-zeroado a A) ---
        self._draw_extracted(dt)

        # --- Ejes 5 y 6: tasas + tabla ---
        self._draw_rates_and_table(dt)
        self.canvas.draw_idle()

    def _draw_extracted(self, dt):
        """Dibuja el corte real de temperatura de cada segmento (temps[lo:hi+1]) con el
        tiempo re-zeroado al punto A, separando calentamiento y enfriamiento en dos ejes.
        Color por índice de segmento (ciclado); leyenda 'exp/segK/rate' (decisión Q5)."""
        gi = 0  # índice global de segmento → color
        any_h = any_c = False
        for exp in self.experiments:
            if not exp.visible or exp.temps.size == 0:
                continue
            for k, seg in enumerate(exp.segments, start=1):
                m = exp.seg_metrics(seg, dt)
                if m is None:
                    continue
                rate = m[6]
                lo, hi = (seg.ia, seg.ib) if seg.ia <= seg.ib else (seg.ib, seg.ia)
                ys = exp.temps[lo : hi + 1]
                xs = (np.arange(lo, hi + 1) - lo) * dt
                color = f"C{gi % 10}"
                gi += 1
                label = f"{exp.name}/seg{k} {rate:.3g}"
                if rate >= 0:
                    self.ax_ext_heat.plot(xs, ys, color=color, linewidth=1.4, label=label)
                    any_h = True
                else:
                    self.ax_ext_cool.plot(xs, ys, color=color, linewidth=1.4, label=label)
                    any_c = True
        if any_h:
            leg = self.ax_ext_heat.legend(loc="best", fontsize=7, ncol=2)
            if leg is not None:
                leg.set_visible(self._legend_visible)
        if any_c:
            leg = self.ax_ext_cool.legend(loc="best", fontsize=7, ncol=2)
            if leg is not None:
                leg.set_visible(self._legend_visible)

    def _draw_rates_and_table(self, dt):
        self.tree_res.delete(*self.tree_res.get_children())
        self._res_ref = {}
        heat_sx, heat_sy, cool_sx, cool_sy = [], [], [], []
        heat_mx, heat_m, heat_s = [], [], []
        cool_mx, cool_m, cool_s = [], [], []
        xticks, xlabels = [], []

        exp_idx = 0
        for exp in self.experiments:
            if not exp.visible:
                continue
            exp_idx += 1
            xticks.append(exp_idx)
            xlabels.append(exp.name)
            heats, cools = [], []
            exp_iid = self.tree_res.insert(
                "", ttk.END, text=exp.name, values=("experiment", "", "", ""), open=True
            )
            self._res_ref[exp_iid] = ("exp", exp)
            for k, seg in enumerate(exp.segments, start=1):
                m = exp.seg_metrics(seg, dt)
                if m is None:
                    riid = self.tree_res.insert(
                        exp_iid, ttk.END, text=f"seg{k} [{seg.ia}→{seg.ib}]",
                        values=("invalid", "", "", ""),
                    )
                    self._res_ref[riid] = ("seg", exp, seg)
                    continue
                _t_a, _t_b, _T_a, _T_b, d_temp, d_time, rate = m
                if rate >= 0:
                    typ = "heating"
                    heats.append(rate)
                    heat_sx.append(exp_idx)
                    heat_sy.append(rate)
                else:
                    typ = "cooling"
                    cools.append(rate)
                    cool_sx.append(exp_idx)
                    cool_sy.append(rate)
                riid = self.tree_res.insert(
                    exp_iid, ttk.END, text=f"seg{k} [{seg.ia}→{seg.ib}]",
                    values=(typ, f"{d_temp:.3g}", f"{d_time:.3g}", f"{rate:.4g}"),
                )
                self._res_ref[riid] = ("seg", exp, seg)
            if heats:
                hm, hs = float(np.mean(heats)), float(np.std(heats))
                heat_mx.append(exp_idx)
                heat_m.append(hm)
                heat_s.append(hs)
                self.tree_res.insert(
                    exp_iid, ttk.END, text="⟨heating⟩",
                    values=("mean", "", "", f"{hm:.4g} ± {hs:.2g}"),
                )
            if cools:
                cm, cs = float(np.mean(cools)), float(np.std(cools))
                cool_mx.append(exp_idx)
                cool_m.append(cm)
                cool_s.append(cs)
                self.tree_res.insert(
                    exp_iid, ttk.END, text="⟨cooling⟩",
                    values=("mean", "", "", f"{cm:.4g} ± {cs:.2g}"),
                )

        # Scatter de cada segmento + media±std por experimento (decisión Q8).
        if heat_sx:
            self.ax_heat.scatter(heat_sx, heat_sy, color="tab:red", alpha=0.45, s=30, label="segments")
        if heat_mx:
            self.ax_heat.errorbar(
                heat_mx, heat_m, yerr=heat_s, marker="o", linestyle="-",
                color="tab:red", capsize=4, label="mean ± std",
            )
        if cool_sx:
            self.ax_cool.scatter(cool_sx, cool_sy, color="tab:blue", alpha=0.45, s=30, label="segments")
        if cool_mx:
            self.ax_cool.errorbar(
                cool_mx, cool_m, yerr=cool_s, marker="o", linestyle="-",
                color="tab:blue", capsize=4, label="mean ± std",
            )
        if xticks:
            for ax in (self.ax_heat, self.ax_cool):
                ax.set_xticks(xticks)
                ax.set_xticklabels(xlabels, rotation=20, ha="right", fontsize=7)
        if heat_sx or heat_mx:
            self.ax_heat.legend(fontsize=7)
        if cool_sx or cool_mx:
            self.ax_cool.legend(fontsize=7)

    # ----------------------------------------------------- Picking segmentos
    def _toggle_add_mode(self):
        self._add_mode = not self._add_mode
        if self._add_mode:
            self._pending_ia = None
            self._pending_exp = None
            if self._pick_cid is None:
                self._pick_cid = self.canvas.mpl_connect("button_press_event", self._on_add_click)
            self.btn_add.configure(bootstyle="success")
            self._set_status(
                "Add-segment ON: select ONE experiment in the tree, then click two "
                "points on the temperature plot (toolbar pan/zoom must be off)."
            )
        else:
            if self._pick_cid is not None:
                try:
                    self.canvas.mpl_disconnect(self._pick_cid)
                except Exception:
                    pass
                self._pick_cid = None
            self._pending_ia = None
            self._pending_exp = None
            self.btn_add.configure(bootstyle="secondary-outline")
            self._set_status("Add-segment OFF.")
            self._redraw()

    def _pick_target_exp(self):
        """Experimento sobre el que picar: el único seleccionado en el árbol, o el
        único cargado si no hay selección. None si es ambiguo."""
        exps = [r[1] for r in self._selected_refs() if r[0] == "exp"]
        if len(exps) == 1:
            return exps[0]
        vis = [e for e in self.experiments if e.visible and e.temps.size]
        if len(vis) == 1:
            return vis[0]
        return None

    def _nearest_temp_index(self, exp, event):
        n = exp.temps.size
        if n == 0:
            return None
        xs = np.arange(n) * self._dt()
        try:
            pts = self.ax_temp.transData.transform(np.column_stack([xs, exp.temps]))
        except Exception:
            return None
        d = np.hypot(pts[:, 0] - event.x, pts[:, 1] - event.y)
        return int(np.argmin(d))

    def _on_add_click(self, event):
        try:
            if getattr(self.toolbar_mpl, "mode", "") not in ("", None):
                return
        except Exception:
            pass
        if event.inaxes is not self.ax_temp or event.x is None:
            return
        exp = self._pick_target_exp()
        if exp is None:
            self._set_status("Select exactly one experiment in the tree first.")
            return
        idx = self._nearest_temp_index(exp, event)
        if idx is None:
            return
        if self._pending_ia is None or self._pending_exp is not exp:
            self._pending_ia = idx
            self._pending_exp = exp
            self._set_status(f"Point A at sample {idx} of '{exp.name}'. Click point B.")
            self._redraw()
            return
        ia = self._pending_ia
        self._pending_ia = None
        self._pending_exp = None
        if idx == ia:
            self._set_status("Point B equals A; segment discarded.")
            self._redraw()
            return
        exp.segments.append(PcrSegment(ia, idx))
        m = exp.seg_metrics(exp.segments[-1], self._dt())
        rate = m[6] if m else float("nan")
        typ = "heating" if rate >= 0 else "cooling"
        self._redraw()
        self._set_status(f"Added {typ} segment on '{exp.name}': {rate:.4g} °C/s.")

    def _on_hover(self, event):
        if event.inaxes is not self.ax_temp or event.xdata is None:
            self.lbl_cross.configure(text="")
            return
        self.lbl_cross.configure(text=f"t={event.xdata:.4g} s   T={event.ydata:.4g} °C")

    # -------------------------------------------------------- Renombrado
    def _begin_rename(self, event):
        """Editor in-place sobre la columna #0 (mismo patrón que las otras pestañas):
        solo renombra experimentos (las filas de segmento/agregado no)."""
        self._cancel_rename()
        tree = event.widget
        ref_map = self._tree_ref if tree is self.tree_curves else self._res_ref
        iid = tree.identify_row(event.y)
        if not iid or iid not in ref_map:
            return
        if tree.identify_column(event.x) != "#0":
            return
        ref = ref_map[iid]
        if ref[0] != "exp":
            return
        bbox = tree.bbox(iid, "#0")
        if not bbox:
            return
        x, y, w, h = bbox
        entry = ttk.Entry(tree)
        entry.insert(0, ref[1].name)
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
        if ref[0] != "exp" or ref[1].name == new_name:
            return
        ref[1].name = new_name
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
        exps = {id(r[1]) for r in self._selected_refs() if r[0] == "exp"}
        if not exps:
            self._set_status("Select experiment(s) to remove.")
            return
        self.experiments = [e for e in self.experiments if id(e) not in exps]
        if self._pending_exp is not None and id(self._pending_exp) in exps:
            self._pending_ia = None
            self._pending_exp = None
        self._refresh_tree()
        self._redraw()
        self._set_status(f"Removed {len(exps)} experiment(s).")

    def toggle_visibility(self):
        refs = self._selected_refs()
        if not refs:
            return
        for ref in refs:
            if ref[0] == "exp":
                ref[1].visible = not ref[1].visible
        self._refresh_tree()
        self._redraw()

    def remove_segment(self):
        to_drop = []
        for iid in self.tree_res.selection():
            ref = self._res_ref.get(iid)
            if ref and ref[0] == "seg":
                to_drop.append((ref[1], ref[2]))
        if not to_drop:
            self._set_status("Select segment row(s) in the results table to remove.")
            return
        for exp, seg in to_drop:
            if seg in exp.segments:
                exp.segments.remove(seg)
        self._redraw()
        self._set_status(f"Removed {len(to_drop)} segment(s).")

    def clear_segments(self):
        exps = [r[1] for r in self._selected_refs() if r[0] == "exp"]
        targets = exps if exps else self.experiments
        n = sum(len(e.segments) for e in targets)
        for e in targets:
            e.segments.clear()
        self._pending_ia = None
        self._pending_exp = None
        self._redraw()
        scope = f"{len(exps)} experiment(s)" if exps else "all experiments"
        self._set_status(f"Cleared {n} segment(s) from {scope}.")

    def toggle_legend(self):
        self._legend_visible = not self._legend_visible
        for ax in (self.ax_temp, self.ax_photo, self.ax_ext_heat, self.ax_ext_cool):
            leg = ax.get_legend()
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
        self._pending_ia = None
        self._pending_exp = None
        self.tree_curves.delete(*self.tree_curves.get_children())
        self.tree_res.delete(*self.tree_res.get_children())
        self._reset_plot_canvas()
        self.canvas.draw_idle()
        self._set_status("Cleared.")

    # --------------------------------------------------------- Carga CSV
    def _read_temp_csv(self, path):
        """Serie de temperatura: primera fila = prefijo/metadatos (se salta), luego
        un valor por fila (decisión Q5/executive: el prefijo no se parsea)."""
        vals = []
        try:
            with open(path, newline="") as f:
                reader = csv.reader(f, skipinitialspace=True)
                next(reader, None)  # prefijo (self.prefix_row de PcrFrame)
                for row in reader:
                    if not row:
                        continue
                    try:
                        vals.append(float(row[0]))
                    except (ValueError, TypeError):
                        continue
        except Exception as e:
            self._set_status(f"Error loading temperature: {e}")
            return None
        return vals

    def _read_photo_csv(self, path):
        vals = []
        try:
            with open(path, newline="") as f:
                reader = csv.reader(f, skipinitialspace=True)
                next(reader, None)  # header "photodetector"
                for row in reader:
                    if not row:
                        continue
                    try:
                        vals.append(float(row[0]))
                    except (ValueError, TypeError):
                        continue
        except Exception:
            return None
        return vals

    def load_csv(self):
        """Carga la corrida: se elige el *_temperature_data_*.csv y se busca el hermano
        *_photodetector_data_*.csv en la misma carpeta (decisión Q5)."""
        path = askopenfilename(
            title="Select PCR temperature CSV",
            initialdir=experiment_dir("pcr"),
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not path:
            return
        temps = self._read_temp_csv(path)
        if temps is None:
            return
        if not temps:
            self._set_status("No temperature data parsed from file.")
            return
        base = os.path.basename(path)
        photo = []
        photo_note = ""
        if "temperature_data" in base:
            cand = os.path.join(
                os.path.dirname(path), base.replace("temperature_data", "photodetector_data")
            )
            if os.path.exists(cand):
                photo = self._read_photo_csv(cand) or []
                photo_note = f"; photo {len(photo)} cyc"
            else:
                photo_note = "; no photo sibling"
        name = self._unique_name(os.path.splitext(base)[0].replace("_temperature_data", ""))
        self.experiments.append(PcrExperiment(name=name, temps=temps, photo=photo))
        self._refresh_tree()
        self._redraw()
        self._set_status(f"Loaded '{name}' ({len(temps)} temp samples{photo_note}).")

    # --------------------------------------------------------- Export / Import
    def export_results(self):
        """Exporta un bundle re-importable (temperatura + fotodetector + dt + segmentos)
        y un resumen de tasas legible aparte (decisión Q10)."""
        if not self.experiments:
            self._set_status("Nothing to export.")
            return
        path = asksaveasfilename(
            title="Export PCR analysis",
            defaultextension=".csv",
            initialfile=f"pcr_analysis_{time.strftime('%Y%m%d_%H%M')}.csv",
            filetypes=[("CSV files", "*.csv")],
        )
        if not path:
            return
        dt = self._dt()
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["record", "experiment", "i", "a", "b", "value"])
                w.writerow(["dt", "", "", "", "", f"{dt:.9g}"])
                for exp in self.experiments:
                    for i, v in enumerate(exp.temps):
                        w.writerow(["temp", exp.name, i, "", "", f"{v:.9g}"])
                    for i, v in enumerate(exp.photo):
                        w.writerow(["photo", exp.name, i, "", "", f"{v:.9g}"])
                    for seg in exp.segments:
                        w.writerow(["segment", exp.name, "", seg.ia, seg.ib, ""])
        except Exception as e:
            self._set_status(f"Export error: {e}")
            return

        base, ext = os.path.splitext(path)
        rates_path = f"{base}_rates{ext or '.csv'}"
        try:
            with open(rates_path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(
                    [
                        "experiment", "segment", "type", "t_a_s", "t_b_s",
                        "T_a_C", "T_b_C", "dT_C", "dt_s", "rate_C_per_s",
                    ]
                )
                for exp in self.experiments:
                    heats, cools = [], []
                    for k, seg in enumerate(exp.segments, start=1):
                        m = exp.seg_metrics(seg, dt)
                        if m is None:
                            continue
                        t_a, t_b, T_a, T_b, d_temp, d_time, rate = m
                        typ = "heating" if rate >= 0 else "cooling"
                        (heats if rate >= 0 else cools).append(rate)
                        w.writerow(
                            [
                                exp.name, f"seg{k}", typ, f"{t_a:.6g}", f"{t_b:.6g}",
                                f"{T_a:.6g}", f"{T_b:.6g}", f"{d_temp:.6g}",
                                f"{d_time:.6g}", f"{rate:.6g}",
                            ]
                        )
                    if heats:
                        w.writerow([exp.name, "mean_heating", "heating", "", "", "", "", "", "", f"{np.mean(heats):.6g}"])
                        w.writerow([exp.name, "std_heating", "heating", "", "", "", "", "", "", f"{np.std(heats):.6g}"])
                    if cools:
                        w.writerow([exp.name, "mean_cooling", "cooling", "", "", "", "", "", "", f"{np.mean(cools):.6g}"])
                        w.writerow([exp.name, "std_cooling", "cooling", "", "", "", "", "", "", f"{np.std(cools):.6g}"])
        except Exception as e:
            self._set_status(f"Bundle exported, but rates summary failed: {e}")
            return
        self._set_status(
            f"Exported {len(self.experiments)} experiment(s) → {os.path.basename(path)} "
            f"(+ {os.path.basename(rates_path)})."
        )

    def import_analysis(self):
        """Importa un bundle generado por export_results: reconstruye múltiples
        experimentos con sus segmentos y el dt global (decisión Q10)."""
        path = askopenfilename(
            title="Select PCR analysis bundle CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not path:
            return
        dt_val = None
        temps, photos, segs, order = {}, {}, {}, []
        try:
            with open(path, newline="", encoding="utf-8") as f:
                reader = csv.reader(f, skipinitialspace=True)
                header = [h.strip() for h in (next(reader, None) or [])]
                if "record" not in header:
                    self._set_status(
                        "Not a PCR analysis bundle (missing 'record' column). Export "
                        "produces two files — select the main one (not _rates.csv)."
                    )
                    return
                col = {n: i for i, n in enumerate(header)}

                def cell(row, key):
                    i = col.get(key)
                    return row[i] if i is not None and i < len(row) else ""

                for row in reader:
                    if not row:
                        continue
                    rec = cell(row, "record").strip()
                    if rec == "dt":
                        try:
                            dt_val = float(cell(row, "value"))
                        except (ValueError, TypeError):
                            pass
                        continue
                    name = cell(row, "experiment").strip()
                    if not name:
                        continue
                    if name not in temps:
                        temps[name] = {}
                        photos[name] = {}
                        segs[name] = []
                        order.append(name)
                    if rec == "temp":
                        try:
                            temps[name][int(float(cell(row, "i")))] = float(cell(row, "value"))
                        except (ValueError, TypeError):
                            pass
                    elif rec == "photo":
                        try:
                            photos[name][int(float(cell(row, "i")))] = float(cell(row, "value"))
                        except (ValueError, TypeError):
                            pass
                    elif rec == "segment":
                        try:
                            segs[name].append((int(float(cell(row, "a"))), int(float(cell(row, "b")))))
                        except (ValueError, TypeError):
                            pass
        except Exception as e:
            self._set_status(f"Import error: {e}")
            return
        if not order:
            self._set_status("No experiments parsed from file.")
            return
        added = 0
        for name in order:
            tmap, pmap = temps[name], photos[name]
            tarr = [tmap[k] for k in sorted(tmap)]
            parr = [pmap[k] for k in sorted(pmap)]
            uname = self._unique_name(name)
            exp = PcrExperiment(name=uname, temps=tarr, photo=parr)
            for ia, ib in segs[name]:
                exp.segments.append(PcrSegment(ia, ib))
            self.experiments.append(exp)
            added += 1
        if dt_val and dt_val > 0:
            self.dt_var.set(f"{dt_val:.9g}")
        self._refresh_tree()
        self._redraw()
        self._set_status(f"Imported {added} experiment(s) from {os.path.basename(path)}.")


__author__ = "Edisson A. Naula"
__date__ = "2026-07-03"
