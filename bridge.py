"""
bridge.py — Flask server bridging the web UI to the Raspberry Pi Pico
over USB serial.

Endpoints:
  POST /api/grid      — send an 8×8 binary grid to the Pico
  GET  /api/status     — get serial connection status
  POST /api/connect    — connect to a serial port
  POST /api/disconnect — disconnect from serial

Serial Protocol:
  Send 9 bytes: [0xFF, row0, row1, ..., row7]
  Each row byte encodes 8 cells (MSB = col 0, LSB = col 7).
"""

import json
import sys
import glob
import struct
import logging
from flask import Flask, request, jsonify
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
app = Flask(__name__)
CORS(app)

# Global serial connection
ser = None


def grid_to_bytes(grid):
    """
    Convert an 8×8 binary grid (list of lists) to 8 bytes.
    Each byte encodes one row: MSB = col 0, LSB = col 7.

    Args:
        grid: list of 8 lists, each containing 8 ints (0 or 1)

    Returns:
        list of 8 ints (0–255)

    Raises:
        ValueError: if grid is not 8×8 or contains non-binary values
    """
    if not isinstance(grid, list) or len(grid) != 8:
        raise ValueError("Grid must be a list of 8 rows")

    result = []
    for row_idx, row in enumerate(grid):
        if not isinstance(row, list) or len(row) != 8:
            raise ValueError(f"Row {row_idx} must be a list of 8 values")
        byte = 0
        for col_idx, val in enumerate(row):
            if val not in (0, 1):
                raise ValueError(
                    f"Cell [{row_idx}][{col_idx}] must be 0 or 1, got {val}")
            if val:
                byte |= (1 << (7 - col_idx))
        result.append(byte)

    return result


def send_grid_serial(grid_bytes):
    """
    Send grid bytes over serial with start marker 0xFF.
    Total: 9 bytes = [0xFF] + 8 row bytes.

    Args:
        grid_bytes: list of 8 ints (0–255)

    Returns:
        True on success

    Raises:
        RuntimeError: if serial is not connected
    """
    global ser
    if ser is None or not ser.is_open:
        raise RuntimeError("Serial port not connected")

    payload = bytes([0xFF] + grid_bytes)
    ser.write(payload)
    ser.flush()
    logger.info(f"Sent {len(payload)} bytes: {[hex(b) for b in payload]}")
    return True


def detect_pico_port():
    """Auto-detect likely Pico serial port."""
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
    # Fallback: look for common macOS patterns
    candidates = glob.glob('/dev/tty.usbmodem*')
    if candidates:
        return candidates[0]
    return None


# ──────────────────────────────────────────
# API Endpoints
# ──────────────────────────────────────────

@app.route('/api/grid', methods=['POST'])
def post_grid():
    """Receive an 8×8 grid and send it to the Pico."""
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

    # If serial is connected, send
    if ser is not None and ser.is_open:
        try:
            send_grid_serial(grid_bytes)
            return jsonify({
                "status": "sent",
                "bytes": [hex(b) for b in grid_bytes]
            })
        except Exception as e:
            return jsonify({"error": f"Serial write failed: {e}"}), 500
    else:
        # No serial connected — just log and return the encoded bytes
        logger.info(f"No serial connected. Grid bytes: "
                    f"{[hex(b) for b in grid_bytes]}")
        return jsonify({
            "status": "no_serial",
            "bytes": [hex(b) for b in grid_bytes],
            "message": "Grid encoded but serial not connected"
        })


@app.route('/api/status', methods=['GET'])
def get_status():
    """Return serial connection status."""
    connected = ser is not None and ser.is_open
    port_name = ser.port if connected else None

    # List available ports
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
    """Connect to a serial port."""
    global ser

    if not HAS_SERIAL:
        return jsonify({"error": "pyserial not installed"}), 500

    data = request.get_json(force=True) if request.data else {}
    port = data.get('port')
    baud = data.get('baud', 115200)

    # Auto-detect if no port specified
    if not port:
        port = detect_pico_port()
        if not port:
            return jsonify({
                "error": "No port specified and auto-detect failed"
            }), 400

    # Close existing connection
    if ser is not None and ser.is_open:
        ser.close()

    try:
        ser = serial.Serial(port, baud, timeout=1)
        logger.info(f"Connected to {port} at {baud} baud")
        return jsonify({"status": "connected", "port": port, "baud": baud})
    except Exception as e:
        ser = None
        return jsonify({"error": f"Failed to connect: {e}"}), 500


@app.route('/api/disconnect', methods=['POST'])
def disconnect_serial():
    """Disconnect from serial port."""
    global ser
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
    """List available serial ports."""
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


# ──────────────────────────────────────────
# Main
# ──────────────────────────────────────────

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
        logger.info("No Pico port auto-detected. "
                     "Use POST /api/connect to connect manually.")

    app.run(host='0.0.0.0', port=port_num, debug=False)
