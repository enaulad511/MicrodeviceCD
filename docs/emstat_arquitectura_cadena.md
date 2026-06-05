# EmStat — Arquitectura de la cadena de tres nodos

Diagramas de referencia de la ruta completa host ↔ EmStat para los experimentos
electroquímicos (CV / SWV / EIS). Acompaña a [emstat_udp_recovery.md](emstat_udp_recovery.md),
[emstat_swv_y_fiabilidad_uart.md](emstat_swv_y_fiabilidad_uart.md) y
[emstat_abort_y_canal.md](emstat_abort_y_canal.md).

---

## 1. Vista física: nodos, transportes y enlaces

```
┌──────────────────────────┐         ┌───────────────────────┐         ┌─────────────────────────┐        ┌──────────┐
│   App Python (este repo) │         │   Wemos D1 mini       │         │   Pico 2                │        │  EmStat  │
│   Raspberry Pi           │         │   (ESP8266)           │         │   (MicroPython)         │        │  Pico    │
│                          │         │                       │         │                         │        │ (PalmSens)│
│  ui/EventEmstatFrame.py  │         │  WemosD1Mini.ino      │         │  emstat_wifi_v1.7.py    │        │          │
│  Drivers/EmstatUtils.py  │         │                       │         │  EmstatDrivers.py       │        │          │
└─────────┬────────────────┘         └───────┬───────────────┘         └────────┬────────────────┘        └────┬─────┘
          │                                  │                                  │                              │
          │   TCP :5006  (control + datos)   │                                  │                              │
          │ ───────────────────────────────► │                                  │                              │
          │ ◄─────────────────────────────── │   UART_LINK  GP8(TX)/GP9(RX)     │                              │
          │      EMSTAT:<json> de vuelta      │      230400 baud                 │   UART_EMSTAT GP0(TX)/GP1(RX)│
          │                                   │ ◄──────────────────────────────► │      230400 baud             │
          │   UDP :5005  broadcast            │                                  │ ◄──────────────────────────► │
          │ ◄─────────────────────────────── │ ◄────────────────────────────────┤   (MethodSCRIPT + resultados)│
          │   EMSTAT:<json>  y  UDP:<temp>    │   (el Wemos bifurca a TCP+UDP)   │                              │
          │                                   │                                  │                              │
   tap UDP dedicado +                    fork TCP+UDP                   genera script,                    mide; celda
   socket temp 5005                      (broadcast)                    lee respuesta,                    + electrodos
                                                                        inyecta "seq"
```

- **App ↔ Wemos:** TCP **5006** (control: envía el payload JSON del experimento, keepalive,
  ABORT; recibe los `EMSTAT:<json>`). UDP **5005** broadcast (recibe los `EMSTAT:` en
  paralelo — *tap* de recuperación — y la temperatura `UDP:<...>`).
- **Wemos ↔ Pico:** UART_LINK, **GP8/GP9 @ 230400**. Líneas con prefijo `UDP:` o `EMSTAT:`.
- **Pico ↔ EmStat:** UART_EMSTAT, **GP0/GP1 @ 230400**. MethodSCRIPT crudo (con **pacing de
  5 ms/línea**, ver [SWV/UART](emstat_swv_y_fiabilidad_uart.md)).

## 2. Flujo de CONTROL (arrancar un experimento)

```
Usuario ▶ Start
   │
   ▼
EventEmstatFrame.start()                      payload JSON  {"method":"sqwv","ch":0,"E_b":...}
   │  abre socket TCP 5006, envía payload ───────────────────────────────────────────────┐
   ▼                                                                                       ▼
Wemos handleTcpRx():  reenvía la línea TCP al Pico como  EMSTAT:<json>\n  (UART_LINK)
   │
   ▼
Pico process_uart_rx() → handle_command(obj)
   │   • valida canal MCP (ch 0-7) → _activate_channel
   │   • emite  EMSTAT:{"type":"emstat_start", "seq":0, "params":..., "ch":...}
   │   • construye MethodSCRIPT (EmstatDrivers.construc_*)
   │   • EmstatPico.send_script → write_lines() ── pacing 5 ms/línea ──► UART_EMSTAT
   ▼
EmStat: parsea el script.  Si hay error de sintaxis → "e!<hex>: Line L, Col C"
                           Si OK → ejecuta y va emitiendo paquetes de medición
```

