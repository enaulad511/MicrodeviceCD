# EmStat — Recuperación de datos perdidos en TCP vía UDP

Diseño para recuperar paquetes del EmStat que se pierden en el camino TCP usando el
**broadcast UDP paralelo** (puerto 5005, el mismo de la temperatura). Estado: firmware
`seq` verificado en hardware; host Fases 0–2 implementadas. El merge de la Fase 2 se
rediseñó el 12/11/2026 porque dañaba los datos (§6).

Lectura previa: [emstat_abort_y_canal.md](emstat_abort_y_canal.md) (cadena de 3 nodos,
fire-and-close, dead-man switch) y [eis_impedancia.md](eis_impedancia.md).

---

## 1. El problema

En Wireshark se observa que, en ciertas corridas, el **Wemos recorta o cierra el TCP**
antes de entregar todo: faltan paquetes `emstat_data` (huecos en la gráfica/CSV) e incluso
el terminal `emstat_end` (la corrida se cuelga hasta pulsar Stop). El **mismo paquete sí
sale por el broadcast UDP (5005)**. TCP no "pierde" por sí mismo (es confiable); la pérdida
es **aguas arriba**, en la bifurcación del Wemos hacia TCP.

Hoy ese UDP se descarta: el `UdpClient` de temperatura filtra `if "UDP" not in text`
([Drivers/ClientUDP.py](../Drivers/ClientUDP.py)) y los mensajes `EMSTAT:` no contienen esa
subcadena. Además, durante un experimento la **telemetría de temperatura se pausa**
(`measuring`/`poll`), así que temp y EMSTAT están **multiplexados en el tiempo** y no
compiten en 5005 — el tap recibe EMSTAT limpio.

## 2. El cimiento: `seq` por mensaje (firmware)

El EmStat **no emite número de secuencia** (el `,14,200` del `raw` es metadata: status +
current-range, diagnóstico — ver manual MethodSCRIPT §"measurement data package"). Por eso
el **Pico** genera la clave, en el único punto por el que pasan todos los mensajes EMSTAT
antes de bifurcarse a TCP+UDP (`send_emstat_line` en `emstat_wifi_v1.7.py`):

- `"seq"` en **todos** los mensajes EMSTAT (data + terminales + marcadores).
- Reinicia a 0 en `emstat_start`; incrementa por mensaje.
- Idéntico en TCP y UDP para el mismo paquete (un solo `uart_link.write`).
- Granularidad **1 mensaje = 1 P-line** (no agrupa).

Verificado en hardware: `…"type": "emstat_data", "seq": 106`. Espejo del firmware y diff:
[firmware/DiscPCB/](../firmware/DiscPCB/README.md).

## 3. Arquitectura del host (toda en `ui/EventEmstatFrame.py`, salvo el parser)

- **Socket UDP dedicado** en `EventPlotter`, creado en `start()` / cerrado en `stop()`,
  con `SO_REUSEADDR` + `SO_BROADCAST` + **RCVBUF grande** (no 512). Convive con el socket
  de temperatura porque EMSTAT es **broadcast en 5005**. En dev/Windows va en `try/except`
  y degrada a TCP-only.
- **Hilo lector UDP** propio → cola `q_udp_lines`. Parseo defensivo: `text.find("EMSTAT:")`
  (tolera prefijos basura como `(ECr|)`), `json.loads`, descarta lo inválido.
- **Dos instancias de `EmstatStreamParser`** (una por transporte): el parser es *stateful*
  (`cycle`/`direction`); mezclar dos copias en uno corrompería el contexto.
- **El control sigue por TCP**: enviar MethodSCRIPT, keepalive y ABORT no cambian. "Solo
  UDP" = leer datos por UDP, pero **disparar** el experimento siempre por TCP.
- **Selector TCP/UDP** en la fila de controles de `EventPlotter`, fijado **antes** de Start,
  **default TCP** (comportamiento actual intacto). Solo decide qué transporte alimenta la
  gráfica/CSV; ambos cuentan cobertura siempre.

### Cambio crítico: desacoplar el fin de corrida del cierre de TCP

