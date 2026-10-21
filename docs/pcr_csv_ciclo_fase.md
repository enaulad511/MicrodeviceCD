# Ciclo y fase por muestra en el CSV de temperatura (PCR)

Archivo modificado: `ui/PcrFrame.py`

Cada muestra del `*_temperature_data_*.csv` lleva ahora **en qué ciclo y en qué fase**
del programa térmico estaba el experimento cuando llegó. Antes el CSV solo traía
`[primario, secundario, t_s]`, y ubicar un tramo (p. ej. "el hold de high del ciclo 7")
obligaba a reconstruirlo a ojo desde la curva, que es lo que hace hoy la selección de
segmentos a dos clics de la pestaña de análisis. Con las dos columnas nuevas la
estadística por ciclo o por fase es un `groupby` directo, sin reconstruir nada.

## 1. Formato

Dos columnas **al final** de cada fila:

| col | nombre | contenido |
|:---:|--------|-----------|
| 0 | primario | temperatura del sensor que regula el PID |
| 1 | secundario | el otro sensor del par |
| 2 | `t_s` | tiempo real desde el inicio de la corrida ([pcr_eje_tiempo.md](pcr_eje_tiempo.md)) |
| 3 | `cycle` | **nuevo** — ciclo en curso (ver §2) |
| 4 | `phase` | **nuevo** — código de la fase en curso (ver §3) |
| 5 | `heater_on_s` | segundos de heater encendido acumulados (desde el 21/10/2026, ver §6) |

La fila 0 (metadata) declara `cols: <pri>|<sec>|t_s|cycle|phase|heater_on_s` (antes del
21/10/2026, sin `heater_on_s`).

Ir **al final** es lo que hace el cambio retrocompatible: el loader del análisis
(`_read_temp_csv` en [ui/analysis/pcr.py](../ui/analysis/pcr.py)) lee las columnas 0–2
por posición e ignora las demás, y no parsea la fila de metadata. Los CSV viejos (sin
estas columnas) siguen cargando igual. Ningún notebook lee estos archivos.

## 2. `cycle`: 1..N dentro del ciclado, 0 fuera

