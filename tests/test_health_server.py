"""Unit tests for health server module."""
import unittest
from unittest.mock import Mock, patch, MagicMock
import base64
import time
from io import BytesIO
from datetime import datetime
import lib.health_server as health_server


class TestHealthServerFunctions(unittest.TestCase):
    """Test cases for health server utility functions."""

    def setUp(self):
        """Reset global state before each test."""
        health_server._last_pn532_success = None
        health_server._last_pn532_error = None

    def test_update_pn532_success(self):
        """Test updating PN532 success timestamp."""
        before = datetime.now()
        time.sleep(0.01)
        health_server.update_pn532_success()

        status = health_server.get_pn532_status()
        self.assertIsNotNone(status['last_success'])
        self.assertGreater(status['last_success'], before)

    def test_update_pn532_error(self):
        """Test updating PN532 error."""
        health_server.update_pn532_error("Test error")

        status = health_server.get_pn532_status()
        self.assertEqual(status['last_error'], "Test error")

    def test_format_timestamp(self):
        """Test timestamp formatting."""
        dt = datetime(2026, 2, 7, 12, 30, 45)
        result = health_server.format_timestamp(dt)
        self.assertEqual(result, "2026-02-07 12:30:45")

        result = health_server.format_timestamp(None)
        self.assertEqual(result, "Never")

    def test_get_uptime(self):
        """Test uptime formatting."""
        # Uptime should be very recent
        uptime = health_server.get_uptime()
        self.assertIsInstance(uptime, str)
        self.assertIn("s", uptime)

    def test_get_disk_space(self):
        """Test disk space retrieval."""
        disk = health_server.get_disk_space()

        self.assertIn('free_mb', disk)
        self.assertIn('total_mb', disk)
        self.assertIn('used_mb', disk)
        self.assertIn('percent_used', disk)

        self.assertGreaterEqual(disk['free_mb'], 0)
        self.assertGreaterEqual(disk['total_mb'], 0)


class TestHealthCheckHandler(unittest.TestCase):
    """Test cases for HTTP request handler."""

    def setUp(self):
        """Set up test fixtures."""
        # Create mock request
        self.mock_request = Mock()
        self.mock_client_address = ('127.0.0.1', 12345)
        self.mock_server = Mock()

        # Patch config
        self.config_patcher = patch('lib.health_server.config', {
            "HEALTH_SERVER_USERNAME": "testuser",
            "HEALTH_SERVER_PASSWORD": "testpass",
            "LOG_FILE": "/tmp/test.log"
        })
        self.config_patcher.start()

        # Patch logger
        self.logger_patcher = patch('lib.health_server.get_logger')
        self.mock_logger = self.logger_patcher.start()
        self.mock_logger.return_value = Mock()

    def tearDown(self):
        """Clean up patches."""
        self.config_patcher.stop()
        self.logger_patcher.stop()

    def _create_handler(self, path='/', auth_header=None):
        """Helper to create handler with mocked request."""
        # Mock the request socket
        self.mock_request.makefile = Mock(side_effect=[
            BytesIO(b'GET ' + path.encode() + b' HTTP/1.1\r\n\r\n'),
            BytesIO()
        ])

        # Instantiate handler without invoking automatic handling flow.
        handler = object.__new__(health_server.HealthCheckHandler)
        handler.request = self.mock_request
        handler.client_address = self.mock_client_address
        handler.server = self.mock_server
        # Initialize rfile/wfile via setup (will wrap wfile for tests)
        handler.setup()

        # Set path and requestline so methods and logging work as expected
        handler.path = path
        handler.requestline = f'GET {path} HTTP/1.1'
        handler.command = 'GET'
        handler.request_version = 'HTTP/1.1'

        # Mock headers
        handler.headers = {}
        if auth_header:
            handler.headers['Authorization'] = auth_header

        return handler

    def test_check_auth_success(self):
        """Test successful authentication."""
        credentials = base64.b64encode(b'testuser:testpass').decode('ascii')
        auth_header = f'Basic {credentials}'

        handler = self._create_handler(auth_header=auth_header)
        self.assertTrue(handler.check_auth())

    def test_check_auth_failure_wrong_password(self):
        """Test authentication failure with wrong password."""
        credentials = base64.b64encode(b'testuser:wrongpass').decode('ascii')
        auth_header = f'Basic {credentials}'

        handler = self._create_handler(auth_header=auth_header)
        self.assertFalse(handler.check_auth())

    def test_check_auth_failure_no_header(self):
        """Test authentication failure without auth header."""
        handler = self._create_handler()
        self.assertFalse(handler.check_auth())

    def test_check_auth_failure_invalid_format(self):
        """Test authentication failure with invalid format."""
        handler = self._create_handler(auth_header='Invalid format')
        self.assertFalse(handler.check_auth())

    def test_refresh_badges_no_callback(self):
        """Requesting badge refresh without callback should result in a 503 and mark download as failed."""
        credentials = base64.b64encode(b'testuser:testpass').decode('ascii')
        auth_header = f'Basic {credentials}'

        handler = self._create_handler(auth_header=auth_header)
        handler.path = '/api/refresh_badges'

        with patch('lib.health_server.update_last_badge_download') as upd_mock:
            # Ensure no callback is registered
            health_server._badge_refresh_fn = None
            handler.do_POST()
            upd_mock.assert_called_with(success=False)

    def test_refresh_badges_calls_callback_success(self):
        """A successful badge refresh should call the registered callback and update timestamps."""
        credentials = base64.b64encode(b'testuser:testpass').decode('ascii')
        auth_header = f'Basic {credentials}'

        handler = self._create_handler(auth_header=auth_header)
        handler.path = '/api/refresh_badges'

        mock_cb = Mock(return_value=(True, '5 badges'))
        health_server.set_badge_refresh_callback(mock_cb)

        with patch('lib.health_server.update_last_badge_download') as upd_mock, patch('lib.health_server.record_action') as rec_mock:
            handler.do_POST()
            mock_cb.assert_called_once()
            upd_mock.assert_called_with(success=True)
            rec_mock.assert_called()

    def test_openapi_and_docs_authenticated(self):
        """Authenticated requests to /openapi.json and /docs should succeed and return JSON/HTML respectively."""
        credentials = base64.b64encode(b'testuser:testpass').decode('ascii')
        auth_header = f'Basic {credentials}'

        # Test OpenAPI JSON
        handler = self._create_handler(auth_header=auth_header, path='/openapi.json')
        handler.do_GET()
        body = handler.wfile.getvalue()
        self.assertIn(b'"paths"', body)

        # Test Docs HTML
        handler2 = self._create_handler(auth_header=auth_header, path='/docs')
        handler2.do_GET()
        body2 = handler2.wfile.getvalue()
        self.assertIn(b'SwaggerUIBundle', body2)
        # FavIcon should be present like health page
        self.assertIn(b'favicon.ico', body2)

    def test_health_page_shows_current_log_file(self):
        """Health page should show the current log file path."""
        credentials = base64.b64encode(b'testuser:testpass').decode('ascii')
        auth_header = f'Basic {credentials}'

        handler = self._create_handler(auth_header=auth_header, path='/health')
        # Patch the log file path function
        with patch('lib.health_server.get_current_log_file_path', return_value='/tmp/test-2026-02-08.txt'):
            handler.do_GET()
            body = handler.wfile.getvalue()
            self.assertIn(b'/tmp/test-2026-02-08.txt', body)

    def test_health_page_shows_last_data_connection(self):
        """Health page should show the last data connection timestamp."""
        credentials = base64.b64encode(b'testuser:testpass').decode('ascii')
        auth_header = f'Basic {credentials}'

        handler = self._create_handler(auth_header=auth_header, path='/health')
        with patch('lib.health_server.get_last_data_connection', return_value=datetime(2026, 2, 8, 1, 2, 3)):
            handler.do_GET()
            body = handler.wfile.getvalue()
            self.assertIn(b'2026-02-08 01:02:03', body)

    def test_health_page_shows_last_50_lines(self):
        """Health page should display the most recent 50 log lines."""
        credentials = base64.b64encode(b'testuser:testpass').decode('ascii')
        auth_header = f'Basic {credentials}'

        # Create a temp log file with 100 lines
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w+', delete=False) as tf:
            for i in range(100):
                tf.write(f"line {i}\n")
            tf.flush()
            temp_path = tf.name

        handler = self._create_handler(auth_header=auth_header, path='/health')
        # Patch the log file path function to return our temp file
        with patch('lib.health_server.get_current_log_file_path', return_value=temp_path):
            handler.do_GET()
            body = handler.wfile.getvalue()

            # Last 50 lines should include 'line 50' and 'line 99' but not 'line 49'
            self.assertIn(b'line 50', body)
            self.assertIn(b'line 99', body)
            self.assertNotIn(b'line 49', body)

        try:
            import os
            os.unlink(temp_path)
        except Exception:
            pass



