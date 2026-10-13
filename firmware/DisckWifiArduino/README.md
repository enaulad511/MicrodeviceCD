# DiskWifiArduino — emisor de temperatura por UDP broadcast (MKR WiFiNINA)

Sketch **legacy** del equipo antiguo: lee la termocupla (MAX31855) cada ~100 ms y **emite la
temperatura por UDP en broadcast** (puerto 5005) para que la reciba cualquier placa de la
subred — en particular [../OldDevice/](../OldDevice/), que la usa como entrada de su PID.
Además contesta el último valor por HTTP en el puerto 80.

- **Placa:** Arduino MKR con WiFiNINA (MKR WiFi 1010 o similar) + MAX31855 por SPI software.
- **Archivo:** [DiskWifiArduino/DiskWifiArduino.ino](DiskWifiArduino/DiskWifiArduino.ino)
- **Fuente:** este `.ino` es la única copia en el repo (sin original externo que reflejar).
- **Autor:** Edisson Naula

> ⚠️ Firmware **legacy**: no participa en la cadena del equipo actual
> (Raspberry ↔ Wemos ↔ Pico ↔ EmStat). El payload es un **número plano** como texto
> (`udp.print(temperature)`), no el formato `UDP:<a>:<b>:<temp>` del disco actual; la app
> Python solo lo entiende vía `ClientUDP.latest_float()`.

> 📌 **02/09/2026** — pasó de unicast a una IP fija (`receiverIP = "10.55.63.151"`) a
> **broadcast dirigido** de la subred. Ya no hay que editar el sketch cuando cambia la IP del
> receptor o el hotspot.

## 1. Pines

| Función | Pin | Constante |
|---|---|---|
| Relay (se deja en LOW; el `loop()` no lo usa) | D5 | `RelayPin` |
| MAX31855 DO | D6 | `MAXDO` |
| MAX31855 CS | D12 | `MAXCS` |
| MAX31855 CLK | D7 | `MAXCLK` |

## 2. Red

`ssid`/`password` del hotspot en [DiskWifiArduino.ino:9](DiskWifiArduino/DiskWifiArduino.ino#L9).
El `setup()` bloquea hasta conectar y luego imprime por Serial la IP propia y la dirección de
broadcast que va a usar.

## 3. Broadcast UDP (puerto 5005)

- **Dirección:** `computeBroadcastIP()`
  ([DiskWifiArduino.ino:21](DiskWifiArduino/DiskWifiArduino.ino#L21)) calcula el broadcast
  dirigido de la subred, `(ip & mask) | ~mask`, a partir de `WiFi.localIP()` y
  `WiFi.subnetMask()`. Si la máscara llega como `0.0.0.0` cae al broadcast limitado
  `255.255.255.255`. Se calcula **una vez** tras conectar
  ([DiskWifiArduino.ino:52](DiskWifiArduino/DiskWifiArduino.ino#L52)); si la placa cambia de
  red hay que resetearla.
- **Por qué dirigido y no `255.255.255.255`:** el limitado no se enruta y no todos los AP lo
  tratan igual; el dirigido es la forma estándar de alcanzar a todos los hosts de la misma
  subred, que es donde están los receptores.
- **Envío:** en cada vuelta del `loop()`
  ([DiskWifiArduino.ino:87](DiskWifiArduino/DiskWifiArduino.ino#L87)):
  `udp.beginPacket(broadcastIP, udpPort)` + `udp.print(temperature)` + `udp.endPacket()`,
  seguido de `delay(100)` → ~10 paquetes/s. El socket se abre con `udp.begin(udpPort)` en el
  `setup()` (WiFiNINA lo exige antes de `beginPacket`).
- **Payload:** el `double` como texto con 2 decimales (`Print::print(double)`), p. ej. `23.75`.
  Compatible con el `atof` de [../OldDevice/OldDevice.ino](../OldDevice/OldDevice.ino) y con
  `ClientUDP.latest_float()` del host. Si la termocupla falla (`NaN`) no se envía nada.
- **Receptores:** cualquier socket UDP en el puerto 5005 con `SO_BROADCAST` (`ClientUDP` ya lo
  activa; OldDevice no necesita configuración).

## 4. Servidor HTTP (puerto 80)

Sin cambios: cada `loop()` atiende como mucho un cliente y responde `Temperature: <T> C` en
texto plano. Sirve para comprobar la lectura desde el navegador del portátil.

## 5. Pendientes

- [ ] Probar en el hotspot real que el broadcast dirigido llega a OldDevice y a la Raspberry
      (algunos hotspots aíslan a los clientes entre sí; en ese caso tampoco llegaba el unicast).
- [ ] Recalcular `broadcastIP` si algún día se agrega reconexión WiFi al `loop()` (hoy no hay).

---

__author__ = "Edisson A. Naula"
__date__ = "$ 02/09/2026 $"
