# FluorReader — lectura de fluorescencia bajo demanda (Arduino MKR Zero)

Sketch de **banco de pruebas**: mide fluorescencia **solo cuando se le pide** (`f`) y publica el
resultado por Serial **y en una LCD 16x4**. Deriva de
[../OldDevice/OldDevice.ino](../OldDevice/OldDevice.ino) y conserva su enfoque de medición **sin
cambios**: integración ON–OFF con chopping + resta del blanco. Ver
[../OldDevice/README.md](../OldDevice/README.md) para el detalle del método, las escalas
(0.27 nA/LSB, fondo de escala ~1.1 µA) y las limitaciones heredadas.

- **Placa:** Arduino MKR Zero (SAMD21, 3.3 V, ADC 12 bits) — la misma del equipo antiguo.
- **Archivo:** [FluorReader.ino](FluorReader.ino)
- **Autor:** Edisson Naula

> ⚠️ **Standalone**: no se integra con la app Python de este repo. No habla UDP ni el protocolo
> `EMSTAT:`/`UDP:`; toda la interacción es por el Serial USB.

---

## 1. Qué cambia respecto a `OldDevice.ino`

| | OldDevice | FluorReader |
|---|---|---|
| Medición | Bucle continuo `r` hasta pulsar tecla | **Una medida por comando `f`** |
| Sin blanco capturado | Mide y resta 0 **sin avisar** | **Rechaza** `f` y pide capturar blanco |
| Comandos | `b`, `r`/`R`, `c`, `s` | `f`/`F`, `b`, `c`, `s` (se elimina `r`) |
| Estado del blanco | Solo el valor | Valor **+ bandera** `baseline_ready` |
| `s` | `RF`, `SETTLE_US`, `BL` | Añade `CYCLES` y `(ready)`/`(not captured)` |
| Salida | Solo Serial | Serial **+ LCD 16x4** (§3) |

Todo lo demás es idéntico y **deliberadamente**: mismas constantes, misma cadena
counts → V → nA, misma línea de salida en Serial.

## 2. Comandos

| Comando | Efecto | LCD |
|---|---|---|
| `f` / `F` | Una medida (256 ciclos) y la imprime. Si no hay blanco: `No baseline. Capture it first with 'b'.` | `Measuring...` → resultado en 3 líneas (o `Need blank (b)`) |
| `b` | Captura el blanco (512 ciclos) con el **blanco puesto**; activa `baseline_ready` | `Blank...` → `BL 1234.56 ct` (limpia el detalle) |
| `c` | Borra el blanco y baja `baseline_ready` | `Blank cleared` (limpia el detalle) |
| `s` | `RF`, `SETTLE_US`, `CYCLES`, blanco vigente y si está capturado | *(no toca la LCD: es para el monitor)* |

Salida de `f` — **idéntica** a la del sketch antiguo, para poder contrastar medidas históricas:

```
Δcounts(256) = 1234.56   ΔV = 0.99512 V   ΔI = 331.71 nA
```

El campo `Δcounts` es el **neto** (blanco ya restado).

## 3. LCD

Reparto de las cuatro líneas (16x4):

```
línea 0:  I= 331.71 nA        <- resultado principal, o estado del proceso
línea 1:  N= 1234.56 ct       <- neto en counts
línea 2:  V= 0.99512 V        <- tensión a la salida del TIA
línea 3:  Blank: OK           <- Blank: OK | Blank: NONE
```

Las líneas 1 y 2 son el detalle que en 16x2 no cabía: las tres magnitudes que el Serial siempre
imprimió, ahora también en pantalla. La **última** línea lleva el estado del blanco porque el
bloqueo de `f` sin blanco (§4) es invisible de otro modo: dice de un vistazo por qué la placa se
niega a medir, sin ir al monitor serie.

El layout **se adapta solo**: con `LCD_ROWS 2` desaparecen las líneas de detalle y el estado
vuelve a la línea 1 (`LCD_ROW_STATUS = LCD_ROWS - 1`). Al capturar o borrar el blanco, las líneas
de detalle se limpian (`lcdClearDetail`) para no dejar la medida anterior junto a un estado nuevo.

### Configuración (cabecera del `.ino`)

```cpp
#define LCD_I2C   1     // 1 = backpack I2C (PCF8574); 0 = HD44780 en paralelo
#define LCD_ADDR  0x27  // 0x27 o 0x3F según el backpack
#define LCD_COLS  16
#define LCD_ROWS  4     // 4 = 16x4; 2 = 16x2
```

### ⚠️ El 16x4 por I2C necesita un parche de direcciones

`LiquidCrystal_I2C` (el fork de F. de Brabander, que es el que instala
`arduino-cli lib install "LiquidCrystal I2C"`) trae las direcciones de fila **fijas a un módulo de
20 columnas**:

```cpp
int row_offsets[] = { 0x00, 0x40, 0x14, 0x54 };   // 0x14 = 20, 0x54 = 0x40+20
```

En un **16x4** las filas 3 y 4 empiezan en `0x10` y `0x50`, no en `0x14`/`0x54`: sin corregir,
esas dos líneas salen **corridas 4 caracteres**. `lcdSetCursor()` lo arregla restando 4 a la
columna en las filas ≥2 (la suma la hace la propia librería), activado por
`#define LCD_I2C_ROW_FIX`, que se enciende solo cuando I2C + 16 columnas + 4 filas.

| Síntoma | Causa | Remedio |
|---|---|---|
| Líneas 3-4 indentadas 4 caracteres | El parche no está activo | `LCD_I2C_ROW_FIX 1` |
| Líneas 3-4 **encimadas** sobre las 1-2 | Tu fork ya calculaba bien y el parche sobra | `LCD_I2C_ROW_FIX 0` |
| Líneas 3-4 en blanco o basura | No es 16x4 (¿20x4?) | Ajusta `LCD_COLS`/`LCD_ROWS` |

