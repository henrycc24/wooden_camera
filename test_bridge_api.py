"""
test_bridge_api.py — Integration tests for the Flask bridge API.

Tests the HTTP endpoints with a mock serial connection to verify
request handling, validation, and response formatting.
"""

import sys
import os
import json
import unittest
from unittest.mock import MagicMock, patch

# Add server directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))

import bridge
from bridge import app, grid_to_bytes


class TestBridgeAPI(unittest.TestCase):
    """Test the Flask API endpoints."""

    def setUp(self):
        """Create test client and reset serial state."""
        self.app = app
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        # Reset global serial connection
        bridge.ser = None

    def tearDown(self):
        """Ensure serial is cleaned up."""
        bridge.ser = None

    # ── POST /api/grid ──

    def test_grid_valid_no_serial(self):
        """Valid grid with no serial → returns encoded bytes with no_serial status."""
        grid = [[0]*8 for _ in range(8)]
        grid[0][0] = 1  # MSB of row 0

        resp = self.client.post('/api/grid',
                                data=json.dumps({"grid": grid}),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data['status'], 'no_serial')
        self.assertIn('bytes', data)
        self.assertEqual(data['bytes'][0], '0x80')

    def test_grid_valid_with_mock_serial(self):
        """Valid grid with mock serial → bytes are sent."""
        mock_ser = MagicMock()
        mock_ser.is_open = True
        bridge.ser = mock_ser

        grid = [[1]*8 for _ in range(8)]  # All black

        resp = self.client.post('/api/grid',
                                data=json.dumps({"grid": grid}),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data['status'], 'sent')

        # Verify serial.write was called with 9 bytes (start + 8 rows)
        mock_ser.write.assert_called_once()
        payload = mock_ser.write.call_args[0][0]
        self.assertEqual(len(payload), 9)
        self.assertEqual(payload[0], 0xFF)  # Start byte
        for i in range(1, 9):
            self.assertEqual(payload[i], 0xFF)  # All 1s

    def test_grid_missing_field(self):
        """POST without 'grid' field → 400 error."""
        resp = self.client.post('/api/grid',
                                data=json.dumps({"data": []}),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertIn('error', data)
        self.assertIn("Missing 'grid'", data['error'])

    def test_grid_invalid_json(self):
        """POST with invalid JSON → 400 error."""
        resp = self.client.post('/api/grid',
                                data='not json at all{{{',
                                content_type='application/json')
        # Flask may return 400 or 415 depending on version
        self.assertIn(resp.status_code, [400, 415])

    def test_grid_wrong_dimensions(self):
        """Grid with wrong dimensions → 400 error."""
        grid = [[0]*8 for _ in range(7)]  # 7 rows instead of 8
        resp = self.client.post('/api/grid',
                                data=json.dumps({"grid": grid}),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertIn('error', data)

    def test_grid_invalid_values(self):
        """Grid with non-binary values → 400 error."""
        grid = [[0]*8 for _ in range(8)]
        grid[0][0] = 5
        resp = self.client.post('/api/grid',
                                data=json.dumps({"grid": grid}),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 400)

    def test_grid_serial_write_fail(self):
        """Serial write failure → 500 error."""
        mock_ser = MagicMock()
        mock_ser.is_open = True
        mock_ser.write.side_effect = Exception("USB disconnected")
        bridge.ser = mock_ser

        grid = [[0]*8 for _ in range(8)]
        resp = self.client.post('/api/grid',
                                data=json.dumps({"grid": grid}),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 500)

    def test_grid_checkerboard_encoding(self):
        """Checkerboard pattern encodes correctly."""
        grid = [
            [1,0,1,0,1,0,1,0] if r % 2 == 0 else [0,1,0,1,0,1,0,1]
            for r in range(8)
        ]
        resp = self.client.post('/api/grid',
                                data=json.dumps({"grid": grid}),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data['bytes'][0], '0xaa')
        self.assertEqual(data['bytes'][1], '0x55')

    # ── GET /api/status ──

    def test_status_disconnected(self):
        """Status when not connected."""
        resp = self.client.get('/api/status')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertFalse(data['connected'])
        self.assertIsNone(data['port'])

    def test_status_connected(self):
        """Status when connected with mock serial."""
        mock_ser = MagicMock()
        mock_ser.is_open = True
        mock_ser.port = '/dev/tty.test'
        bridge.ser = mock_ser

        resp = self.client.get('/api/status')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data['connected'])
        self.assertEqual(data['port'], '/dev/tty.test')

    # ── POST /api/disconnect ──

    def test_disconnect_when_connected(self):
        """Disconnect when serial is open."""
        mock_ser = MagicMock()
        mock_ser.is_open = True
        mock_ser.port = '/dev/tty.test'
        bridge.ser = mock_ser

        resp = self.client.post('/api/disconnect')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data['status'], 'disconnected')
        mock_ser.close.assert_called_once()

    def test_disconnect_when_not_connected(self):
        """Disconnect when already disconnected."""
        resp = self.client.post('/api/disconnect')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data['status'], 'already_disconnected')

    # ── GET /api/ports ──

    def test_list_ports(self):
        """List ports endpoint returns a list."""
        resp = self.client.get('/api/ports')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn('ports', data)
        self.assertIsInstance(data['ports'], list)


if __name__ == '__main__':
    unittest.main(verbosity=2)
