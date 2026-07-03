# EIS — Espectroscopia de Impedancia Electroquímica

Nuevo tipo de experimento electroquímico, con estructura análoga a CV/SQWV. La fuente
de verdad del protocolo sigue siendo el firmware del Pico (ver
[emstat_abort_y_canal.md](emstat_abort_y_canal.md) para la cadena de transporte y el
contrato STOP/ABORT/canal).

Archivos:

- `ui/EisFrame.py` — frame nuevo (`EISFrame`).
- `ui/ElectrochemicalFrame.py` — caso `"Electrochemical Impedance"` cableado.
- `Drivers/EmstatUtils.py` — `construct_eis_script` + escala `zi` negada para Nyquist.
- `DiscPCB/EmstatDrivers.py` (Pico) — `construct_eis_script` + rama `"eis"` en `send_script`.
- `DiscPCB/emstat_wifi_v1.8.py` (Pico) — copia de v1.7 + EIS Fase 2 (claves nuevas en la
  rama `"eis"`, topes `max_ms`/`idle_ms` por corrida). v1.7 = copia de v1.6 + rama `"eis"`.

> El firmware del Pico vive en un proyecto **separado, no versionado en este repo**
> (`~/MicroPython/DiscPCB`, espejo en `firmware/DiscPCB/`). Cada versión previa se
> conserva intacta; el activo pasa a ser **v1.8** (convención de versionado).

---

## 1. Alcance (Fase 1)

El frame expone **dos selectores**, pero solo una combinación está implementada:

| Selector | Opciones | Fase 1 |
|---|---|---|
| **Scan type** | Default (E_dc, E_ac) · E_dc Scan · Time Scan | Solo **Default** |
| **Frequency type** | Scan · Fixed | Solo **Scan** |

Las entradas de las opciones inactivas **existen en la UI** (se muestran al seleccionarlas)
pero aún no generan script: al intentar `Script` o `Send Script` con una combinación no
soportada, se muestra el aviso *"Only 'Default' scan + 'Scan' frequency are implemented
for now."* y no se envía nada. Quedan listas para la Fase 2.

---

## 2. Parámetros

| Sección | Campo | Clave payload | Default | Notas |
|---|---|---|---|---|
| Pre-acondicionamiento | E cond 1 (V) | `E_con1` | 0 | Bloque `meas_loop_ca` omitido si `t_con1=0` |
| | t cond 1 (s) | `t_con1` | 0 | `0` → `""` (etapa omitida) |
| | E cond 2 (V) | `E_con2` | 0 | Segundo bloque, omitido si `t_con2=0` |
| | t cond 2 (s) | `t_con2` | 0 | |
| Scan: Default | E dc (V) | `E_dc` | 0.2 | Potencial DC del barrido EIS |
| | E ac (V) | `E_ac` | 0.01 | Amplitud AC (10 mV) |
| Frequency: Scan | f max (Hz) | `f_max` | 100000 | Frecuencia inicial (alta) |
| | f min (Hz) | `f_min` | 100 | Frecuencia final (baja) |
| | n frequencies | `n_freq` | 11 | Nº total de puntos (escala log) |
| | val/dec | — | — | **Solo lectura**: `round(n_freq / log10(f_max/f_min), 1)` |

`val/dec` se recalcula en vivo al cambiar `f_max`/`f_min`/`n_freq` (vía `trace_add` sobre
las `StringVar`); es informativo, no se envía. El parámetro que va al script es `n_freq`.

**Est. duration** (Fase 2, en el frame *Experiment type*): duración estimada del
experimento, recalculada en vivo (trace sobre todas las entradas de tiempo/barrido y al
cambiar de modo). Usa `_estimate_duration_s` — el mismo modelo `_point_s` de los topes
(§7.4) pero **sin** el margen ×1.5+60 de `max_time_s`. Muestra `—` con entradas
inválidas o la combo no soportada. Solo informativo, no se envía.

Los rangos de corriente (`da`/`ba`/`ab`) **no se exponen** en la UI: quedan fijos en el
generador de script (decisión de diseño — EIS usa autorango interno).

### Payload

```json
{"method":"eis","scan_type":1,"freq_type":1,"ch":0,
 "E_ac":"10m","f_max":"100k","f_min":"100","n_freq":11,"E_dc":"200m",
 "E_con1":"0","t_con1":"","E_con2":"0","t_con2":""}
```