Hoy, cuando el servidor cierra el TCP, `_tcp_reader` hace `stop_event.set()`
([EventEmstatFrame.py:481](../ui/EventEmstatFrame.py)), lo que **mataría también el hilo
UDP** justo cuando se necesita para recuperar el final. Nuevo modelo: el cierre de TCP
**solo detiene el lector TCP**; la corrida termina por

1. **primer terminal de cualquier transporte** (`emstat_end`/`error`/`aborted`/`maxtime`/
   `timeout`), con **gate anti-rezago** (solo se honra tras ver `emstat_start`/data de la
   corrida actual, para que un broadcast viejo no corte la nueva);
2. **Stop** del usuario;
3. **watchdog de inactividad total** (~5–10 s sin paquetes en *ambos* transportes).

## 4. Fases

| Fase | Qué hace | Depende de |
|---|---|---|
| **0 — Diagnóstico** | Tap paralelo: ambos transportes leen y parsean siempre; cada uno mantiene un `set()` de `seq` de paquetes `data`. Al cerrar, **resumen en consola**: conteos TCP/UDP, `udp−tcp` (evidencia de la hipótesis), `tcp−udp` (si UDP también pierde). Gráfica por el transporte seleccionado. | `seq` |
| **1 — Terminales** | El primer terminal de cualquier transporte cierra limpio (`send_abort=False`; el experimento ya terminó en el Pico). Arregla el cuelgue por `emstat_end` perdido. | — |
| **2 — Merge de datos** | TCP primario live como hoy; ambos transportes guardan la **línea cruda** por `seq`. Al cerrar, si el primario perdió algún `seq`: re-parsear la unión con **un** parser, redibujar y reemplazar la corrida en `total_data`; si no perdió nada, no se toca. Rediseñado el 12/11/2026, ver §6. | `seq` |

## 5. Limpieza del parser y mejoras relacionadas

- **`_parse_packet` (hecho):** antes malinterpretaba la metadata `,14,200` como
  `state`/`index` (un `event["point"]` basura). Ahora la decodifica correctamente:
  cada token es `<id><valor_hex>`, `id=1`→`status`, `id=2`→`current_range` (diagnóstico).
  El evento expone `status` y `current_range` (listas, una entrada por sub-campo) y se
  eliminó el `point`/`index` falso.
- **IDs de técnica de medición (hecho):** `EmstatStreamParser.TECHNIQUE_IDS` mapea la
  Tabla 5 del manual (marcador `M<hex>`: `0x05`=CV, `0x02`=SWV, `0x0D`=EIS, …). El evento
  `method` ahora trae `method_name`.
- **Estado final visible (hecho):** antes `stop()` pisaba siempre la etiqueta de estado
  con `"Status: stopped"`, borrando el mensaje terminal recién publicado
  (`End of experiment (via …)`, errores, watchdog, etc.), y `_reconcile_merge` la volvía
  a pisar con el resumen del merge. Ahora `stop()` solo escribe `"Stopped by user."`
  cuando `_terminated` es `False` (stop manual), y `_reconcile_merge` **anexa** su
  resumen al estado terminal en vez de reemplazarlo:
  `"End of experiment (via TCP). Merge: 250 pts (+3 recovered)"`.
- **Fin de experimento con preprocesamiento (firmware, hecho):** el Pico terminaba en
  *cualquier* línea en blanco, así que con varios `meas_loop` antes del método principal
  (p.ej. acondicionamiento antes de EIS) terminaba antes de tiempo. Ahora el fin normal es
  `'*'` (fin de meas_loop) **seguido** de una línea en blanco; las blanks entre sub-loops se
  ignoran. Cambio en `run_experiment_read_loop` (`emstat_wifi_v1.7.py`, requiere reflasheo).

## 6. El merge dañaba los datos (corregido 12/11/2026)

**Síntoma (usuario, mediciones CV):** la gráfica en vivo se veía bien y, al terminar,
"la corrección" la dañaba.

