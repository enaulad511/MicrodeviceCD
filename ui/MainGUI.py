# -*- coding: utf-8 -*-
from ui.ConfigFrame import ConfigFrame
__author__ = "Edisson A. Naula"
__date__ = "$ 08/10/2025  at 09:35 a.m. $"

import platform

import ttkbootstrap as ttk
from PIL import Image, ImageTk

from templates.constants import (
    font_buttons,
    font_labels,
    font_entry,
    font_labels_frame,
    font_tabs,
    tab_icons,
    tab_texts,
    main_tabs_texts,
    main_tabs_icons,
)
from ui.DiscFrame import ControlDiscFrame
from ui.ElectrochemicalFrame import ElectrochemicalFrame
from ui.FluorecenseLEDFrame import ControlFluorescenteFrame
from ui.FrameInit import StartImageFrame
from ui.LEDFrame import ControleLEDFrame
from ui.PcrFrame import PCRFrame
from ui.PhotoreceptorFrame import PhotoreceptorFrame


def configure_styles():
    style = ttk.Style()
    style.configure("Custom.TButton", font=font_buttons)        # pyrefly: ignore
    style.configure("Custom.TLabel", font=font_labels)      # pyrefly: ignore
    style.configure("Custom.TEntry", font=font_entry)       # pyrefly: ignore
    style.configure("Custom.TLabelframe.Label", font=font_labels_frame)     # pyrefly: ignore
    style.configure("Custom.TNotebook.Tab", font=font_tabs)     # pyrefly: ignore
    style.configure("Custom.TCombobox", font=font_entry)        # pyrefly: ignore
    style.configure("info.TButton", font=font_buttons)      # pyrefly: ignore
    style.configure("success.TButton", font=("Arial", 18))      # pyrefly: ignore
    style.configure("danger.TButton", font=("Arial", 18))       # pyrefly: ignore
    style.configure("Custom.Treeview", font=("Arial", 18), rowheight=30)        # pyrefly: ignore
    style.configure("Custom.Treeview.Heading", font=("Arial", 18, "bold"))      # pyrefly: ignore
    style.configure("success.TButton", font=font_buttons)       # pyrefly: ignore
    style.configure("primary.TButton", font=font_buttons)       # pyrefly: ignore
    style.configure("secondary.TButton", font=font_buttons)     # pyrefly: ignore
    return style


def load_images():
    img_path_dict = {
        "arrow_up": r"files/img/arrow_up.png",
        "arrow_down": r"files/img/arrow_down.png",
        "rotate": r"files/img/rotate-icon.png",
        "rotate_end": r"files/img/rotate-icon-tope.png",
        "config": r"files/img/config.png",
        "save": r"files/img/save_btn.png",
        "control": r"files/img/remote-control.jpg",
        "link": r"files/img/link.png",
        "default": r"files/img/no_image.png",
    }
    images = {}
    for key, path in img_path_dict.items():
        try:
            img = Image.open(path)
        except FileNotFoundError:
            path = img_path_dict["default"]
            img = Image.open(path)
        img = img.resize((50, 50))
        images[key] = ImageTk.PhotoImage(img)
    return images


