# OldDevice — integrador ON–OFF de fluorescencia (Arduino MKR Zero)

Documentación del sketch [OldDevice.ino](OldDevice.ino): el **lector de fluorescencia del
equipo anterior** (previo al CD microdevice). Se conserva en el repo como **referencia de
diseño** — la parte de medición (chopping ON–OFF + resta de blanco) es lo que se quiere
recuperar/portar en futuras versiones del firmware y del host.

- **Placa:** Arduino MKR Zero (SAMD21, 3.3 V, ADC de 12 bits).
- **Fuente:** este `.ino` es la única copia en el repo (no hay original externo que reflejar,
  a diferencia de [../WemosD1Mini/](../WemosD1Mini/) o [../DiscPCB/](../DiscPCB/)).
- **Autor:** Edisson Naula.

> ⚠️ Firmware **legacy**: no participa en la cadena del equipo actual
> (Raspberry ↔ Wemos ↔ Pico ↔ EmStat). No lo flashees esperando compatibilidad con la app
> Python de este repo — no habla UDP ni el protocolo `EMSTAT:`/`UDP:`, solo Serial USB.

---

## 1. Qué hace

Mide **corriente de fluorescencia** con un fotodiodo + TIA, usando un *lock-in* pobre de dos
estados (chopping): enciende el LED de excitación, lee, lo apaga, lee, y **acumula la
diferencia** ON−OFF durante N ciclos.

Dos cancelaciones apiladas:

1. **ON − OFF por ciclo** (`OldDevice.ino:39`) — elimina luz ambiente, offset del TIA y
   corriente de oscuridad del fotodiodo: todo lo que sea DC en la escala del chopping.
2. **− baseline del blanco** (`OldDevice.ino:52`) — elimina lo que *sí* modula con el LED pero
   no es la muestra: fuga óptica del LED al detector, autofluorescencia del cartucho/blanco.

Lo que sobrevive a las dos restas es la señal de la muestra.

---

## 2. Hardware

| Recurso | Pin / valor | Constante | Notas |
|---|---|---|---|
| Gate del MOSFET que enciende los LEDs 470 nm | D2 | `LED_GATE` (`:8`) | Salida digital; se deja LOW en `setup` |
| Salida del TIA → ADC | A0 | `ADC_PIN` (`:9`) | Lectura single-ended contra GND |
| Referencia analógica | 3.3 V | `VREF` (`:12`) | Valor **asumido**, no medido — ver §6 |
| Realimentación del TIA | 3 MΩ | `RF` (`:13`) | Fija: no hay conmutación de ganancia |
| Resolución ADC | 12 bits (0..4095) | `analogReadResolution(12)` (`:65`) | Por defecto el core SAMD da 10 bits |
| Puerto serie | USB, 115200 | `:66` | `while(!Serial)` bloquea hasta que se abre el monitor |

**Escalas derivadas** (con `RF = 3 MΩ`, `VREF = 3.3 V`, 12 bits):

- 1 LSB = 3.3 V / 4095 ≈ **0.806 mV** ≈ **0.27 nA** de corriente de fotodiodo.
- Fondo de escala ≈ 3.3 V / 3 MΩ ≈ **1.1 µA**.
- Con 256 ciclos promediados, el piso de ruido (si es blanco y hay dither ≥1 LSB) baja
  ~√256 = 16× → **~17 pA** por lectura. Es la razón de ser de la integración.

---

## 3. Protocolo serie (comandos de un carácter)

115200 baudios, un carácter por comando; el `\n` que manda el monitor cae en el `else`
inexistente y se ignora sin ruido.

| Comando | Función | Código |
|---|---|---|
| `b` | Captura baseline con el **blanco** puesto (512 ciclos) y la guarda en RAM | `captureBaseline()` `:44` |
| `r` / `R` | Lecturas continuas hasta que se pulse cualquier tecla | `:75-89` |
| `c` | Borra el baseline (`baseline_counts = 0`) | `:90` |
| `s` | Imprime `RF`, `SETTLE_US` y el baseline vigente | `:91-95` |

Salida de cada lectura (`printReading`, `:50`):

```
Δcounts(256) = 1234.56   ΔV = 0.99512 V   ΔI = 331.71 nA
```

El campo etiquetado `Δcounts` es en realidad el **neto** (ya con el baseline restado).

`r` es el único que acepta mayúscula; `b`, `c` y `s` son solo minúscula. Antes de entrar al
bucle continuo se **vacía el buffer** (`:79`) para que el CR/LF del Enter no lo detenga de
inmediato, y se vuelve a vaciar al salir (`:88`) para que la tecla de paro no quede como
comando pendiente.

---

## 4. Cadena de medición

```
measureDeltaCounts(cycles)                      // :28
  repetir `cycles` veces:
      LED ON   → delayMicroseconds(SETTLE_US)  → on  = readAvg(SAMPLES_PER_STATE)
      LED OFF  → delayMicroseconds(SETTLE_US)  → off = readAvg(SAMPLES_PER_STATE)
      acc += (on - off)
  return acc / cycles                            // counts promedio por ciclo

printReading()                                   // :50
  net_counts = measureDeltaCounts(CYCLES_MEASURE) - baseline_counts
  dV = net_counts * VREF / 4095.0                // voltios en la salida del TIA
  dI = dV / RF                                   // amperios en el fotodiodo  (se imprime en nA)
```

`readAvg` (`:22`) promedia `SAMPLES_PER_STATE` conversiones dentro de cada estado; acumula en
`long` y divide, así que no hay desbordamiento (256 × 4095 ≈ 1.05 M cabe de sobra).

---

## 5. Parámetros y su compromiso

