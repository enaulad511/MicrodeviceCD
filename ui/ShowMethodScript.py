# -*- coding: utf-8 -*-

import ttkbootstrap as ttk

__author__ = "Edisson A. Naula"
__date__ = "$ 04/06/2026 at 12:00 p.m. $"


class ShowMethodScript(ttk.Toplevel):
    def __init__(self, parent, script: str):
        super().__init__(parent)
        self.title("Method Script")
        self.parent = parent
        # self.geometry("600x400")
        self.script_box = ttk.ScrolledText(self, height=20)
        self.script_box.pack(fill="both", expand=True, padx=10, pady=10)
        self.script_box.insert("end", script)
        self.script_box.configure(state="disabled")
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def on_close(self):
        self.parent.on_close_script_window()
        self.destroy()
