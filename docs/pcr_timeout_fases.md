# Salvaguarda de tiempo por fase en el ciclado PCR

Archivos modificados: `ui/PcrFrame.py` · `resources/settings.json` · `templates/utils.py`

## 1. El problema

En experimentos reales hubo momentos en que el disco **no alcanzaba la temperatura** de
una rampa y el programa **se quedaba colgado** esperando. La causa era mecánica y
transitoria: según los datos del usuario, **en el ciclo siguiente se resolvía sola**.
Como un ciclo malo no arruina el proceso (la PCR tolera perder algunos ciclos), es
preferible **abandonar la fase y seguir** a quedarse esperando para siempre.

Hay cuatro esperas **sin límite de tiempo** (los *holds* no son el problema: terminan
por duración fija):

| fase | dónde | qué espera |
|------|-------|------------|
| `denat_ramp`, `high_ramp`, `ext_ramp` | `_reach_temperature_pi` | pre-rampa a potencia plena (`while temp < ceiling`) + PI (`while abs(sp − temp) > 0.5`) |
| `cooling` | `_run_cycle` | giro del motor hasta `target + 9.5 °C` y luego espera pasiva (`while temp > target + 0.5`) |

El caso que importa es el **calentamiento**. En `cooling` casi siempre se llega, y no
llegar solo pasaría con un objetivo inalcanzable por mala configuración de la receta.
Por eso ahí la salvaguarda es solo una red.

## 2. La regla

```
límite   = max(piso, factor × estimado)
estimado = |setpoint − temp al ENTRAR a la fase| × ramp_s_per_c    (rampas)
estimado = |temp al ENTRAR − objetivo| × cool_s_per_c               (cooling)
```

Si la fase supera su límite **se abandona y se pasa a la siguiente**:

- **Rampa → su *hold*.** El *hold* sigue empujando hacia el setpoint durante su propio
  tiempo, así que una rampa lenta no pierde del todo esa etapa. Al abandonar, el heater
  queda **apagado** (`_reach_temperature_pi` hace `write(False)` antes de devolver
  `False`) y el *hold* lo retoma.
- **`cooling` → `low_hold`** (o directo a `ext_ramp` si Low se omite). El
  `stop_func` del motor incluye el vencimiento, así que el disco frena y vuelve a cero
  como siempre.

Un solo reloj por fase: en las rampas cubre la pre-rampa **y** el PI; en `cooling`, el
giro **y** la espera pasiva.

### Por qué ΔT real y no el historial ni un fijo

Se discutieron tres bases (de la conversación de diseño):

- **(a) teórico por ΔT real (elegida).** Se usa la temperatura **medida al entrar**, no la
  nominal: si la fase anterior se abandonó y el disco quedó lejos, el plazo crece con el
  salto. No necesita historial y cuesta una resta y una multiplicación al entrar a la
  fase.
- **(b) mediana de ciclos previos:** no tiene dato en el ciclo 1, y se contamina justo
  en las corridas con fallos mecánicos, que son las que importan.
- **(c) segundos fijos por fase:** no escala con el salto de temperatura.

El **piso** cubre los saltos chicos: con ΔT = 3 °C, `3 × 0.6 s` sería absurdo, porque la
cola de asentamiento del PI a ±0.5 °C no escala con ΔT. Según el usuario, esa cola no es
grande, y la corrida real lo confirma (§7.1): 0.3 s de mediana. Con los defaults,
ext→high (70→94 °C) da `max(20, 3 × 4.8) = 20 s` y `cooling` 94→60 °C da
`max(20, 3 × 34) = 102 s`.

### El estimado del enfriamiento: medido, no el de la preview

