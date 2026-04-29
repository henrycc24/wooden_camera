#include <Adafruit_NeoPixel.h>
#include <Arduino.h>
#include <Wire.h>
#include <stdint.h>

#if defined(ARDUINO_ARCH_RP2040)
#include <LEAmDNS.h>
#include <WebSocketsServer.h>
#include <WiFi.h>
#endif

const char *WIFI_SSID = "RedRover";
const char *WIFI_PASSWORD = "";

#define NEOPIXEL_PIN 15
#define NUM_LEDS 30
#define I2C_SDA_PIN 4
#define I2C_SCL_PIN 5
#define I2C_CLOCK_HZ 400000

#define NUM_WORKERS 4
#define SERVOS_PER_WORKER 16
#define ROWS_PER_WORKER 2
#define GRID_ROWS 8
#define GRID_COLS 8

const uint8_t WORKER_ADDR[NUM_WORKERS] = {0x10, 0x11, 0x12, 0x13};

#define WIFI_CONNECT_TIMEOUT_MS 30000
#define WIFI_RECONNECT_INTERVAL 10000
#define SERIAL_FRAME_TIMEOUT_MS 100
#define I2C_TIMEOUT_MS 5
#define HEARTBEAT_INTERVAL_MS 5000
#define WS_PORT 81

#define START_BYTE 0xFF
#define FRAME_SIZE 8

#define MDNS_HOSTNAME "flipdot"

enum SystemState {
  STATE_BOOT,
  STATE_WIFI_CONNECTING,
  STATE_WIFI_CONNECTED,
  STATE_READY,
  STATE_WIFI_FAILED,
  STATE_SERIAL_ONLY
};

SystemState state = STATE_BOOT;

Adafruit_NeoPixel strip(NUM_LEDS, NEOPIXEL_PIN, NEO_GRB + NEO_KHZ800);

#if defined(ARDUINO_ARCH_RP2040)
WebSocketsServer ws = WebSocketsServer(WS_PORT);
#endif

uint8_t currentGrid[GRID_ROWS] = {0};
bool workerAlive[NUM_WORKERS] = {false};
int workerFailCount[NUM_WORKERS] = {0};

unsigned long lastHeartbeat = 0;
unsigned long lastReconnectTry = 0;
uint32_t framesReceived = 0;
uint32_t framesErrors = 0;

void ledSolid(uint8_t r, uint8_t g, uint8_t b) {
  strip.fill(strip.Color(r, g, b));
  strip.show();
}

void ledFlash(uint8_t r, uint8_t g, uint8_t b, uint16_t ms = 40) {
  ledSolid(r, g, b);
  delay(ms);
  ledShowState();
}

void ledShowState() {
  switch (state) {
  case STATE_BOOT:
    ledSolid(128, 0, 128);
    break;
  case STATE_WIFI_CONNECTING:
    ledSolid(128, 128, 0);
    break;
  case STATE_WIFI_CONNECTED:
    ledSolid(128, 128, 0);
    break;
  case STATE_READY:
    ledSolid(0, 200, 200);
    break;
  case STATE_WIFI_FAILED:
    ledSolid(255, 60, 0);
    break;
  case STATE_SERIAL_ONLY:
    ledSolid(255, 255, 255);
    break;
  }
}

bool sendRowsToWorker(int worker, uint8_t rowA, uint8_t rowB);

bool probeWorker(uint8_t addr) {
  Wire.beginTransmission(addr);
  return (Wire.endTransmission() == 0);
}

void scanWorkers() {
  Serial.println("[I2C] Scanning workers with test transmission...");
  int found = 0;
  for (int i = 0; i < NUM_WORKERS; i++) {
    workerAlive[i] = sendRowsToWorker(i, 0x00, 0x00);
    workerFailCount[i] = 0;
    if (workerAlive[i]) {
      Serial.printf("  Worker %d (0x%02X): OK — rows %d-%d\n", i,
                    WORKER_ADDR[i], i * 2, i * 2 + 1);
      found++;
    } else {
      Serial.printf("  Worker %d (0x%02X): NOT FOUND\n", i, WORKER_ADDR[i]);
    }
  }
  Serial.printf("[I2C] %d / %d workers online\n", found, NUM_WORKERS);
}

