# -*- coding: utf-8 -*-
import math
import os
import re
import time
import weakref
from functools import lru_cache
from tkinter import TclError
from tkinter.filedialog import askopenfilename, asksaveasfilename
from typing import TypedDict

import numpy as np
import ttkbootstrap as ttk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure
from matplotlib.widgets import SpanSelector

from templates.utils import experiment_dir
from templates.xlsx_io import (
    XLSX_FILETYPES,
    read_sheet_text,
    read_sheets_text,
    write_workbook,
    xlsx_path,
)
from ui.analysis.common import CycleCurve, Experiment, _apply_filter, plt


# ---------------------------------------------------------------------------
# Detección de picos SWV (múltiples picos, solo máximos, con prominencia)
# ---------------------------------------------------------------------------
# Etiquetas de líneas cargadas por EventPlotter desde un archivo SWV: "<base>-r<run>c<cycle>".
_SQWV_LBL_RE = re.compile(r"^(.+)-r(\d+)c(\d+)$")


def _parse_sqwv_label(label):
    """'archivo-r2c0' → ('archivo', 2, 0); si no matchea, ('label', 1, 0)."""
    m = _SQWV_LBL_RE.match(str(label))
    if m:
        return m.group(1), int(m.group(2)), int(m.group(3))
    return str(label), 1, 0


