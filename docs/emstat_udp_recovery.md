# EmStat — Recuperación de datos perdidos en TCP vía UDP

Diseño para recuperar paquetes del EmStat que se pierden en el camino TCP usando el
**broadcast UDP paralelo** (puerto 5005, el mismo de la temperatura). Estado: **Paso 0
(firmware `seq`) implementado y verificado en hardware**; host pendiente (Pasos 1–5).

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
| **2 — Merge de datos** | TCP primario live como hoy; UDP se bufferea por `seq`. Al cerrar: `faltantes = seq_udp − seq_tcp` → insertar ordenado por `seq`, **redibujar la gráfica completa** y mezclar en `total_data` para que Save guarde el dataset completo. | `seq` |

## 5. Limpieza del parser y mejoras relacionadas

- **`_parse_packet` (hecho):** antes malinterpretaba la metadata `,14,200` como
  `state`/`index` (un `event["point"]` basura). Ahora la decodifica correctamente:
  cada token es `<id><valor_hex>`, `id=1`→`status`, `id=2`→`current_range` (diagnóstico).
  El evento expone `status` y `current_range` (listas, una entrada por sub-campo) y se
  eliminó el `point`/`index` falso.
- **IDs de técnica de medición (hecho):** `EmstatStreamParser.TECHNIQUE_IDS` mapea la
  Tabla 5 del manual (marcador `M<hex>`: `0x05`=CV, `0x02`=SWV, `0x0D`=EIS, …). El evento
  `method` ahora trae `method_name`.
- **Fin de experimento con preprocesamiento (firmware, hecho):** el Pico terminaba en
  *cualquier* línea en blanco, así que con varios `meas_loop` antes del método principal
  (p.ej. acondicionamiento antes de EIS) terminaba antes de tiempo. Ahora el fin normal es
  `'*'` (fin de meas_loop) **seguido** de una línea en blanco; las blanks entre sub-loops se
  ignoran. Cambio en `run_experiment_read_loop` (`emstat_wifi_v1.7.py`, requiere reflasheo).

## 6. A verificar en hardware

- [x] El `seq` aparece, incrementa y es idéntico en TCP y UDP (Wireshark) — **OK (`seq:106`)**.
- [ ] Dos sockets en 5005 (temp + tap) **ambos reciben** el broadcast en la Pi (Linux,
      `SO_REUSEADDR`).
- [ ] Fase 0: `udp−tcp` no vacío confirma la pérdida solo-TCP; `tcp−udp` mide si UDP también
      pierde.
- [ ] Fase 1: matar el TCP a mitad de corrida y confirmar que el terminal por UDP cierra
      limpio (sin colgarse).

---

__author__ = "Edisson A. Naula"
