# -*- coding: utf-8 -*-
__author__ = "Edisson Naula"
__date__ = "$ 17/12/2025 at 16:11 $"

import ttkbootstrap as ttk
import tkinter as tk

def configure_styles():
    style = ttk.Style()
    # Configuración del campo de texto (Entry) del Combobox
    style.configure("Custom.TCombobox", font=("Arial", 24))
    return style

if __name__ == '__main__':
    app = ttk.Window(themename="flatly")
    app.title("MicroAA Main GUI")
    app.geometry("1200x800")
    
    # 1. ESTO ES LO MÁS IMPORTANTE:
    # Usar *Combobox*Listbox (sin la 'T') suele ser más efectivo para capturar el widget interno.
    # Debe declararse ANTES de crear el widget o justo después de iniciar la app.
    app.option_add('*TCombobox*Listbox.font', ("Arial", 24))
    app.option_add('*Combobox*Listbox.font', ("Arial", 24)) 

    frame_test = ttk.Frame(app)
    frame_test.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
    
    style = configure_styles()
    
    selector = ttk.Combobox(
        frame_test,
        values=["PCR", "Electrochemical", "Manual Control"],
        state="readonly",
        width=30,
        style="Custom.TCombobox", # Aplicamos el estilo personalizado
        font=("Arial", 24)        # Esto cambia el texto del campo seleccionado
    )
    
    selector.grid(row=0, column=0, padx=10, pady=10, sticky="w")
    
    app.mainloop()