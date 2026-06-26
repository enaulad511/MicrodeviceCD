# -*- coding: utf-8 -*-
"""Mixin compartido para la barra de "proyectos" de los frames electroquímicos.

Implementa TODA la cola de UI común (combobox + botones Save/Import/Export/Delete,
diálogo "Guardar como", detección de cambios sin guardar, mapeo de nombre legible
y la cascada de auto-carga) contra el backend genérico ``templates.electrochem_projects``.

Cada frame anfitrión (CVFrame / SWVFrame / EISFrame) solo aporta tres cosas:

* ``self.project_method``  -> "cv" | "sqwv" | "eis"
* ``collect_values()``     -> dict con el estado COMPLETO del formulario
* ``apply_values(values)`` -> vuelca un dict en los widgets del formulario

y, en su rutina de envío, llama a ``self.snapshot_current_run()`` para que
``_last_run`` refleje siempre lo último ejecutado (decisión Q7).

El anfitrión debe ser un ``ttk.Frame`` (usa ``self.winfo_toplevel``,
``self.wait_window``, ``ttk.Toplevel(self)``).
"""

from typing import TYPE_CHECKING

import ttkbootstrap as ttk

from templates import electrochem_projects as epp
from templates.constants import font_entry

__author__ = "Edisson A. Naula"
__date__ = "$ 22/06/2026 at 11:30 a.m. $"


# El mixin SIEMPRE se mezcla con un ttk.Frame (CVFrame/SWVFrame/EISFrame). En
# tiempo de ejecución es un mixin puro (base object); para el type checker se
# declara como Frame para que conozca winfo_toplevel/wait_window y acepte
# `parent=self` en los diálogos de tkinter.
if TYPE_CHECKING:
    _Base = ttk.Frame
else:
    _Base = object


