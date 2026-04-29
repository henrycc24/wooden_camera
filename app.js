/**
 * app.js — Wooden Mirror Control Panel
 *
 * Combines:
 *   - Camera capture & image processing
 *   - Manual testing grid
 *   - Communication with Python bridge server
 */

const BRIDGE_URL = 'http://localhost:5123';

const app = {
  // ── State ──
  processor: null,
  cameraStream: null,
  cameraRunning: false,
  autoSend: true,
  sendInterval: 200,   // ms between sends
  sendTimerId: null,
  isSending: false,    // Prevent concurrent sends
  connected: false,
  lastSentTime: null,
  frameCount: 0,
  fpsTimerId: null,

  // Testing grid state: 8×8 array of 0s and 1s
  testGrid: Array.from({ length: 8 }, () => Array(8).fill(0)),

  // Current camera grid (for display and sending)
  currentCameraGrid: Array.from({ length: 8 }, () => Array(8).fill(0)),
  
  // Connection state
  connectionMode: 'serial', // 'serial' | 'wireless'
  webSocket: null,

  // ──────────────────────────────────────────
  // Initialization
  // ──────────────────────────────────────────
  init() {
    this.processor = new ImageProcessor(128);
    this.buildGrid('camera-grid', false);
    this.buildGrid('testing-grid', true);
    this.refreshPorts();
    this.startFpsCounter();
  },

  // ──────────────────────────────────────────
  // Tab Switching
  // ──────────────────────────────────────────
  switchTab(tabName) {
    document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
    document.getElementById(`tab-${tabName}`).classList.add('active');
    document.getElementById(`tab-btn-${tabName}`).classList.add('active');
  },

  // ──────────────────────────────────────────
  // Grid Building
  // ──────────────────────────────────────────
  buildGrid(containerId, clickable) {
    const container = document.getElementById(containerId);
    container.innerHTML = '';

    for (let row = 0; row < 8; row++) {
      for (let col = 0; col < 8; col++) {
        const cell = document.createElement('div');
        cell.className = 'wooden-cell white';
        cell.dataset.row = row;
        cell.dataset.col = col;
        cell.id = `${containerId}-cell-${row}-${col}`;

        if (clickable) {
          cell.addEventListener('click', () => this.toggleTestCell(row, col));
        }

        container.appendChild(cell);
      }
    }
  },

  // ──────────────────────────────────────────
  // Grid Rendering
  // ──────────────────────────────────────────
  renderGrid(containerId, grid) {
    for (let row = 0; row < 8; row++) {
      for (let col = 0; col < 8; col++) {
        const cell = document.getElementById(`${containerId}-cell-${row}-${col}`);
        if (!cell) continue;

        const newClass = grid[row][col] ? 'black' : 'white';
        const oldClass = grid[row][col] ? 'white' : 'black';

        if (cell.classList.contains(oldClass)) {
          cell.classList.remove(oldClass);
          cell.classList.add(newClass);
          // Trigger flip animation
          cell.classList.remove('flipping');
          void cell.offsetWidth; // force reflow
          cell.classList.add('flipping');
        }
      }
    }
  },

  updateBytePreview(previewId, grid) {
    const bytes = ImageProcessor.gridToBytes(grid);
    const hexStr = bytes.map(b => '0x' + b.toString(16).padStart(2, '0').toUpperCase()).join('  ');
    const binStr = bytes.map(b => b.toString(2).padStart(8, '0')).join('  ');
    document.getElementById(previewId).textContent =
      `HEX: ${hexStr}\nBIN: ${binStr}`;
  },

  // ──────────────────────────────────────────
  // Camera
  // ──────────────────────────────────────────
  async startCamera() {
    try {
      const video = document.getElementById('camera-video');
      video.crossOrigin = "anonymous";
      video.src = `${BRIDGE_URL}/api/camera/stream?t=${Date.now()}`;

      this.cameraRunning = true;
      document.getElementById('video-overlay').classList.add('hidden');
      document.getElementById('btn-start-camera').disabled = true;
      document.getElementById('btn-stop-camera').disabled = false;
      document.getElementById('status-camera-dot').classList.add('active');
      document.getElementById('status-camera-text').textContent = 'Camera: active';

      this.toast('HM01B0 Camera started', 'success');
      this.startProcessingLoop();
    } catch (err) {
      this.toast(`Camera error: ${err.message}`, 'error');
      console.error('Camera error:', err);
    }
  },

  stopCamera() {
    this.cameraRunning = false;
    this.stopProcessingLoop();

    const video = document.getElementById('camera-video');
    video.src = "";

    document.getElementById('video-overlay').classList.remove('hidden');
    document.getElementById('btn-start-camera').disabled = false;
    document.getElementById('btn-stop-camera').disabled = true;
    document.getElementById('status-camera-dot').classList.remove('active');
    document.getElementById('status-camera-text').textContent = 'Camera: off';

    this.toast('Camera stopped', 'info');
  },

  // ──────────────────────────────────────────
  // Processing Loop
  // ──────────────────────────────────────────
  startProcessingLoop() {
    this.stopProcessingLoop();

    const loop = async () => {
      if (!this.cameraRunning) return;

      const video = document.getElementById('camera-video');
      if (video.complete && video.naturalHeight !== 0) {
        // Process frame
        this.currentCameraGrid = this.processor.process(video);
        this.renderGrid('camera-grid', this.currentCameraGrid);
        this.updateBytePreview('camera-byte-preview', this.currentCameraGrid);
        this.frameCount++;

        // Auto-send if enabled and not currently sending
        if (this.autoSend && !this.isSending) {
          await this.sendGrid(this.currentCameraGrid);
        }
      }

      this.sendTimerId = setTimeout(loop, this.sendInterval);
    };

    loop();
  },

  stopProcessingLoop() {
    if (this.sendTimerId) {
      clearTimeout(this.sendTimerId);
      this.sendTimerId = null;
    }
  },

  // ──────────────────────────────────────────
  // Threshold & Interval Controls
  // ──────────────────────────────────────────
  onThresholdChange(value) {
    this.processor.setThreshold(parseInt(value));
    document.getElementById('threshold-value').textContent = value;
  },

  onIntervalChange(value) {
    this.sendInterval = parseInt(value);
    const fps = Math.round(1000 / this.sendInterval);
    document.getElementById('interval-value').textContent = `${fps} fps`;

    // Restart loop with new interval
    if (this.cameraRunning) {
      this.startProcessingLoop();
    }
  },

  onAutoSendToggle(checked) {
    this.autoSend = checked;
  },

  // ──────────────────────────────────────────
  // Testing Grid
  // ──────────────────────────────────────────
  toggleTestCell(row, col) {
    this.testGrid[row][col] = this.testGrid[row][col] ? 0 : 1;
    this.renderGrid('testing-grid', this.testGrid);
    this.updateBytePreview('testing-byte-preview', this.testGrid);
  },

  fillTestGrid(value) {
    this.testGrid = Array.from({ length: 8 }, () => Array(8).fill(value));
    this.renderGrid('testing-grid', this.testGrid);
    this.updateBytePreview('testing-byte-preview', this.testGrid);
  },

  checkerboardTestGrid() {
    this.testGrid = Array.from({ length: 8 }, (_, r) =>
      Array.from({ length: 8 }, (_, c) => (r + c) % 2 === 0 ? 1 : 0)
    );
    this.renderGrid('testing-grid', this.testGrid);
    this.updateBytePreview('testing-byte-preview', this.testGrid);
  },

  invertTestGrid() {
    this.testGrid = this.testGrid.map(row => row.map(v => v ? 0 : 1));
    this.renderGrid('testing-grid', this.testGrid);
    this.updateBytePreview('testing-byte-preview', this.testGrid);
  },

  sendTestGrid() {
    this.sendGrid(this.testGrid);
  },

  sendCurrentGrid() {
    this.sendGrid(this.currentCameraGrid);
  },

  // ──────────────────────────────────────────
  // Communication with Hardware
  // ──────────────────────────────────────────
  async sendGrid(grid) {
    if (this.isSending) return;
    this.isSending = true;

    try {
      const gridBytes = ImageProcessor.gridToBytes(grid);

      if (this.connectionMode === 'wireless' && this.webSocket && this.webSocket.readyState === WebSocket.OPEN) {
        // Wireless mode: send raw 9-byte ArrayBuffer
        const buffer = new Uint8Array(9);
        buffer[0] = 0xFF; // Start byte
        for (let i = 0; i < 8; i++) {
          buffer[i + 1] = gridBytes[i];
        }
        this.webSocket.send(buffer);
        this.updateSendStatus();

      } else if (this.connectionMode === 'serial') {
        // Serial mode: send JSON to Bridge Server
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 2000); // 2 second timeout

        const resp = await fetch(`${BRIDGE_URL}/api/grid`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ grid }),
          signal: controller.signal
        });

        clearTimeout(timeoutId);
        const data = await resp.json();
        
        if (!resp.ok) {
          console.warn('[UI] Bridge error:', data.error);
          this.isSending = false;
          return;
        }

        this.updateSendStatus();
      }
    } catch (err) {
      if (err.name === 'AbortError') {
        console.warn('[UI] Send grid timeout (server took >2000ms)');
      } else {
        console.warn(`[UI] Connection failed: ${err.message}`);
      }
      
      if (!this.autoSend || !this.cameraRunning) {
        this.toast('Connection failed or timed out', 'error');
      }
    } finally {
      this.isSending = false;
    }
  },

  updateSendStatus() {
    this.lastSentTime = new Date();
    document.getElementById('status-last-sent').textContent =
      `Last sent: ${this.lastSentTime.toLocaleTimeString()}`;
  },

  // ──────────────────────────────────────────
  // Connection Management
  // ──────────────────────────────────────────
  onModeChange(mode) {
    this.connectionMode = mode;
    if (mode === 'serial') {
      document.getElementById('serial-controls').style.display = 'flex';
      document.getElementById('wireless-controls').style.display = 'none';
      document.getElementById('btn-connect').textContent = 'Connect Bridge';
    } else {
      document.getElementById('serial-controls').style.display = 'none';
      document.getElementById('wireless-controls').style.display = 'flex';
      document.getElementById('btn-connect').textContent = 'Connect WiFi';
    }
    
    // Disconnect if we switch modes
    if (this.connected) {
      this.disconnect();
    }
  },
  async refreshPorts() {
    try {
      const resp = await fetch(`${BRIDGE_URL}/api/ports`);
      const data = await resp.json();

      const select = document.getElementById('port-select');
      const currentVal = select.value;
      select.innerHTML = '<option value="">Select port...</option>';

      (data.ports || []).forEach(p => {
        const opt = document.createElement('option');
        opt.value = p.device;
        opt.textContent = `${p.device} — ${p.description}`;
        select.appendChild(opt);
      });

      if (currentVal) select.value = currentVal;
    } catch {
      // Bridge not running
    }
  },

  async toggleConnection() {
    if (this.connected) {
      await this.disconnect();
    } else {
      await this.connect();
    }
  },

  async connect() {
    if (this.connectionMode === 'serial') {
      await this.connectSerialBridge();
    } else {
      this.connectWireless();
    }
  },

  connectWireless() {
    const ip = document.getElementById('ip-input').value.trim();
    if (!ip) {
      this.toast('Please enter the Pico W IP address', 'error');
      return;
    }

    if (ip === "localhost" || ip === "127.0.0.1") {
      this.connected = true;
      this.updateConnectionUI(`Bridge UDP`, 'btn-danger', 'Disconnect');
      this.cameraRunning = true; // Block local processing
      this.toast(`Connected to Local UDP Bridge!`, 'success');
      
      this.udpPollTimer = setInterval(async () => {
        try {
          const resp = await fetch(`${BRIDGE_URL}/api/wireless_grid`);
          if (resp.ok) {
            const data = await resp.json();
            const receivedGrid = ImageProcessor.bytesToGrid(data.grid);
            this.currentCameraGrid = receivedGrid;
            this.renderGrid('camera-grid', receivedGrid);
            this.updateBytePreview('camera-byte-preview', receivedGrid);
          }
        } catch (e) {}
      }, 100);
      return;
    }

    this.toast(`Connecting to ws://${ip}:81...`, 'info');
    
    // Connect websocket
    try {
      this.webSocket = new WebSocket(`ws://${ip}:81/`);
      this.webSocket.binaryType = 'arraybuffer';
      
      this.webSocket.onopen = (e) => {
        this.connected = true;
        this.updateConnectionUI(`WiFi: ${ip}`, 'btn-danger', 'Disconnect');
        this.toast(`Connected wirelessly to Pico W!`, 'success');
      };

      this.webSocket.onmessage = (e) => {
        if (e.data instanceof ArrayBuffer) {
          const bytes = new Uint8Array(e.data);
          if (bytes.length === 9 && bytes[0] === 0xFF) {
            const gridBytes = Array.from(bytes.slice(1));
            const receivedGrid = ImageProcessor.bytesToGrid(gridBytes);
            
            // Only update UI if we aren't actively processing a local camera
            if (!this.cameraRunning) {
              this.currentCameraGrid = receivedGrid;
              this.renderGrid('camera-grid', receivedGrid);
              this.updateBytePreview('camera-byte-preview', receivedGrid);
            }
          }
        }
      };

      this.webSocket.onerror = (e) => {
        this.toast(`WebSocket error. Check IP address.`, 'error');
        this.disconnect();
      };

      this.webSocket.onclose = (e) => {
        if (this.connected) {
           this.toast('Wireless connection lost', 'warning');
        }
        this.disconnect();
      };

    } catch (err) {
      this.toast(`Invalid IP or network error`, 'error');
    }
  },

  async connectSerialBridge() {
    const port = document.getElementById('port-select').value;
    try {
      const resp = await fetch(`${BRIDGE_URL}/api/connect`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ port: port || undefined })
      });
      const data = await resp.json();

      if (resp.ok) {
        this.connected = true;
        this.updateConnectionUI(`Bridge: ${data.port}`, 'btn-danger', 'Disconnect');
        this.toast(`Connected to ${data.port}`, 'success');
      } else {
        this.toast(data.error || 'Bridge connection failed', 'error');
      }
    } catch {
      this.toast('Bridge server not reachable', 'error');
    }
  },

  updateConnectionUI(statusText, btnClass, btnText) {
    if (this.connected) {
      document.getElementById('connection-dot').classList.add('connected');
      document.getElementById('status-connection-dot').classList.add('active');
    } else {
      document.getElementById('connection-dot').classList.remove('connected');
      document.getElementById('status-connection-dot').classList.remove('active');
    }
    
    document.getElementById('connection-status').textContent = this.connected ? statusText : 'Disconnected';
    document.getElementById('status-connection-text').textContent = `Connection: ${this.connected ? statusText : 'disconnected'}`;
    
    const btn = document.getElementById('btn-connect');
    btn.textContent = btnText;
    btn.className = `btn ${btnClass}`;
  },

  async disconnect() {
    if (this.udpPollTimer) {
      clearInterval(this.udpPollTimer);
      this.udpPollTimer = null;
      this.cameraRunning = false;
    }
    
    if (this.connectionMode === 'serial') {
      try {
        await fetch(`${BRIDGE_URL}/api/disconnect`, { method: 'POST' });
      } catch { /* ignore */ }
    } else if (this.webSocket) {
      this.webSocket.close();
      this.webSocket = null;
    }

    this.connected = false;
    const connectText = this.connectionMode === 'serial' ? 'Connect Bridge' : 'Connect WiFi';
    this.updateConnectionUI('Disconnected', 'btn-success', connectText);
    this.toast('Disconnected', 'info');
  },

  // ──────────────────────────────────────────
  // FPS counter
  // ──────────────────────────────────────────
  startFpsCounter() {
    let lastCount = 0;
    this.fpsTimerId = setInterval(() => {
      const fps = this.frameCount - lastCount;
      lastCount = this.frameCount;
      document.getElementById('status-fps-text').textContent =
        `FPS: ${this.cameraRunning ? fps : '—'}`;
    }, 1000);
  },

  // ──────────────────────────────────────────
  // Toast Notifications
  // ──────────────────────────────────────────
  toast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);

    setTimeout(() => {
      if (toast.parentNode) toast.parentNode.removeChild(toast);
    }, 3000);
  }
};

// ── Boot ──
document.addEventListener('DOMContentLoaded', () => app.init());
