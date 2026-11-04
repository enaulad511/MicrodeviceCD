# Control adaptativo de PCR (opcional)

> **26/10/2026:** el guardado pasó a `.xlsx` ([almacenamiento_por_experimento.md](almacenamiento_por_experimento.md)): `-adaptive: …` es la fila `adaptive` de la hoja `metadata`; la config completa queda además en la hoja `settings`.
>
> **26/10/2026, validado en el equipo** en dos cámaras (§6): los *holds* mejoran contra el clásico en las dos. Se encontraron cuatro problemas y un ciclo anómalo (§7). Decisiones en el §8; arreglos verificados en tiempo virtual en el §9.
>
> **03/11/2026, corrida Newn3 (§10):** los arreglos del §9 funcionan en el equipo. Trajo una planta nueva (duty a 85 °C 0.37, no 0.14–0.17, y masa térmica que se duplica durante la corrida) y un **atasco con el heater a fondo** por el ángulo del disco (§10.3), que ninguna ganancia arregla.
>
> **03/11/2026, ajuste final (§11):** objetivo del usuario, tiempo en ±1 °C sin picos en high ni denat. Siete valores nuevos en `pcr_adaptive` y tres cambios de código.
>
> **04/11/2026, corridas Newn4 (§12):** el ajuste final **cumple en una cámara sin eventos** y falla en la otra, con **eventos de calor** discretos que el control no puede corregir. El modelo de la planta cambia: lo que varía entre corridas es el acople del heater, no la masa, y durante la corrida se calienta el ambiente del equipo.

Archivo: [ui/PcrFrame.py](../ui/PcrFrame.py) (`_ramp_adaptive`, `_hold_adaptive`,
`_adaptive_cfg`). Config: `settings.json` → `pcr_adaptive`. **Apagado por defecto.**

## 1. Por qué

Cada experimento usa un **disco nuevo** y la respuesta térmica cambia mucho de uno a otro
([pcr_ajuste_ganancias.md](pcr_ajuste_ganancias.md) §7, tres discos el 21/10/2026):

- **Constante entre discos:** la potencia para *sostener* una temperatura es del
  instrumento: duty ≈ 0.20–0.21 a 90 °C y 0.03–0.05 a 50 °C, estable de un ciclo a otro.
- **Variable entre discos:** el **calor en vuelo**, cuánto sigue subiendo la temperatura
  tras apagar el heater (2.7–8.2 °C en la rampa a ext), con el termopar respondiendo en
  0.3–1.25 s según el disco.

El control clásico (rampa a potencia plena + PI con integral que satura en < 1 s) se pasa
según el disco (+2.7 a +9.2 °C en ext) y deja los *holds* calientes en un ciclo límite de
±2 °C. Ninguna ganancia fija sirvió para todos los discos. El adaptativo **aprende el
disco durante la corrida**.

> **Corregido el 03/11/2026:** el duty de régimen **no** es constante entre discos. Newn3
> pidió 0.37 a 85 °C contra 0.14–0.17 el 26/10 (§10.2). Como el duty también se aprende, el
> diseño no cambia, pero el *feed-forward* inicial puede fallar por un factor de 2.

## 2. Cómo funciona

**Rampa** (`denat_ramp`, `high_ramp`, `ext_ramp`):

1. **Potencia plena** hasta `setpoint − coast`, con el mismo descarte de lectura vieja
   que el blast clásico. La temperatura se **extrapola entre ráfagas**: con lecturas cada
   ~0.27 s y ~10 °C/s, sin extrapolar el corte llegaba una ráfaga (~3 °C) tarde. La tasa
   se estima con lecturas separadas ≥ 0.2 s (`PCR_ADAPT_RATE_MIN_SPAN_S`): las de una
   misma ráfaga llegan con ~1 ms de diferencia, y un cociente entre ellas daría cientos
   de °C/s y un corte en falso.
2. **Inercia:** solo el *feed-forward* del *hold* siguiente mientras dure la subida
   rápida. Apagar del todo haría caer la temperatura tras el pico. Termina cuando la
   temperatura baja 0.15 °C de su máximo, cuando la subida cae de 0.8 °C/s (ya sube solo
   por el *feed-forward*) o a `coast_window_s`. El resto del acercamiento lo hace el
   *hold*.
3. **Aprende:** `coast += coast_learn · (máximo de la subida rápida − setpoint)`. Pasarse
   adelanta el corte y quedarse corto lo atrasa. Hay un `coast` por rampa, porque high y
   ext difieren mucho en el mismo disco.
   - **Semilla:** `denat` arranca con `coast_init` y high/ext con `coast_init_cycle`.
     Antes high heredaba el de denat (§7.1).
   - **Cuándo aprende:** si hubo ≥ 0.3 s de potencia plena (`PCR_ADAPT_MIN_FULL_S`), o
     siempre que la subida rápida se quedó corta. Con un corte inmediato no se midió el
     calor en vuelo, pero atrasar el corte es la dirección segura.
   - **Paso:** cada rampa mueve el corte como mucho `coast_step_max`.
   - **Saltos:** una rampa cuya subida pasa de `jump_cps` (tasa sobre ≥ 0.45 s) no
     enseña, porque es un salto del termopar y no calor de la muestra (§7.2).
   - **Objetivo en high:** `setpoint − coast_margin`, no el setpoint (§11). Las otras rampas
     apuntan al setpoint.

`break_if_below` se respeta igual que en el clásico, y la salvaguarda de tiempo
([pcr_timeout_fases.md](pcr_timeout_fases.md)) cubre la rampa completa, inercia incluida.

**Hold** (`h_denat`, `h_high`, `h_low`, `h_ext`, también la extensión final):

- **Potencia** = *feed-forward* + PI suave (`hold_kp/ki/imax`, con el mismo escalado de
  `_fuzzy_gains`). Dentro de `hold_tband` se mantiene *feed-forward* + I: el clásico
  fuerza 0.
- **Freno:** la potencia no pasa de *feed-forward* + `hold_pmax`. Sin él, tras un corte
  temprano el P (×2 del fuzzy lejos del setpoint) calentaba a fondo sin descontar el
  calor en vuelo y se pasaba (§7.4).
- ***Feed-forward*:** el duty aprendido para ese *hold* en esta corrida o, mientras no
  hay, el modelo `ff_slope · (setpoint − ff_t0)` (0.21 a 90 °C, 0.04 a 50 °C, 0.11 a
  65 °C). El primer *hold* de high parte del duty aprendido en la denaturación, corregido
  con `ff_slope` si los setpoints difieren.
- **Rampa vencida** (atasco, §10.3): el *hold* siguiente suelta el freno mientras falte más
  que el calor en vuelo de esa rampa. Al acercarse vuelve y no se suelta otra vez: si el
  disco se realinea, la tasa normal regresa de golpe y sin freno se pasaría.
- **Aprende** el duty medido por `heater_on_s` en la segunda mitad del *hold*, con peso
  `ff_learn`, solo si duró ≥ 2 s y el error medio fue ≤ 0.75 °C. Un *hold* pasado de
  temperatura mide 0, y eso no es el duty de régimen.

Todo lo aprendido se reinicia en cada corrida: el disco cambia.

## 3. Configuración (`settings.json` → `pcr_adaptive`)

`main.py` lo siembra al arrancar (`seed_default_settings`) con `enabled 0`. Se activa
poniendo `enabled` en 1 (ConfigFrame) y se lee **una vez por corrida**. Un valor no
numérico o negativo cae a su default. **Decisión (26/10/2026):** `enabled 1` solo en el
Pi; el default del repo sigue en 0.

| clave | default | significado |
|-------|:-:|-------------|
| `enabled` | 0 | 1 = adaptativo; 0 = control clásico **intacto** |
| `ff_slope`, `ff_t0` | 0.0043, 40 | duty inicial = ff_slope × (setpoint − ff_t0) |
| `ff_learn` | 0.5 | peso del duty medido en cada *hold* (0 = no aprende) |
| `hold_kp`, `hold_ki`, `hold_imax` | 0.1, 0.03, 3 | PI suave sobre el *feed-forward* (techo del I ≈ ±0.12) |
| `hold_tband`, `hold_win` | 0.05, 0.05 | banda (sin P) y ventana de PWM (s) |
| `hold_pmax` | 0.3 | tope de la potencia del *hold* sobre el *feed-forward* (0 = sin tope) |
| `coast_init` | 4 °C | calor en vuelo supuesto en la rampa de denat (una por corrida) |
| `coast_init_cycle` | 8 °C | ídem en high y ext antes de medir (26/10: convergió a 6.3–9.8) |
| `coast_learn` | 0.5 | ganancia: coast += coast_learn·(pico − setpoint) |
| `coast_step_max` | 2 °C | cambio máximo del corte por rampa (0 = sin tope) |
| `coast_margin` | 0 °C | solo high: el corte aprende a dejar el pico rápido estos °C bajo el setpoint |
| `jump_cps` | 20 °C/s | subida que se toma como salto del termopar: esa rampa no enseña (0 = no filtra) |
| `coast_min`, `coast_max` | 0.5, 12 °C | límites del corte |
| `coast_window_s` | 8 s | espera máxima de la inercia |

