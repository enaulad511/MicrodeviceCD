# Pendientes del control térmico PCR (tras la corrida Newn1)

Lista de trabajo abierta el 13/10/2026 al validar la salvaguarda de fases
([pcr_timeout_fases.md](pcr_timeout_fases.md)) contra la corrida real
`Newn1_temperature_data_20261013_143040.csv` (35 ciclos, 94/60 °C, 15/15 s, ext deducida
72 °C × 6 s, 700 rpm, termopar). Cada punto separa **lo que muestran los datos** de **lo
que se deduce** y dice si depende del `settings.json` del Pi. Ese archivo es el que manda
en el equipo: el `update_repo` conserva el local ("local siempre gana") y puede diferir de
los defaults del repo.

| # | pendiente | prioridad | ¿necesita el settings del Pi? | estado |
|:-:|-----------|:---------:|:-----------------------------:|--------|
| 1 | Cadencia de temperatura 0.30 s vs. umbrales de frescura del control | **alta** | sí (revisado) | **(B) hecho** (frescura relativa a la cadencia); (A) causa de los 0.3 s: diagnóstico listo, falta correrlo en el equipo |
| 2 | Hold de desnaturalización 2.5 °C por debajo del setpoint | alta | sí (revisado) | probablemente consecuencia del 1 |
| 3 | Causa de los atascos de `ext_ramp` | media | sí (revisado) | **decidido: no re-afinar** hasta ver una corrida con (B); mitigado por la salvaguarda |
| 4 | `ext_ramp` con `break_if_below` en el ciclo 1 | media | no | **hecho** (quitado por decisión del usuario) |
| 5 | `ext_temp`/`ext_time` ausentes de la metadata del CSV | baja | no | **hecho** |
| 6 | Preview y ETA subestiman el enfriamiento | baja | no | **hecho** |
| 7 | Validación en equipo de los cambios del 13/10 | alta | — | abierto |
| 8 | La pestaña de análisis aún no usa `cycle`/`phase`/`timeouts` | baja | no | abierto |
| 9 | `PCR_TEMP_START_WAIT_S` sigue hardcodeado | baja | no | **hecho** (`temp_start_wait_s`) |
| 10 | Zona intermedia de `_fuzzy_gains` (2–5 °C) no hace lo que dice su comentario | baja | no | **hecho** (corregido, continua) |
| 11 | `DEFAULT_SETTINGS` del repo desfasado del equipo | baja | sí (revisado) | **hecho** (defaults = equipo) |

## 0. Qué revisar en cuanto llegue el `settings.json` del Pi

Bloque `pidControllerRPM`:

- **`ts_pcr`:** fija el umbral de frescura de los *holds* (punto 1).
- **`m_age_min_*` / `m_age_max_*`** de `denat`, `high` y `ext`: umbrales de frescura de
  las rampas (punto 1).
- **`KI_h_denat`:** en el repo **no existe** y cae al default 0.5 (punto 2). Revisar
  también `KP_h_denat`, `imax_h_denat` y `tband_h_denat`.
- **`KP/KI/imax/tband_ext` y `*_h_ext`:** punto 3.
- **Si ya tiene las claves sembradas** (`temp_stale_s`, `phase_timeout_*`,
  `ramp_s_per_c`, `cool_s_per_c`, `max_failed_cycles`, `*_ext`): aparecen después del
  primer arranque de la app con el código nuevo, o del paso 4 de `update_repo`.
- **Cualquier valor afinado a mano** que difiera de `DEFAULT_SETTINGS`
  ([templates/utils.py](../templates/utils.py)).

### 0.1 Resultado (13/10/2026, `files_test/settings_device.json`)

Se asume que Newn1 corrió con este mismo archivo, porque se trajo el mismo día.

- **`ts_pcr = 0.1`:** igual que el repo. El umbral de frescura de los *holds* es 0.1 s.
- **`m_age_*`:** denat 0.02 / 0.2; high 0.02 / **0.3**. **ext no tiene ninguna** (cae a
  0.02 / 0.2).
- **`KI_h_denat`:** **tampoco existe en el equipo** (→ 0.5). En cambio
  `KP_h_denat = 1.2` en el equipo, contra 0.2 en el repo.
