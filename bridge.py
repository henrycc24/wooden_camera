"""
bridge.py — Flask server bridging the web UI to the Raspberry Pi Pico
over USB serial.

Endpoints:
  POST /api/grid       — send an 8×8 binary grid to the Pico
  GET  /api/status     — get serial connection status
  POST /api/connect    — connect to a serial port
  POST /api/disconnect — disconnect from serial
  GET  /api/camera/stream — stream MJPEG frames from the HM01B0

Serial Protocol:
  Send 9 bytes: [0xFF, row0, row1, ..., row7]
  Each row byte encodes 8 cells (MSB = col 0, LSB = col 7).
"""

import json
import sys
import glob
import struct
import logging
import threading
import time
import numpy as np
import cv2
from flask import Flask, request, jsonify, Response
from flask_cors import CORS

# Serial import with graceful fallback for testing
try:
    import serial
    import serial.tools.list_ports
    HAS_SERIAL = True
except ImportError:
    HAS_SERIAL = False

# ──────────────────────────────────────────
# Logging
# ──────────────────────────────────────────
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────
# Flask App
# ──────────────────────────────────────────
app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)

@app.route('/')
def serve_index():
    return app.send_static_file('index.html')

# Global serial connection
ser = None
serial_lock = threading.Lock()

# Global camera frame
latest_frame_jpg = None

def serial_reader_thread():
    global ser, latest_frame_jpg
    FRAME_WIDTH = 96
    FRAME_HEIGHT = 96
    FRAME_SIZE = FRAME_WIDTH * FRAME_HEIGHT
    HEADER = bytes([0x55, 0xAA])
    
    buf = b''
    while True:
        with serial_lock:
            current_ser = ser
            
        if current_ser is None or not current_ser.is_open:
            time.sleep(0.5)
            buf = b''
            continue
            
        try:
            with serial_lock:
                in_waiting = current_ser.in_waiting
                if in_waiting > 0:
                    data = current_ser.read(in_waiting)
                else:
                    data = b''
                    
            if data:
                buf += data
            else:
                time.sleep(0.01)
                continue
                
            idx = buf.find(HEADER)
            if idx >= 0:
                # discard anything before header
                buf = buf[idx:]
                if len(buf) >= len(HEADER) + FRAME_SIZE:
                    frame_data = buf[len(HEADER):len(HEADER) + FRAME_SIZE]
                    buf = buf[len(HEADER) + FRAME_SIZE:]
                    
                    img_array = np.frombuffer(frame_data, dtype=np.uint8).reshape((FRAME_HEIGHT, FRAME_WIDTH))
                    # Encode to JPEG
                    ret, jpeg = cv2.imencode('.jpg', img_array)
                    if ret:
                        latest_frame_jpg = jpeg.tobytes()
            else:
                # keep last few bytes in case it's a partial header
                if len(buf) > len(HEADER):
                    buf = buf[-len(HEADER):]
                    
        except Exception as e:
            time.sleep(0.5)

# Start reader thread
reader_thread = threading.Thread(target=serial_reader_thread, daemon=True)
reader_thread.start()


def grid_to_bytes(grid):
    if not isinstance(grid, list) or len(grid) != 8:
        raise ValueError("Grid must be a list of 8 rows")

    result = []
    for row_idx, row in enumerate(grid):
        if not isinstance(row, list) or len(row) != 8:
            raise ValueError(f"Row {row_idx} must be a list of 8 values")
        byte = 0
        for col_idx, val in enumerate(row):
            if val not in (0, 1):
                raise ValueError(f"Cell [{row_idx}][{col_idx}] must be 0 or 1, got {val}")
            if val:
                byte |= (1 << (7 - col_idx))
        result.append(byte)

    return result


def send_grid_serial(grid_bytes):
    global ser
    with serial_lock:
        if ser is None or not ser.is_open:
            raise RuntimeError("Serial port not connected")

        payload = bytes([0xFF] + grid_bytes)
        try:
            ser.write(payload)
            ser.flush()
        except serial.SerialTimeoutException:
            logger.warning("Serial write timeout (Pico RX buffer full). Is the Pico running the camera firmware without a serial reader?")
            return False
        except Exception as e:
            logger.error(f"Serial write error: {e}")
            raise
    logger.info(f"Sent {len(payload)} bytes: {[hex(b) for b in payload]}")
    return True