**Para el Pi** (`resources/settings.json`, copia del equipo, §11): `hold_kp 0.15`,
`hold_ki 0.015`, `hold_imax 5` (techo del I ≈ ±0.10), `hold_pmax 0.4`, `coast_init 8`,
`coast_min 3`, `coast_margin 0.5`. Los defaults del repo no cambian hasta validarlos en el
equipo.

## 4. Qué queda registrado

- **Consola,** en cada rampa y en cada *hold*:
  `Adaptive ext ramp: cut at 56.9 °C (coast 7.1), peak 64.9 °C → coast 7.0 °C` y
  `Adaptive h_high: duty 0.202 (mean err −0.03 °C) → bias 0.203` (o `not learned`). Una
  rampa con salto del termopar imprime
  `…, peak 92.3 °C, rise 31 °C/s (thermocouple jump) → coast kept`.
- **Metadata** (fila `adaptive`): `off`, o la config y lo aprendido al final
  (`on … pmax 0.4 coast init 8/8C learn 0.5 step 2C jump 20C/s margin 0.5C | bias h_high 0.212 … |
  coast ext 7.0 high 7.1`). `an_adaptive.py` solo lee la parte desde `| bias`.
- **Columnas** `phase` y `heater_on_s`: con ellas se reconstruye cada corte y cada duty.

## 5. Verificación (sin equipo)

`files_test/ajuste_21oct/test_adaptive.py` corre el **código real** de
`_reach_phase`/`_hold_phase` en **tiempo virtual**: sustituye el `time` que ve
`ui.PcrFrame` por un reloj que avanza un disco simulado (con pérdidas al ambiente, duty de
régimen 0.21 a 90 °C) y entrega lecturas en ráfagas de 4 cuantizadas a 0.25 °C. Doce
ciclos en segundos.

Ciclos 4–12, fracción del *hold* dentro de ±0.5 °C y sobreimpulso:

| disco simulado | clásico | adaptativo |
|---|:-:|:-:|
| rápido: high / low / ext | 0.14 / 0.48 / 0.24, +5.3 / +6.2 °C | **0.88 / 0.89 / 0.64, +0.7 / +0.9 °C** |
| lento: high / low / ext | 0.10 / 0.41 / 0.29, +7.2 / +7.6 °C | 0.28 / 0.61 / 0.57, **+1.5 / +0.7 °C** |

Desde el tercer ciclo los picos caen en 90.0 ± 0.2 °C y 65.0 ± 0.5 °C, y el corte converge
sin saturar. Los discos simulados **no** son el equipo: sirven para comprobar que el
código aprende, no se cuelga (0 timeouts) y no toca el clásico, no para predecir números.

**Dos fallos de diseño detectados en simulación y corregidos:**

1. Aprender `coast` como "pico − corte", o del pico completo, lo dejaba clavado en
   `coast_max`. Con el *feed-forward* encendido la temperatura sigue subiendo despacio
   hasta el setpoint, así que un corte demasiado temprano también "acertaba".
2. Sin extrapolar entre ráfagas, el corte llegaba ~3 °C tarde.

**Pendiente:** el *hold* de 90 °C del disco lento sigue oscilando en simulación
(std 0.9 °C). Cambiar `hold_kp/ki` no mejoró a la vez los dos discos simulados. (En el
equipo no pasó: el *hold* de 85 °C quedó con std 0.33–0.45 °C, §6.)

## 6. Validación en el equipo (26/10/2026)

**Corridas.** `files_test/Newn2_pcr_data_20261026_182410.xlsx` (**A**, inicio 17:32) y
`…_192302.xlsx` (**B**, 18:32). Código de `4b36d46` (la metadata trae `end: done`).
Receta: 35 ciclos, high 85 °C × 15 s, low 50 × 15 s, ext 62 × 6 s, denat 85 × 120 s,
extensión final 120 s, 800 rpm, termopar al mando, `pcr_adaptive` con los defaults del
§3 y `enabled 1`. Las ganancias clásicas no intervienen; de la rampa solo se usan los
umbrales de frescura. **Mismo disco, cámaras distintas** (usuario, 26/10/2026): cada cámara
es una planta distinta, como un disco nuevo. Las huellas difieren:

- respuesta del termopar: 0.90 s en A, 0.61 s en B;
- calentamiento en la rampa a high: 5.4 °C/s en A, 9.2 °C/s en B;
- desfase IR − termopar a 85 °C: −3.5 °C en A, −0.4 °C en B.

**Scripts** (`files_test/ajuste_21oct/`, gitignored):

- `an_adaptive.py` reconstruye cada corte, cada pico y cada duty tal como los vio el
  controlador (la EMA guardada es su `self.temp`) y re-simula el aprendizaje. Reproduce
  lo que la corrida dejó en la fila `adaptive`: los `bias` exactos, y el `coast` exacto
  en A. En B el `coast` de ext difiere en 1 °C: ahí la potencia plena de la rampa a ext
  dura ~1.0 s, justo el mínimo para aprender (`PCR_ADAPT_MIN_FULL_S`), y algunas rampas
  no enseñaron.
- `plot_adaptive.py` genera las figuras `adaptive_*.png`.
- `fingerprint.py` e `ir_vs_tc.py` ahora leen los setpoints de la metadata.
  `fingerprint.py` agrega `hi_rate` (calentamiento a media rampa a high) y `coast_cut_C`
  (subida tras dejar la potencia plena). `coast_C` mantiene la definición del 21/10
  (subida tras **apagar** el heater), que con el adaptativo no aplica, porque el heater
  sigue con el *feed-forward*.

**Contra el clásico** (medianas de los ciclos ≥ 2; *holds* en ±0.5 °C). La comparación
**no es controlada**: la receta difiere (85/62 contra 90/65), los discos también, y no
hubo una corrida clásica el mismo día. Aun así, el ciclo límite del clásico no depende de
5 °C de setpoint (§2 de [pcr_ajuste_ganancias.md](pcr_ajuste_ganancias.md)), y la mejora
aparece en las dos cámaras:

| | clásico 21/10, discos 1 / 2 / 3 | adaptativo A | adaptativo B |
|---|:-:|:-:|:-:|
| *hold* de high en ±0.5 | 19 / 19 / 27 % | **57 %** | **73 %** |
| std del *hold* de high tras 3 s (°C) | 1.40 / 1.26 / 1.05 | 0.50 | 0.39 |
| máximo − sp en high (°C) | +3.6 / +5.1 / +4.5 | +2.5 | +1.1 |
| *hold* de low en ±0.5 | 80 / 51 / 49 % | 87 % | 97 % |
| *hold* de ext en ±0.5 | 25 / 0 / 0 % | 13 % | 58 % |
| máximo − sp en ext (°C) | +2.7 / +9.2 / +5.2 | +1.6 | +1.0 |
| denaturación de 120 s en ±0.5 | 21 / 58 / 97 % | 88 % | 81 % |
| extensión final de 120 s en ±0.5 | 26 / 17 / 16 % | **85 %** | **86 %** |
| std de la extensión final, 2.ª mitad (°C) | 1.09 / 1.66 / 2.01 | 0.28 | 0.34 |
| timeouts | 0 / 7 / 0 | 0 | 0 |
| duración de un ciclo (s) | 85 / 95 / 90 | 81 | 81 |

- **Los *holds* largos dejan de oscilar.** El clásico tenía la denaturación y la
  extensión final en un ciclo límite de ±2–5 °C. Con el adaptativo, tras los primeros
  20 s (el sobreimpulso de la rampa), la denaturación queda en std 0.15–0.35 °C y en
  ±0.5 el 85–100 % del tiempo.
- **Duty de régimen a 85 °C** (denaturación, 60–125 s): 0.17 en A y 0.14 en B, por
  debajo de las 0.19 del modelo inicial (`ff_slope`). El aprendizaje lo absorbe.
- **Lo aprendido al final:** `bias` de `h_high` 0.16 / 0.125 y de `h_denat`
  0.18 / 0.17. `coast` de high 8.4 / 8.7 y de ext 6.3 / 7.7. Figura de la convergencia:
  `adaptive_learning.png`.

**Checklist de la validación:**

- [x] Corrido en dos cámaras. Falta una corrida con `enabled 0` en condiciones comparables
      (opcional, §8).
- [~] Picos en ±1 °C del setpoint desde el 3er–4º ciclo:
  - **B sí:** en los ciclos 6–35 el pico de high queda en +1.0 °C (máximo +2.2) y el de
    ext en +0.9 °C.
  - **A no:** el de high queda en +2.1 °C (hasta +7 °C, por los saltos del termopar,
    §7.2) y el de ext en +1.5 °C (cola lenta, §7.3).
- [x] `bias` de `h_high` estable. A 85 °C es 0.13–0.16, no 0.20 (eso era a 90 °C).
- [x] Sin timeouts.
- [x] El *hold* de 85 °C no oscila (std 0.33–0.45 °C en la segunda mitad): no hace falta
      tocar `hold_kp/ki/imax`.