- **Rampa a ext (`KP/KI/imax/tband/win/ff_frac_ext`): nunca existió en el equipo.**
  Siempre corrió con los *fallbacks* (KP 0.15, KI 0.5, imax 0.5), mientras que el *hold*
  de ext **sí** está afinado: `KP_h_ext 0.5`, `KI_h_ext 1.3`, `win_h_ext 0.02`.
- **Sin sembrar todavía:** los `*_ext` de rampa, `temp_stale_s`, `phase_timeout_*`,
  `ramp_s_per_c`, `cool_s_per_c` y `max_failed_cycles`. Aparecerán con los valores del
  repo tras el update.
- **Valores del equipo distintos del repo** (punto 11): KP/KI/win/m_age de denat,
  `KP_h_denat`, `KI_high 1.9`, `m_age_high 0.2`, `m_age_max_high 0.3`, `tband_high 0.1`,
  `KI_h_high 1.3`, `tband_h_high 0.02`, `KP/win/KI_h_ext`.

## 1. Cadencia de temperatura 0.30 s vs. umbrales de frescura del control

**Datos.** La metadata de Newn1 dice `dt_mean: 0.3014-dt_p95: 0.3130-dt_max: 0.9226`: llegó
una temperatura cada ~0.3 s, de forma regular. El *mirror* del firmware del disco
([firmware/DiscPCB/emstat_wifi_v1.9.py:284](../firmware/DiscPCB/emstat_wifi_v1.9.py#L284))
declara `sample_ms = 80`, y [pcr_eje_tiempo.md](pcr_eje_tiempo.md) documenta 0.08 s.

**Código.** `temp_ts` es el instante de **recepción** de la última lectura válida
([PcrFrame.py:1117](../ui/PcrFrame.py#L1117)), y el control apaga el heater cuando esa
lectura es más vieja que:

- en los *holds*, `MAX_TEMP_AGE = ts` = `ts_pcr` = **0.1 s**
  ([PcrFrame.py:1644](../ui/PcrFrame.py#L1644));
- en las rampas, `_fuzzy_max_age` ([PcrFrame.py:218](../ui/PcrFrame.py#L218)):
  **0.02 s** a menos de 2 °C del setpoint, interpolando hasta **0.2 s** a 5 °C o más.

**Deducción (no verificada).** Si las lecturas llegan cada 0.3 s, después de cada ventana
de control (~0.09 s) la temperatura ya cuenta como "vieja" hasta la siguiente muestra, y
el heater queda forzado a OFF. La potencia efectiva tiene entonces un techo de
≈ 0.09 / 0.3 ≈ **30 %** de lo que pide el PI, justo en los *holds* y en la aproximación
final al setpoint. Eso es coherente con dos cosas que se vieron en la corrida:

- el *hold* de desnaturalización no alcanzó el setpoint (punto 2);
- el atasco del ciclo 2 quedó **plano a 0.2–0.5 °C de la banda** (punto 3).

No lo prueba: el usuario atribuye los atascos a causas mecánicas, y ambas cosas pueden
coexistir.

**Confirmado en simulación del código (no en hardware).** Se corrieron
`hold_temperature` y `_reach_temperature_pi` reales con la temperatura fija, `temp_ts`
renovado cada `dt` y las ganancias del settings del equipo (§0.1). Se midió la fracción
de tiempo real con el heater encendido:

| caso | duty con dt = 0.30 s (Newn1) | duty con dt = 0.08 s (diseño) |
|---|:---:|:---:|
| *hold* `h_denat`, 91.5 → 94 °C (el PI pide 100 %) | **35 %** | 100 % |
| *hold* `h_high`, 91.5 → 94 °C | 37 % | 100 % |
| *hold* `h_ext`, 71.2 → 72 °C | 32 % | 94 % |
| rampa `ext` a 71.2 °C (atasco del ciclo 2) | **10 %** | 27 % |
| rampa `ext` a 69 °C (atasco del ciclo 23) | **20 %** | 65 % |
| rampa `ext` a 63 °C (tramo normal, lejos del setpoint) | 91 % | 100 % |

Con la cadencia de Newn1, **los *holds* y la aproximación final reciben ~1/3 de la
potencia que pide el PI**. Lejos del setpoint casi no se nota, porque `m_age_max` (0.2 s)
cubre casi un periodo de muestreo. Por eso las rampas siguen siendo rápidas y el problema
solo aparece al asentarse.

**Opciones (decisión pendiente del usuario):**

- **(A) Recuperar la cadencia de 0.08 s.** Hay que encontrar primero por qué es 0.3 s,
  con el paso 1 de abajo. Devuelve todo al diseño y también afecta al análisis
  ([pcr_eje_tiempo.md](pcr_eje_tiempo.md)).
- **(B) Umbrales de frescura relativos a la cadencia medida.** Por ejemplo,
  `max_age ≥ k × dt` con k ≈ 1.5. El control dejaría de perder potencia en silencio si la
  cadencia se degrada otra vez. Sigue protegiendo contra un stall real del UDP: 0.45 s es
  mucho menos que el watchdog de 10 s. Toca la lógica anti-*runaway*
  ([pcr_temperature_control.md](pcr_temperature_control.md)).
- No son excluyentes: (A) arregla esta causa y (B) blinda contra la siguiente.

**Decisión (13/10/2026): ambas.**

**(B) hecho.** Ver [pcr_temperature_control.md](pcr_temperature_control.md) §9, y
`_note_rx` / `fresh_dt_factor` / `fresh_age_cap_s`. Resultado en la misma simulación:

- *holds* de 31–34 % a **100 %**;
- rampa `ext` cerca de la banda de 10 % a **36 %**, igual que con dt = 0.08 s;
- un stall real apaga el heater a los 0.45 s.

**Pendiente:** validarlo en una corrida real. Con la columna `phase` se puede comparar
el nivel de los *holds* contra Newn1.

**(A) diagnóstico listo**, falta correrlo en el equipo:
[test/test_udp_cadence.py](../test/test_udp_cadence.py) (gitignored, como todo `test/`).
Escucha UDP:5005 con un buffer de 1 MB y sin trabajo por datagrama, y reporta la mediana,
el p95 y el máximo de dt cada 10 s. El disco transmite siempre (`measuring = True` por
defecto), así que no hace falta la app:

1. **Con la app cerrada**, en el Pi: `python test/test_udp_cadence.py`.
   - dt ≈ 0.08 s → el disco emite bien y el cuello está en la recepción de la app
     (`SO_RCVBUF` de 512 B en `ClientUDP`, o el hilo receptor sin turno de CPU).
   - dt ≈ 0.30 s → el cuello está antes del Pi: el lazo del Pico, el UART a 230400 o el
     reenvío del Wemos. En el código del firmware no hay ningún retardo de 300 ms a la
     vista: leer los tres sensores y enviar por UART son milisegundos.
2. **Con la app corriendo un PCR**, en paralelo (ambos sockets usan `SO_REUSEADDR` y
   reciben el broadcast): comparar con el `dt_mean` de la metadata de esa corrida.

Nota: antes del 13/10, la pre-rampa y las ramas de "lectura vieja" giraban sin `sleep`
([pcr_timeout_fases.md](pcr_timeout_fases.md) §6). Un núcleo al 100 % compite por el GIL
con el hilo receptor. Si el paso 1 da 0.08 s, conviene repetir una corrida con el código
nuevo antes de tocar `ClientUDP`: podría haberse arreglado solo.

**Por hacer:**

1. Averiguar **por qué la cadencia es 0.3 s y no 0.08 s**. Puede ser el lazo del firmware
   (tres sensores, reintento del MLX: ver
   [mlx90614_fiabilidad_lectura.md](mlx90614_fiabilidad_lectura.md)) o la recepción en el
   Pi (`SO_RCVBUF` de 512 bytes en `ClientUDP` descarta datagramas a propósito). Prueba:
   capturar el UDP en el Pi con un script de `test/`, y contrastar con lo que el disco
   imprime por serial.
2. Con el settings del Pi, revisar `ts_pcr` y los `m_age_*` reales.
3. Decidir si los umbrales de frescura deben ser **relativos a la cadencia medida** (p. ej.
   ≥ 1.5 × dt) en vez de absolutos. Es decisión de diseño: hay que releer
   [pcr_temperature_control.md](pcr_temperature_control.md), donde está el porqué del
   descarte de lecturas viejas (evitar *runaway* térmico).

## 2. Hold de desnaturalización por debajo del setpoint

**Datos.** En el *hold* inicial (22–142 s) la temperatura promedió **91.55 °C** (mediana
91.46, rango 90.2–93.9) contra un setpoint de 94 °C, y solo **16 de 120 s** estuvo por
encima de 92 °C. El *hold* de high, con otras ganancias, sí se sostiene en 93–95 °C.

**Código.** `_hold_phase("h_denat", …)` ([PcrFrame.py:2210](../ui/PcrFrame.py#L2210))
lee `KI_h_denat`, que en el `settings.json` del repo **no existe**, así que cae al default
0.5 de `_load_phase_pid` ([PcrFrame.py:1691](../ui/PcrFrame.py#L1691)). Los presentes son
`KP_h_denat 0.2`, `imax_h_denat 0.55`, `tband_h_denat 0.05` y `win_h_denat 0.09`.

**Revisado con el settings del equipo.** `KI_h_denat` tampoco existe allá (→ 0.5), pero
`KP_h_denat = 1.2`. Con 2.5 °C de error, `_fuzzy_gains` da `kp ≈ 0.9`, el término P solo
ya vale 2.25 y **el PI pide 100 %**. El cuello no son las ganancias, sino el punto 1: con
dt = 0.3 s el heater entrega **35 %**.

El *hold* de high del ciclo 1, con un techo similar (37 %), sí llevó el disco de 91.5 a
94 °C en ~5 s a los 142 s. Lo coherente con los datos es que ~1/3 de potencia no alcanza
en los **primeros minutos**, con la masa térmica aún fría, y sí alcanza cuando ya está
caliente. Es una deducción.

**Por hacer:**

- Resolver el punto 1 y repetir una corrida.
- Si el *hold* sigue corto con la potencia completa, revisar ganancias, incluido añadir
  `KI_h_denat`.

## 3. Causa de los atascos de `ext_ramp`

**Datos** ([pcr_timeout_fases.md](pcr_timeout_fases.md) §7.1): 2 de 33 rampas a
extensión se atascaron. En ambos casos el ciclo siguiente volvió a la normalidad (rampa
típica de 4.3 s).

- **Ciclo 2:** 42.7 s plano en 71.0–71.3 °C, de 0.2 a 0.5 °C por debajo de la banda.
- **Ciclo 23:** 67.9 s plano en ~69 °C, tras un sobre-enfriamiento a 57 °C.

**Mitigado:** la salvaguarda los corta a los 20 s.

**Abierto: la causa.** Hay tres candidatas, no excluyentes:

- mecánica (lo que observa el usuario);
- el techo de potencia del punto 1;
- el tope del integrador (`imax_ext 0.5`): la rampa a ext **no tiene blast**
  (`ff_frac_ext 0`) y llega solo con el PI.

Con la columna `phase` de las corridas nuevas
([pcr_csv_ciclo_fase.md](pcr_csv_ciclo_fase.md)) un atasco se aísla sin reconstruirlo a
ojo.

**Revisado con el settings del equipo: mecanismo candidato.** Hasta hoy, las claves de la
**rampa** a ext no existían en el equipo, así que siempre corrió con los *fallbacks*
débiles: KP 0.15, KI 0.5, imax 0.5 y sin blast. El *hold* de ext, en cambio, sí se afinó
(KP 0.5, KI 1.3). Cerca de la banda, la rampa pide poco: con imax 0.5 el integrador
satura en ~0.3 de potencia. Además el punto 1 le recorta ~2/3. Medido en simulación del
código (tabla del punto 1):

- a 71.2 °C entrega **10 %** de duty;
- a 69 °C, **20 %**.

Si esa potencia no alcanza para sostener ~71–72 °C, la rampa queda en **equilibrio por
debajo de la banda**, que es la firma exacta del ciclo 2 (plano a 0.2–0.5 °C) y del 23
(plano a ~69 °C, con el disco más frío tras el sobre-enfriamiento a 57 °C). Las rampas
normales llegan porque entran a la banda con la inercia del tramo rápido (91 % de duty
lejos del setpoint). Es compatible con la explicación mecánica: un disco con peor
contacto pide más potencia, y el equilibrio cae más abajo.

**Predicción con (B) del punto 1 (deducción, comprobable en la próxima corrida).**

- **Pérdida térmica estimada:** el *hold* de denaturación de Newn1 se equilibró en
  91.5 °C con ~1/3 de duty (el PI pedía 100 % y le llegaba ~33 %). Con pérdidas
  newtonianas proporcionales a `T − T_amb` (T_amb ≈ 25 °C, supuesto), sostener ~71.5 °C
  pediría ≈ 33 % × 46.5 / 66.5 ≈ **23 %** de duty.
- **Antes de (B):** la rampa entregaba 10 % a 71.2 °C y 19 % a 69 °C, ambos por debajo
  de ~23 %. El modelo predice exactamente los dos atascos.
- **Con (B):** entrega 36 % y 64 %, ambos por encima. **Los atascos de `ext_ramp`
  deberían desaparecer sin re-afinar ganancias.**
- **Por qué el margen es real:** ese 33 % se midió con la masa todavía fría (primeros
  minutos), así que en régimen la pérdida es menor y el margen, mayor.

**Por hacer:**

- Correr con (B) y revisar la duración de `ext_ramp` (columna `phase`) y los eventos
  `-timeouts:`.
- **Solo si los atascos siguen**, afinar los `*_ext` de rampa en el equipo, que existen
  desde el 13/10: acercar `KI_ext`/`imax_ext` a los del *hold* o activar `ff_frac_ext`.
  Afinar ahora, sin la corrida, sería tocar dos variables a la vez.
- **Decidido (13/10/2026):** se sigue esta recomendación, sin re-afinar todavía. Con el
  fuzzy corregido (punto 10), la rampa a 69 °C ya entrega 78 % en simulación: más margen
  aún.

## 4. `ext_ramp` con `break_if_below` en el ciclo 1

**Código.** `_reach_phase("ext_ramp", …, break_if_below=(idx == 0))`, en `_run_cycle`.
Viniendo de low, siempre por debajo de ext, en el **primer** ciclo la rampa sale de
inmediato y el `ext_hold` calienta por su cuenta.

**Datos.** En Newn1, la extensión del ciclo 1 (195–205 s) sube sin rampa.

**Historia (git).** Es **anterior** al refactor a `_run_cycle` (`a66b4c0`, 2026-05-08).
El lazo inline original de la rampa a ext ya tenía
`if current_cycle == 0 and self.temp < exts_temp: break`, idéntico al de la rampa a
high. Luego `78f6f95` (2026-06-29) refinó **solo** el de high con `denat_skipped`. Así que
lleva meses en todas las corridas, incluidas las del paper si usaron este código.

**Deducción.** Parece copiado de `high_ramp`, donde sí tiene sentido: ahí se viene del
*hold* de denaturación, ya caliente.

**Hecho (13/10/2026), por decisión del usuario.** `break_if_below=False` en `ext_ramp`.
El ciclo 1 rampea a ext como los demás, con salvaguarda, y su extensión deja de diferir
del resto. Ojo al comparar con corridas anteriores: su ciclo 1 tiene la extensión sin
rampa.

## 5. Extensión ausente de la metadata del CSV — **hecho (13/10/2026)**

El prefijo guardaba high, low, tiempos, ciclos, rpm, denat y ts, pero no la extensión.
Para Newn1 hubo que deducir 72 °C × 6 s de la curva: el valle previo a cada subida cae
siempre 9.5 s después de llegar a 71.5 °C.

**Ahora** el prefijo agrega `-ext_temp: …-ext_time: …-ext_time_final: …-initial_spin: …`
antes de `-ts:`. Nadie parsea la metadata (el loader del análisis la salta), así que es
seguro.

## 6. Preview y ETA subestiman el enfriamiento — **hecho (13/10/2026)**

**Antes:**

- La preview dibujaba el enfriamiento como `10000 / rpm`: 14.3 s a 700 rpm, contra 34 s
  reales (2.4× corta).
- La ETA previa al primer ciclo (`teorical_time_pcr`) era `holds × 1.2`: ignoraba
  rampas y enfriamiento.

**Ahora** un solo modelo, en `_estimate_cycle_s` / `_estimate_total_s` (módulo de
`PcrFrame.py`): rampas y enfriamiento por ΔT con `ramp_s_per_c` / `cool_s_per_c`, las
mismas reglas de omisión que `_run_cycle`, y la lectura de fluorescencia incluida. Lo
usan tres sitios: la preview (tramo de enfriamiento y tope de recorte), la ETA inicial y,
con las mismas tasas, la salvaguarda de fases. `PCR_COOL_CONST` desapareció. Contra
Newn1:

| | antes | ahora | real |
|---|:---:|:---:|:---:|
| ciclo | — | 80.3 s | 83.8 s (mediana) |
| enfriamiento dibujado | 14.3 s | 34.0 s | 34.4 s |
| duración total (ETA) | 1878 s (−43 %) | 3079 s (−6 %) | 3269 s |

(`initial_spin` ≈ 10 s y `ext_time_final` ≈ 120 s se leyeron de la curva, porque Newn1 es
anterior al punto 5.) El RPM de la receta se sigue validando en la preview, pero ya no
entra en el estimado.

## 7. Validación en equipo de los cambios del 13/10

Checklist para la próxima corrida real:

- [ ] El `settings.json` del Pi tiene las claves nuevas (punto 0).
- [ ] La consola imprime `Temp watchdog window: 10.0 s` y `Phase timeout config: …`.
- [ ] El CSV de temperatura trae columnas `cycle`/`phase` coherentes con la curva, y
      `cols: …|t_s|cycle|phase`.
- [ ] La metadata trae `-timeout_cfg: …-failed_cycles: …-timeouts: …-fresh: x1.5 cap 1s eff …`.
      Con la cadencia de Newn1, `eff` ≈ 0.45 s; `eff 0.000s` significa que nunca se midió
      la cadencia.
- [ ] Los *holds* llegan al setpoint. Comparar con Newn1, por ejemplo la desnaturalización
      contra los 91.5 °C de entonces.
- [ ] La consola imprime `Estimated run time: … min` y `| start wait: 3.0 s`. La ETA
      inicial queda a pocos % de la duración real.
- [ ] El ciclo 1 tiene `ext_ramp` en la columna `phase` (punto 4).
- [ ] **Sin sobreimpulso nuevo** en las aproximaciones a high y ext. El fuzzy corregido
      (punto 10) mete más kp entre 2 y 5 °C de error. Si aparece, es el primer sospechoso.
- [ ] Sin atascos de `ext_ramp` (punto 3: predicción de que desaparecen sin re-afinar).
- [ ] El CSV de fotodetector trae la columna `timeouts`.
- [ ] Si una rampa se atasca, corta en ~20 s y el ciclo sigue. La línea `State` muestra
      el aviso.
- [ ] La pestaña de análisis sigue cargando las corridas nuevas y las viejas.
- [ ] El uso de CPU durante las rampas bajó, porque los lazos ya no giran sin `sleep`.

## 8. La pestaña de análisis aún no usa las columnas nuevas

Las columnas `cycle`/`phase` del CSV de temperatura y `timeouts` del de fotodetector están
pensadas como anclas estadísticas. La pestaña sigue con la selección manual de segmentos
a dos clics. El siguiente paso sería segmentar por `phase` y agrupar por `cycle`
automáticamente, excluyendo los ciclos con timeouts. Cambia el flujo de la pestaña: es
una decisión de diseño aparte ([pcr_analisis.md](pcr_analisis.md)).

## 9. `PCR_TEMP_START_WAIT_S` hardcodeado — **hecho (13/10/2026)**

El *start-gate* (3 s esperando la primera lectura válida) ahora sale de
`pidControllerRPM.temp_start_wait_s` (default 3.0, también en `DEFAULT_SETTINGS`), igual
que `temp_stale_s`. Se lee una vez por corrida en `experiment_pcr` y se imprime con la
config de la corrida (`| start wait: 3.0 s`). Un valor no numérico, negativo o 0 cae al
default: 0 abortaría siempre que la primera lectura no hubiera llegado ya.

## 10. Zona intermedia de `_fuzzy_gains` — **hecho (13/10/2026)**

**El bug.** La zona `2 ≤ |e| < 5 °C` calculaba `t = (|e| − 5) / 10`, **negativa** (de
−0.3 a 0). Con eso, en vez de interpolar hacia `kp × 2.0` / `ki × 0.2` daba
`kp × 0.7–1.0` y `ki × 1.24–1.0`, con un **salto** en 5 °C (kp × 1.0 → 2.0,
ki × 1.0 → 0.2). La zona fina, además, interpolaba sobre 0–5 °C en vez de 0–2 °C.

**Origen (git).** El gain scheduling nació continuo con cortes 15/5 °C (`9c6f3f1`). Los
cortes se movieron a 7/3 y luego a 5/2 (mayo–junio) sin reescalar las `t`.

**Corrección, por decisión del usuario.** Se reescalaron las `t` a los cortes actuales,
que ahora son constantes compartidas con `_fuzzy_max_age` (`FUZZY_NEAR_C`,
`FUZZY_FAR_C`), para que no vuelvan a desfasarse. La curva quedó continua, con salto
< 1e-9 en ambos cortes. Multiplicadores sobre KP/KI base:

| \|e\| °C | kp antes | kp ahora | ki antes | ki ahora |
|:---:|:---:|:---:|:---:|:---:|
| 0 | 0.50 | 0.50 | 1.30 | 1.30 |
| 1 | 0.60 | 0.75 | 1.24 | 1.15 |
| 2 | 0.70 | 1.00 | 1.24 | 1.00 |
| 3 | 0.80 | 1.33 | 1.16 | 0.73 |
| 4 | 0.90 | 1.67 | 1.08 | 0.47 |
| 4.99 | 1.00 | 2.00 | 1.00 | 0.20 |
| ≥ 5 | 2.00 | 2.00 | 0.20 | 0.20 |

**Efecto esperado:** entre 2 y 5 °C de error, más proporcional y menos integral: una
aproximación más decidida y con menos *windup*, que era la intención original. En
simulación del código (punto 1, con (B) y dt = 0.3 s):

- los *holds* siguen en ~100 %;
- la rampa `ext` a 69 °C pasa de 64 % a **78 %** de duty;
- a 71.2 °C queda igual (36 %).

**Ojo al validar:** las ganancias del equipo se afinaron con la curva vieja, y la próxima
corrida cambia a la vez frescura (punto 1), fuzzy (este) y la rampa del ciclo 1 (punto 4).
Si aparece sobreimpulso en las aproximaciones, el primer sospechoso es este punto, porque
mete más kp en 2–5 °C.

## 11. `DEFAULT_SETTINGS` desfasado del equipo — **hecho (13/10/2026)**

**Antes.** El equipo tenía 14 valores afinados distintos de los defaults del repo
(§0.1), entre ellos `KI_high 1.9` contra 0.9 y `KP_h_denat 1.2` contra 0.2.

**Por decisión del usuario, `DEFAULT_SETTINGS` y el `settings.json` del repo adoptan
los 14 valores del equipo.** Además:

- **`KI_h_denat: 0.5` explícito:** es el *fallback* que ya regía, así que el
  comportamiento no cambia, pero queda visible para afinarlo (punto 2).
- **`temp_start_wait_s: 3.0`:** la clave nueva del punto 9.

Verificado: el `settings.json` del repo es idéntico a `DEFAULT_SETTINGS`, y todas las
claves del equipo tienen exactamente su valor. **En el Pi esto no cambia nada** (el
*seeder* nunca pisa valores locales): sirve para un equipo nuevo, para un archivo
corrupto o para desarrollo. Las 18 claves que el equipo aún no tiene se le sembrarán con
estos valores tras el update.

__author__ = "Edisson A. Naula"
