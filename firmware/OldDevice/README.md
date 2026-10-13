# OldDevice — firmware completo del equipo anterior (PCR + fluorescencia)

Documentación del sketch [OldDevice.ino](OldDevice.ino): el **firmware del instrumento
anterior** al CD microdevice. No es un lector de fluorescencia suelto — es la máquina
completa: termociclador PCR (relay + PID), enfriado por giro del disco, LCD de estado,
temperatura por UDP y **medición de fluorescencia automática al final de cada ciclo**.

- **Placa:** SAMD21 con módulo WiFi NINA (el sketch usa `WiFiNINA`, p. ej. MKR WiFi 1010).
  ADC de 12 bits.
- **Fuente:** este `.ino` es la única copia en el repo (no hay original externo que
  reflejar, a diferencia de [../WemosD1Mini/](../WemosD1Mini/) o [../DiscPCB/](../DiscPCB/)).
- **Autor:** Edisson Naula.

> ⚠️ Firmware **legacy**: no participa en la cadena del equipo actual
> (Raspberry ↔ Wemos ↔ Pico ↔ EmStat). Escucha UDP en el puerto 5005 pero espera un
> **número plano** (`atof`) como payload, no el formato `UDP:<a>:<b>:<temp>` del disco
> actual — no son compatibles sin adaptar el emisor. La salida de datos es solo Serial USB.

> 📌 **26/08/2026** — la medición de fluorescencia se migró del integrador ON–OFF
> (chopping ~1.5 kHz, versión anterior de este archivo) al **método de
> [FluorReaderV2](../FlourReaderV2/FluorReaderV2.ino)**: promedio simple + baseline
> oscuro en nA. El chopping sobrevive como referencia en [../FluorReader/](../FluorReader/).
> Ver §5.

---

## 1. Qué hace