class MainGUI(ttk.Window):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.frame_m_control = None
        self.config_frame = None
        self.project_key = None
        self.title("\u03BCAA")
        self.style_gui = configure_styles()
        # --------------------Start Animation -------------------
        # self.show_gif_toplevel()
        self.after(0, self.maximize_window)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        # self.images = load_images()
        # --------------------notebook-------------------
        self.connected = ttk.BooleanVar(value=False)
        self.frame_content = ttk.Frame(self)
        self.frame_content.grid(
            row=0, column=0, sticky="nsew", padx=(5, 10), pady=(10, 10)
        )
        self.frame_content.columnconfigure(0, weight=1)
        self.frame_content.rowconfigure(0, weight=1)
        # ------------------main tabs-------------------
        self.main_notebook = ttk.Notebook(self.frame_content)
        self.main_notebook.configure(style="Custom.TNotebook")
        self.main_notebook.grid(row=0, column=0, sticky="nsew")
        self.main_notebook.columnconfigure(0, weight=1)
        self.main_notebook.rowconfigure(0, weight=1)
        self.main_notebook.bind("<<NotebookTabChanged>>", self.on_main_tab_changed)

        # ------------------PCR tab-------------------
        self.tab_pcr = PCRFrame(self.main_notebook)
        self.main_notebook.add(self.tab_pcr, text=main_tabs_texts[0], padding=10)
        # ------------------Electrochemical tab-------------------
        self.tab_electrochemical = ElectrochemicalFrame(self.main_notebook)
        self.main_notebook.add(self.tab_electrochemical, text=main_tabs_texts[1], padding=10)
        # ------------------Manual Control tab-------------------
        self.tab_manual_control = ttk.Frame(self.main_notebook)
        self.main_notebook.add(self.tab_manual_control, text=main_tabs_texts[2], padding=10)
        self.tab_manual_control.columnconfigure(0, weight=1)
        self.tab_manual_control.rowconfigure(0, weight=1)
        # ------------------Manual Control tabs-------------------
        self.notebook = ttk.Notebook(self.tab_manual_control)
        self.notebook.configure(style="Custom.TNotebook")
        self.notebook.grid(row=0, column=0, sticky="nsew")
        self.notebook.columnconfigure(0, weight=1)
        self.notebook.rowconfigure(0, weight=1)
        self.callbacks_manual_control = {
            # "change_tab_text": self.change_tab_text,
            # "change_title": self.change_title,
            # "init_tabs": self.init_tabs_callback,
            # "change_project": self.change_project_key,
            # "test_connection_callback":  self.test_connection,
            # "save_project_callback": self.save_project,
            # "on_geometry_changed": self.on_geometry_changed,
        }
        self.notebook.bind("<<NotebookTabChanged>>", self.on_tab_changed)
        print("init tabs")

        self.tab1 = ControleLEDFrame(self.notebook)
        self.notebook.add(self.tab1, text=tab_texts[0])
        print("init tabs LED")

        self.tab2 = ControlFluorescenteFrame(self.notebook)
        self.notebook.add(self.tab2, text=tab_texts[1])
        print("init tabs Fluorescence")

        self.tab3 = ControlDiscFrame(self.notebook)
        self.notebook.add(self.tab3, text=tab_texts[2])
        print("init tabs Disc")

        self.tab4 = PhotoreceptorFrame(self.notebook)
        self.notebook.add(self.tab4, text=tab_texts[3])
        print("init tabs Photoreceptor")
        # # --------------------footer-------------------
        self.frame_footer = ttk.Frame(self)
        self.frame_footer.grid(row=1, column=0, sticky="ew", padx=15, pady=15)
        self.txt_connected = ttk.StringVar(value="Disconnected")
        ttk.Label(
            self.frame_footer,
            textvariable=self.txt_connected,
            font=("Arial", 18),
            style="Custom.TLabel",
        ).grid(row=0, column=0, sticky="ns", padx=15, pady=15)
        ttk.Button(
            self.frame_footer,
            text="Configuration",
            style="success.TButton",
            command=self.open_configurations,
        ).grid(row=0, column=1, sticky="ns", padx=15, pady=15)

    def on_tab_changed(self, event):
        selected_index = self.notebook.index(self.notebook.select())
        for i, text in enumerate(tab_texts):
            if i == selected_index:
                icon = tab_icons[text]
                self.notebook.tab(i, text=f"{icon} {text}")
            else:
                self.notebook.tab(i, text=text)

    def on_main_tab_changed(self, event):
        selected_index = self.main_notebook.index(self.main_notebook.select())
        for i, text in enumerate(main_tabs_texts):
            if i == selected_index:
                icon = main_tabs_icons[text]
                self.main_notebook.tab(i, text=f"{icon} {text}")
            else:
                self.main_notebook.tab(i, text=text)

    def maximize_window(self):
        try:
            self.attributes("-fullscreen", False)
            system = platform.system()

            if system == "Windows":
                self.state("zoomed")
            else:
                # Fallback para Linux/macOS
                self.state("normal")
                self.update_idletasks()
                screen_width = self.winfo_screenwidth()
                screen_height = self.winfo_screenheight()
                self.geometry(f"{screen_width}x{screen_height}+0+0")
        except Exception as e:
            print(f"Error al maximizar la ventana: {e}")

    def show_gif_toplevel(self):
        # GifFrameApp(self)
        StartImageFrame(self)

    def open_configurations(self):
        # config_frame = ConfigFrame(self)
        if self.config_frame is None:
            self.config_frame = ConfigFrame(self)   # pyrefly: ignore
        else:
            self.config_frame.lift()
