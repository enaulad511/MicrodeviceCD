# EmStat — Retención de datos entre corridas ("Keep runs")

Checkbox en el plotter (`EventPlotter`) que permite **apilar varias corridas en la misma
gráfica** para compararlas, sin tener que guardar a CSV y recargar. Estado: **implementado
en host**; pendiente smoke test en hardware (ver §6).

Toda la lógica vive en [ui/EventEmstatFrame.py](../ui/EventEmstatFrame.py); no toca firmware
ni el parser. Lectura relacionada: [emstat_udp_recovery.md](emstat_udp_recovery.md) (de ahí
viene el merge por `seq` y `_reconcile_merge`).

---

## 1. El problema

CV emite un marcador de ciclo (`C<hex>`) por scan, así que una corrida con N scans ya pinta
N líneas superpuestas en la **misma** corrida — comparar ciclos es gratis. Pero SWV y EIS
emiten **un solo ciclo** (`cycle=0`), así que cada experimento es una sola traza. Para
comparar dos SWV había que **Save + Load**.

Peor: con el merge TCP+UDP, `_reconcile_merge()` al cerrar hacía `self.x_by_m.clear()` y
reconstruía **solo la corrida actual**, así que incluso corridas consecutivas quedaban
reducidas a la última. Por eso SWV "solo mostraba un experimento".

## 2. La idea

Un checkbox **"Keep runs"** en la barra de controles de `EventPlotter`. Como el widget es
compartido, aparece en las tres pestañas (CV, SWV, EIS), cada una con su estado independiente.

- **Apagado (default):** comportamiento de siempre — cada Start limpia la corrida anterior.
- **Encendido:** cada Start **apila** la nueva corrida como traza(s) separada(s).

Por defecto **apagado** (sin sorpresas) y **deshabilitado mientras corre** (como
`cmb_transport`); solo se lee en `start()`.

## 3. El mecanismo: offset de clave por corrida

Las líneas se indexan por `m = cycle`. Como SWV siempre manda `cycle=0`, dos corridas
colisionarían en la misma línea. La solución es **desplazar** la clave de cada corrida antes
de usarla como índice de plot, dejando el `cycle` crudo del evento intacto.

- `self.plot_run_offset` — desplazamiento de la corrida actual.
- `self.run_index` — índice de corrida (1, 2, 3…), para etiqueta y columna CSV.
- `self.key_meta` — `clave_de_línea -> (run, cycle)`, para etiquetas adaptativas.

En `start()` ([EventEmstatFrame.py](../ui/EventEmstatFrame.py), bloque "Retención entre
corridas"):

```
keep OFF  -> _reset_live_plot(); offset = 0          # limpia (conserva loaded CSV)
keep ON   -> offset = max(lines_by_m) + 1            # apila, no limpia
run_index += 1
_run_td_start = len(total_data)                       # dónde empieza esta corrida en Save
```

Resultado:

| Método | Run 1 (claves) | Run 2 (claves) |
|---|---|---|
| SWV/EIS (1 ciclo) | `0` | `1` |
| CV (4 scans) | `0..3` | `4..7` |

El offset se aplica **solo al índice de plot**, en los tres puntos donde el ciclo se vuelve
clave: la ruta en vivo (`_handle_emstat_msg` → `q_points`), `_update_plot` y
`_reconcile_merge`. El `event["cycle"]` nunca se muta.

## 4. Reset acotado y `_reconcile_merge`

- **`_reset_live_plot()` (nuevo):** limpia **solo** los datos en vivo (`lines_by_m`,
  `x_by_m`, `y_by_m`, `key_meta`, `total_data`, `merged_by_seq`, `q_points`) y **conserva las
  líneas cargadas de CSV** (`loaded_lines`) — son referencias que el usuario trajo a propósito.
  El botón 🗑 Clean sigue siendo el wipe total.
- **`_reconcile_merge` acotado:** ahora limpia/reconstruye **solo las claves de la corrida
  actual** (`>= offset`); las corridas anteriores quedan intactas en el gráfico. Y reemplaza
  **solo la porción de esta corrida** en `total_data` (`self.total_data[self._run_td_start:] =
  ordered`) en vez de todo el dataset, así Save conserva las corridas previas.

### Transición OFF → ON (aditiva)

Como el reset ocurre en el **siguiente** Start (no al detener), la última corrida queda en
pantalla. Si el usuario marca el checkbox y pulsa Start, la nueva corrida se **apila sobre lo
que ya esté graficado** (offset = clave máxima + 1, sin limpiar). "Keep" incluye lo que ya
está ahí; 🗑 Clean es la pizarra en blanco si la quieren.

## 5. Etiquetas, Save y Load

- **Leyenda adaptativa** (calculada al render en `_update_legends`): se cuentan los ciclos
  por corrida entre las líneas actuales. Si la corrida aporta **un** ciclo → `R{run}`
  (SWV/EIS: `R1`, `R2`, `R3`); si aporta **varios** → `R{run}c{cycle}` (CV: `R1c0…R1c3`,
  `R2c0…`). La ruta de renombrado/leyenda custom (`legends_list`) sigue intacta.
- **Save:** el CSV gana una columna `run` al final → `sample, <x>, <y>, cycle, run`. Cada
  evento se etiqueta con su `run`.
- **Load:** agrupa por **(run, cycle)** y dibuja una línea por par (etiqueta
  `…-r{run}c{cycle}`). La columna `run` es **opcional**: si falta (CSV viejo de 4 columnas)
  se asume `run=0` — retrocompatible.

## 6. A verificar en hardware

- [ ] Dos SWV con "Keep runs" **marcado** dejan dos trazas distintas (`R1`, `R2`).
- [ ] Sin marcar, sigue mostrando **solo la última** corrida (comportamiento previo).
- [ ] OFF → marcar → Start apila sobre la corrida ya en pantalla (no la borra).
- [ ] Save de un dataset multi-corrida y Load lo recarga como las mismas trazas separadas.
- [ ] Load de un CSV viejo (sin columna `run`) sigue funcionando (`run=0`).
- [ ] CV con varios scans: las etiquetas salen `R1c0…`, `R2c0…` y los ciclos intra-corrida
      se conservan como hoy.

---

__author__ = "Edisson A. Naula"
