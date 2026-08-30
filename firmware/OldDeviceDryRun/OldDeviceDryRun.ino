// === OldDeviceDryRun: actuator dry-run version of OldDevice.ino ===
//
// Temperature is removed entirely (no WiFi/UDP input, no PID): every stage
// advances on a fixed, editable time so the full PCR procedure still runs
// and the actuators can be bench-tested without the thermal hardware:
//   - Heater relay: ON during INITIAL_HEAT and HEAT, OFF elsewhere
//     (MIN_ON/MIN_OFF dwell protection kept).
//   - Motor: pre-spin once, then exactly one cooling burst per cycle.
//   - Fluorescence: real measurement (FluorReaderV2 method) at the end of
//     each cycle; SenderLedPin lights while a measurement is in progress.
//
// Serial gate unchanged: first 'f' captures the dark baseline, second 'f'
// starts the run. CSV keeps the 4-column format; the Temperature column
// carries the nominal stage setpoint (96/93/63), NOT a measurement.

#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <SmoothStepper.h>

// === Pin Definitions and Motor Setup (same wiring as OldDevice) ===
#define RelayPin         4   // Heating element via mechanical relay
#define PowerLedPin      1
#define WifiLedPin       0   // no WiFi in this version — stays LOW
#define SenderLedPin     5   // reused: ON while a fluorescence read runs
#define LED_Fluorescence 2
#define PHD_receiver     A0

SmoothStepper motor(3, 7);  // DIR=3, PUL=7

// === LCD Display Setup ===
LiquidCrystal_I2C lcd(0x27, 16, 4);

// === Relay protection (same as OldDevice) ===
const unsigned long MIN_ON_MS  = 700;     // minimum ON dwell to protect relay
const unsigned long MIN_OFF_MS = 700;     // minimum OFF dwell
unsigned long lastRelayToggleMs = 0;
bool relayState = false;

// === Simulated stage durations — EDIT HERE (bench-test defaults, ms) ===
const unsigned long InitialHeatTime = 10000;  // replaces: ramp until 96 C
const unsigned long InitialHoldTime = 15000;  // real run: 180000
const unsigned long HeatTime        = 8000;   // replaces: ramp until 93 C
const unsigned long HoldTimeHigh    = 10000;  // real value
const unsigned long HoldTimeLow     = 10000;  // real value
const unsigned long FinalHoldTime   = 15000;  // real run: 60000
const unsigned long PauseTime       = 100;

const int MaxCycles = 5;                      // real run: 40

// === Nominal temperatures (CSV/plot column only — nothing is measured) ===
const double TempAmbient   = 25.0;
const double TempInitial   = 96.0;
const double TempCycleHigh = 93.0;
const double TempCycleLow  = 63.0;
const double TempFinalHold = 63.0;

// --- Cooling via motor (same as OldDevice) ---
const double MotorRPM  = 1800.0;
const int    MotorRevs = 40;

// --- Pre-Spin ---
const double PreSpinRPM  = 800.0;
const int    PreSpinRevs = 100;

// === Runtime Variables ===
int cycleCount = 0;
bool preSpinDone = false;
unsigned long stageStartTime = 0;

// === Fluorescence tracking ===
volatile bool fluorActive = false;

// === Fluorescence parameters (FluorReaderV2 method: plain average + baseline in nA) ===
const float ADC_VREF = 1.7;      // FluorReaderV2 calibration (3.3 for 5V supply, 1.7 for 3.5V)
const float RF_OHMS  = 3e6;      // 3 MOhm
const int   ADC_BITS = 12;
const int   SAMPLES_AVG      = 40;    // ADC averages per reading
const int   BASELINE_SAMPLES = 200;   // readings averaged for the dark baseline
const int   LED_SETTLE_MS    = 50;    // LED ON -> settle -> sample
float baseline_nA  = 0.0f;            // dark baseline (LED OFF), in nA
float lastFluor_nA = 0.0f;            // last corrected reading, third CSV column
float lastRaw = 0.0f;
float dI_nA[MaxCycles] = {0};