class TestHealthServer(unittest.TestCase):
    """Test cases for HealthServer class."""

    def setUp(self):
        """Set up test fixtures."""
        # Patch config
        self.config_patcher = patch('lib.health_server.config', {
            "HEALTH_SERVER_PORT": 8888
        })
        self.config_patcher.start()

        # Patch logger
        self.logger_patcher = patch('lib.health_server.get_logger')
        self.mock_logger = self.logger_patcher.start()
        self.mock_logger.return_value = Mock()

    def tearDown(self):
        """Clean up patches."""
        self.config_patcher.stop()
        self.logger_patcher.stop()

    @patch('lib.health_server.HTTPServer')
    def test_server_start(self, mock_http_server):
        """Test starting the health server."""
        # Make the mocked server block briefly so the thread stays alive during the check
        mock_http_server.return_value.serve_forever = lambda: time.sleep(0.1)

        server = health_server.HealthServer(port=8888)
        server.start()

        # Check thread was created
        self.assertIsNotNone(server.thread)
        self.assertTrue(server.thread.is_alive())

        # Give thread time to start
        time.sleep(0.1)

        # Clean up
        if server.server:
            server.stop()

    def test_server_port_configuration(self):
        """Test server port configuration."""
        server = health_server.HealthServer(port=9999)
        self.assertEqual(server.port, 9999)

        server2 = health_server.HealthServer()
        self.assertEqual(server2.port, 8888)  # From mocked config

    @patch('lib.health_server.HTTPServer')
    def test_global_start_stop(self, mock_http_server):
        """Test starting and stopping the global health server via helpers."""
        # Make the mocked server block briefly so the thread stays alive during the check
        mock_http_server.return_value.serve_forever = lambda: time.sleep(0.1)

        # Ensure global is reset
        health_server._health_server = None

        # Start global server
        health_server.start_health_server(port=8888)
        self.assertIsNotNone(health_server._health_server)
        self.assertIsNotNone(health_server._health_server.thread)
        self.assertTrue(health_server._health_server.thread.is_alive())

        # Stop global server
        health_server.stop_health_server()
        # After stop, thread should be None
        self.assertIsNone(health_server._health_server.thread)


if __name__ == '__main__':
    unittest.main()
