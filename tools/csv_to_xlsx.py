# -*- coding: utf-8 -*-
"""Convierte los CSV que guardaba la app al formato actual: un .xlsx por guardado.

Uso (desde la raíz del repo, en Windows o en el Pi)::

    python tools/csv_to_xlsx.py <carpeta> [--dry-run] [--force]

Recorre <carpeta> recursivamente y escribe cada .xlsx AL LADO de sus CSV; nunca
borra ni modifica los CSV (docs/almacenamiento_por_experimento.md):

- Corrida PCR: ``<slug>_temperature_data_<ts>.csv`` + ``_photodetector_data_`` +
  ``_photodetector_raw_`` → ``<slug>_pcr_data_<ts>.xlsx`` (hojas metadata,
  temperature, photodetector, photodetector_raw; las que existan). La metadata vieja
  era un string en una celda: va completo a la fila ``prefix`` (partirlo por "-" no
  es confiable: la fecha y los negativos llevan guiones). Sin hoja settings: esas
  corridas no la registraban.
- Exports de análisis (detectados por encabezado): PCR ``bundle`` + ``rates``, SQWV
  ``peaks`` + ``curves``, CV ``results`` + ``curves``, EIS ``spectra`` + ``nyquist``.
- Guardados de un solo CSV (EmStat ``<method>_data_*``, photoreceptor, temperature
  log, Quick Control ``unified_*``, ``data_temps``) → hoja ``data``.

Lo que no reconoce lo lista y lo deja. Si el .xlsx ya existe lo salta (``--force``
lo reescribe).
"""

import argparse
import csv
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from templates.xlsx_io import kv_rows, num_or_text, write_workbook  # noqa: E402

__author__ = "Edisson A. Naula"
__date__ = "$ 26/10/2026 at 10:00 a.m. $"


PCR_RE = re.compile(
    r"^(?P<prefix>.*?)(?P<kind>temperature_data|photodetector_data|photodetector_raw)"
    r"_(?P<ts>\d{8}_\d{6})\.csv$"
)
SINGLE_RE = re.compile(
    r"^((cv|sqwv|eis|ca)_data_|photoreceptor_data_|temperature_log_|unified_|data_temps)",
    re.IGNORECASE,
)
# Columnas de la hoja temperature cuando la metadata vieja no trae "cols:".
TEMP_COLS = ["primary", "secondary", "t_s", "cycle", "phase", "heater_on_s"]
COLS_RE = re.compile(r"cols: (.*?)(?=-[a-z_]+:|$)")


def _read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return [row for row in csv.reader(f, skipinitialspace=True) if row]


def _cell(text):
    """Texto del CSV → valor de celda: vacío/"None" (f-string de un None) → vacía."""
    text = text.strip()
    if text in ("", "None"):
        return None
    return num_or_text(text)


def _typed(rows):
    return [[_cell(c) for c in row] for row in rows]


def _header(rows):
    return [h.strip() for h in rows[0]] if rows else []


# --------------------------------------------------------------------- PCR
def _pcr_sheets(files):
    """``files``: {kind: path} de una misma corrida."""
    sheets = {}
    if "temperature_data" in files:
        rows = _read_csv(files["temperature_data"])
        prefix = rows[0][0] if rows and rows[0] else ""
        data = _typed(rows[1:])
        m = COLS_RE.search(prefix)
        ncols = max((len(r) for r in data), default=1)
        cols = m.group(1).split("|") if m else TEMP_COLS[:ncols]
        sheets["metadata"] = kv_rows([("prefix", prefix), ("converted_from", "csv")])
        sheets["temperature"] = [cols] + data
    if "photodetector_data" in files:
        rows = _read_csv(files["photodetector_data"])
        # Mismo formato que PcrFrame: [cycle, photodetector, timeouts]; fila k = ciclo k.
        body = rows[1:] if rows and _header(rows)[:1] == ["photodetector"] else rows
        sheets["photodetector"] = [["cycle", "photodetector", "timeouts"]] + [
            [k] + [_cell(c) for c in row[:2]] for k, row in enumerate(body, start=1)
        ]
    if "photodetector_raw" in files:
        rows = _read_csv(files["photodetector_raw"])
        sheets["photodetector_raw"] = [_header(rows)] + _typed(rows[1:])
    return sheets


