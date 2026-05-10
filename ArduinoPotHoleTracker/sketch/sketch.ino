#include <Wire.h>
#include <Arduino_LSM6DSOX.h>
#include "Modulino.h"
#include <Arduino_RouterBridge.h>

ModulinoMovement movement;
ModulinoPixels leds;
int brightness = 25;

const int NUM_LEDS = 8;
unsigned long lastLedActivation = 0;

ModulinoBuzzer buzzer;
ModulinoKnob knob;

int frequency = 440;  // Frequency of the tone in Hz
int duration = 100;

// Motion detection thresholds
const float MOTION_THRESHOLD = 0.15;  // g units for acceleration
const float ROTATION_THRESHOLD = 20.0;  // degrees per second

// Calibration variables
float baseX = 0, baseY = 0, baseZ = 1.0; 
float baseRoll = 0, basePitch = 0, baseYaw = 0;
bool isCalibrated = false;

// Motion state tracking
bool inMotion = false;
unsigned long motionStartTime = 0;
unsigned long stillStartTime = 0;
const unsigned long STILL_TIMEOUT = 2000;  // 2 seconds to detect stillness

void setup() {
  Serial.begin(9600);
  Modulino.begin();
  movement.begin();
  buzzer.begin();
  leds.begin();
  knob.begin();
  // INICIEM EL PONT AMB PYTHON
  Bridge.begin(); 
  
  Serial.println("Motion Detection System");
  Serial.println("Keep device still for calibration...");
  
  delay(2000);
  calibrateSensor();
}

void calibrateSensor() {
  const int samples = 50;
  float sumX = 0, sumY = 0, sumZ = 0;
  
  for (int i = 0; i < samples; i++) {
    movement.update();
    sumX += movement.getX();
    sumY += movement.getY();
    sumZ += movement.getZ();
    delay(20);
  }
  
  baseX = sumX / samples;
  baseY = sumY / samples;
  baseZ = sumZ / samples;
  
  isCalibrated = true;
  Serial.println("✓ Calibration complete!");
}

bool detectMotion() {
  bool ret = false;
  movement.update();
  
  float deltaX = abs(movement.getX() - baseX);
  float deltaY = abs(movement.getY() - baseY);
  float deltaZ = abs(movement.getZ() - baseZ);
  
  bool motionDetected = (deltaX > MOTION_THRESHOLD || 
                         deltaY > MOTION_THRESHOLD || 
                         deltaZ > MOTION_THRESHOLD);
  
  if (motionDetected && !inMotion) {
    inMotion = true;
    motionStartTime = millis();
    Serial.println("🏃 MOTION DETECTED!");
    
    // AVISAR A PYTHON QUE LA BICI ES MOU
    Bridge.call("motion_started");
    ret = true;
  }
  else if (!motionDetected && inMotion) {
    if (stillStartTime == 0) {
      stillStartTime = millis();
    }
    else if (millis() - stillStartTime > STILL_TIMEOUT) {
      inMotion = false;
      Serial.println("✋ Motion stopped.");
      stillStartTime = 0;
      
      // AVISAR A PYTHON QUE LA BICI ESTÀ ATURADA
      Bridge.call("motion_stopped");
    }
    ret = false;
  }
  else if (motionDetected && inMotion) {
    stillStartTime = 0;
    ret = true;
  }
  return ret;
}

void changeLedsPotholes(int amount)
{
  for (int i = 0; i < amount; i++) {
    leds.set(i, RED, brightness);
  }
  leds.show();
}

void changeBuzzerPotholes()
{
  buzzer.tone(frequency, duration);
}

void tmp()
{
  return ;
}

void loop() {
  // IMPORTANT: Mantenir viu el pont de comunicació
  Bridge.update(); 

  if (knob.isPressed())
  {
    Bridge.provide("park_button_pressed", tmp);
  }
  if (isCalibrated) {
    if (detectMotion())
    {
      int potholes_num = 0;
      bool do_leds_potholes = false;
      Bridge.call("do_leds_potholes").result(do_leds_potholes);
      Bridge.call("leds_potholes").result(potholes_num);

      bool cooldownFinished = (millis() - lastLedActivation) > 5000;
      if (do_leds_potholes && potholes_num && cooldownFinished) {
        // Save activation time
        lastLedActivation = millis();
        changeBuzzerPotholes();
        changeLedsPotholes(potholes_num);
      }
      else {
        for (int i = 0; i < NUM_LEDS; i++) {
          leds.set(i, RED, 0);
        }
        leds.show();
      }
    }
    delay(50);
  }
}