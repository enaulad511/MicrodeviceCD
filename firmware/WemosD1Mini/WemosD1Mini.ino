#include <ESP8266WiFi.h>
#include <WiFiUdp.h>
#include <ArduinoOTA.h>

// --- Configuración de Red ---
const char* ssid     = "EdiPcTec";
const char* password = "editec2025";

// --- AP Fallback ---
const char* AP_SSID     = "CD_DEVICE";
const char* AP_PASSWORD = "cdlab2026";
bool apMode = false;

// =====================
// --- Puertos ---
// =====================
const uint16_t UDP_PORT = 5005;   // Beacon + comandos + salida de datos
const uint16_t TCP_PORT = 5006;   // Cliente para iniciar experimentos y recibir resultados EMSTAT

// =====================
// --- Red ---
// =====================
WiFiUDP udp;
WiFiServer tcpServer(TCP_PORT);
WiFiClient tcpClient;
IPAddress broadcastIP;

// =====================
// --- Dead-man switch (seguridad de la celda) ---
// =====================
// Si el cliente TCP (host) se cae mientras hay un experimento en curso, el host
// puede no alcanzar a abortar (su {"cmd":"ABORT"} se pierde porque al cerrar el
// socket se descarta el buffer RX, o porque el host crasheó/perdió red). En ese
// caso ningún watchdog del Pico se dispara a tiempo (el EmStat responde y el
// experimento dura <10 min) -> la celda quedaría energizada. Para evitarlo, el
// Wemos inyecta él mismo EMSTAT:{"cmd":"ABORT"} al Pico al detectar la caída,
// pero SOLO si había un experimento activo (gating), para no envenenar la
// siguiente corrida con un ABORT espurio.
bool experimentActive = false;   // true entre emstat_start y un tipo terminal
bool tcpWasConnected = false;    // latch para detectar la transición conectado->caído

// =====================
// --- Timers ---
// =====================
unsigned long lastBeacon = 0;
const unsigned long beaconInterval = 4000; // 2s
// =====================
// --- UART headers ---
// =====================
const char* HDR_UDP    = "UDP:";
const char* HDR_EMSTAT = "EMSTAT:";
const unsigned long BAUDRATE = 230400;

// Buffer para armar líneas desde Serial
String serialBuffer;

// =====================
// --- Utilidades ---
// =====================
void calcBroadcast(IPAddress ip, IPAddress mask) {
  broadcastIP = ip;
  for (int i = 0; i < 4; i++) {
    broadcastIP[i] = ip[i] | (~mask[i]);
  }
}

bool startsWith(const String& s, const char* prefix) {
  int n = strlen(prefix);
  if (s.length() < (unsigned)n) return false;
  for (int i = 0; i < n; i++) if (s[i] != prefix[i]) return false;
  return true;
}

String stripPrefix(const String& s, const char* prefix) {
  int n = strlen(prefix);
  if ((int)s.length() >= n) return s.substring(n);
  return "";
}

void sendBeacon() {
  udp.beginPacket(broadcastIP, UDP_PORT);
  if (apMode) {
    udp.print("CD_DISCOVERY_AP:");
    udp.print(WiFi.softAPIP().toString());
  } else {
    udp.print("CD_DISCOVERY:");
    udp.print(WiFi.localIP().toString());
  }
  udp.endPacket();
}

void handleBeacon(unsigned long now) {
  if (now - lastBeacon >= beaconInterval) {
    lastBeacon = now;
    sendBeacon();
  }
}

// =====================
// --- UDP comandos ---
// =====================
void handleUdpCommands() {
  int packetSize = udp.parsePacket();
  if (packetSize <= 0) return;

  IPAddress senderIP = udp.remoteIP();
  uint16_t  senderPort = udp.remotePort();

  String cmd = udp.readStringUntil('\n');
  cmd.trim();
  if (cmd.length() == 0) return;

  // Comandos básicos
  if (cmd.equalsIgnoreCase("PING")) {
    udp.beginPacket(senderIP, senderPort);
    udp.print("PONG");
    udp.endPacket();
  } else if (cmd.equalsIgnoreCase("DISCOVER")) {
    // Responder con beacon inmediato
    sendBeacon();
  } else {
    // Comando no reconocido
    udp.beginPacket(senderIP, senderPort);
    udp.print("{\"error\":\"UNKNOWN_CMD\",\"cmd\":\"");
    udp.print(cmd);
    udp.print("\"}");
    udp.endPacket();
  }
}

