# -*- coding: utf-8 -*-
from templates.utils import write_settings_to_file
from ttkbootstrap.scrolled import ScrolledFrame
from templates.constants import font_entry
from templates.utils import read_settings_from_file
import ttkbootstrap as ttk

from ui.KeyboardFrame import NumericKeyboard

__author__ = "Edisson Naula"
__date__ = "$ 19/11/2025 at 11:27 $"


def create_widgets_configuration(parent):
    entries = {}
    entry_widgets = []
    settings = read_settings_from_file()
    index = 0
    for k, v in settings.items():
        if k in ["version"]:
            continue
        if isinstance(v, dict):
            subframe = ttk.LabelFrame(parent, text=f"{k}")
            subframe.grid(row=index, column=0, padx=10, pady=10, sticky="nswe", columnspan=2)
            subframe.columnconfigure((0, 1), weight=1)

            index += 1
            subindex = 0
            entries[k] = {}
            for k1, v1 in v.items():
                ttk.Label(subframe, text=f"{k1}:", style="Custom.TLabel").grid(
                    row=subindex, column=0, padx=5, pady=5, sticky="nswe"
                )
                svar = ttk.StringVar(value=str(v1))
                entry = ttk.Entry(subframe, font=font_entry, textvariable=svar)
                entry.grid(row=subindex, column=1, padx=5, pady=5, sticky="nswe")
                entries[k][k1] = svar
                entry_widgets.append(entry)
                subindex += 1
        else:
            index += 1
            ttk.Label(parent, text=f"{k}:", style="Custom.TLabel").grid(
                row=index, column=0, padx=5, pady=5, sticky="nswe"
            )
            svar = ttk.StringVar(value=str(v))
            entry = ttk.Entry(parent, font=font_entry, textvariable=svar)
            entry.grid(row=index, column=1, padx=5, pady=5, sticky="nswe")
            entries[k] = svar
            entry_widgets.append(entry)
    return entries, entry_widgets


class ConfigFrame(ttk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Configuration Settings")
        self.resizable(True, True)
        self.geometry("500x400")
        self.parent = parent
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        # self.rowconfigure((0, 1), weight=1)
        content_frame = ScrolledFrame(self)
        content_frame.grid(row=0, column=0, sticky="nswe")
        content_frame.columnconfigure((0, 1), weight=1)

        self.entries, entry_widgets = create_widgets_configuration(content_frame)
        self.keyboard = NumericKeyboard(self)
        self.keyboard.place_forget()
        for entry in entry_widgets:
            entry.bind("<FocusIn>", self._on_entry_focus)
        ttk.Button(
            self,
            text="Save Settings",
            style="CustomPrimary.TButton",
            command=self.save_settings,
        ).grid(row=1, column=0, columnspan=2, pady=10, padx=5, sticky="n")
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def _on_entry_focus(self, event):
        entry = event.widget
        self.keyboard.set_target(entry)
        kb_w, kb_h = 360, 250
        self.update_idletasks()
        x = entry.winfo_rootx() - self.winfo_rootx()
        y = entry.winfo_rooty() - self.winfo_rooty() + entry.winfo_height()
        max_x = self.winfo_width() - kb_w
        if max_x > 0:
            x = max(0, min(x, max_x))
        max_y = self.winfo_height() - kb_h
        if max_y > 0 and y > max_y:
            y = entry.winfo_rooty() - self.winfo_rooty() - kb_h
        self.keyboard.place(x=x, y=y, width=kb_w, height=kb_h)
        self.keyboard.lift()

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
        ads_fsr = new_settings.get("ads_fsr")
        if ads_fsr is not None and self.parent.ads is not None:
            self.parent.ads.set_fsr(ads_fsr)

    def on_close(self):
        self.save_settings()
        self.parent.config_frame = None
        self.destroy()
