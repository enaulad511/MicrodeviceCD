# -*- coding: utf-8 -*-
from ../Drivers.ReaderADS import Ads1115Reader
from ui.PcrFrame import ads

__author__ = "Edisson Naula"
__date__ = "$ 19/02/2026 at 15:29 $"


if __name__ == "__main__":
    ads = Ads1115Reader(address=0x4A, fsr=4.096, sps=128, single_shot=True)
    for i in range(10):
        print(ads.read_voltage(0, averages=4))