// =====================
// --- Serial (UART) ---
// =====================
// REGLA: líneas terminadas en '\n' con prefijo "UDP:" o "EMSTAT:"
void handleSerialLines() {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      String line = serialBuffer;
      serialBuffer = "";
      line.trim();
      if (line.length() == 0) continue;

      if (startsWith(line, HDR_UDP)) {
        // Telemetría simple -> UDP inmediato (broadcast)
        String payload = stripPrefix(line, HDR_UDP);
        payload.trim();
        udp.beginPacket(broadcastIP, UDP_PORT);
        // Reenvía SOLO el payload o con encabezado; aquí mando con encabezado para consistencia
        udp.print(HDR_UDP);
        udp.print(payload);
        udp.endPacket();
      }
      else if (startsWith(line, HDR_EMSTAT)) {
        // Resultados del EmStat -> UDP y TCP si hay cliente
        String payload = stripPrefix(line, HDR_EMSTAT);
        payload.trim();

        // Rastrea estado del experimento para el dead-man switch. Los datos
        // (emstat_data) son el caso común: se saltan. emstat_start activa;
        // cualquier tipo terminal desactiva. (Un emstat_error sin start previo
        // -p.ej. canal inválido- deja experimentActive=false: no hay qué abortar.)
        if (payload.indexOf("emstat_data") < 0) {
          if (payload.indexOf("emstat_start") >= 0) {
            experimentActive = true;
          } else if (payload.indexOf("emstat_end") >= 0
                  || payload.indexOf("emstat_aborted") >= 0
                  || payload.indexOf("emstat_maxtime") >= 0
                  || payload.indexOf("emstat_timeout") >= 0
                  || payload.indexOf("emstat_error") >= 0) {
            experimentActive = false;
          }
        }

        // UDP (broadcast) con encabezado
        udp.beginPacket(broadcastIP, UDP_PORT);
        udp.print(HDR_EMSTAT);
        udp.print(payload);
        udp.endPacket();
        // TCP si está conectado
        if (tcpClient && tcpClient.connected()) {
          tcpClient.print(HDR_EMSTAT);
          tcpClient.println(payload);
        }
      }
      else {
        // Línea desconocida: ignorar o, si prefieres, forward UDP sin encabezado
        // udp.beginPacket(broadcastIP, UDP_PORT);
        // udp.print(line);
        // udp.endPacket();
      }
    } else {
      serialBuffer += c;
      if (serialBuffer.length() > 2048) {
        serialBuffer = ""; // evitar crecimiento descontrolado
      }
    }
    yield();
  }
}

// =====================
// --- TCP persistente ---
// =====================
unsigned long lastTcpActivity = 0;
// 4 min: corta un host muerto (sin FIN) antes del tope absoluto de 10 min del Pico.
// Margen amplio sobre el keepalive del host (cada 120 s) para no cortar uno vivo.
const unsigned long tcpIdleTimeout = 4 * 60 * 1000; // 4 min

// Dead-man: inyecta ABORT al Pico por UART. El Pico lo lee con poll_stop() y
// envía 'Z\n' al EmStat -> on_finished: -> cell_off. Idempotente: un ABORT con
// experimento ya terminado es ignorado por el Pico.
void injectAbortToPico() {
  Serial.print(HDR_EMSTAT);
  Serial.println("{\"cmd\":\"ABORT\"}");
}