La versión **paralela** (`LiquidCrystal` del core) no necesita nada: calcula los offsets desde
`cols` en `begin()`. Y si nada cuadra, `LCD_ROWS 2` degrada a las dos primeras líneas, que
direccionan bien siempre.

`LiquidCrystal` (paralela) y `LiquidCrystal_I2C` (backpack) comparten la API de impresión
(`setCursor`/`print`), así que la capa de pantalla está escrita **una sola vez** y el
`#define LCD_I2C` elige el constructor. En paralelo los pines por defecto son RS/E/D4-D7 =
`3,4,5,6,7,8` — **D2 queda libre a propósito**, es el gate del LED.

### Cableado I2C

SDA/SCL de la MKR Zero = **D11/D12**. ⚠️ **Aviso de niveles**: si alimentas el backpack a 5 V, sus
pull-ups suben SDA/SCL a 5 V y la **SAMD21 no es tolerante a 5 V**. Aliméntalo a 3.3 V (algunos
módulos pierden contraste; se compensa con el potenciómetro) o intercala un traductor de niveles.

### Detalles de implementación

- **`lcdLine()` rellena con espacios** hasta el final de la línea. La HD44780 no borra sola: sin el
  padding, `Blank: OK` escrito encima de `Blank: NONE` dejaría `Blank: OKNE`.
- **Ninguna escritura a la LCD ocurre dentro de `measureDeltaCounts`.** Una transacción I2C cuesta
  ~1-2 ms y el chopping ON–OFF vive de un temporizado de 320 µs por estado: meter la pantalla en
  el bucle falsearía la medida.
- **Los números se imprimen con `Print::print(float, 2)`**, no con `sprintf("%f")`: el soporte de
  float en `printf` no es fiable entre cores.
- **La `Δ` no va a la LCD** (no está en el juego de caracteres de la HD44780); se queda en Serial.
- La LCD se inicializa **antes** del `while(!Serial)`, así muestra estado mientras esperas a abrir
  el monitor.

## 4. Decisiones tomadas (y por qué)

- **`CYCLES_MEASURE` se queda en 256**, aunque al disparar a mano ya no hay presión de refresco
  y subir a 512 bajaría el ruido ~√2. Se prioriza que los números salgan **directamente
  comparables** con los del equipo antiguo. Cada `f` tarda ≳164 ms (solo los `delayMicroseconds`,
  sin contar el ADC).
- **`f` exige blanco.** Era el fallo silencioso más caro del antiguo: tras un reset el blanco
  vale 0 y la lectura sale con la fuga óptica del LED dentro, con la misma pinta que una buena.
  Bloquear es preferible a marcar la línea porque en banco de pruebas el dato se apunta sin mirar.
- **Bandera `baseline_ready` aparte del valor**: un blanco legítimo puede dar 0.0 o negativo, así
  que `baseline_counts != 0` no sirve como test de "hay blanco".
- **Feedback de proceso en `f` y en `b`** (`Measuring...` / `Blank...`): con la LCD como salida
  principal, un `f` que devuelve un valor parecido al anterior es indistinguible de "no registró
  la tecla".
- **Sin detección de saturación** (fidelidad al antiguo). Sigue vigente el riesgo: con `RF` fijo
  de 3 MΩ, si el ADC pega en 4095 o en 0 la medida sale subestimada y nada lo delata.
- **Se conserva `while(!Serial)`**: los comandos siguen llegando por teclado, así que un host USB
  es requisito de todas formas. La LCD es salida cómoda, **no** convierte al equipo en autónomo;
  eso exigiría quitar el bloqueo y cablear un pulsador para disparar `f`.
- **Blanco en RAM** (no se persiste en flash): un reset lo borra, pero ahora `f` avisa en vez de
  medir mal, que era el problema real.

## 5. Build & Upload

```powershell
arduino-cli core install arduino:samd
arduino-cli lib install "LiquidCrystal I2C"    # solo si LCD_I2C = 1
arduino-cli compile --fqbn arduino:samd:mkrzero firmware/FluorReader
arduino-cli upload  --fqbn arduino:samd:mkrzero --port <COMx> firmware/FluorReader
```

Con `LCD_I2C 0` no hace falta instalar nada: `LiquidCrystal` viene con el core. Monitor serie a
**115200**. Hardware de medida igual que el antiguo: gate del MOSFET de los LED de 470 nm en
**D2**, salida del TIA en **A0**.

## 6. Pendiente de verificar

- [ ] No se ha compilado ni flasheado: falta `arduino-cli compile` y un ciclo real
      (`b` con blanco → `f` con muestra).
- [ ] **Modelo de LCD sin confirmar**: se asumió **16x4** con backpack I2C en `0x27`. Si no
      enciende, prueba `0x3F`; si no responde nada al bus, es paralela → `#define LCD_I2C 0`.
- [ ] **Confirmar que son 16 columnas y no 20**: el 20x4 es mucho más común que el 16x4. Cuenta
      los caracteres de una línea llena; si son 20, pon `LCD_COLS 20` y el parche de filas se
      desactiva solo (con 20 columnas los offsets de la librería ya son los correctos).
- [ ] **Fork de la librería**: se usa `lcd.init()` (fork de johnrickman). Otros forks exponen
      `lcd.begin()` — si no compila, es esa línea de `setup()`.
- [ ] Confirmar que la `Δ` (UTF-8) se sigue viendo bien en tu monitor serie, igual que en el antiguo.

---

__author__ = "Edisson A. Naula"
__date__ = "$ 04/08/2026 $"