Valores SI vía `convert_si_integer_full` (p.ej. `0.01 → "10m"`, `100000 → "100k"`);
`n_freq` es `int` crudo; `ch` es `int` (canal MCP, ver doc de canal). Los tiempos de
acondicionamiento en `0` se normalizan a `""`.

---

## 3. MethodSCRIPT generado (`construct_eis_script`)

Diseño **híbrido**: front-end verificado contra el **ejemplo oficial de PalmSens**
(`set_pgstat_chan 0`, `set_pgstat_mode 3` high-speed, `set_autoranging ba 10u 1m`) +
acondicionamiento opcional. No reutiliza `construct_header_experiment`.

```
e
var f / var z_r / var z_i / var i / var e
set_pgstat_chan 0
set_pgstat_mode 3
set_autoranging ba 10u 1m
[si hay acondicionamiento:] set_e {E_con1 si t_con1, si no E_con2 si t_con2}
cell_on
[si t_con1:] meas_loop_ca e i {E_con1} 200m {t_con1} … endloop
[si t_con2:] meas_loop_ca e i {E_con2} 200m {t_con2} … endloop
[si hubo acondicionamiento:] set_autoranging ba 10u 1m   (re-asegura el rango)
meas_loop_eis f z_r z_i {E_ac} {f_max} {f_min} {n_freq} {E_dc}
  pck_start / pck_add f / pck_add z_r / pck_add z_i / pck_end
endloop
on_finished:
  cell_off
```

**Sin acondicionamiento** (`t_con1=t_con2=0`) el script se reduce exactamente al ejemplo
oficial: `chan 0 → mode 3 → autoranging ba 10u 1m → cell_on → meas_loop_eis`. Con
acondicionamiento se añaden `set_e` inicial, los bloques `meas_loop_ca` y el re-aseguro
del rango ba. Las variables `i`/`e` se declaran para los bloques `meas_loop_ca`.

**Orden de `meas_loop_eis`:** `f z_r z_i E_ac f_max f_min n_freq E_dc`. Validado contra el
ejemplo oficial `meas_loop_eis freq z_real z_imag 10m 200k 200 11 0` (E_ac=10 mV,
f_max=200 kHz, f_min=200 Hz, n_freq=11, E_dc=0).

La misma función existe **dos veces** (idéntica, verificado byte a byte): en
`Drivers/EmstatUtils.py` (host, para previsualizar el script) y en
`DiscPCB/EmstatDrivers.py` (Pico, para enviarlo al EmStat).

---

## 4. Graficado (Nyquist) y parseo

- **Plot:** `EventPlotter` en modo Nyquist — `x_key="Z_real"`, `y_key="Z_imag"`,
  etiquetas `Z_real (Ω)` / `-Z_imag (Ω)`, título `EIS (Nyquist)`.
- **Convención del eje Y:** el eje Y del Nyquist es **−Z_imag**. La negación se hace
  **explícita en `_decode`** (`out["Z_imag"] = -out["Z_imag"]` para `experiment=="eis"`).
  Nota: la columna `scale` de `FIELD_MAP` es **vestigial** — `_decode` solo aplica el
  prefijo de unidad SI, no `scale`; por eso la negación no puede hacerse vía `scale`.
- **Parser — códigos de paquete REALES** (verificados contra salida cruda del EmStat):
  `dc`→`freq_Hz`, `cc`→`Z_real`, `cd`→`Z_imag`. **No** son `fr`/`zr`/`zi`. La frecuencia
  se guarda en `total_data` (no se grafica en el Nyquist) y queda disponible para análisis.
- **Marcador de inicio de loop `M000D`:** el índice es **hexadecimal**. El parser lo
  decodifica con `int(x, 16)` (`_safe_hex`); antes usaba base 10 y **crasheaba** el hilo
  procesador con índices que traen letras hex (CV/SQWV se salvaban por usar índices 0-9).
- **Paquetes de acondicionamiento:** los bloques `meas_loop_ca` emiten paquetes `da`/`ba`
  (potencial/corriente), sin campos Z. El parser los marca como `type="unknown"` para no
  graficar puntos `(0,0)` espurios en el Nyquist.

### Ejemplo de salida cruda (verificado)

```
M000D                                                  ← inicio del loop (índice hex)
Pdc8030D40 ;ccAAE483Fm,14,288;cd7FD3127 ,14,288        ← f≈200 kHz, Z_real, Z_imag
…
Pdc8030D3Fm;cc80EDA04 ,14,287;cd9751491m,14,287
*                                                      ← fin del loop
```

