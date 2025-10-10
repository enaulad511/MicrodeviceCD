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
        self.configure(
            background="black"
        )  # Set background to white to fix transparency issues

        # Load and display the image
        image = Image.open("resources/imgs/title.png")  # Replace with the path to your image
        photo = ImageTk.PhotoImage(image)

        # Create a label to display the image
        image_label = ttk.Label(self, image=photo)
        image_label.image = photo  # Keep a reference to prevent garbage collection
        image_label.pack(fill="both", expand=True)
        image_label.place(relx=0.5, rely=0.5, anchor="center")

        # Automatically close the Toplevel after 6 seconds
        self.after(6000, self.destroy)
        print("Start image closed")
