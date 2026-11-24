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
_Evitar_: segmento (reservado a los tramos de tasa de una corrida PCR), región, rango de tiempo

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

### Electroquímica

**Corrida (electroquímica)**:
Un barrido completo de corriente contra potencial de un método (CV, SWV…). "Keep runs" apila varias corridas en un mismo archivo.
_Evitar_: medición

**Experimento** (CV, SWV):
Una serie de corridas con distintas concentraciones o ajustes (settings) con la que se caracteriza un electrodo. Puede abarcar varios archivos, y un archivo puede traer solo parte de la serie.

**Pico** (SWV):
Un máximo de corriente en una corrida, o un hombro con cambio de pendiente, con su potencial de pico y su corriente.
_Evitar_: mínimo (en SWV no se calculan)

**Semi-ventana del pico** (en la UI: *Peak window*):
El semiancho de potencial, en mV, que se espera de un pico: dos máximos más cerca que esto
cuentan como uno solo. No es una Ventana en el sentido de arriba (esa es un intervalo de tiempo).
_Evitar_: ventana (sin más), ancho del pico

**Altura del pico**:
La corriente del pico sobre la recta de base local; distinta de la corriente absoluta en el pico.
_Evitar_: amplitud

**Rango de potencial**:
El intervalo [E_min, E_max] del barrido dentro del cual se muestra la corrida y se calculan los picos.
Es el último **aplicado** (Apply); lo escrito en los campos sin aplicar no cuenta.
_Evitar_: ventana (reservada a un intervalo de tiempo), región, rango vigente