- **`1..N`** mientras corre el ciclo *k*: se fija al **inicio** de `_run_cycle`
  ([PcrFrame.py:1773](../ui/PcrFrame.py#L1773)), así que incluye la rampa a high, el
  enfriamiento, los holds y la lectura de fluorescencia de ese ciclo. Es 1-based a
  propósito: coincide con la columna `cycle` de `*_photodetector_raw_*.csv` y con la
  fila *k* de `*_photodetector_data_*.csv` (lectura del fin del ciclo *k*), así que
  temperatura y fluorescencia se cruzan por el mismo número.
- **`0`** fuera del ciclado, **antes** (`initial`, `denat_*`) **y después**
  (`final_ext`, `final_read`) — el reset está en
  [PcrFrame.py:2072](../ui/PcrFrame.py#L2072). La fase distingue cuál de los dos.

Se eligió `0` en lugar de etiquetar el cierre como ciclo `N` o `N+1` porque ambos son
trampas para la estadística: con `N`, la extensión final (puede durar minutos) inflaría
la duración y la media del último ciclo; con `N+1`, un `groupby("cycle")` mostraría un
ciclo que nunca existió. Con `0`, **`cycle > 0` son exactamente las muestras del
ciclado** y `cycle` sigue siendo entero (sin celdas vacías que pandas convierta a float).

Si se detiene la corrida a mitad de un ciclo, `cycle` queda en ese ciclo hasta el final:
es correcto, son muestras de un ciclo incompleto.

## 3. `phase`: código estable

`PCR_PHASE_LABELS` ([PcrFrame.py:97](../ui/PcrFrame.py#L97)) mapea **código → etiqueta**
del label de estado. Toda transición pasa por `_enter_phase(code)`
([PcrFrame.py:1099](../ui/PcrFrame.py#L1099)), que fija ambos a la vez, así que lo que
dice la pantalla y lo que queda en el CSV no pueden divergir.

| código | cuándo | `cycle` |
|--------|--------|:------:|
| `initial` | start-gate, spin inicial, armado de GPIO | 0 |
| `denat_ramp` / `denat_hold` | rampa y hold de desnaturalización | 0 |
| `high_ramp` / `high_hold` | rampa (FF + PI) y hold a high | k |
| `cooling` | enfriamiento con giro del motor | k |
| `low_hold` | hold a low (sin rampa: se llega enfriando) | k |
| `ext_ramp` / `ext_hold` | rampa PI y hold a la extensión | k |
| `fluor_read` | espera previa + lectura de fluorescencia del ciclo | k |
| `final_ext` | hold de la extensión final | 0 |
| `final_read` | espera previa + lectura de fluorescencia final | 0 |
| `done` | terminó (no suele llevar muestras: el cliente UDP se detiene) | 0 |
| `aborted_start` | ningún sensor dio lectura válida al inicio | 0 |
| `aborted_sensors` | watchdog "ambas caídas" ([temp_source_selector.md](temp_source_selector.md)) | el del momento |
| `aborted_timeouts` | racha de ciclos con fases abandonadas ([pcr_timeout_fases.md](pcr_timeout_fases.md)) | el último ciclo |

Una rampa abandonada por la salvaguarda de tiempo **no** tiene código propio: se ve como
un `*_ramp` que termina sin llegar al setpoint y da paso a su `*_hold`. El detalle (ciclo,
fase, duración/límite) va en la metadata y en la columna `timeouts` del CSV de
fotodetector ([pcr_timeout_fases.md](pcr_timeout_fases.md) §5).

El **código** es la llave de los datos: no se renombra. La **etiqueta** es solo pantalla
y se puede retocar libremente.

Una fase omitida (tiempo ≤ 0, ver
[pcr_temperature_control.md](pcr_temperature_control.md)) simplemente no aparece; y si
el enfriamiento no hace falta (ya se está bajo el objetivo) tampoco hay `cooling`.

### La espera previa a la lectura ya no es hold

`fluor_read` y `final_read` se declaran **antes** de los `pcr_fluorescence.pre_sleep_s`
(0.5 s por defecto, [cambios_fluorescencia.md](cambios_fluorescencia.md) §3) de espera, no después ([PcrFrame.py:1865](../ui/PcrFrame.py#L1865),
[PcrFrame.py:2082](../ui/PcrFrame.py#L2082)). En esa espera el lazo del hold ya terminó y
la temperatura deriva; etiquetarla `ext_hold` ensuciaría justo la estadística del hold
que estas columnas buscan habilitar. Efecto visible: el label de estado dice
"Reading Fluorescence" 0.5 s antes. La lectura final tiene ahora su propia etiqueta
("Reading final fluorescence"); antes la pantalla seguía en "Extension".

## 4. Cómo se etiqueta cada muestra

El hilo del experimento declara la fase (`_enter_phase`) y el ciclo (`cycle_current`);
`update_displayed_temperature`, en el hilo del cliente UDP, los lee **al anexar** cada
muestra ([PcrFrame.py:1096](../ui/PcrFrame.py#L1096)) en lockstep con las otras tres
listas. Son asignaciones/lecturas de atributo simples, atómicas bajo el GIL; no hace
falta lock. La muestra lleva la fase vigente **al recibir el datagrama**: en un cambio de
fase, a lo más el datagrama que ya estaba en vuelo queda con la fase anterior (≤ una
muestra, ~80 ms).

Ambas se reinician por corrida en `init_temperature_graph`
([PcrFrame.py:1253](../ui/PcrFrame.py#L1253)), junto al resto del estado de captura.

## 5. Lo que NO se hizo

- **La pestaña de análisis no usa todavía las columnas.** Sigue con la selección manual
  de segmentos. Es el siguiente paso natural (segmentar holds/rampas por `phase` y
  agrupar por `cycle` automáticamente), pero cambia el flujo de esa pestaña y se deja
  para cuando se decida cómo convivir con la selección manual.
- **No se añadió `cycle` al CSV de fotodetector por ciclo:** el número de fila ya lo es.
  Sí ganó una columna `timeouts` por ciclo con la salvaguarda de fases
  ([pcr_timeout_fases.md](pcr_timeout_fases.md)).

## 6. `heater_on_s`: lo que de verdad calentó el heater (21/10/2026)

Hasta aquí el CSV solo traía temperatura: para afinar ganancias había que **deducir**
qué hizo el PI a partir de la curva. La columna 5 graba, por muestra, los **segundos
acumulados de heater encendido** desde que se armó el pin en esa corrida, evaluados en el
instante de recepción (`t_s`). El duty de cualquier ventana sale directo:

```
duty[a..b] = (heater_on_s[b] − heater_on_s[a]) / (t_s[b] − t_s[a])
```

**Por qué acumulado y no un 0/1 por muestra:** las muestras llegan en ráfagas (~80 ms de
media, huecos de ~0.27 s) y el PWM del PI dura `win_*` = 20–90 ms. Un 0/1 muestreado así
es alias puro; tampoco sirve grabar la potencia que pidió el PI, porque no incluye los
cortes. El acumulado es exacto con cualquier ventana y deja elegir el suavizado al
analizar.

**Qué incluye:** todo lo que pasa por el pin. El pin del heater es un `_HeaterMeter`
([PcrFrame.py](../ui/PcrFrame.py), clase `_HeaterMeter`) que envuelve el `GPIOPin` y
contabiliza cada `write`: blast de feed-forward (duty 1), PWM de rampas y holds,
**cortes por lectura vieja** (duty 0 aunque el PI pidiera más; fue el problema de Newn1,
[pendientes](pcr_pendientes.md) punto 1) y el apagado del teardown. Si una escritura del
pin falla, no se contabiliza.

- **Antes de armar el pin** (`initial`: start-gate y spin inicial) vale `0`. **Tras el
  teardown** se congela en el último valor: el heater está apagado.
- Es **monótono**: el tiempo de cada transición se toma dentro del lock que comparten el
  hilo del experimento (escribe) y el hilo UDP (lee), así que un Δ nunca es negativo.
- **Invariante:** toda escritura del heater va por `self.pin_heating` (el medidor).
  Escribir un `GPIOPin` crudo encendería el heater sin que la columna lo vea.

Verificado en simulación (pin falso, PWM 30 % + blast + corte, lector en ráfagas):
0.96 s contados contra 0.95 s ideales, sin retrocesos. Pendiente de validar en el
equipo con la primera corrida que lo traiga.

## Archivos

- [ui/PcrFrame.py](../ui/PcrFrame.py) — `PCR_PHASE_LABELS`, `_enter_phase`,
  `cycle_current`/`phase_code`, `data_cycle`/`data_phase`, `_HeaterMeter`/`data_heater_on`,
  columnas 3–5 de `save_data_temps_file`, `cols:` de la metadata.
- Docs relacionados: [pcr_eje_tiempo.md](pcr_eje_tiempo.md) §6 (columna `t_s` y
  metadata), [pcr_analisis.md](pcr_analisis.md) (loader),
  [pcr_temperature_control.md](pcr_temperature_control.md) (fases omitidas).

__author__ = "Edisson A. Naula"
__date__ = "$ 13/10/2026 $"