def _detect_local_max_indices(ys, window, min_prom):
    """Índices de máximos locales en ys (SWV solo usa máximos; los mínimos se quitaron).

    Un punto es candidato si es el máximo en su ventana ±window y su prominencia
    local (vs el lado menos profundo dentro de esa ventana) supera min_prom. Los
    candidatos a <= window de distancia se fusionan conservando el más alto, así
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
        if v == seg.max() and v > seg.min():
            base = max(ys[lo : i + 1].min(), ys[i:hi].min())
            if (v - base) >= min_prom:
                cand.append(i)
    merged = []
    for i in cand:
        if merged and (i - merged[-1]) <= w:
            if ys[i] > ys[merged[-1]]:
                merged[-1] = i
        else:
            merged.append(i)
    return merged


def _slope_window(n, window):
    """Semi-ventana (puntos) que usa el detector por pendiente sobre `n` puntos: la pedida
    (mínimo 2), reducida a lo sumo a n//4 (mínimo 2) cuando el rango de E es estrecho. La
    comparten el detector y el aviso de Compute, para que avisen exactamente cuando se reduce."""
    return min(max(2, int(window)), max(2, n // 4))


@lru_cache(maxsize=32)
def _sg_coeffs(w, order, deriv):
    """Coeficientes Savitzky-Golay (ventana 2w+1, polinomio `order`, derivada `deriv`)
    para np.correlate(ys, coef, 'valid'); respecto al ÍNDICE de muestra (no a E), así
    un barrido descendente en E da el mismo resultado que uno ascendente."""
    x = np.arange(-w, w + 1, dtype=float)
    a = np.vander(x, order + 1, increasing=True)
    return np.linalg.pinv(a)[deriv] * math.factorial(deriv)


def _detect_slope_indices(ys, window, prom_frac):
    """Índices de picos por PENDIENTE (curvatura), para picos sobre una línea base
    inclinada que no son máximos locales.

    Sobre una base decreciente la 1.ª derivada nunca cruza por cero: el pico solo la
    frena. Lo que lo delata es el cambio de pendiente, es decir -y'' (máxima en el
    centro de un pico, ~0 o negativa en una caída/subida suave de la base). Se estima
    y' e y'' con Savitzky-Golay (ventana 2w+1, w = peak window, mínimo 2) y:

    1. candidatos = máximos locales de -y'' sobre un umbral
       max(prom_frac × máx(-y''), 5 × ruido), con ruido = MAD de las SEGUNDAS DIFERENCIAS
       de y propagada a y'' (no la dispersión de y'': base y picos la inflan y se
       pierden picos débiles). El umbral relativo solo no basta: una curva sin picos
       siempre tendría un "más fuerte";
    2. candidatos a <= w se fusionan conservando el de mayor -y'';
    3. si y' cruza de + a − a menos de w del centro, el pico se ajusta a ese máximo
       real (la pendiente fija el vértice); si no, queda en el hombro (centro de -y'').
    """
    ys = np.asarray(ys, dtype=float)
    n = ys.size
    # Un rango de E estrecho deja pocos puntos: se reduce la ventana (a lo sumo n/4, mínimo
    # 2) en vez de no detectar nada; el llamador avisa cuando eso ocurre (`_slope_window`).
    w = _slope_window(n, window)
    if n < 2 * w + 3:
        return []
    c2 = _sg_coeffs(w, 3, 2)
    d1 = np.full(n, np.nan)
    d2 = np.full(n, np.nan)
    d1[w : n - w] = np.correlate(ys, _sg_coeffs(w, 3, 1), "valid")
    d2[w : n - w] = np.correlate(ys, c2, "valid")
    curv = -d2
    core = curv[w : n - w]
    top = float(np.max(core))
    if not np.isfinite(top) or top <= 0:
        return []
    # Ruido de y'' propagado desde el ruido de y, estimado con la MAD de las segundas
    # diferencias (anulan la pendiente de la base; la MAD ignora los pocos puntos de
    # los picos). La dispersión de y'' misma no sirve: la inflan base y picos.
    dd = ys[2:] - 2.0 * ys[1:-1] + ys[:-2]
    sigma_y = 1.4826 * float(np.median(np.abs(dd - np.median(dd)))) / math.sqrt(6.0)
    noise = sigma_y * float(np.sqrt(np.sum(c2**2)))
    thr = max(max(0.0, prom_frac) * top, 5.0 * noise)
    cand = [
        i
        for i in range(w + 1, n - w - 1)
        if curv[i] > 0 and curv[i] >= thr and curv[i] >= curv[i - 1] and curv[i] > curv[i + 1]
    ]
    merged = []
    for i in cand:
        if merged and (i - merged[-1]) <= w:
            if curv[i] > curv[merged[-1]]:
                merged[-1] = i
        else:
            merged.append(i)
    out = []
    for i in merged:
        best: "int | None" = None  # cruce + → − de y' más cercano al centro
        for j in range(max(w, i - w), min(n - w - 1, i + w)):
            if d1[j] > 0 >= d1[j + 1] and (best is None or abs(j - i) < abs(best - i)):
                best = j
        if best is not None:
            i = best if ys[best] >= ys[best + 1] else best + 1
        if not out or i != out[-1]:
            out.append(i)
    return out


def _detect_peaks(xs, ys, window, prom_frac, method="local"):
    """Devuelve los máximos como lista de (x, y). SWV solo usa máximos (el pico de
    corriente neta); los mínimos no se calculan.

    method="local": máximos locales; prom_frac = prominencia mínima como fracción del
    span de ys (decisión Q11: porcentaje del rango, escala con el current range).
    method="slope": por pendiente/curvatura (`_detect_slope_indices`); prom_frac =
    fracción de la curvatura del pico más marcado.
    """
    ys = np.asarray(ys, dtype=float)
    xs = np.asarray(xs, dtype=float)
    if ys.size == 0:
        return []
    if method == "slope":
        idx = _detect_slope_indices(ys, window, prom_frac)
    else:
        span = float(np.max(ys) - np.min(ys)) or 1.0
        idx = _detect_local_max_indices(ys, window, max(0.0, prom_frac) * span)
    return [(float(xs[i]), float(ys[i])) for i in idx]


class _DetectSig(TypedDict):
    """Parámetros de detección que firman un Compute (`_controls_sig`)."""

    method: str
    window_mv: int
    prom: float
    filter: str
    fwin: int


# ---------------------------------------------------------------------------
# Pestaña: análisis de picos SWV (múltiples picos por corrida, sin tendencia)
# ---------------------------------------------------------------------------
class SqwvAnalysisFrame(ttk.Frame):
    """Pestaña de picos SWV: archivos cargados → corridas (runs). (En la UI cada archivo se
    llama "File"; "experimento" es una serie de corridas de un mismo electrodo, ver
    GLOSSARY.md. Internamente el archivo se guarda como `Experiment`, clase de `common`.)

    A diferencia de PeakAnalysisFrame, NO calcula tendencia entre experimentos: el
    énfasis es detectar MÚLTIPLES picos por corrida (analitos a distintos potenciales)
    y reportar E_pico / I_pico (y la altura sobre la base local) en cada punto. Solo
    máximos; semi-ventana en mV y prominencia por método; permite añadir/borrar picos a
    mano, y un solo overlay con los picos marcados y anotados. Reusa Experiment/CycleCurve;
    el ítem por curva es una corrida (SWV = un barrido I vs E por run; un archivo puede
    traer varios).
    """

    FILTERS = ("none", "moving_avg", "median")
    # Detección: máximos locales (clásico) o por pendiente/curvatura (picos sobre base inclinada).
    METHODS = ("Local max", "Slope")
    # Semi-ventana por defecto (mV): con 5.9 mV/punto son ~10 puntos. En las corridas reales
    # de referencia (163121) con ±30 mV el pico aparecía/desaparecía entre corridas.
    DEFAULT_PEAK_WINDOW_MV = 60
    # La recta de la base se ancla a ±BASE_ANCHOR × semi-ventana del pico (±1× quedaba sobre
    # los flancos y subestimaba la altura a la mitad; ±3× cae en el pico vecino).
    BASE_ANCHOR = 2

    def _method_key(self):
        return "slope" if self.method_var.get() == "Slope" else "local"

    def _num(self, var, cast, default, minimum):
        """Lee un campo numérico sin lanzar: vacío / texto no numérico (mientras se
        escribe en el spinbox) devuelve el último valor válido de ese campo, o `default`."""
        key = str(var)
        try:
            v = cast(var.get())
            if not math.isfinite(v):
                raise ValueError
        except (ValueError, TclError, OverflowError):  # 'inf' / '1e400' en un IntVar
            return self._last_valid.get(key, default)
        v = max(minimum, v)
        self._last_valid[key] = v
        return v

    def _set_prom_field(self, value):
        """Escribe el campo de prominencia desde el código (cambio de método, Import) y lo
        registra como último valor válido: si luego el usuario lo deja vacío, `_num` debe
        devolver ESTE valor y no el que tenía el campo con el otro método."""
        v = max(0.0, float(value))
        self.prominence_var.set(v)
        self._last_valid[str(self.prominence_var)] = v

    def _peak_window_mv(self):
        return self._num(self.peak_window_var, int, self.DEFAULT_PEAK_WINDOW_MV, 1)

    def _filter_window(self):
        return self._num(self.filter_window_var, int, 5, 1)

    def _prom_pct(self):
        return self._num(self.prominence_var, float, 5.0, 0.0)

    def _on_method_change(self):
        """Guarda la prominencia del método que se deja y carga la del nuevo."""
        self._prom[self._prom_method] = self._prom_pct()
        self._prom_method = self._method_key()
        self._set_prom_field(self._prom[self._prom_method])
        self._update_prom_label()

    def _prom_values(self):
        """{'local': %, 'slope': %} con el valor del método activo tomado del campo."""
        vals = dict(self._prom)
        vals[self._method_key()] = self._prom_pct()
        return vals

    def _controls_sig(self) -> "_DetectSig":
        """Parámetros de detección vigentes (sin el rango: Apply ya poda los picos)."""
        return {
            "method": self._method_key(),
            "window_mv": self._peak_window_mv(),
            "prom": self._prom_pct(),
            "filter": self.filter_var.get(),
            "fwin": self._filter_window(),
        }

    @staticmethod
    def _window_pts(window_mv, xs):
        """Semi-ventana en puntos para una curva: mV / paso medio de E (mínimo 1)."""
        xs = np.asarray(xs, dtype=float)
        if xs.size < 2:
            return 1
        step = float(np.median(np.abs(np.diff(xs))))
        if not np.isfinite(step) or step <= 0:
            return 1
        return max(1, int(round(window_mv / 1000.0 / step)))

    def _height_above_base(self, xs, ys, x, y, half_pts):
        """Altura (A) del pico (x, y) sobre la recta que une los puntos a ±BASE_ANCHOR ×
        half_pts (acotados a los extremos de xs/ys, que ya vienen recortados al rango de E).
        None si el pico es él mismo un ancla (borde del rango) o no hay dos anclas distintas."""
        if xs.size < 3:
            return None
        i = int(np.argmin(np.abs(xs - x)))
        k = max(1, self.BASE_ANCHOR * int(half_pts))
        a, b = max(0, i - k), min(xs.size - 1, i + k)
        if a == b or a == i or b == i or xs[b] == xs[a]:
            return None
        base = ys[a] + (ys[b] - ys[a]) * (xs[i] - xs[a]) / (xs[b] - xs[a])
        return float(y - base)

    def _remember_heights(self, c, ys_full, peaks):
        """Calcula y GUARDA la altura de `peaks` de la curva `c`, con los datos filtrados
        (`ys_full`, curva completa) y la ventana vigentes AHORA. Se llama al detectar o añadir
        un pico: la altura queda fija junto a E/I del pico y no cambia si luego se tocan el
        filtro o la ventana sin recalcular."""
        m = self._range_mask(c.xs)
        xs_r, ys_r = c.xs[m], np.asarray(ys_full, dtype=float)[m]
        half = self._window_pts(self._peak_window_mv(), xs_r)
        store = self._heights.setdefault(c, {})
        for x, y in peaks:
            store[(x, y)] = self._height_above_base(xs_r, ys_r, x, y, half)

    def _peaks_in_range(self, c):
        """[(x, y, altura|None)] de los picos de `c` dentro del rango de E aplicado. Los
        guardados fuera del rango (p. ej. el rango restaurado por Import, que no poda) no
        se muestran ni se exportan."""
        lo, hi = self._range()
        heights = self._heights.get(c, {})
        return [(x, y, heights.get((x, y))) for x, y in c.max_points if lo <= x <= hi]

    def _update_prom_label(self):
        if self._method_key() == "slope":
            self.lbl_prom.configure(text="Min curvature (% of max):")
        else:
            self.lbl_prom.configure(text="Min prominence (%):")

    def __init__(self, master, owner, plotter=None, **kwargs):
        super().__init__(master, **kwargs)
        self.owner = owner
        self._last_valid: "dict[str, float]" = {}  # str(var) → último valor válido del campo
        # curva → {(x, y): altura}; débil para que borrar la curva libere su entrada.
        self._heights: "weakref.WeakKeyDictionary[CycleCurve, dict]" = weakref.WeakKeyDictionary()
        # curva → (filtro, ventana) con que se calculó su `ys_filtered` en el último Compute.
        self._filters: "weakref.WeakKeyDictionary[CycleCurve, tuple[str, int]]" = (
            weakref.WeakKeyDictionary()
        )
        # parámetros usados en el último Compute, o None
        self._compute_sig: "_DetectSig | None" = None
        # Rango de E APLICADO (Apply / Select on plot / Full range / Import): el único que
        # leen Compute, Export, Add peak y el dibujo. Lo escrito en los campos no cuenta
        # hasta aplicarlo.
        self._applied_range: "tuple[float, float]" = (-np.inf, np.inf)
        self.experiments = []  # list[Experiment]
        self._tree_ref = {}  # iid árbol izq → ("exp", exp) | ("run", exp, curve)
        self._res_ref = {}  # iid tabla → ("exp", exp) | ("run", exp, c) | ("peak", exp, c, kind, (x,y))
        self._legend_visible = True
        self._add_mode = False  # captura de clics para añadir picos
        self._pick_cid: int | None = None
        self._span_mode = False  # arrastre en la gráfica para fijar el rango de E
        self._span: "SpanSelector | None" = None

        self._build_ui()
        # Siembra: corrida SWV en memoria (total_data, sin pre-tratamiento) + curvas cargadas
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
        ttk.Button(toolbar, text="📂 Load", bootstyle="secondary", command=self.load_file).pack(
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

        # --- Toolbar fila 2: ventana + prominencia + filtro ---
        toolbar2 = ttk.Frame(self)
        toolbar2.pack(side=ttk.TOP, fill=ttk.X, padx=6, pady=(0, 4))
        ttk.Label(toolbar2, text="Method:").pack(side=ttk.LEFT, padx=(0, 4))
        self.method_var = ttk.StringVar(value=self.METHODS[1])  # Slope por defecto
        ttk.Combobox(
            toolbar2,
            textvariable=self.method_var,
            values=self.METHODS,
            state="readonly",
            width=10,
        ).pack(side=ttk.LEFT)

        # Semi-ventana en mV (no en puntos): lo que importa es cuánto abarca respecto al
        # ancho del pico, y el paso de E cambia entre archivos. Se pasa a puntos por curva.
        ttk.Label(toolbar2, text="Peak window (mV):").pack(side=ttk.LEFT, padx=(12, 4))
        self.peak_window_var = ttk.IntVar(value=self.DEFAULT_PEAK_WINDOW_MV)
        ttk.Spinbox(
            toolbar2, from_=5, to=1000, increment=5, width=5, textvariable=self.peak_window_var
        ).pack(side=ttk.LEFT)

        self.lbl_prom = ttk.Label(toolbar2, text="Min prominence (%):")
        self.lbl_prom.pack(side=ttk.LEFT, padx=(12, 4))
        # Un valor por método (significan cosas distintas): el campo muestra el del activo.
        self._prom = {"local": 5.0, "slope": 5.0}
        self._prom_method = "slope"
        self.prominence_var = ttk.DoubleVar(value=self._prom["slope"])
        ttk.Spinbox(
            toolbar2, from_=0, to=100, increment=0.5, width=6, textvariable=self.prominence_var
        ).pack(side=ttk.LEFT)
        self.method_var.trace_add("write", lambda *_: self._on_method_change())
        self._update_prom_label()

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
        ttk.Label(toolbar2, text="Filter window (pts):").pack(side=ttk.LEFT, padx=(8, 4))
        self.filter_window_var = ttk.IntVar(value=5)
        ttk.Spinbox(
            toolbar2, from_=1, to=500, increment=1, width=5, textvariable=self.filter_window_var
        ).pack(side=ttk.LEFT)

        # --- Toolbar fila 2b: rango de potencial (se muestra y se calcula solo dentro) ---
        toolbar_r = ttk.Frame(self)
        toolbar_r.pack(side=ttk.TOP, fill=ttk.X, padx=6, pady=(0, 4))
        ttk.Label(toolbar_r, text="E range (V):").pack(side=ttk.LEFT, padx=(0, 4))
        self.e_min_var = ttk.StringVar(value="")
        self.e_max_var = ttk.StringVar(value="")
        e_min = ttk.Entry(toolbar_r, textvariable=self.e_min_var, width=8)
        e_min.pack(side=ttk.LEFT)
        ttk.Label(toolbar_r, text="to").pack(side=ttk.LEFT, padx=4)
        e_max = ttk.Entry(toolbar_r, textvariable=self.e_max_var, width=8)
        e_max.pack(side=ttk.LEFT)
        for e in (e_min, e_max):
            e.bind("<Return>", lambda _e: self.apply_range())
        ttk.Button(
            toolbar_r, text="Apply", bootstyle="secondary", command=self.apply_range
        ).pack(side=ttk.LEFT, padx=(6, 3))
        self.btn_span = ttk.Button(
            toolbar_r,
            text="↔ Select on plot",
            bootstyle="secondary-outline",
            command=self._toggle_span_mode,
        )
        self.btn_span.pack(side=ttk.LEFT, padx=3)
        ttk.Button(
            toolbar_r, text="Full range", bootstyle="secondary-outline", command=self.reset_range
        ).pack(side=ttk.LEFT, padx=3)
        ttk.Label(toolbar_r, text="(blank = no limit)").pack(side=ttk.LEFT, padx=6)

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

        # --- Split árbol | figura ---
        main = ttk.PanedWindow(inner, orient=ttk.HORIZONTAL)
        main.pack(fill=ttk.X, padx=0, pady=(0, 6))

        left = ttk.LabelFrame(main, text="Files → Runs (double-click to rename)")
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
        cols_r = ("e_peak", "i_peak", "height")
        self.tree_res = ttk.Treeview(bottom, columns=cols_r, show="tree headings", height=14)
        self.tree_res.heading("#0", text="File / Run")
        self.tree_res.column("#0", width=300, anchor="w")
        heads = {"e_peak": "E peak (V)", "i_peak": "I peak (A)", "height": "Height (A)"}
        widths = {"e_peak": 150, "i_peak": 150, "height": 150}
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
        # Igual para el arrastre de rango: el selector pertenece al eje recreado.
        self._span = None
        if self._span_mode:
            self._span = SpanSelector(
                self.ax_overlay,
                self._on_span_select,
                "horizontal",
                useblit=False,
                props=dict(facecolor="tab:green", alpha=0.2),
            )

    def _reset_plot_canvas(self):
        self._pick_cid = None
        self._span = None
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
        """Corrida SWV en memoria (total_data, sin pre-tratamiento) + curvas cargadas ya
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
        """Curvas cargadas desde archivo en el plotter (loaded_lines), agrupadas por archivo."""
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
        usa los picos ya almacenados en cada curva (max_points; SWV solo máximos)."""
        kind = self.filter_var.get()
        fw = self._filter_window()
        self._reset_plot_canvas()
        self.tree_res.delete(*self.tree_res.get_children())
        self._res_ref = {}

        any_visible = False
        all_max = []
        for exp in self.experiments:
            vis = [c for c in exp.cycles if c.visible]
            if not vis:
                continue
            exp_iid = self.tree_res.insert(
                "", ttk.END, text=exp.name, values=("", "", ""), open=True
            )
            self._res_ref[exp_iid] = ("exp", exp)
            for c in vis:
                ys_disp = _apply_filter(c.ys, kind, fw) if kind != "none" else c.ys
                m = self._range_mask(c.xs)
                if not m.any():
                    continue
                self.ax_overlay.plot(
                    c.xs[m], ys_disp[m], linewidth=1.2, marker=".", markersize=2,
                    label=f"{exp.name}/{c.name}",
                )
                any_visible = True
                for x, y, h in self._peaks_in_range(c):
                    all_max.append((x, y))
                    riid = self.tree_res.insert(
                        exp_iid, ttk.END, text=c.name,
                        values=(f"{x:.6g}", f"{y:.6g}", "" if h is None else f"{h:.6g}"),
                    )
                    self._res_ref[riid] = ("peak", exp, c, "max", (x, y))
        if all_max:
            xs, ys = zip(*all_max)
            self.ax_overlay.scatter(xs, ys, marker="^", s=55, color="tab:red", zorder=5)
            for x, y in all_max:
                self.ax_overlay.annotate(
                    f"{x:.3g} V\n{y:.3g} A", (x, y), textcoords="offset points",
                    xytext=(0, 8), ha="center", fontsize=7, color="tab:red",
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
        self._set_status(f"Removed {len(exps_to_drop)} file(s), {len(runs_to_drop)} run(s).")

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
        sig = self._controls_sig()
        method = sig["method"]
        pwin_mv = sig["window_mv"]
        prom_frac = sig["prom"] / 100.0
        fkind = sig["filter"]
        fwin = sig["fwin"]
        n_curves = 0
        n_peaks = 0
        n_narrow = 0  # curvas con menos puntos en el rango que los que pide la ventana
        for exp in self.experiments:
            for c in exp.cycles:
                if not c.visible:
                    c.max_points = []
                    self._heights.pop(c, None)
                    continue
                ys_f = _apply_filter(c.ys, fkind, fwin) if fkind != "none" else c.ys
                c.ys_filtered = ys_f
                self._filters[c] = (fkind, fwin)  # Export etiqueta `y_filtered` con esto
                # Se filtra la curva completa (sin efectos de borde por el recorte) y
                # solo entonces se recorta al rango: todos los picos dentro se detectan,
                # y la prominencia (% del span) es la del tramo seleccionado.
                m = self._range_mask(c.xs)
                # La semi-ventana está en mV: se pasa a puntos con el paso de E de esta curva.
                pwin = self._window_pts(pwin_mv, c.xs[m])
                if method == "slope":
                    n_pts = int(m.sum())
                    w_eff = _slope_window(n_pts, pwin)
                    # Avisa si el detector reduce la ventana, o si no quedan puntos para correrlo.
                    if w_eff != max(2, pwin) or n_pts < 2 * w_eff + 3:
                        n_narrow += 1
                maxs = _detect_peaks(c.xs[m], ys_f[m], pwin, prom_frac, method)
                c.max_points = maxs
                # La altura se fija ahora, con el mismo filtro/ventana que dieron el pico.
                self._heights.pop(c, None)
                self._remember_heights(c, ys_f, maxs)
                n_curves += 1
                n_peaks += len(maxs)
        self._compute_sig = sig
        self._redraw()
        lo, hi = self._range()
        rng = ""
        if np.isfinite(lo) or np.isfinite(hi):
            rng = f", E=[{lo:.4g}, {hi:.4g}] V".replace("-inf", "min").replace("inf", "max")
        self._set_status(
            f"Detected {n_peaks} peak(s) on {n_curves} run(s) — "
            f"{self.method_var.get()}, prom={sig['prom']:g}%, filter={fkind}"
            + (f" (w={fwin})" if fkind != "none" else "")
            + rng
            + (
                f". E range narrower than the peak window on {n_narrow} run(s): window "
                "shrunk (or too few points to detect), and peaks within one window of the "
                "range edge can't be found — widen the range or lower the window."
                if n_narrow
                else ""
            )
            + self._range_hint()
        )

    # ------------------------------------------------------ Rango de potencial
    def _range(self):
        """(lo, hi) en V del rango de E APLICADO; ±inf = sin límite. Lo escrito en los campos
        no cuenta hasta pulsar Apply (o Select on plot / Full range / Import)."""
        return self._applied_range

    def _parse_range_fields(self):
        """(lo, hi, bad): lo/hi = float, o None si el campo está vacío (sin límite); bad = el
        texto del primer campo que no es un número finito (entonces lo y hi son None), o
        None si ambos valen."""
        out = []
        for var in (self.e_min_var, self.e_max_var):
            s = var.get().strip()
            if not s:
                out.append(None)
                continue
            try:
                v = float(s)
            except ValueError:
                v = float("nan")
            if not math.isfinite(v):  # 'nan' / 'inf' / texto a medio escribir ('0.2 V')
                return None, None, s
            out.append(v)
        return out[0], out[1], None

    def _commit_range(self):
        """Fija el rango aplicado desde los campos (con mín > máx los intercambia y los campos
        muestran el rango realmente aplicado). Devuelve (ok, swapped, bad): si algún campo no
        es un número finito no cambia nada y `bad` es ese texto."""
        lo, hi, bad = self._parse_range_fields()
        if bad is not None:
            return False, False, bad
        swapped = lo is not None and hi is not None and lo > hi
        if swapped:
            self.e_min_var.set(f"{hi:.6g}")
            self.e_max_var.set(f"{lo:.6g}")
            lo, hi, _ = self._parse_range_fields()  # el rango es el del texto ya redondeado
        self._applied_range = (-np.inf if lo is None else lo, np.inf if hi is None else hi)
        return True, swapped, None

    def _range_fields_pending(self):
        """True si lo escrito en E min / E max no coincide con el rango aplicado."""
        lo, hi, bad = self._parse_range_fields()
        if bad is not None:
            return True
        lo = -np.inf if lo is None else lo
        hi = np.inf if hi is None else hi
        if lo > hi:
            lo, hi = hi, lo
        return (lo, hi) != self._applied_range

    def _range_hint(self):
        """Sufijo para el estado de Compute / Export cuando los campos no están aplicados."""
        if self._range_fields_pending():
            return " The E range fields are not applied — press Apply (the applied range was used)."
        return ""

    def _range_mask(self, xs):
        lo, hi = self._range()
        xs = np.asarray(xs, dtype=float)
        return (xs >= lo) & (xs <= hi)

    def apply_range(self):
        """Aplica el rango: recorta lo que se muestra y descarta los picos que quedan
        fuera (no quedan picos ocultos que se exporten); Compute detecta dentro."""
        ok, swapped, bad = self._commit_range()
        if not ok:
            self._set_status(f"'{bad}' is not a valid number; E range not applied.")
            return
        lo, hi = self._range()
        dropped = 0
        for exp in self.experiments:
            for c in exp.cycles:
                keep = [p for p in c.max_points if lo <= p[0] <= hi]
                dropped += len(c.max_points) - len(keep)
                c.max_points[:] = keep
        self._redraw()
        if np.isfinite(lo) or np.isfinite(hi):
            self._set_status(
                ("E min/max were swapped. " if swapped else "")
                + f"E range applied; {dropped} peak(s) outside removed. Press Compute to re-detect."
            )
        else:
            self._set_status("E range cleared (full sweep).")

    def reset_range(self):
        self.e_min_var.set("")
        self.e_max_var.set("")
        self.apply_range()

    def _toggle_span_mode(self):
        self._span_mode = not self._span_mode
        if self._span_mode:
            if self._add_mode:  # los clics no pueden servir a las dos cosas
                self._toggle_add_mode()
            self.btn_span.configure(bootstyle="success")
            self._set_status("Drag on the plot to choose the E range (toolbar pan/zoom must be off).")
        else:
            self.btn_span.configure(bootstyle="secondary-outline")
            self._set_status("Range selection cancelled.")
        self._redraw()

    def _on_span_select(self, xmin, xmax):
        try:
            if getattr(self.toolbar_mpl, "mode", "") not in ("", None):
                return
        except Exception:
            pass
        if xmax - xmin <= 0:
            return
        self.e_min_var.set(f"{xmin:.4g}")
        self.e_max_var.set(f"{xmax:.4g}")
        # Una sola selección por activación: evita redefinir el rango sin querer.
        self._span_mode = False
        self.btn_span.configure(bootstyle="secondary-outline")
        # El redibujo recrea el canvas; se difiere fuera del callback del selector.
        self.after(0, self.apply_range)

    # ------------------------------------------------ Edición manual de picos
    def _toggle_add_mode(self):
        self._add_mode = not self._add_mode
        if self._add_mode:
            if self._span_mode:
                self._span_mode = False
                self.btn_span.configure(bootstyle="secondary-outline")
                if self._span is not None:
                    self._span.set_active(False)
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
        fw = self._filter_window()
        for exp in self.experiments:
            for c in exp.cycles:
                if not c.visible or c.xs.size == 0:
                    continue
                ys = _apply_filter(c.ys, kind, fw) if kind != "none" else c.ys
                m = self._range_mask(c.xs)
                if not m.any():
                    continue
                xs_r, ys_r = c.xs[m], ys[m]
                try:
                    pts = self.ax_overlay.transData.transform(np.column_stack([xs_r, ys_r]))
                except Exception:
                    continue
                d = np.hypot(pts[:, 0] - event.x, pts[:, 1] - event.y)
                j = int(np.argmin(d))
                if best is None or d[j] < best[0]:
                    best = (float(d[j]), exp, c, float(xs_r[j]), float(ys_r[j]))
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
        # SWV: solo máximos, todo clic añade un pico máximo.
        target = c.max_points
        if any(abs(px - x) < 1e-12 and abs(py - y) < 1e-30 for px, py in target):
            self._set_status(f"Peak already present at E={x:.4g} V, I={y:.4g} A.")
            return
        target.append((x, y))
        target.sort(key=lambda t: t[0])
        kind = self.filter_var.get()
        ys_f = _apply_filter(c.ys, kind, self._filter_window()) if kind != "none" else c.ys
        self._remember_heights(c, ys_f, [(x, y)])
        self._redraw()
        self._set_status(f"Added peak at E={x:.4g} V, I={y:.4g} A.")

    def _delete_selected_peaks(self):
        sel = [i for i in self.tree_res.selection() if i in self._res_ref]
        peaks = [self._res_ref[i] for i in sel if self._res_ref[i][0] == "peak"]
        if not peaks:
            self._set_status("Select one or more peak rows in the table to delete.")
            return
        n = 0
        for _tag, _exp, c, _kind, (x, y) in peaks:
            for k, (px, py) in enumerate(c.max_points):
                if abs(px - x) < 1e-12 and abs(py - y) < 1e-30:
                    c.max_points.pop(k)
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
        self._heights.clear()
        self._filters.clear()
        self._compute_sig = None  # el rango aplicado se conserva, igual que los campos
        self._tree_ref.clear()
        self._res_ref.clear()
        self.tree_curves.delete(*self.tree_curves.get_children())
        self.tree_res.delete(*self.tree_res.get_children())
        self._reset_plot_canvas()
        self.canvas.draw_idle()
        self._set_status("Cleared.")

    # ------------------------------------------------------ Load / Import
    def load_file(self):
        """Carga la hoja `data` de un libro guardado por EventPlotter.save_data (un
        archivo = un experimento, agrupado por 'run'). Excluye filas de pre-tratamiento
        (columna 'phase')."""
        path = askopenfilename(
            title="Select SWV data file (one experiment)",
            initialdir=experiment_dir("sqwv"),
            filetypes=XLSX_FILETYPES,
        )
        if not path:
            return
        groups = {}  # (run, cycle) → ([xs], [ys])
        try:
            rows = read_sheet_text(path, "data") or []
            header = [h.strip() for h in (rows[0] if rows else [])]
            col = {name: i for i, name in enumerate(header)}
            xi = col.get("E_V", 1)
            yi = col.get("I_A", 2)
            ci = col.get("cycle", 3)
            ri = col.get("run", 4)
            pi = col.get("phase", None)
            for row in rows[1:]:
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
        """Importa la hoja `curves` de un export_results (espejo de
        PeakAnalysisFrame.import_analysis; agrupa por experiment → run via y_raw)."""
        path = askopenfilename(
            title="Select SWV analysis export",
            filetypes=XLSX_FILETYPES,
        )
        if not path:
            return
        settings_rows = None
        try:
            sheets = read_sheets_text(path)
            rows = sheets.get("curves") or []
            settings_rows = sheets.get("settings")
            header = [h.strip() for h in (rows[0] if rows else [])]
            if "y_raw" not in header:
                self._set_status("Not an SWV analysis export (missing 'curves' sheet).")
                return
            col = {name: i for i, name in enumerate(header)}
            groups = {}
            for row in rows[1:]:
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
        restored = self._apply_settings_rows(settings_rows)
        self._refresh_tree()
        self._redraw()
        self._set_status(
            f"Imported {added} file(s) from {os.path.basename(path)}."
            + (" Settings restored — press Compute to recalculate peaks." if restored else "")
        )

    # ------------------------------------------- Settings (rango + parámetros)
    def _settings_rows(self):
        """Hoja `settings` (key, value): rango de E y parámetros de detección/filtro,
        para poder recalcular los picos al volver a cargar el export."""
        lo, hi = self._range()
        # Los parámetros del ÚLTIMO COMPUTE (los que produjeron los picos exportados); si no
        # se ha calculado, los controles vigentes. El rango es el vigente (Apply ya poda).
        sig = self._compute_sig or self._controls_sig()
        prom = self._prom_values()
        prom[sig["method"]] = sig["prom"]
        return [
            ["key", "value"],
            ["e_min_V", lo if np.isfinite(lo) else ""],
            ["e_max_V", hi if np.isfinite(hi) else ""],
            ["method", sig["method"]],
            ["peak_window_mV", sig["window_mv"]],
            # Uno por método: significan cosas distintas (% del span / % de la curvatura).
            ["prominence_pct_local", prom["local"]],
            ["prominence_pct_slope", prom["slope"]],
            ["filter", sig["filter"]],
            ["filter_window", sig["fwin"]],
        ]

    def _apply_settings_rows(self, rows):
        """Restaura los controles desde la hoja `settings` (si el libro la trae; los
        exports viejos no). Valores inválidos se ignoran. No recalcula picos."""
        if not rows:
            return False
        kv = {}
        for r in rows[1:]:
            if r:
                # Una celda vacía (rango sin límite) puede llegar como fila de un solo
                # elemento: la clave debe existir con valor "" para limpiar el campo.
                kv[r[0].strip()] = r[1].strip() if len(r) >= 2 else ""

        def _num(key, cast):
            try:
                return cast(float(kv[key]))
            except (KeyError, ValueError, OverflowError):  # int(float('inf')) → OverflowError
                return None

        # Rango: vacío en el archivo = sin límite (se limpia el campo). Se aplica (es el
        # rango del export) pero NO poda los picos de lo ya cargado: `_peaks_in_range` los
        # oculta y Full range los devuelve.
        if "e_min_V" in kv or "e_max_V" in kv:
            for key, var in (("e_min_V", self.e_min_var), ("e_max_V", self.e_max_var)):
                if key in kv:
                    v = _num(key, float)
                    var.set(f"{v:.6g}" if v is not None and math.isfinite(v) else "")
            self._commit_range()
        if kv.get("method") in ("local", "slope"):
            self.method_var.set(self.METHODS[1] if kv["method"] == "slope" else self.METHODS[0])
        if kv.get("filter") in self.FILTERS:
            self.filter_var.set(kv["filter"])
        for key, var, cast in (
            ("peak_window_mV", self.peak_window_var, int),
            ("filter_window", self.filter_window_var, int),
        ):
            v = _num(key, cast)
            if v is not None:
                var.set(v)
        # Exports anteriores guardaban la ventana en puntos (`peak_window`): se convierte
        # a mV con el paso de las curvas ya cargadas.
        if "peak_window_mV" not in kv:
            pts = _num("peak_window", int)
            step_mv = self._median_step_mv()
            if pts is not None and step_mv is not None:
                self.peak_window_var.set(max(1, int(round(pts * step_mv))))
        # Prominencia por método; el export anterior traía un solo valor (`min_prominence_pct`)
        # que pertenece al método guardado en ese mismo archivo.
        legacy = _num("min_prominence_pct", float)
        if legacy is not None and "prominence_pct_local" not in kv:
            self._prom[self._method_key()] = legacy
        for key, mkey in (("prominence_pct_local", "local"), ("prominence_pct_slope", "slope")):
            v = _num(key, float)
            if v is not None:
                self._prom[mkey] = v
        self._set_prom_field(self._prom[self._method_key()])
        return True

    def _median_step_mv(self):
        """Paso medio de E (mV) de las curvas cargadas; None si no hay."""
        steps = []
        for exp in self.experiments:
            for c in exp.cycles:
                if c.xs.size > 1:
                    s = float(np.median(np.abs(np.diff(c.xs))))
                    if np.isfinite(s) and s > 0:
                        steps.append(s)
        return 1000.0 * float(np.median(steps)) if steps else None

    def export_results(self):
        """Exporta UN libro (espejo de PeakAnalysisFrame):
        - hoja `peaks`: un pico por fila (experiment, run, type, E_peak, I_peak, height_A),
          solo los del rango aplicado; `type` es siempre "max".
        - hoja `curves`: curvas punto-a-punto (crudo + filtrado) para reimportar, siempre el
          barrido completo. `filter`/`filter_window` de cada curva son los que produjeron su
          `y_filtered` en el último Compute (no los controles de ahora).
        - hoja `settings`: rango aplicado y parámetros del último Compute (`_settings_rows`).
        """
        rows: list[list] = []
        for exp in self.experiments:
            for c in exp.cycles:
                if not c.visible:
                    continue
                # `type` queda como constante "max" por compatibilidad del formato.
                for x, y, h in self._peaks_in_range(c):
                    rows.append([exp.name, c.name, "max", x, y, h])
        if not any(c.visible for e in self.experiments for c in e.cycles):
            self._set_status("Nothing to export. Load or seed a run first.")
            return
        path = asksaveasfilename(
            title="Export SWV peaks",
            defaultextension=".xlsx",
            initialfile=f"sqwv_peaks_{time.strftime('%Y%m%d_%H%M')}.xlsx",
            filetypes=XLSX_FILETYPES,
        )
        if not path:
            return
        path = xlsx_path(path)
        fkind = self.filter_var.get()
        fwin = self._filter_window()
        curves: list[list] = [
            ["experiment", "run", "point_idx", "x", "y_raw", "y_filtered",
             "filter", "filter_window"]
        ]
        for exp in self.experiments:
            for c in exp.cycles:
                if not c.visible:
                    continue
                # La etiqueta es la del filtro que produjo `ys_filtered` (Compute); una curva
                # que no pasó por Compute se filtra ahora con los controles y se etiqueta con ellos.
                ys_f = c.ys_filtered
                rec = self._filters.get(c)
                if ys_f is None or len(ys_f) != len(c.ys) or rec is None:
                    ys_f = _apply_filter(c.ys, fkind, fwin) if fkind != "none" else c.ys
                    rec = (fkind, fwin)
                kind_c, win_c = rec
                for i in range(len(c.xs)):
                    curves.append(
                        [exp.name, c.name, i, c.xs[i], c.ys[i], ys_f[i], kind_c,
                         win_c if kind_c != "none" else None]
                    )
        try:
            write_workbook(
                path,
                {
                    "peaks": [
                        ["experiment", "run", "type", "E_peak_V", "I_peak_A", "height_A"]
                    ] + rows,
                    "curves": curves,
                    "settings": self._settings_rows(),
                },
            )
        except Exception as e:
            self._set_status(f"Export error: {e}")
            return
        stale = self._compute_sig is not None and self._compute_sig != self._controls_sig()
        self._set_status(
            ("Controls changed since Compute: the file keeps the settings used by Compute. "
             if stale else "")
            + f"Exported {len(rows)} peak(s) and {len(curves) - 1} curve point(s) "
            f"→ {os.path.basename(path)}."
            + self._range_hint()
        )


__author__ = "Edisson A. Naula"
__date__ = "2026-07-03"