---

## 5. Firmware del Pico (v1.7)

Rama `"eis"` en `handle_command` (en `emstat_wifi_v1.7.py`), idéntica en estructura a
`cv`/`sqwv`:

1. Normaliza `t_con1`/`t_con2` (`"0"`/`0` → `""`).
2. Arma `params` desde las claves del payload.
3. Valida y activa el canal de electrodo (`_activate_channel`) — **obligatorio**; si falla,
   responde `emstat_error`.
4. `emstat_start` → `send_script(params, method="eis")` → `run_experiment_read_loop("eis")`.
5. `_deactivate_channel()` en `finally` (apaga el canal en TODAS las salidas).

Reusa el loop de lectura robusto de v1.6 (idle timeout + tope absoluto + ABORT + `Z`), así
que EIS hereda gratis el manejo de cierres terminales y el dead-man switch del Wemos.

---

## 6. Pendientes / a verificar (requiere hardware)

- [x] **Códigos de paquete EIS** — resueltos contra salida cruda: `dc`/`cc`/`cd`
      (frecuencia/Z_real/Z_imag). Parser corregido y probado con paquetes reales.
- [x] **Orden de `meas_loop_eis`** — confirmado contra el ejemplo oficial
      (`10m 200k 200 11 0` = E_ac/f_max/f_min/n_freq/E_dc).
- [x] **Front-end del script** — alineado con el ejemplo oficial PalmSens (modo 3,
      autorango ba 10u-1m). Sin acondicionamiento, el script == ejemplo oficial.
- [ ] Corrida EIS real end-to-end: confirmar que el Nyquist se grafica y que los
      semicírculos van hacia arriba (−Z_imag positivo en zona capacitiva).
- [ ] Validar el acondicionamiento opcional (`E_con1`/`t_con1`, `E_con2`/`t_con2`) en
      hardware: que los bloques `meas_loop_ca` no contaminen el Nyquist (filtro `da`/`ba`).
- [ ] Barridos EIS de baja frecuencia pueden superar `MAX_EXPERIMENT_MS` (10 min) →
      vigilar `emstat_maxtime` y ajustar si hace falta.

---

## 7. Fase 2 — implementada (host + firmware v1.8 flasheado)

Diseño cerrado en entrevista (2026-06-11) contra **4 exports reales de PSTrace** (uno por
modo, valores distintivos para mapeo unívoco). El lado host está implementado
(`ui/EisFrame.py`, `Drivers/EmstatUtils.py`, `ui/EventEmstatFrame.py`); los 5 scripts
generados se verificaron contra los exports. El firmware **v1.8 está flasheado en la
placa** (2026-06-11) y **E_dc Scan + freq Scan quedó validado end-to-end en hardware**
(9 espectros superpuestos, leyenda por potencial, cierre con `emstat_end` tras el fix
del marcador `'+'` — ver §7.5). Decisiones:

### 7.1 Matriz soportada

| Combo | Sentido físico | Plot |
|---|---|---|
| Default + Fixed | Un punto Z a una frecuencia | Nyquist (1 punto) |
| E_dc Scan + Scan | Espectro completo por potencial | Nyquist superpuestos, una curva por potencial (mecanismo de cycles; leyenda `E=…V`) |
| E_dc Scan + Fixed | Z vs E a una frecuencia (Mott-Schottky-style) | x=potencial, y=\|Z\| |
| Time Scan + Fixed | Z vs tiempo a una frecuencia | x=tiempo, y=\|Z\| |

**Time Scan + Scan queda excluido** (espectros repetidos en el tiempo: corridas larguísimas,
choca con el tope del firmware). `\|Z\| = sqrt(Z_real²+Z_imag²)` es un campo derivado
calculado en el parser (`Z_mod`); Z_real/Z_imag completos siguen en `total_data`/CSV.

### 7.2 Construcciones MethodSCRIPT (verificadas contra exports PSTrace)

- **Frequency Fixed** = `meas_loop_eis` degenerado: `f_max = f_min = f`, `n_freq = 1`.
  No hay comando nuevo; el parser `dc`/`cc`/`cd` sirve tal cual.
