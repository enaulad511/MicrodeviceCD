# Firmware WemosD1Mini — espejo (mirror) en el repo

Copia **de referencia** del sketch Arduino del **Wemos D1 mini (ESP8266)**, el gateway
WiFi que une la Raspberry Pi (host) con el Pico 2 por UART. La fuente original vive fuera
de git en
`~/OneDrive - …/Documents/Arduino/WemosD1Mini/WemosD1Mini.ino` y es lo que realmente se
flashea.

> ⚠️ **No se compila ni flashea desde aquí.** Espejo para versionar el firmware junto al
> host y al Pico. Editar aquí **no** cambia la placa: edita el original, flashea (OTA), y
> refresca el espejo. (El `CLAUDE.md` que traía la carpeta se reescribió como este README:
> `.gitignore` excluye `CLAUDE.md`, y un `CLAUDE.md` anidado se auto-cargaría como
> instrucciones de directorio.)

## Rol en la cadena de tres nodos

```
App Python (este repo) ──TCP:5006──► Wemos D1 mini ──UART 230400──► Pico 2 ──UART──► EmStat
   ui/EventEmstatFrame.py            (WemosD1Mini.ino)        (emstat_wifi_v1.7.py)    celda
                          ◄──UDP:5005 broadcast──┘
```

El Wemos corre un **loop cooperativo** (sin RTOS ni interrupciones):
`ArduinoOTA.handle()` → `handleBeacon()` → `handleUdpCommands()` → `handleSerialLines()`
→ `acceptTcpIfNeeded()` → `handleTcpRx()`.

## Reglas de comunicación

**UART → Red (el Pico manda, el Wemos reenvía):** líneas `\n`-terminadas con prefijo:
- `UDP:<payload>` → broadcast UDP en 5005.
- `EMSTAT:<payload>` → broadcast UDP **y** además al cliente TCP activo.

**Red → UART (el host manda):**
- Cualquier línea JSON por TCP 5006 → al Pico como `EMSTAT:<json>\n`.
- UDP 5005 acepta `PING` (responde `PONG`) y `DISCOVER` (beacon inmediato).

**Beacon:** cada 4 s difunde `CD_DISCOVERY:<ip>` (o `CD_DISCOVERY_AP:<ip>` en modo AP).

### Relevancia para la recuperación por UDP (`seq`)

En `handleSerialLines()`, el Wemos reenvía el **mismo `payload`** a UDP broadcast y a TCP
sin modificarlo. Por eso el `"seq"` que el Pico inyecta en cada `EMSTAT:` (v1.7) llega
**idéntico** por ambos transportes — el cimiento de la dedup/recuperación del host. Ver
[docs/emstat_udp_recovery.md](../../docs/emstat_udp_recovery.md).

**`Serial.setRxBufferSize(2048)` en `setup()` (antes de `begin`):** el RX por defecto del
ESP8266 (~256 B) se desbordaba en los mensajes largos del Pico (`emstat_start` lleva todos
los params), perdía el `\n` y **concatenaba el siguiente mensaje** — corrompiendo TCP y UDP
por igual (se veían dos `EMSTAT:{…}` pegados). El host ya tolera el pegado (parte por
`EMSTAT:`), pero este buffer evita la corrupción en origen.

## Dead-man switch (seguridad de la celda)

Si el cliente TCP se cae (crash, pérdida de red o idle-timeout) **con un experimento en
curso**, el Wemos inyecta él mismo `EMSTAT:{"cmd":"ABORT"}\n` al Pico por UART, para que la
celda no quede energizada. Detalles:

- **Gating** por `experimentActive`: no aborta si no hay experimento (evita ABORT espurio).
- `experimentActive` se deduce observando el stream `EMSTAT:`: `emstat_start` → `true`;
  cualquier terminal (`emstat_end`/`aborted`/`maxtime`/`timeout`/`error`) → `false`; los
  `emstat_data` se saltan por rendimiento.
- Dispara en dos lugares: caída de TCP en `acceptTcpIfNeeded()` (host muerto/FIN) e
  idle-timeout en `handleTcpRx()` (host silencioso).