## 7. Problemas encontrados en el equipo

**7.1 Primera rampa a high: la semilla heredada de denat queda corta.** El `coast` de
high arranca con el de denat: 2.7 °C en A (su rampa de denat se quedó 2.5 °C corta) y
5.5 °C en B. Las dos cámaras convergieron después a 8.4–9.8 °C. En B, ciclo 2, la rampa
cortó en 78.3 °C:

- el termopar llegó a +12.3 °C (97.3 °C);
- el IR llegó a +6.7 °C, así que el sobreimpulso fue real.

La rampa de denat no sirve de semilla: arranca en frío (~30 °C, 6–8 s a potencia plena),
y su calor en vuelo no se parece al de una rampa de 62 a 85 °C.

**7.2 Saltos del termopar por encima de ~70 °C (cámara A).** En 19 de las 34 rampas a high
(ciclos 2–35), el termopar crudo sube a ~4 °C/s hasta 70–77 °C. A veces queda plano ~1 s,
y luego **salta ~20 °C en 0.3–0.6 s**:

- son más de 20 °C/s, el doble de lo que el heater puede calentar;
- el IR nunca pasa de ~11 °C/s;
- ninguna rampa a ext (por debajo de 70 °C) los tiene.

Es la misma firma del disco 2 del 21/10, donde aparecía en el 100 % de las rampas a 90 °C.
En B aparece en 1 de 34. Medido contra el nivel final de cada *hold*, el pico del termopar
es +2.4 °C (p90 +5.8), y el del IR, +0.8 °C (p90 +1.8): **la mayor parte del pico es un
artefacto local del termopar**. Es una deducción: falta una referencia de la muestra
([ir_vs_termopar.md](ir_vs_termopar.md) §5).

> **Matiz (04/11/2026):** son los *eventos de calor* del §12.2. Medido evento por evento, el
> IR también salta (9 °C de mediana en A, contra 15 °C del termopar), así que "artefacto del
> termopar" se queda corto.

El daño está en el **aprendizaje**:

- el `coast` de high oscila entre 7 y 12 °C, y 4 ciclos tocan `coast_max`;
- cuando el salto llega después de la subida rápida, aprende al revés. En el ciclo 11 la
  rampa quedó plana en 77 °C, la subida "terminó" y el algoritmo aprendió que se había
  quedado corto (−8 °C). Luego, ya en el *hold*, el termopar saltó de 77 a 95.5 °C.

Por eso el *hold* de high de A queda en 49–59 % en ±0.5, haya salto en ese ciclo o no.

**7.3 Cola lenta en ext (cámara A).** La subida rápida termina en el setpoint (mediana
−0.1 °C), pero la temperatura sigue subiendo +1–1.5 °C con el heater ya apagado. A 62 °C
solo cae a ~0.25 °C/s, así que el *hold* de 6 s queda entero por encima: media +1.0 °C y
13 % del tiempo en ±0.5. En B la cola es menor (~+1.0 °C) y el *hold* queda en 58 %.

Consecuencia en el aprendizaje del *hold* de ext de A:

- casi nunca aprende: 3 de 35 veces, porque el error medio pasa de 0.75 °C;
- las 3 veces que aprendió midió duty 0, y su `bias` bajó de 0.09 a 0.012;
- la extensión final arrancó con ese `bias` y cayó a −2.0 °C al principio.

**7.4 Corte demasiado temprano: el *hold* hace de rampa sin freno.** En el ciclo 7 de A
(`coast` 10.2 °C), la subida rápida acabó en 55.9 °C, 6.1 °C por debajo del setpoint.

- El P del *hold* lleva el ×2 del fuzzy con |e| ≥ 5 °C: 0.2·e, potencia plena con 5 °C
  de error.
- Calentó a fondo ~1.5 s sin ninguna compensación del calor en vuelo y se pasó +4.5 °C.
- Lo mismo, más leve, en el ciclo 27: de −3.2 a +2.5 °C.

Así que cortar antes "por seguridad" no sale gratis mientras el *hold* empuje así.

**7.5 Un ciclo con la planta cambiada.** En el ciclo 6 de A hubo 1.5 s de potencia plena
(lo típico es 2.2 s), y aun así la temperatura siguió subiendo 14 °C tras el corte: de 54
a 68.5 °C (el IR llegó a 67.9). No es un artefacto del termopar ni se explica con la
rampa. Deducción sin confirmar: se movió la muestra o una burbuja, o el contacto del
heater.

## 8. Propuestas y decisiones (26/10/2026)

1. **Semilla de high y ext:** no heredar el `coast` de denat y arrancar con uno
   conservador, de ~8 °C (lo que convergió en las dos cámaras). Va junto con el punto 2:
   si no, un corte temprano termina como el §7.4. **Hecho** (`coast_init_cycle`, §9).
2. **Freno al P del *hold*:** un tope de potencia de `bias + 0.3`. Así, un corte temprano
   se acerca despacio en vez de pasarse; el costo es una aproximación más lenta cuando la
   rampa se queda corta. **Hecho** (`hold_pmax`, §9).
3. **Aprendizaje robusto del corte:** tope por paso de ±2 °C y no aprender de rampas con
   una subida imposible para el heater (salto del termopar, §7.2). **Hecho**
   (`coast_step_max`, `jump_cps`, §9).

   La alternativa de fondo, sin hacer, es decidir el corte con el IR, que no salta. Pero
   necesita aprender el desfase IR − termopar, que cambia por cámara
   ([ir_vs_termopar.md](ir_vs_termopar.md) §5), y se conecta con la migración al IR.
4. **Cola lenta de ext:** **aceptada** (usuario: +1 °C en la extensión de 6 s es
   despreciable por ahora). Si algún día importa, la vía es apuntar la subida rápida a
   `setpoint − cola`, con la cola medida solo cuando la subida rápida acaba en ±0.5 °C
   del setpoint, para no repetir el trinquete del §5.
5. **Aprender el `bias` solo con el error medio ≤ ~0.3 °C** (hoy es 0.75): evitaría
   aprender duty 0 de un *hold* pasado de temperatura (§7.3). **Abierto, prioridad baja:**
   con la cola de ext aceptada, su efecto es el arranque bajo de la extensión final.
6. **Default:** `enabled 1` **solo en el Pi** (usuario). El default del repo
   (`DEFAULT_SETTINGS`) sigue en 0. Una corrida clásica con la receta 85/50/62 daría la
   comparación controlada que falta en el §6, pero no hace falta.

## 9. Arreglos del 26/10/2026 (verificados en tiempo virtual)

**Código** ([PcrFrame.py](../ui/PcrFrame.py), solo `_ramp_adaptive`/`_hold_adaptive` y la
config; el clásico no cambia):

- **Semilla:** `coast_init_cycle` (8 °C) para high y ext, sin heredar de denat.
- **Cuándo aprende:** `PCR_ADAPT_MIN_FULL_S` pasa de 1.0 a 0.3 s, y una subida rápida que
  se quedó corta enseña siempre. Con la semilla de 8 y el mínimo de 1 s, la rampa a ext
  de un disco rápido (0.5–1.0 s a potencia plena) **no aprendía nunca**: en simulación el
  *hold* de ext cayó de 88 % a 56 %. En el equipo pasaría lo mismo: en la cámara B la
  potencia plena de ext ya rondaba 1.0 s.
- **Paso** limitado a `coast_step_max` (2 °C).
- **Saltos:** si la subida de la EMA, medida sobre ≥ 0.45 s (`PCR_ADAPT_JUMP_SPAN_S`),
  pasa de `jump_cps` (20 °C/s), esa rampa no enseña. Emulando el peor caso del sondeo
  sobre las cinco corridas del 21 y 26/10 detecta el 79 % de los saltos que ocurren
  dentro de la rampa, con 2 falsos positivos en 287 rampas. No ve los que llegan ya en el
  *hold* (§7.2, ciclo 11): esos los acota el tope de paso.
- **Tasa con lapso mínimo de 0.2 s** (`PCR_ADAPT_RATE_MIN_SPAN_S`) para la extrapolación
  del corte (§2). Riesgo latente: no se vio en los datos, pero el lazo sondea cada 10 ms.
- **Freno del *hold*:** `hold_pmax` (0.3).

Las cuatro claves nuevas están en `DEFAULT_SETTINGS`: el *seeder* se las agrega al Pi al
arrancar, sin tocar lo demás. **`coast_init` del Pi sigue en 4**, y ahora solo lo usa la
rampa de denat.

**Verificación:** `files_test/ajuste_21oct/test_adaptive_26oct.py` corre el código real
(contra el `PcrFrame` de `HEAD`) con la receta 85/50/62, en cuatro discos simulados:
rápido, lento y los dos con un salto del termopar al cruzar 72 °C (p 0.55; congela la
lectura 0.5 s y salta +6 °C). Mide sobre la temperatura **real** de la muestra. Con 12
ciclos (picos en °C sobre el setpoint):