- **E_dc Scan** = loop genérico envolviendo `meas_loop_eis` con potencial en variable:

  ```
  store_var extra1 {E_begin} da
  loop 1i == 1i
    meas_loop_eis f z_r z_i {E_ac} {f_max} {f_min} {n_freq} extra1
      pck_start / pck_add f / pck_add z_r / pck_add z_i / pck_add extra1 / pck_end
    endloop
    add_var extra1 {±E_step}
    if extra1 {>|<} {E_end ± E_step/2}   ← tolerancia de medio paso (acumulación float)
      breakloop
    endif
  endloop
  ```

  El `pck_add extra1` (código `da`) es **desviación nuestra** del export: PSTrace no mete
  el potencial en el paquete (habría que contar marcadores `M…`, frágil ante pérdidas).
  Con el potencial en el paquete los datos son autodescriptivos y la recuperación UDP
  funciona. **Ambas direcciones soportadas**: el generador deriva el signo del paso de
  `(E_end − E_begin)`; el usuario captura `E_step` siempre positivo.
- **Time Scan** = **un solo** `meas_loop_eis` con `n_freq = floor(t_run/t_interval) + 1`
  a frecuencia fija, pacificado por timer (patrón exacto del export PSTrace):

  ```
  store_var extra1 0 eb
  meas_loop_eis f z_r z_i {E_ac} {f} {f} {n} {E_dc}
    if extra1 == 0:  timer_start / set_int {t_interval}   else:  timer_get extra1
    pck_start / f / z_r / z_i / pck_add extra1 / pck_end
    if extra1 == 0:  store_var extra1 {t_interval} eb
    if extra1 >= {t_run}:  abort
    await_int
  endloop
  ```

  El tiempo viaja en el paquete con tipo **`eb`** (código de paquete a verificar en
  hardware). ⚠️ PSTrace termina con `abort` dentro del script: verificar en hardware
  cómo lo reporta el EmStat (si el Pico lo mapea a `emstat_aborted`, una corrida exitosa
  se marcaría abortada).

### 7.3 Front-end común (los 5 modos)

Se mantiene el de Fase 1 (chan 0, mode 3, `set_autoranging ba 10u 1m` — verificado con
paquetes reales) + dos adopciones del export PSTrace:

- `set_e {potencial inicial}` **incondicional** antes de `cell_on` (E_con1 si hay
  acondicionamiento, si no E_dc / E_begin).
- `set_max_bandwidth` = **10 × frecuencia máxima** (regla confirmada en 3 exports:
  10k→100k, 100k→1M, 5k→50k, 2k→20k).

**No** se adopta el resto del boilerplate PSTrace (chan 1 off, rangos fijos min=max:
dependen de la corriente esperada de la celda; contradice la decisión de autorango §2).

### 7.4 Payload / firmware / parser

- **Encoding 1-based** (ya enviado en Fase 1): `scan_type` 1=Default, 2=E_dc Scan,
  3=Time Scan; `freq_type` 1=Scan, 2=Fixed. Claves nuevas por modo: `E_begin`/`E_step`/
  `E_end`, `f` (fixed), `t_run`/`t_interval`.
- **Topes dinámicos**: el host estima la duración y manda `max_time_s` en el payload; el
  firmware usa `max(estimado×1.5, 10 min)` como tope absoluto de esa corrida. Además el
  host manda **`idle_s`**: el EmStat emite UN paquete por punto AL TERMINARLO, así que el
  hueco máximo legítimo entre paquetes es la duración del punto más lento — modelo
  `_point_s(f) = 30/f + 3 s` (≈30 periodos + overhead), `idle_s = punto_más_lento×1.5+15`
  (en Time Scan también cubre `t_interval`). Sin esto, el idle fijo del Pico (16 s)
  abortaba con `emstat_timeout` cualquier barrido con puntos bajo ~1 Hz (corridas reales
  de 51 puntos llegan a ~20 min). El watchdog del host se deriva del mismo valor
  (`idle_s + 15`) para que el terminal del firmware siempre gane. Dead-man del Wemos
  intacto. Requiere firmware v1.8.
- **Parser**: `da` → `E_V` y `eb` → `t_s` en `FIELD_MAP["eis"]`; el filtro de
  acondicionamiento (unknown si no trae Z) ya cubría el caso mixto da+Z. `Z_mod`
  (=|Z|) se deriva en `_decode`. La asignación de cycle por cambio de potencial es
  opt-in (`EmstatStreamParser(..., eis_group_by_potential=True)`, solo E_dc Scan +
  freq Scan — en Mott-Schottky partiría la traza única) y se plumbea vía
  `EventPlotter.update_val_experiment(parser_kwargs=..., cycle_legend=...)`; la
  leyenda por potencial usa `cycle_legend=("E_V", "E={:.3g}V")`.