| Constante | Valor | Rango sugerido | Qué mueve |
|---|---|---|---|
| `SETTLE_US` | 320 µs | 200–400 | Tiempo de asentamiento del TIA tras conmutar. Muy corto ⇒ arrastre del estado anterior (señal subestimada); muy largo ⇒ lectura lenta y más deriva térmica dentro del ciclo |
| `SAMPLES_PER_STATE` | 1 | 1–8 | Promedio *dentro* de cada estado. Sube SNR pero alarga el ciclo; casi siempre conviene más `CYCLES` que más samples |
| `CYCLES_BASELINE` | 512 | — | El blanco se mide más fino que la muestra: el baseline entra en **todas** las lecturas posteriores, su ruido no se promedia después |
| `CYCLES_MEASURE` | 256 | — | Compromiso ruido ↔ refresco |

**Tiempos (cota inferior, solo los `delayMicroseconds`, sin contar el `analogRead`):**

- Ciclo = 2 × 320 µs = 640 µs ⇒ frecuencia de chopping ≲ **1.5 kHz**.
- Baseline (512 ciclos) ≳ **328 ms**.
- Lectura (256 ciclos) ≳ **164 ms**.

El `analogRead` del core SAMD no es gratis (decenas–cientos de µs por conversión), así que
los tiempos reales son bastante mayores. Consecuencia práctica: el comentario `~20 Hz update`
del `delay(50)` (`:84`) **no se cumple** — el techo real ronda 4–5 Hz, y menos con
`SAMPLES_PER_STATE > 1`.

---

## 6. Limitaciones conocidas (leer antes de portar)

- **`while(!Serial)`** (`:67`): la placa no arranca sin un host USB que abra el puerto. Inservible
  para operación autónoma/embebida; quitarlo (o darle timeout) es lo primero en una v2.
- **Baseline volátil**: vive en RAM (`baseline_counts`, `:20`). Reset o desconexión ⇒ se pierde y
  las lecturas siguientes salen sin restar el blanco, **sin avisar**. Candidato claro a EEPROM/flash
  + un flag "baseline no capturado" en la salida.
- **`VREF` asumido**: 3.3 V hardcodeado. La referencia real del MKR Zero se desvía; cualquier
  cifra absoluta en nA arrastra ese error. Para valores absolutos hace falta calibrar (medir el
  riel o inyectar una corriente patrón). Para comparaciones relativas entre muestras no importa.
- **División entre 4095** (`:53`): con 12 bits el fondo de escala es 4096 LSB; el sesgo es ~0.02 %,
  irrelevante frente al punto anterior, pero conviene saberlo si algún día se calibra en serio.
- **Ganancia fija** (`RF = 3 MΩ`): sin conmutación de rango. Fuera de ~1.1 µA satura sin
  detección de saturación — nada avisa si el ADC pegó en 4095.
- **Todo bloqueante**: `delayMicroseconds` + bucle cerrado. No hay forma de atender otra tarea
  (red, motor, otro sensor) durante una lectura.
- **Sin marca de tiempo ni persistencia**: la salida es texto para ojo humano; no hay CSV, ni
  contador de muestra, ni timestamp. Cualquier análisis posterior exige recapturar el monitor serie.
- **Deriva lineal no cancelada**: el patrón ON,OFF cancela DC pero no una rampa. Un esquema
  ON,OFF,OFF,ON (chopping balanceado) cancela también la deriva de primer orden — mejora barata
  para la siguiente versión.

---

## 7. Relación con el equipo actual

El CD microdevice mide fluorescencia por otro camino: Raspberry Pi + **ADS1115** por I2C, con el
LED de fluorescencia en el GPIO 24 (`led_fluorescence_pin`, `templates/constants.py`), y la lógica
en `PcrFrame._read_fluorescence` — ventanas de baseline (0.5 s, luz OFF) / excitación (2.0 s, luz ON)
/ post (0.5 s), escalar = media(luz) − media(baseline). Ver
[docs/cambios_fluorescencia.md](../../docs/cambios_fluorescencia.md).

Diferencias que importan si se quiere portar el enfoque viejo:

| | OldDevice (MKR Zero) | Equipo actual (Pi + ADS1115) |
|---|---|---|
| Modulación | Chopping ~1.5 kHz, cientos de ciclos | Dos ventanas largas (segundos), una conmutación |
| Frontend | TIA discreto, `RF` 3 MΩ, ADC 12 bits del MCU | ADS1115 16 bits, FSR configurable (`ads_fsr`) |
| Rechazo | Ambiente y deriva DC cancelados por ciclo | Solo el offset lento; deriva dentro de la ventana entra en la señal |
| Blanco | Baseline explícito del blanco, restado en counts | No hay resta de blanco separada |
| Salida | Texto por Serial | CSV (`photodetector_data_*.csv`, `photodetector_raw_*.csv`) + plot |

La ventaja real del esquema viejo es el **rechazo de ambiente**: al conmutar a ~1.5 kHz, la luz de
la sala y las derivas térmicas quedan fuera de la banda. El ADS1115 llega a 860 SPS, así que un
chopping equivalente en el equipo actual sería de orden ~100 Hz — más lento, pero ya muy por
encima de las derivas y del parpadeo de red. Es el camino a explorar si el fotodetector actual
se ve limitado por ambiente y no por ruido del detector.

---

## 8. Build & Upload

Arduino IDE o `arduino-cli`. Board: `arduino:samd:mkrzero`.

```powershell
arduino-cli core install arduino:samd
arduino-cli compile --fqbn arduino:samd:mkrzero firmware/OldDevice
arduino-cli upload  --fqbn arduino:samd:mkrzero --port <COMx> firmware/OldDevice
```

Sin librerías externas: solo el core (`analogRead`, `analogReadResolution`, `Serial`).

---

__author__ = "Edisson A. Naula"
__date__ = "$ 04/08/2026 $"
