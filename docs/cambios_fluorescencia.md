# Cambios: lectura de fluorescencia continua + estimación de tiempo

Archivo modificado: `ui/PcrFrame.py`

## 1. `_read_fluorescence` — muestreo continuo

Antes: encendía la luz, esperaba, tomaba **1 lectura**, apagaba. Devolvía 1 valor/ciclo.

Ahora: muestrea de forma continua (~0.1 s) modulando la luz (`pin_pcr`):

| Ventana    | Duración (default) | Luz | Clave en `settings.json` → `pcr_fluorescence` |
|------------|--------------------|-----|-----------------------------------------------|
| baseline   | 0.5 s              | OFF | `baseline_s`                                  |
| excitación | 2.0 s              | ON  | `light_s`                                     |
| post       | 0.5 s              | OFF | `post_s`                                      |

(Antes eran constantes de módulo; desde el 14/10/2026 se configuran en `settings.json`, ver §3.)

- Cadencia con *pacing* por tiempo transcurrido: `sleep(max(0, sample_dt - elapsed))`. `averages=4` por muestra (ambos en `pcr_fluorescence` desde el 14/10/2026: `sample_dt_s`, `averages`).
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

## 3. Ventanas configurables en `settings.json` (14/10/2026)

Las cuatro duraciones y el muestreo salieron del código a `settings.json` →
`pcr_fluorescence` (`pre_sleep_s`, `baseline_s`, `light_s`, `post_s`,
`sample_dt_s`, `averages`), editables desde el ConfigFrame como el resto del tuning. Las constantes `FLUOR_*` de
[PcrFrame.py](../ui/PcrFrame.py) quedan **solo como defaults**; `FLUOR_READ_TOTAL_S`
desapareció (ahora es `total_s` del dict).

- `_fluor_cfg(dict)` valida: no numérico o negativo → default. `baseline_s` y
  `light_s` en 0 también caen al default (sin una de esas ventanas el delta
  luz − baseline no tiene sentido); `pre_sleep_s` y `post_s` sí admiten 0.
  `sample_dt_s` también admite 0 (sin pacing: tan rápido como lea el ADS);
  `averages` se trunca a entero y < 1 cae al default (4). El JSON lo guarda como
  float (`4.0`) porque el ConfigFrame guarda todo con `float()`.
- `total_s` suma solo espera + ventanas: el muestreo no cambia la duración de una
  lectura (las ventanas son por tiempo), solo cuántas muestras caen en ellas.
- **Una lectura por corrida**: `experiment_pcr` guarda `self.fluor_cfg`, y de ahí
  salen la espera previa, las tres ventanas de `_read_fluorescence`, la ETA
  (`_estimate_total_s`, `_estimate_remaining_time`) y la metadata. Así todas las
  lecturas de una corrida usan las mismas ventanas aunque se edite el archivo a
  media corrida (a diferencia de las ganancias PID, que se releen por fase).
- La preview lee `settings.json` al dibujarse; `_estimate_cycle_s` /
  `_estimate_total_s` reciben el total como argumento `fluor_s`.
- Trazabilidad: la fila de metadata del CSV de temperatura lleva
  `-fluor: pre …s base …s light …s post …s dt …s avg …`.
- `DEFAULT_SETTINGS` incluye la sección, así que un Pi con `settings.json` viejo la
  recibe con los valores de siempre al arrancar (`seed_default_settings`).

## Decisiones tomadas (para retomar)
- Acumulación: serie completa + escalar derivado.
- Escalar: delta luz − baseline.
- Duraciones: `settings.json` → `pcr_fluorescence` (§3), una lectura por corrida; `use_diff` sigue en `photoreceptor`.
- Cadencia: `averages` (4) + pacing por tiempo transcurrido (`sample_dt_s`, 0.1 s), ambos en `pcr_fluorescence`.
- CSV crudo: nuevo archivo formato largo.
- Lectura final: se acumula igual que las de ciclo (índice = siguiente entero).
- Lógica de acumulación dentro de la función.
- Aborto: chequeo de stop + `try/finally`.
- Plot: un punto por read (sin plot en vivo de crudas).
- Estimación: teórico + lectura final, y también en camino medido; total desde `self.fluor_cfg`.

## Pendiente de verificar
Código de ruta hardware (Pi): pasa `pyrefly` (38 errores preexistentes, sin nuevos) pero **no** se ejecutó un ciclo real. Confirmar en el instrumento: timing del muestreo, contenido del CSV crudo y el ETA mostrado.
