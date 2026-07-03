# -*- coding: utf-8 -*-
__author__ = "Edisson A. Naula"
__date__ = "$ 08/10/2025  at 09:33 a.m. $"

from templates.utils import seed_default_settings
from ui.MainGUI import MainGUI

if __name__ == '__main__':
    # Auto-repara settings.json con las claves nuevas por defecto (sin tocar los
    # valores locales) tras un update que conservó el archivo del dispositivo.
    seed_default_settings()
    app = MainGUI(themename="litera")
    app.mainloop()
    