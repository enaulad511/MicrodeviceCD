# -*- coding: utf-8 -*-
import ttkbootstrap as ttk

from ui.analysis.peaks import PeakAnalysisFrame
from ui.analysis.sqwv import SqwvAnalysisFrame
from ui.analysis.eis import EISAnalysisFrame
from ui.analysis.pcr import PcrAnalysisFrame


# ---------------------------------------------------------------------------
# Ventana: shell con notebook por metodo (Peaks CV - SQWV - EIS - PCR)
# ---------------------------------------------------------------------------


class AnalysisWindow(ttk.Toplevel):
    """Ventana de análisis con un notebook por método: picos (CV), SQWV, EIS y PCR.
    La pestaña activa por defecto la decide el método del plotter que la lanzó (EIS →
    pestaña EIS; SQWV → SQWV) o, si trae una corrida PCR en memoria, la pestaña PCR."""

    def __init__(self, master, plotter=None, pcr_frame=None, **kwargs):
        super().__init__(master, **kwargs)
        self.title("Curve Analysis")
        self.geometry("1180x860")
        self.parent = master

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=ttk.BOTH, expand=True)
        self.peaks = PeakAnalysisFrame(self.notebook, owner=self, plotter=plotter)
        self.sqwv = SqwvAnalysisFrame(self.notebook, owner=self, plotter=plotter)
        self.eis = EISAnalysisFrame(self.notebook, owner=self, plotter=plotter)
        self.pcr = PcrAnalysisFrame(self.notebook, owner=self, plotter=plotter, pcr_frame=pcr_frame)
        self.notebook.add(self.peaks, text="Peaks (CV)")
        self.notebook.add(self.sqwv, text="SQWV Peaks")
        self.notebook.add(self.eis, text="EIS")
        self.notebook.add(self.pcr, text="PCR")
        method = getattr(plotter, "method", "") if plotter is not None else ""
        if method == "eis":
            self.notebook.select(self.eis)
        elif method == "sqwv":
            self.notebook.select(self.sqwv)
        elif pcr_frame is not None and len(getattr(pcr_frame, "data_temperature", []) or []):
            # Abierta desde el shell general con una corrida PCR en memoria.
            self.notebook.select(self.pcr)

        # Atajos de teclado enrutados a la pestaña activa (Peaks, SQWV, EIS o PCR).
        self.bind("<Control-l>", lambda _e: self._active_load())
        self.bind("<Control-i>", lambda _e: self._active_import())
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def _active_tab(self):
        """Frame de la pestaña actualmente seleccionada en el notebook."""
        try:
            return self.notebook.nametowidget(self.notebook.select())
        except Exception:
            return self.peaks

    def _active_load(self):
        self._active_tab().load_csv()

    def _active_import(self):
        tab = self._active_tab()
        if tab is self.eis:
            self.eis.import_spectra()
        elif tab is self.sqwv:
            self.sqwv.import_analysis()
        elif tab is self.pcr:
            self.pcr.import_analysis()
        else:
            self.peaks.import_analysis()

    def on_close(self):
        try:
            if hasattr(self.parent, "_on_analysis_window_closed"):
                self.parent._on_analysis_window_closed()
        except Exception:
            pass
        self.destroy()


__author__ = "Edisson A. Naula"
__date__ = "2026-07-03"
