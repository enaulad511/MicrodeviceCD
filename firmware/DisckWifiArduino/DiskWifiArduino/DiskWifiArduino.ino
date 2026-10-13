#include <WiFiNINA.h>
#include "Adafruit_MAX31855.h"

#define RelayPin 5
#define MAXDO 9
#define MAXCS 8
#define MAXCLK 7

const char* ssid = "MasoudiPhone";  // Your Hotspot Name
const char* password = "27Ggaabb";  // Your Hotspot Password

WiFiServer server(80);
WiFiUDP udp;
const int udpPort = 5005;                   // Every receiver listens here (OldDevice, ClientUDP)
IPAddress broadcastIP(255, 255, 255, 255);  // Recomputed from the subnet once connected

Adafruit_MAX31855 thermocouple(MAXCLK, MAXCS, MAXDO);

// Directed broadcast address of the current subnet: (ip & mask) | ~mask.
// Falls back to the limited broadcast 255.255.255.255 if the mask is unknown.
IPAddress computeBroadcastIP() {
    IPAddress ip = WiFi.localIP();
    IPAddress mask = WiFi.subnetMask();
    if (mask == IPAddress(0, 0, 0, 0)) {
        return IPAddress(255, 255, 255, 255);
    }
    uint8_t b[4];
    for (int i = 0; i < 4; i++) {
        b[i] = (ip[i] & mask[i]) | (uint8_t)(~mask[i]);
    }
    return IPAddress(b[0], b[1], b[2], b[3]);
}

void setup() {
    Serial.begin(9600);
    pinMode(RelayPin, OUTPUT);
    digitalWrite(RelayPin, LOW);

    Serial.print("Connecting to WiFi: ");
    Serial.println(ssid);

    while (WiFi.status() != WL_CONNECTED) {
        WiFi.begin(ssid, password);
        Serial.print(".");
        delay(1000);
    }

    Serial.println("\nConnected!");
    Serial.print("Sender MKR IP Address: ");
    Serial.println(WiFi.localIP());

    broadcastIP = computeBroadcastIP();
    Serial.print("Broadcasting to ");
    Serial.print(broadcastIP);
    Serial.print(":");
    Serial.println(udpPort);

    server.begin();
    udp.begin(udpPort);
}

void loop() {
    double temperature = thermocouple.readCelsius();
    //double temperature = 33;

    if (isnan(temperature)) {
        Serial.println("Error: Failed to read from thermocouple");
        return;
    }

    // **Send data to laptop via web server**
    WiFiClient client = server.available();
    if (client) {
        Serial.println("Client connected (Laptop)");
        client.println("HTTP/1.1 200 OK");
        client.println("Content-Type: text/html");
        client.println("Connection: close");
        client.println();
        client.print("Temperature: ");
        client.print(temperature);
        client.println(" C");
        client.stop();
    }

    // **Broadcast the temperature via UDP to every receiver on the subnet**
    // Payload stays a plain float as text, so OldDevice's atof() and the
    // Raspberry's ClientUDP.latest_float() keep parsing it unchanged.
    udp.beginPacket(broadcastIP, udpPort);
    udp.print(temperature);
    udp.endPacket();

    Serial.print("Broadcast temperature to ");
    Serial.print(broadcastIP);
    Serial.print(": ");
    Serial.println(temperature);

    delay(100);
}