- **Fix de parseo descubierto en pruebas**: el valor de cada subcampo es SIEMPRE
  7 hex + 1 char de unidad; si el último subcampo de la línea tiene unidad espacio
  (adimensional: `eb` segundos, `da` en volts exactos) y no trae metadata, el strip
  del transporte se la comía y `head[-1]` corrompía el valor. `_parse_packet` ahora
  corta por longitud fija (`head[2:9]` + `head[9]`).
- **Watchdog del host**: `EventPlotter.watchdog_timeout` (10 s) se ajusta por corrida
  en `EisFrame.send_script` a `max(10, t_interval+5)` — un Time Scan con intervalo
  ≥10 s cerraría la corrida a medias con el default.
- **CSV**: columnas extra *trailing* (`freq_Hz`, `E_V`, `t_s`, `Z_mod` cuando existen
  y no son ya x/y); Load solo lee las 5 primeras, así que no rompen la recarga.
- `construct_eis_script` sigue duplicado byte a byte (host + Pico), ahora parametrizado
  por `scan_type` (el freq_type no llega al generador: el host degenera
  f_max=f_min=f / n_freq antes).

### 7.5 Pendientes de verificación en hardware (Fase 2)

**E_dc Scan + freq Scan validado end-to-end** (2026-06-11): 9 espectros 0.1→0.5 V
correctos, superpuestos y con leyenda por potencial; tras re-flashear con el fix del
`'+'`, la corrida cierra con `emstat_end` ✓.

**idle_s validado con cola de baja frecuencia** (2026-06-12): Default + Scan
200 kHz→0.5 Hz, 30 puntos. Con el firmware viejo (idle fijo 16 s) moría por
`emstat_timeout` justo en el punto de 0.5 Hz (29/30); con v1.8 re-flasheado (idle_s
del payload) completa ✓. Duración real ~4 min ≈ estimado del indicador — el modelo
`_point_s` queda calibrado razonablemente (los puntos reales son más rápidos que el
modelo: t(0.5 Hz) real < 20 s, el ×1.5 de margen sobra).

- [x] **Fin anticipado en E_dc Scan**: NO ocurre — los 9 espectros completaron (tras
      cada `*` viene directo el siguiente bloque, sin blank intercalada).
- [x] **Fin de corrida en E_dc Scan** — RESUELTO con el TAIL de la 2ª corrida. El
      script anidado termina `'*'` (último meas_loop) → **`'+'`** (fin del loop
      GENÉRICO, marcador que CV/SWV/Fase-1 nunca producían) → blank. El Pico solo
      reconocía `'*' + blank`, así que ignoraba la blank tras `'+'`, esperaba su
      idle (16 s), mandaba `Z` y el EmStat respondía **`Z!0006`** (nada que abortar:
      el script ya había acabado) → `emstat_timeout`; y como el watchdog del host
      (10 s) era menor, el usuario veía "watchdog". Fixes: firmware v1.8 reconoce
      fin con blank tras `'*'` **o** `'+'` (`last_was_star = stripped in ("*", "+")`),
      y el watchdog EIS del host subió a `max(25 s, t_interval+15)`. `EventPlotter`
      ganó el volcado **TAIL** (últimos 20 mensajes crudos al cerrar) como
      herramienta de diagnóstico permanente.
      Evidencia adicional del TAIL: `da` llega con unidad `u` (0.5 V = `da807A120u`),
      merge = 99 puntos exactos (9 espectros × 11), pérdida TCP 0%.
- [ ] Código de paquete real de `eb` (tiempo) en salida cruda.
- [x] Código/formato de `da` (potencial) en paquetes EIS mixtos — funciona (el
      agrupado por potencial salió bien en hardware).
- [ ] Terminal del `abort` de fin de Time Scan (`emstat_end` vs `emstat_aborted`).
- [ ] Interacción cycles-por-potencial × Keep runs (los offsets de
      `plot_run_offset` deben apilarse sobre los cycles por espectro).
- [x] `MAX_IDLE_MS` del Pico vs `t_interval` grandes — idle dinámico en v1.8 (§7.6).

### 7.6 Diff de firmware v1.8 — aplicado y **flasheado** (2026-06-11)

Aplicado en `~/MicroPython/DiscPCB` (v1.7 intacto), resincronizado a
`firmware/DiscPCB/` y flasheado a la placa (`main.py` + `EmstatDrivers.py`). Los
cambios:

