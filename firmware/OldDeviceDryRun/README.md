# OldDeviceDryRun — corrida en seco (actuadores sin temperatura)

Documentación del sketch [OldDeviceDryRun.ino](OldDeviceDryRun.ino): versión **dry-run**
de [../OldDevice/OldDevice.ino](../OldDevice/OldDevice.ino) para probar en banco los
**movimientos del motor y las mediciones de fluorescencia**. La temperatura se eliminó
por completo (sin WiFi/UDP, sin PID); el procedimiento PCR se ejecuta íntegro con
**etapas de duración fija** para que cada actuador cumpla su secuencia real.

- **Placa:** SAMD21 (misma que OldDevice; ya no requiere el módulo WiFi NINA).
- **Fuente:** este `.ino` es la única copia en el repo, derivada de OldDevice — no hay
  original externo que reflejar.
- **Autor:** Edisson Naula.

> ⚠️ **No mide ni controla temperatura.** No conectar el calentador a una carga real
> esperando control térmico: el relay conmuta por etapa, no por temperatura.

---

## 1. Qué hace

Misma máquina de estados que OldDevice, pero cada transición es **por tiempo**
(las condiciones `Input >= 96`, `Input >= 93`, `Input > 63` desaparecieron):

```
PRE_SPIN → INITIAL_HEAT → INITIAL_HOLD
   → [ HEAT → HOLD_HIGH → COOL → HOLD_LOW → PAUSE ] × MaxCycles
   → FINAL_HOLD (y se detiene)
```

Por etapa:

| Etapa | Duración (default) | Relay | Motor | Fluorescencia |
|---|---|---|---|---|
| `PRE_SPIN` | lo que tarde el giro | OFF (inhibido) | 800 RPM × 100 revs | — |
| `INITIAL_HEAT` | 10 s (`InitialHeatTime`) | **ON** | — | — |
| `INITIAL_HOLD` | 15 s (`InitialHoldTime`, real: 180 s) | OFF | — | — |
| `HEAT` | 8 s (`HeatTime`) | **ON** | — | — |
| `HOLD_HIGH` | 10 s (`HoldTimeHigh`, real) | OFF | — | — |
| `COOL` | lo que tarde el burst | OFF (inhibido) | **1 burst** 1800 RPM × 40 revs | — |
| `HOLD_LOW` | 10 s (`HoldTimeLow`, real) | OFF | — | — |
| `PAUSE` | 100 ms | OFF | — | **medición** (`modeRun()`) |
| `FINAL_HOLD` | 15 s (`FinalHoldTime`, real: 60 s) | OFF | — | — |

Con los defaults (`MaxCycles = 5`) la corrida completa dura **≈ 3–4 min**. Todos los
tiempos son constantes editables al inicio del sketch (bloque *"EDIT HERE"*).

Notas heredadas del original, conservadas a propósito:

- En `COOL` siempre hay **exactamente un burst** (en OldDevice `MaxCoolingBursts = 1`
  ya lo limitaba; sin temperatura no hay condición que re-verificar).
- La medición de fluorescencia ocurre en `PAUSE`, es decir **entre ciclos**: con
  `MaxCycles = 5` hay 4 mediciones (el último ciclo pasa directo a `FINAL_HOLD`),
  igual que en OldDevice.
- Protección del relay mecánico intacta: dwell mínimo `MIN_ON_MS`/`MIN_OFF_MS` = 700 ms
  e inhibición del heater (`inhibitHeater`) alrededor de cada movimiento del motor.

## 2. Hardware / pines

Mismo cableado que OldDevice, con dos LEDs re-semantizados:

| Recurso | Pin | Cambio vs OldDevice |
|---|---|---|
| Relay del heater | D4 | igual (ON solo en `INITIAL_HEAT`/`HEAT`) |
| LED de power | D1 | igual |
| LED de estado WiFi | D0 | **sin uso** (queda LOW; no hay WiFi) |
| LED "paquete de temperatura" | D5 | **reutilizado**: enciende durante cada medición de fluorescencia |
| LED de excitación | D2 | igual |
| Fotodiodo + TIA → ADC | A0 | igual |
| Stepper (SmoothStepper) | DIR=3, PUL=7 | igual |
| LCD I2C 16x4 | 0x27 | igual |

Librerías: `Wire`, `LiquidCrystal_I2C`, `SmoothStepper`. Ya **no** se usan `WiFiNINA`,
`WiFiUdp` ni `PID_v1` — el arranque es instantáneo y no depende de ningún hotspot.

## 3. Fluorescencia (real, método FluorReaderV2)

La medición es la única parte "de verdad": promedio simple de 40 muestras del ADC →
V (`ADC_VREF = 1.7`) → nA, con baseline oscuro (LED OFF, 200 lecturas) restado y clamp
≥ 0 — idéntico a [../FlourReaderV2/FluorReaderV2.ino](../FlourReaderV2/FluorReaderV2.ino)
y a la versión actual de OldDevice.

Igual que FluorReaderV2 (y que OldDevice desde el fix del 30/08/2026), el `setup()`
llama `analogReadResolution(12)` — el SAMD21 arranca en 10 bits y la conversión divide
entre 4095, así que sin esa línea las lecturas saldrían con escala ~4× baja.

## 4. Protocolo serial

Gate de doble `f`, igual que OldDevice:

1. Primer `f` → captura el baseline oscuro (mantener el detector tapado).
2. Segundo `f` → arranca la corrida. Nada se mueve antes.

Salida CSV (una línea cada 500 ms, no cada ~50 ms como el original):

```
# OldDeviceDryRun: Temperature(C) is the nominal stage setpoint, not a measurement
Time(s),Temperature(C),Current signal (nA),Raw (nA)
12.50,96.0,0.000000,0.000000
...
# Cycle 1 fluorescence = 12.345 nA
```

- `Temperature(C)` lleva el **setpoint nominal de la etapa** (25 / 96 / 93 / 63):
  graficada se ve como los escalones del perfil PCR y sirve para verificar la
  secuencia, pero **no es una medición**.
- Las líneas `# ...` son comentarios/eventos (header y una por medición de
  fluorescencia); filtrarlas al parsear como CSV.

## 5. LCD

```
SIM Hold High
Left: 8 s
F: 12.345 nA
C:3/5 Rly:OFF
```

Etapa, segundos restantes (`-` en etapas por evento: pre-spin y burst), última
fluorescencia corregida y ciclo + estado del relay. Escritura con ancho fijo de
16 columnas (`lcdPrintLine`) para no invadir otras filas del 16x4.

---

__author__ = "Edisson A. Naula"