La primera versión usaba para `cooling` la fórmula de la preview, `10000 / rpm`, que da
14.3 s a 700 rpm. Contra la corrida real (§7.1) **se queda 2.4× corta**. Esa fórmula solo
modela el giro, y la fase incluye además la cola **pasiva**: el motor para en
`objetivo + 9.5 °C` y de ahí a `objetivo + 0.5` baja solo, en unos 2/3 del tiempo total.
Con factor 3, el límite (42.9 s) quedaba a **7 %** del enfriamiento más lento medido
(39.9 s): en una corrida más larga o más caliente habría dado timeouts falsos. Ahora el
enfriamiento se estima igual que las rampas, por ΔT real, con
`cool_s_per_c = 1.0 s/°C` (medido: 1.02 de mediana, 1.19 de máximo), lo que deja un margen
de 2.5×. Desde el mismo día, la preview del perfil y la ETA previa al primer ciclo
también usan esta tasa (`_estimate_cycle_s` / `_estimate_total_s`), y `PCR_COOL_CONST`
desapareció. Ver [pcr_pendientes.md](pcr_pendientes.md) punto 6.

`ramp_s_per_c` es **la misma tasa que dibuja la preview del perfil** (antes un `0.2`
local en `callback_generate_profile`, ahora leído de settings,
[PcrFrame.py:847](../ui/PcrFrame.py#L847)): perfil dibujado y plazo salen del mismo
número. El 0.2 s/°C (≈ 5 °C/s) es coherente con las tasas de calentamiento **con
muestra**; en membrana seca el disco calienta más rápido y el plazo sobra.

## 3. Racha de ciclos fallidos

Un ciclo con **algún** timeout cuenta como fallido. Lo que se vigila es la **racha
consecutiva**, no el total ([PcrFrame.py:2036](../ui/PcrFrame.py#L2036)): un fallo
aislado es el caso mecánico que se arregla solo, mientras que varios seguidos indican
heater o motor muertos, y seguir solo gasta tiempo y muestra. Un ciclo limpio reinicia
la racha a 0.

Con `max_failed_cycles` ciclos fallidos **seguidos**, la corrida se aborta
([PcrFrame.py:2230](../ui/PcrFrame.py#L2230)) con el mismo apagado que el watchdog de
sensores: se activan los stop-events, la fase pasa a `aborted_timeouts`, no se hace la
extensión final y **el CSV se guarda igual**. Un timeout en `denat_ramp` (ciclo 0) se
registra, pero no cuenta para la racha: `_cycle_timeouts` se reinicia al empezar el
ciclo 1.

## 4. Configuración (`settings.json` → `pidControllerRPM`)

| clave | default | significado |
|-------|:-------:|-------------|
| `phase_timeout_factor` | `3.0` | múltiplo del estimado. **`0` desactiva la salvaguarda** (vuelve a esperar sin límite). |
| `phase_timeout_floor_s` | `20.0` | límite mínimo en segundos. |
| `ramp_s_per_c` | `0.2` | s/°C del estimado de calentamiento (y de la preview). |
| `cool_s_per_c` | `1.0` | s/°C del estimado de enfriamiento (giro + cola pasiva, medido en §7.1). |
| `max_failed_cycles` | `3` | racha de ciclos fallidos que aborta. **`0` = nunca abortar.** |

Están también en `DEFAULT_SETTINGS`, así que el *seeder* las agrega tras un update que
restaura el `settings.json` local (ver [pcr_temperature_control.md](pcr_temperature_control.md)
§4). Se leen **una vez por corrida** en `experiment_pcr`
([PcrFrame.py:2085](../ui/PcrFrame.py#L2085)), validadas por `_phase_timeout_cfg`
([PcrFrame.py:132](../ui/PcrFrame.py#L132)): un valor no numérico o negativo cae a su
default.

## 5. Qué queda registrado

- **Label de estado:** la línea `State` agrega
  `⚠ N phase timeout(s), last: <fase> (cycle k)` durante el resto de la corrida.
- **Consola:** `Phase timeout: high_ramp (cycle 7) 21.3s > 20.0s at 88.4 °C (target 95 °C) — skipping to next phase`.
- **Metadata del CSV de temperatura** (`_timeouts_summary`,
  [PcrFrame.py:1448](../ui/PcrFrame.py#L1448)): la config efectiva, los ciclos
  fallidos y **cada evento con su duración, su límite y la temperatura alcanzada vs. el
  objetivo**:
  `-timeout_cfg: x3 floor 20s 0.2s/C max_failed 3-failed_cycles: 7-timeouts: c7 high_ramp 21.3/20.0s 88.4/95C`.
  Archivar el límite junto a lo que de verdad tardó permite reajustar factor y piso con
  datos.
- **CSV de fotodetector por ciclo:** gana una segunda columna `timeouts`
  (`high_ramp|cooling`; vacía = ciclo limpio) ([PcrFrame.py:1513](../ui/PcrFrame.py#L1513)).
  La fila *k* es la lectura del ciclo *k*, así que excluir las lecturas de ciclos
  fallidos es un filtro directo. El loader del análisis lee solo la columna 0.
- **Columna `phase` del CSV de temperatura** ([pcr_csv_ciclo_fase.md](pcr_csv_ciclo_fase.md)):
  una rampa abandonada se ve como un `high_ramp` que termina sin llegar y da paso al
  `high_hold`.

## 6. Carga computacional

El chequeo es una comparación `time.time() > deadline` por vuelta de un lazo que ya
existía; el estimado se calcula una vez por fase.

Además, este cambio **bajó** la carga: los lazos de espera giraban sin pausa. La pre-rampa
hacía `pin_heating.write(True)` en un lazo sin `sleep` durante todo el blast, y las ramas
de "temperatura vieja" de la pre-rampa y del PI hacían `continue` sin dormir: un núcleo
al 100 % en cada rampa. Ahora esas ramas duermen `PCR_POLL_S = 10 ms`. La temperatura
llega cada ~80 ms, así que la reacción no cambia (en simulación, ~100 writes/s al pin en
vez de un lazo libre). La espera pasiva del `cooling` pasó de sondear cada 1 ms a cada
10 ms por la misma razón.

## 7. Verificación

Sin hardware, con un harness que llama a los métodos reales de `PCRFrame` sobre un
objeto falso (pin simulado, motor stub, planta que sigue o congela la temperatura):

- PI atascado → abandona en el límite, con el heater apagado.
- Blast atascado bajo el techo → abandona desde la pre-rampa.
- La planta llega → sin timeout.
- `factor = 0` → espera hasta Stop, sin registrar timeout.
- Patrón de ciclos falla/ok/falla/falla/falla → la racha vuelve a 0 en el ciclo sano y
  aborta tras el quinto; la metadata y la columna `timeouts` coinciden con los eventos.

### 7.1 Contra una corrida real (offline)

`Newn1_temperature_data_20261013_143040.csv`: 35 ciclos, 94/60 °C, 15/15 s, 700 rpm,
desnaturalización 94 °C × 120 s, termopar. La extensión (72 °C, 6 s) no está en la
metadata de ese CSV y se deduce de los datos: el valle previo a cada subida cae siempre
9.5 s después de llegar a 71.5 °C, es decir 6 s de *hold* + 3.5 s de lectura. No hay
huecos de muestreo > 1 s (dt de 0.31 s).

Se segmentó **sobre la misma señal que ve el PID** (la columna 0 del CSV es el EMA del
host), con los conceptos de
[analisis_temp_paper.ipynb](../analisis_temp_paper.ipynb): pendiente LSQ desde el ancla
de 73 °C hasta el 85 % del recorrido (§5), transición 10–90 % contra la cola de
aproximación (§7c), y ciclo útil = alcanza `HI − 2` y `LO + 2` sostenido ≥ 1 s (§7d).
Ciclos 2–34 (el 1 es especial por `break_if_below`; del 35 sigue la extensión final):

| fase (entrada → banda ±0.5) | mediana | máx. normal | medido / estimado (máx.) | límite |
|---|---|---|---|---|
| `high_ramp` (ΔT ≈ 24 °C) | 5.5 s | 7.4 s | ×1.59 | 20 s (piso) |
| `ext_ramp` (ΔT ≈ 12 °C) | 4.3 s | 7.1 s | ×2.4 (sin atascos) | 20 s (piso) |
| `cooling` (ΔT ≈ 33.5 °C) | 34.4 s | 39.9 s | ×1.19 con 1.0 s/°C (×2.8 con `10000/rpm`) | 102 s |

- **Anatomía de la subida:** 5.1 °C/s de tasa LSQ (coherente con 4–6 °C/s con muestra),
  transición 10–90 % de 4.0 s y **cola 90 % → banda de 0.3 s de mediana (máx. 0.9 s)**.
  Es decir, la cola de asentamiento es despreciable, como dijo el usuario, y en las
  rampas manda el piso.
- **Dos atascos reales, los dos en `ext_ramp`:**
  - **Ciclo 2:** 42.7 s plano en 71.0–71.3 °C, de 0.2 a 0.5 °C por debajo de la banda.
  - **Ciclo 23:** 67.9 s plano en ~69 °C, tras un sobre-enfriamiento a 57 °C.

  En ambos el ciclo siguiente volvió a la normalidad. Con la salvaguarda se habrían
  cortado a los 20 s, **ahorrando 23 s y 48 s**, sin ningún corte falso en el resto.
- **§7d:** los 33 ciclos medidos son útiles, y el *hold* de extensión promedia
  72.0 °C (71.85–72.21).

**Pendiente:** correr en el equipo con la salvaguarda activa y revisar los eventos
`-timeouts:` en la metadata.

## 8. Lo que NO se hizo, y por qué

- **Sin estimado adaptativo** (§2, opción b).
- **Los *holds* no tienen salvaguarda:** ya terminan por tiempo.
- **No se reintenta la fase:** el siguiente ciclo **es** el reintento, y es lo que según
  los datos arregla el problema.
- **La pestaña de análisis no usa todavía la columna `timeouts`.**

### Observación (resuelta el 13/10/2026)

`ext_ramp` se llamaba con `break_if_below=(idx == 0)`. En el **primer** ciclo, viniendo
de low (por debajo de ext), eso hacía que la rampa saliera de inmediato y el `ext_hold`
calentara por su cuenta. Era una copia de `high_ramp`, donde sí tiene sentido porque se
viene del *hold* de denaturación ya caliente, y estaba desde antes del refactor de mayo.
Por decisión del usuario, ahora el ciclo 1 rampea a ext como los demás, con salvaguarda
([pcr_pendientes.md](pcr_pendientes.md) punto 4).

## Archivos

- [ui/PcrFrame.py](../ui/PcrFrame.py):
  - Constantes `PCR_TIMEOUT_*`, `PCR_RAMP_S_PER_C`, `PCR_COOL_S_PER_C`,
    `PCR_MAX_FAILED_CYCLES`, `PCR_POLL_S`, más `_phase_timeout_cfg`.
  - Métodos `_phase_deadline`, `_record_timeout` y `_reach_phase`
    ([PcrFrame.py:1697-1745](../ui/PcrFrame.py#L1697-L1745)), y el `deadline` de
    `_reach_temperature_pi`.
  - El reloj del cooling ([PcrFrame.py:1964](../ui/PcrFrame.py#L1964)), la racha, el
    aborto y el resumen en metadata.
- [resources/settings.json](../resources/settings.json) y
  [templates/utils.py](../templates/utils.py): las cuatro claves.
- Docs relacionados:
  - [pcr_temperature_control.md](pcr_temperature_control.md): rampas FF+PI.
  - [pcr_csv_ciclo_fase.md](pcr_csv_ciclo_fase.md): columnas `cycle`/`phase` y el
    código `aborted_timeouts`.
  - [temp_source_selector.md](temp_source_selector.md): watchdog de sensores, el otro
    aborto.

__author__ = "Edisson A. Naula"
