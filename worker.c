#include <Servo.h>
#include <Wire.h>

#define I2C_SDA_PIN 16
#define I2C_SCL_PIN 17
#define NUM_SERVOS 16

const int servoPins[NUM_SERVOS] = {
    0,  1,  -1, -1, -1, -1, -1, -1, // Row A: only col 0-1
    13, 14, -1, -1, -1, -1, -1, -1  // Row B: only col 0-1
};

Servo servos[NUM_SERVOS];
volatile uint32_t messagesReceived = 0;

void setServo(int index, int state) {
  if (index < 0 || index >= NUM_SERVOS)
    return;
  if (servoPins[index] == -1)
    return;
  servos[index].write(state ? 180 : 0);
}

void onReceive(int numBytes) {
  messagesReceived++;
  Serial.printf("[I2C] Got %d bytes: ", numBytes);
  while (Wire.available() >= 2) {
    int index = Wire.read();
    int state = Wire.read();
    if (servoPins[index] != -1) {
      Serial.printf("[%d=%d] ", index, state);
    }
    setServo(index, state);
  }
  while (Wire.available())
    Wire.read();
  Serial.println();
}

void setup() {
  Serial.begin(115200);
  while (!Serial && millis() < 4000)
    delay(10);

  for (int i = 0; i < NUM_SERVOS; i++) {
    if (servoPins[i] != -1) {
      servos[i].attach(servoPins[i], 500, 2500);
      setServo(i, 0);
    }
  }

  Wire.setSDA(I2C_SDA_PIN);
  Wire.setSCL(I2C_SCL_PIN);
  Wire.begin(0x10);
  Wire.onReceive(onReceive);

  Serial.println("[READY] Listening at 0x10");
}

void loop() {
  static unsigned long lastPrint = 0;
  if (millis() - lastPrint >= 5000) {
    lastPrint = millis();
    Serial.printf("[STATUS] Uptime: %lus | Messages: %u\n", millis() / 1000,
                  messagesReceived);
  }
}