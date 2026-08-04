// MKR Zero: ON–OFF integrator with baseline subtraction
// Commands via Serial Monitor (newline OK):
//   b = capture baseline on blank (stores ON-OFF avg)
//   r = continuous readings (delta - baseline)
//   c = clear baseline
//   s = show settings

const int LED_GATE = 2;          // MOSFET gate driving your 470 nm LEDs
const int ADC_PIN  = A0;         // TIA output to ADC

// ---- Adjust these to your hardware ----
const float VREF = 3.3;          // MKR Zero analog reference (~3.3 V)
const float RF   = 3e6;          // TIA feedback (use 3e6 if Rf=3 MΩ)
const int   SETTLE_US = 320;     // allow TIA to settle each state (200–400 µs)
const int   SAMPLES_PER_STATE = 1;    // ADC averages per ON or OFF (1–8)
const int   CYCLES_BASELINE   = 512;  // integration cycles for baseline
const int   CYCLES_MEASURE    = 256;  // cycles for each reading
// ---------------------------------------

float baseline_counts = 0.0f;    // stored baseline in ADC counts (ON-OFF)

uint16_t readAvg(int n){
  long s = 0;
  for(int i=0;i<n;i++) s += analogRead(ADC_PIN);
  return (uint16_t)(s / n);
}

float measureDeltaCounts(int cycles){
  long acc = 0;
  for(int i=0;i<cycles;i++){
    digitalWrite(LED_GATE, HIGH);
    delayMicroseconds(SETTLE_US);
    int on = readAvg(SAMPLES_PER_STATE);

    digitalWrite(LED_GATE, LOW);
    delayMicroseconds(SETTLE_US);
    int off = readAvg(SAMPLES_PER_STATE);

    acc += (on - off);           // ON–OFF removes ambient/DC
  }
  return (float)acc / (float)cycles;
}

void captureBaseline(){
  Serial.println(F("Capturing baseline... keep BLANK in place."));
  baseline_counts = measureDeltaCounts(CYCLES_BASELINE);
  Serial.print(F("Baseline (counts): ")); Serial.println(baseline_counts, 2);
}

void printReading(){
  float d_counts = measureDeltaCounts(CYCLES_MEASURE);
  float net_counts = d_counts - baseline_counts;               // subtract LED leak
  float dV = net_counts * VREF / 4095.0f;                      // volts of fluorescence only
  float dI = dV / RF;                                          // amperes at photodiode

  Serial.print(F("Δcounts(")); Serial.print(CYCLES_MEASURE);
  Serial.print(F(") = ")); Serial.print(net_counts, 2);
  Serial.print(F("   ΔV = ")); Serial.print(dV, 5); Serial.print(F(" V"));
  Serial.print(F("   ΔI = ")); Serial.print(dI*1e9, 2); Serial.println(F(" nA"));
}

void setup(){
  pinMode(LED_GATE, OUTPUT);
  digitalWrite(LED_GATE, LOW);
  analogReadResolution(12);        // 0..4095 over ~0..3.3 V
  Serial.begin(115200);
  while(!Serial){}                 // wait for USB
  Serial.println(F("Ready. Commands: b=baseline, r=run, c=clear, s=status"));
}

void loop(){
  if(Serial.available()){
    char cmd = Serial.read();
    if(cmd=='b'){ captureBaseline(); }
    else if (cmd=='r' || cmd=='R') {
  Serial.println(F("Running (press any key to stop)…"));

  // FLUSH leftover characters (e.g., CR/LF from hitting Enter)
  while (Serial.available()) Serial.read();

  // Continuous readings until a key is pressed
  while (!Serial.available()) {
    printReading();
    delay(50); // ~20 Hz update
  }

  // Clear the key that stopped the loop
  while (Serial.available()) Serial.read();
}
else if(cmd=='c'){ baseline_counts = 0.0f; Serial.println(F("Baseline cleared.")); }
    else if(cmd=='s'){
      Serial.print(F("RF=")); Serial.print(RF,0);
      Serial.print(F("  SETTLE_US=")); Serial.print(SETTLE_US);
      Serial.print(F("  BL=")); Serial.println(baseline_counts,2);
    }
  }
}