**Causa.** El merge guardaba por `seq` el **evento ya decodificado** (`merged_by_seq`,
el primer transporte que lo trajera ganaba) y al cerrar los mezclaba. Pero cada transporte
tiene **su propio** `EmstatStreamParser` con estado (`cycle` por marcador `C`, `direction`
por `-`, índice de tiempo de CA, `_ca_main_started` por `*`). Si UDP perdía un marcador `C`,
su parser seguía en el ciclo anterior; cuando TCP perdía un dato de ese ciclo, el hueco se
rellenaba con el evento del parser UDP → **un punto con el ciclo anterior en medio del
ciclo**. Al redibujar, ese punto se agrega a la línea del ciclo anterior, que traza una
recta gruesa desde su final hasta él. Además, si el que perdía el `C` era TCP, el merge no
lo arreglaba; y en CA un hueco dejaba `t_s` duplicados (`…0.4, 0.4…`).

**Evidencia** en `files/CV` (archivos del 09–10/11, Keep runs): saltos de ciclo de 1 punto
dentro de una corrida, siempre al ciclo anterior, p.ej. r1 de `…20261109_204521`:
`[(0,216), (1,216), (2,209), (1,1), (2,7)]`; también `…20261110_182504` r1 y
`…20261110_190221` r3. E e I del punto son continuos con sus vecinos: el dato era bueno,
solo la etiqueta salía mal. Un simulador (pérdida controlada por transporte, código real de
`EventPlotter`) reproduce la misma huella.

**Diseño nuevo** ([EventEmstatFrame.py](../ui/EventEmstatFrame.py) `_reconcile_merge`):

- Cada transporte guarda `raw_by_seq[source][seq] = raw` de **todo** `emstat_data`
  (datos y marcadores). Ya no se guardan eventos decodificados.
- Al cerrar: si el primario **no perdió ningún `seq`**, `total_data` y la gráfica **no se
  tocan** (lo guardado es exactamente lo que se vio en vivo; status `Merge: no gaps`).
- Si perdió alguno (dato o marcador): se re-parsea la unión ordenada por `seq` con **un
  parser nuevo** (mismos `parser_kwargs` de la corrida, congelados en `start()`); si ambos
  traen el `seq`, gana el primario. Así `cycle`/`direction`/`t_s` salen de un estado único,
  y un marcador perdido en TCP se recupera del UDP.
- Columna `recovered` en la hoja `data` (1 = punto que no se vio en vivo): filtrar
  `recovered == 0` da la gráfica en vivo.
- Hoja `raw` (`run, seq, tcp, udp, raw`): la unión cruda, para re-derivar o auditar
  offline. Si un mismo `seq` trae `raw` distinto por cada transporte, se usa el primario
  y se cuenta en consola.
- `_reconcile_merge` corre una sola vez por corrida (`_reconciled`): `stop()` puede
  entrar dos veces (botón + procesador) y antes duplicaba el merge.
- Se quitó el `total_data.append(storage_dict.copy())` de `stop()`: `storage_dict` nunca
  se llenaba y metía una fila vacía cuando el merge no reemplazaba la corrida.

Lo que sigue sin resolverse: un `seq` que pierden **ambos** transportes. En CA eso corre
`t_s` un intervalo desde ahí (el índice cuenta paquetes recibidos); calcular `t_s` desde el
`seq` lo evitaría, pendiente.

## 7. A verificar en hardware

- [x] El `seq` aparece, incrementa y es idéntico en TCP y UDP (Wireshark) — **OK (`seq:106`)**.
- [ ] Dos sockets en 5005 (temp + tap) **ambos reciben** el broadcast en la Pi (Linux,
      `SO_REUSEADDR`).
- [ ] Fase 0: `udp−tcp` no vacío confirma la pérdida solo-TCP; `tcp−udp` mide si UDP también
      pierde.
- [ ] Fase 1: matar el TCP a mitad de corrida y confirmar que el terminal por UDP cierra
      limpio (sin colgarse).
- [ ] §6: corrida CV con Keep runs; si la consola dice `rellenados del otro transporte`,
      comprobar que la gráfica final no tiene trazos cruzados y que los ciclos de la hoja
      `data` son monótonos por corrida.

---

__author__ = "Edisson A. Naula"
__date__ = "$ 12/11/2026 $"
