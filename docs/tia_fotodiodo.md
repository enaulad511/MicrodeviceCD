# TIA del fotodiodo: rediseño con OPA320 y Rf ajustable (trimmer de 1 MΩ)

Diseño del 11/11/2026 para la actualización del amplificador de transimpedancia (TIA) del
fotorreceptor de fluorescencia. Parte de lo que hay montado y medido, no de supuestos, y
usa las piezas disponibles: **OPA320AISBVR**, **MCP6001T**, resistencias, condensadores
cerámicos y **trimmers de 1 MΩ**. El software de lectura (ventanas, `use_diff`, `ads_fsr`)
está en [cambios_fluorescencia.md](cambios_fluorescencia.md); aquí solo el hardware y los
números que lo justifican.

> Primera versión del mismo día, descartada: suponía Rf = 3 MΩ (la del equipo antiguo) y
> por tanto ≈ 17 nA de fotocorriente, y proponía Rf 10 MΩ + una etapa de ganancia. La Rf
> real es **56.3 kΩ** y la fotocorriente ≈ **0.9 µA**: con eso la etapa extra sobra y el
> trimmer puede ir en la propia Rf. Esa variante queda anotada en §9 por si algún día la
> corriente baja de verdad (mejor filtrado óptico, §9).

## 1. Lo que hay hoy (medido)