bool sendRowsToWorker(int worker, uint8_t rowA, uint8_t rowB) {
  Wire.beginTransmission(WORKER_ADDR[worker]);

  for (int col = 0; col < GRID_COLS; col++) {
    uint8_t servoIdx = col;
    uint8_t servoState = (rowA >> (7 - col)) & 1;
    Wire.write(servoIdx);
    Wire.write(servoState);
  }

  for (int col = 0; col < GRID_COLS; col++) {
    uint8_t servoIdx = 8 + col;
    uint8_t servoState = (rowB >> (7 - col)) & 1;
    Wire.write(servoIdx);
    Wire.write(servoState);
  }

  uint8_t err = Wire.endTransmission();

  if (err != 0) {
    workerFailCount[worker]++;
    if (workerFailCount[worker] >= 5 && workerAlive[worker]) {
      Serial.printf(
          "[I2C] Worker %d unresponsive (%d fails), marking offline\n", worker,
          workerFailCount[worker]);
      workerAlive[worker] = false;
    }
    return false;
  }

  if (!workerAlive[worker]) {
    Serial.printf("[I2C] Worker %d (0x%02X) responded! Marking online.\n",
                  worker, WORKER_ADDR[worker]);
    workerAlive[worker] = true;
  }
  workerFailCount[worker] = 0;
  return true;
}

void updateGrid(const uint8_t newGrid[GRID_ROWS]) {
  bool changed = false;
  for (int w = 0; w < NUM_WORKERS; w++) {
    int rowA = w * 2;
    int rowB = w * 2 + 1;

    if (newGrid[rowA] != currentGrid[rowA] ||
        newGrid[rowB] != currentGrid[rowB]) {
      sendRowsToWorker(w, newGrid[rowA], newGrid[rowB]);
      currentGrid[rowA] = newGrid[rowA];
      currentGrid[rowB] = newGrid[rowB];
      changed = true;
    }
  }
#if defined(ARDUINO_ARCH_RP2040)
  if (changed && ws.connectedClients() > 0) {
    uint8_t syncMsg[9];
    syncMsg[0] = START_BYTE;
    memcpy(&syncMsg[1], currentGrid, 8);
    ws.broadcastBIN(syncMsg, 9);
  }
#endif
}

void resetGrid() {
  uint8_t blank[GRID_ROWS] = {0};
  for (int row = 0; row < GRID_ROWS; row++) {
    currentGrid[row] = 0xFF;
  }
  updateGrid(blank);
  Serial.println("[GRID] Reset to all-zero");
}

bool processFrame(const uint8_t *buf, size_t len) {
  if (len != 9 || buf[0] != START_BYTE) {
    framesErrors++;
    return false;
  }

  uint8_t newGrid[GRID_ROWS];
  for (int i = 0; i < GRID_ROWS; i++) {
    newGrid[i] = buf[i + 1];
  }
  updateGrid(newGrid);
  framesReceived++;
  return true;
}

#if defined(ARDUINO_ARCH_RP2040)
void handleTextCommand(uint8_t clientNum, const String &cmd);

void onWebSocketEvent(uint8_t clientNum, WStype_t type, uint8_t *payload,
                      size_t length) {
  switch (type) {
  case WStype_CONNECTED: {
    IPAddress ip = ws.remoteIP(clientNum);
    Serial.printf("[WS] Client %u connected from %d.%d.%d.%d\n", clientNum,
                  ip[0], ip[1], ip[2], ip[3]);
    state = STATE_READY;
    ledShowState();

    uint8_t syncMsg[9];
    syncMsg[0] = START_BYTE;
    memcpy(&syncMsg[1], currentGrid, 8);
    ws.sendBIN(clientNum, syncMsg, 9);
    break;
  }

  case WStype_DISCONNECTED:
    Serial.printf("[WS] Client %u disconnected\n", clientNum);
    if (ws.connectedClients() == 0) {
      state = STATE_WIFI_CONNECTED;
      ledShowState();
    }
    break;

  case WStype_BIN:
    if (processFrame(payload, length)) {
      ledFlash(0, 255, 0, 30);
    } else {
      ledFlash(255, 0, 0, 50);
      Serial.printf("[WS] Bad frame from client %u (len=%u)\n", clientNum,
                    length);
    }
    break;

  case WStype_TEXT:
    if (length > 0) {
      String cmd = String((char *)payload).substring(0, length);
      cmd.trim();
      handleTextCommand(clientNum, cmd);
    }
    break;

  default:
    break;
  }
}

