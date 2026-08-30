#include <WiFiNINA.h>
#include "Adafruit_MAX31855.h"

#define RelayPin 5
#define MAXDO 6
#define MAXCS 12
#define MAXCLK 7

const char* ssid = "MasoudiPhone";  // Your Hotspot Name
const char* password = "27Ggaabb";  // Your Hotspot Password

WiFiServer server(80);
WiFiUDP udp;
const char* receiverIP = "10.55.63.151";  // MKR Receiver IP (Update if needed)
const int receiverPort = 5005;

Adafruit_MAX31855 thermocouple(MAXCLK, MAXCS, MAXDO);

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

    server.begin();
    udp.begin(receiverPort);
}

void loop() {
    double temperature = thermocouple.readCelsius();

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

    // **Send data to another MKR via UDP**
    udp.beginPacket(receiverIP, receiverPort);
    udp.print(temperature);
    udp.endPacket();

    Serial.print("Sent temperature to ");
    Serial.print(receiverIP);
    Serial.print(": ");
    Serial.println(temperature);

    delay(100);
}