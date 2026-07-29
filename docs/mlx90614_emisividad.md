# Emisividad del MLX90614 (0.96 en EEPROM)

El sensor IR **MLX90614** del disco calcula la temperatura de objeto (`t_obj`)
asumiendo una emisividad `ε` que vive en su **EEPROM**. De fábrica `ε = 1.00`
(cuerpo negro perfecto); ninguna superficie real lo es, así que con el valor de
fábrica el objeto se lee **más frío** de lo que está. Este cambio fija
`ε = 0.96` en el propio sensor, una sola vez, desde el firmware del Pico.

Afecta únicamente a `t_obj` (`ir_object` del selector de fuente de temperatura,
ver [temp_source_selector.md](temp_source_selector.md)). `t_amb` (ambiente del
mismo MLX) y `t_tc` (termocupla MAX31855) no dependen de `ε`.

> Qué pasa cuando la lectura **falla** (EIO transitorio, flag de error del sensor)
> y cómo se propaga hasta el PID:
> [mlx90614_fiabilidad_lectura.md](mlx90614_fiabilidad_lectura.md).

## 1. Dónde vive el sensor (no es I2C de la Raspberry)

El MLX90614 **no** cuelga de la Raspberry: está en el bus **I2C0 del Pico 2**
(SDA=GP20, SCL=GP21, 100 kHz), compartido con el MCP23017 de canales
([emstat_arquitectura_cadena.md](emstat_arquitectura_cadena.md) §pines). Por eso
el cambio es **solo de firmware**: el host nunca habla I2C con él, solo recibe
las tres temperaturas ya calculadas en el broadcast UDP `t_amb:t_obj:t_tc`.

Recetas tipo `smbus.SMBus(1)` (Raspberry) no aplican aquí; el equivalente
MicroPython vive en [firmware/DiscPCB/mlx90614.py](../firmware/DiscPCB/mlx90614.py).

## 2. Los dos detalles que hacen fallar la escritura en silencio

### 2.1 El registro es 0x24, no 0x04

El mapa de opcodes del MLX90614 selecciona el **espacio de memoria** en los bits
altos del comando:

| Comando | Espacio |
|---|---|
| `0x00`–`0x1F` | RAM (`0x06` = Ta, `0x07` = Tobj1) |
| `0x20`–`0x3F` | EEPROM (`0x20 \| dirección`) |