| disco simulado | pico high, ciclo 2: HEAD → nuevo | pico ext, ciclos 1–2 | *hold* high / ext en ±0.5 (ciclos 4+) |
|---|:-:|:-:|:-:|
| rápido | +1.2 → +1.4 | +3.5 → **+1.4** | 0.97 / 0.88 → 0.93 / 0.83 |
| lento | +3.0 → **+1.8** | +5.8 → **+1.5** | 0.20 / 0.34 → 0.20 / 0.39 |
| rápido + saltos | +1.5 → +1.4 | +3.9 → **+1.1** | 0.72 / 0.85 → 0.73 / **1.00** |
| lento + saltos | +5.1 → **+1.9** | +5.8 → **+1.6** | 0.25 / 0.36 → 0.25 / 0.38 |

- **Lo que se gana:** los primeros ciclos dejan de pasarse (sobre todo ext, y high en
  discos lentos). En régimen queda igual o mejor.
- **El disco rápido baja un poco en 12 ciclos** porque converge desde la semilla de 8 °C.
  Con 30 ciclos ya no: high 0.94 contra 0.95, ext 0.88 contra 0.84. Con saltos, 0.73 /
  0.90 contra 0.70 / 0.85.
- **El freno solo actúa tras un corte temprano.** Con la semilla de 8 nunca se activó.
  Forzado con semilla 12, el pico de ext de los ciclos 1–2 baja de +6.0–6.3 a +2.3–2.9 °C
  en los cuatro discos, y el de high del ciclo 2 de +4.9–5.1 a +2.2 en los rápidos. Cuesta
  tiempo en banda en el disco rápido (*hold* de high 0.91 → 0.82), porque se acerca más
  despacio.
- **El banco original** (`test_adaptive.py`, receta 90/50/65) también mejora con el código
  nuevo: el *hold* de ext del disco rápido pasa de 0.64 a 0.84, y en el lento ext va de
  0.57 a 0.75 y high de 0.28 a 0.32. Sin timeouts, y el clásico da lo mismo que antes.

**Pendiente: correr en el equipo.** Revisar en consola:

- `coast kept` en las rampas con salto;
- que el `coast` de ext aprenda desde el ciclo 1, sin quedarse fijo en 8;
- que los picos de high y ext de los ciclos 1–2 queden en ≲ +2 °C.

`an_adaptive.py` reproduce las reglas nuevas cuando la corrida trae `coast_init_cycle` en
su hoja `settings`.

## 10. Corrida Newn3 (02/11/2026) y ajuste de ganancias

**Corrida.** `files_test/Newn3_pcr_data_20261102_152624.xlsx` (inicio 14:16, 4174 s): 35
ciclos, 85/50/62, high y low 15 s, **ext 22 s** (antes 6), denat 85 × 120 s, extensión
final 120 s, 800 rpm, termopar al mando, `hold_ki 0.02`, código con los arreglos del §9. La
hoja `settings` es idéntica al `resources/settings.json` que trajo el usuario. Sin consola.

Scripts en `files_test/ajuste_21oct/` (gitignored):

- `an_adaptive.py`: ahora las rampas vencidas no enseñan, igual que `_ramp_adaptive`. Con eso
  reproduce **exacto** el `coast` de la metadata (denat 2.5, ext 2.9, high 2.0) y el `bias`
  a ±0.001.
- `fit_step.py`: ajusta la planta con los escalones reales de cada `ext_ramp`.
- `test_adaptive_nov.py`: banco en tiempo virtual con esas plantas (modos `calib`, `scan`,
  `stress`, `others`, `stall`).

### 10.1 Los arreglos del §9 funcionan

- [x] Picos de los ciclos 1–2 ≲ +2 °C: high +0.50 / −0.29, ext +0.49 / +0.71.
- [x] `coast` de ext aprende desde el ciclo 1 (8 → 6.3 → 5.7 …).
- [x] Freno del *hold*: en el ciclo 25 la subida rápida acabó en −3.3 °C y el pico total fue
      +0.85 °C. El mismo caso en la cámara A (§7.4) se pasaba +4.5 °C.
- [ ] `coast kept` ante un salto del termopar: **sin probar**. Esta cámara no tuvo saltos
      (subida máxima de la EMA 8.8 °C/s).

Medianas de los ciclos ≥ 2:

| | A (26/10) | B (26/10) | Newn3 |
|---|:-:|:-:|:-:|
| *hold* de high en ±0.5 | 57 % | 73 % | **50 %** (58 % en c6–35) |
| std del *hold* de high tras 3 s (°C) | 0.50 | 0.39 | 0.29 |
| máximo − sp en high (°C) | +2.5 | +1.1 | **+0.7** |
| *hold* de low en ±0.5 | 87 % | 97 % | 95 % |
| *hold* de ext en ±0.5 | 13 % | 58 % | **72 %** (22 s) |
| denaturación de 120 s en ±0.5 | 88 % | 81 % | 68 % |
| extensión final en ±0.5 | 85 % | 86 % | **91 %** |
| timeouts | 0 | 0 | **4** (§10.3) |
| duración de un ciclo (s) | 81 | 81 | 118 |

### 10.2 Planta nueva

**Lo que cambió (usuario, 03/11/2026):** entre el 26/10 y el 02/11 se realineó un poco la
montura del heater. No se sabe si eso alcanza para explicar lo de abajo.

**Duty de régimen mucho mayor,** ya desde el ciclo 2:

| duty | A | B | Newn3 |
|---|:-:|:-:|:-:|
| *hold* de 15 s a 85 °C | 0.16–0.18 | 0.13–0.15 | **0.36–0.38** |
| denaturación a 85 °C (> 60 s) | 0.17 | 0.14 | 0.27 |
| *hold* a 62 °C | ~0.07 | 0.06–0.09 | 0.15 |
| *hold* a 50 °C | 0.04 | 0.02 | 0.05 |

**La masa térmica aparente se duplica durante la corrida.** Entre los ciclos 2–5 y 17–35:
calentamiento (IR) de 6 a 3 °C/s, cola pasiva de −0.56 a −0.25 °C/s, enfriamiento con motor
de 14 a 32 s, y **el duty de *hold* no cambia**. Que las tres tasas caigan parecido (~2–2.3×)
con el duty constante es lo que produce una masa mayor; un heater más débil pediría más duty.
Esto último es una deducción: los datos no dicen qué masa creció. Por eso el ciclo pasa de
82 a 122 s.

> **Matiz (04/11/2026):** Newn4 no repite esto. La tasa no cae durante la corrida y el ciclo
> se alarga por otra causa (§12.3). "La masa se duplica" queda como algo propio de Newn3, sin
> explicar, no como rasgo del equipo.

**Cambio brusco entre los ciclos 8 y 9.** En un solo ciclo el enfriamiento sube 7 s, la rampa
a high 3 s y el desfase IR − termopar a 85 °C pasa de −3.0 a +2.3 °C. Ese desfase oscila hasta
c16 (−2.6 a +2.3) y desde c17 queda en ~+1.1; en c2–8 era ~−5. A 50 °C sigue estable
(+1.4–1.6). Si el IR refleja la muestra, "85 °C" fue ~79–80 °C al principio y ~86–88 °C al
final ([ir_vs_termopar.md](ir_vs_termopar.md) §6).

**El termopar se vuelve más lento que el IR, de forma gradual:** responde en ~0.6 s en c5–6 y
en ~1.2 s desde c10 (c7–9: 0.9 s), mientras el IR sigue en 0.6–0.9 s.

Ajuste con los escalones reales (`fit_step.py`; rms 0.21–0.28 °C, 0.57 en c2–8). Los grupos de
Newn3 son para promediar, no marcan cambios de planta:

| | `a` (°C/s a fondo) | retraso (s) | `a` × retraso (°C) | `coast` usado, high / ext (°C) |
|---|:-:|:-:|:-:|:-:|
| B | 10.7 | 0.70 | 7.5 | 9.8 / 8.2 |
| A | 6.1 | 1.50 | 9.2 | 9.4 / 7.0 |
| Newn3 c2–8 | 6.7 | 0.65 | 4.4 | 4.5 / 5.0 |
| Newn3 c9–16 | 3.8 | 1.55 | 5.9 | 3.4 / 4.7 |
| Newn3 c17–35 | 3.2 | 1.20 | 3.8 | 2.6 / 2.9 |

**El aprendizaje del corte siguió a la planta:** el `coast` baja junto con `a` × retraso, que
se midió de forma independiente. Coinciden en orden y tendencia, no en el valor exacto.

Los picos de +4.2 y +2.9 °C de los ciclos 23–24 son **reales**, no del termopar: el IR sube
+5.4 y +4.8 °C sobre su propio nivel. El tope de paso del `coast` los corrigió en dos ciclos.

### 10.3 Atasco con el heater a fondo (no es de ganancias)

Dos episodios. Empiezan **en `low_hold`, justo después de parar el motor**:

| | desde | hasta | consecuencia |
|---|:-:|:-:|---|
| 1 | `low_hold` c11 | c12, ~4 s dentro de `high_ramp`, **sin orden al motor** | extensión c11 a 56 °C (22 s) |
| 2 | `low_hold` c28 | giro de `cooling` de c29 | extensión c28 a 55 °C; **denaturación de c29 a 59 °C, no a 85** |

