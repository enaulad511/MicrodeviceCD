// === Include Required Libraries ===
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <WiFiNINA.h>
#include <WiFiUdp.h>
#include <PID_v1.h>
#include <SmoothStepper.h>
#include <math.h>  // fabs()

// === Pin Definitions and Motor Setup ===
#define RelayPin         4   // Heating element via mechanical relay
#define PowerLedPin      1
#define WifiLedPin       0
#define SenderLedPin     5
#define LED_Fluorescence 2
#define PHD_receiver     A0

SmoothStepper motor(3, 7);  // DIR=3, PUL=7

// === LCD Display Setup ===
LiquidCrystal_I2C lcd(0x27, 16, 4);

// === WiFi Credentials ===
const char* ssid     = "MasoudiPhone";
const char* password = "27Ggaabb";

// === UDP Communication Setup ===
WiFiUDP udp;
const int udpPort = 5005;
char InputBuffer[100];

// === Relay-safe control settings ===
const unsigned long WindowSize   = 5000;  // 5 s window (mechanical relay friendly)
const int           SampleTimeMs = 1000;  // PID sample time 1 s
unsigned long WindowStartTime = 0;

const unsigned long MIN_ON_MS  = 700;     // minimum ON dwell to protect relay
const unsigned long MIN_OFF_MS = 700;     // minimum OFF dwell
unsigned long lastRelayToggleMs = 0;
bool relayState = false;

// Hysteresis and filters
const double TEMP_DEADBAND = 0.30;  // +/- 0.3 C rest zone near setpoint
const double ALPHA         = 0.20;  // EMA smoothing for UDP temperature

// Fast approach strategy
const double FAST_RAMP_ERR = 3.0;   // *** widen to 3 C so we travel faster when far

// === PID Variables ===
double Kp = 4.0, Ki = 0.12, Kd = 28.0;    // hold-friendly base gains
double Setpoint, Input, Output;
double InputFiltered = 0.0;
PID myPID(&Input, &Output, &Setpoint, Kp, Ki, Kd, DIRECT);

// --- Setpoint handling (INSTANT steps) ---
double SetpointTarget = 0.0;
// const double SLEW_C_PER_S = 1.0;       // (old) slew-limit
// *** make steps instantaneous:
const double SLEW_C_PER_S = 1e9;          // effectively disables ramp

// --- Integral separation & coast logic ---
const double I_ZONE = 1.5;                 // enable Ki only when |error| < 1.5 C
const double COAST_OFFSET = 0.8;           // if within 0.8 C and rising fast -> OFF
const double SLOPE_COAST_C_PER_S = 0.5;    // rising faster than this triggers coasting

// *** Predictive coast parameters (new) ***
const double COAST_HORIZON_S   = 2.0;      // look-ahead horizon
const double COAST_MARGIN_C    = 0.2;      // safety margin for predicted overshoot

// --- Temp slope tracking ---
double lastInputForSlope = 0.0;
unsigned long lastSlopeMs = 0;

// === PCR Program Parameters ===
const double TempInitial   = 95.0;  // Initial heating stage
const double TempCycleHigh = 95.0;  // Denaturation
const double TempCycleLow  = 63.0;  // Annealing
const double TempFinalHold = 63.0;  // Final hold

const unsigned long InitialHoldTime = 1000;
const unsigned long HoldTimeHigh    = 1000;
const unsigned long HoldTimeLow     = 1000;
const unsigned long FinalHoldTime   = 1000;
const unsigned long PauseTime       = 100;

const int MaxCycles = 6;

// --- Cooling via motor ---
const double MotorRPM = 4800.0;
const int    MotorRevs = 40;
// *** allow more corrective bursts if needed
const int    MaxCoolingBursts = 1;

// --- Pre-Spin ---
const double PreSpinRPM = 800.0;
const int    PreSpinRevs = 0;

// === Runtime Variables ===
int cycleCount = 0;
bool finalHoldStarted = false;
bool preSpinDone = false;
unsigned long stageStartTime = 0;

// === Fluorescence tracking for LCD "F" indicator ===
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

// === Heater inhibit for motor guard ===
unsigned long heaterInhibitUntilMs = 0;
inline void inhibitHeater(unsigned long ms) {
  unsigned long until = millis() + ms;
  if (until > heaterInhibitUntilMs) heaterInhibitUntilMs = until;
  digitalWrite(RelayPin, LOW);
  relayState = false;
  lastRelayToggleMs = millis();
}

// === Stages (enum BEFORE any use) ===
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

