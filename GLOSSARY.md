# Glosario — CD microdevice

Vocabulario del dominio del instrumento (PCR en disco + electroquímica). Fija qué palabra
usar para cada concepto; el diseño y el porqué viven en `docs/`.

## Lenguaje

### Lecturas manuales (Quick Control)

**Corrida (Quick Control)**:
Una lectura continua, de Start a Stop, de una sola señal: temperatura o fotodetector.
"Keep data" apila varias corridas de la misma señal en un mismo archivo.
_Evitar_: medición, sesión

**Canal**:
Cada serie que produce una corrida a la vez: un sensor de temperatura (IR ambiente, IR
objeto, termopar) o el voltaje del fotodetector. En "All (3 temps)" una corrida tiene tres.

**Traza**:
Un canal de una corrida concreta (archivo × corrida × canal); la unidad que se grafica y
se analiza.
_Evitar_: curva, serie

**Ventana**:
Un intervalo de tiempo [t_a, t_b] dentro de una corrida, con una etiqueta, sobre el que se
calculan estadísticas de cada canal de esa corrida.
_Evitar_: segmento (reservado a los tramos de tasa de una corrida PCR), región, rango

**Evento de actuador**:
Un cambio de estado del LED de fluorescencia, del LED de calentamiento o del motor durante
una corrida, con el instante en que ocurrió.

### Óptica

**Señal del fotodetector** (en la UI: *Photodetector*):
El voltaje a la salida del TIA del fotodiodo, tal como lo lee el ADS. Incluye el fondo del
LED que atraviesa el filtro de emisión.
_Evitar_: fluorescencia, intensidad (para la lectura cruda)

**Fluorescencia**:
La emisión de la muestra: la parte de la señal del fotodetector que no es fondo.
_Evitar_: usarla como nombre de la lectura cruda del fotodetector
