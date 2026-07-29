# Fiabilidad de lectura del MLX90614 (camino de fallo hasta el PID)

Qué pasa cuando una lectura del sensor IR **falla**, desde el bus I2C del Pico
hasta el PID de PCR. El tema importa ahora porque **se va a migrar el PID a la
fuente IR** (`ir_object`): mientras la termocupla mandaba, una lectura mala del
MLX era un número raro en una gráfica secundaria; con el IR al mando es el lazo
térmico actuando sobre basura.

Disparador: un `[Errno 5] EIO` aislado en el REPL del Pico (29/07/2026) con el
sensor perfectamente sano (`i2c.scan()` → `[0x20, 0x5a]`, emisividad `0.9600061`,
`t_obj` 25.25 °C en la lectura siguiente). O sea: **NACK transitorio**, no sensor
caído — el disco gira y el motor mete EMI en el bus.

## 1. Los dos sentinels disfrazados de medición

El bug de fondo no era el EIO: era **cómo se reportaba**. Dos caminos entregaban
un número plausible en lugar de "no sé":

| Falla | Antes devolvía | Efecto en el PID |
|---|---|---|
| EIO / NACK del bus | `temp = 0` → `×0.02 − 273.15` = **−273.15 °C** | error de ~−90 °C tras el EMA → calentador a fondo |
| Flag de error del sensor (bit 15) | palabra cruda convertida → **> +382 °C** | error enorme por arriba → calentador apagado |

