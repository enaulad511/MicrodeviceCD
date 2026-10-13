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
| `KP_ext`, `KI_ext`, `imax_ext`, `tband_ext`, `win_ext`, `m_age_min_ext`, `m_age_max_ext`, `ff_frac_ext` | `0.15`, `0.5`, `0.5`, `0.05`, `0.09`, `0.02`, `0.2`, `0.0` | Rampa PI de low → `ext_temp` en cada ciclo (`_run_cycle`, "Reach ext temp"). Distinta del *hold* (`*_h_ext`, que también usa la extensión final). |

`_load_phase_pid` devuelve `FF_FRAC = ff_frac_<phase>` con **default `0.0`**, por lo que
cualquier fase sin la clave conserva el comportamiento PI puro previo.
**Activar el blast en otra fase no requiere tocar Python**: basta añadir la clave
`ff_frac_<phase>` (o, en ext, subir `ff_frac_ext`) en `settings.json`.

> **Claves `*_ext` explícitas (13/10/2026):** hasta esta fecha la rampa hacia `ext_temp`
> no tenía ninguna clave en `settings.json` y corría con los *fallbacks* hardcodeados de
> `_load_phase_pid`. Se añadieron (también a `DEFAULT_SETTINGS`, para que el *seeder* las
> siembre en el `settings.json` local del Pi) con **exactamente esos valores**, así que el
> comportamiento no cambia; solo quedan editables. Única diferencia: `win_ext` antes era
> `ts_pcr·0.9` y ahora es un `0.09` fijo (idéntico con `ts_pcr=0.1`), igual que el `win_`
> explícito de las demás fases. No se añadió `m_age_ext`: `MAX_AGE` no lo consume nadie
> (ver §"Parámetros" de la edad máxima).
>
> **Supervivencia a la restauración de `update_repo`:** el paso de restauración copia el
> `settings.json` previo al update, que aún no tiene estas claves. Las devuelve
> `seed_default_settings` (solo agrega claves ausentes, nunca pisa valores locales), que
> ahora corre en dos sitios: al final de `update_repo` (paso 4, no fatal) y al arrancar
> `main.py`. Una vez en el archivo, el guardado del `ConfigFrame` las conserva: reconstruye
> `pidControllerRPM` entero a partir del propio archivo. Restaurar un *snapshot* viejo sí
> revierte un `*_ext` ya afinado a su default (lo mismo que cualquier otra clave).

> **Tuning pendiente:** `KI_denat/imax_denat/tband_denat` se inicializaron espejando high
> (`0.6 / 0.5 / 0.05`). Conviene una pasada de tuning en hardware, ya que denat parte de
> ambiente y su dinámica térmica difiere de la subida intra-ciclo de high.
> **Actualización 13/10/2026:** esa pasada se hizo en el equipo (`KP_denat 1.9`,
> `KI_denat 1.9`, `win_denat 0.1`, …). Desde ese día, `DEFAULT_SETTINGS` adopta las
> ganancias del equipo ([pcr_pendientes.md](pcr_pendientes.md) punto 11) y declara
> `KI_h_denat = 0.5` explícito, que es el *fallback* que ya regía.

> **Salvaguarda de tiempo (13/10/2026):** `_reach_temperature_pi` acepta un `deadline`
> que cubre la pre-rampa **y** el PI. Si vence, apaga el heater y devuelve `False`, y
> `_reach_phase` registra el timeout y deja pasar al *hold*. Sus ramas sin trabajo ahora
> duermen `PCR_POLL_S` (10 ms); antes giraban sin pausa. Ver
> [pcr_timeout_fases.md](pcr_timeout_fases.md).

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

## 8. `m_age` dinámico (fuzzy) durante la rampa

`MAX_AGE` es la edad máxima que una lectura UDP puede tener antes de que el lazo la
descarte y apague el heater (guarda anti-*runaway*, §2). Históricamente era un valor
estático por fase (`m_age_<phase>`). Ahora, **solo en la rampa** (`_reach_temperature_pi`),
se calcula de forma **difusa** en cada iteración a partir del error, reutilizando los
**mismos umbrales** que `_fuzzy_gains` para KP/KI:

```
_fuzzy_max_age(error, m_age_min, m_age_max):
    |e| >= 5°C   → m_age_max            (plano)   # rampa dura, tolera lecturas añejas
    2 <= |e| < 5 → interp m_age_min → m_age_max   # transición lineal
    |e| < 2°C    → m_age_min            (plano)   # cerca del setpoint, exige frescura
```

Monótona: **más error ⇒ más `m_age`**. La idea es que cuando estás lejos del setpoint
(blast / rampa dura) el heater no debe apagarse por una lectura ligeramente vieja; cerca
del setpoint sí conviene exigir frescura para no sobrepasar. Se aplica en **ambos** sitios
de la rampa: la pre-rampa *feed-forward* (el `error = setpoint - temp` se calcula ahí) y
el lazo PI (donde `error` se reordenó para computarse antes de la guarda).

El **hold** (`hold_temperature`) queda intacto: usa su propio umbral estricto (`ts`), no el
`m_age` difuso.

> **`ts` (`pidControllerRPM.ts_pcr`) es el periodo del lazo PI y el umbral de vejez del
> hold. NO es la cadencia de muestreo** — esa la fija el firmware del disco (`sample_ms`)
> y el host la mide por corrida. Confundirlas dejaba las tasas °C/s del análisis ~20 %
> bajas; ver [pcr_eje_tiempo.md](pcr_eje_tiempo.md).

> **Cortes y continuidad (corregido el 13/10/2026).** Los cortes efectivos son **5 °C y
> 2 °C**, ahora constantes compartidas (`FUZZY_FAR_C`, `FUZZY_NEAR_C`) entre
> `_fuzzy_gains` y `_fuzzy_max_age`.
>
> Historia del bug: el gain scheduling nació (`9c6f3f1`) con cortes 15/5 °C e
> interpolaciones continuas. Los cortes se movieron a 7/3 (`6a3587b`) y luego a 5/2
> (`c67e0d9`, `f708e4e`) **sin reescalar las `t`**. Resultado:
>
> - en 2–5 °C, `t` era negativa, y daba kp × 0.7–1.0 y ki × 1.24–1.0 en vez de
>   kp × 1.0→2.0 y ki × 1.0→0.2;
> - en 5 °C había un salto de kp × 1.0 → 2.0 y de ki × 1.0 → 0.2;
> - la zona fina interpolaba sobre 0–5 °C en vez de 0–2 °C.
>
> Ahora las `t` se escriben en función de las constantes y la curva es continua (salto
> < 1e-9 en ambos cortes). Tabla antes/después en
> [pcr_pendientes.md](pcr_pendientes.md) punto 10.

### Parámetros (`settings.json` → `pidControllerRPM`)

| Clave | Default | Significado |
|-------|---------|-------------|
| `m_age_min_<phase>` | `0.02` | Cota inferior de `m_age` (cerca del setpoint). |
| `m_age_max_<phase>` | `m_age_<phase>` si existe, si no `0.2` | Cota superior (rampa dura / blast). |
| `m_age_<phase>` | — | Clave estática antigua. **Ya no se usa como umbral directo** en la rampa; sobrevive solo como *fallback* de `m_age_max_<phase>`. |

`_load_phase_pid` devuelve `MAX_AGE_MIN`/`MAX_AGE_MAX`. Cualquier fase sin las claves nuevas
cae a `0.02`/`0.2` (`ext` las declara explícitas con esos mismos valores). Los límites son absolutos (no escalan el valor base),
acotados a `[m_age_min, m_age_max]` por construcción del interpolador.

## 9. Frescura relativa a la cadencia medida (13/10/2026)

### El problema: umbrales absolutos menores que la cadencia

