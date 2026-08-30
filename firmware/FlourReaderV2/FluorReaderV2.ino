// MKR Zero: Fotodiodo + TIA con corrección de BASELINE
//
// Comandos:
//   r = lecturas continuas
//   1 = LED ON
//   0 = LED OFF
//   z = tomar baseline con sensor TAPADO
//   s = mostrar estado

const int LED_GATE = 2;
const int ADC_PIN  = A0;

// ---- Ajustes de hardware --0--
const float VREF = 1.7;        // 3.3 para 5V y 1.7 para 3.5v

const float RF   = 3e6;        // 3 MΩ
const int SAMPLES_AVG = 40;

// ---- Ajustes del baseline ----
const int BASELINE_SAMPLES = 200;
// ---------------------------------------

bool ledState = false;

// Baseline almacenado en nA
float baseline_nA = 0.0;


// =====================================================
// Lee corriente sin aplicar baseline
// =====================================================
float readCurrentRaw_nA() {

  long sum = 0;

  for (int i = 0; i < SAMPLES_AVG; i++) {
    sum += analogRead(ADC_PIN);
  }

  float avg_counts = (float)sum / SAMPLES_AVG;

  float volts = avg_counts * VREF / 4095.0f;

  float current_nA = (volts / RF) * 1e9;

  return current_nA;
}


// =====================================================
// Calcula el baseline con el sensor TAPADO
// =====================================================
void calibrateBaseline() {

  Serial.println();
  Serial.println(F("================================"));
  Serial.println(F(" CALIBRACION DE BASELINE"));
  Serial.println(F(" Sensor TAPADO"));
  Serial.println(F("================================"));

  // Aseguramos que el LED esté apagado
  digitalWrite(LED_GATE, LOW);
  ledState = false;

  Serial.println(F("Tomando muestras..."));
  delay(1000);

  float sum = 0.0;

  for (int i = 0; i < BASELINE_SAMPLES; i++) {

    float current = readCurrentRaw_nA();

    sum += current;

    delay(5);
  }

  baseline_nA = sum / BASELINE_SAMPLES;

  Serial.print(F("Baseline = "));
  Serial.print(baseline_nA, 5);
  Serial.println(F(" nA"));

  Serial.println(F("Baseline guardado."));
  Serial.println(F("================================"));
  Serial.println();
}


// =====================================================
// Imprime lectura corregida
// =====================================================
void printReading() {

  long sum = 0;

  for (int i = 0; i < SAMPLES_AVG; i++) {
    sum += analogRead(ADC_PIN);
  }

  float avg_counts = (float)sum / SAMPLES_AVG;

  float volts = avg_counts * VREF / 4095.0f;

  float current_raw_nA = (volts / RF) * 1e9;

  // RESTAMOS EL BASELINE
  float current_corrected_nA = current_raw_nA - baseline_nA;

  // Si queda ligeramente negativo por ruido, mostramos 0
  if (current_corrected_nA < 0) {
    current_corrected_nA = 0;
  }

  Serial.print(F("Raw Counts: "));
  Serial.print(avg_counts, 2);

  Serial.print(F("   Volts: "));
  Serial.print(volts, 4);
  Serial.print(F(" V"));

  Serial.print(F("   Raw: "));
  Serial.print(current_raw_nA, 3);
  Serial.print(F(" nA"));

  Serial.print(F("   Corrected: "));
  Serial.print(current_corrected_nA, 3);
  Serial.println(F(" nA"));
}


// =====================================================
// SETUP
// =====================================================
void setup() {

  pinMode(LED_GATE, OUTPUT);
  digitalWrite(LED_GATE, LOW);

  analogReadResolution(12);

  Serial.begin(115200);

  while (!Serial) {}

  Serial.println(F("======================================"));
  Serial.println(F(" MKR Zero - Fotodiodo + TIA"));
  Serial.println(F(" Correccion de BASELINE"));
  Serial.println(F("======================================"));

  Serial.println(F("Comandos:"));
  Serial.println(F("  r = lectura continua"));
  Serial.println(F("  1 = LED ON"));
  Serial.println(F("  0 = LED OFF"));
  Serial.println(F("  z = calibrar baseline"));
  Serial.println(F("  s = estado"));
  Serial.println();

  Serial.println(F("IMPORTANTE: inicia con el sensor TAPADO."));
  Serial.println(F("Escribe z para tomar el baseline."));
}


// =====================================================
// LOOP
// =====================================================
void loop() {

  if (Serial.available()) {

    char cmd = Serial.read();

    // -----------------------------------------------
    // BASELINE
    // -----------------------------------------------
    if (cmd == 'z' || cmd == 'Z') {

      calibrateBaseline();
    }

    // -----------------------------------------------
    // LECTURA CONTINUA
    // -----------------------------------------------
    else if (cmd == 'r' || cmd == 'R') {

      Serial.println(F("Transmitiendo datos..."));
      Serial.println(F("Presiona cualquier tecla para detener."));

      while (Serial.available()) {
        Serial.read();
      }

      while (!Serial.available()) {

        printReading();

        delay(50);
      }

      while (Serial.available()) {
        Serial.read();
      }

      Serial.println(F("Lectura detenida."));
    }

    // -----------------------------------------------
    // LED ON
    // -----------------------------------------------
    else if (cmd == '1') {

      digitalWrite(LED_GATE, HIGH);
      ledState = true;

      Serial.println(F(">> LED ENCENDIDO <<"));
    }

    // -----------------------------------------------
    // LED OFF
    // -----------------------------------------------
    else if (cmd == '0') {

      digitalWrite(LED_GATE, LOW);
      ledState = false;

      Serial.println(F(">> LED APAGADO <<"));
    }

    // -----------------------------------------------
    // ESTADO
    // -----------------------------------------------
    else if (cmd == 's' || cmd == 'S') {

      Serial.print(F("RF = "));
      Serial.print(RF, 0);

      Serial.print(F(" ohm   VREF = "));
      Serial.print(VREF, 3);

      Serial.print(F(" V   LED = "));
      Serial.print(ledState ? F("ON") : F("OFF"));

      Serial.print(F("   Baseline = "));
      Serial.print(baseline_nA, 3);

      Serial.println(F(" nA"));
    }
  }
}
