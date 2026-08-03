# Eje temporal real de la curva de temperatura (PCR)

El plot de temperatura de [ui/PcrFrame.py](../ui/PcrFrame.py) y el eje del tab de
análisis pasan de **índice de muestra** a **segundos reales medidos**. Este documento
existe porque el cambio nace de corregir una premisa equivocada que contaminaba dos
subsistemas a la vez, y porque varias de sus decisiones son *no hacer algo*.

## 1. La premisa equivocada: `ts_pcr` nunca fue la cadencia

`pidControllerRPM.ts_pcr` (0.1 s en [resources/settings.json](../resources/settings.json))
es el **periodo del lazo PI**: se lee una sola vez en `experiment_pcr` y se pasa a
`_load_phase_pid`, `hold_temperature` y `spinMotorRPM_ramped`. **Nunca compuertó la
adquisición.**

Las muestras entran por otro camino: `data_temperature.append` vive dentro de
`update_displayed_temperature`, que es el `on_message` de
[Drivers/ClientUDP.py](../Drivers/ClientUDP.py). Se agrega **una muestra por datagrama
UDP recibido**, y el disco emite cada `sample_ms = 80` ms
([firmware/DiscPCB/emstat_wifi_v1.9.py](../firmware/DiscPCB/emstat_wifi_v1.9.py), gate en
el loop principal).

Consecuencias de tratar `ts_pcr` como cadencia:

- Escala 100 ms vs 80 ms reales → **25 % de error** desde el primer segundo.
- El tab de análisis sintetizaba su eje igual (`xs = arange(n)·dt`, `dt` sembrado de
  `ts_pcr`) y de ahí derivaba `rate = ΔT/Δt`. **Toda tasa °C/s reportada antes de este
  cambio salía ~20 % baja.** Un reporte viejo y uno nuevo del mismo experimento no son
  comparables: no cambió el equipo, cambió la regla.

## 2. La solución: el timestamp ya estaba ahí

`ClientUDP` estampa el instante de recepción y lo entrega en cada callback como
`temps_list[3]`. Solo se usaba para el control de vejez del PID (`self.temp_ts`); nadie
lo acumulaba. Ahora se acumula en `self.data_time` como **segundos relativos** al inicio
de la corrida, en lockstep con las dos curvas de temperatura.

**No se usa `self.temp_ts` para esto.** Cuando el sensor primario falla,
`update_displayed_temperature` fija `temp_ts = 0.8` como centinela de "lectura
antiquísima" para que el PID desconfíe; usarlo como eje mandaría ese punto a 1970. El
eje sale siempre de `temps_list[3]`, exista o no lectura válida.

## 3. Origen único del tiempo (era una carrera real)

El orden anterior era: `init_temperature_graph()` limpia las listas en el hilo principal
→ arranca el hilo del experimento → el hilo crea y arranca el `UdpClient` → **y hasta
después** fijaba `start_pcr_time`. Entre esas dos últimas líneas está el
`from Drivers.DriverStepperSys import ...`, que en su primer import arrastra `gpiod` y
`serial`: decenas de ms. A 80 ms de cadencia, un datagrama puede caer ahí dentro.

Antes eso solo ensuciaba un tick del label. Con eje temporal, esa muestra se fecharía
contra el origen de la corrida anterior → **un punto a miles de segundos que arruina el
`xlim` y queda grabado en el CSV**.

`start_pcr_time` se fija ahora en `callback_start_experiment`, en el hilo principal y
antes de que existan el hilo y el cliente: la carrera desaparece por construcción. Es un
**reloj único** compartido por el plot, el label "Time passed" y la estimación de tiempo
restante, para que una anomalía en la curva se pueda ubicar contra el `State:` del label.

## 4. Ventana deslizante: sigue en muestras

`windows_pcr` se sigue contando en **muestras**, no en segundos. Es un tope de puntos
dibujados (costo de render), no una duración; reinterpretar la clave habría convertido
silenciosamente un `1500` ya persistido de ~2 min a 25 min en equipos en uso. Lo único
que cambió es el `set_xlim`, que ahora toma los extremos de tiempo del tramo visible.

Si algún día se quiere "los últimos N segundos", la puerta limpia es una clave nueva
(`window_pcr_s`), no reciclar esta.

## 5. Unidades: segundos

`set_xlabel("Time (s)")`, igual que la preview teórica del perfil. Es la unidad de las
entradas del protocolo ("Time High (s)", "Denaturing time (s)") y la de las rampas. La
posición absoluta ya la da el label de estado en formato legible, así que el plot no
necesita minutos; una etiqueta que cambia de unidad sola a mitad de corrida es
justamente lo que hace que alguien malinterprete una gráfica en revisión.

## 6. CSV: tercera columna `t_s`

`save_data_temps_file` escribe ahora `[primario, secundario, t_s]` por muestra. El
`zip_longest` cubre un desfase de a lo más una muestra si el paro cayó entre appends.

La fila 0 (metadata, que **nadie parsea** — el loader hace `next(reader, None)`) gana:

- `start: <ISO>` — ancla el eje relativo al reloj de pared sin pagar una columna por
  muestra, para poder correlacionar la corrida con otros logs.
- `cols: <pri>|<sec>|t_s` — identidad de columnas.
- El resumen de cadencia **medido** (`_cadence_summary`): `dt_mean`, `dt_p95`, `dt_max`,
  `n`, `span`.

`ts:` sigue en la metadata y sigue siendo el periodo del lazo PI. **No es la cadencia de
muestreo** — es exactamente la confusión que originó todo esto.

### Por qué se archiva la cadencia