1. **`EmstatDrivers.py` — `construct_eis_script`**: reemplazar la función completa por
   la de `Drivers/EmstatUtils.py` de este repo (byte a byte; ya incluye los kwargs
   nuevos `scan_type`, `bandwidth`, `E_begin/E_step/E_break/E_dir`, `t_run/t_interval`).

2. **`EmstatDrivers.py` — `send_script`, rama `"eis"`**: añadir el reenvío de los
   kwargs nuevos:

   ```python
   elif method == "eis":
       script = construct_eis_script(
           parameters.get("E_ac", "10m"),
           parameters.get("f_max", "100k"),
           parameters.get("f_min", "100"),
           parameters.get("n_freq", 11),
           parameters.get("E_dc", "0"),
           parameters.get("E_con1", ""),
           parameters.get("t_con1", ""),
           parameters.get("E_con2", ""),
           parameters.get("t_con2", ""),
           scan_type=parameters.get("scan_type", 1),
           bandwidth=parameters.get("bandwidth", ""),
           E_begin=parameters.get("E_begin", ""),
           E_step=parameters.get("E_step", ""),
           E_break=parameters.get("E_break", ""),
           E_dir=parameters.get("E_dir", 1),
           t_run=parameters.get("t_run", 0),
           t_interval=parameters.get("t_interval", 0),
       )
   ```

3. **`emstat_wifi_v1.8.py`**:
   - `run_experiment_read_loop(method, on_data=None, max_ms=None, idle_ms=None)`:
     usar `max_ms or MAX_EXPERIMENT_MS` en el chequeo del tope absoluto y
     `idle_ms or MAX_IDLE_MS` en el chequeo de idle (defaults actuales intactos
     para cv/sqwv).
   - Rama `"eis"` de `handle_command`: extender `params` con las claves nuevas
     (`scan_type`, `bandwidth`, `E_begin`, `E_step`, `E_break`, `E_dir`, `t_run`,
     `t_interval` — mismos defaults que el punto 2) y calcular los topes dinámicos:

     ```python
     max_ms = max(int(cmd_obj.get("max_time_s", 0)) * 1000, MAX_EXPERIMENT_MS)
     idle_ms = max(int(cmd_obj.get("idle_s", 0)) * 1000,
                   (int(cmd_obj.get("t_interval", 0)) + 5) * 1000, MAX_IDLE_MS)
     ...
     run_experiment_read_loop("eis", max_ms=max_ms, idle_ms=idle_ms)
     ```

     El dead-man del Wemos queda intacto como red de seguridad; `max_time_s` e
     `idle_s` vienen ya calculados desde el host (`EisFrame._estimate_max_time_s` /
     `EisFrame._point_s` — ver §7.4 *Topes dinámicos*). El modelo del punto
     (`30/f + 3 s`) es calibración conservadora: **si una corrida real muere con
     `emstat_maxtime`/`emstat_timeout` siendo legítima, subir la constante en
     `_point_s` (host) — el firmware no se toca.**

4. (Post-hardware) **Fin normal con `'+'`**: `run_experiment_read_loop` reconoce el
   fin con blank tras `'*'` **o** `'+'` (fin de loop genérico, emitido por el script
   anidado del E_dc Scan). Ver hallazgo en §7.5. Sin cambio para cv/sqwv (nunca
   emiten `'+'`).

---

## 8. Ventana de análisis EIS (`ui/analysis/eis.py`)

`AnalysisWindow` pasó de ser una ventana única (análisis de picos CV/SWV) a un **shell
`Toplevel` con un `ttk.Notebook` por método**: pestaña **"Peaks (CV/SWV)"**
(`PeakAnalysisFrame`, el contenido anterior refactorizado a un `Frame` — el antiguo menú
File se reemplazó por botones Load/Import/Export en su toolbar; los atajos `Ctrl+L`/`Ctrl+I`
se mantienen, ahora cableados en el shell; además una **lectura por hover** (`_on_hover`)
muestra el `(x, y)` del punto medido más cercano de la curva bajo el cursor en el overlay,
con snap en píxeles para no sesgar por las escalas dispares de los ejes) y pestaña
**"EIS"** (`EISAnalysisFrame`, nueva). `EventPlotter.open_analysis_window` abre la misma
ventana; la pestaña activa por defecto la decide `plotter.method` (EIS → pestaña EIS).

