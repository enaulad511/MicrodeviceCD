# -*- coding: utf-8 -*-
"""Modelo de datos y helpers compartidos por las pestanas de analisis de picos
(CV/SWV y SQWV): CycleCurve, Experiment y el filtro _apply_filter.

Importar plt DESDE este modulo garantiza que matplotlib.use("TkAgg") ya corrio
antes del primer import de pyplot en todo el paquete ui.analysis."""
import matplotlib

matplotlib.use("TkAgg")

import matplotlib.pyplot as plt  # re-exportado; su import aqui fija el backend
import numpy as np


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


__author__ = "Edisson A. Naula"
__date__ = "2026-07-03"