- `heater_on_s` da **duty 1.0**, y termopar e IR coinciden en **0.2–0.3 °C/s** (normal 2–3 con
  el mismo criterio). No es un artefacto del sensor ni el techo de frescura de
  [pcr_pendientes.md](pcr_pendientes.md) §1, que ya no aplica: el heater está encendido y
  medido.
- Plano en 56 °C con duty 0.45 (normal 0.10) y en 59 °C con 0.63 (normal 0.13): el calor
  efectivo cae a ~15–25 %.
- Al arrancar el motor en c29, con el heater apagado, **la temperatura sube** +3.0 °C en el
  termopar y +2.5 °C en el IR. Lo más simple es que hubiera una zona más caliente cerca, sin
  mezclar; es una deducción.

**Causa (usuario, 03/11/2026): el disco quedó en un ángulo equivocado tras la parada, y lo
realineó a mano.** Eso resuelve lo que no cuadraba: c12 se recupera sin orden al motor porque
se movió con la mano. La fluorescencia de c28 cae 14 % (0.0459 contra 0.053 a ambos lados) y
la de c11 no. Esa corrida no tiene log de consola, así que no se sabe en qué ángulo quedó ni
por qué: las líneas `Stopped--> pos: …°` y `go_zero wait timed out` lo dirían.

**La tasa cambia con cada parada del motor, no solo en los atascos.** `ext_ramp` del ciclo c
y `high_ramp` del c+1 comparten parada; `high_ramp` del c y `ext_ramp` del c no. Tasa del IR,
sin la tendencia lenta:

| corrida | misma parada | otra parada | dispersión de la tasa |
|---|:-:|:-:|:-:|
| A | **+0.49** | −0.28 | 22 % |
| B | +0.13 | −0.01 | 7 % |
| Newn3 | **+0.63** | −0.45 | 15 % |

El duty de high de esa misma parada va al revés (−0.69, −0.54, −0.30): más tasa, menos duty.
Deducción: los atascos serían el extremo de una variación de ángulo en cada parada. Sería
también la fuente principal de los picos de high: el corte se aprende de la rampa anterior,
que viene de otra parada. Al modelarlo así, el banco reproduce la estadística real de picos
(§11).

**Lo que sí hizo el control:** la salvaguarda cortó cada rampa a los 20 s, y ni el `coast` ni
el `bias` aprendieron del atasco. c28 y c29 son dos ciclos fallidos seguidos: con
`max_failed_cycles 3`, uno más abortaba la corrida. El cuarto timeout (`cooling` de c29, a
0.2 °C del objetivo) es consecuencia: entró a 59 °C, y el plazo por ΔT quedó corto.

### 10.4 Primer ajuste, en ±0.5 °C (03/11/2026; lo reemplaza el §11)

Con `enabled 1` las ganancias clásicas (`KP_*`, `KI_*`) **no intervienen**: no se tocan. El
ajuste está en `pcr_adaptive`. Lo de este apartado se mantiene (`hold_kp`, `hold_imax`), con el
banco anterior, que aún no modelaba la variación por parada:

| clave | antes | ahora | por qué |
|---|:-:|:-:|---|
| `hold_kp` | 0.1 | **0.15** | mejora el *hold* en todas las plantas medidas y en la rápida de estrés |
| `hold_imax` | 3 | **5** | techo del I de ±0.08 a ±0.13 |
| el resto | — | sin cambio | ningún efecto consistente, o un costo (abajo) |

**Por qué el techo del I.** Con `hold_ki 0.02`, el techo quedó en ±0.08 de potencia, y en
Newn3 el error del `bias` llegó a ±0.15. El integrador pasó ≥ 40 % del tiempo saturado en 10
de los 34 *holds* de high (c2–5, c9–10, c12–13, c15–16; sin contar el atasco de c29):

- ciclos 2–3: −1.3 °C, sin aprender el duty, porque el error medio pasa de 0.75 °C;
- ciclo 12: +1.27 °C, fuera de ±0.5 todo el *hold*.

**Banco.** Con los ajustes con los que corrió cada corrida, reproduce:

| | rampa a high (s) | `coast` high / ext | duty a 85 °C | std *hold* | *hold* high en ±0.5 |
|---|:-:|:-:|:-:|:-:|:-:|
| Newn3 real | 11.0 | 2.0 / 2.9 | 0.37 | 0.29 | 0.50 |
| Newn3 simulada | 11.5 | 1.9 / 2.7 | 0.35 | 0.26 | 0.72 |
| B real | 4.3 | 8.7 / 7.7 | 0.14 | 0.39 | 0.73 |
| B simulada | 4.3 | 7.1 / 7.0 | 0.14 | 0.34 | 0.88 |

**Es optimista en los *holds*** (~0.15–0.2: no tiene ruido ni artefactos del termopar), así
que valen las diferencias, no los absolutos. La planta A sale demasiado oscilatoria (std 0.97
contra 0.50): es un caso de estrés, no una predicción. El duty de régimen de cada planta se
fijó con lo medido, así que coincidir ahí no prueba nada; las rampas y el `coast` sí.

*Hold* de high en ±0.5 (media de 4 semillas, ciclos ≥ 2):

| planta | antes | **kp 0.15, imax 5** | kp 0.2, imax 5 | kp 0.3, ki 0.015, imax 8 |
|---|:-:|:-:|:-:|:-:|
| B | 0.88 | **0.92** | 0.93 | 0.90 |
| A | 0.48 | **0.51** | 0.54 | 0.55 |
| Newn3 | 0.69 | **0.77** | 0.81 | 0.85 |
| estado final de Newn3 | 0.67 | **0.78** | 0.82 | 0.86 |
| duty alto, ext 6 s | 0.76 | **0.85** | 0.88 | 0.90 |
| B × 1.4 (`a` = 15; estrés) | 0.81 | **0.84** | 0.78 | **0.51** |

Con el valor elegido, el peor *hold* de ext sube de 0.28 a 0.47 y la peor denaturación de
0.34 a 0.62. En la planta A, los *holds* sin aprender bajan de 21 a 9.

**Por qué no un `hold_kp` mayor.** Se ve mejor en las plantas lentas, pero se derrumba en la
rápida (0.25: 0.68; 0.3: 0.51), y esa planta no es exagerada: el disco 1 del 21/10 calentaba a
~14 °C/s. Solo 0.15 mejora **en todas**. Fuera del rango medido (`a` × retraso ≈ 17–20 °C,
el doble del máximo medido) ningún juego sirve, incluido el anterior.

**Lo que se probó y no se cambió** (efecto dentro del ruido, salvo lo indicado):

- `hold_ki`: volver a 0.03 empeora la planta A (0.48 → 0.31), así que la bajada a 0.02 del
  usuario fue correcta. Con 0.015 no mejora de forma consistente.
- `ff_learn`, `coast_learn`, `coast_step_max`, `hold_pmax`, `hold_tband`, `hold_win`,
  `ff_slope`: sin mejora consistente.
- `coast_init_cycle` 5–6: mejora los primeros ciclos de Newn3 (0.46 → 0.69–0.74), pero sube
  los primeros picos de la planta rápida de +2.8 a +4.4–5.7 °C, lo que la semilla de 8 evita.

## 11. Ajuste final: tiempo en ±1 °C sin picos (03/11/2026)

**Objetivo (usuario):** el mayor tiempo posible en las temperaturas pedidas. **±1 °C es
tolerable; los picos altos en high y denaturación no.** Quedarse 1 °C abajo cuesta menos que
pasarse.

**Línea base real** (ciclos ≥ 2, sin los ciclos con atasco):

| | A (26/10) | B (26/10) | Newn3 |
|---|:-:|:-:|:-:|
| *hold* de high / low / ext en ±1 | 85 / 100 / 38 % | 93 / 100 / 92 % | 87 / 100 / 92 % |
| denaturación / extensión final en ±1 | 91 / 94 % | 94 / 97 % | **83** / 97 % |
| entrada a ±1 en la denaturación | 1.2 s | 0.6 s | **20.6 s** |
| pico de high: p90 / máximo | +5.7 / +7.7 | +1.9 / +12.3 | +1.75 / +4.2 |
| ciclos con pico > +1 / > +2 °C | 85 / 59 % | 53 / 6 % | 26 / 10 % |
| pico de la denaturación | +7.0 | +3.1 | +0.5 |

**Valores** (`resources/settings.json`; el resto de `pcr_adaptive` no cambia):

