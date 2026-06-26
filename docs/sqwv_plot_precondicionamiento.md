# SWV — Pre-tratamiento fuera del plot (conservado en el CSV)

En SWV el pre-tratamiento (condition + deposition + equilibration) **emite datos** (cada fase es
un `meas_loop_ca` con `pck_add e`/`pck_add i`), pero esos puntos no son parte del voltamograma:
aparecen como clusters a potencial constante (E_con, E_dep, E_begin) que ensucian el plot E vs I.
Esta feature los **oculta de la gráfica** pero los **conserva en el CSV** (diagnóstico).

Es host-only: el firmware y el EmStat no cambian. Comparte el tag de fase con
[sqwv_motor_pretratamiento.md](sqwv_motor_pretratamiento.md) (red de seguridad del motor).

---

## 1. Discriminador: presencia de `i_forward`/`i_reverse`

El barrido SWV (`meas_loop_swv`) emite SIEMPRE `i_forward`/`i_reverse` (`ba_1`/`ba_2` →
`I_A_F`/`I_A_R`); los `meas_loop_ca` del pre-tratamiento solo emiten `e`/`i`. Por eso el
discriminador es **por presencia de campo**, sin contar marcadores (inmune a un `*` perdido en
TCP), igual que EIS descarta sus paquetes de acondicionamiento por ausencia de `Z_real`/`Z_imag`
([Drivers/EmstatUtils.py](../Drivers/EmstatUtils.py) `_handle_packet`).

A diferencia de EIS/CA (que marcan el acondicionamiento como `type="unknown"` y lo **descartan**),
aquí el paquete sigue siendo `type="data"` y solo se **etiqueta**:

```python
if self.experiment == "sqwv":
    is_sweep = "I_A_F" in decoded or "I_A_R" in decoded
    decoded["phase"] = "sweep" if is_sweep else "pretreatment"
```

> El tag no separa condition/deposition/equilibration entre sí (todas son CA e/i); las agrupa como
> `"pretreatment"`. Distinguirlas requeriría contar marcadores `*`, más frágil y sin valor aquí.

## 2. El host: conserva en `total_data`, no grafica

En `EventPlotter._handle_emstat_msg` (y en `_reconcile_merge` al cerrar) el evento de datos
**siempre** se añade a `total_data` (para Save), pero solo se manda a la gráfica si
`phase != "pretreatment"`:

```python
self.total_data.append(event)            # CSV: conserva TODO
if event.get("phase") != "pretreatment":  # plot: solo el barrido
    ... key_meta / q_points ...
```

Experimentos sin tag de fase (CV, EIS, CA) tienen `phase = None`, que pasa el filtro
(`None != "pretreatment"`) → se grafican igual que siempre. Sin regresión.

## 3. CSV: columna `phase` trailing

`save_data` añade `phase` a las columnas extra TRAILING (tras `sample,E_V,I_A,cycle,run`). Como
`Load` solo lee las 5 primeras, es retro-compatible. Permite filtrar el pre-tratamiento en
análisis posterior (todos los puntos llevan `cycle=0`, así que la columna `phase` es la única
forma fiable de separarlos):

```
sample, E_V, I_A, cycle, run, phase
0, -0.50, 1.2e-07, 0, 1, pretreatment
...
88, 0.31, 4.5e-06, 0, 1, sweep
```

## 4. Indicador de fase: que no parezca congelado

Como el pre-tratamiento (≈75–85 s con valores típicos) no dibuja nada, el plot queda estático y
parece colgado. Para evitarlo, la **etiqueta de estado** muestra la fase actual con un contador
que avanza cada segundo:

```
Pre-treatment — Condition  8/15 s
Pre-treatment — Deposition  34/60 s
Pre-treatment — Equilibration  3/10 s
Sweep — acquiring…
```

- **Time-based con cierre data-driven.** `SWVFrame.send_script` pasa `pretreatment_phases`
  (lista `[[nombre, dur_s], …]` de las fases presentes, mismas condiciones de presencia que el
  builder del script) a `EventPlotter.update_val_experiment`. El contador se ancla en
  `emstat_start` (`_acq_t0`) y se refresca dentro del loop UI existente (`_update_plot`, sin timer
  aparte). La transición a "Sweep" la marca el **primer paquete real de barrido** (`_sweep_t0`,
  `phase != "pretreatment"`), no el reloj: así el desfase de latencia (~<1 s) solo afecta a las
  cotas intermedias, no al fin del pre-tratamiento. Un contador de fase mostrando solo el nombre
  no bastaría (la "Deposition" de 60 s seguiría pareciendo congelada); por eso el contador n/dur.
- Si la duración estimada se cumple pero aún no llega el barrido (latencia/equilibración larga):
  `Pre-treatment done — waiting for sweep…`.
- CV/EIS/CA no pasan `pretreatment_phases` → el indicador no se activa (sin regresión).

## 5. Archivos tocados (host-only)

| Archivo | Cambio |
|---|---|
| `Drivers/EmstatUtils.py` | `EmstatStreamParser._handle_packet`: tag `phase` SWV por presencia de `I_A_F`/`I_A_R` |
| `ui/EventEmstatFrame.py` | data branch + `_reconcile_merge`: graficar solo `phase!="pretreatment"`, conservar todo en `total_data`; `save_data`: columna `phase`; `on_first_data` re-apuntado al 1er paquete de barrido (§2 de la doc del motor); indicador de fase (`pretreatment_phases`, `_acq_t0`/`_sweep_t0`, `_refresh_phase_status`) |
| `ui/SqwVFrame.py` | `send_script`: construye `pretreatment_phases` y lo pasa al plotter |

## 6. Verificación

- [ ] Con `t_con`/`t_dep`/`t_equil` > 0: el plot muestra solo la curva del barrido SWV (sin
  clusters a E constante).
- [ ] Durante el pre-tratamiento la etiqueta muestra la fase y un contador que avanza; al iniciar
  el barrido cambia a "Sweep — acquiring…".
- [ ] El CSV guardado contiene las filas de pre-tratamiento con `phase=pretreatment` y las del
  barrido con `phase=sweep`.
- [ ] CV/EIS/CA siguen graficando y guardando igual (sin columna `phase`, sin indicador de fase).

---

__author__ = "Edisson A. Naula"
__date__ = "$ 25/06/2026 $"