Los umbrales de "lectura vieja" de §8 (`m_age_min/max`, 0.02–0.3 s) y el del *hold*
(`MAX_TEMP_AGE = ts_pcr` = 0.1 s) se fijaron pensando en lecturas cada 0.08 s. En la
corrida Newn1 llegaron **cada 0.30 s** (metadata `dt_mean: 0.3014`; la causa está en
[pcr_pendientes.md](pcr_pendientes.md) punto 1). Con umbrales menores que el periodo
de muestreo, después de cada ventana de control la lectura ya cuenta como vieja hasta que
llega la siguiente, y el heater queda **forzado a OFF**.

No es una protección: es una pérdida de potencia silenciosa. Medido corriendo
`hold_temperature` y `_reach_temperature_pi` reales, con las ganancias del equipo y
lecturas cada 0.3 s:

| caso | antes | con §9 | con dt = 0.08 s |
|---|:---:|:---:|:---:|
| *hold* `h_denat` 91.5 → 94 °C (el PI pide 100 %) | 31 % | **100 %** | 100 % |
| *hold* `h_high` 91.5 → 94 °C | 34 % | **100 %** | 100 % |
| *hold* `h_ext` 71.2 → 72 °C | 27 % | **93 %** | 94 % |
| rampa `ext` a 71.2 °C (atasco del ciclo 2) | 10 % | **36 %** | 36 % |
| rampa `ext` a 69 °C (atasco del ciclo 23) | 19 % | **64 %** | 64 % |

Lo que la rampa `ext` aún no entrega cerca de la banda (36 %) ya no es frescura: son sus
ganancias de *fallback* (punto 3 de los pendientes).

### La regla

```
umbral efectivo = max(umbral absoluto, min(fresh_age_cap_s, fresh_dt_factor × mediana(dt)))
```

- **Mediana de los últimos `PCR_CADENCE_WIN` = 15 periodos** entre lecturas **válidas**
  del primario. La calcula `_note_rx` en el hilo UDP, una vez por lectura (ordenar 15
  números a ~3 Hz). Los lazos solo leen el atributo `fresh_age_s`. Antes de
  `PCR_CADENCE_MIN_N` = 5 periodos medidos vale 0, y solo rigen los umbrales absolutos.
- **`fresh_dt_factor` = 1.5:** una lectura es confiable hasta que la siguiente llega 50 %
  tarde. Con Newn1 da 0.45 s. El jitter medido (p95 0.313 s contra mediana 0.307 s)
  queda muy dentro.
- **Los umbrales absolutos quedan como piso:** §8 sigue rigiendo cuando la cadencia es
  más rápida que ellos.
- Se reinicia por corrida en `init_temperature_graph`.

### Por qué no reabre el *runaway* (§2, §6)

La guarda anti-*runaway* protege contra un **stall** del feed UDP: segundos sin datos con
el heater encendido. La regla la conserva por construcción:

- **Mediana, no media:** un hueco aislado es un *outlier* que no la mueve (verificado: un
  hueco de 2 s dentro de la ventana deja el umbral en 0.450 s). Un stall real sigue
  apagando el heater en ~1.5 periodos: en simulación se apagó **0.45 s** después de la
  última lectura y no volvió a encender.
- **Solo una degradación sostenida** de la cadencia relaja el umbral, y nunca más allá de
  `fresh_age_cap_s` = 1.0 s. Más allá de eso ya es un stall, no una cadencia.
- **El watchdog de sensores** (`temp_stale_s` = 10 s) sigue por encima de todo.
- **Lecturas inválidas del primario** siguen fijando `temp_ts = 0.8`, es decir, vieja
  siempre. Y no alimentan la mediana.

### Configuración (`pidControllerRPM`)

| clave | default | significado |
|-------|:-------:|-------------|
| `fresh_dt_factor` | `1.5` | múltiplo de la cadencia medida. **`0` desactiva §9** (solo umbrales absolutos, comportamiento previo). |
| `fresh_age_cap_s` | `1.0` | tope del umbral derivado de la cadencia. |

Se leen una vez por corrida en `experiment_pcr`, junto a la salvaguarda de fases. La
metadata del CSV registra la config y el último umbral efectivo:
`-fresh: x1.5 cap 1s eff 0.451s` (`eff 0.000s` = nunca llegó a medirse cadencia).

__author__ = "Edisson A. Naula"