// === Heater inhibit for motor guard (same as OldDevice) ===
unsigned long heaterInhibitUntilMs = 0;
inline void inhibitHeater(unsigned long ms) {
  unsigned long until = millis() + ms;
  if (until > heaterInhibitUntilMs) heaterInhibitUntilMs = until;
  digitalWrite(RelayPin, LOW);
  relayState = false;
  lastRelayToggleMs = millis();
}

// === Stages ===
enum Stage {
  PRE_SPIN,
  INITIAL_HEAT,
  INITIAL_HOLD,
  HEAT,
  HOLD_HIGH,
  COOL,
  HOLD_LOW,
  PAUSE,
  FINAL_HOLD,
  STAGE_COUNT
};

const char* const STAGE_NAME[STAGE_COUNT] = {
  "Pre-Spin","Init Heat","Init Hold","Heat",
  "Hold High","Cool","Hold Low","Pause","Final Hold"
};

Stage currentStage = PRE_SPIN;

// === Gate state ===
enum RunGate { WAIT_BASELINE, WAIT_START, RUNNING };
RunGate runGate = WAIT_BASELINE;
bool gatePromptShown = false;

// === Status refresh throttle (LCD + CSV, ms) ===
const unsigned long StatusPeriodMs = 500;
unsigned long lastStatusMs = 0;

// === Helpers ===
int readCharNonBlocking() {
  if (Serial.available() > 0) {
    int c = Serial.read();
    while (Serial.available() > 0) Serial.read();
    return c;
  }
  return -1;
}

float readAvgCounts(int pin, int n){
  long s = 0;
  for (int i = 0; i < n; i++) s += analogRead(pin);
  return (float)s / (float)n;
}
float countsToVolts(float counts){
  return counts * ADC_VREF / ((1 << ADC_BITS) - 1);
}
float voltsToCurrentA(float dv){
  return dv / RF_OHMS;
}

// One raw reading in nA, no baseline applied (FluorReaderV2 readCurrentRaw_nA)
float readCurrentRaw_nA(){
  float avg_counts = readAvgCounts(PHD_receiver, SAMPLES_AVG);
  return voltsToCurrentA(countsToVolts(avg_counts)) * 1e9f;
}

// Dark baseline, FluorReaderV2 method: LED OFF, detector kept dark
void captureBaseline() {
  digitalWrite(LED_Fluorescence, LOW);
  delay(1000);
  float sum = 0.0f;
  for (int i = 0; i < BASELINE_SAMPLES; i++) {
    sum += readCurrentRaw_nA();
    delay(5);
  }
  baseline_nA = sum / BASELINE_SAMPLES;
}

void modeRun() {
  fluorActive = true;
  digitalWrite(SenderLedPin, HIGH);
  digitalWrite(LED_Fluorescence, HIGH);
  delay(LED_SETTLE_MS);
  float raw_nA = readCurrentRaw_nA();
  digitalWrite(LED_Fluorescence, LOW);
  digitalWrite(SenderLedPin, LOW);
  fluorActive = false;

  float corrected_nA = raw_nA - baseline_nA;
  if (corrected_nA < 0) corrected_nA = 0;   // clamp, same as FluorReaderV2

  lastFluor_nA = corrected_nA;
  lastRaw = raw_nA;
  if (cycleCount > 0 && cycleCount <= MaxCycles) {
    dI_nA[cycleCount - 1] = corrected_nA;
  }
}

// Nominal temperature of the current stage (CSV column only)
double stageNominalTemp() {
  switch (currentStage) {
    case PRE_SPIN:                        return TempAmbient;
    case INITIAL_HEAT: case INITIAL_HOLD: return TempInitial;
    case HEAT: case HOLD_HIGH:            return TempCycleHigh;
    case COOL: case HOLD_LOW: case PAUSE: return TempCycleLow;
    case FINAL_HOLD:                      return TempFinalHold;
    default:                              return 0.0;
  }
}