def detect_pico_port():
    if not HAS_SERIAL:
        return None

    ports = serial.tools.list_ports.comports()
    for port in ports:
        desc = (port.description or '').lower()
        mfg = (port.manufacturer or '').lower()
        if any(kw in desc for kw in ['pico', 'rp2040', 'usb serial']):
            return port.device
        if any(kw in mfg for kw in ['raspberry pi', 'micropython']):
            return port.device
    candidates = glob.glob('/dev/tty.usbmodem*')
    if candidates:
        return candidates[0]
    return None

# ──────────────────────────────────────────
# API Endpoints
# ──────────────────────────────────────────

@app.route('/api/camera/stream')
def camera_stream():
    def gen():
        while True:
            if latest_frame_jpg is not None:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + latest_frame_jpg + b'\r\n')
            time.sleep(0.05)
    return Response(gen(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/api/grid', methods=['POST'])
def post_grid():
    try:
        data = request.get_json(force=True)
    except Exception:
        return jsonify({"error": "Invalid JSON"}), 400

    grid = data.get('grid')
    if grid is None:
        return jsonify({"error": "Missing 'grid' field"}), 400

    try:
        grid_bytes = grid_to_bytes(grid)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    with serial_lock:
        is_connected = ser is not None and ser.is_open

    if is_connected:
        try:
            send_grid_serial(grid_bytes)
            return jsonify({
                "status": "sent",
                "bytes": [hex(b) for b in grid_bytes]
            })
        except Exception as e:
            return jsonify({"error": f"Serial write failed: {e}"}), 500
    else:
        logger.info(f"No serial connected. Grid bytes: {[hex(b) for b in grid_bytes]}")
        return jsonify({
            "status": "no_serial",
            "bytes": [hex(b) for b in grid_bytes],
            "message": "Grid encoded but serial not connected"
        })

@app.route('/api/status', methods=['GET'])
def get_status():
    with serial_lock:
        connected = ser is not None and ser.is_open
        port_name = ser.port if connected else None

    available = []
    if HAS_SERIAL:
        for p in serial.tools.list_ports.comports():
            available.append({
                "device": p.device,
                "description": p.description or "",
                "manufacturer": p.manufacturer or ""
            })

    return jsonify({
        "connected": connected,
        "port": port_name,
        "available_ports": available,
        "has_serial_lib": HAS_SERIAL
    })

@app.route('/api/connect', methods=['POST'])
def connect_serial():
    global ser

    if not HAS_SERIAL:
        return jsonify({"error": "pyserial not installed"}), 500

    data = request.get_json(force=True) if request.data else {}
    port = data.get('port')
    baud = data.get('baud', 115200)

    if not port:
        port = detect_pico_port()
        if not port:
            return jsonify({"error": "No port specified and auto-detect failed"}), 400

    with serial_lock:
        if ser is not None and ser.is_open:
            ser.close()

        try:
            ser = serial.Serial(port, baud, timeout=0.1, write_timeout=0.1)
            logger.info(f"Connected to {port} at {baud} baud")
            return jsonify({"status": "connected", "port": port, "baud": baud})
        except Exception as e:
            ser = None
            return jsonify({"error": f"Failed to connect: {e}"}), 500

@app.route('/api/disconnect', methods=['POST'])
def disconnect_serial():
    global ser
    with serial_lock:
        if ser is not None and ser.is_open:
            port_name = ser.port
            ser.close()
            ser = None
            logger.info(f"Disconnected from {port_name}")
            return jsonify({"status": "disconnected", "port": port_name})
        else:
            ser = None
            return jsonify({"status": "already_disconnected"})

@app.route('/api/ports', methods=['GET'])
def list_ports():
    if not HAS_SERIAL:
        return jsonify({"ports": [], "error": "pyserial not installed"})

    ports = []
    for p in serial.tools.list_ports.comports():
        ports.append({
            "device": p.device,
            "description": p.description or "",
            "manufacturer": p.manufacturer or ""
        })
    return jsonify({"ports": ports})

if __name__ == '__main__':
    port_num = 5123
    if len(sys.argv) > 1:
        try:
            port_num = int(sys.argv[1])
        except ValueError:
            pass

    logger.info(f"Starting bridge server on http://localhost:{port_num}")
    logger.info(f"pyserial available: {HAS_SERIAL}")

    detected = detect_pico_port()
    if detected:
        logger.info(f"Auto-detected Pico port: {detected}")
    else:
        logger.info("No Pico port auto-detected.")

    app.run(host='0.0.0.0', port=port_num, debug=False, threaded=True)