void handleTextCommand(uint8_t clientNum, const String &cmd) {
  if (cmd == "ping") {
    ws.sendTXT(clientNum, "pong");
  } else if (cmd == "reset") {
    resetGrid();
    ws.sendTXT(clientNum, "ok:reset");
  } else if (cmd == "status") {
    String s = "status:frames=" + String(framesReceived) +
               ",errors=" + String(framesErrors) + ",workers=";
    for (int i = 0; i < NUM_WORKERS; i++) {
      s += workerAlive[i] ? "1" : "0";
    }
    s += ",topology=4x16";
    ws.sendTXT(clientNum, s.c_str());
  } else if (cmd == "scan") {
    scanWorkers();
    ws.sendTXT(clientNum, "ok:scan");
  } else {
    ws.sendTXT(clientNum, "err:unknown_cmd");
  }
}
#endif

void pollSerial() {
  while (Serial.available() > 0) {
    uint8_t b = Serial.read();

    if (b == START_BYTE) {
      uint8_t frameBuf[9];
      frameBuf[0] = START_BYTE;

      unsigned long t0 = millis();
      int idx = 1;

      while (idx < 9 && (millis() - t0) < SERIAL_FRAME_TIMEOUT_MS) {
        if (Serial.available() > 0) {
          frameBuf[idx++] = Serial.read();
        }
      }

      if (idx == 9) {
        if (processFrame(frameBuf, 9)) {
          ledFlash(0, 255, 0, 30);
        } else {
          ledFlash(255, 0, 0, 50);
        }
      } else {
        framesErrors++;
        Serial.printf("[SERIAL] Incomplete frame (%d/9 bytes)\n", idx);
        ledFlash(255, 0, 0, 50);
      }
    }
  }
}

#if defined(ARDUINO_ARCH_RP2040)

void printMac() {
  uint8_t mac[6];
  WiFi.macAddress(mac);
  Serial.print("[WIFI] MAC: ");
  for (int i = 0; i < 6; i++) {
    if (mac[i] < 0x10)
      Serial.print("0");
    Serial.print(mac[i], HEX);
    if (i < 5)
      Serial.print(":");
  }
  Serial.println();
  Serial.println("[WIFI] >>> Register this MAC at network.cornell.edu <<<");
}

bool connectWiFi() {
  WiFi.mode(WIFI_STA);
  printMac();

  Serial.printf("[WIFI] Connecting to \"%s\"", WIFI_SSID);

  if (strlen(WIFI_PASSWORD) > 0) {
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  } else {
    WiFi.begin(WIFI_SSID);
  }

  state = STATE_WIFI_CONNECTING;
  unsigned long t0 = millis();
  bool toggle = false;

  while (WiFi.status() != WL_CONNECTED) {
    if (millis() - t0 > WIFI_CONNECT_TIMEOUT_MS) {
      Serial.println("\n[WIFI] Connection timed out!");
      Serial.println("[WIFI] Falling back to serial-only mode.");
      WiFi.disconnect();
      return false;
    }

    toggle = !toggle;
    if (toggle)
      ledSolid(128, 128, 0);
    else
      ledSolid(0, 0, 0);
    delay(250);
    Serial.print(".");
  }

  Serial.println();
  Serial.print("[WIFI] Connected! IP: ");
  Serial.println(WiFi.localIP());
  Serial.printf("[WIFI] RSSI: %d dBm\n", WiFi.RSSI());
  return true;
}

void startWebSocketServer() {
  ws.begin();
  ws.onEvent(onWebSocketEvent);
  Serial.printf("[WS] Server listening on port %d\n", WS_PORT);
  Serial.printf("[WS] Connect at:  ws://%s:%d\n",
                WiFi.localIP().toString().c_str(), WS_PORT);

  if (MDNS.begin(MDNS_HOSTNAME)) {
    MDNS.addService("ws", "tcp", WS_PORT);
    Serial.printf("[MDNS] Reachable at %s.local\n", MDNS_HOSTNAME);
  } else {
    Serial.println("[MDNS] Failed to start — use IP address instead");
  }
}

#include <WiFiUdp.h>

WiFiUDP Udp;
const unsigned int localUdpPort = 8888;

void checkWiFiHealth() {
  if (state == STATE_WIFI_FAILED) {
    if (millis() - lastReconnectTry > WIFI_RECONNECT_INTERVAL) {
      lastReconnectTry = millis();
      Serial.println("[WIFI] Attempting reconnection...");
      if (connectWiFi()) {
        startWebSocketServer();
        Udp.begin(localUdpPort);
        Serial.printf("[UDP] Listening on port %d\n", localUdpPort);
        state = STATE_WIFI_CONNECTED;
        ledShowState();
      }
    }
    return;
  }

  if (WiFi.status() != WL_CONNECTED && state != STATE_WIFI_CONNECTING) {
    Serial.println("[WIFI] Connection lost!");
    state = STATE_WIFI_FAILED;
    ledShowState();
  }
}

