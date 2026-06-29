# Control de temperatura PCR: feed-forward + PI

Archivo modificado: `ui/PcrFrame.py` · `resources/settings.json`

Este documento describe cómo el cicladador alcanza cada setpoint de temperatura.
**Todas las rampas de subida** (desnaturalización y "Reach High temp") usan ahora
el **mismo** mecanismo: una pre-rampa *feed-forward* a potencia plena hasta una
fracción del setpoint, seguida de un lazo PI que asienta sin sobreimpulso. Ambas
comparten el método `_reach_temperature_pi`.

## 1. El problema

El heater es un actuador on/off (pin GPIO `led_heatin_pin`). No hay PWM analógico:
la "potencia" se modula encendiendo el pin una fracción `power ∈ [0,1]` de una
ventana `WINDOW` (PWM de software de ciclo lento). La temperatura llega por broadcast
UDP del Arduino del disco (~10 Hz), por lo que una lectura puede **envejecer** si el
feed se interrumpe.

Históricamente convivían dos formas de subir a un setpoint:

| Fase | Estrategia previa | Salida del lazo |
|------|-------------------|-----------------|
| Desnaturalización (`experiment_pcr`, inline) | blast a potencia plena hasta `0.80·sp`, luego **P-only** (`power = KP·error`), **sin** guarda de temperatura vieja durante el blast | salía al **primer cruce** `temp ≥ sp` |
| Reach High temp (`_reach_temperature_pi`) | **PI** con ganancias difusas + anti-windup desde el arranque | se asienta dentro de **±0.5 °C** |

El PI puro arrancaba "frío" sin aprovechar que el heater puede ir a fondo en la zona
lejana al setpoint; el blast de denat sí lo aprovechaba pero perdía la precisión del PI
y dejaba un riesgo de *runaway* (ver §2). La unificación toma lo mejor de ambos.

## 2. La solución: pre-rampa feed-forward configurable

`_reach_temperature_pi` ejecuta una **pre-rampa feed-forward** antes del lazo PI,
controlada por un parámetro por fase `ff_frac_<phase>` leído desde `settings.json`:

```
if FF_FRAC > 0 y NO break_if_below:
    ceiling = setpoint * FF_FRAC
    while temp < ceiling y no stop:
        si (now - temp_ts) > MAX_AGE:   # lectura vieja
            heater OFF; continue        # no confiar, reintentar
        heater ON                       # re-arma idempotente
# ...después: el lazo PI existente asienta hasta ±tolerancia
```

Tras la pre-rampa, **se mantiene el PI completo** (ganancias difusas, integral con
anti-windup, banda muerta `TEMP_BAND`) para asentar sin sobreimpulso. Es decir: se
aporta la **velocidad** del blast sin perder la **precisión** del PI.

### Guarda de temperatura vieja durante el blast

El blast revisa `MAX_AGE` en cada iteración: si la lectura UDP envejece, apaga el
heater y lo re-arma (idempotente, `write(True)`) cuando vuelve una lectura fresca. Esto
evita el *runaway* térmico que tenía el blast inline original de denat —que dejaba el
heater encendido sin chequear antigüedad—, ya que si `temp` se congelaba bajo el umbral
el heater quedaba **encendido indefinidamente**. Al compartir `_reach_temperature_pi`,
denat hereda esta guarda.

## 3. Interacción con `break_if_below`

La pre-rampa se **omite** cuando `break_if_below` es verdadero.

- **Reach High temp** se invoca con `break_if_below=(idx == 0)`. En el **ciclo 0**, la
  rampa ocurre justo tras el *hold* de denaturación, cuando `temp` ya está en el
  setpoint alto: el blast se omite para no recalentar (consistente con el `break`
  inmediato que el PI ya hacía). Para `idx > 0` el blast corre desde la temperatura de
  extensión/baja.
- **Desnaturalización** se invoca con `break_if_below=False`: parte de temperatura
  ambiente, muy por debajo del setpoint, así que el blast siempre corre.

## 4. Parámetros (`settings.json` → `pidControllerRPM`)

| Clave | Valor | Significado |
|-------|-------|-------------|
| `ff_frac_high` | `0.8` | Techo del blast como fracción del setpoint high. `0` = sin pre-rampa. |
| `ff_frac_denat` | `0.8` | Ídem para la rampa de desnaturalización. |
| `KP_high`, `KI_high`, `imax_high`, `tband_high`, `win_high`, `m_age_high` | — | Lazo PI de la fase high. |
| `KP_denat`, `KI_denat`, `imax_denat`, `tband_denat`, `win_denat`, `m_age_denat` | — | Lazo PI de la fase denat (las claves `KI/imax/tband` se añadieron para que denat use PI real, espejando los valores de high). |

`_load_phase_pid` devuelve `FF_FRAC = ff_frac_<phase>` con **default `0.0`**, por lo que
cualquier fase sin la clave (low, ext, …) conserva el comportamiento PI puro previo.
**Activar el blast en otra fase no requiere tocar Python**: basta añadir, p. ej.,
`ff_frac_ext` a `settings.json`.