La cadencia no es un parámetro del host: la fija el firmware y la degradan las pérdidas
del broadcast. `ClientUDP` fija `SO_RCVBUF` en 512 bytes a propósito ("leer el paquete
más reciente"): **prefiere descartar datagramas viejos antes que atrasarse**. Cualquier
stall del hilo receptor mayor a la cadencia tira muestras. Medirla y archivarla con el
dato es lo que evita volver a suponerla.

**`dt_max` es el número a mirar.** Si sale ~0.08, la captura está limpia. Si sale en
segundos, hay huecos reales en la curva y toca reabrir la decisión de §9 y revisar ese
buffer de recepción.

## 7. Análisis: tiempo por experimento

El tab superpone varios experimentos, y durante la transición lo normal es mezclar un
run viejo (sin `t_s`) con uno nuevo. Por eso la resolución del eje es **por
experimento**, no global:

- `PcrExperiment.times` — eje real, vacío = corrida sin `t_s`.
- `PcrExperiment.xs(dt, n)` — **único punto** donde se decide entre tiempo real y
  sintético. Sustituye los `arange(n)·dt` dispersos (curvas, overlay secundario, slices
  extraídos con su re-cero, snapping del picado, `set_xlim` de la ventana).
- `seg_metrics` deriva `Δt = t_b − t_a` del eje del experimento.

El campo global pasó a llamarse **"Legacy dt (s)"**: solo rige a los experimentos sin
tiempo real. `load_csv` lo dice en el status ("real time axis" vs "no t_s column —
synthetic axis from Legacy dt") para que nunca sea implícito de cuál de los dos ejes
salió una tasa.

Los segmentos se siguen guardando como **pares de índices**, no de tiempos: los bundles
exportados antes de este cambio siguen importando igual. El bundle gana un registro
`time` para round-trip, análogo al `temp2` que ya existía.

### El fallback legado

`PCR_LEGACY_DT_S = 0.08` en [ui/analysis/pcr.py](../ui/analysis/pcr.py), constante de
módulo. Es una constante **histórica** (la cadencia nominal del firmware cuando se
escribieron esos archivos), no un parámetro de operación — por eso **no** es una clave de
`settings.json`: una clave llamada "sample dt" invita a editarla creyendo que cambia la
adquisición. Sigue siendo una suposición: nunca se midió cuándo se escribieron esos CSV,
y por eso el campo de la pestaña es editable.

## 8. Compatibilidad

| Origen | Qué pasa |
|---|---|
| CSV de 3 columnas (nuevo) | Eje real; `Legacy dt` no se usa |
| CSV de 2 columnas | `times` vacío → eje sintético con `Legacy dt` |
| CSV de 1 columna | Igual, sin overlay secundario |
| Bundle con registro `time` | Round-trip del eje real |
| Bundle sin `time` | Cae al `Legacy dt` |
| Corrida en vivo | `data_time` se siembra junto a las curvas |

Una fila con `t_s` vacío (desfase de a lo más una muestra del `zip_longest`) recorta las
tres series a esa posición: `xs()` asume alineación.

## 9. Lo que NO se hizo, y por qué

- **No se cortan los huecos.** Con eje por índice los paquetes perdidos eran invisibles;
  ahora aparecen como un tramo estirado unido por una recta. Se evaluó insertar `NaN`
  cuando `Δt > k·cadencia`, y se descartó **por ahora**: nadie sabe todavía cuánta
  pérdida real hay, y un umbral `k` sin datos es una perilla que nadie sabrá calibrar.
  El resumen de cadencia de §6 existe justo para contestar esto con la primera corrida.
  Si `dt_max` sale feo, cortar la línea es un cambio de tres líneas.
- **No se tocó `SO_RCVBUF`.** El descarte de datagramas viejos es deliberado. Cambiarlo
  sin medir sería reemplazar una suposición por otra.
- **No se tocó el firmware.** `sample_ms` sigue mandando la cadencia; el host ya no la
  supone, la mide.
- **No hay indicador de Hz en vivo.** El label de estado ya lleva tres líneas y tiene
  historia de crecer sin control. Si en banco hace falta ver la pérdida mientras el motor
  gira, es una línea más.
- **El eje del fotodetector sigue por ciclo.** Alinearlo con la temperatura es otro
  cambio, con su propia justificación.
- **`ts_pcr` no se tocó ni se renombró.** Sigue siendo el periodo del lazo PI, que es lo
  que siempre fue.

## 10. Impacto en datos históricos

Los runs viejos re-analizados dan tasas **~25 % más altas** que las reportadas antes
(`0.1 → 0.08` en el denominador). Las nuevas son las correctas — o más precisamente, las
nuevas se apoyan en una suposición mejor, y las corridas con `t_s` ya no se apoyan en
ninguna. Al comparar reportes de distintas épocas hay que verificar de qué eje salió cada
uno: el status de `load_csv` lo dice al cargar.

## Archivos

- [ui/PcrFrame.py](../ui/PcrFrame.py) — `data_time`, origen en `callback_start_experiment`,
  `update_graph_temperature`, `_cadence_summary`, 3ª columna del CSV.
- [ui/analysis/pcr.py](../ui/analysis/pcr.py) — `PcrExperiment.times` / `xs()`,
  `seg_metrics`, `_read_temp_csv`, `PCR_LEGACY_DT_S`, round-trip del bundle.
- Docs relacionados: [pcr_analisis.md](pcr_analisis.md) §2,
  [temp_source_selector.md](temp_source_selector.md),
  [pcr_temperature_control.md](pcr_temperature_control.md).

__author__ = "Edisson A. Naula"