// === Gate state (declare BEFORE loop()) ===
enum RunGate { WAIT_BASELINE, WAIT_START, RUNNING };
RunGate runGate = WAIT_BASELINE;
bool gatePromptShown = false;

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
  digitalWrite(LED_Fluorescence, HIGH);
  delay(LED_SETTLE_MS);
  float raw_nA = readCurrentRaw_nA();
  digitalWrite(LED_Fluorescence, LOW);
  fluorActive = false;

  float corrected_nA = raw_nA - baseline_nA;
  if (corrected_nA < 0) corrected_nA = 0;   // clamp, same as FluorReaderV2

  lastFluor_nA = corrected_nA;
  lastRaw = raw_nA;
  if (cycleCount > 0 && cycleCount <= MaxCycles) {
    dI_nA[cycleCount - 1] = corrected_nA;
  }
}

// === Relay drive with protection ===
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
  Serial.println("Time(s),Temperature(C),Current signal (nA)");

  pinMode(RelayPin, OUTPUT);         digitalWrite(RelayPin, LOW);
  pinMode(PowerLedPin, OUTPUT);      digitalWrite(PowerLedPin, HIGH);
  pinMode(WifiLedPin, OUTPUT);       digitalWrite(WifiLedPin, LOW);
  pinMode(SenderLedPin, OUTPUT);     digitalWrite(SenderLedPin, LOW);
  pinMode(LED_Fluorescence, OUTPUT); digitalWrite(LED_Fluorescence, LOW);

  analogReadResolution(ADC_BITS);   // FluorReaderV2 method: 12-bit ADC (SAMD21 defaults to 10)

  Wire.begin();
  lcd.init(); delay(50);
  lcd.backlight();
  lcd.setCursor(0,0); lcd.print("Connecting WiFi");

  while (WiFi.begin(ssid, password) != WL_CONNECTED) {
    delay(50); Serial.print(".");
  }
  Serial.println("\nConnected!");
  Serial.print("IP Address: "); Serial.println(WiFi.localIP());
  digitalWrite(WifiLedPin, HIGH);

  lcd.clear();
  lcd.setCursor(0,0); lcd.print("WiFi Connected");

  udp.begin(udpPort);

  Setpoint = TempInitial;
  SetpointTarget = TempInitial;

  myPID.SetMode(AUTOMATIC);
  myPID.SetSampleTime(SampleTimeMs);
  myPID.SetOutputLimits(0, WindowSize);
  WindowStartTime = millis();
  lastRelayToggleMs = millis();
  relayState = false;
  digitalWrite(RelayPin, LOW);

  lastSlopeMs = millis();
  lastInputForSlope = InputFiltered;
}

