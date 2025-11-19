# -*- coding: utf-8 -*-
from templates.utils import write_settings_to_file
from ttkbootstrap.scrolled import ScrolledFrame
from templates.constants import font_entry
from templates.utils import read_settings_from_file
import ttkbootstrap as ttk
__author__ = "Edisson Naula"
__date__ = "$ 19/11/2025 at 11:27 $"


def create_widgets_configuration(parent):
    entries = {}
    settings = read_settings_from_file()
    index = 0
    for k, v in settings.items():
        if k in ["version"]:
            continue
        if isinstance(v, dict):
            subframe = ttk.LabelFrame(parent, text=f"{k}")
            subframe.grid(row=index, column=0, padx=10, pady=10, sticky="nswe")
            index += 1
            subindex = 0
            entries[k] = {}
            for k1, v1 in v.items():
                ttk.Label(subframe, text=f"{k1}:", style="Custom.TLabel").grid(
                    row=subindex, column=0, padx=5, pady=5, sticky="w"
                )
                svar = ttk.StringVar(value=str(v1))
                entry = ttk.Entry(subframe, font=font_entry, textvariable=svar)
                entry.grid(row=subindex, column=1, padx=5, pady=5)
                entries[k][k1] = svar
                subindex += 1
        else:
            ttk.Label(parent, text=f"{k}:", style="Custom.TLabel").grid(
                row=index, column=0, padx=5, pady=5, sticky="w"
            )
            svar = ttk.StringVar(value=str(v))
            entry = ttk.Entry(parent, font=font_entry, textvariable=svar)
            entry.grid(row=index, column=1, padx=5, pady=5)
    return entries


class ConfigFrame(ttk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Configuration Settings")
        self.parent = parent
        content_frame = ScrolledFrame(self)
        content_frame.grid(row=0, column=0, sticky="nswe")
        self.entries = create_widgets_configuration(content_frame)
        ttk.Button(
            self,
            text="Save Settings",
            style="info.TButton",
            command=self.save_settings,
        ).grid(row=1, column=0, columnspan=2, pady=10, padx=5, sticky="nswe")
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def save_settings(self):
        new_settings = {}
        for k, v in self.entries.items():
            if isinstance(v, dict):
                new_settings[k] = {}
                for k1, v1 in v.items():
                    try:
                        new_settings[k][k1] = float(v1.get())
                    except ValueError:
                        new_settings[k][k1] = v1.get()
            else:
                try:
                    new_settings[k] = float(v.get())
                except ValueError:
                    new_settings[k] = v.get()
        write_settings_to_file(new_settings)
    
    def on_close(self):
        self.save_settings()
        self.parent.config_frame = None
        self.destroy()
        