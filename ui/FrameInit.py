# -*- coding: utf-8 -*-
__author__ = "Edisson A. Naula"
__date__ = "$ 10/10/2025  at 01:24 p.m. $"

from PIL import Image, ImageTk
import ttkbootstrap as ttk


class StartImageFrame(ttk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.master = master
        self.title("Starting Image")
        self.attributes("-topmost", True)
        self.attributes("-fullscreen", True)

        self.overrideredirect(True)  # Remove window decorations for a cleaner display

        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        self.geometry(f"{screen_width}x{screen_height}+0+0")

        self.configure(
            background="black"
        )  # Set background to white to fix transparency issues

        # Cargar y redimensionar la imagen al tamaño de pantalla
        image = Image.open("resources/imgs/title.png")
        image = image.resize((screen_width, screen_height), Image.LANCZOS)
        photo = ImageTk.PhotoImage(image)

        # Mostrar la imagen
        image_label = ttk.Label(self, image=photo, background="black")
        image_label.image = photo
        image_label.pack(fill="both", expand=True)

        # Cerrar automáticamente después de 6 segundos
        self.after(5000, self.destroy)
        print("Start image closed")

