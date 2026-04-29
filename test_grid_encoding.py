"""
test_grid_encoding.py — Unit tests for grid_to_bytes encoding logic.

Tests the conversion of 8×8 binary grids to byte arrays that are sent
over serial to the Raspberry Pi Pico controller.
"""

import sys
import os
import unittest

# Add server directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))
from bridge import grid_to_bytes


class TestGridToBytes(unittest.TestCase):
    """Test the grid_to_bytes function."""

    def test_all_zeros(self):
        """All-zero grid should produce 8 zero bytes."""
        grid = [[0]*8 for _ in range(8)]
        result = grid_to_bytes(grid)
        self.assertEqual(result, [0]*8)

    def test_all_ones(self):
        """All-one grid should produce 8 × 0xFF bytes."""
        grid = [[1]*8 for _ in range(8)]
        result = grid_to_bytes(grid)
        self.assertEqual(result, [0xFF]*8)

    def test_single_cell_top_left(self):
        """Single cell [0][0]=1 → byte 0 should be 0x80 (MSB set)."""
        grid = [[0]*8 for _ in range(8)]
        grid[0][0] = 1
        result = grid_to_bytes(grid)
        self.assertEqual(result[0], 0x80)
        for i in range(1, 8):
            self.assertEqual(result[i], 0)

    def test_single_cell_bottom_right(self):
        """Single cell [7][7]=1 → byte 7 should be 0x01 (LSB set)."""
        grid = [[0]*8 for _ in range(8)]
        grid[7][7] = 1
        result = grid_to_bytes(grid)
        for i in range(7):
            self.assertEqual(result[i], 0)
        self.assertEqual(result[7], 0x01)

    def test_checkerboard_even_rows(self):
        """Even rows: [1,0,1,0,1,0,1,0] → 0xAA (170)."""
        grid = [
            [1,0,1,0,1,0,1,0] if r % 2 == 0 else [0,1,0,1,0,1,0,1]
            for r in range(8)
        ]
        result = grid_to_bytes(grid)
        self.assertEqual(result[0], 0xAA)  # 10101010
        self.assertEqual(result[1], 0x55)  # 01010101
        self.assertEqual(result[2], 0xAA)
        self.assertEqual(result[3], 0x55)

    def test_first_half_cols(self):
        """Row with first 4 cols set: [1,1,1,1,0,0,0,0] → 0xF0."""
        grid = [[0]*8 for _ in range(8)]
        grid[0] = [1,1,1,1,0,0,0,0]
        result = grid_to_bytes(grid)
        self.assertEqual(result[0], 0xF0)

    def test_last_half_cols(self):
        """Row with last 4 cols set: [0,0,0,0,1,1,1,1] → 0x0F."""
        grid = [[0]*8 for _ in range(8)]
        grid[0] = [0,0,0,0,1,1,1,1]
        result = grid_to_bytes(grid)
        self.assertEqual(result[0], 0x0F)

    def test_custom_pattern(self):
        """Specific known pattern."""
        grid = [
            [1,0,0,1,1,0,1,0],  # 10011010 = 0x9A
            [0,1,1,0,0,1,0,1],  # 01100101 = 0x65
            [1,1,0,0,1,1,0,0],  # 11001100 = 0xCC
            [0,0,1,1,0,0,1,1],  # 00110011 = 0x33
            [1,0,1,0,1,0,1,0],  # 10101010 = 0xAA
            [0,1,0,1,0,1,0,1],  # 01010101 = 0x55
            [1,1,1,1,0,0,0,0],  # 11110000 = 0xF0
            [0,0,0,0,1,1,1,1],  # 00001111 = 0x0F
        ]
        expected = [0x9A, 0x65, 0xCC, 0x33, 0xAA, 0x55, 0xF0, 0x0F]
        result = grid_to_bytes(grid)
        self.assertEqual(result, expected)

    # ── Error cases ──

    def test_invalid_grid_wrong_rows(self):
        """Grid with wrong number of rows should raise ValueError."""
        grid = [[0]*8 for _ in range(7)]  # Only 7 rows
        with self.assertRaises(ValueError):
            grid_to_bytes(grid)

    def test_invalid_grid_wrong_cols(self):
        """Row with wrong number of columns should raise ValueError."""
        grid = [[0]*8 for _ in range(8)]
        grid[3] = [0]*7  # Only 7 cols in row 3
        with self.assertRaises(ValueError):
            grid_to_bytes(grid)

    def test_invalid_grid_bad_value(self):
        """Cell value outside {0,1} should raise ValueError."""
        grid = [[0]*8 for _ in range(8)]
        grid[2][3] = 2
        with self.assertRaises(ValueError):
            grid_to_bytes(grid)

    def test_invalid_grid_not_list(self):
        """Non-list input should raise ValueError."""
        with self.assertRaises(ValueError):
            grid_to_bytes("not a grid")

    def test_byte_range(self):
        """All output bytes should be in range [0, 255]."""
        grid = [[1]*8 for _ in range(8)]
        result = grid_to_bytes(grid)
        for b in result:
            self.assertGreaterEqual(b, 0)
            self.assertLessEqual(b, 255)


if __name__ == '__main__':
    unittest.main(verbosity=2)