| clave | Newn3 | ahora | por qué |
|---|:-:|:-:|---|
| `coast_init` | 4 | **8** | el pico de la denaturación es el único que no se aprende (una rampa por corrida): peor caso de +4.8 a +1.3 °C |
| `coast_min` | 0.5 | **3** | piso del corte: menos picos, sin perder tiempo en banda. Solo actúa en plantas lentas |
| `hold_pmax` | 0.3 | **0.4** | compensa el corte más temprano: la entrada a la denaturación baja a la mitad, con un costo mínimo en picos |
| `hold_kp` | 0.1 | **0.15** | §10.4; sigue siendo el tope seguro para discos rápidos |
| `hold_ki` | 0.02 | **0.015** | sigue la bajada que hizo el usuario: menos oscilación (std en A de 0.68 a 0.57) y mejor extensión final |
| `hold_imax` | 3 | **5** | techo del I ±0.10; 7–8 da peor resultado |
| `coast_margin` | — | **0.5** | clave nueva. Solo high: apuntar al setpoint se pasa en cerca de la mitad de las paradas; 0.5 °C abajo sigue dentro de ±1 y el *hold* termina el acercamiento |

**Banco** (`test_adaptive_nov.py`). Al aplicar la dispersión de la tasa por parada, reproduce
la estadística real de picos, que no se ajustó directamente. Cada corrida con sus propios
ajustes:

| | *hold* high en ±1 | denat en ±1 | entrada a denat (s) | pico p90 | > +1 °C | > +2 °C |
|---|:-:|:-:|:-:|:-:|:-:|:-:|
| Newn3 real | 0.87 | 0.83 | 20.6 | +1.75 | 26 % | 10 % |
| Newn3 simulada | 0.91 | 0.82 | 21.9 | +1.67 | 21 % | 9 % |
| B real | 0.93 | 0.94 | 0.6 | +1.85 | 53 % | 6 % |
| B simulada | 0.98 | 0.98 | 1.7 | +1.26 | 18 % | 3 % |
| A real | 0.85 | 0.91 | 1.2 | +5.74 | 85 % | 59 % |
| A simulada | 0.65 | 0.92 | 2.1 | +5.23 | 85 % | 58 % |

Sigue siendo **algo optimista** (~0.04 en B y Newn3) y B se pasa menos que la real. A oscila de
más en el *hold*. El pico de +7 °C de la denaturación de A es un salto del termopar, que el
banco no pone en esa rampa.

**Resultado** (media de 6 semillas, 35 ciclos, Newn3 → nuevo):

| planta | high en ±1 | high c2–5 | ext en ±1 | denat en ±1 | entrada denat (s) | > +1 °C | > +2 °C | máximo | pico denat |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| Newn3 | 0.91 → **0.93** | 0.80 → 0.86 | 0.96 → 0.97 | 0.82 → **0.91** | 21 → **7.6** | 22 → **9 %** | 7 → **1 %** | +2.8 → +2.2 | 0 → +0.3 |
| estado final de Newn3 | 0.91 → 0.93 | 0.67 → 0.76 | 0.97 → 0.98 | 0.84 → 0.90 | 19 → 11 | 19 → **3 %** | 3 → **0 %** | +2.2 → +1.2 | −0.1 → +0.2 |
| B, ext 22 s | 0.98 → 0.98 | 0.98 → 0.98 | 0.99 → 0.99 | 0.99 → 0.99 | 1.7 → 0.5 | 17 → **7 %** | 2 → **0 %** | +2.1 → +1.7 | **+2.5 → +1.0** |
| rápida (`a` = 15) | 0.96 → 0.96 | 0.92 → 0.92 | 0.91 → 0.94 | 0.97 → 0.99 | 2.1 → 0.8 | 27 → 26 % | 8 → 7 % | +3.2 → +3.1 | **+4.8 → +1.3** |
| A, ext 22 s | 0.71 → 0.74 | 0.68 → 0.69 | 0.89 → 0.90 | 0.96 → 0.96 | 2.4 → 1.9 | 78 → 80 % | 29 → 26 % | +8.1 → +9.0 | +1.6 → +1.5 |
| A, ext 6 s | 0.71 → 0.74 | 0.68 → 0.70 | 0.49 → 0.68 | 0.96 → 0.96 | 2.4 → 1.9 | 74 → 78 % | 36 → 28 % | +8.7 → +7.8 | +1.6 → +1.5 |

**Efecto del margen por sí solo** (mismo juego, `coast_margin` 0 → 0.5). Casi no cuesta tiempo en
banda, y lo gana sobre todo el disco rápido en régimen (B). Con 0.75 baja poco más:

| planta | high en ±1 | ciclos > +1 °C | > +2 °C | máximo |
|---|:-:|:-:|:-:|:-:|
| Newn3 | 0.94 → 0.93 | 10 → 9 % | 3 → 1 % | +2.5 → +2.2 |
| duty alto, ext 6 s | 0.95 → 0.95 | 9 → 6 % | 3 → 2 % | +2.2 → +2.0 |
| B | 0.98 → 0.98 | 14 → 5 % | 1 → 0 % | +2.0 → +1.5 |
| B, ext 22 s | 0.98 → 0.98 | 17 → 7 % | 2 → 0 % | +2.1 → +1.7 |
| rápida | 0.96 → 0.96 | 27 → 26 % | 7 → 7 % | +3.3 → +3.1 |
| estado final de Newn3 | 0.93 → 0.93 | 3 → 3 % | 0 → 0 % | +1.3 → +1.2 |

- **Los picos de A son saltos del termopar**, y ninguna ganancia los corrige; ahí pesa más la
  extensión (también la final, de 0.67 a 0.97).
- **Fuera del rango medido** (`a` × retraso ≈ 17–20 °C) sigue mal con cualquier juego, y en
  una de las dos plantas baja: high 0.33 → 0.28, denat 0.88 → 0.72.
- **Se probó y no se cambió:** `coast_learn 0.3`. Sin `coast_min` parecía ayudar, pero con él
  da lo mismo y converge más lento (high c2–5 en Newn3: 0.85 contra 0.87; en el estado final,
  0.71 contra 0.76). Tampoco `hold_kp 0.2` (§10.4), `hold_imax 7–8`, `coast_step_max`, `ff_learn`,
  `coast_init_cycle` (bajarlo sube los primeros picos) ni `ff_slope` (0.007 lleva el pico de
  denat a +6.5 °C de media).

**Cambios de código** (solo en la rama adaptativa):

- `_adapt_bias_for`: el primer *hold* de high parte del `bias` de la denaturación. En B con
  extensión de 22 s, el *hold* de high del ciclo 1 en ±1 pasa de 0.88 a 1.00. En Newn3 ya daba
  1.00 con las ganancias nuevas.
- `_hold_adaptive` + `_reach_phase`: suelta el freno tras una rampa vencida. La extensión
  atascada termina más cerca (Newn3: −6.4 → −4.3 °C; estado final: −6.8 → −3.7 °C), no en el
  setpoint: en un atasco no alcanza el calor, y el freno vuelve a unos 3 °C. Si el disco se
  realinea durante la fase, el pico sube poco: en ext de +2.0 a +2.3 °C, y en un *hold* de high
  atascado de +1.8 a +2.4 °C.
- **Efecto a vigilar:** con el ángulo mal, el calor cae en una zona del disco que ningún sensor
  ve, y ahora con ~30–40 % más tiempo encendido durante el atasco (c28–29: de ~59 a ~77 s).
  Revisar el disco tras un atasco. Si preocupa, se quita sin tocar lo demás.
- `_ramp_adaptive`: en high aprende contra `setpoint − coast_margin`. La clave también va en
  `DEFAULT_SETTINGS` (0) y en la fila `adaptive` de la metadata; `an_adaptive.py` la reproduce.

**Verificado sin equipo:**

- Control clásico **idéntico a HEAD** en el banco (12 ciclos, dos plantas, todas las métricas).
- `coast_margin 0` **idéntico al código anterior** en adaptativo (15 ciclos, dos plantas, dos
  semillas).
- `test_adaptive.py` y `test_adaptive_26oct.py` contra la copia de HEAD: 0 timeouts; el adaptativo
  sigue muy por encima del clásico; diferencias pequeñas en ambos sentidos con una semilla
  (*hold* del disco rápido 0.93 → 0.89, varias plantas mejoran).
- Pyrefly: ningún error en las líneas nuevas.

**Validar en la próxima corrida** (Newn3 de referencia; resultado en el §12.1):

- [x] Denaturación: entrada a ±1 °C en ≲ 10 s (Newn3 20.6 s) y pico ≤ +1.5 °C.
- [~] *Hold* de high en ±1 ≥ 90 % (Newn3 87 %); ciclos con pico > +2 °C ≲ 5 % (Newn3 10 %). Sí en
      R1 (90 %; 9 % de ciclos, todos antes de c9). No en R2, por los eventos de calor.
- [~] **Sin oscilación:** std del *hold* de high ≲ 0.4 °C. R1 0.21. R2 1.36, sin periodo fijo: son
      los eventos, no el `hold_kp`, y el banco da 0.32 con la misma planta sin eventos.
- [ ] Si hay atasco: consola `power cap released`, y **guardar el log**. Sin atascos en Newn4: sin
      probar. `Stopped--> pos:` marca siempre `0.00°`, así que ese log **no** da el ángulo.