# ------------------------------------------------------- Exports de análisis
def _export_kind(header):
    if header[:1] == ["record"]:
        return "pcr_bundle"
    if header[:5] == ["experiment", "run", "type", "E_peak_V", "I_peak_A"]:
        return "sqwv_peaks"
    if header[:3] == ["experiment", "cycle", "exp_idx"]:
        return "cv_results"
    if "Rs_ohm" in header and "spectrum" in header:
        return "eis_nyquist"
    return None


# hoja principal → (sufijo del hermano, hoja del hermano)
EXPORT_SHEETS = {
    "pcr_bundle": ("bundle", "_rates", "rates"),
    "sqwv_peaks": ("peaks", "_curves", "curves"),
    "cv_results": ("results", "_curves", "curves"),
    "eis_nyquist": ("nyquist", "_spectra", "spectra"),
}
SIBLING_SHEET = {"_rates": "rates", "_curves": "curves", "_spectra": "spectra"}


def _plan(folder):
    """Lista de (xlsx destino, {hoja: filas-callable}, [csv fuente]) + no reconocidos."""
    jobs, unknown = [], []
    for root, _dirs, names in os.walk(folder):
        csvs = sorted(n for n in names if n.lower().endswith(".csv"))
        used = set()
        # 1) Corridas PCR agrupadas por (prefijo, timestamp).
        runs = {}
        for n in csvs:
            m = PCR_RE.match(n)
            if m:
                runs.setdefault((m["prefix"], m["ts"]), {})[m["kind"]] = os.path.join(root, n)
                used.add(n)
        for (prefix, ts), files in runs.items():
            out = os.path.join(root, f"{prefix}pcr_data_{ts}.xlsx")
            jobs.append((out, lambda f=files: _pcr_sheets(f), sorted(files.values())))
        # 2) Exports de análisis: archivo principal (por encabezado) + hermano.
        for n in csvs:
            if n in used:
                continue
            path = os.path.join(root, n)
            try:
                kind = _export_kind(_header(_read_csv(path)[:1]))
            except (OSError, UnicodeDecodeError, csv.Error):
                kind = None
            if kind is None:
                continue
            base = n[:-4]
            main_sheet, suffix, sib_sheet = EXPORT_SHEETS[kind]
            sib = f"{base}{suffix}.csv"
            sources = [path]
            if sib in csvs:
                sources.append(os.path.join(root, sib))
                used.add(sib)
            used.add(n)
            jobs.append(
                (
                    os.path.join(root, f"{base}.xlsx"),
                    lambda s=sources, a=main_sheet, b=sib_sheet: {
                        a: _typed(_read_csv(s[0])),
                        **({b: _typed(_read_csv(s[1]))} if len(s) > 1 else {}),
                    },
                    sources,
                )
            )
        # 3) Hermanos sin principal (_curves/_spectra/_rates sueltos) y CSV únicos.
        for n in csvs:
            if n in used:
                continue
            path = os.path.join(root, n)
            base = n[:-4]
            sib_suffix = next((s for s in SIBLING_SHEET if base.endswith(s)), None)
            if sib_suffix is not None:
                sheet = SIBLING_SHEET[sib_suffix]
                out = os.path.join(root, f"{base[: -len(sib_suffix)]}.xlsx")
            elif SINGLE_RE.match(n):
                sheet, out = "data", os.path.join(root, f"{base}.xlsx")
            else:
                unknown.append(path)
                continue
            jobs.append((out, lambda p=path, sh=sheet: {sh: _typed(_read_csv(p))}, [path]))
    return jobs, unknown


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("folder")
    ap.add_argument("--dry-run", action="store_true", help="solo listar, no escribir")
    ap.add_argument("--force", action="store_true", help="reescribir .xlsx existentes")
    args = ap.parse_args()

    jobs, unknown = _plan(args.folder)
    done = skipped = failed = 0
    for out, build, sources in jobs:
        rel = os.path.relpath(out, args.folder)
        if os.path.exists(out) and not args.force:
            print(f"skip (exists)  {rel}")
            skipped += 1
            continue
        if args.dry_run:
            print(f"would write    {rel}  <- {', '.join(os.path.basename(s) for s in sources)}")
            continue
        try:
            sheets = build()
            write_workbook(out, sheets)
        except Exception as e:
            print(f"FAILED         {rel}: {e}")
            failed += 1
            continue
        print(f"wrote          {rel}  [{', '.join(sheets)}]")
        done += 1
    for path in unknown:
        print(f"not recognized {os.path.relpath(path, args.folder)}")
    print(
        f"\n{done} written, {skipped} skipped, {failed} failed, "
        f"{len(unknown)} not recognized (CSV files untouched)."
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