void acceptTcpIfNeeded() {
  if (tcpClient && tcpClient.connected()) {
    tcpWasConnected = true;
    return;
  }
  // Aquí el cliente NO está conectado. Si lo estaba antes, es una caída (cierre
  // del host, crash o pérdida de red). Dead-man switch: si había experimento en
  // curso, aborta ANTES de stop() (que descartaría el buffer RX con un posible
  // ABORT del host aún sin reenviar) para no dejar la celda energizada.
  if (tcpWasConnected) {
    if (experimentActive) {
      injectAbortToPico();
      experimentActive = false;
    }
    tcpWasConnected = false;
  }
  if (tcpClient) tcpClient.stop();

  WiFiClient newClient = tcpServer.available();
  if (newClient) {
    tcpClient = newClient;
    tcpClient.setNoDelay(true);
    tcpClient.setTimeout(50);
    lastTcpActivity = millis();
    tcpWasConnected = true;
    // Mensaje de bienvenida
    tcpClient.println("{\"hello\":\"CD_TCP_READY\"}");
  }
}

// REGLA: toda línea que llegue por TCP es un payload JSON que se manda a UART con encabezado EMSTAT:
void handleTcpRx() {
  if (!(tcpClient && tcpClient.connected())) return;

  while (tcpClient.available() > 0) {
    String jsonLine = tcpClient.readStringUntil('\n');
    jsonLine.trim();
    if (jsonLine.length() == 0) continue;
    if (jsonLine.indexOf("keepalive") >= 0) {
      lastTcpActivity = millis();
    }
    // Reenviar al Pico por UART con encabezado EMSTAT:
    Serial.print(HDR_EMSTAT);
    Serial.println(jsonLine);

    // (Opcional) ACK al cliente
    tcpClient.println("{\"status\":\"FORWARDED\",\"to\":\"UART_EMSTAT\"}");
    lastTcpActivity = millis();
    yield();
  }

  // Timeout: host probablemente muerto (sin FIN). Dead-man antes de cerrar para
  // no dejar la celda energizada esperando el tope de 10 min del Pico.
  if (millis() - lastTcpActivity > tcpIdleTimeout) {
    if (experimentActive) {
      injectAbortToPico();
      experimentActive = false;
    }
    tcpClient.println("{\"status\":\"TIMEOUT\"}");
    tcpClient.stop();
    tcpWasConnected = false;
  }
}

// =====================
// --- Setup/Loop ---
// =====================
void setup() {
  // UART hacia Pico (NO usar para logs)
  // setRxBufferSize ANTES de begin: el RX por defecto del ESP8266 (~256 B) se
  // desborda en mensajes largos del Pico (emstat_start lleva todos los params),
  // pierde el '\n' y concatena el siguiente mensaje (corrompe TCP y UDP por igual).
  Serial.setRxBufferSize(2048);
  Serial.begin(BAUDRATE);
  delay(10);

  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, HIGH); // OFF (active LOW)

  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);

  // Espera conexión (sin imprimir por Serial)
  unsigned long t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < 20000) {
    delay(250);
    yield();
  }

  if (WiFi.status() == WL_CONNECTED) {
    calcBroadcast(WiFi.localIP(), WiFi.subnetMask());
    digitalWrite(LED_BUILTIN, HIGH); // OFF en modo STA
  } else {
    // Red principal no disponible: levantar hotspot
    WiFi.mode(WIFI_AP);
    WiFi.softAP(AP_SSID, AP_PASSWORD);
    calcBroadcast(WiFi.softAPIP(), IPAddress(255, 255, 255, 0));
    apMode = true;
    digitalWrite(LED_BUILTIN, LOW); // ON en modo AP
  }

  udp.begin(UDP_PORT);
  tcpServer.begin();
  tcpServer.setNoDelay(true);

  // OTA: permite actualizar firmware por WiFi sin tocar el UART del Pico
  ArduinoOTA.setHostname("CD-DEVICE");
  ArduinoOTA.begin();

  // Beacon inicial
  sendBeacon();
}

void loop() {
  unsigned long now = millis();

  ArduinoOTA.handle();
  handleBeacon(now);
  handleUdpCommands();
  handleSerialLines();
  acceptTcpIfNeeded();
  handleTcpRx();

  yield(); // watchdog
}