La emisividad es la **dirección 0x04 de EEPROM** → el comando es
**`0x24`**. Escribir a `0x04` a secas apunta a RAM: la trama se acepta y no pasa
nada. La confirmación está en el propio driver desde antes de este cambio:
`ConfigRegister1` es EEPROM `0x05` y se lee como `0x25`
([mlx90614.py:117](../firmware/DiscPCB/mlx90614.py#L117)).

### 2.2 Toda escritura exige PEC

El MLX90614 habla **SMBus**, no I2C pelado: en cada *escritura* el último byte
debe ser el **PEC** (CRC-8, polinomio `x⁸+x²+x+1`, init `0x00`) calculado sobre la
trama completa **incluyendo la dirección desplazada + bit de escritura**. Si el
PEC no cuadra, el sensor **descarta el comando sin error visible**.

`i2c.writeto_mem()` (MicroPython) y `bus.write_word_data()` (smbus sin
`bus.pec = True`) **no** agregan el PEC, así que la trama se arma a mano:

```python
# mlx90614.py:38
def write16(self, register, value):
    low, high = value & 0xFF, (value >> 8) & 0xFF
    pec = _crc8(bytes([self.address << 1, register, low, high]))
    self.i2c.writeto(self.address, bytes([register, low, high, pec]))
```

`_crc8` ([mlx90614.py:25](../firmware/DiscPCB/mlx90614.py#L25)) es el CRC-8/SMBus
estándar (verificado contra el valor de control canónico: `"123456789"` → `0xF4`).

Tramas reales para `ε = 0.96` en `0x5A`:

```
borrado : 0x24 0x00 0x00 0x28
escritura: 0x24 0xC2 0xF5 0x2A      # 0xF5C2 = 62914 = round(0.96 * 65535)
```

## 3. La API del driver

[firmware/DiscPCB/mlx90614.py](../firmware/DiscPCB/mlx90614.py):

| Miembro | Rol |
|---|---|
| `_REGISTER_EMISSIVITY` | `0x24` en `MLX90614` (`0x13` en `MLX90615`, sin verificar). |
| `write16(reg, value)` | Escritura de palabra **con PEC** (base de cualquier escritura a EEPROM). |
| `read_emissivity()` | `valor / 65535` → fracción 0–1. |
| `set_emissivity(value, force=False)` | Fija `ε`. Devuelve `True` si escribió. |

`set_emissivity` ([mlx90614.py:52](../firmware/DiscPCB/mlx90614.py#L52)):

1. Valida rango `0.1–1.0` (`ValueError` fuera de él).
2. `raw = round(ε × 65535)`, acotado a `1–65535`.
3. **Idempotencia**: si el valor guardado ya es `raw`, no escribe y devuelve
   `False`. La EEPROM tiene vida finita (~100k ciclos) y esto corre en **cada**
   arranque; sin este corte, cada reinicio gastaría dos ciclos de celda.
4. Secuencia del datasheet: **borrar** (`0x0000`) → esperar → **escribir** →
   esperar (10 ms por paso, sobre los ~5 ms que pide la celda).
5. Relectura de verificación; si no coincide, `OSError`.

## 4. Aplicación en el arranque del Pico

[firmware/DiscPCB/emstat_wifi_v1.9.py:187](../firmware/DiscPCB/emstat_wifi_v1.9.py#L187),
justo después de construir el sensor:

```python
MLX_EMISSIVITY = 0.96
mlx_emissivity = None
if sensor_temp is not None:
    try:
        if sensor_temp.set_emissivity(MLX_EMISSIVITY):
            print("MLX90614: emisividad escrita ->", MLX_EMISSIVITY, "(rige tras reinicio)")
        else:
            print("MLX90614: emisividad ya en", MLX_EMISSIVITY)
        mlx_emissivity = round(sensor_temp.read_emissivity(), 4)
    except Exception as e:
        print("MLX90614: no se pudo fijar la emisividad:", e)
```

Decisiones:

- **Constante, no comando.** No se agregó un `{"cmd":"SET","emissivity":…}` al
  protocolo: no hay UI que lo mande, y exponer escrituras de EEPROM por red es
  desgaste sin dueño. Para cambiar el valor se edita `MLX_EMISSIVITY` y se
  reflashea (o se llama `sensor_temp.set_emissivity(x)` desde el REPL).
- **No aborta el arranque.** Cualquier fallo (sensor ausente, PEC rechazado)
  queda en un `print` y el firmware sigue: la temperatura es telemetría, no un
  requisito para correr un experimento.
- **Diagnóstico por UDP.** El `hello` de `main_loop`
  ([emstat_wifi_v1.9.py:885](../firmware/DiscPCB/emstat_wifi_v1.9.py#L885)) lleva
  ahora `"mlx_emissivity"` con el valor **leído del sensor** (no la constante),
  que es la única forma de confirmar el estado real sin REPL. El host lo ignora
  (`_parse_temp` tolera campos no numéricos en `ClientUDP`), así que no rompe el
  parseo del broadcast.

### 4.1 Cuándo empieza a regir

El chip carga la EEPROM en el **POR**, así que el valor nuevo aplica **desde el
siguiente encendido**. Como la escritura es idempotente y corre en cada arranque,
la secuencia real es: primer boot tras el flasheo → escribe (`t_obj` aún con el
`ε` viejo) → reinicio → ya rige y los siguientes arranques no tocan la EEPROM.
Por eso conviene **apagar y encender el disco una vez** después de flashear.

## 5. Sincronización firmware ↔ espejo

El original que se flashea vive fuera de git (`~/MicroPython/DiscPCB/`); el
espejo versionado es [firmware/DiscPCB/](../firmware/DiscPCB/). Ambos quedaron con
los mismos `mlx90614.py` y `emstat_wifi_v1.9.py` (verificado por `diff`).

## 6. Pendiente

- **Flasheo**: el cambio viaja en `emstat_wifi_v1.9.py`, que **aún no está
  flasheado** (mismo pendiente que CA, ver
  [ca_cronoamperometria.md §7](ca_cronoamperometria.md)). Hay que copiar
  `mlx90614.py` **y** `emstat_wifi_v1.9.py` a la placa.
- **Validación en hardware**: confirmar por REPL/UDP que `read_emissivity()`
  devuelve ≈0.96 tras el reinicio, y que el segundo arranque ya no escribe.
- **Calibración del valor**: 0.96 es el valor pedido (típico de plásticos/vidrio);
  si se compara `t_obj` contra la termocupla y queda un sesgo sistemático, el
  ajuste fino de `ε` es la perilla.

__author__ = "Edisson A. Naula"
__date__ = "$ 29/07/2026 $"
