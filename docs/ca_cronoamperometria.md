# Cronoamperometría (CA)

Medición de **corriente vs tiempo** (`I` vs `t`) bajo un **escalón de potencial**
constante `E_dc`. A diferencia de CV/SQWV (barren el potencial) o EIS (modula en
frecuencia), CA fija `E_dc` y registra el transitorio de corriente (decaimiento tipo
Cottrell) durante `t_run`, muestreando cada `t_interval`.

En este instrumento CA se usa principalmente como **paso intermedio de
acondicionamiento entre corridas de SQWV** (limpiar/estabilizar el electrodo a un
potencial fijo antes del siguiente barrido).

## 1. Inputs

Cuatro entradas propias + dos controles compartidos con CV/SQWV:

| Input | Significado |
|---|---|
| `t_equilibrium` (s) | Pre-acondicionamiento opcional a `E_dc` (0 = omitido). |
| `E_dc` (V) | Potencial del escalón (constante toda la corrida). |
| `t_interval` (s) | Periodo de muestreo del loop principal. |
| `t_run` (s) | Duración del escalón principal. |
| Max bandwidth (Hz) | `set_max_bandwidth`. Editable; default `58505m` (valor de PSTrace, aún sin fórmula derivada). |
| Current Range | Radio de rango `ba` (igual que CV/SQWV). |

El **canal de electrodo** NO es parte de la receta: vive en el selector compartido de
`ElectrochemicalFrame` y llega vía `callback_get_channel` (igual que CV/SQWV/EIS).

UI: [ui/CaFrame.py](../ui/CaFrame.py) (`CAFrame`), conectado en
[ui/ElectrochemicalFrame.py](../ui/ElectrochemicalFrame.py) como
"Chronoamperometry".

## 2. MethodSCRIPT generado

Builder: `construct_ca_script` en [Drivers/EmstatUtils.py](../Drivers/EmstatUtils.py)
(preview en el host) **duplicado byte a byte** en
[firmware/DiscPCB/EmstatDrivers.py](../firmware/DiscPCB/EmstatDrivers.py) (ejecución
en el Pico). Reusa `construct_header_experiment` igual que CV (modo 2; `da` fijado a
`E_dc`/`E_dc` porque el potencial es constante).

Ejemplo (`t_equilibrium=0`, `E_dc=0.5`, `t_interval=0.1`, `t_run=10`):

```
e
var i
var e
set_pgstat_chan 1
set_pgstat_mode 0
set_pgstat_chan 0
set_pgstat_mode 2
set_max_bandwidth 58505m
set_range_minmax da 500m 500m
set_range ba 470u
set_autoranging ba 470u 470u
set_e 500m
cell_on
meas_loop_ca e i 500m 100m 10100m
  pck_start
    pck_add e
    pck_add i
  pck_end
endloop
on_finished:
  cell_off
```

Con `t_equilibrium=3` se antepone un `meas_loop_ca` de equilibrio (intervalo FIJO
`200m`, duración exacta `3`), antes del loop principal:

```
...
cell_on
meas_loop_ca e i 500m 200m 3
  pck_start
    pck_add e
    pck_add i
  pck_end
endloop
meas_loop_ca e i 500m 100m 10100m
  ...
```

### 2.1 El `+t_interval` del loop principal

`meas_loop_ca <E> <i> <E_dc> <t_interval> <t_run_arg>` corre con `t` en
`[0, t_run_arg)` (semiabierto). Para capturar el punto en `t = t_run` exacto el host
pasa `t_run_arg = t_run + t_interval` (ej. `10 + 0.1 → 10100m`), de modo que el loop
emite `t_run/t_interval + 1` puntos (`t = 0 … t_run`). El loop de **equilibrio** usa
`t_run = t_equilibrium` **exacto** (sin el intervalo extra: es solo acondicionamiento).
La suma `t_run + t_interval` se hace en el host con `round(..., 9)` para que
`convert_si_integer_full` siempre encuentre un prefijo entero, y viaja en el payload
como `t_r` (el firmware solo la reenvía).

## 3. Eje de tiempo (sintetizado en el host)

Los paquetes de `meas_loop_ca` solo traen `e` (`da`) e `i` (`ba`): **no hay campo de
tiempo**. El eje `t` se sintetiza en el parser `"ca"` de `EmstatStreamParser`
([Drivers/EmstatUtils.py](../Drivers/EmstatUtils.py)):

```
t_s = índice_del_loop_principal × t_interval     (t = 0 en el escalón)
```

`t_interval` llega al parser vía `parser_kwargs={"ca_t_interval": ..., "ca_has_equil": ...}`
desde `CAFrame.send_script`. El plotter usa `x_key="t_s"`, `y_key="I_A"`.

