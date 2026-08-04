// MKR Zero: ON–OFF integrator with baseline subtraction — on-demand reading
// Derived from OldDevice.ino: same measurement approach (chopped ON–OFF
// integration + blank subtraction), but a measurement happens only when asked
// for, instead of the free-running 'r' loop.
// Commands via Serial Monitor (newline OK):
//   f = measure fluorescence once (needs a baseline)
//   b = capture baseline on blank (stores ON-OFF avg)
//   c = clear baseline
//   s = show settings
// A 16x2 LCD mirrors the result (line 1) and the blank state (line 2).

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

// ---- LCD: ajusta al módulo que tengas conectado ----
// LCD_I2C 1 -> backpack I2C (PCF8574) en SDA/SCL (D11/D12 en la MKR Zero)
// LCD_I2C 0 -> HD44780 en paralelo; revisa los pines del constructor de abajo
#define LCD_I2C   1
#define LCD_ADDR  0x27           // 0x27 o 0x3F según el backpack
#define LCD_COLS  16
#define LCD_ROWS  2

#if LCD_I2C
  #include <Wire.h>
  #include <LiquidCrystal_I2C.h>
  LiquidCrystal_I2C lcd(LCD_ADDR, LCD_COLS, LCD_ROWS);
#else
  #include <LiquidCrystal.h>
  // RS, E, D4, D5, D6, D7 — D2 queda libre porque lo usa LED_GATE
  LiquidCrystal lcd(3, 4, 5, 6, 7, 8);
#endif
// ----------------------------------------------------

float baseline_counts = 0.0f;    // stored baseline in ADC counts (ON-OFF)
bool  baseline_ready  = false;   // 'b' lo activa, 'c' lo apaga. Bandera aparte
                                 // porque un blanco válido puede valer 0.0 o
                                 // negativo: el valor no delata si se capturó.

// ---- Pantalla ----
// Ninguna de estas funciones se llama dentro de measureDeltaCounts: una
// escritura I2C cuesta ~1-2 ms y el chopping ON-OFF depende del temporizado.

void lcdLine(uint8_t row, const char* text){
  // Escribe y RELLENA con espacios hasta el final: la HD44780 no borra sola,
  // sin el padding queda la cola del mensaje anterior ("Blank: OK" sobre
  // "Blank: NONE" dejaría "Blank: OKNE").
  lcd.setCursor(0, row);
  uint8_t n = 0;
  while(text[n] != '\0' && n < LCD_COLS){ lcd.write(text[n]); n++; }
  for(; n < LCD_COLS; n++) lcd.write(' ');
}

void lcdBlankStatus(){
  lcdLine(1, baseline_ready ? "Blank: OK" : "Blank: NONE");
}

void lcdValue(const char* prefix, float value, const char* unit){
  // Sin sprintf("%f"): Print::print(float, dec) evita el soporte de float en
  // printf, que no es fiable entre cores.
  lcd.setCursor(0, 0);
  int n = 0;
  n += lcd.print(prefix);
  n += lcd.print(value, 2);
  n += lcd.print(unit);
  for(; n < LCD_COLS; n++) lcd.write(' ');
}

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
  lcdLine(0, "Blank...");
  baseline_counts = measureDeltaCounts(CYCLES_BASELINE);
  baseline_ready  = true;
  Serial.print(F("Baseline (counts): ")); Serial.println(baseline_counts, 2);
  lcdValue("BL ", baseline_counts, " ct");
  lcdBlankStatus();
}

void printReading(){
  lcdLine(0, "Measuring...");
  float d_counts = measureDeltaCounts(CYCLES_MEASURE);
  float net_counts = d_counts - baseline_counts;               // subtract LED leak
  float dV = net_counts * VREF / 4095.0f;                      // volts of fluorescence only
  float dI = dV / RF;                                          // amperes at photodiode

  Serial.print(F("Δcounts(")); Serial.print(CYCLES_MEASURE);
  Serial.print(F(") = ")); Serial.print(net_counts, 2);
  Serial.print(F("   ΔV = ")); Serial.print(dV, 5); Serial.print(F(" V"));
  Serial.print(F("   ΔI = ")); Serial.print(dI*1e9, 2); Serial.println(F(" nA"));

  // La LCD no tiene 'Δ' (juego de caracteres HD44780): se queda en Serial.
  lcdValue("I= ", dI*1e9, " nA");
}

void setup(){
  pinMode(LED_GATE, OUTPUT);
  digitalWrite(LED_GATE, LOW);
  analogReadResolution(12);        // 0..4095 over ~0..3.3 V

  // LCD antes del Serial: así muestra estado mientras se espera al USB.
#if LCD_I2C
  lcd.init();                      // algunos forks de la librería usan begin()
  lcd.backlight();
#else
  lcd.begin(LCD_COLS, LCD_ROWS);
#endif
  lcdLine(0, "FluorReader");
  lcdBlankStatus();

  Serial.begin(115200);
  while(!Serial){}                 // wait for USB
  Serial.println(F("Ready. Commands: f=measure, b=baseline, c=clear, s=status"));
}

void loop(){
  if(Serial.available()){
    char cmd = Serial.read();
    if(cmd=='f' || cmd=='F'){
      // Sin blanco la resta sería 0 y la lectura incluiría la fuga óptica del
      // LED: se rechaza en vez de imprimir un valor engañoso.
      if(!baseline_ready){
        Serial.println(F("No baseline. Capture it first with 'b'."));
        lcdLine(0, "Need blank (b)");
        lcdBlankStatus();
      } else {
        printReading();
      }
    }
    else if(cmd=='b'){ captureBaseline(); }
    else if(cmd=='c'){
      baseline_counts = 0.0f;
      baseline_ready  = false;
      Serial.println(F("Baseline cleared."));
      lcdLine(0, "Blank cleared");
      lcdBlankStatus();
    }
    else if(cmd=='s'){
      Serial.print(F("RF=")); Serial.print(RF,0);
      Serial.print(F("  SETTLE_US=")); Serial.print(SETTLE_US);
      Serial.print(F("  CYCLES=")); Serial.print(CYCLES_MEASURE);
      Serial.print(F("  BL=")); Serial.print(baseline_counts,2);
      Serial.println(baseline_ready ? F(" (ready)") : F(" (not captured)"));
    }
  }
}
