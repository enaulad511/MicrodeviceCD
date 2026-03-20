import time
from typing import Dict, List, Literal, Optional, Tuple

# --- Compatibilidad de imports según versión de la librería Adafruit ---
try:
    # Algunos entornos exponen todo en el paquete raíz:
    from adafruit_ads1x15 import ADS1115, ads1x15
    from adafruit_ads1x15.ads1x15 import Mode
    try:
        # AnalogIn a veces está en el paquete raíz:
        from adafruit_ads1x15 import AnalogIn  # type: ignore
    except ImportError:
        # O en el submódulo analog_in:
        from adafruit_ads1x15.analog_in import AnalogIn  # type: ignore
except Exception:
    # Alternativa clásica (más común en versiones recientes)
    from adafruit_ads1x15.ads1115 import ADS1115  # type: ignore
    from adafruit_ads1x15.ads1x15 import Mode, ads1x15  # type: ignore
    from adafruit_ads1x15.analog_in import AnalogIn  # type: ignore

# Placas CircuitPython / Blinka
import board
import busio

__author__ = "Edisson Naula (actualizado)"
__date__ = "$ 20/03/2026 $"

# Tipos
Channel = Literal[0, 1, 2, 3]
DiffPair = Tuple[Channel, Channel]


class Ads1115Reader:
    """
    Envoltura POO para el ADS1115 (Adafruit) con soporte de:
      - Lecturas single-ended (AINx vs GND) y diferenciales (AINp - AINn).
      - Control de FSR (ganancia), SPS (data rate) y modo (single/continuous).
      - Promediado opcional con retardo configurable.
      - Cache de canales para evitar recreaciones.

    Recomendación para tu TIA con OPA333:
      - Conecta Vout (TIA) a A0, Vref (~1.65V) a A1 y usa lectura diferencial A0-A1.
      - Elige fsr pequeño (0.256 o 0.512 V) para máxima resolución, SIEMPRE que
        |Vout - Vref| no exceda el FSR.

    Notas:
      - En single-ended se hace clamp a 0.0V (ruido puede dar negativo). En diferencial NO.
      - El ADS1115 no mide por encima de VDD (tensión de alimentación del propio ADC).
    """

    # Mapeo FSR (±V) -> gain (Adafruit)
    _FSR_TO_GAIN = {
        6.144: 2 / 3,  # ±6.144 V
        4.096: 1,      # ±4.096 V
        2.048: 2,      # ±2.048 V
        1.024: 4,      # ±1.024 V
        0.512: 8,      # ±0.512 V
        0.256: 16,     # ±0.256 V
    }

    # Mapeo canal entero -> constante de pin Adafruit
    _CH_TO_PIN = {
        0: ads1x15.Pin.A0,
        1: ads1x15.Pin.A1,
        2: ads1x15.Pin.A2,
        3: ads1x15.Pin.A3,
    }

    # Pares diferenciales válidos en ADS1115 (por hardware)
    _VALID_DIFF_PAIRS: List[DiffPair] = [
        (0, 1),  # A0 - A1
        (0, 3),  # A0 - A3
        (1, 3),  # A1 - A3
        (2, 3),  # A2 - A3
    ]

    # Conjunto aceptado de SPS (samples per second)
    _VALID_SPS = [8, 16, 32, 64, 128, 250, 475, 860]

    def __init__(
        self,
        address: int = 0x48,
        fsr: float = 0.512,          # Para diferencial típico de TIA alrededor de Vref
        sps: int = 128,
        single_shot: bool = True,
        i2c: Optional[busio.I2C] = None,
    ):
        if fsr not in self._FSR_TO_GAIN:
            raise ValueError(f"fsr inválido: {fsr}. Opciones: {list(self._FSR_TO_GAIN.keys())}")
        if sps not in self._VALID_SPS:
            raise ValueError(f"sps inválido. Usa uno de: {self._VALID_SPS}")

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

        # Aplica data_rate si la versión de la librería lo soporta así (la mayoría)
        try:
            self._ads.data_rate = self._sps
        except Exception:
            # Algunas versiones requieren enums; si fuese el caso, se puede mapear aquí.
            pass

        # Cache de canales: single-ended por índice; diferenciales por tupla (p,n)
        self._chan_cache_se: Dict[Channel, AnalogIn] = {}
        self._chan_cache_diff: Dict[DiffPair, AnalogIn] = {}

    # --- Configuración ---

    @property
    def fsr(self) -> float:
        return self._fsr

    def set_fsr(self, fsr: float):
        """
        Cambia el FSR (±V) ajustando la ganancia del ADS1115.
        NOTA: Afecta a TODOS los canales (propiedad global del ADS).
        """
        if fsr not in self._FSR_TO_GAIN:
            raise ValueError(f"fsr inválido: {fsr}. Opciones: {list(self._FSR_TO_GAIN.keys())}")
        self._fsr = fsr
        self._gain = self._FSR_TO_GAIN[fsr]
        self._ads.gain = self._gain
        # No hay que recrear canales; la ganancia es global

    @property
    def sps(self) -> int:
        return self._sps

    def set_sps(self, sps: int):
        if sps not in self._VALID_SPS:
            raise ValueError(f"sps inválido. Usa: {self._VALID_SPS}")
        self._sps = sps
        # Aplica data_rate según disponibilidad de la librería
        try:
            self._ads.data_rate = self._sps
        except Exception:
            pass

    def set_mode(self, single_shot: bool = True):
        self._mode = Mode.SINGLE if single_shot else Mode.CONTINUOUS
        self._ads.mode = self._mode

    # --- Lecturas: single-ended ---

    def _get_channel_se(self, ch: Channel) -> AnalogIn:
        if ch not in self._CH_TO_PIN:
            raise ValueError("Canal inválido. Usa 0,1,2,3.")
        if ch not in self._chan_cache_se:
            self._chan_cache_se[ch] = AnalogIn(self._ads, self._CH_TO_PIN[ch])
        return self._chan_cache_se[ch]

    def read_raw(self, ch: Channel = 0, averages: int = 1, delay_s: Optional[float] = None) -> int:
        """
        Lee el valor crudo (16-bit firmado) del canal single-ended AINx vs GND.
        """
        chan = self._get_channel_se(ch)
        if averages <= 1:
            return chan.value

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
        Lee voltaje single-ended (AINx vs GND) en voltios.
        Clamp mínimo 0.0 V para evitar negativos por ruido.
        """
        chan = self._get_channel_se(ch)
        if averages <= 1:
            return max(0.0, chan.voltage)

        acc = 0.0
        if delay_s is None:
            delay_s = max(0.0, 1.0 / (2.0 * self._sps))
        for _ in range(averages):
            acc += chan.voltage
            if delay_s > 0:
                time.sleep(delay_s)
        return max(0.0, acc / averages)

    def read_all_voltages(self, channels: List[Channel] = [0, 1, 2, 3],
                          averages: int = 1, delay_s: Optional[float] = None) -> Dict[Channel, float]:
        """
        Lee múltiples canales single-ended y devuelve dict {canal: voltios}.
        """
        return {ch: self.read_voltage(ch, averages=averages, delay_s=delay_s) for ch in channels}

    # --- Lecturas: diferencial ---

    def _validate_diff_pair(self, p: Channel, n: Channel):
        pair = (p, n)
        if pair not in self._VALID_DIFF_PAIRS:
            raise ValueError(
                f"Par diferencial inválido {pair}. Válidos: {self._VALID_DIFF_PAIRS} "
                "(por limitaciones del multiplexor interno del ADS1115)."
            )

    def _get_channel_diff(self, p: Channel, n: Channel) -> AnalogIn:
        self._validate_diff_pair(p, n)
        key = (p, n)
        if key not in self._chan_cache_diff:
            self._chan_cache_diff[key] = AnalogIn(self._ads, self._CH_TO_PIN[p], self._CH_TO_PIN[n])
        return self._chan_cache_diff[key]

    def read_raw_diff(self, p: Channel = 0, n: Channel = 1, averages: int = 1,
                      delay_s: Optional[float] = None) -> int:
        """
        Lee el valor crudo (16-bit firmado) del canal diferencial (AINp - AINn).
        Úsalo para medir (Vout - Vref) en tu TIA: p=0 (A0), n=1 (A1).
        """
        ch = self._get_channel_diff(p, n)
        if averages <= 1:
            return ch.value

        acc = 0
        if delay_s is None:
            delay_s = max(0.0, 1.0 / (2.0 * self._sps))
        for _ in range(averages):
            acc += ch.value
            if delay_s > 0:
                time.sleep(delay_s)
        return int(round(acc / averages))

    def read_voltage_diff(self, p: Channel = 0, n: Channel = 1, averages: int = 1,
                          delay_s: Optional[float] = None) -> float:
        """
        Lee voltaje diferencial (AINp - AINn) en voltios.
        NO se hace clamp; el resultado puede ser ±FSR.
        """
        ch = self._get_channel_diff(p, n)
        if averages <= 1:
            return ch.voltage

        acc = 0.0
        if delay_s is None:
            delay_s = max(0.0, 1.0 / (2.0 * self._sps))
        for _ in range(averages):
            acc += ch.voltage
            if delay_s > 0:
                time.sleep(delay_s)
        return acc / averages