class ElectrochemProjectBarMixin(_Base):
    """Barra de proyectos reutilizable. Ver el docstring del módulo."""

    # El anfitrión define estos; se declaran aquí para que el mixin sea autónomo.
    project_method: str = ""

    # --------------------------------------------------------------- #
    # Hooks que el frame anfitrión DEBE implementar.
    # --------------------------------------------------------------- #
    def collect_values(self) -> dict:
        raise NotImplementedError

    def apply_values(self, values: dict) -> None:
        raise NotImplementedError

    # --------------------------------------------------------------- #
    # Construcción de la barra
    # --------------------------------------------------------------- #
    def build_project_bar(self, master):
        """Crea (y devuelve) el LabelFrame de la barra de proyecto.

        Inicializa también el estado interno del mixin. Llamar UNA vez antes de
        ``load_initial_project``.
        """
        # Estado interno (proyecto activo + baseline para detectar ediciones).
        self.active_project_name = None
        self._loaded_snapshot: dict = {}
        self.cbo_project: "ttk.Combobox | None" = None
        self._proj_status_var = ttk.StringVar(value="")

        frame = ttk.LabelFrame(master, text="Project")
        frame.configure(style="Custom.TLabelframe")
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="Project:", style="Custom.TLabel").grid(
            row=0, column=0, padx=5, pady=5, sticky="w"
        )
        self.cbo_project = ttk.Combobox(frame, state="readonly", font=font_entry)
        self.cbo_project.grid(row=0, column=1, padx=5, pady=5, sticky="we")
        self.cbo_project.bind("<<ComboboxSelected>>", self._on_project_selected)

        ttk.Button(
            frame, text="💾Save", style="success.TButton", command=self._on_save_as
        ).grid(row=0, column=2, padx=3, pady=5, sticky="we")
        ttk.Button(
            frame, text="📁Import", style="info.TButton", command=self._on_import
        ).grid(row=0, column=3, padx=3, pady=5, sticky="we")
        ttk.Button(
            frame, text="📤Export", style="info.TButton", command=self._on_export
        ).grid(row=0, column=4, padx=3, pady=5, sticky="we")
        ttk.Button(
            frame, text="🗑️Delete", style="danger.TButton", command=self._on_delete
        ).grid(row=0, column=5, padx=3, pady=5, sticky="we")

        ttk.Label(
            frame, textvariable=self._proj_status_var, style="Custom.TLabel", anchor="w"
        ).grid(row=1, column=0, columnspan=6, padx=5, pady=(0, 4), sticky="we")
        return frame

    # --------------------------------------------------------------- #
    # Estado / status
    # --------------------------------------------------------------- #
    def project_status(self, msg: str):
        """Muestra un mensaje en la barra de proyecto. Sobrescribible."""
        if getattr(self, "_proj_status_var", None) is not None:
            self._proj_status_var.set(msg)
        else:
            print(msg)

    def _display_name(self, name):
        return epp.LAST_RUN_LABEL if name == epp.LAST_RUN_KEY else name

    def _internal_name(self, display):
        return epp.LAST_RUN_KEY if display == epp.LAST_RUN_LABEL else display

    def _refresh_project_list(self, select=None):
        method = self.project_method
        names = []
        if epp.has_last_run(method):
            names.append(epp.LAST_RUN_KEY)
        names.extend(epp.project_names(method))
        if self.cbo_project is None:
            return
        self.cbo_project["values"] = [self._display_name(n) for n in names]
        target = select if select is not None else self.active_project_name
        if target in names:
            self.cbo_project.set(self._display_name(target))

    def _has_unsaved_changes(self):
        if not self._loaded_snapshot:
            return False
        return self.collect_values() != self._loaded_snapshot

    def has_unsaved_changes(self):
        """Público: el padre podría consultarlo (ver gap Q13). No se usa hoy."""
        return self._has_unsaved_changes()

    # --------------------------------------------------------------- #
    # Carga
    # --------------------------------------------------------------- #
    def _do_load_project(self, name, values, persist_last_used=True):
        method = self.project_method
        normalized = {k: str(values.get(k, "")) for k in epp.entry_keys(method)}
        self.apply_values(normalized)
        self.active_project_name = name
        self._loaded_snapshot = self.collect_values()
        if persist_last_used:
            epp.set_last_used(method, name)
        self._refresh_project_list(select=name)
        self.project_status(f"Project loaded: {self._display_name(name)}")

    def load_initial_project(self):
        """Cascada de auto-carga (_last_used -> _last_run -> named -> Default)."""
        name, values = epp.resolve_initial(self.project_method)
        # No persistimos last_used aquí: solo refleja lo ya elegido.
        self._do_load_project(name, values, persist_last_used=False)

    def _on_project_selected(self, _event=None):
        if self.cbo_project is None:
            return
        display = self.cbo_project.get()
        name = self._internal_name(display)
        if name == self.active_project_name:
            return
        if self._has_unsaved_changes():
            from tkinter import messagebox

            if not messagebox.askyesno(
                "Unsaved changes",
                f"Discard unsaved changes and load '{display}'?",
                parent=self,
            ):
                self._refresh_project_list(select=self.active_project_name)
                return
        values = epp.get_project(self.project_method, name)
        if values is None:
            self.project_status(f"Project not found: {display}")
            return
        self._do_load_project(name, values)

    # --------------------------------------------------------------- #
    # Guardar / borrar / importar / exportar
    # --------------------------------------------------------------- #
    def _on_save_as(self):
        method = self.project_method
        values = self.collect_values()
        ok, msg = epp.validate_values(method, values)
        if not ok:
            self.project_status(f"Cannot save: {msg}")
            return
        suggested = (
            "" if self.active_project_name in (None, epp.LAST_RUN_KEY)
            else self.active_project_name
        )
        name = self._ask_project_name(suggested)
        if not name:
            return
        name = name.strip()
        if not name or epp.is_reserved(name):
            self.project_status("Invalid project name.")
            return
        if epp.get_project(method, name) is not None:
            from tkinter import messagebox

            if not messagebox.askyesno(
                "Overwrite project",
                f"Project '{name}' already exists. Overwrite?",
                parent=self,
            ):
                return
        if epp.save_project(method, name, values):
            self._do_load_project(name, values)
            self.project_status(f"Project saved: {name}")
        else:
            self.project_status("Error saving project.")

    def _on_delete(self):
        method = self.project_method
        name = self.active_project_name
        if name is None or epp.is_reserved(name):
            self.project_status("Select a saved project to delete.")
            return
        from tkinter import messagebox

        if not messagebox.askyesno(
            "Delete project", f"Delete project '{name}'?", parent=self
        ):
            return
        if epp.delete_project(method, name):
            n, v = epp.resolve_initial(method)
            self._do_load_project(n, v, persist_last_used=False)
            self.project_status(f"Project deleted: {name}")
        else:
            self.project_status("Error deleting project.")

    def _on_import(self):
        from tkinter import filedialog

        method = self.project_method
        path = filedialog.askopenfilename(
            title="Import project",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            parent=self,
        )
        if not path:
            return
        result = epp.import_project(method, path)
        if not result.get("ok"):
            self.project_status(f"Error: {result.get('error', 'invalid project file.')}")
            return
        values = result["values"]
        ok, msg = epp.validate_values(method, values)
        if not ok:
            self.project_status(f"Cannot import: {msg}")
            return
        name = self._ask_project_name(result.get("name", "Imported"))
        if not name:
            return
        name = name.strip()
        if not name or epp.is_reserved(name):
            self.project_status("Invalid project name.")
            return
        if epp.get_project(method, name) is not None:
            from tkinter import messagebox

            if not messagebox.askyesno(
                "Overwrite project",
                f"Project '{name}' already exists. Overwrite?",
                parent=self,
            ):
                return
        if epp.save_project(method, name, values):
            self._do_load_project(name, values)
            self.project_status(f"Project imported: {name}")
        else:
            self.project_status("Error importing project.")

    def _on_export(self):
        from tkinter import filedialog

        method = self.project_method
        name = self.active_project_name
        if name is None:
            self.project_status("No project to export.")
            return
        default_name = "last_run" if name == epp.LAST_RUN_KEY else name
        path = filedialog.asksaveasfilename(
            title="Export project",
            defaultextension=".json",
            initialfile=f"{method}_{default_name}.json",
            filetypes=[("JSON files", "*.json")],
            parent=self,
        )
        if not path:
            return
        if epp.export_project(method, name, path):
            self.project_status(f"Project exported: {self._display_name(name)}")
        else:
            self.project_status("Error exporting project.")

    def snapshot_current_run(self):
        """Vuelca el estado actual del formulario a _last_run y refresca la lista.

        Llamar al inicio de la rutina de envío del frame (decisión Q7).
        """
        method = self.project_method
        epp.snapshot_last_run(method, self.collect_values())
        self._refresh_project_list()

    # --------------------------------------------------------------- #
    # Diálogo "Guardar como" (replica el de PcrFrame, con onboard en el Pi)
    # --------------------------------------------------------------- #
    def _ask_project_name(self, suggested=""):
        dialog = ttk.Toplevel(self)
        dialog.title("Save project as")
        dialog.transient(self.winfo_toplevel())
        result: dict = {"name": None}

        ttk.Label(dialog, text="Project name:", style="Custom.TLabel").grid(
            row=0, column=0, columnspan=2, padx=10, pady=(10, 5), sticky="w"
        )
        entry = ttk.Entry(dialog, font=font_entry, width=28)
        entry.grid(row=1, column=0, columnspan=2, padx=10, pady=5, sticky="we")
        entry.insert(0, suggested)
        entry.bind("<FocusIn>", lambda _e: self._launch_os_keyboard())

        def _accept():
            result["name"] = entry.get()
            dialog.destroy()

        def _cancel():
            dialog.destroy()

        ttk.Button(dialog, text="OK", style="success.TButton", command=_accept).grid(
            row=2, column=0, padx=10, pady=10, sticky="we"
        )
        ttk.Button(dialog, text="Cancel", style="secondary.TButton", command=_cancel).grid(
            row=2, column=1, padx=10, pady=10, sticky="we"
        )
        entry.bind("<Return>", lambda _e: _accept())
        dialog.columnconfigure(0, weight=1)
        dialog.columnconfigure(1, weight=1)
        entry.focus_set()
        dialog.grab_set()
        self.wait_window(dialog)
        return result["name"]

    def _launch_os_keyboard(self):
        # onboard solo existe en el Pi; en dev (Windows) falla silenciosamente.
        try:
            from templates.utils import show_keyboard

            show_keyboard()
        except Exception:
            pass