> **Tuning pendiente:** `KI_denat/imax_denat/tband_denat` se inicializaron espejando high
> (`0.6 / 0.5 / 0.05`). Conviene una pasada de tuning en hardware, ya que denat parte de
> ambiente y su dinámica térmica difiere de la subida intra-ciclo de high.

## 5. Resumen de cambios en código

- `_load_phase_pid`: agrega `FF_FRAC` (`ff_frac_<phase>`, default `0.0`) al dict.
- `_reach_temperature_pi`: pre-rampa feed-forward guardada antes del lazo PI; omitida
  si `break_if_below` o `FF_FRAC == 0`.
- `_run_cycle` ("Reach High temp"): usa `_reach_temperature_pi` con el blast activo vía
  `ff_frac_high`; el heater se pre-arma con `pin_heating.write(True)` antes de la llamada.
- `experiment_pcr` (Denaturación): **se eliminó el lazo inline P-only**; ahora llama a
  `_reach_temperature_pi(denat_temp, _load_phase_pid("denat"), stop, break_if_below=False,
  tolerance=0.5)`. El heater se pre-arma antes de la llamada, igual que en high.
- `settings.json`: nuevas claves `ff_frac_high`, `ff_frac_denat`, y `KI/imax/tband_denat`.

## 6. Seguridad / invariantes

- El heater se **pre-arma** antes de llamar a `_reach_temperature_pi` (tanto en high como
  en denat); el blast lo re-arma de forma idempotente, así que un periodo de lecturas
  viejas no lo deja apagado de forma latente.
- Tanto el blast como el PI respetan `stop_event` (`stop_udp_listenner`): un Stop sale
  de ambos lazos. El `finally` de `experiment_pcr` apaga y cierra el pin en
  `_teardown_hardware`.
- El riesgo de *runaway* del blast inline de denat queda **cerrado** al compartir la
  guarda de `MAX_AGE`.
- No se introducen escrituras CSV nuevas; el flag `dev` no se ve afectado.

## 7. Omisión de fases con tiempo ≤ 0 (skip-on-zero)

Una fase cuyo campo de tiempo es `<= 0` se **omite por completo**: ni la rampa de
alcance ni el *hold*. El objetivo es no calentar/enfriar hacia un setpoint que luego
no se sostiene (p. ej. `Ext. Time = 0` ya no calienta inútilmente hacia `ext_temp`).

Helper único `_skip(t)` (módulo `ui/PcrFrame.py`): `True` si `float(t) <= 0` (o no
numérico). Se usa **idéntico** en ejecución y en la preview, para que el perfil
dibujado coincida con lo que realmente corre.

Fases omitibles y matices:

| Fase | Campo | Al omitir |
|------|-------|-----------|
| Denaturación | `denat_time` | Sin rampa ni hold. **Efecto colateral:** el primer ciclo arranca en frío, así que su "Reach High" usa `break_if_below=False` (ver abajo). |
| High | `time_high` | Sin rampa ni hold. |
| Low | `time_low` | Se omite el *hold*, pero el **enfriamiento por giro del motor se conserva**, apuntando al setpoint de la **siguiente fase activa** del ciclo (Extension) en vez de `low_temp`. |
| Extension | `ext_time` | Sin rampa ni hold. La lectura de fluorescencia **por ciclo sigue corriendo** (la medición nunca se salta). |
| Extensión final | `ext_time_final` | Se omite el *hold*, pero la **lectura de fluorescencia final SIEMPRE se realiza**. |

### Enfriamiento hacia la siguiente fase activa

El bloque de *cooling* en `_run_cycle` calcula `cool_target`:

```
cool_target = low_temp  si NO _skip(time_low)
              ext_temp  si _skip(time_low) y NO _skip(ext_time)
              None      si ambas se omiten   # nada que enfriar (la próxima fase calienta)
```

El giro solo corre si `cool_target is not None` y `self.temp > cool_target + 0.5`
(no se enfría si ya estamos por debajo). El `stop_func` del motor y el bucle de espera
posterior referencian `cool_target`, no `low_temp`. Alcance **mínimo y a prueba de
crashes** (no se persigue el objetivo a través de límites de ciclo): para combinaciones
extrañas el ciclo simplemente procede sin colgarse ni dejar el lazo varado.

### `break_if_below` y la desnaturalización omitida

`break_if_below=True` significa "si `temp < setpoint`, sal de inmediato sin calentar".
En el ciclo 0 esto era seguro **solo** porque se asumía llegar caliente del hold de
denaturación. Si `denat_time <= 0`, ese supuesto se rompe: el ciclo 0 arrancaría frío y
el "Reach High" saldría sin calentar. Por eso `experiment_pcr` calcula
`denat_skipped = _skip(denat_time)` y lo pasa a `_run_cycle`, que usa
`break_if_below=(idx == 0 and not denat_skipped)`. El "Reach Ext" del ciclo 0 mantiene
`break_if_below=(idx == 0)` (independiente de denat).

### Visibilidad

Silencioso en la UI (no se escribe un estado "skipped" transitorio en `svar_status`);
cada fase omitida solo emite un `print(...)` a consola para depuración. La **preview**
ya da confirmación visual previa al Start de que una fase se omite.

__author__ = "Edisson A. Naula"
