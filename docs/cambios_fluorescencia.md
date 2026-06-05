# Cambios: lectura de fluorescencia continua + estimación de tiempo

Archivo modificado: `ui/PcrFrame.py`

## 1. `_read_fluorescence` — muestreo continuo

Antes: encendía la luz, esperaba, tomaba **1 lectura**, apagaba. Devolvía 1 valor/ciclo.

Ahora: muestrea de forma continua (~0.1 s) modulando la luz (`pin_pcr`):

| Ventana    | Duración | Luz | Constante           |
|------------|----------|-----|---------------------|
| baseline   | 0.5 s    | OFF | `FLUOR_BASELINE_S`  |
| excitación | 2.0 s    | ON  | `FLUOR_LIGHT_S`     |
| post       | 0.5 s    | OFF | `FLUOR_POST_S`      |

- Cadencia con *pacing* por tiempo transcurrido: `sleep(max(0, sample_dt - elapsed))`. `averages=4` por muestra.
- **Abort-safe**: revisa `stop_udp_listenner` cada iteración; `try/finally` garantiza `pin_pcr.write(False)`.
- **Escalar acumulado** = `media(ventana luz) − media(ventana baseline)` (ventana vacía → 0.0).
- Acumulación **dentro de la función** (fuente única): agrega el escalar a `data_photodetector` (plot por-ciclo) y la serie cruda a la nueva lista `data_photodetector_series`; agenda `update_graph_photodetector` vía `self.after`. Devuelve el escalar.

### Estructuras / call sites
- Nueva lista `self.data_photodetector_series` (init líneas ~207 y ~390).
- Call site por-ciclo: se eliminó el `append`/`update` redundante (ahora interno).
- Lectura **final** (post-ciclos): antes solo se imprimía; ahora **también acumula** (escalar + serie + plot). Recibe el siguiente índice entero de ciclo automáticamente (comparte `data_photodetector_series`).

### CSV
- Se mantiene `photodetector_data_*.csv` (1 escalar por fila).
- **Nuevo** `photodetector_raw_*.csv` formato largo: `cycle, t_rel_s, light_on, voltage` (1 fila por muestra, todos los ciclos apilados).

## 2. Estimación de tiempo

Constantes de módulo como fuente única de verdad (también defaults de la función y sleeps previos):

```python
FLUOR_PRE_SLEEP_S = 0.5
FLUOR_BASELINE_S  = 0.5
FLUOR_LIGHT_S     = 2.0
FLUOR_POST_S      = 0.5
FLUOR_READ_TOTAL_S = FLUOR_PRE_SLEEP_S + FLUOR_BASELINE_S + FLUOR_LIGHT_S + FLUOR_POST_S  # 3.5 s
```

- `time.sleep(0.5)` previos a cada lectura → `time.sleep(FLUOR_PRE_SLEEP_S)`.
- `teorical_time_pcr` (ETA pre-primer-ciclo): suma `FLUOR_READ_TOTAL_S * cycles` (lecturas por ciclo) + `FLUOR_READ_TOTAL_S` (lectura final).
- `_estimate_remaining_time`, rama `cycles_left > 0` (camino medido): suma `FLUOR_READ_TOTAL_S` por la lectura final pendiente (las por-ciclo ya están en `avg_cycle_duration`, no se duplican).

## Decisiones tomadas (para retomar)
- Acumulación: serie completa + escalar derivado.
- Escalar: delta luz − baseline.
- Duraciones: parámetros de la función; `use_diff` sigue desde `settings.json`.
- Cadencia: `averages=4` + pacing por tiempo transcurrido.
- CSV crudo: nuevo archivo formato largo.
- Lectura final: se acumula igual que las de ciclo (índice = siguiente entero).
- Lógica de acumulación dentro de la función.
- Aborto: chequeo de stop + `try/finally`.
- Plot: un punto por read (sin plot en vivo de crudas).
- Estimación: teórico + lectura final, y también en camino medido; constantes de módulo.

## Pendiente de verificar
Código de ruta hardware (Pi): pasa `pyrefly` (38 errores preexistentes, sin nuevos) pero **no** se ejecutó un ciclo real. Confirmar en el instrumento: timing del muestreo, contenido del CSV crudo y el ETA mostrado.