**Aplazado (usuario, 03/11/2026): atacar el ángulo.** Por ahora funciona bien: un episodio cada
~35 ciclos es aceptable (Newn3 tuvo dos, c11 y c28–29). Si vuelve a importar: es la causa de los
atascos y probablemente de los picos, y las ganancias solo los mitigan. Las opciones serían
detectar el atasco (tasa muy baja a potencia plena) y repetir `go_zero`, registrar la posición de
cada parada en la metadata (hoy solo sale por consola) y revisar el homing de
[firmware/Stepper](../firmware/Stepper/README.md).

## 12. Corridas Newn4 (04/11/2026): validación y modelo actualizado

**Corridas.** `files_test/Newn4_pcr_data_20261104_130627.xlsx` (**R1**, inicio 11:39) y
`…_150942.xlsx` (**R2**, 13:46), con consola en `files_test/logpvr.txt` y `logvpr2.txt`.
Receta: 35 ciclos, 85/**40**/62 °C, high y low 15 s, ext 22 s, denat 85 × 120 s, extensión final
120 s, 800 rpm, termopar al mando, valores del §11. Entre las dos solo cambia
`cool_stop_margin_c` (5.5 en R1, 2 en R2). **Fueron dos cámaras distintas** (usuario, 04/11/2026), así
que lo que difiere entre R1 y R2 es de la cámara, salvo que se separe de otro modo.
Los ciclos son los del .xlsx: la consola cuenta uno menos ("cycle 12" es c13).

**El nivel del IR no se usa como evidencia** de la temperatura de la muestra (§12.6): el usuario duda
de esa medición. Lo que sigue se apoya en termopar y `heater_on_s`, salvo donde se indica.

Scripts en `files_test/ajuste_21oct/` (gitignored): `an_eventos.py`, `an_planta_n4*.py`,
`an_ir_ruido*.py`, `test_eventos_energia.py`, `newn4_high_overlay.png`, `newn4_r2_eventos.png`.

### 12.1 El ajuste del §11 cumple donde no hay eventos

Medias por ciclo de los ciclos ≥ 2, mismas definiciones del §11:

| | objetivo | Newn3 | R1 | R2 |
|---|:-:|:-:|:-:|:-:|
| entrada a ±1 en la denaturación | ≲ 10 s | 20.6 s | **8.6 s** | 9.8 s |
| pico de la denaturación | ≤ +1.5 °C | +0.5 | **+0.07** | −0.37 |
| denaturación en ±1 | — | 83 % | 84 % | **48 %** |
| *hold* de high en ±1 | ≥ 90 % | 87 % | **90 %** | **46 %** |
| ciclos con pico > +2 °C | ≲ 5 % | 10 % | 9 % | **71 %** |
| std del *hold* de high (°C) | ≲ 0.4 | 0.29 | **0.21** | 1.36 |
| *hold* de ext en ±1 | — | 92 % | 96 % | 85 % |
| extensión final en ±1 | — | 97 % | 99 % | 97 % |
| timeouts | — | 4 | 0 | 0 |

- **R1:** los tres ciclos con pico > +2 °C son c4, c5 y c8. De c9 a c35 el pico máximo es +0.99 °C.
  El `coast` de high queda en `coast_min` (3 °C) desde c6: el pico rápido se queda ~1 °C bajo el
  objetivo y el *hold* termina el acercamiento sin pasarse.
- **`coast kept`:** ya probado en el equipo, en R2 (c13, c14, c32 y c33, con 21–25 °C/s).

### 12.2 Eventos de calor (lo nuevo)

En R2 **no hay rampas rápidas**, como sugería la tasa máxima: hay saltos discretos. El termopar
sube despacio, queda atrasado, y de pronto salta 10–20 °C en ~1 s. También ocurre en pleno *hold*,
con el motor parado. Detector: el crudo sube ≥ 4 °C en ≤ 0.6 s a más de max(2·`a`, 8) °C/s, lo que
el heater no puede dar.

| | A | B | Newn3 | R1 | R2 |
|---|:-:|:-:|:-:|:-:|:-:|
| eventos (sin los de arranque) | 37 | 2 | 6 | **0** | **40** |
| ciclos con evento | 29 | 1 | 4 | 0 | 24 |
| en `high_ramp` / `high_hold` | 28 / 4 | 1 / 0 | 4 / 0 | 0 / 0 | 22 / 17 |
| salto del termopar, mediana (°C) | 15 | 20 | 12 | — | 10 |
| salto del IR, mediana (°C) | 9 | 16 | 9 | — | 7.4 |

Lo que los datos muestran en R2:

- **Casi siempre coinciden en el tiempo con el IR:** 26 de sus 29 saltos caen a ±1.5 s de uno del
  termopar (A: 29 de 32), y unos 16 de los ~40 del termopar no tienen par en el IR. Aquí solo cuenta el
  *cuándo*, no el nivel. Van por buses distintos (SPI e I2C).
- **Umbral de temperatura:** ninguno por debajo de ~65 °C en el termopar. A potencia plena, la tasa
  sube de 0.09 /s (65–68 °C) a 0.24 /s (74–77 °C) y 0.28 /s (77–80 °C). Son pocos eventos por tramo
  (3–6).
- **Depende de la potencia.** En el *hold*, excluyendo 5 s tras cada evento: **0 eventos en 211 s con
  duty ≤ 0.45, y 9 en 98 s con duty > 0.45**. Hay un confundidor: el duty alto ocurre cuando el
  termopar está bajo.
- **Salta hacia un nivel, no una cantidad:** el salto se correlaciona −0.71 con la temperatura de
  partida; el pico queda en ~87 °C en la rampa y ~90 °C en el *hold*.
- **Sin memoria aparente:** 10 de 34 ciclos sin evento en R2, y un proceso de tasa constante daría
  ~1/3. Aumentan hacia c11–17, cuando también crece el desfase IR − termopar.

- **No parece ruido eléctrico:** casi todos son subidas (R2: 42 subidas y 1 bajada rápidas), con una
  caída de segundos. 22 de 39 en R2 y 28 de 32 en A llegan con el heater encendido sin interrupción
  los 2 s previos, sin flancos que induzcan.
- **Dependen de la cámara:** R1 0 y R2 40, el mismo día. También A 37 y B 2, mismo disco. Esto no
  descarta el cableado si al cambiar de cámara se mueve el cable del termopar.

**Prueba de energía, sin el IR: el salto no parece calor neto en la muestra.** Ciclos con evento
contra sin evento, sin la tendencia lenta (`an_ir_ruido2.py`, `test_eventos_energia.py`):

| | R2 real | A real | banco: todo lectura | banco: mitad real | banco: todo real |
|---|:-:|:-:|:-:|:-:|:-:|
| heater en rampa + *hold* (s) | **+0.41 ± 0.23** | +0.38 ± 0.33 | −0.30 a +0.14 | −0.85 a −1.80 | −1.84 a −2.13 |

Si el salto sumara calor a la muestra, el heater tendría que entregar menos, y entrega lo mismo o algo
más. El tiempo de motor hasta 60 °C tampoco cambia (−0.10 s, std 0.8), aunque esa medida no separa los
casos en el banco. El estadístico es ruidoso en el banco: son dos tandas de 6 semillas.

**Quedan dos candidatas, sin confirmar:** un artefacto de contacto del termopar en esa cámara, o calor
local que le llega al sensor sin cambiar el total (una burbuja que mueve líquido, por ejemplo). Mirar
la cámara durante una corrida sigue siendo la prueba: si es lo segundo, habría que ver la burbuja en
las cámaras con eventos y no en las otras.

**Consecuencia para el control:** el salto entra por la lectura y ninguna ganancia lo corrige. El
termopar se pasa, el control corta, la muestra se enfría, el P empuja con duty > 0.45 y puede venir
otro: en c13 hay tres en 15 s. **Si es lectura, los picos no son de la muestra y el daño va al revés:**
en el banco, la muestra queda 1.5 °C bajo el setpoint de media en el *hold* (42 % en ±1). Además
contamina el aprendizaje: de las 22 rampas con evento, solo 4 quedaron filtradas por `jump_cps`; las
demás mueven el `coast`, que oscila entre 3.7 y 9.5 °C.

### 12.3 Lo que varía entre corridas y durante una corrida

**Entre corridas varía el acople del heater, no la masa.** La tasa en frío cae a un tercio, y las
pérdidas casi no cambian:

| | denat_rate (°C/s) | `a` ajustada (°C/s) | duty denat > 60 s | enfriamiento a 70 °C (°C/s) | pasivo a 62 °C (°C/s) |
|---|:-:|:-:|:-:|:-:|:-:|
| A (26/10) | 9.7 | 6.1 | 0.17 | −1.2 | −0.45 |
| B (26/10) | 9.0 | 10.7 | 0.14 | −1.1 | −0.45 |
| Newn3 (02/11) | 6.0 | 3.2–6.7 | 0.28 | −1.0 a −2.1 | −0.25 a −0.8 |
| R1 (04/11) | 4.6 | 4.2–5.0 | 0.31 | −1.3 a −1.6 | −0.4 a −0.6 |
| R2 (04/11) | 3.0 | 3.7–4.0 | 0.38 | −1.3 a −1.5 | −0.3 |

