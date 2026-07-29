"""
MicroPython MLX90614 IR temperature sensor driver
https://github.com/mcauser/micropython-mlx90614
MIT License
Copyright (c) 2016 Mike Causer
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:
The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""
import ustruct
import time

def _crc8(data):
  """CRC-8 SMBus (polinomio x^8+x^2+x+1, init 0x00) sobre los bytes de la trama."""
  crc = 0
  for byte in data:
    crc ^= byte
    for _ in range(8):
      crc = ((crc << 1) ^ 0x07) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
  return crc

class SensorBase:
  def read16(self, register):
    """Lee una palabra. UN reintento a 2 ms ante OSError (NACK/EIO transitorio).

    El bus I2C del disco recoge EMI del motor y suelta NACKs aislados; un solo
    reintento los cubre sin poder colgar el bucle principal (peor caso +4 ms por
    payload, contra los 80 ms de periodo de muestreo). Se atrapa SOLO OSError: un
    fallo de ustruct.unpack seria un bug nuestro y debe explotar, no reintentarse.
    Si el segundo intento tambien falla, el OSError propaga: la POLITICA de que
    reportar es del llamador (read_temp), no de esta primitiva de bus."""
    try:
      data = self.i2c.readfrom_mem(self.address, register, 2)
    except OSError:
      time.sleep_ms(2)
      data = self.i2c.readfrom_mem(self.address, register, 2)
    return ustruct.unpack('<H', data)[0]
  def write16(self, register, value):
    """Escribe una palabra (16 bits) con byte PEC al final.

    El MLX90614 EXIGE el PEC en toda escritura (en lectura es opcional): sin el,
    descarta el comando en silencio. Por eso se arma la trama a mano en vez de
    usar i2c.writeto_mem(), que no lo agrega. El PEC cubre la trama completa
    empezando por la direccion desplazada + bit de escritura."""
    low = value & 0xFF
    high = (value >> 8) & 0xFF
    pec = _crc8(bytes([self.address << 1, register, low, high]))
    self.i2c.writeto(self.address, bytes([register, low, high, pec]))
  def read_emissivity(self):
    """Emisividad guardada en EEPROM, como fraccion 0-1 (epsilon = valor/65535)."""
    return self.read16(self._REGISTER_EMISSIVITY) / 65535.0
  def set_emissivity(self, value, force=False):
    """Fija la emisividad en EEPROM. Devuelve True si hubo escritura.

    Idempotente a proposito: si el valor guardado ya coincide no toca la EEPROM
    (celdas con vida limitada, ~100k ciclos), asi que es seguro llamarla en cada
    arranque. El chip carga la EEPROM en el POR, de modo que el valor nuevo rige
    a partir del siguiente encendido.
    """
    if value < 0.1 or value > 1.0:
      raise ValueError("emisividad fuera de rango (0.1-1.0)")
    raw = min(65535, max(1, int(round(value * 65535))))
    if not force and self.read16(self._REGISTER_EMISSIVITY) == raw:
      return False
    # Secuencia obligatoria del datasheet: borrar la celda (0x0000) y luego
    # escribir; cada paso necesita ~5 ms de EEPROM (se dan 10 ms de margen).
    self.write16(self._REGISTER_EMISSIVITY, 0x0000)
    time.sleep_ms(10)
    self.write16(self._REGISTER_EMISSIVITY, raw)
    time.sleep_ms(10)
    readback = self.read16(self._REGISTER_EMISSIVITY)
    if readback != raw:
      raise OSError("emisividad no persistio (%d != %d)" % (readback, raw))
    return True
  def read_temp(self, register):
    """Temperatura en grados C. LANZA OSError si la lectura no es valida.

    Antes atrapaba la excepcion y devolvia temp=0, que tras la conversion sale
    como -273.15: un sentinel disfrazado de medicion, que el host no puede
    distinguir de un dato real (entra al PID como un error de ~90 grados). Ahora
    propaga: el llamador (read_temperatures_payload) ya lo traduce a None, que el
    host SI maneja (sostiene el ultimo valor y avisa en la UI).

    Ademas valida el bit 15, que el MLX usa como FLAG DE ERROR en Tobj: encendido
    nunca es una temperatura legitima (Tobj valido = 0x27AD-0x7FFF, Ta valido =
    0x2DE3-0x4DC3), y sin este chequeo el I2C responde perfecto y el driver
    entrega >+382 grados como dato bueno -- el mismo bug que el -273.15, pero por
    arriba y sin excepcion que lo delate."""
    raw = self.read16(register)
    if raw & 0x8000:
      raise OSError("MLX: flag de error en reg 0x%02X (raw 0x%04X)" % (register, raw))
    # apply measurement resolution (0.02 degrees per LSB) + Kelvin to Celsius
    return raw * .02 - 273.15
  def read_ambient_temp(self):
    return self.read_temp(self._REGISTER_TA)
  def read_object_temp(self):
    return self.read_temp(self._REGISTER_TOBJ1)
  def read_object2_temp(self):
    if self.dual_zone:
      return self.read_temp(self._REGISTER_TOBJ2)
    else:
      raise RuntimeError("Device only has one thermopile")
  @property
  def ambient_temp(self):
    return self.read_ambient_temp()
  @property
  def object_temp(self):
    return self.read_object_temp()
  @property
  def object2_temp(self):
    return self.read_object2_temp()

class MLX90614(SensorBase):
  _REGISTER_TA = 0x06
  _REGISTER_TOBJ1 = 0x07
  _REGISTER_TOBJ2 = 0x08
  # EEPROM 0x04 (emisividad) accedida con el opcode de EEPROM 0x20|dir -> 0x24.
  # Mismo criterio que el 0x25 de ConfigRegister1 (EEPROM 0x05) usado abajo:
  # 0x04 a secas apunta a RAM y la escritura no tiene efecto.
  _REGISTER_EMISSIVITY = 0x24
  def __init__(self, i2c, address=0x5a):
    self.i2c = i2c
    self.address = address
    _config1 = i2c.readfrom_mem(address, 0x25, 2)
    _dz = ustruct.unpack('<H', _config1)[0] & (1<<6)
    self.dual_zone = True if _dz else False
class MLX90615(SensorBase):
  _REGISTER_TA = 0x26
  _REGISTER_TOBJ1 = 0x27
  _REGISTER_EMISSIVITY = 0x13  # EEPROM 0x13 (sin verificar en hardware: aqui se usa el 90614)
  def __init__(self, i2c, address=0x5b):
    self.i2c = i2c
    self.address = address
    self.dual_zone = False