// Fixed duration of the current stage (0 = event-driven: PRE_SPIN, COOL)
unsigned long stageDurationMs() {
  switch (currentStage) {
    case INITIAL_HEAT: return InitialHeatTime;
    case INITIAL_HOLD: return InitialHoldTime;
    case HEAT:         return HeatTime;
    case HOLD_HIGH:    return HoldTimeHigh;
    case HOLD_LOW:     return HoldTimeLow;
    case PAUSE:        return PauseTime;
    case FINAL_HOLD:   return FinalHoldTime;
    default:           return 0;
  }
}

// Fixed-width LCD line (pads/truncates to 16 cols so rows never wrap)
void lcdPrintLine(uint8_t row, String text) {
  if (text.length() > 16) text = text.substring(0, 16);
  while (text.length() < 16) text += ' ';
  lcd.setCursor(0, row);
  lcd.print(text);
}

// === Relay drive with protection (same as OldDevice) ===
void setRelay(bool on){
  unsigned long now = millis();
  if (on != relayState) {
    unsigned long dwell = now - lastRelayToggleMs;
    if (relayState && dwell < MIN_ON_MS) return;
    if (!relayState && dwell < MIN_OFF_MS) return;
    relayState = on;
    digitalWrite(RelayPin, relayState ? HIGH : LOW);
    lastRelayToggleMs = now;
  }
}

// === Setup ===
void setup() {
  Serial.begin(9600);
  Serial.println("# OldDeviceDryRun: Temperature(C) is the nominal stage setpoint, not a measurement");
  Serial.println("Time(s),Temperature(C),Current signal (nA),Raw (nA)");

  pinMode(RelayPin, OUTPUT);         digitalWrite(RelayPin, LOW);
  pinMode(PowerLedPin, OUTPUT);      digitalWrite(PowerLedPin, HIGH);
  pinMode(WifiLedPin, OUTPUT);       digitalWrite(WifiLedPin, LOW);
  pinMode(SenderLedPin, OUTPUT);     digitalWrite(SenderLedPin, LOW);
  pinMode(LED_Fluorescence, OUTPUT); digitalWrite(LED_Fluorescence, LOW);

  analogReadResolution(ADC_BITS);   // FluorReaderV2 method: 12-bit ADC

  Wire.begin();
  lcd.init(); delay(50);
  lcd.backlight();
  lcd.setCursor(0,0); lcd.print("DRY RUN no temp");

  lastRelayToggleMs = millis();
  relayState = false;
}