**Paridad de la pestaña Peaks con EIS.** El frame de Peaks adoptó dos patrones que
nacieron en EIS:

- **Reconstrucción del canvas** (mismo que §8.2): `_refresh_overlay` y `clear_all`
  recrean Figure + `FigureCanvasTkAgg` + toolbar desde cero (`_reset_plot_canvas` →
  `_create_plot_canvas`) en vez de `ax.clear()`/`fig.clear()`, para no arrastrar estado
  residual en el canvas Tk vivo. Efecto colateral intencional: las tendencias
  (`ax_min`/`ax_max`) quedan en blanco tras un refresco de overlay (cambio de
  filtro/visibilidad/nombre) hasta el siguiente **Compute**, que las recalcula — es lo
  correcto, dependen del filtro/datos que pudieron cambiar.
- **Renombrar (doble clic)**: editor `Entry` inline sobre la columna `#0`, igual que en
  EIS (Enter/foco-fuera confirma, Esc cancela, vacío revierte). Aquí funciona en **ambas
  tablas**: el árbol izquierdo *Experiments → Cycles* (`tree_curves` → `_tree_ref`) y la
  **tabla de resultados** (`tree_res` → `_res_ref`, poblado en `compute_extrema`). Las
  filas agregadas `⟨max⟩`/`⟨min⟩` no están en `_res_ref`, así que no son editables. El
  editor es genérico (detecta el árbol vía `event.widget`); al confirmar renombra
  `exp.name`/`cycle.name` (fluye a la leyenda `exp/cycle` del overlay), refresca el árbol
  y, si la tabla de resultados tiene contenido, re-ejecuta `compute_extrema` para que el
  nombre nuevo aparezca en todas sus filas. Es **solo de sesión**.

### 8.1 Datos (carga / siembra)

- **Modelo rico por espectro** (`EISSpectrum`): arrays nombrados (`freq_Hz`, `Z_real`,
  `Z_imag`, `Z_mod`, `E_V`, `t_s`) + **derivados** `Z_mod` (si falta) y `phase_deg`
  (`atan2(Z_imag, Z_real)`). Como el parser guarda `Z_imag` ya negado, la fase sale con
  el signo de PSTrace (positiva en zona capacitiva). `EISExperiment` = un archivo/corrida
  con N espectros.
- **Siembra desde `total_data`** de la corrida en memoria al abrir Analyze desde un
  plotter EIS (datos ricos: freq+Z completos → Bode disponible al instante).
- **Load CSV** lee los CSV de `save_data` **por NOMBRE de header** (no por posición como
  el de Peaks): mapea `Z_real`/`Z_imag`/`freq_Hz`/`Z_mod`/`E_V`/`t_s` + `cycle`/`run` y
  agrupa por `(run, cycle)` en espectros (etiqueta `E=…V` si hay potencial embebido).
- **Renombrar (doble clic en el árbol)**: el nombre auto-deducido de un experimento o
  espectro se edita con un `Entry` inline sobre la celda (Enter/foco-fuera confirma, Esc
  cancela, vacío revierte; duplicados permitidos). El `Entry` se ensancha hasta el borde
  derecho del árbol (solapa la columna *State*, mínimo 240 px) para ver el nombre completo
  al escribir. El nombre nuevo fluye al árbol, la leyenda del plot y la tabla/Export de
  resultados. Es **solo de sesión**: recargar el `eis_data_*.csv` crudo re-deduce el nombre
  (ese archivo no guarda nombres).

### 8.1b Layout (scroll + figura adaptativa)

Igual que la pestaña Peaks, el contenido (árbol + figura + tabla de resultados) vive dentro
de un `Canvas` con scroll vertical (toolbars arriba y status abajo quedan fijos; rueda de
ratón cableada). La **altura de la figura es adaptativa** (`_set_fig_height`): ~4″ con 1 fila
del grid (1-2 plots), ~7″ con 2 filas (3-4 plots) — ajusta también el alto del widget Tk para
que el `scrollregion` sea correcto. Así cada eje conserva un tamaño legible y el scroll
aparece cuando el contenido no entra.

### 8.2 Gráficos (checkboxes + grid dinámico)

Cuatro tipos, en una sola figura cuyo grid se reconstruye con los ejes marcados (1→1×1,
2→1×2, 3/4→2×2). Cada checkbox se **habilita solo si los datos cargados tienen las
columnas** que necesita (gris si no):