## 3. Flujo de DATOS / RESULTADOS (durante la medición)

```
EmStat ──(UART_EMSTAT)──► Pico run_experiment_read_loop()
                              │  por cada línea cruda del EmStat:
                              │     send_emstat_line({"type":"emstat_data","raw":<línea>, "seq":N})
                              │  fin normal: '*' + línea en blanco → {"type":"emstat_end"}
                              ▼
                          Pico envía  EMSTAT:<json>\n  (UART_LINK, con "seq" inyectado)
                              │
                              ▼
                  Wemos handleSerialLines():  reenvía el MISMO payload a DOS destinos
                       ├──(TCP 5006)────────► App  ─┐
                       └──(UDP 5005 broadcast)► App ─┤  el "seq" es IDÉNTICO en ambos
                                                     ▼
                              EventEmstatFrame: dos parsers (uno por transporte)
                                 • cuenta cobertura por seq (Fase 0)
                                 • grafica el transporte seleccionado (default TCP)
                                 • al cerrar: merge TCP+UDP por seq (Fase 2) → dataset completo
```

Tipos de mensaje `EMSTAT:` (campo `type`): `emstat_start`, `emstat_data`, y los terminales
`emstat_end` / `emstat_error` / `emstat_aborted` / `emstat_maxtime` / `emstat_timeout`.

## 4. Por qué hay UN broadcast UDP y un TCP (recuperación)

```
                  ┌──────────────► TCP 5006 ──► App   (a veces el Wemos recorta/cierra → pierde paquetes)
 Pico ─EMSTAT:─► Wemos (fork)
                  └──────────────► UDP 5005 ──► App   (broadcast; a veces también pierde, pero OTROS paquetes)
                                   (broadcast)

 Ambos canales pierden ~3% pero paquetes DISTINTOS → el merge por "seq" en el host
 reconstruye la unión ≈ dataset completo. Ver emstat_udp_recovery.md.
```

## 5. Seguridad: el ABORT recorre los tres nodos

```
Stop ▶  App stop(send_abort=True)
   │  {"cmd":"ABORT"}  (fire-and-close por TCP)
   ▼
Wemos ── si el cliente TCP cae con experimento activo, inyecta ABORT por su cuenta
   │     (dead-man switch, gating por experimentActive; idle-timeout 4 min)
   ▼
Pico poll_stop() ve {"cmd":"ABORT"} → envía 'Z\n' al EmStat
   ▼
EmStat: 'Z' → salta a on_finished: → cell_off  (celda apagada por protocolo)
```

Detalle y huecos aceptados: [emstat_abort_y_canal.md](emstat_abort_y_canal.md).

---

## Resumen de puertos / pines / baudios

| Enlace | Medio | Puerto / Pines | Baud | Sentido |
|---|---|---|---|---|
| App ↔ Wemos | WiFi TCP | 5006 | — | control + resultados |
| App ◄ Wemos | WiFi UDP | 5005 (broadcast) | — | resultados (tap) + temperatura |
| Wemos ↔ Pico | UART_LINK | GP8 (TX) / GP9 (RX) | 230400 | comandos / `EMSTAT:` / `UDP:` |
| Pico ↔ EmStat | UART_EMSTAT | GP0 (TX) / GP1 (RX) | 230400 | MethodSCRIPT (pacing 5 ms/línea) |
| Pico ↔ MLX90614 / MCP23017 | I2C0 | GP20 (SDA) / GP21 (SCL) | 100 kHz | temperatura / mux electrodos |
| Pico ↔ MAX31855 | SPI1 | GP14/GP12/GP13 | 1 MHz | termopar |

---

__author__ = "Edisson A. Naula"
