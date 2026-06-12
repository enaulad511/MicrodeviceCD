# -*- coding: utf-8 -*-

from dotenv import dotenv_values

__author__ = "Edisson A. Naula"
__date__ = "$ 08/10/2025  at 09:46 a.m. $"

font_title = ("Arial", 28, "bold")
font_title_n = ("Arial", 28, "normal")
font_text = ("Arial", 16, "normal")
font_text_combobox = ("Arial", 19, "normal")
font_tabs = ("Arial", 11, "bold")
font_options = ("Arial", 11, "normal")
font_footer = ("Arial", 8, "bold")
font_buttons = ("Arial", 16, "normal")
font_buttons_small = ("Arial", 11, "normal")
font_labels = ("Arial", 14, "normal")
font_entry = ("Arial", 14, "normal")
font_entry_display = ("Arial", 18, "normal")
font_labels_frame = ("Arial", 11, "bold")
font_labels_plates = ("Arial", 10, "bold")
format_timestamp = "%Y-%m-%d %H:%M:%S"
tab_icons = {
    "Quick": "⚡",
    "Heating LED": "💡",
    "Fluorescence LED": "🔬",
    "Disc": "💿",
    "Photoreceptor": "👁️",
    "Temperature": "🌡️",
}
tab_texts = [
    "Quick",
    "Heating LED",
    "Fluorescence LED",
    "Disc",
    "Photoreceptor",
    "Temperature",
]
main_tabs_texts = ["PCR", "Electrochemical", "Manual Control"]
main_tabs_icons = {"PCR": "🧪", "Electrochemical": "🧫", "Manual Control": "🖥️"}
serial_port_encoder = "/dev/ttyAMA0"
led_heatin_pin = 25
led_fluorescence_pin = 24
chip_rasp: str = "/dev/gpiochip0"
secrets = dotenv_values(".env")