**Cadena actual.** Fotodiodo **MTD5052W** (Marktech, silicio visible 410–580 nm, pico 525 nm,
0.3 A/W, chip de 0.62 mm², corriente de oscuridad 5 pA típ / 30 pA máx a 5 V, Cj 500–700 pF a
5 V, inversa máx 5 V; [hoja de datos](https://www.mouser.com/datasheet/3/3777/1/MTD5052W.pdf)),
**ánodo a GND** → trabaja con 1.65 V de polarización inversa, con un **filtro de emisión
delante** (modelo y banda: §10) → TIA con **OPA333** y
**Rf = 56.3 kΩ** (medida el 11/11) →
ADS1115 en **diferencial**: A0 = salida del TIA, **A1 = otro pin del op-amp** (la entrada
no inversora, Vref, o la inversora; por el cortocircuito virtual ambas miden lo mismo salvo
los ≈ 10 µV de Vos del OPA333). Es decir, **el voltaje guardado no es la salida del
amplificador respecto a GND, es `Ip × Rf`** directamente. `ads_fsr = 0.256` (7.8 µV/LSB =
**139 pA/LSB**), 64 SPS continuo, 4 promedios por muestra, una muestra cada 0.1 s, ventanas
0.5 s oscuro / 2.0 s LED / 0.5 s oscuro ([PcrFrame.py:2580](../ui/PcrFrame.py#L2580)).
Dividir por 56.3 kΩ convierte a corriente cualquier archivo guardado hasta esta fecha.

**Niveles reales** (hoja `photodetector_raw` de Newn4 y Newn6, 04–05/11, 36 ciclos cada una):

| Magnitud | Voltaje | Corriente (÷ 56.3 kΩ) | Nota |
|---|---|---|---|
| Oscuro (ventana baseline) | 0.21 mV, sd 0.03 mV | **3.7 nA**, sd 0.53 nA | sd ≈ 4 LSB: es el ADS |
| LED ON asentado (t > 0.5 s) | 50.9 mV, sd 0.43 mV | **904 nA**, sd 7.6 nA (0.84 %) | muestra a muestra 0.23 mV |
| Media ON, ciclo a ciclo | sd 1.6 mV | sd 28 nA (3 %) | repetibilidad real de la medida |
| 1.ª muestra ON / 1.ª muestra OFF | ≈ 1/3 y ≈ 2/3 del valor | — | transitorio; se asienta en < 100 ms |
| Deriva dentro de los 2 s con LED | ≈ −1 mV | ≈ −18 nA (−2 %) | el LED se calienta y baja de brillo |

Si se calcula la sd de la ventana ON **incluyendo** la primera muestra sale ≈ 7 mV: es el
transitorio, no ruido. Las pruebas de Quick Control del 10/11
(`files/unified_fluor_20261110_154738.xlsx`) dieron mesetas de 14–19 mV (250–340 nA) con
LED y ≈ 1.5 mV (27 nA) sin; las del 09/11 rondan 1 mV (18 nA). Son la **misma electrónica**
(misma Rf, misma lectura), así que la diferencia con las corridas PCR es óptica (muestra,
disco, posición del LED), no del TIA (§10).

**Lectura de esos números.**
- La fotocorriente es **grande**: ≈ 1 µA con LED, del orden del fondo de escala del equipo
  antiguo. El ruido de disparo (0.54 pA/√Hz) y el Johnson de 56 kΩ (0.54 pA/√Hz) son tres
  órdenes menores que lo medido: la electrónica del TIA no limita nada.
- Los 3.7 nA "a oscuras" **no son corriente de oscuridad** (la hoja de datos da 5–30 pA): es
  luz residual que llega al fotodiodo con el LED apagado, o fuga de la placa. Se distingue
  tapándolo (§8).
- El ruido **a oscuras** (0.53 nA rms ≈ 4 LSB) es el **ADS**: con Rf tan baja el ADC
  trabaja al 20 % del fondo de escala y su ruido pesa. Esto sí lo baja más Rf.
- Con luz el ruido es **14× mayor y proporcional a la señal** (0.84 %): viene del LED
  (corriente, temperatura) o de la óptica. Más ganancia no cambia esa fracción.
- La dispersión ciclo a ciclo (3 %) es mecánica/óptica (posición del disco).
- Conclusión: subir Rf de 56 kΩ a ≈ 0.8 MΩ usa el rango del ADS, baja el piso a oscuras
  3–6× y no toca el ruido con luz. Es lo que se diseña; lo demás está en §9.

## 2. Requisitos del caso

- Señal **unipolar** (positiva sobre Vref), ≈ 0.9 µA con LED y ≈ 4 nA a oscuras con el
  montaje actual. Puede **subir con la amplificación** (en el equipo antiguo el nivel con
  LED llegaba a duplicarse): dejar **margen ×2** sobre el nivel con LED.
- **Lenta**: ventanas de 2 s muestreadas a 10 Hz → basta un ancho de banda de 10–30 Hz,
  pero debe asentarse en < 100 ms para que la primera muestra ON valga.
- **Rango de salida limitado por el ADS**: el ADS1115 no lee por encima de su VDD, y como
  comparte el I2C a 3.3 V del Pi, se queda a **3.3 V** (a 5 V su nivel lógico alto es 3.5 V y
  el Pi no llega). Con Vref = 1.65 V quedan **≈ 1.6 V de margen positivo**; con margen ×2,
  el nivel con LED debe quedar en ≤ 0.8 V → **Rf ≤ 0.88 MΩ**.
- **Ganancia ajustable** con el trimmer de 1 MΩ. Con ≈ 1 µA el nodo sumador es un nodo de
  µA, no de pA: ni las fugas del PCB (1 nA = 0.1 %) ni el cursor del trimmer pesan, así que
  **el trimmer puede ir en la propia Rf**.
- **Canales del ADS**: A0 y A1 siguen ocupados por el TIA actual, así que el nuevo va en
  **A2 (salida) y A3 (Vref)**, par diferencial 2-3 (el mux del ADS1115 solo forma 0-1, 0-3,
  1-3 y 2-3). El par deja de estar fijo en el código y sale a `settings.json` →
  `photoreceptor.ch_p` / `ch_n` (§7); además cambia `ads_fsr`.

## 3. Circuito propuesto

Una sola etapa más el buffer de referencia, todo a 3.3 V:

```
3V3 ─┬────────────────────────┬──────────────────┐
     │                        │                  │
    R5 10k               C5 100n (U1)       C6 100n (U2)      + C10 10µ en 3V3
     │                        │                  │
     ├──────────┐            GND                GND
     │          │
    R6 10k    C7 10µ        ┌──────────┐
     │          │   Vref ───┤+   U2    ├──┬── Vref_buf ───────── ADS A3 (C8 100n a GND junto al ADS)
    GND        GND          │ MCP6001  │  │
                       ┌────┤-         │  │
                       │    └──────────┘  │
                       └──────────────────┘

                 Rf = R1 100k + Rt 1 MΩ (trimmer como reóstato)   ║   Cf 10 nF
              ┌──────[R1]────[Rt]─────────┐
              ├──────────┤Cf├─────────────┤
              │   ┌──────────┐            │
  PD cátodo ──┴───┤-   U1    ├────────────┴── Vout ── R4 10k ─┬── ADS A2
  PD ánodo ── GND             │                              C4 1 µF
       Vref_buf ─┤+  OPA320  │                               │
                 └──────────┘                               GND
```

Ecuaciones:

- `Vout = Vref + Ip·(R1 + Rt)`
- El ADS lee `A2 − A3 = Ip·(R1 + Rt)`, independiente de Vref, con Rf de **0.1 a 1.1 MΩ**
  (×1.8 a ×19.5 respecto a los 56.3 kΩ de hoy)

| Ref | Valor | Función |
|---|---|---|
| U1 | OPA320 | TIA |
| R1 | 100 kΩ | suelo del rango de ganancia (×1.8 respecto a hoy) y tope si el trimmer queda a 0 |
| Rt | trimmer 1 MΩ, **cursor soldado a un extremo** | ajuste de Rf; si el cursor se abre queda la pista entera (1 MΩ), no el lazo abierto |
| Cf | 10 nF, cerámico monolítico (código 103; 472 o 223 también sirven) | 14.5 Hz con Rf = 1.1 MΩ, τ 11 ms; 32 Hz con 0.5 MΩ; estabilidad sobrada |
| R4, C4 | 10 kΩ, 1 µF | segundo polo a 16 Hz y aísla la entrada conmutada del ADS |
| U2 | MCP6001 | buffer de Vref (alimenta al TIA y a A3) |
| R5, R6, C7 | 10 kΩ, 10 kΩ, 10 µF | Vref = 3.3/2 = 1.65 V |
| C5, C6 | 100 nF | desacoplo pegado a cada op-amp; C10 10 µF en la entrada de 3.3 V |
| C8 | 100 nF | A3 a GND, junto al ADS |

**Fotodiodo MTD5052W, como hoy: cátodo al nodo sumador, ánodo a GND** (1.65 V de
polarización inversa, dentro de los 5 V máximos). Con el cátodo en el nodo la lectura sube
con la luz (A2 − A3 positivo), igual que ahora; si al montar sale negativo, el diodo está al
revés: girarlo (el multiplexor del ADS solo forma A2 − A3, no A3 − A2, y A3 debe seguir
siendo Vref para la cancelación de §4). La primera versión de este doc proponía el ánodo a
Vref_buf (fotovoltaico) por miedo a la corriente de oscuridad; la hoja de datos la da en
5–30 pA a 5 V, así que no hay nada que ganar: la inversa deja menos capacidad (≈ 1 nF a
1.65 V frente a ≈ 2 nF a 0 V) y una conexión menos. Si algún día se prefiere fotovoltaico,
basta mover el ánodo a Vref_buf; nada más cambia.

**Pin de referencia**: en el TIA actual A1 va a "otro pin" del OPA333; en el nuevo, A3 va a
Vref_buf (entrada no inversora), no a la inversora. Mide lo mismo y deja el muestreador
conmutado del ADS fuera del nodo sumador.

Patillaje: los dos encapsulados SOT-23-5 siguen el orden estándar **1 OUT, 2 V−, 3 +IN,
4 −IN, 5 V+** (OPA320 DBV; MCP6001 OT). Las variantes MCP6001R/U cambian el orden:
confirmar en la hoja de datos antes de soldar.

**Alimentación: fuente única de 3.3 V**, la misma del ADS1115 y del Pi (no 5 V: las entradas
del ADS no pueden pasar de su VDD). OPA320: **V+ (pin 5) = 3.3 V, V− (pin 2) = GND**.
MCP6001: **VDD (pin 5) = 3.3 V, VSS (pin 2) = GND**. No hay riel negativo: Vref a mitad de
riel deja las entradas en modo común 1.65 V y las salidas entre ≈ 0.01 y 3.25 V (los dos
son rail-to-rail), que es todo lo que necesita la lectura diferencial. 100 nF de V+/VDD a
GND pegado a cada chip (C5, C6).

### Conexiones pin a pin

Encapsulados SOT-23-5 vistos desde arriba, marca/pin 1 abajo a la izquierda: 1-2-3 en un
lado, 4-5 en el otro.

**U1 — OPA320 (TIA)**

| Pin | Nombre | Conectar a |
|---|---|---|
| 1 | OUT | Vout: extremo de Rt (terminal 3 del trimmer) y Cf; de aquí R4 (10 kΩ) → A2 del ADS |
| 2 | V− | GND |
| 3 | +IN | Vref_buf (pin 1 de U2) |
| 4 | −IN | nodo sumador: cátodo del fotodiodo, R1 (100 kΩ) y Cf (10 nF). Nada más en este nodo |
| 5 | V+ | 3.3 V, con C5 (100 nF) a GND pegado al pin |

**U2 — MCP6001 (buffer de Vref)**

| Pin | Nombre | Conectar a |
|---|---|---|
| 1 | VOUT | Vref_buf: pin 3 de U1, A3 del ADS (con C8 100 nF a GND junto al ADS) y su propio pin 4 |
| 2 | VSS | GND |
| 3 | VIN+ | Vref: unión de R5 (10 kΩ a 3.3 V) y R6 (10 kΩ a GND), con C7 (10 µF) a GND |
| 4 | VIN− | pin 1 (VOUT): seguidor de ganancia 1 |
| 5 | VDD | 3.3 V, con C6 (100 nF) a GND pegado al pin |

**Fotodiodo MTD5052W** (ánodo a GND: 1.65 V de inversa, como hoy)

| Terminal | Conectar a |
|---|---|
| cátodo (K, normalmente el terminal corto o la marca) | pin 4 de U1 (−IN) |
| ánodo (A) | GND (opcional: Vref_buf, pin 1 de U2, para modo fotovoltaico) |

Si la lectura sale negativa con luz, está al revés: girarlo.

**Rt — trimmer 1 MΩ (3 terminales, como reóstato)**

| Terminal | Conectar a |
|---|---|
| 1 (extremo de pista) | R1 (100 kΩ), cuyo otro extremo va al pin 4 de U1 |
| 2 (cursor) | soldado al terminal 3 |
| 3 (extremo de pista) | pin 1 de U1 (OUT) |

Rf = R1 + resistencia entre el terminal 1 y el cursor. Con el cursor soldado al 3, si el
cursor pierde contacto queda la pista entera (1 MΩ) en el lazo, no el lazo abierto.

**ADS1115 (placa Adafruit)**

| Pin | Conectar a |
|---|---|
| A2 | R4 (10 kΩ) desde el pin 1 de U1; C4 (1 µF) de A2 a GND |
| A3 | Vref_buf (pin 1 de U2); C8 (100 nF) de A3 a GND |
| A0, A1 | como hoy (TIA actual); no se tocan |
| VDD | 3.3 V del Pi (el mismo riel que U1 y U2) |
| GND | GND común con la placa del TIA, un solo punto |
| SDA, SCL | al Pi, como hoy |
| ADDR | como hoy (GND → dirección 0x48, la que usa `Ads1115Reader`) |
| ALRT | sin conectar |

Lectura: `photoreceptor.ch_p = 2`, `ch_n = 3`, `use_diff = 1` (§7).

## 4. Por qué cada elección

- **OPA320 en el TIA, MCP6001 en el buffer.** Con 0.9 µA los dos servirían en el TIA (el
  Cf mínimo de estabilidad del MCP6001 a 1.1 MΩ es ≈ 12 pF con el ≈ 1 nF del MTD5052W, y su ruido de 28 nV/√Hz queda
  bajo el Johnson de 1 MΩ, 129 nV/√Hz). Se elige el OPA320 por Vos 150 µV máx con
  1.5 µV/°C (el MCP6001 tiene 3.5 mV máx: estático y restado por el baseline, pero equivale
  a 3.5 nA a 1 MΩ), Ib ±0.9 pA, GBW 20 MHz y entrada sin cruce (zero-crossover), 1.8–5.5 V
  ([TI OPA320](https://www.ti.com/product/OPA320)). El MCP6001 (Ib 1 pA, 100 µA, 1.8–5.5 V,
  [Microchip MCP6001](https://www.microchip.com/en-us/product/MCP6001)) sobra para el
  buffer: su Vos es común al TIA y a A3 y se cancela.
- **Trimmer en Rf, sin segunda etapa.** Con señal de µA el nodo sumador no es sensible:
  una sola etapa son menos piezas, un solo offset y menos ruido. El trimmer en serie con
  R1 da ×1.8 a ×19.5 respecto a hoy, que cubre de sobra el objetivo (×14 para 0.8 V).
- **R1 = 100 kΩ en serie.** Fija el mínimo (no se puede dejar el TIA sin realimentación
  resistiva) y, con el cursor soldado a un extremo, un cursor abierto deja Rf = 1.1 MΩ en
  vez de abrir el lazo.
- **Cf = 10 nF.** Con Rf = 1.1 MΩ: 14.5 Hz, τ 11 ms, 99 % en 51 ms, asentado antes de la
  primera muestra ON. Con Rf = 0.5 MΩ: 32 Hz. El MTD5052W tiene 500–700 pF a 5 V, o sea
  ≈ 1 nF a 1.65 V: el Cf mínimo de estabilidad del OPA320 es ≈ 2.7 pF (3.8 pF con los ≈ 2 nF
  de 0 V), y 10 nF deja el lazo sobreamortiguado con pico de ganancia de ruido ≤ 1.2. 4.7 nF también vale (31 Hz);
  22 nF (7 Hz, 99 % en 110 ms) ya muerde la primera muestra.
- **Objetivo de ajuste: ≈ 0.7–0.8 V con LED** (Rf ≈ 0.8 MΩ), no 1 V: deja ×2 para la
  subida por amplificación antes de saturar el OPA320 (1.6 V) y entra en `ads_fsr` 2.048.
- **Vref 1.65 V con buffer, común a todo.** El ruido de la 3.3 V del Pi llega igual al
  TIA y a A3 y se **cancela** en la lectura diferencial. Bajar Vref a 1.0 V daría 2.25 V de
  margen (Rf hasta 1.24 MΩ con ×2), pero obligaría a `ads_fsr` 4.096 (125 µV/LSB) y no
  mejora la resolución en corriente: no compensa.
- **R4 + C4 a la salida.** Segundo polo a 16 Hz y fuente de baja impedancia para el
  muestreador conmutado del ADS1115 (a 64 SPS con 10 kΩ no hay error de carga).
- **Todo a 3.3 V.** Misma referencia que el ADS y el I2C del Pi (§2).

## 5. Números (cálculo del 11/11, Ip = 904 nA)

| Rf | V con LED | % margen | margen amplif. | Johnson | fc (10 nF) | τ | 99 % | pA/LSB (`2.048`) | piso ADS (1–2 LSB) | disparo + Johnson (rms) |
|---|---|---|---|---|---|---|---|---|---|---|
| 0.10 MΩ | 0.09 V | 6 % | ×17.7 | 407 fA/√Hz | 159 Hz | 1 ms | 5 ms | 625 | 0.6–1.3 nA | 11 pA |
| 0.22 MΩ | 0.20 V | 12 % | ×8.0 | 274 fA/√Hz | 72 Hz | 2 ms | 10 ms | 284 | 0.3–0.6 nA | 6 pA |
| 0.50 MΩ | 0.45 V | 28 % | ×3.5 | 182 fA/√Hz | 32 Hz | 5 ms | 23 ms | 125 | 0.13–0.25 nA | 4 pA |
| **0.80 MΩ** | **0.72 V** | **45 %** | **×2.2** | **144 fA/√Hz** | **20 Hz** | **8 ms** | **37 ms** | **78** | **0.08–0.16 nA** | **3 pA** |
| 1.00 MΩ | 0.90 V | 57 % | ×1.8 | 129 fA/√Hz | 16 Hz | 10 ms | 46 ms | 63 | 0.06–0.13 nA | 3 pA |
| 1.10 MΩ | 0.99 V | 62 % | ×1.6 | 123 fA/√Hz | 14.5 Hz | 11 ms | 51 ms | 57 | 0.06–0.11 nA | 3 pA |

Hoy (56.3 kΩ, `0.256`): 139 pA/LSB, piso a oscuras medido 0.53 nA rms, ruido con luz
7.6 nA rms. Con 0.8 MΩ el piso del ADS baja a ≈ 0.1 nA rms (3–6×); el ruido de disparo +
Johnson (3 pA) sigue siendo irrelevante; el ruido con luz (7.6 nA, 0.84 %) **no cambia**
hasta que se trate el LED (§9).

## 6. Montaje y layout

- Nodo sumador (cátodo, pin 4 de U1, R1, Rt, Cf): corto y limpio por costumbre, pero con
  µA de señal no hace falta anillo de guarda ni cuidados de pA. Protoboard vale para la
  prueba; la versión final en placa.
- **Trimmer**: cermet multivuelta si hay (≈ 100 ppm/°C); uno de carbón (≈ 1000 ppm/°C)
  mueve la ganancia 0.1 %/°C: dentro de una corrida es un factor constante (y el baseline
  se resta por ciclo), entre corridas hay que anotar Rt. Una vez fijado el ajuste, medir
  R1 + Rt con el multímetro y apuntarlo (§7) o sustituir por fija.
- Fotodiodo y U1 en la misma placa, dentro del blindaje óptico actual. El cable hasta el
  ADS puede ser largo: Vout es de baja impedancia y R4/C4 van junto al ADS.
- **Condensadores**: todos pueden ser cerámicos monolíticos (MLCC): 104 para C5, C6, C8; 103
  para Cf; 105 para C4; C7 y C10 de 10 µF, o 1 µF (105) si no hay, que para Vref sobra
  (su ruido es modo común y se cancela en la lectura diferencial). En Cf la tolerancia
  (±20 %) y la deriva con tensión y temperatura del dieléctrico solo mueven fc entre ≈ 10 y
  20 Hz, da igual; lo único a cuidar es que no vibre (los X7R/Y5V son piezoeléctricos y en
  el lazo de un TIA una vibración se vuelve corriente): soldado corto, y la lectura ya se
  hace con el motor parado. Si hay para elegir, X7R antes que Y5V/Z5U.
- Lejos del relé del calefactor, del motor y de sus cables
  ([FluorReader README §4](../firmware/FluorReader/README.md) ya registró el ruido del relé
  en el TIA antiguo). GND de la placa a un solo punto.

## 7. Software y conversión a corriente

- **Canales** (cambio del 11/11): `settings.json` → `photoreceptor.ch_p = 2`, `ch_n = 3`,
  `use_diff = 1`, editables en el ConfigFrame. Los tres lectores (PCR, Photoreceptor, Quick
  Control) los toman de `photoreceptor_channels` ([utils.py](../templates/utils.py)) en cada
  lectura: el par se valida contra los que forma el mux y uno imposible cae a 0-1 con aviso.
  Así el TIA viejo (0-1) y el nuevo (2-3) conviven y se comparan cambiando solo el setting;
  por defecto sigue 0-1, nada cambia hasta que se edite.
- `ads_fsr` → **2.048** desde el ConfigFrame (con LED a 0.7–0.8 V y margen ×2). Si se
  prefiere ajustar más bajo (≤ 0.45 V con LED), `1.024`. Ojo: la ganancia del ADS1115 es
  **global** a los cuatro canales; con 2.048 el TIA viejo en 0-1 (50 mV) queda a 800 LSB,
  suficiente para comparar, pero no para medir fino con él.
- **Corriente = voltaje guardado / Rf.** Todo lo guardado hasta el 11/11 (Newn1 a Newn6,
  pruebas de Quick Control) es con **Rf = 56.3 kΩ**: 50 mV ↔ 0.9 µA. Las corridas guardan
  `ads_fsr` en la hoja `settings`, pero no Rf: tras el cambio, apuntar R1 + Rt medido en el
  cuaderno de cada ajuste (o añadir `tia_rf_ohm` a `settings.json` y a la metadata; no
  hecho). Sin ese dato dos corridas con distinto Rt no son comparables en nA.
- Mejora pendiente y barata: descartar la primera muestra ON y la primera OFF al promediar
  (`settle_s` en `pcr_fluorescence`): hoy la primera ON vale 1/3 y entra en la media con un
  sesgo constante de ≈ −3 %. Inocuo mientras no cambie el muestreo.

## 8. Plan de validación (banco)

1. Cablear el TIA nuevo a **A2 (salida) y A3 (Vref_buf)** sin tocar A0/A1, y poner
   `ch_p = 2`, `ch_n = 3` en el ConfigFrame (§7). Con `0`/`1` se sigue leyendo el viejo.
2. **Sin fotodiodo**: A2 − A3 < 0.5 mV (Vos). Con el fotodiodo **tapado**: debería caer muy
   por debajo de los 3.7 nA actuales (la corriente de oscuridad del MTD5052W es de pA). Si
   con el diodo tapado se quedan los ≈ 4 nA × Rf (4 mV a 1 MΩ), es fuga eléctrica de la
   placa, no luz.
3. **LED ON con un disco**, trimmer al mínimo: A2 − A3 ≈ 0.9 µA × 0.1 MΩ ≈ 0.09 V. Si sale
   negativo, girar el fotodiodo. Subir Rt hasta **≈ 0.7–0.8 V**.
4. `ads_fsr` = 2.048. Con la muestra más brillante que se tenga (o el final de una PCR
   positiva): A2 − A3 < 1.5 V. Si no, bajar Rt.
5. **Ruido** en Quick Control (fluorescencia, 100 ms): 60 s a oscuras y 60 s con LED,
   convertido a nA (÷ Rf). Referencia hoy: 0.53 nA rms a oscuras, 7.6 nA rms con luz. Lo
   que debe bajar es el de oscuras (a ≈ 0.1–0.2 nA); si con luz sigue en ≈ 0.8 % → es el LED
   (§9).
6. **Paso del LED**: la primera muestra tras el encendido debe estar ≥ 95 % del valor
   asentado (τ ≤ 10 ms). Si no, revisar Cf y C4.
7. Una corrida PCR completa: `photodetector_raw` con los mismos cortes que §1, y anotar
   R1 + Rt en la bitácora de la corrida.

## 9. Lo que este circuito no arregla (y la variante de baja corriente)

- **Ruido y deriva con luz** (0.84 % y −2 % en 2 s). Hoy el LED de 470 nm se enciende con
  GPIO 24 → MOSFET como interruptor, y su corriente la fija lo que haya en serie (una
  resistencia) contra el riel que lo alimenta ("la fuente": 5 V del Pi, el riel del motor,
  una fuente aparte... no está documentado). Con resistencia en serie I = (Vriel − Vf)/R: la
  Vf de un LED azul baja ≈ 3–4 mV/°C al calentarse (la corriente sube mientras el brillo por
  mA baja) y cualquier rizado del riel (motor, relé) entra directo en el brillo. Un **driver
  de corriente constante** fija I sin importar riel ni temperatura: por ejemplo un MCP6001
  de los disponibles + MOSFET canal N + resistencia de sensado Rs a GND; el op-amp compara
  la caída en Rs con una referencia que sale del propio GPIO 24 por un divisor (3.3 V →
  Vset), I_LED = Vset / Rs (0.33 V y 16.5 Ω → 20 mA); GPIO en 0 → 0 mA, así que el encendido
  sigue siendo el mismo pin. Es independiente del TIA: primero validar el TIA (§8) y, solo
  si el ruido relativo con luz sigue en ≈ 0.8 %, hacer esto. Antes, anotar qué riel alimenta
  hoy el LED y cuánta corriente lleva.
- **Dispersión ciclo a ciclo** (3 %): posición del disco / óptica.
- **Fondo**: los 0.9 µA con LED son ≈ 3 µW de luz sobre el chip (0.3 A/W) que **pasan el
  filtro de emisión** que ya hay delante del fotodiodo, y el nivel es el mismo en corridas
  con y sin amplificación visible: es fondo, no señal. El MTD5052W responde de 410 a 580 nm,
  así que sin filtro vería el LED de 470 nm de frente; con filtro, lo que llega depende de
  su OD a 470 nm y del ángulo de incidencia (un filtro de interferencia corre su banda hacia
  el azul y pierde bloqueo fuera del eje). Candidatos, por orden: fuga del filtro a 470 nm;
  cola larga del espectro del LED (un LED de 470 nm emite algo a 500–550 nm, dentro de la
  banda de emisión: un filtro de **excitación** sobre el LED la corta); autofluorescencia
  del plástico del disco y del propio filtro; la muestra. Se separan en banco con el Quick
  Control y el LED ON: (1) sin disco, (2) disco vacío, (3) buffer sin colorante, (4) con
  colorante; cada escalón dice cuánto aporta. La amplificación se verá como un cambio
  encima del fondo que quede.
- **Si un mejor filtrado (filtro de excitación en el LED, o uno de emisión con más OD) baja
  la corriente a decenas de nA**, este diseño se
  queda corto (0.9 V a 1.1 MΩ con 0.9 µA son 16 mV con 15 nA). Entonces vale la variante
  de dos etapas: TIA con Rf 10 MΩ fija y Cf 1 nF (16 Hz; 1 GΩ de fuga ya son 1.6 nA, hay
  que cuidar el nodo) + etapa no inversora con MCP6001 referida a Vref_buf,
  G = 1 + Rt/100 kΩ (1 a 11), mismo buffer y mismo RC de salida. A 17 nA da 0.17 V en la
  primera etapa y ≈ 1 V con G = 6.

## 10. Pendiente de verificar

- [x] Fotodiodo **MTD5052W** con ánodo a GND; todas las medidas de este doc son con esa misma
      placa (confirmado el 11/11, §1 y §3).
- [ ] Por qué las pruebas del 09–10/11 dieron 18–340 nA frente a los 904 nA de las corridas
      PCR con la misma electrónica: anotar muestra, disco y posición del LED en la próxima.
- [ ] Construir y pasar el plan de §8; registrar R1 + Rt y `ads_fsr` finales aquí.
- [ ] Qué riel alimenta el LED y con qué corriente; driver de corriente constante solo si el
      ruido con luz no baja tras el TIA (§9).
- [ ] Filtro de emisión delante del fotodiodo: modelo, banda y OD a 470 nm; y la prueba de
      fondo por partes (§9).

---

__author__ = "Edisson A. Naula"
__date__ = "$ 11/11/2026 $"