### 3.1 Exclusión del loop de equilibrio

El equilibrio NO se grafica (`t=0` debe ser el escalón). Como sus paquetes son
idénticos a los del loop principal (`e`/`i`, mismo `E_dc`), el corte se detecta por el
marcador `*` de fin de `meas_loop`: cada `meas_loop` emite un `*` al terminar
(confirmado en el firmware, ver `run_experiment_read_loop`). Con `ca_has_equil=True` el
parser marca los paquetes como no-dato hasta ver el **primer** `*`; a partir de ahí los
paquetes son del loop principal y cuentan para `t_s`. Esto es más robusto que contar
`⌈t_equilibrium/0.2⌉` paquetes (inmune a la pérdida de un dato individual).

### 3.2 Tradeoff aceptado

Bajo pérdida de paquetes en el transporte seleccionado, el contador de índice puede
descuadrar el `t` **en vivo** (el contador avanza por paquete recibido, no por `seq`).
La unión por `seq` y el CSV final del transporte ganador quedan completos; la
imperfección es solo cosmética y en vivo. Decisión deliberada (síntesis en host en vez
de un `timer` en el firmware, que habría complicado el script con dos loops y `extra1`).

## 4. Payload y firmware

`CAFrame.generate_payload` ([ui/CaFrame.py](../ui/CaFrame.py)) → claves compactas
(estilo CV/SQWV):

| Clave | Valor |
|---|---|
| `method` | `"ca"` |
| `t_e` | `t_equilibrium` SI (`""` si 0) |
| `E_dc` | `E_dc` SI |
| `t_i` | `t_interval` SI |
| `t_r` | `t_run + t_interval` SI (ya combinado) |
| `m_b` | Max bandwidth SI |
| `min_da` / `max_da` | `E_dc` SI (potencial fijo) |
| `range_ba` / `ba_1` / `ba_2` | Current range SI |
| `ch` | canal de electrodo (int 0–7) |
| `max_time_s` | `(t_equilibrium + t_run) × 1.5 + 60` (tope absoluto del firmware) |
| `idle_s` | `max(t_interval, 200m si hay equilibrio) × 1.5 + 15` (watchdog de inactividad) |

Firmware: rama `"ca"` en `handle_command`
([firmware/DiscPCB/emstat_wifi_v1.9.py](../firmware/DiscPCB/emstat_wifi_v1.9.py)) →
`emstatpico.send_script(params, method="ca")` → `construct_ca_script`. Topes por
corrida como EIS: `max(max_time_s*1000, MAX_EXPERIMENT_MS)` y
`max(idle_s*1000, MAX_IDLE_MS)`. El canal se valida/activa igual que en los demás
métodos (`_activate_channel`); el firmware es el validador estricto del rango.

El watchdog del plotter (`CAFrame.send_script`) se fija a `idle_s + 15` para que el
terminal del firmware (`emstat_end`/`emstat_timeout`) siempre le gane al watchdog del
host.

## 5. Proyectos (recetas)

CA replica el patrón de recetas con `project_method = "ca"`
([ui/ElectrochemProjectBar.py](../ui/ElectrochemProjectBar.py),
[templates/electrochem_projects.py](../templates/electrochem_projects.py)): guarda
`t_equil`, `E_dc`, `t_interval`, `t_run`, `max_bw`, `current_range` en la sección
`"ca"` de `resources/electrochem_projects.json`, con snapshot `_last_run` al enviar y
auto-carga en cascada. El canal de electrodo NO se guarda (es hardware compartido).

## 6. Sin motor

CA no expone el bloque de motor del disco (a diferencia de CV): es una medida de
transitorio a potencial fijo con el electrodo quieto. `callback_spin_motor=None`,
igual que EIS/SQWV.

## 7. Pendiente

- **Flasheo del firmware v1.9**: el mirror `emstat_wifi_v1.9.py` tiene la rama `"ca"`,
  pero hay que copiar el original (`~/MicroPython/DiscPCB/`) a la placa y flashear; sin
  eso, un payload `"ca"` cae en `UNKNOWN_COMMAND` / `emstat_error`.
- **Validación end-to-end en hardware** (forma de los paquetes `e`/`i` de CA, marcador
  `*` entre loops, decaimiento de Cottrell esperado).
- **Automatizar Max bandwidth**: hoy es editable con default `58505m`; falta deducir
  cómo lo calcula PSTrace (¿de `t_interval`?) para fijarlo automáticamente.

__author__ = "Edisson A. Naula"
__date__ = "$ 24/06/2026 $"
