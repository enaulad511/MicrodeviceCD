# -*- coding: utf-8 -*-
__author__ = "Edisson A. Naula"
__date__ = "$ 08/10/2025  at 09:35 a.m. $"

import ttkbootstrap as ttk
from PIL import Image, ImageTk

from templates.constants import font_buttons, font_labels, font_entry, font_labels_frame, font_tabs
from ui.DiscFrame import ControlDiscFrame
from ui.FluorecenseLEDFrame import ControlFluorescenteFrame
from ui.FrameInit import StartImageFrame
from ui.LEDFrame import ControleLEDFrame
from ui.PhotoreceptorFrame import PhotoreceptorFrame


def configure_styles():
    style = ttk.Style()
    style.configure("Custom.TButton", font=font_buttons)
    style.configure("Custom.TLabel", font=font_labels)
    style.configure("Custom.TEntry", font=font_entry)
    style.configure("Custom.TLabelframe.Label", font=font_labels_frame)
    style.configure("Custom.TNotebook.Tab", font=font_tabs)
    style.configure("Custom.TCombobox", font=font_entry)
    style.configure("info.TButton", font=font_buttons)
    style.configure("success.TButton", font=("Arial", 18))
    style.configure("danger.TButton", font=("Arial", 18))
    style.configure("Custom.Treeview", font=("Arial", 18), rowheight=30)
    style.configure("Custom.Treeview.Heading", font=("Arial", 18, "bold"))
    style.configure("success.TButton", font=font_buttons)
    style.configure("primary.TButton", font=font_buttons)
    style.configure("secondary.TButton", font=font_buttons)
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
        self.project_key = None
        self.title("uAA")
        self.style_gui = configure_styles()
        # self.after(0, lambda: self.state("zoomed"))
        self.after(0, self.maximize_window)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        # self.images = load_images()
        self.frame_config = None
        self.connected = ttk.BooleanVar(value=False)
        # --------------------Start Animation -------------------
        self.show_gif_toplevel()
        # --------------------notebook-------------------
        self.frame_content = ttk.Frame(self)
        self.frame_content.grid(
            row=0, column=0, sticky="nsew", padx=(5, 10), pady=(10, 10)
        )
        self.frame_content.columnconfigure(0, weight=1)
        self.frame_content.rowconfigure(0, weight=1)
        self.notebook = ttk.Notebook(self.frame_content)
        self.notebook.configure(style="Custom.TNotebook")
        self.notebook.grid(row=0, column=0, sticky="nsew")
        self.notebook.columnconfigure(0, weight=1)
        self.notebook.rowconfigure(0, weight=1)
        self.callbacks = {
            # "change_tab_text": self.change_tab_text,
            # "change_title": self.change_title,
            # "init_tabs": self.init_tabs_callback,
            # "change_project": self.change_project_key,
            # "test_connection_callback":  self.test_connection,
            # "save_project_callback": self.save_project,
            # "on_geometry_changed": self.on_geometry_changed,
        }
        print("init tabs")
        # self.tab0 = HomePage(self.notebook, callbacks=self.callbacks)
        # self.notebook.add(self.tab0, text="Home")
        # self.callbacks["render_thumbnails"] = self.tab0.render_thumbnails
        # print("init tabs home")
        self.tab1 = ControleLEDFrame(self.notebook)
        self.notebook.add(self.tab1, text="LED Control")
        print("init tabs LED")

        self.tab2 = ControlFluorescenteFrame(self.notebook)
        self.notebook.add(self.tab2, text="Fluorescence LED Control")
        print("init tabs Fluorescence")

        self.tab3 = ControlDiscFrame(self.notebook)
        self.notebook.add(self.tab3, text="Disc Control")
        print("init tabs Disc")

        self.tab4 = PhotoreceptorFrame(self.notebook)
        self.notebook.add(self.tab4, text="Photoreceptor Control")
        print("init tabs Photoreceptor")
        # # --------------------footer-------------------
        # self.frame_footer = ttk.Frame(self)
        # self.frame_footer.grid(row=1, column=0, sticky="nsew", padx=15, pady=15)
        # self.frame_footer.columnconfigure((0, 1, 2, 3, 4), weight=1)
        # ttk.Button(
        #     self.frame_footer,
        #     text="Configuration",
        #     image=self.images["config"],
        #     compound="left",
        #     command=self.click_config,
        #     style="secondary.TButton",
        # ).grid(row=0, column=0, sticky="w", padx=15, pady=15)
        # self.button_test = ttk.Button(
        #     self.frame_footer,
        #     text="Test Connection",
        #     command=self.test_connection,
        #     style="danger.TButton",
        #     compound="left",
        #     image=self.images["link"],
        # )
        # self.button_test.grid(row=0, column=1, sticky="e", padx=15, pady=15)
        # self.txt_connected = ttk.StringVar(value="Disconnected")
        # ttk.Label(
        #     self.frame_footer,
        #     textvariable=self.txt_connected,
        #     font=("Arial", 18),
        #     style="Custom.TLabel",
        # ).grid(row=0, column=2, sticky="w", padx=15, pady=15)
        # self.button_save = ttk.Button(
        #     self.frame_footer,
        #     text="Save project",
        #     image=self.images["save"],
        #     command=self.save_project,
        #     style="success.TButton",
        #     compound="left",
        # )
        # self.button_save.grid(row=0, column=3, sticky="e", padx=15, pady=15)
        # self.button_mControl = ttk.Button(
        #     self.frame_footer,
        #     text="Manual Control",
        #     command=self.click_manual_control,
        #     style="primary.TButton",
        #     image=self.images["control"],
        #     compound="left",
        # )
        # self.button_mControl.grid(row=0, column=4, sticky="e", padx=15, pady=15)
        # print("init tabs footer")

    def maximize_window(self):
        try:
            self.attributes(
                "-fullscreen", False
            )  # Asegura que no esté en modo fullscreen
            self.state("normal")  # Establece el estado normal antes de maximizar
            self.update_idletasks()  # Actualiza la geometría
            screen_width = self.winfo_screenwidth()
            screen_height = self.winfo_screenheight()
            self.geometry(f"{screen_width}x{screen_height}+0+0")  # Maximiza manualmente
        except Exception as e:
            print(f"Error al maximizar la ventana: {e}")

    def show_gif_toplevel(self):
        # GifFrameApp(self)
        StartImageFrame(self)