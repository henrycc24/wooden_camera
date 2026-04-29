"""
test_pipeline_e2e.py — End-to-end verification that a grid in the UI
produces the correct I2C signals from the controller to the workers.

Traces the full data path:
  UI grid (8×8) → grid_to_bytes (8 bytes) → serial frame (0xFF + 8 bytes)
  → controller decodes → I2C dispatch to workers → worker sets servos

This test simulates the controller's C logic in Python to verify
the I2C commands that would be sent to each worker.
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))
from bridge import grid_to_bytes


# ──────────────────────────────────────────────────────────
# Simulate the controller's C logic in Python
# ──────────────────────────────────────────────────────────

WORKER_ADDRS = [0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17]
SERVOS_PER_WORKER = 8


def simulate_controller(serial_frame):
    """
    Simulate what controller.c does when it receives a serial frame.

    Args:
        serial_frame: bytes object — [0xFF, row0, row1, ..., row7]

    Returns:
        list of I2C transactions, each being:
          {"worker_addr": int, "commands": [(servo_index, state), ...]}
    """
    assert serial_frame[0] == 0xFF, "Frame must start with 0xFF"
    assert len(serial_frame) == 9, "Frame must be 9 bytes"

    row_bytes = serial_frame[1:]
    i2c_transactions = []

    for row in range(8):
        # controller.c: updateGrid → setServosOn(row, indices, states, 8)
        # This sends to workerAddrs[row]
        commands = []
        for col in range(8):
            state = (row_bytes[row] >> (7 - col)) & 1
            commands.append((col, state))

        i2c_transactions.append({
            "worker_addr": WORKER_ADDRS[row],
            "commands": commands
        })

    return i2c_transactions


def simulate_worker_servos(i2c_commands):
    """
    Simulate what worker.c does when it receives I2C commands.

    Args:
        i2c_commands: list of (servo_index, state) tuples

    Returns:
        dict mapping servo_index → angle (0 or 180)
    """
    servos = {}
    for index, state in i2c_commands:
        # worker.c: servos[index].write(state ? 180 : 0)
        servos[index] = 180 if state else 0
    return servos


class TestFullPipeline(unittest.TestCase):
    """Verify UI grid → I2C signals → servo angles for known patterns."""

    def _run_pipeline(self, grid):
        """Run the full pipeline for a grid and return servo states per worker."""
        # Step 1: UI encodes grid to bytes (what app.js / bridge.py does)
        grid_bytes = grid_to_bytes(grid)

        # Step 2: Bridge wraps with start byte (what bridge.py sends over serial)
        serial_frame = bytes([0xFF] + grid_bytes)

        # Step 3: Controller decodes and dispatches I2C
        i2c_txns = simulate_controller(serial_frame)

        # Step 4: Each worker sets servos
        worker_servos = {}
        for txn in i2c_txns:
            servos = simulate_worker_servos(txn["commands"])
            worker_servos[txn["worker_addr"]] = servos

        return worker_servos

    # ── Test: All white (all 0s) → all servos at 0° ──

    def test_all_white_grid(self):
        """All-white grid → every servo on every worker at 0°."""
        grid = [[0]*8 for _ in range(8)]
        result = self._run_pipeline(grid)

        for addr in WORKER_ADDRS:
            for servo in range(8):
                self.assertEqual(result[addr][servo], 0,
                    f"Worker {hex(addr)} servo {servo} should be 0° (white)")

    # ── Test: All black (all 1s) → all servos at 180° ──

    def test_all_black_grid(self):
        """All-black grid → every servo on every worker at 180°."""
        grid = [[1]*8 for _ in range(8)]
        result = self._run_pipeline(grid)

        for addr in WORKER_ADDRS:
            for servo in range(8):
                self.assertEqual(result[addr][servo], 180,
                    f"Worker {hex(addr)} servo {servo} should be 180° (black)")

    # ── Test: Single black cell at [2][5] ──

    def test_single_cell(self):
        """Single black cell at row 2, col 5 → only worker 0x12, servo 5 at 180°."""
        grid = [[0]*8 for _ in range(8)]
        grid[2][5] = 1

        result = self._run_pipeline(grid)

        # Worker 0x12 (row 2), servo 5 should be 180°
        self.assertEqual(result[0x12][5], 180,
            "Worker 0x12 servo 5 should be 180° (black cell)")

        # All other servos on worker 0x12 should be 0°
        for s in range(8):
            if s != 5:
                self.assertEqual(result[0x12][s], 0,
                    f"Worker 0x12 servo {s} should be 0°")

        # All servos on other workers should be 0°
        for addr in WORKER_ADDRS:
            if addr != 0x12:
                for s in range(8):
                    self.assertEqual(result[addr][s], 0,
                        f"Worker {hex(addr)} servo {s} should be 0°")

    # ── Test: Checkerboard pattern ──

    def test_checkerboard(self):
        """Checkerboard → alternating 180°/0° on each worker."""
        grid = [
            [1,0,1,0,1,0,1,0] if r % 2 == 0 else [0,1,0,1,0,1,0,1]
            for r in range(8)
        ]
        result = self._run_pipeline(grid)

        for row in range(8):
            addr = WORKER_ADDRS[row]
            for col in range(8):
                expected_angle = 180 if (row + col) % 2 == 0 else 0
                self.assertEqual(result[addr][col], expected_angle,
                    f"Worker {hex(addr)} servo {col}: expected {expected_angle}°")

    # ── Test: Top half black, bottom half white ──

    def test_top_half_black(self):
        """Top 4 rows black, bottom 4 rows white."""
        grid = [[1]*8 for _ in range(4)] + [[0]*8 for _ in range(4)]
        result = self._run_pipeline(grid)

        # Workers 0x10–0x13 (rows 0–3): all 180°
        for addr in WORKER_ADDRS[:4]:
            for s in range(8):
                self.assertEqual(result[addr][s], 180,
                    f"Worker {hex(addr)} servo {s} should be 180°")

        # Workers 0x14–0x17 (rows 4–7): all 0°
        for addr in WORKER_ADDRS[4:]:
            for s in range(8):
                self.assertEqual(result[addr][s], 0,
                    f"Worker {hex(addr)} servo {s} should be 0°")

    # ── Test: Left half black, right half white ──

    def test_left_half_black(self):
        """Left 4 cols black, right 4 cols white on every row."""
        grid = [[1,1,1,1,0,0,0,0] for _ in range(8)]
        result = self._run_pipeline(grid)

        for addr in WORKER_ADDRS:
            for col in range(4):
                self.assertEqual(result[addr][col], 180,
                    f"Worker {hex(addr)} servo {col} should be 180° (left half)")
            for col in range(4, 8):
                self.assertEqual(result[addr][col], 0,
                    f"Worker {hex(addr)} servo {col} should be 0° (right half)")

    # ── Test: Diagonal ──

    def test_diagonal(self):
        """Diagonal line: cell [i][i] = 1 for i in 0..7."""
        grid = [[0]*8 for _ in range(8)]
        for i in range(8):
            grid[i][i] = 1

        result = self._run_pipeline(grid)

        for row in range(8):
            addr = WORKER_ADDRS[row]
            for col in range(8):
                expected = 180 if row == col else 0
                self.assertEqual(result[addr][col], expected,
                    f"Worker {hex(addr)} servo {col}: expected {expected}°")

    # ── Test: Worker address mapping ──

    def test_worker_address_mapping(self):
        """Verify row 0 → worker 0x10, row 1 → worker 0x11, etc."""
        # Set a unique pattern per row to verify mapping
        grid = [[0]*8 for _ in range(8)]
        for row in range(8):
            grid[row][row] = 1  # Only column=row is black in each row

        result = self._run_pipeline(grid)

        for row in range(8):
            addr = WORKER_ADDRS[row]
            # Only servo[row] should be 180°
            self.assertEqual(result[addr][row], 180,
                f"Worker {hex(addr)} servo {row} should be 180°")
            # All others should be 0
            for col in range(8):
                if col != row:
                    self.assertEqual(result[addr][col], 0,
                        f"Worker {hex(addr)} servo {col} should be 0°")

    # ── Test: Serial frame integrity ──

    def test_serial_frame_format(self):
        """Verify serial frame has correct format: 0xFF + 8 row bytes."""
        grid = [
            [1,0,0,1,1,0,1,0],  # 0x9A
            [0,1,1,0,0,1,0,1],  # 0x65
            [1,1,0,0,1,1,0,0],  # 0xCC
            [0,0,1,1,0,0,1,1],  # 0x33
            [1,0,1,0,1,0,1,0],  # 0xAA
            [0,1,0,1,0,1,0,1],  # 0x55
            [1,1,1,1,0,0,0,0],  # 0xF0
            [0,0,0,0,1,1,1,1],  # 0x0F
        ]

        grid_bytes = grid_to_bytes(grid)
        frame = bytes([0xFF] + grid_bytes)

        self.assertEqual(len(frame), 9)
        self.assertEqual(frame[0], 0xFF)
        self.assertEqual(frame[1], 0x9A)
        self.assertEqual(frame[2], 0x65)
        self.assertEqual(frame[3], 0xCC)
        self.assertEqual(frame[4], 0x33)
        self.assertEqual(frame[5], 0xAA)
        self.assertEqual(frame[6], 0x55)
        self.assertEqual(frame[7], 0xF0)
        self.assertEqual(frame[8], 0x0F)

    # ── Test: Verify I2C wire protocol ──

    def test_i2c_wire_bytes(self):
        """Verify the exact bytes sent over I2C match worker.c expectations.

        worker.c onReceive reads pairs: (index, state).
        controller.c setServosOn writes: index0, state0, index1, state1, ...
        """
        grid = [[0]*8 for _ in range(8)]
        grid[3][6] = 1  # Row 3, col 6 → worker 0x13, servo 6, state 1

        grid_bytes = grid_to_bytes(grid)
        frame = bytes([0xFF] + grid_bytes)
        i2c_txns = simulate_controller(frame)

        # Find the transaction for worker 0x13 (row 3)
        txn = i2c_txns[3]
        self.assertEqual(txn["worker_addr"], 0x13)

        # The I2C payload should contain 8 pairs:
        # (0,0), (1,0), (2,0), (3,0), (4,0), (5,0), (6,1), (7,0)
        expected_commands = [(i, 0) for i in range(8)]
        expected_commands[6] = (6, 1)
        self.assertEqual(txn["commands"], expected_commands)


if __name__ == '__main__':
    unittest.main(verbosity=2)