Ambos son floats válidos, así que **el host no puede distinguirlos de un dato
real**: `_parse_temp` los acepta, `_valid()` no los descarta y, peor,
`temp_source_bad` queda en `False` — la UI ni avisa
([PcrFrame.py:915-937](../ui/PcrFrame.py#L915-L937)).

Y lo que el host tiene **no** es un filtro de rango de entrada: acota la *salida*
del PID (`max(0, min(1, power))` y el clamp del integral,
[PcrFrame.py:1345-1351](../ui/PcrFrame.py#L1345-L1351)) y suaviza la entrada con un
EMA de `alpha=0.3` (el `temp_filters` de media móvil vive en `QuickControlFrame`,
no en el lazo de PCR). El EMA atenúa el −273.15 al 30% — siguen siendo ~90 °C de
error — y el clamp lo vuelve "calentador a fondo": acotado en magnitud,
equivocado en dirección.

## 2. La división: bus abajo, política arriba

| Capa | Responsabilidad |
|---|---|
| `read16` ([mlx90614.py:35](../firmware/DiscPCB/mlx90614.py#L35)) | **Bus.** Reintenta; si no puede, lanza. |
| `read_temp` ([mlx90614.py:87](../firmware/DiscPCB/mlx90614.py#L87)) | **Política.** Valida el flag y decide que un fallo es excepción, no valor. |
| `read_temperatures_payload` ([emstat_wifi_v1.9.py:348](../firmware/DiscPCB/emstat_wifi_v1.9.py#L348)) | **Traducción al protocolo.** Excepción → `None` en el payload. |
| `_valid()` en el host | **Continuidad del lazo.** `None` → sostener último valor + avisar. |

El reintento va en `read16` porque un NACK es un problema *de bus* y ahí está toda
la información para resolverlo; poner ahí la política obligaría a la primitiva a
inventar una temperatura. Y `read16` es el único choke point de lectura, así que
el reintento cubre también la **relectura de verificación de la EEPROM** de
`set_emissivity` — que sin esto, con un EIO transitorio, lanzaría `OSError` y te
haría creer que la emisividad no persistió cuando sí
([mlx90614_emisividad.md §3](mlx90614_emisividad.md)).

## 3. Reintento: 1 solo, a 2 ms

```python
# mlx90614.py:35
try:
    data = self.i2c.readfrom_mem(self.address, register, 2)
except OSError:
    time.sleep_ms(2)
    data = self.i2c.readfrom_mem(self.address, register, 2)
return ustruct.unpack('<H', data)[0]
```

- **Un** reintento, no tres con backoff: el criterio fue **no poder colgar el
  bucle**. Peor caso +4 ms por payload (dos lecturas MLX), contra `sample_ms = 80`.
  Un backoff de ~35 ms —lo que haría falta para cubrir el timeout SMBus del MLX
  cuando el bus queda *colgado*— daría worst case ~200 ms y haría tartamudear la
  telemetría justo cuando el bus va mal. El bus colgado se resuelve con POR, no
  con reintentos.
- **Solo `OSError`**: es lo que MicroPython lanza para EIO/ETIMEDOUT. Un fallo de
  `ustruct.unpack` sería un bug nuestro y debe explotar, no reintentarse.
- La pausa va **entre** intentos, nunca después del último.

Presupuesto verificado: la telemetría **no** corre durante un experimento
(`maybe_send_temperature` solo se llama desde `main_loop`, nunca desde
`run_experiment_read_loop`), así que un bloqueo aquí no puede atrasar la lectura
del EmStat. El único costo es atrasar `process_uart_rx` en el bucle idle, y con
`rxbuf=2048` eso es retraso sin pérdida.

## 4. El flag de error del sensor (bit 15)

El MLX90614 usa el **bit 15 de `Tobj` como flag de error**: encendido, el dato es
inválido. Y el rango legítimo es `0x27AD`–`0x7FFF` para Tobj (−70.01 a
+382.19 °C) y `0x2DE3`–`0x4DC3` para Ta: **en ninguno de los dos ese bit puede
estar encendido**. Por eso el chequeo es genérico, sin tablas por registro:

```python
# mlx90614.py:102
raw = self.read16(register)
if raw & 0x8000:
    raise OSError("MLX: flag de error en reg 0x%02X (raw 0x%04X)" % (register, raw))
return raw * .02 - 273.15
```

Este caso **no lo cubre el reintento**: el I2C responde perfecto, no hay error de
bus que reintentar. Es el espejo por arriba del bug del −273.15, y sin este
chequeo llega al PID sin una sola excepción que lo delate.

Se descartó validar el rango completo por registro: el beneficio marginal sobre
el bit 15 es acotar el rango *físico*, que es criterio del host (y del sensor
correcto para el rango de PCR), no del driver.

## 5. Reportar el fallo: excepción, no valor

`read_temp` **lanza** en vez de devolver `None` o `"NS"`. No es gratuito:

- El firmware **ya estaba escrito para un driver que lanza**: el
  `except Exception: t_obj = None` existe idéntico en v1.5–v1.9 (misma placa,
  mismo `mlx90614.py`), con un solo llamador por método. El −273.15 existía solo
  porque `read_temp` se comía la excepción.
- Devolver `None` habría funcionado *por accidente*: el llamador hace
  `round(None, 2)` → `TypeError` → cae en el mismo `except`. Romper el contrato
  "devuelve float" con un valor que revienta la aritmética del llamador dos
  líneas después es peor que lanzar.
- Devolver `"NS"` habría colisionado con su significado actual: `NS` es **sensor
  ausente** (`sensor_temp is None`), `None` es **lectura fallida**. Esa distinción
  es diagnóstico real y se preserva.

Cadena completa: `OSError` → `except` → `t_obj = None` → payload `"None"` →
`_parse_temp` → `None` → `_valid()` sostiene el último valor, prende
`temp_source_bad` ("⚠ IR Object unavailable — holding last value") y arma el
watchdog de "ambas caídas" ([temp_source_selector.md](temp_source_selector.md)).
Al migrar el PID al IR, `_secondary_idx()` ([PcrFrame.py:395](../ui/PcrFrame.py#L395))
empareja `ir_object` (idx 1) con la termocupla (idx 2), así que la termocupla queda
automáticamente como señal de respaldo del watchdog.

Sostener el último valor 80 ms es inocuo para un lazo térmico de dinámica en
segundos — por eso un solo reintento alcanza.

## 6. Observabilidad: print por flanco, no por fallo

Con el `print(e)` del driver eliminado, el fallo se volvía invisible en el REPL
(el host sí avisa, pero no dice *cuántas veces seguidas* ni *con qué error*, y esa
racha es justo lo que distingue un NACK aislado de un sensor muerto). El contador
vive en el firmware, no en el driver — el driver se queda sin estado y sin
política ([emstat_wifi_v1.9.py:325-345](../firmware/DiscPCB/emstat_wifi_v1.9.py#L325-L345)):

```
MLX90614: lectura fallida: [Errno 5] EIO        # solo al ENTRAR en fallo
MLX90614: lectura recuperada tras 37 fallos     # solo al recuperarse
```

Por flanco y no por fallo porque a 80 ms de cadencia un bus malo escupiría ~12
líneas/s y ahogaría el REPL exactamente cuando se está depurando otra cosa. En
producción (sin REPL conectado) no imprime nada mientras nada cambie.

## 7. Lo que deliberadamente NO se hizo

- **Reintento en el MAX31855.** Sería inútil por diseño del chip: convierte de
  forma continua cada ~100 ms y publica en un registro, así que una relectura 2 ms
  después devuelve **los mismos bytes**. Sus bits de falla no son error de
  transmisión sino **estado real** (termocupla abierta, en corto a VCC o GND):
  reintentar solo agrega latencia para llegar a la misma conclusión y maquilla un
  problema de cableado que hoy se reporta limpio. Su camino de fallo ya devuelve
  `None`, sin sentinel ([emstat_wifi_v1.9.py:228](../firmware/DiscPCB/emstat_wifi_v1.9.py#L228)).
  Si algún día resulta ruidosa, el arreglo es esperar la ventana de conversión
  (~100 ms), que ya no cabe en el muestreo de 80 ms: rediseño del muestreo, no
  reintento.
- **Banda de plausibilidad en el host** (rechazar floats fuera de −40…300 °C). Tras
  §3–§5 el firmware no puede emitir ningún sentinel numérico, y el modo de
  corrupción real del enlace (el Wemos concatenando líneas por desborde de RX, lo
  que motivó `setRxBufferSize(2048)`) produce campos como `"25.2524.71"` que
  `_parse_temp` ya rechaza por no ser float. Además el fallo que de verdad muerde
  tras migrar al IR —que el sensor mire fuera del tubo y reporte una temperatura
  real pero de la cosa equivocada— cae **dentro** de cualquier banda razonable. Si
  algún día se quiere validación en el host, lo que tiene contenido es el
  **cross-check contra el canal secundario** que el emparejamiento de
  `_secondary_idx()` ya hace posible ("IR y termocupla difieren más de X °C"), no
  un rango absoluto.
- **Bump de versión del firmware.** El cambio se aplicó sobre
  `emstat_wifi_v1.9.py` (ya flasheado) con sub-bullet fechado en su encabezado, no
  en un `v1.10`: el peso del cambio está en `mlx90614.py`, que no tiene esquema de
  versión, así que un v1.9 "congelado" no permitiría reconstruir lo que corrió en
  la placa (para eso está git). Los números de versión rastrean el **contrato con
  el EmStat** (v1.6 abort, v1.7 `seq`, v1.8 EIS Fase 2, v1.9 CA) y esto no lo mueve.

## 8. Pendiente

- **Reflashear** `mlx90614.py` **y** `emstat_wifi_v1.9.py`. Degrada bien: si solo
  copias el driver, el `except` que ya está en la placa igual convierte el fallo
  en `None`; lo único que pierdes es el print por flanco.
- **Validar antes de migrar el PID al IR**: comparar `t_obj` contra la termocupla
  en régimen (con ε = 0.96 ya rigiendo) y verificar que el sesgo es aceptable en
  el rango de PCR (~55–95 °C). El ajuste fino de `ε` es la perilla
  ([mlx90614_emisividad.md §6](mlx90614_emisividad.md)).
- **Confirmar el flag de error en hardware**: forzar una condición inválida (tapar
  el campo de visión / sensor recién energizado) y ver `MLX90614: lectura fallida`
  seguido del aviso en la UI, en vez de una temperatura absurda.

__author__ = "Edisson A. Naula"
__date__ = "$ 29/07/2026 $"