Máquina de estados de PCR ([OldDevice.ino:129](OldDevice.ino#L129)):

```
PRE_SPIN → INITIAL_HEAT → INITIAL_HOLD
   → [ HEAT → HOLD_HIGH → COOL → HOLD_LOW → PAUSE ] × MaxCycles
   → FINAL_HOLD (y se detiene)
```

En `PAUSE` — es decir, **al terminar cada ciclo térmico** — se dispara una medición de
fluorescencia (`modeRun()`, [OldDevice.ino:513-515](OldDevice.ino#L513-L515)) y el valor
corregido pasa a ser la tercera columna del log CSV (§6).

Antes de correr hay un **gate** por serial ([OldDevice.ino:150](OldDevice.ino#L150)):
un primer `f` captura el baseline oscuro de fluorescencia, un segundo `f` arranca el run.

## 2. Hardware / pines

| Recurso | Pin / valor | Constante |
|---|---|---|
| Relay del heater (mecánico) | D4 | `RelayPin` |
| LED de power | D1 | `PowerLedPin` |
| LED de estado WiFi | D0 | `WifiLedPin` |
| LED "llegó paquete de temperatura" | D5 | `SenderLedPin` |
| LED de excitación (fluorescencia) | D2 | `LED_Fluorescence` |
| Fotodiodo + TIA → ADC | A0 | `PHD_receiver` |
| Stepper del disco (SmoothStepper) | DIR=3, PUL=7 | [OldDevice.ino:18](OldDevice.ino#L18) |
| LCD I2C 16x4 | 0x27 | [OldDevice.ino:21](OldDevice.ino#L21) |

Librerías: `Wire`, `LiquidCrystal_I2C`, `WiFiNINA`, `WiFiUdp`, `PID_v1`, `SmoothStepper`.
Las credenciales WiFi están **hardcodeadas** (`ssid`/`password`, líneas 24-25) y el
`setup()` bloquea hasta conectar ([OldDevice.ino:240](OldDevice.ino#L240)) — sin esa red
la placa no arranca.

## 3. Temperatura por UDP (puerto 5005)

Un emisor externo manda la temperatura como texto plano; el firmware la parsea con `atof`
y la suaviza con EMA (`ALPHA = 0.20`, [OldDevice.ino:44](OldDevice.ino#L44)). Ese valor
filtrado es la entrada del PID. `SenderLedPin` se enciende cuando llegan paquetes con
valor > 0.

El emisor de referencia es [../DisckWifiArduino/](../DisckWifiArduino/) (MKR + MAX31855):
desde el 02/09/2026 **emite en broadcast** a la dirección dirigida de la subred (puerto
5005), así que no hay que configurar la IP de esta placa en el emisor.

## 4. Control térmico

Relay mecánico protegido y PID por ventana de tiempo:

- **Ventana** de 5 s (`WindowSize`, [OldDevice.ino:33](OldDevice.ino#L33)); la salida del
  PID (0–5000) es el tiempo ON dentro de la ventana. Dwell mínimo de 700 ms ON/OFF
  (`MIN_ON_MS`/`MIN_OFF_MS`) para no matar el relay; `setRelay()` en
  [OldDevice.ino:212](OldDevice.ino#L212).
- **Lejos del setpoint** (|err| > 3 °C, `FAST_RAMP_ERR`): bang-bang puro.
- **Cerca**: PID con separación integral (`I_ZONE = 1.5` °C), deadband ±0.3 °C, y
  **coast predictivo**: si la temperatura proyectada a 2 s (`COAST_HORIZON_S`,
  [OldDevice.ino:67](OldDevice.ino#L67)) rebasa el setpoint, apaga antes de llegar.
- Las ganancias Kp/Ki/Kd se **re-sintonizan en cada transición de etapa** (rampa agresiva
  al subir, hold conservador al mantener).
- `inhibitHeater()` corta el heater alrededor de cada arranque de motor.

## 5. Programa PCR y enfriado

| Parámetro | Valor | Ref |
|---|---|---|
| Calentamiento/hold inicial | 95 °C, 180 s | [OldDevice.ino:75](OldDevice.ino#L75), `:80` |
| Ciclo: denaturación / annealing | 95 °C / 63 °C, holds de 1 s | `:76-82` |
| Ciclos | 40 (`MaxCycles`) | [OldDevice.ino:86](OldDevice.ino#L86) |
| Pausa fin de ciclo (mide fluorescencia) | 100 ms | `:84` |
| Hold final | 63 °C, 120 s, luego `while(true)` | `:83` |
| Enfriado | ráfagas de motor 1200 RPM × 40 rev (máx. 1) | `:89-92`, [OldDevice.ino:446](OldDevice.ino#L446) |
| Pre-spin | 800 RPM × 100 rev antes de calentar | `:95-96` |

## 6. Fluorescencia — método FluorReaderV2

La medición replica [FluorReaderV2.ino](../FlourReaderV2/FluorReaderV2.ino) (promedio
simple + baseline en nA), con el LED automatizado; ya **no hay chopping ON–OFF** ni
`autoPolarity`.

| Constante | Valor | Nota |
|---|---|---|
| `ADC_VREF` | **1.7 V** | Calibración empírica de V2 (TIA alimentado a 3.5 V; sería 3.3 con 5 V). [OldDevice.ino:108](OldDevice.ino#L108) |
| `RF_OHMS` | 3 MΩ | Realimentación del TIA |
| `SAMPLES_AVG` | 40 | Muestras promediadas por lectura |
| `BASELINE_SAMPLES` | 200 | Lecturas promediadas para el baseline (cada 5 ms) |
| `LED_SETTLE_MS` | 50 | LED ON → settle → muestrear |

Cadena: `readAvgCounts` → `countsToVolts` → `voltsToCurrentA` → ×1e9 =
`readCurrentRaw_nA()` ([OldDevice.ino:177](OldDevice.ino#L177)), en nA sin baseline.

> 📌 **30/08/2026** — se agregó `analogReadResolution(12)` al `setup()`
> ([OldDevice.ino:237](OldDevice.ino#L237)): la conversión divide entre 4095 pero el
> SAMD21 arranca en 10 bits, así que las lecturas previas a este fix salían con escala
> **~4× baja**. FluorReaderV2 siempre lo llamó; la migración del método lo había omitido.

- **Baseline oscuro** (`captureBaseline()`, [OldDevice.ino:183](OldDevice.ino#L183)):
  con el primer `f` del gate, LED OFF y detector a oscuras; `delay(1000)` + 200 lecturas
  → `baseline_nA` (~2.2 s). Vive en RAM: un reset lo pierde.
- **Medición por ciclo** (`modeRun()`, [OldDevice.ino:194](OldDevice.ino#L194)):
  LED ON → 50 ms de settle (transitorio del LED, lo más parecido al "LED encendido
  estable" con que se calibró V2) → 40 muestras → LED OFF. `corregido = raw − baseline`,
  **recortado a 0 si sale negativo** (fiel a V2 — ojo: esto oculta deriva térmica del
  baseline). Se guarda en `dI_nA[ciclo-1]` y en `lastFluor_nA` para el CSV.

Compromiso asumido al dejar el chopping: el baseline oscuro solo resta corriente de
oscuridad + offset del TIA; **la fuga óptica del LED y la luz ambiente entran en la
señal**. Si eso vuelve a doler, las alternativas son baseline con blanco + LED ON, o el
integrador ON–OFF que se conserva en [../FluorReader/](../FluorReader/).

## 7. Salida serie (CSV)

9600 baudios. Header impreso en `setup()`
([OldDevice.ino:227](OldDevice.ino#L227)):

```
Time(s),Temperature(C),Current signal (nA)
12.35,94.80,0.000
...
98.20,63.10,4.512    ← tras el ciclo 1
98.25,63.05,4.512
```

- Línea cada ~50 ms durante el run ([OldDevice.ino:566-568](OldDevice.ino#L566-L568)) y
  también dentro de las ráfagas de enfriado ([OldDevice.ino:487-489](OldDevice.ino#L487-L489)).
- La tercera columna **repite el último valor corregido** hasta la siguiente medición;
  `0.000` antes de la primera. No hay línea suelta `dI=` — todo va en la columna.
- Los mensajes del gate (`Press 'f'...`, `Baseline stored = ... nA`) salen antes de
  `RUNNING` y no son CSV; al post-procesar, filtrar líneas que no tengan dos comas.

El LCD 16x4 muestra temperatura (con flag `F` mientras se mide fluorescencia),
Heating/Cooling, setpoint y etapa + ciclo.

## 8. Limitaciones conocidas

- **Baseline volátil** en RAM, sin persistencia ni flag de "no capturado".
- **`ADC_VREF = 1.7` es empírico**: los nA absolutos solo valen con el mismo montaje con
  el que se calibró V2; entre montajes, comparar solo relativos.
- **Sin rechazo de ambiente / fuga del LED** (ver §6).
- **El recorte a 0** hace invisible en los datos una deriva del baseline con temperatura
  (la placa vive junto a un heater a 95 °C).
- **WiFi bloqueante y hardcodeado**: sin esa SSID no arranca.
- **`FINAL_HOLD` termina en `while(true)`**: hay que resetear para otro run.

## 9. Build & Upload

Arduino IDE o `arduino-cli`. Placa con NINA, p. ej. MKR WiFi 1010:

```powershell
arduino-cli core install arduino:samd
arduino-cli compile --fqbn arduino:samd:mkrwifi1010 firmware/OldDevice
arduino-cli upload  --fqbn arduino:samd:mkrwifi1010 --port <COMx> firmware/OldDevice
```

Librerías externas: `LiquidCrystal_I2C`, `WiFiNINA`, `PID` (Brett Beauregard, `PID_v1.h`),
`SmoothStepper`.

---

__author__ = "Edisson A. Naula"
__date__ = "$ 26/08/2026 $"
