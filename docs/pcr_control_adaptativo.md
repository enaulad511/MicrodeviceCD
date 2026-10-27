# Control adaptativo de PCR (opcional)

> **26/10/2026:** el guardado pasó a `.xlsx` ([almacenamiento_por_experimento.md](almacenamiento_por_experimento.md)): `-adaptive: …` es la fila `adaptive` de la hoja `metadata`; la config completa queda además en la hoja `settings`.
>
> **26/10/2026, validado en el equipo** en dos cámaras (§6): los *holds* mejoran contra el clásico en las dos. Se encontraron cuatro problemas y un ciclo anómalo (§7). Decisiones en el §8; arreglos verificados en tiempo virtual en el §9, **pendientes de correr en el equipo**.

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
  65 °C).
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
| `jump_cps` | 20 °C/s | subida que se toma como salto del termopar: esa rampa no enseña (0 = no filtra) |
| `coast_min`, `coast_max` | 0.5, 12 °C | límites del corte |
| `coast_window_s` | 8 s | espera máxima de la inercia |

## 4. Qué queda registrado

- **Consola,** en cada rampa y en cada *hold*:
  `Adaptive ext ramp: cut at 56.9 °C (coast 7.1), peak 64.9 °C → coast 7.0 °C` y
  `Adaptive h_high: duty 0.202 (mean err −0.03 °C) → bias 0.203` (o `not learned`). Una
  rampa con salto del termopar imprime
  `…, peak 92.3 °C, rise 31 °C/s (thermocouple jump) → coast kept`.
- **Metadata** (fila `adaptive`): `off`, o la config y lo aprendido al final
  (`on … pmax 0.3 coast init 4/8C learn 0.5 step 2C jump 20C/s | bias h_high 0.212 … |
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

__author__ = "Edisson A. Naula"
__date__ = "$ 26/10/2026 $"