// === Main Loop ===
void loop() {

  // Gating: baseline then start
  if (runGate != RUNNING) {
    if (!gatePromptShown) {
      if (runGate == WAIT_BASELINE) {
        Serial.println("Press 'f' to CAPTURE fluorescence baseline (LED off, keep detector dark)...");
        lcd.clear();
        lcd.setCursor(0,0); lcd.print("Press 'f' for");
        lcd.setCursor(0,1); lcd.print("dark baseline");
      } else if (runGate == WAIT_START) {
        Serial.print("Baseline stored = "); Serial.print(baseline_nA, 3); Serial.println(" nA");
        Serial.println("Press 'f' to START the run...");
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
        Serial.println("Run started. Proceeding with PCR/rotation/heater...");
        lcd.clear();
        lcd.setCursor(0,0); lcd.print("Run started");
      }
    }
    delay(20);
    return;
  }

  // WiFi LED
  digitalWrite(WifiLedPin, WiFi.status() == WL_CONNECTED ? HIGH : LOW);

  // Read UDP temperature
  int packetSize = udp.parsePacket();
  if (packetSize) {
    int len = udp.read(InputBuffer, sizeof(InputBuffer) - 1);
    if (len < 0) len = 0;
    InputBuffer[len] = '\0';
    double newInput = atof(InputBuffer);
    static bool haveFirst = false;
    if (!haveFirst) { InputFiltered = newInput; haveFirst = true; }
    else            { InputFiltered = ALPHA * newInput + (1.0 - ALPHA) * InputFiltered; }
    Input = InputFiltered;
    if (currentStage != PRE_SPIN) digitalWrite(SenderLedPin, newInput > 0.0 ? HIGH : LOW);
  } else {
    if (currentStage != PRE_SPIN) digitalWrite(SenderLedPin, LOW);
  }

  // === Time base & slope ===
  unsigned long nowMs = millis();
  double dt = (nowMs - lastSlopeMs) / 1000.0;
  if (dt < 0.001) dt = 0.001;

  // *** Instant setpoint steps (slew effectively disabled)
  double maxStep = SLEW_C_PER_S * dt;
  if (Setpoint < SetpointTarget)      Setpoint = min(Setpoint + maxStep, SetpointTarget);
  else if (Setpoint > SetpointTarget) Setpoint = max(Setpoint - maxStep, SetpointTarget);

  double dTdt = (Input - lastInputForSlope) / dt;
  lastInputForSlope = Input;
  lastSlopeMs = nowMs;

  // === Control (skip during PRE_SPIN) ===
  if (currentStage != PRE_SPIN) {
    if (nowMs < heaterInhibitUntilMs) {
      setRelay(false);
    } else {
      double err = Setpoint - Input;
      bool far = fabs(err) > FAST_RAMP_ERR;

      // roll PID window
      if (nowMs - WindowStartTime >= WindowSize) {
        WindowStartTime += WindowSize;
      }

      // dynamic Ki (integral separation)
      double Ki_eff = (fabs(err) < I_ZONE) ? Ki : 0.0;
      myPID.SetTunings(Kp, Ki_eff, Kd);

      bool heatOn = false;

      if (far) {
        // === FAST TRAVEL REGION: Bang-bang ===
        heatOn = (err > 0);   // full ON below setpoint, OFF above
      } else {
        // === PRECISION REGION: PID + coasting ===
        // Predictive coast (look-ahead)
        double T_pred = Input + dTdt * COAST_HORIZON_S;
        bool predictOvershoot = (T_pred > Setpoint - COAST_MARGIN_C);

        // Coast if close & rising fast OR prediction says we’ll overshoot
        bool coastEarly = ((err > 0) && ((Setpoint - Input) < COAST_OFFSET) && (dTdt > SLOPE_COAST_C_PER_S))
                          || predictOvershoot;

        if (coastEarly) {
          heatOn = false;
        } else {
          myPID.Compute();
          bool inDead = fabs(err) < TEMP_DEADBAND;
          if (!inDead) {
            unsigned long posInWin = nowMs - WindowStartTime;
            heatOn = (posInWin < (unsigned long)Output);
          } else {
            heatOn = relayState;  // hold state in deadband
          }
        }
      }

      setRelay(heatOn);
    }
  }

  unsigned long now = millis();

  // === Stage Transitions ===
  switch (currentStage) {
    case PRE_SPIN:
      digitalWrite(SenderLedPin, LOW);
      setRelay(false);
      if (PreSpinRevs > 0 && !preSpinDone) {
        lcd.setCursor(0,0); lcd.print("Pre-Spin Motor   ");
        lcd.setCursor(0,1); lcd.print("RPM:");  lcd.print(PreSpinRPM, 0);
        lcd.setCursor(0,2); lcd.print("Revs: "); lcd.print(PreSpinRevs);
        lcd.setCursor(0,3); lcd.print("Stage: Pre-Spin  ");
        inhibitHeater(MIN_OFF_MS + 100);
        delay(50);
        motor.run(PreSpinRPM, PreSpinRevs);
        preSpinDone = true;
      } else {
        currentStage = INITIAL_HEAT;
        stageStartTime = now;
        // *** more aggressive heat-up, higher Kp and Kd reduce lag without windup (Ki gated)
        Kp = 7.0; Ki = 0.20; Kd = 30.0;
      }
      break;

    case INITIAL_HEAT:
      SetpointTarget = TempInitial;
      if (Input >= TempInitial) {
        currentStage = INITIAL_HOLD;
        stageStartTime = now;
        Kp = 4.0; Ki = 0.12; Kd = 30.0;  // tighter Kd to quell overshoot
      }
      break;

    case INITIAL_HOLD:
      if (now - stageStartTime >= InitialHoldTime) {
        currentStage = HEAT;
        stageStartTime = now;
        Kp = 7.0; Ki = 0.18; Kd = 30.0;  // aggressive ramp again
      }
      break;

    case HEAT:
      SetpointTarget = TempCycleHigh;
      if (Input >= TempCycleHigh) {
        currentStage = HOLD_HIGH;
        stageStartTime = now;
        Kp = 4.2; Ki = 0.12; Kd = 32.0;  // stiffen D a bit at the peak
      }
      break;

    case HOLD_HIGH:
      if (now - stageStartTime >= HoldTimeHigh) {
        currentStage = COOL;
        // keep current gains; predictive coast + I-zone remain active
      }
      break;

    case COOL: {
      SetpointTarget = TempCycleLow;
      inhibitHeater(MIN_OFF_MS + 200);

      int burstCount = 0;
      while (Input > TempCycleLow && burstCount < MaxCoolingBursts) {
        digitalWrite(SenderLedPin, LOW);
        inhibitHeater(MIN_OFF_MS + 100);
        delay(50);
        motor.run(MotorRPM, MotorRevs);
        burstCount++;

        // resample temp between bursts
        unsigned long tStart = millis();
        while (millis() - tStart < 800) {
          int ps = udp.parsePacket();
          if (ps) {
            int len = udp.read(InputBuffer, sizeof(InputBuffer) - 1);
            if (len < 0) len = 0;
            InputBuffer[len] = '\0';
            double newInput = atof(InputBuffer);
            InputFiltered = ALPHA * newInput + (1.0 - ALPHA) * InputFiltered;
            Input = InputFiltered;
            break;
          }
        }

        // LCD/log during cooling
        lcd.setCursor(0,0);
        lcd.print("Temp:");
        lcd.print(Input, 1);
        lcd.print((char)223);
        lcd.print("C");
        lcd.print(fluorActive ? "F " : "  ");
        lcd.setCursor(0,1); lcd.print("Cooling Burst "); lcd.print(burstCount); lcd.print("  ");
        lcd.setCursor(0,2); lcd.print("Set:"); lcd.print(Setpoint, 1); lcd.print((char)223); lcd.print("C   ");
        lcd.setCursor(0,3); lcd.print("Stg: ");
        lcd.print(STAGE_NAME[currentStage]);
        lcd.print(" C:");
        lcd.print(cycleCount + 1); lcd.print("/"); lcd.print(MaxCycles);

        float timeSeconds = millis() / 1000.0;
        Serial.print(timeSeconds, 2); Serial.print(","); Serial.print(Input);
        Serial.print(","); Serial.print(lastFluor_nA, 6);
        Serial.print(","); Serial.print(lastRaw, 6);
        Serial.print(", "); Serial.println(cycleCount, 1);
        delay(50);
      }
      currentStage = HOLD_LOW;
      stageStartTime = millis();
      Kp = 4.0; Ki = 0.12; Kd = 30.0;  // tighter hold
      break;
    }

    case HOLD_LOW:
      if (now - stageStartTime >= HoldTimeLow) {
        cycleCount++;
        if (cycleCount < MaxCycles) {
          currentStage = PAUSE;
          stageStartTime = now;
        } else {
          currentStage = FINAL_HOLD;
          stageStartTime = now;
          SetpointTarget = TempFinalHold;
          Kp = 4.0; Ki = 0.12; Kd = 30.0;
        }
      }
      break;

    case PAUSE:
      if (now - stageStartTime >= PauseTime) {
        modeRun();
        currentStage = HEAT;
        Kp = 7.0; Ki = 0.18; Kd = 30.0;  // ramp up again
      }
      break;

    case FINAL_HOLD:
      SetpointTarget = TempFinalHold;
      if (!finalHoldStarted) {
        lcd.clear();
        lcd.setCursor(0,0); lcd.print("Final Hold 63C");
        finalHoldStarted = true;
        Kp = 4.0; Ki = 0.12; Kd = 30.0;
      }
      if (now - stageStartTime >= FinalHoldTime) {
        setRelay(false);
        lcd.clear();
        lcd.setCursor(0,0); lcd.print("All Complete");
        Serial.println("All cycles + final hold complete.");
        while (true) { /* stop */ }
      }
      break;
  }

  // === LCD Display (Main Status) ===
  lcd.setCursor(0,0);
  lcd.print("Temp:");
  lcd.print(Input, 1);
  lcd.print((char)223);
  lcd.print("C");
  lcd.print(fluorActive ? "F " : "  ");

  lcd.setCursor(0,1);
  if (relayState) lcd.print("Heating         ");
  else            lcd.print("Cooling         ");

  lcd.setCursor(0,2);
  lcd.print("Set:");
  lcd.print(Setpoint, 1);
  lcd.print((char)223);
  lcd.print("C   ");

  lcd.setCursor(0,3);
  lcd.print("Stg:");
  lcd.print(STAGE_NAME[currentStage]);
  lcd.print(" C:");
  lcd.print(cycleCount + 1);
  lcd.print("/");
  lcd.print(MaxCycles);

  // Serial logging
  float timeSeconds = millis() / 1000.0;
  Serial.print(timeSeconds, 2); Serial.print(", "); Serial.print(Input);
  Serial.print(", "); Serial.print(lastFluor_nA, 6);
  Serial.print(", "); Serial.print(lastRaw, 6);
  Serial.print(", "); Serial.println(cycleCount, 1);

  delay(50);
}