// === Main Loop ===
void loop() {

  // Gating: baseline then start (same double-'f' gate as OldDevice)
  if (runGate != RUNNING) {
    if (!gatePromptShown) {
      if (runGate == WAIT_BASELINE) {
        Serial.println("Press 'f' to CAPTURE fluorescence baseline (LED off, keep detector dark)...");
        lcd.clear();
        lcd.setCursor(0,0); lcd.print("Press 'f' for");
        lcd.setCursor(0,1); lcd.print("dark baseline");
      } else if (runGate == WAIT_START) {
        Serial.print("Baseline stored = "); Serial.print(baseline_nA, 3); Serial.println(" nA");
        Serial.println("Press 'f' to START the dry run...");
        lcd.clear();
        lcd.setCursor(0,0); lcd.print("Baseline OK");
        lcd.setCursor(0,1); lcd.print("Press 'f' START");
      }
      gatePromptShown = true;
    }

    int c = readCharNonBlocking();
    if (c == 'f' || c == 'F') {
      if (runGate == WAIT_BASELINE) {
        captureBaseline();
        runGate = WAIT_START;
        gatePromptShown = false;
      } else if (runGate == WAIT_START) {
        runGate = RUNNING;
        gatePromptShown = false;
        Serial.println("Dry run started. Timed stages, no temperature.");
        lcd.clear();
        lcd.setCursor(0,0); lcd.print("Dry run started");
        stageStartTime = millis();
        lastStatusMs = 0;
      }
    }
    delay(20);
    return;
  }

  unsigned long now = millis();

  // === Relay: ON during heating stages, OFF elsewhere ===
  bool heatStage = (currentStage == INITIAL_HEAT || currentStage == HEAT);
  if (now < heaterInhibitUntilMs) setRelay(false);
  else                            setRelay(heatStage);

  // === Stage Transitions (fixed times — no temperature thresholds) ===
  switch (currentStage) {
    case PRE_SPIN:
      if (PreSpinRevs > 0 && !preSpinDone) {
        lcdPrintLine(0, "Pre-Spin Motor");
        lcdPrintLine(1, String("RPM: ") + String(PreSpinRPM, 0));
        lcdPrintLine(2, String("Revs: ") + PreSpinRevs);
        lcdPrintLine(3, "Stage: Pre-Spin");
        inhibitHeater(MIN_OFF_MS + 100);
        delay(50);
        motor.run(PreSpinRPM, PreSpinRevs);
        preSpinDone = true;
      } else {
        currentStage = INITIAL_HEAT;
        stageStartTime = now;
      }
      break;

    case INITIAL_HEAT:
      if (now - stageStartTime >= InitialHeatTime) {
        currentStage = INITIAL_HOLD;
        stageStartTime = now;
      }
      break;

    case INITIAL_HOLD:
      if (now - stageStartTime >= InitialHoldTime) {
        currentStage = HEAT;
        stageStartTime = now;
      }
      break;

    case HEAT:
      if (now - stageStartTime >= HeatTime) {
        currentStage = HOLD_HIGH;
        stageStartTime = now;
      }
      break;

    case HOLD_HIGH:
      if (now - stageStartTime >= HoldTimeHigh) {
        currentStage = COOL;
      }
      break;

    case COOL:
      // Exactly one cooling burst per cycle (no temperature left to re-check)
      inhibitHeater(MIN_OFF_MS + 200);
      lcdPrintLine(1, "Cooling burst");
      delay(50);
      motor.run(MotorRPM, MotorRevs);
      currentStage = HOLD_LOW;
      stageStartTime = millis();
      break;

    case HOLD_LOW:
      if (now - stageStartTime >= HoldTimeLow) {
        cycleCount++;
        if (cycleCount < MaxCycles) {
          currentStage = PAUSE;
          stageStartTime = now;
        } else {
          currentStage = FINAL_HOLD;
          stageStartTime = now;
        }
      }
      break;

    case PAUSE:
      if (now - stageStartTime >= PauseTime) {
        modeRun();
        Serial.print("# Cycle "); Serial.print(cycleCount);
        Serial.print(" fluorescence = "); Serial.print(lastFluor_nA, 3);
        Serial.println(" nA");
        currentStage = HEAT;
        stageStartTime = millis();
      }
      break;

    case FINAL_HOLD:
      if (now - stageStartTime >= FinalHoldTime) {
        setRelay(false);
        lcd.clear();
        lcd.setCursor(0,0); lcd.print("All Complete");
        Serial.println("All cycles + final hold complete.");
        while (true) { /* stop */ }
      }
      break;
  }

  // === Status refresh: LCD + CSV every StatusPeriodMs ===
  if (now - lastStatusMs >= StatusPeriodMs) {
    lastStatusMs = now;

    unsigned long dur = stageDurationMs();
    unsigned long elapsed = now - stageStartTime;
    unsigned long leftS = (dur > elapsed) ? (dur - elapsed + 999) / 1000 : 0;
    int cycleShown = (cycleCount < MaxCycles) ? cycleCount + 1 : MaxCycles;

    lcdPrintLine(0, String("SIM ") + STAGE_NAME[currentStage]);
    lcdPrintLine(1, dur ? (String("Left: ") + leftS + " s") : String("Left: -"));
    lcdPrintLine(2, String("F: ") + String(lastFluor_nA, 3) + " nA");
    lcdPrintLine(3, String("C:") + cycleShown + "/" + MaxCycles
                    + (relayState ? " Rly:ON" : " Rly:OFF"));

    float timeSeconds = now / 1000.0;
    Serial.print(timeSeconds, 2);           Serial.print(",");
    Serial.print(stageNominalTemp(), 1);    Serial.print(",");
    Serial.print(lastFluor_nA, 6);          Serial.print(",");
    Serial.println(lastRaw, 6);
  }

  delay(50);
}