Si creciera la masa, bajarían la tasa y las pérdidas, y el duty se quedaría igual. Aquí baja la
tasa, sube el duty y `denat_rate × duty` se mantiene en 1.1–1.7 °C/s. Es deducción, con dos
matices: se realineó la montura tras el 26/10, y el 21/10 ya había dispersión (14.2 / 8.4 / 8.7).
Los tres días con varias corridas van a menos dentro del día, pero cada corrida fue otro disco o
cámara, así que no prueba una deriva. **`denat_rate` es el control más simple de este acople.**

**Durante la corrida se calienta el ambiente, no crece la masa.** En Newn4, `a` no cae (R1 4.2 → 5.0,
R2 3.9 → 4.0), y la `k` del enfriamiento casi no cambia (0.046 → 0.04). Lo que cambia, de c2–8 a c21–35:

| | R1 | R2 |
|---|:-:|:-:|
| tasa a 70 / 52 °C con motor | −1.62 → −1.34 / −0.79 → −0.62 | −1.50 → −1.33 / −0.68 → −0.58 |
| duty de ext / low | 0.17 → 0.14 / 0.02 → 0 | 0.18 → 0.15 / 0.01 → 0 |
| motor girando (s) | 35 → 43 | 46 → 57 |
| de cruzar el margen hasta `low` + 0.5 (s) | 17 → 43 | 5 → 12 |

Todo esto cuadra con un ambiente efectivo que sube ~5 °C (de ~34 a ~38 °C en el banco): es deducción,
porque nada lo mide directo. **A 40 °C casi no queda gradiente**, y por eso el enfriamiento pesa tanto
en esta receta. La columna `t_amb` (desde el 04/11/2026,
[pcr_csv_ciclo_fase.md](pcr_csv_ciclo_fase.md) §7) dará un indicio en la próxima corrida: es la
temperatura del encapsulado del MLX, no la del aire.

**Margen de parada.** Como R1 y R2 son cámaras distintas, sus 84 s contra 69 s de enfriamiento no lo
separan; se separa en el banco, con la misma planta:

| enfriamiento (s), ciclos 2–5 / ≥ 18 | margen 5.5 | margen 2 |
|---|:-:|:-:|
| planta de R1 | 57 / 83 | 49 / 63 |
| planta de R2, sin eventos | 62 / 90 | 54 / 67 |

Sin cambio en el *hold* de low, high ni ext. Son 8–23 s menos por ciclo, a favor de 2.

**La tasa por parada se sostiene a medias sin el IR.** Misma parada contra otra, con ventanas que evitan
los eventos:

| correlación, misma / otra parada | A | B | Newn3 | R1 | R2 |
|---|:-:|:-:|:-:|:-:|:-:|
| duty de high(c) con ext(c−1) / ext(c) | +0.14 / −0.25 | −0.46 / +0.42 | +0.40 / +0.07 | **+0.44 / −0.08** | +0.46 / +0.14 |
| tasa del termopar | — | — | — | **+0.62 / 0.00** | +0.65 / +0.54 |

R1 y Newn3 la apoyan, R2 solo en el duty, y B va al revés. Las correlaciones del §10.3 son del IR. La
dispersión de la tasa del termopar es del 11 % en R1 y del 16 % en R2.

**El retraso del termopar llega a 2.3 s** (`fit_step.py`, ajustado con la `low` real):

| | `a` (°C/s) | retraso (s) | `a` × retraso (°C) | `coast` de ext usado (°C) |
|---|:-:|:-:|:-:|:-:|
| R1 c2–8 / c9–20 / c21–35 | 4.2 / 4.4 / 5.0 | 1.20 / 1.06 / 0.76 | 5.0 / 4.6 / 3.8 | 4.4 / 4.2 / 3.7 |
| R2 c2–8 / c9–20 / c21–35 | 3.9 / 3.7 / 4.0 | 2.30 / 2.03 / 1.56 | 9.1 / 7.5 / 6.2 | 6.5 / 5.2 / 5.0 |

En R1, el `coast` de ext coincide con `a` × retraso y sigue su tendencia. En R2 queda en 70–80 % de
ese producto, y su retraso se mide con el peor ajuste (rms 0.29–0.35 °C).

### 12.4 Bloqueo del aprendizaje en la denaturación (R2)

`Adaptive h_denat: duty not learned (mean err +0.93 °C over 60.0 s)`. El duty real es 0.375 y el
modelo da 0.194. En equilibrio: 0.194 + I 0.086 (saturado) + P 0.104 = 0.384. El *hold* se estabiliza
~1 °C abajo, con std 0.10 °C. Ese error supera los 0.75 °C del umbral, y **no aprende justo cuando el
modelo está más equivocado**. El primer *hold* de high tampoco hereda nada.

El umbral protege de un *hold* pasado, que mide duty 0. Uno por debajo mide un duty válido.
**Propuesta, sin implementar:** admitir error positivo hasta ~2 °C y dejar 0.75 °C para el negativo.
Bajar el umbral a 0.3 °C, como planteaba el §8.5, agravaría este bloqueo.

### 12.5 Banco actualizado

`test_adaptive_nov.py`, plantas `N4a` (R1) y `N4b` (R2), con cuatro agregados: receta y margen por
planta, ambiente que sube (`ta_f`), eventos (`ev_*`, tasa
0.5·(u − 0.4)·(T − 62)/20 por segundo, todo en la lectura) y `real_stats`, que aplica las **mismas
métricas** a la corrida real. **No usa el IR.** Modos `calib4` y `decomp`. Las plantas viejas dan
exactamente lo mismo que antes (C, A y B22, 14 ciclos). Media de 6 semillas:

| | high ±1 | high c2–5 | ext ±1 | denat ±1 | pico p90 | pico máx | > +1 | > +2 | std | rampa high (s) | enfriamiento (s) | duty high / ext |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| R1 real | 0.90 | 0.67 | 0.96 | 0.84 | +1.65 | +2.48 | 18 % | 9 % | 0.21 | 7.7 | 84 | 0.30 / 0.15 |
| R1 simulada | 0.96 | 0.83 | 0.98 | 0.82 | +0.79 | +1.46 | 4 % | 0 % | 0.15 | 7.8 | 83 | 0.31 / 0.16 |
| R2 real | 0.46 | 0.89 | 0.85 | 0.48 | +6.89 | +9.29 | 91 % | 71 % | 1.36 | 9.2 | 69 | 0.32 / 0.16 |
| R2 simulada | 0.45 | 0.53 | 0.90 | 0.30 | +7.09 | +13.31 | 86 % | 63 % | 1.41 | 8.4 | 67 | 0.34 / 0.18 |

También reproduce que `h_denat` no aprende en R2 (3 de 3 semillas) y sí en R1, sin ajustar nada para
eso salvo el duty de la denaturación.

**Dónde falla:**

- Sigue optimista sin eventos: en R1 no da los picos tempranos, y el ±1 de c2–5 sale 0.16 mejor.
- En R2 pone los primeros ciclos peor que los reales (0.53 contra 0.89), y se pasa en el pico máximo
  (+13 contra +9) y en el `coast` de high final (9.3 contra 5.3).
- Subestima los picos de ext de R2 (> +1 °C en 44 % contra 91 %): no tiene la cola lenta.
- `denat_mult` (1.14) es un ajuste sin explicación: R2 pidió 0.375 en la denaturación y ~0.32 en los
  *holds*. La entrada a la denaturación de R2 no vale como métrica, porque se queda justo en −1 °C.
- La forma del evento (nivel, ev_tau 3 s) se eligió para reproducir la estadística, **no es una medida
  del fenómeno**. Lo calibrado son R1 y R2: no es una predicción independiente.

**Descomposición (simulada):** con cuánto se queda cada planta con y sin eventos.

| planta | high ±1 | > +2 °C | std | `coast` de high final |
|---|:-:|:-:|:-:|:-:|
| R1, sin eventos | 0.96 | 0 % | 0.15 | 3.1 |
| R1, con los eventos de R2 | 0.63 | 59 % | 0.86 | 6.1 |
| R2, sin eventos | 0.87 | 7 % | 0.32 | 3.4 |
| R2, con eventos | 0.45 | 63 % | 1.41 | 9.3 |

Los eventos explican la mayor parte de la caída de R2: 0.42 de ±1, contra 0.09 del retraso.

### 12.6 Validez del IR

El usuario duda de la medición por ruido inducido en los cables. Las pruebas están en
[ir_vs_termopar.md](ir_vs_termopar.md) §8: no aparece la firma de ruido, pero su nivel cambia hasta
~3 °C de una parada a otra y hasta 9 °C entre cámaras. **Dejó de usarse:** "la muestra estaba a X °C
según el IR", la zona caliente deducida del desfase IR − termopar y la fracción `ev_real` 0.5 del
banco. **Sigue en pie sin él:** los eventos y su umbral, el acople, el ambiente, el retraso del
termopar y el bloqueo de `h_denat`.

**Por validar:** la causa de los eventos (ver la cámara), PEC en la lectura del MLX, y `t_amb` y
`denat_rate` en las próximas corridas.

__author__ = "Edisson A. Naula"
__date__ = "$ 04/11/2026 $"
