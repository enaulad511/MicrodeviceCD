# -*- coding: utf-8 -*-
import csv
import os
import time
import warnings
from tkinter.filedialog import askopenfilename, asksaveasfilename

import numpy as np
import ttkbootstrap as ttk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

from templates.utils import experiment_dir
from ui.analysis.common import plt


# ---------------------------------------------------------------------------
# Modelo de datos (EIS)
# ---------------------------------------------------------------------------
# Columnas canónicas que el cargador/siembra entienden (por NOMBRE de header,
# no por posición — el CSV de EIS guarda x_key/y_key + extras con estos nombres).
EIS_KEYS = ("freq_Hz", "Z_real", "Z_imag", "Z_mod", "E_V", "t_s")
# Columnas de datos del archivo "_spectra.csv" (export/import punto-a-punto), en
# orden de presentación. Incluye el derivado phase_deg (informativo; al reimportar
# EISSpectrum._derive lo recalcula). Header fijo: las celdas van vacías donde un
# espectro no tiene esa magnitud (decisión Q5).
EIS_SPECTRA_COLS = ("freq_Hz", "Z_real", "Z_imag", "Z_mod", "phase_deg", "E_V", "t_s")


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
        # --- Toolbar fila 1: archivo (izq) + globales (der). Dos filas para que en
        # pantallas chicas (touchscreen del Pi) no se corte Clear all. ---
        toolbar = ttk.Frame(self)
        toolbar.pack(side=ttk.TOP, fill=ttk.X, padx=6, pady=(6, 2))
        ttk.Button(toolbar, text="📂 Load CSV", bootstyle="secondary", command=self.load_csv).pack(
            side=ttk.LEFT, padx=3
        )
        ttk.Button(
            toolbar, text="📥 Import", bootstyle="secondary", command=self.import_spectra
        ).pack(side=ttk.LEFT, padx=3)
        ttk.Button(
            toolbar, text="💾 Export", bootstyle="secondary", command=self.export_results
        ).pack(side=ttk.LEFT, padx=3)
        ttk.Button(
            toolbar, text="Clear all", bootstyle="danger-outline", command=self.clear_all
        ).pack(side=ttk.RIGHT, padx=3)

        # --- Toolbar fila 1b: acciones de selección ---
        toolbar_b = ttk.Frame(self)
        toolbar_b.pack(side=ttk.TOP, fill=ttk.X, padx=6, pady=(0, 2))
        ttk.Button(
            toolbar_b, text="🗑 Remove", bootstyle="danger", command=self.remove_selected
        ).pack(side=ttk.LEFT, padx=3)
        ttk.Button(
            toolbar_b, text="👁 Show/Hide", bootstyle="info", command=self.toggle_visibility
        ).pack(side=ttk.LEFT, padx=3)

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
        self.tree = ttk.Treeview(left, columns=("info",), show="tree headings", selectmode="browse")
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
            initialdir=experiment_dir("eis"),
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
        self._set_status(f"Loaded '{base}' with {len(groups)} spectrum(s).")

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
        for run, cyc in sorted(groups):
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
            return any(
                s.has("freq_Hz", "Z_real", "Z_imag") and s.distinct_freqs() > 1 for s in specs
            )
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
            plt.rcParams["axes.prop_cycle"]
            .by_key()
            .get("color", ["b", "g", "r", "c", "m", "y", "k"])
        )
        return colors

    def _color(self, idx):
        return self._style_cycle[idx % len(self._style_cycle)]

    def _active_plots(self):
        return [
            key for key, _ in self.PLOTS if self.plot_vars[key].get() and self._plot_available(key)
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
            ax.plot(
                fo,
                sp.data["Z_mod"][order],
                marker="o",
                markersize=3,
                linewidth=1.3,
                color=c,
                label=sp.name,
            )
            if "phase_deg" in sp.data:
                ax_ph.plot(
                    fo,
                    sp.data["phase_deg"][order],
                    marker="s",
                    markersize=2,
                    linewidth=1.0,
                    linestyle="--",
                    color=c,
                    alpha=0.7,
                )
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
            ax.plot(
                x[order],
                sp.data[ykey][order],
                marker="o",
                markersize=3,
                linewidth=1.3,
                color=self._color(idx),
                label=sp.name,
            )
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
                        "",
                        xy=(m["rct_edge"], 0),
                        xytext=(m["Rs"], 0),
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
                f"Rct edge = {px:.4g} Ω"
                + (f" → Rct = {rct:.4g} Ω" if rct is not None else " (pick Rs too)")
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
        """Exporta dos archivos paralelos (espejo de la pestaña Peaks):

        - `<base>_spectra.csv`: SIEMPRE (si hay al menos un espectro). Datos punto-a-
          punto de TODOS los espectros (sin importar visibilidad, decisión Q3), header
          fijo EIS_SPECTRA_COLS. Reimportable con import_spectra() conservando nombres.
        - `<base>.csv` (el path elegido): solo si hay al menos una medición Nyquist
          (Rs/Rct/Warburg). Mismo formato de mediciones de siempre.

        El gate es "¿hay espectros?", no "¿hay mediciones?" (decisión Q2): permite
        guardar las curvas usadas para análisis sin tener que volver a escogerlas."""
        if not any(exp.spectra for exp in self.experiments):
            self._set_status("No spectra to export. Load or seed an EIS run first.")
            return

        # Mediciones (puede no haber ninguna): se escribirá solo si hay filas.
        meas_rows = []
        for exp in self.experiments:
            for sp in exp.spectra:
                if not sp.meas:
                    continue
                m = sp.meas
                meas_rows.append(
                    [
                        exp.name,
                        sp.name,
                        m.get("Rs", ""),
                        m.get("Rct", ""),
                        m.get("warb_len", ""),
                        m.get("warb_angle", ""),
                    ]
                )

        path = asksaveasfilename(
            title="Export EIS analysis",
            defaultextension=".csv",
            initialfile=f"eis_analysis_{time.strftime('%Y%m%d_%H%M')}.csv",
            filetypes=[("CSV files", "*.csv")],
        )
        if not path:
            return

        # --- Datos de espectros (siempre) → "<base>_spectra.csv" ---
        base, ext = os.path.splitext(path)
        spectra_path = f"{base}_spectra{ext or '.csv'}"
        n_pts = 0
        try:
            with open(spectra_path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["experiment", "spectrum", "point_idx", *EIS_SPECTRA_COLS])
                for exp in self.experiments:
                    for sp in exp.spectra:
                        arrays = {k: sp.data.get(k) for k in EIS_SPECTRA_COLS}
                        n = max((len(a) for a in arrays.values() if a is not None), default=0)
                        for i in range(n):
                            row = [exp.name, sp.name, i]
                            for k in EIS_SPECTRA_COLS:
                                a = arrays[k]
                                row.append(f"{a[i]:.9g}" if a is not None and i < len(a) else "")
                            w.writerow(row)
                            n_pts += 1
        except Exception as e:
            self._set_status(f"Export error (spectra file): {e}")
            return

        # --- Mediciones (solo si hay) → el path elegido ---
        if meas_rows:
            try:
                with open(path, "w", newline="", encoding="utf-8") as f:
                    w = csv.writer(f)
                    w.writerow(
                        [
                            "experiment",
                            "spectrum",
                            "Rs_ohm",
                            "Rct_ohm",
                            "warburg_len_ohm",
                            "warburg_angle_deg",
                        ]
                    )
                    w.writerows(meas_rows)
            except Exception as e:
                self._set_status(
                    f"Spectra exported ({n_pts} pts), but error writing measurements: {e}"
                )
                return
            self._set_status(
                f"Exported {len(meas_rows)} measurement(s) → {os.path.basename(path)}; "
                f"{n_pts} spectrum point(s) → {os.path.basename(spectra_path)}."
            )
        else:
            self._set_status(
                f"Exported {n_pts} spectrum point(s) → {os.path.basename(spectra_path)}; "
                "no measurements to write."
            )

    def import_spectra(self):
        """Importa un archivo "_spectra.csv" generado por export_results, conservando
        los nombres de experimento y espectro (espejo de PeakAnalysisFrame.import_analysis).

        Agrupa por (experiment, spectrum); lee cada columna de EIS_SPECTRA_COLS por
        nombre (ignora celdas vacías). Z_mod/phase_deg vienen del archivo pero se
        re-derivan en EISSpectrum cuando hay Z_real/Z_imag; en modos sin Z (|Z| vs t)
        el Z_mod del archivo se conserva tal cual. Hace append (no reemplaza) y de-
        duplica nombres de experimento colisionantes con sufijo _1, _2, …"""
        path = askopenfilename(
            title="Select spectra CSV (EIS export)",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, newline="", encoding="utf-8") as f:
                reader = csv.reader(f, skipinitialspace=True)
                header = [h.strip() for h in (next(reader, None) or [])]
                col = {name: i for i, name in enumerate(header)}
                if (
                    "experiment" not in col
                    or "spectrum" not in col
                    or not any(k in col for k in ("Z_real", "Z_imag", "Z_mod"))
                ):
                    self._set_status(
                        "Not a spectra file. Export produces a file ending in _spectra.csv — "
                        "select that one."
                    )
                    return
                data_keys = [k for k in EIS_SPECTRA_COLS if k in col]
                # exp_name → {spectrum_name → {key: [vals]}} (orden de inserción)
                groups = {}
                for row in reader:
                    try:
                        exp_name = row[col["experiment"]].strip()
                        spec_name = row[col["spectrum"]].strip()
                    except IndexError:
                        continue
                    spec_d = groups.setdefault(exp_name, {}).setdefault(
                        spec_name, {k: [] for k in data_keys}
                    )
                    for k in data_keys:
                        try:
                            cell = row[col[k]]
                        except IndexError:
                            continue
                        if cell == "":
                            continue
                        try:
                            spec_d[k].append(float(cell))
                        except ValueError:
                            pass
        except Exception as e:
            self._set_status(f"Import error: {e}")
            return
        if not groups:
            self._set_status("No data parsed from file.")
            return

        existing = {e.name for e in self.experiments}
        added = 0
        for exp_name, specs in groups.items():
            name = exp_name or "imported"
            suffix = 1
            while name in existing:
                name = f"{exp_name}_{suffix}"
                suffix += 1
            existing.add(name)
            exp = EISExperiment(name=name)
            for spec_name, data in specs.items():
                data = {k: v for k, v in data.items() if len(v)}
                if not data:
                    continue
                exp.spectra.append(EISSpectrum(name=spec_name, data=data))
            if not exp.spectra:
                continue
            self.experiments.append(exp)
            added += 1

        if not added:
            self._set_status("No data parsed from file.")
            return
        self._update_plot_availability()
        self._refresh_tree()
        self._refresh_plots()
        self._set_status(f"Imported {added} experiment(s) from {os.path.basename(path)}.")

    def _set_status(self, msg):
        self.lbl_status.configure(text=msg)


__author__ = "Edisson A. Naula"
__date__ = "2026-07-03"
