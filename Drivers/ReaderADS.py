import time
import board
import busio
from typing import List, Literal, Optional

from adafruit_ads1x15 import ADS1115, AnalogIn, ads1x15
from adafruit_ads1x15.ads1x15 import Mode

__author__ = "Edisson Naula"
__date__ = "$ 19/02/2026 at 12:51 $"

# Tipo para canal: 0..3
Channel = Literal[0, 1, 2, 3]

class Ads1115Reader:
    """
    Envoltura (wrapper) POO sobre adafruit-circuitpython-ads1x15 para ADS1115.
    - Lecturas single-ended (AIN0..AIN3 vs GND).
    - Control de ganancia por FSR (±6.144V .. ±0.256V).
    - Control de data rate (SPS).
    - Modo single-shot por defecto.
    - Lecturas crudas y en voltios, con promediado opcional.
    """

    # Mapeo FSR (±V) -> gain (Adafruit)
    _FSR_TO_GAIN = {
        6.144: 2/3,  # ±6.144 V
        4.096: 1,    # ±4.096 V
        2.048: 2,    # ±2.048 V
        1.024: 4,    # ±1.024 V
        0.512: 8,    # ±0.512 V
        0.256: 16,   # ±0.256 V
    }

    # Mapeo canal entero -> constante Adafruit
    _CH_TO_PIN = {
        0: ads1x15.Pin.A0,
        1: ads1x15.Pin.A1,
        2: ads1x15.Pin.A2,
        3: ads1x15.Pin.A3,
    }

    def __init__(
        self,
        address: int = 0x48,
        fsr: float = 4.096,
        sps: int = 128,
        single_shot: bool = True,
        i2c: Optional[busio.I2C] = None
    ):
        """
        :param address: Dirección I2C del ADS1115 (0x48..0x4B).
        :param fsr: ±FSR en voltios (clave de _FSR_TO_GAIN). Recomendado 4.096V para señales ~3.3V.
        :param sps: Samples Per Second (8,16,32,64,128,250,475,860).
        :param single_shot: True para Mode.SINGLE, False para Mode.CONTINUOUS.
        :param i2c: Objeto I2C ya creado (opcional). Si None, se crea con board.SCL/SDA.
        """
        if fsr not in self._FSR_TO_GAIN:
            raise ValueError(f"fsr inválido: {fsr}. Opciones: {list(self._FSR_TO_GAIN.keys())}")
        if sps not in [8,16,32,64,128,250,475,860]:
            raise ValueError("sps inválido. Usa uno de: 8,16,32,64,128,250,475,860")

        self._fsr = fsr
        self._gain = self._FSR_TO_GAIN[fsr]
        self._sps = sps
        self._mode = Mode.SINGLE if single_shot else Mode.CONTINUOUS

        # Crea I2C si no se pasó uno
        self._i2c = i2c if i2c is not None else busio.I2C(board.SCL, board.SDA)

        # Instancia ADS
        self._ads = ADS1115(self._i2c, address=address)
        self._ads.gain = self._gain
        self._ads.mode = self._mode

        # Cache de canales para evitar recrearlos repetidamente
        self._chan_cache = {}

    # --- Configuración ---

    @property
    def fsr(self) -> float:
        return self._fsr

    def set_fsr(self, fsr: float):
        if fsr not in self._FSR_TO_GAIN:
            raise ValueError(f"fsr inválido: {fsr}")
        self._fsr = fsr
        self._gain = self._FSR_TO_GAIN[fsr]
        self._ads.gain = self._gain
        # No es necesario recrear canales; la ganancia es global

    @property
    def sps(self) -> int:
        return self._sps

    def set_sps(self, sps: int):
        if sps not in [8,16,32,64,128,250,475,860]:
            raise ValueError("sps inválido. Usa: 8,16,32,64,128,250,475,860")
        self._sps = sps
        # self._ads.data_rate = self._to_rate_enum(sps)

    def set_mode(self, single_shot: bool = True):
        self._mode = Mode.SINGLE if single_shot else Mode.CONTINUOUS
        self._ads.mode = self._mode

    # --- Lecturas ---

    def read_raw(self, ch: Channel = 0, averages: int = 1, delay_s: Optional[float] = None) -> int:
        """
        Lee el valor crudo (entero 16-bit firmado) del canal.
        :param ch: 0..3
        :param averages: promedia N lecturas (>=1).
        :param delay_s: pausa opcional entre lecturas (si None, se usa 1/(2*SPS) como referencia suave).
        """
        chan = self._get_channel(ch)
        if averages <= 1:
            return chan.value

        # Promediado simple
        acc = 0
        if delay_s is None:
            delay_s = max(0.0, 1.0 / (2.0 * self._sps))
        for _ in range(averages):
            acc += chan.value
            if delay_s > 0:
                time.sleep(delay_s)
        return int(round(acc / averages))

    def read_voltage(self, ch: Channel = 0, averages: int = 1, delay_s: Optional[float] = None) -> float:
        """
        Lee voltaje del canal (single-ended) en voltios.
        Aplica el mismo promediado que read_raw.
        """
        chan = self._get_channel(ch)
        if averages <= 1:
            v = chan.voltage
            # Clamp mínimo 0 por ser single-ended (ruido puede dar <0)
            return max(0.0, v)

        acc = 0.0
        if delay_s is None:
            delay_s = max(0.0, 1.0 / (2.0 * self._sps))
        for _ in range(averages):
            acc += chan.voltage
            if delay_s > 0:
                time.sleep(delay_s)
        v = acc / averages
        return max(0.0, v)

    def read_all_voltages(self, channels: List[Channel] = [0,1,2,3], averages: int = 1, delay_s: Optional[float] = None) -> dict:
        """
        Lee múltiples canales y devuelve dict {canal: voltios}.
        """
        return {ch: self.read_voltage(ch, averages=averages, delay_s=delay_s) for ch in channels}

    # --- Utilidades internas ---

    def _get_channel(self, ch: Channel) -> AnalogIn:
        if ch not in self._CH_TO_PIN:
            raise ValueError("Canal inválido. Usa 0,1,2,3.")
        if ch not in self._chan_cache:
            self._chan_cache[ch] = AnalogIn(self._ads, self._CH_TO_PIN[ch])
        return self._chan_cache[ch]

    # def _to_rate_enum(self, sps: int):
    #     # Map a los enums de Adafruit (coinciden en nombre)
    #     mapping = {
    #         8:   Rate.RATE_8,
    #         16:  Rate.RATE_16,
    #         32:  Rate.RATE_32,
    #         64:  Rate.RATE_64,
    #         128: Rate.RATE_128,
    #         250: Rate.RATE_250,
    #         475: Rate.RATE_475,
    #         860: Rate.RATE_860,
    #     }
    #     return mapping[sps]