| Plot | Requiere | Ejes |
|---|---|---|
| **Nyquist** | `Z_real` + `Z_imag` | x=Z_real, y=−Z_imag |
| **Bode** | `freq_Hz` + Z completos, >1 freq | doble eje Y: log\|Z\| (sólido) + fase° (punteado) vs log f |
| **\|Z\| vs E** | `E_V` + `Z_mod`, ≤1 freq | x=E dc, y=\|Z\| |
| **\|Z\| vs t** | `t_s` + `Z_mod` | x=t, y=\|Z\| |

**Reconstrucción del canvas (no `fig.clear()`).** `_refresh_plots` **recrea la Figure y
el `FigureCanvasTkAgg` desde cero** en cada redibujo (`_reset_plot_canvas` →
`_create_plot_canvas`), en vez de reusar la figura con `fig.clear()`. Reusarla dejaba, en
el canvas Tk **vivo** (no reproducible headless), un **subplot fantasma vacío** al togglear
un checkbox: estado residual de `constrained_layout` combinado con el eje gemelo `twinx`
del Bode. Recrear el canvas descarta todo estado previo (motor de layout + ejes gemelos).
El coste es un parpadeo en el toggle deliberado; los handlers (`_on_pick`, `_on_motion`) y
el `NavigationToolbar2Tk` se recablean en cada recreación.

### 8.3 Análisis

- **Nyquist — picking manual + cálculo** sobre el **espectro seleccionado en el árbol**,
  con **snap al punto medido más cercano**: botón *Pick Rs* (intercepto alta-freq), *Pick
  Rct edge* (`Rct = x_edge − Rs`), *Pick Warburg* (2 clics → `L = |Δ Z_real|` proyectada
  sobre el eje real + ángulo para confirmar ~45°). Marcadores/líneas guía dibujados sobre
  la curva; resultados en tabla por espectro.
- **Bode — crosshair/lectura manual**: al mover el ratón sobre el eje |Z| se muestra
  `(freq, |Z|, fase)` del punto más cercano (sin auto-detección de picos).

### 8.4 Export / Import (paridad con Peaks)

Espeja el patrón de dos archivos de la pestaña Peaks (`export_results` →
`<base>.csv` + `<base>_curves.csv`; `import_analysis`). El botón **Export** abre **un
solo** diálogo (`eis_analysis_*.csv` por defecto) y deriva los nombres:

- **`<base>_spectra.csv` — SIEMPRE** (gate = "¿hay espectros?", no "¿hay mediciones?").
  Datos punto-a-punto de **todos** los espectros cargados, **sin importar visibilidad**
  (la visibilidad en EIS es solo visual). Header **fijo** `EIS_SPECTRA_COLS`:
  `experiment, spectrum, point_idx, freq_Hz, Z_real, Z_imag, Z_mod, phase_deg, E_V, t_s`;
  celdas **vacías** donde un espectro no tiene esa magnitud (p.ej. `freq_Hz`/`E_V`/`t_s`
  según el modo). `%.9g` por celda. Es el archivo que permite **guardar las curvas usadas
  para análisis y recargarlas sin re-seleccionarlas**.
- **`<base>.csv` (el path elegido) — solo si hay al menos una medición** Nyquist
  (Rs/Rct/Warburg). Formato intacto: `experiment, spectrum, Rs_ohm, Rct_ohm,
  warburg_len_ohm, warburg_angle_deg`. Sin mediciones, no se crea (el status lo dice).

**Import** (`import_spectra`, botón `📥 Import` y `Ctrl+I` en la pestaña EIS) recarga un
`_spectra.csv`: valida el header (`experiment` + `spectrum` + alguna columna `Z_*`),
agrupa por `(experiment, spectrum)` y **conserva los nombres** (incluidos los renombrados
a mano), a diferencia de **Load CSV** que re-deduce el nombre del `eis_data_*.csv` crudo.
`Z_mod`/`phase_deg` se re-derivan al construir el `EISSpectrum` cuando hay `Z_real/Z_imag`;
en modos sin Z (|Z| vs t) el `Z_mod` del archivo se conserva. Hace **append** (no
reemplaza) y de-duplica nombres de experimento colisionantes con sufijo `_1`, `_2`, …

Los atajos `Ctrl+L` (Load) y `Ctrl+I` (Import) del shell `AnalysisWindow` se **enrutan a
la pestaña activa** del notebook (antes iban fijos a Peaks).

---

__author__ = "Edisson A. Naula"