void pollUDP() {
  int packetSize = Udp.parsePacket();
  if (packetSize > 0) {
    uint8_t packetBuffer[32];
    int len = Udp.read(packetBuffer, sizeof(packetBuffer));
    if (len >= 9) {
      if (processFrame(packetBuffer, 9)) {
        ledFlash(0, 0, 255, 30); // Flash blue for UDP
      } else {
        ledFlash(255, 0, 0, 50);
      }
    }
  }
}

#endif

void heartbeat() {
  if (millis() - lastHeartbeat < HEARTBEAT_INTERVAL_MS)
    return;
  lastHeartbeat = millis();

  Serial.println("────────────────────────────────");
  Serial.printf("[STATUS] Uptime: %lu s\n", millis() / 1000);
  Serial.printf("[STATUS] State: %d  |  Frames: %u ok, %u err\n", (int)state,
                framesReceived, framesErrors);
  Serial.printf("[STATUS] Topology: %d workers × %d servos = %d total\n",
                NUM_WORKERS, SERVOS_PER_WORKER,
                NUM_WORKERS * SERVOS_PER_WORKER);

#if defined(ARDUINO_ARCH_RP2040)
  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("[STATUS] WiFi RSSI: %d dBm  |  WS clients: %d  |  IP: %s\n",
                  WiFi.RSSI(), ws.connectedClients(), WiFi.localIP().toString().c_str());
  }
#endif

  Serial.print("[STATUS] Grid: ");
  for (int r = 0; r < GRID_ROWS; r++) {
    Serial.printf("%02X ", currentGrid[r]);
  }
  Serial.println();

  Serial.print("[STATUS] Workers: ");
  for (int i = 0; i < NUM_WORKERS; i++) {
    Serial.printf("%s[%d:%d-%d] ", workerAlive[i] ? "●" : "○", i, i * 2,
                  i * 2 + 1);
  }
  Serial.println();
}

void setup() {
  Serial.begin(115200);
  unsigned long serialWait = millis();
  while (!Serial && (millis() - serialWait < 4000)) {
    delay(10);
  }

  Serial.println();
  Serial.println("════════════════════════════════════════");
  Serial.println("  Wooden Mirror — Master Controller");
  Serial.println("  4 Workers × 16 Servos (64 total)");
  Serial.println("  Pico W — Cornell RedRover");
  Serial.println("════════════════════════════════════════");

  strip.begin();
  strip.setBrightness(60);
  state = STATE_BOOT;
  ledShowState();

  Wire.setSDA(I2C_SDA_PIN);
  Wire.setSCL(I2C_SCL_PIN);
  Wire.begin();
  Wire.setClock(I2C_CLOCK_HZ);
  Wire.setTimeout(I2C_TIMEOUT_MS);
  Serial.printf("[I2C] Bus init: SDA=%d SCL=%d @ %d Hz\n", I2C_SDA_PIN,
                I2C_SCL_PIN, I2C_CLOCK_HZ);

  scanWorkers();

  Serial.println("[GRID] Initializing servos to home position...");
  resetGrid();

#if defined(ARDUINO_ARCH_RP2040)
  if (connectWiFi()) {
    startWebSocketServer();
    Udp.begin(localUdpPort);
    Serial.printf("[UDP] Listening on port %d\n", localUdpPort);
    state = STATE_WIFI_CONNECTED;
  } else {
    state = STATE_WIFI_FAILED;
  }
#else
  state = STATE_SERIAL_ONLY;
  Serial.println("[MODE] Serial-only (non-WiFi build)");
#endif

  ledShowState();
  Serial.println("[READY] Accepting frames via WebSocket and Serial");
  Serial.println();
}

void loop() {
#if defined(ARDUINO_ARCH_RP2040)
  ws.loop();
  MDNS.update();
  checkWiFiHealth();

  static int prevClients = 0;
  int clients = ws.connectedClients();
  if (clients > 0 && prevClients == 0) {
    state = STATE_READY;
    ledShowState();
  } else if (clients == 0 && prevClients > 0) {
    if (WiFi.status() == WL_CONNECTED) {
      state = STATE_WIFI_CONNECTED;
    }
    ledShowState();
  }
  prevClients = clients;
  pollUDP();
#endif

  pollSerial();
  heartbeat();
}