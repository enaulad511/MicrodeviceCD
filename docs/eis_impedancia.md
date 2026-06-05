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
- `DiscPCB/emstat_wifi_v1.7.py` (Pico) — copia de v1.6 + rama `"eis"` en `handle_command`.

> El firmware del Pico vive en un proyecto **separado, no versionado en este repo**.
> v1.6 se conserva intacto; el activo pasa a ser **v1.7** (convención de versionado).

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

## 7. Fase 2 (no implementado)

Entradas ya presentes en la UI, pendientes de cablear payload + script:

- **Scan type E_dc Scan:** `E_begin`, `E_step`, `E_end`, `E_ac` (barrido de potencial DC).
- **Scan type Time Scan:** `E_dc`, `t_run`, `t_interval`, `E_ac` (impedancia vs tiempo).
- **Frequency type Fixed:** `frequency` (una sola frecuencia).

---

__author__ = "Edisson A. Naula"