- `tcpWasConnected` es un latch para que el aborto dispare **una sola vez** por sesión.
- **Idle timeout: 4 min** — corta un host muerto antes del tope de 10 min del Pico, con
  margen sobre el keepalive del host (~120 s).

Contexto host del aborto: [docs/emstat_abort_y_canal.md](../../docs/emstat_abort_y_canal.md).

## Ciclo de vida del cliente TCP (una conexión por experimento)

El host **abre una conexión TCP nueva por cada experimento** y la cierra al terminar. El
servidor del Wemos es de **un solo cliente** (`WiFiClient tcpClient`). El bug:
`acceptTcpIfNeeded()` hacía `if (tcpClient.connected()) return;` y solo adoptaba al nuevo
cliente vía `tcpServer.available()` cuando el viejo dejaba de estar conectado. Pero en el
ESP8266, tras el cierre del host el socket queda en **CLOSE_WAIT y `connected()` SIGUE
devolviendo `true`** (quirk del core). Resultado: el primer experimento funciona, pero del
**segundo en adelante el host se cuelga** ("starting tcp …" sin respuesta) porque el Wemos
nunca adopta la conexión nueva — hasta que el **idle-timeout de 4 min** recicla el zombie y
recién entonces arranca solo. La temperatura (UDP) no se ve afectada, lo que despista.

**Fix:** preemptar con `tcpServer.hasClient()` al inicio de `acceptTcpIfNeeded()`. Si hay una
conexión nueva en cola, se suelta el cliente viejo (`stop()`, con dead-man si seguía activo)
y se adopta la nueva de inmediato. No se confía en `connected()` para liberar el slot.

## Debug por UDP (`dbgUdp` / `DEBUG_TCP`)

Como `Serial` está cableado al Pico (no se puede `Serial.print` para depurar), el ciclo de
vida del TCP se observa por **UDP broadcast**: `dbgUdp(msg)` emite
`EMSTAT:{"type":"wemos_dbg","msg":...}`, que viaja por el mismo 5005 que la temperatura. El
host lo imprime en consola (`DBG[udp/wemos_dbg]: …`) gracias a una rama en
`EventEmstatFrame._handle_emstat_msg` que captura cualquier `*_dbg`. Eventos emitidos:
`tcp_new_client`, `tcp_client_dropped`, `fwd_cmd_to_pico`, `tcp_idle_timeout`. Pon
**`DEBUG_TCP = false`** en el `.ino` para silenciarlo en operación normal.

## Build & Upload

Arduino IDE o `arduino-cli`. Board: `esp8266:esp8266:d1_mini`.

```
arduino-cli compile --fqbn esp8266:esp8266:d1_mini WemosD1Mini
arduino-cli upload  --fqbn esp8266:esp8266:d1_mini --port <COMx> WemosD1Mini
```

- Paquete de board: `arduino-cli core install esp8266:esp8266`.
- **OTA preferido:** `ArduinoOTA` activo en `loop()`, hostname `CD-DEVICE` (STA y AP). En el
  IDE: Tools → Port → puerto de red `CD-DEVICE`. Evita el puerto serie físico una vez con
  OTA.
- ⚠️ **`Serial` está cableado al UART del Pico — NO usar `Serial.print` para debug**: corrompe
  el stream del Pico.

## Configuración de red (hardcodeada al inicio del `.ino`)

```cpp
const char* ssid     = "EdiPcTec";    // red principal (STA)
const char* password = "editec2025";
const char* AP_SSID     = "CD_DEVICE";  // hotspot de respaldo
const char* AP_PASSWORD = "cdlab2026";
```

Arranque: intenta STA 20 s; si falla, levanta hotspot AP (`192.168.4.1/24`) hasta reset.
LED (GPIO2, active LOW): OFF = STA, ON = AP.

## Sincronización con el espejo

```powershell
Copy-Item "$HOME\OneDrive - Instituto Tecnologico y de Estudios Superiores de Monterrey\Documents\Arduino\WemosD1Mini\WemosD1Mini.ino" firmware\WemosD1Mini\ -Force
```
