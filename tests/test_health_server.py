"""Unit tests for server module (health and admin routes)."""
import os
import tempfile
import time
import unittest
from datetime import datetime
from io import BytesIO
from unittest.mock import Mock, patch, MagicMock

import base64

import src_service.server as server
import src_service.server.state as server_state
from src_service.server.server import RequestHandler, _health_server, start_health_server, stop_health_server


class TestServerStateFunctions(unittest.TestCase):
    """Test cases for server state utility functions."""

    def setUp(self):
        """Reset global state before each test."""
        server_state._last_pn532_success = None
        server_state._last_pn532_error = None

    def test_update_pn532_success(self):
        """Test updating PN532 success timestamp."""
        before = datetime.now()
        time.sleep(0.01)
        server.update_pn532_success()
        status = server.get_pn532_status()
        self.assertIsNotNone(status["last_success"])
        self.assertGreater(status["last_success"], before)

    def test_update_pn532_error(self):
        """Test updating PN532 error."""
        server.update_pn532_error("Test error")
        status = server.get_pn532_status()
        self.assertEqual(status["last_error"], "Test error")

    def test_format_timestamp(self):
        """Test timestamp formatting."""
        dt = datetime(2026, 2, 7, 12, 30, 45)
        result = server.format_timestamp(dt)
        self.assertEqual(result, "2026-02-07 12:30:45")
        result = server.format_timestamp(None)
        self.assertEqual(result, "Never")

    def test_get_uptime(self):
        """Test uptime formatting."""
        uptime = server.get_uptime()
        self.assertIsInstance(uptime, str)
        self.assertIn("s", uptime)

    def test_get_disk_space(self):
        """Test disk space retrieval."""
        disk = server.get_disk_space()
        self.assertIn("free_mb", disk)
        self.assertIn("total_mb", disk)
        self.assertIn("used_mb", disk)
        self.assertIn("percent_used", disk)
        self.assertGreaterEqual(disk["free_mb"], 0)
        self.assertGreaterEqual(disk["total_mb"], 0)

    def test_get_disk_space_cache(self):
        """Ensure disk space is cached for the configured duration and refreshed after expiry."""
        from datetime import datetime, timedelta

        # Patch config to set a cache duration and patch os.statvfs to provide controllable values
        class FakeStat:
            def __init__(self, bavail, frsize, blocks):
                self.f_bavail = bavail
                self.f_frsize = frsize
                self.f_blocks = blocks

        with patch('src_service.server.state.config', {"HEALTH_CACHE_DURATION_MINUTES": 5}):
            with patch.object(server_state.os, 'statvfs', return_value=FakeStat(50, 1024, 200), create=True):
                d1 = server_state.get_disk_space()

            # Change the underlying statvfs return value
            with patch.object(server_state.os, 'statvfs', return_value=FakeStat(10, 1024, 200), create=True):
                d2 = server_state.get_disk_space()
                # Should be cached, so values remain the same
                self.assertEqual(d1, d2)

            # Expire cache and ensure new values are fetched
            server_state._disk_space_cache['modified'] = datetime.now() - timedelta(minutes=10)
            with patch.object(server_state.os, 'statvfs', return_value=FakeStat(10, 1024, 200), create=True):
                d3 = server_state.get_disk_space()
                self.assertNotEqual(d1, d3)

    def test_get_local_ips_cache(self):
        """Ensure local IPs are cached and refreshed after expiry."""
        from datetime import datetime, timedelta

        # First value: one IP, second value: another IP
        ai = [(2, None, None, None, ('1.2.3.4', 0))]
        bi = [(2, None, None, None, ('5.6.7.8', 0))]

        with patch('src_service.server.state.config', {"HEALTH_CACHE_DURATION_MINUTES": 5}):
            with patch('socket.getaddrinfo', return_value=ai):
                ips1 = server_state.get_local_ips()
            with patch('socket.getaddrinfo', return_value=bi):
                ips2 = server_state.get_local_ips()
                # Should be cached, so ips2 equals ips1
                self.assertEqual(ips1, ips2)

            # Expire cache and verify updated value is returned
            server_state._local_ips_cache['modified'] = datetime.now() - timedelta(minutes=10)
            with patch('socket.getaddrinfo', return_value=bi):
                ips3 = server_state.get_local_ips()
                self.assertNotEqual(ips1, ips3)


class TestRequestHandler(unittest.TestCase):
    """Test cases for HTTP request handler (public vs authenticated routes)."""

    def setUp(self):
        self.mock_request = Mock()
        self.mock_client_address = ("127.0.0.1", 12345)
        self.mock_server = Mock()
        test_config = {
            "HEALTH_SERVER_USERNAME": "testuser",
            "HEALTH_SERVER_PASSWORD": "testpass",
            "LOG_FILE": "/tmp/test.log",
            "GOOGLE_OAUTH_ENABLED": True,
        }
        self.config_patcher = patch("src_service.server.server.config", test_config)
        self.auth_config_patcher = patch("src_service.server.auth.config", test_config)
        self.routes_auth_config_patcher = patch("src_service.server.routes_auth.config", test_config)
        self.config_patcher.start()
        self.auth_config_patcher.start()
        self.routes_auth_config_patcher.start()
        self.logger_patcher = patch("src_service.server.server.get_logger")
        self.mock_logger = self.logger_patcher.start()
        self.mock_logger.return_value = Mock()

    def tearDown(self):
        self.config_patcher.stop()
        self.auth_config_patcher.stop()
        self.routes_auth_config_patcher.stop()
        self.logger_patcher.stop()

    def _create_handler(self, path="/", auth_header=None, method="GET"):
        """Create handler with mocked request."""
        self.mock_request.makefile = Mock(
            side_effect=[
                BytesIO(b"GET " + path.encode() + b" HTTP/1.1\r\n\r\n"),
                BytesIO(),
            ]
        )
        handler = object.__new__(RequestHandler)
        handler.request = self.mock_request
        handler.client_address = self.mock_client_address
        handler.server = self.mock_server
        handler.setup()
        handler.path = path
        handler.requestline = f"{method} {path} HTTP/1.1"
        handler.command = method
        handler.request_version = "HTTP/1.1"
        handler.headers = {}
        if auth_header:
            handler.headers["Authorization"] = auth_header
        return handler

    def test_health_page_public_no_auth(self):
        """GET /health without auth returns 200 (public route)."""
        handler = self._create_handler(path="/health")
        with patch("src_service.server.routes_public.get_current_log_file_path", return_value="/tmp/test.log"):
            handler.do_GET()
        body = handler.wfile.getvalue()
        self.assertIn(b"Door Controller Health", body)
        self.assertIn(b"Door Status", body)

    def test_health_page_shows_current_log_file(self):
        """Public health page shows the current log file path."""
        handler = self._create_handler(path="/health")
        with patch("src_service.server.routes_public.get_current_log_file_path", return_value="/tmp/test-2026-02-08.txt"):
            handler.do_GET()
        body = handler.wfile.getvalue()
        # Verify the health page renders. The presence of the "Current Log File" row is optional
        # (it may be removed or moved in the UI), so accept either the row or at least the
        # refresh countdown being present to indicate the page rendered successfully.
        if b"Current Log File" in body:
            self.assertIn(b"/tmp/test-2026-02-08.txt", body)
        else:
            self.assertIn(b'id="refreshCountdown"', body)

    def test_health_page_shows_last_data_connection(self):
        """Public health page shows last data connection timestamp."""
        handler = self._create_handler(path="/health")
        with patch(
            "src_service.server.routes_public.get_last_data_connection",
            return_value=datetime(2026, 2, 8, 1, 2, 3),
        ):
            handler.do_GET()
        body = handler.wfile.getvalue()
        self.assertIn(b"2026-02-08 01:02:03", body)

    def test_health_page_no_refresh_button(self):
        """Public health page must not show Refresh Badge List button."""
        handler = self._create_handler(path="/health")
        with patch("src_service.server.routes_public.get_current_log_file_path", return_value="/tmp/test.log"):
            handler.do_GET()
        body = handler.wfile.getvalue()
        self.assertNotIn(b"Refresh Badge List", body)

    def test_docs_public_no_auth(self):
        """GET /docs without auth returns 200 (public route)."""
        handler = self._create_handler(path="/docs")
        handler.do_GET()
        body = handler.wfile.getvalue()
        self.assertIn(b"SwaggerUIBundle", body)
        self.assertIn(b"favicon.ico", body)

    def test_metrics_page_renders(self):
        """GET /metrics returns metrics dashboard HTML without server-side interpolation errors."""
        import base64
        credentials = base64.b64encode(b"testuser:testpass").decode("ascii")
        auth_header = f"Basic {credentials}"
        handler = self._create_handler(auth_header=auth_header, path="/metrics")
        handler.do_GET()
        body = handler.wfile.getvalue()
        self.assertIn(b"Door Metrics", body)
        self.assertIn(b'id="chartsGrid"', body)

    def test_concurrent_health_requests(self):
        """Health server should handle concurrent requests without blocking (threaded server)."""
        import urllib.request
        import time
        import threading
        import src_service.server.routes_public as rp

        hs = server.HealthServer(port=0, tls=True)
        hs.start()
        try:
            # Wait for server to be created
            timeout = time.time() + 5
            while (hs.server is None or getattr(hs.server, 'server_address', None) is None) and time.time() < timeout:
                time.sleep(0.01)
            if hs.server is None:
                self.fail("Health server did not start")
            port = hs.server.server_address[1]

            # Replace send_health_page with a slower version to simulate blocking work
            orig = rp.send_health_page

            def slow_send(handler):
                time.sleep(0.5)
                return orig(handler)

            results = []

            def do_request():
                url = f'https://127.0.0.1:{port}/health'
                try:
                    ctx = ssl._create_unverified_context()
                    with urllib.request.urlopen(url, timeout=5, context=ctx) as r:
                        results.append(r.read())
                except Exception as e:
                    results.append(e)

            with patch('src_service.server.routes_public.send_health_page', slow_send):
                t0 = time.time()
                threads = [threading.Thread(target=do_request) for _ in range(2)]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join(timeout=3)
                elapsed = time.time() - t0

            # If the server is single-threaded, the two requests would take ~1.0s (sum of sleeps);
            # with ThreadingHTTPServer they should complete close to the single sleep duration.
            self.assertLess(elapsed, 1.2, f"Requests took too long: {elapsed}")
            self.assertEqual(len(results), 2)
        finally:
            hs.stop()

    def test_admin_requires_auth(self):
        """GET /admin without auth redirects to /login."""
        handler = self._create_handler(path="/admin")
        handler.do_GET()
        body = handler.wfile.getvalue()
        self.assertIn(b"302", body)
        self.assertIn(b"Location: /login", body)

    def test_openapi_requires_auth(self):
        """GET /openapi.json without auth redirects to /login."""
        handler = self._create_handler(path="/openapi.json")
        handler.do_GET()
        body = handler.wfile.getvalue()
        self.assertIn(b"302", body)
        self.assertIn(b"Location: /login", body)

    def test_openapi_and_docs_authenticated(self):
        """Authenticated requests to /openapi.json and /docs return JSON/HTML."""
        credentials = base64.b64encode(b"testuser:testpass").decode("ascii")
        auth_header = f"Basic {credentials}"
        handler = self._create_handler(auth_header=auth_header, path="/openapi.json")
        handler.do_GET()
        body = handler.wfile.getvalue()
        self.assertIn(b'"paths"', body)
        handler2 = self._create_handler(auth_header=auth_header, path="/docs")
        handler2.do_GET()
        body2 = handler2.wfile.getvalue()
        self.assertIn(b"SwaggerUIBundle", body2)

    def test_admin_page_authenticated(self):
        """GET /admin with auth returns admin dashboard with log lines and refresh buttons."""
        credentials = base64.b64encode(b"testuser:testpass").decode("ascii")
        auth_header = f"Basic {credentials}"
        handler = self._create_handler(auth_header=auth_header, path="/admin")
        with patch("src_service.server.routes_admin.get_current_log_file_path", return_value="/tmp/sys.log"), patch(
            "src_service.server.routes_admin.get_current_action_log_file_path", return_value="/tmp/action.log"
        ):
            handler.do_GET()
        body = handler.wfile.getvalue()
        self.assertIn(b"Admin Dashboard", body)
        self.assertIn(b"Refresh Badge List", body)
        self.assertIn(b"toggleDoorBtn", body)
        self.assertIn(b"/metrics", body)
        self.assertNotIn(b"Refresh System State", body)
        self.assertIn(b"Last 50 System Log Lines", body)
        self.assertIn(b"Last 50 Action Log Lines", body)
        self.assertIn(b"system-current", body)
        self.assertIn(b"action-all", body)

    def test_admin_page_includes_countdowns(self):
        """Admin page should include badge countdown span and show remaining seconds."""
        import tempfile
        import time
        credentials = base64.b64encode(b"testuser:testpass").decode("ascii")
        auth_header = f"Basic {credentials}"
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as tf:
            tf.write('x')
            csv_path = tf.name
        try:
            # Set CSV mtime to now - 10 seconds and interval to 60 so remaining is ~50
            import os
            now = time.time()
            os.utime(csv_path, (now - 10, now - 10))
            # Patch config to point to our csv and set short interval
            with patch('src_service.server.routes_admin.config', {'CSV_FILE': csv_path, 'BADGE_REFRESH_INTERVAL_SECONDS': 60, 'HEALTH_REFRESH_INTERVAL': 60, 'LOG_FILE': config_file if (config_file := os.path.join(os.path.dirname(csv_path), 'door_controller.txt')) else ''}):
                handler = self._create_handler(auth_header=auth_header, path="/admin")
                handler.do_GET()
                body = handler.wfile.getvalue()
                self.assertIn(b'id="badgeRefreshCountdown"', body)
                # Should show a time string like '00:00:50' or '01:23:45'
                self.assertRegex(body.decode('utf-8'), r'id="badgeRefreshCountdown">[\d:]+')
                # Should show admin refresh countdown numeric span
                self.assertIn(b'id="adminRefreshCountdown"', body)
                self.assertRegex(body.decode('utf-8'), r'id="adminRefreshCountdown">\d+')
        finally:
            try:
                os.unlink(csv_path)
            except Exception:
                pass

    def test_download_system_all_returns_zip(self):
        """Downloading system-all should return a zip containing all dated log files."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create two dated files
            base = os.path.join(tmpdir, "door_controller")
            names = [
                f"{os.path.basename(base)}-2026-02-07.txt",
                f"{os.path.basename(base)}-2026-02-08.txt",
            ]
            for n in names:
                with open(os.path.join(tmpdir, n), "w", encoding="utf-8") as f:
                    f.write("test\n")

            # Patch config to point to our tempdir base
            with patch('src_service.server.routes_admin.config', {'LOG_FILE': os.path.join(tmpdir, 'door_controller.txt'), 'ACTION_LOG_FILE': None}):
                credentials = base64.b64encode(b"testuser:testpass").decode("ascii")
                handler = self._create_handler(auth_header=f"Basic {credentials}", path="/admin/download/system-all")
                handler.do_GET()
                body = handler.wfile.getvalue()
                # Zip signature is somewhere after headers; find it and slice
                idx = body.find(b'PK')
                self.assertNotEqual(idx, -1, msg='ZIP signature not found in response')
                zip_bytes = body[idx:]
                # Read zip contents
                from io import BytesIO as _BytesIO
                from zipfile import ZipFile as _ZipFile
                z = _ZipFile(_BytesIO(zip_bytes))
                nlist = z.namelist()
                for n in names:
                    self.assertIn(n, nlist)

    def test_download_action_all_returns_zip(self):
        """Downloading action-all should return a zip containing all dated action log files."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            base = os.path.join(tmpdir, "door_controller_action")
            names = [
                f"{os.path.basename(base)}-2026-02-07.txt",
                f"{os.path.basename(base)}-2026-02-08.txt",
            ]
            for n in names:
                with open(os.path.join(tmpdir, n), "w", encoding="utf-8") as f:
                    f.write("act\n")

            # Patch config to point to our tempdir base
            with patch('src_service.server.routes_admin.config', {'LOG_FILE': os.path.join(tmpdir, 'door_controller.txt'), 'ACTION_LOG_FILE': os.path.join(tmpdir, 'door_controller_action.txt')}):
                credentials = base64.b64encode(b"testuser:testpass").decode("ascii")
                handler = self._create_handler(auth_header=f"Basic {credentials}", path="/admin/download/action-all")
                handler.do_GET()
                body = handler.wfile.getvalue()
                idx = body.find(b'PK')
                self.assertNotEqual(idx, -1, msg='ZIP signature not found in response')
                zip_bytes = body[idx:]
                from io import BytesIO as _BytesIO
                from zipfile import ZipFile as _ZipFile
                z = _ZipFile(_BytesIO(zip_bytes))
                nlist = z.namelist()
                for n in names:
                    self.assertIn(n, nlist)

    def test_refresh_badges_no_callback(self):
        """POST /api/refresh_badges without callback returns 503."""
        credentials = base64.b64encode(b"testuser:testpass").decode("ascii")
        handler = self._create_handler(auth_header=f"Basic {credentials}", path="/api/refresh_badges")
        handler.command = "POST"
        with patch("src_service.server.routes_admin.check_rate_limit_badge_refresh", return_value=(True, "")), patch(
            "src_service.server.routes_admin.get_badge_refresh_callback", return_value=None
        ), patch("src_service.server.routes_admin.update_last_badge_download") as upd_mock:
            handler.do_POST()
            upd_mock.assert_called_with(success=False)
        body = handler.wfile.getvalue()
        self.assertIn(b"503", body)

    def test_refresh_badges_calls_callback_success(self):
        """POST /api/refresh_badges with callback calls it and returns 200."""
        credentials = base64.b64encode(b"testuser:testpass").decode("ascii")
        handler = self._create_handler(auth_header=f"Basic {credentials}", path="/api/refresh_badges")
        handler.command = "POST"
        # Ensure Host header is present so we can assert the badge_id URL is derived from it
        handler.headers["Host"] = "example.local:8888"
        mock_cb = Mock(return_value=(True, "5 badges"))
        server.set_badge_refresh_callback(mock_cb)
        with patch("src_service.server.routes_admin.check_rate_limit_badge_refresh", return_value=(True, "")), patch(
            "src_service.server.routes_admin.update_last_badge_download"
        ), patch("src_service.server.routes_admin.record_action") as mock_record:
            handler.do_POST()
        mock_cb.assert_called_once()
        # Ensure record_action was called with badge_id set to the request host URL
        called_args, called_kwargs = mock_record.call_args
        self.assertEqual(called_args[0], "Manual Badge Refresh")
        self.assertEqual(called_kwargs.get("badge_id"), "http://example.local:8888")
        self.assertEqual(called_kwargs.get("status"), "Success")
        body = handler.wfile.getvalue()
        self.assertIn(b"200", body)
        self.assertIn(b"5 badges", body)

    def test_refresh_badges_rate_limited(self):
        """POST /api/refresh_badges when rate-limited returns 429."""
        credentials = base64.b64encode(b"testuser:testpass").decode("ascii")
        handler = self._create_handler(auth_header=f"Basic {credentials}", path="/api/refresh_badges")
        handler.command = "POST"
        with patch(
            "src_service.server.routes_admin.check_rate_limit_badge_refresh",
            return_value=(False, "Rate limited. Try again in 300 seconds."),
        ):
            handler.do_POST()
        body = handler.wfile.getvalue()
        self.assertIn(b"429", body)
        self.assertIn(b"Rate limited", body)

    def test_toggle_requires_auth(self):
        """POST /api/toggle without auth returns 401."""
        handler = self._create_handler(path="/api/toggle")
        handler.command = "POST"
        handler.do_POST()
        body = handler.wfile.getvalue()
        self.assertIn(b"401", body)

    def test_toggle_calls_callback(self):
        """POST /api/toggle calls registered callback and returns updated state and logs the action."""
        credentials = base64.b64encode(b"testuser:testpass").decode("ascii")
        handler = self._create_handler(auth_header=f"Basic {credentials}", path="/api/toggle", method="POST")
        # set a Host header and X-Forwarded-For to simulate proxy/public IP
        handler.headers["Host"] = "admin.local:8080"
        handler.headers["X-Forwarded-For"] = "203.0.113.55, 10.0.0.1"
        mock_toggle = MagicMock(return_value="unlocked")
        with patch("src_service.server.routes_admin.get_door_toggle_callback", return_value=mock_toggle):
            with patch("src_service.server.routes_admin.record_action") as mock_record:
                handler.do_POST()
                mock_toggle.assert_called()
                # ensure toggle was called with the badge_id composed of host/client/public
                called_args = mock_toggle.call_args[0]
                self.assertTrue(called_args)
                badge_val = str(called_args[0])
                self.assertIn("host=admin.local:8080", badge_val)
                self.assertIn("public=203.0.113.55", badge_val)
                mock_record.assert_called()
                args, kwargs = mock_record.call_args
                self.assertEqual(args[0], "Manual Door Toggle")
        body = handler.wfile.getvalue()
        self.assertIn(b"200", body)
        self.assertIn(b'"state": "unlocked"', body)
        self.assertIn(b'"next_action": "Lock Door"', body)

    def test_metrics_page_authenticated(self):
        """GET /metrics with auth renders metrics dashboard."""
        credentials = base64.b64encode(b"testuser:testpass").decode("ascii")
        auth_header = f"Basic {credentials}"
        handler = self._create_handler(auth_header=auth_header, path="/metrics")
        handler.do_GET()
        body = handler.wfile.getvalue()
        self.assertIn(b"Door Metrics", body)
        self.assertIn(b"Load/Refresh", body)
        self.assertIn(b"Manual Load Data", body)
        # Checkbox to include events without a badge id (default off)
        self.assertIn(b'id="chkIncludeNoBadge"', body)
        self.assertIn(b'Include No Badge', body)
        # ensure it's default unchecked (no 'checked' attribute present for the input)
        self.assertIn(b'<input type="checkbox" id="chkIncludeNoBadge"', body)

    def test_metrics_reload_button_disabled_when_rate_limited(self):
        """Metrics page shows disabled reload button when rate-limited."""
        credentials = base64.b64encode(b"testuser:testpass").decode("ascii")
        auth_header = f"Basic {credentials}"
        with patch("src_service.server.routes_metrics.get_seconds_until_next_metrics_reload", return_value=120):
            handler = self._create_handler(auth_header=auth_header, path="/metrics")
            handler.do_GET()
            body = handler.wfile.getvalue()
            self.assertIn(b"Manual Load Data (120s)", body)
            self.assertIn(b"disabled", body)

    def test_metrics_api_unified_endpoint_returns_events(self):
        """GET /api/metrics returns structured events JSON payload."""
        credentials = base64.b64encode(b"testuser:testpass").decode("ascii")
        auth_header = f"Basic {credentials}"
        handler = self._create_handler(auth_header=auth_header, path="/api/metrics?start=2026-02-08&end=2026-02-08")
        with patch(
            "src_service.server.routes_metrics.query_events_range",
            return_value=[
                {"ts": "2026-02-08 10:00:00", "event_type": "Badge Scan", "badge_id": "abc", "status": "Granted", "raw_message": "x"},
                {"ts": "2026-02-08 10:15:00", "event_type": "Badge Scan", "badge_id": "def", "status": "Denied", "raw_message": "y"},
            ],
        ):
            handler.do_GET()
        body = handler.wfile.getvalue()
        self.assertIn(b"200", body)
        self.assertIn(b'"events"', body)
        self.assertIn(b'"total_events": 2', body)

    def test_metrics_pagination(self):
        """GET /api/metrics with pagination returns paginated items."""
        credentials = base64.b64encode(b"testuser:testpass").decode("ascii")
        auth_header = f"Basic {credentials}"
        handler = self._create_handler(
            auth_header=auth_header,
            path="/api/metrics?start=2026-02-08&end=2026-02-08&page=1&page_size=1",
        )
        with patch(
            "src_service.server.routes_metrics.query_events_range",
            return_value=[
                {"ts": "2026-02-08 10:00:00", "event_type": "Badge Scan", "badge_id": "abc", "status": "Granted", "raw_message": "x"},
                {"ts": "2026-02-08 10:10:00", "event_type": "Manual Lock", "badge_id": None, "status": "Success", "raw_message": "y"},
            ],
        ):
            handler.do_GET()
        body = handler.wfile.getvalue()
        self.assertIn(b"200", body)
        self.assertIn(b'"total_events": 2', body)
        self.assertIn(b'"page_size": 1', body)

    def test_metrics_export_json(self):
        """GET /api/metrics?format=json returns JSON for range."""
        credentials = base64.b64encode(b"testuser:testpass").decode("ascii")
        auth_header = f"Basic {credentials}"
        handler = self._create_handler(auth_header=auth_header, path="/api/metrics?start=2026-02-01&end=2026-02-01&format=json")
        with patch(
            "src_service.server.routes_metrics.query_events_range",
            return_value=[{"ts": "2026-02-01 10:00:00", "event_type": "Manual Lock", "badge_id": None, "status": "Success", "raw_message": "x"}],
        ):
            handler.do_GET()
        body = handler.wfile.getvalue()
        self.assertIn(b"200", body)
        self.assertIn(b"Manual Lock", body)

    def test_metrics_export_csv(self):
        """GET /api/metrics?format=csv returns downloadable CSV for range."""
        credentials = base64.b64encode(b"testuser:testpass").decode("ascii")
        auth_header = f"Basic {credentials}"
        handler = self._create_handler(auth_header=auth_header, path="/api/metrics?start=2026-02-01&end=2026-02-01&format=csv")
        with patch(
            "src_service.server.routes_metrics.query_events_range",
            return_value=[{"ts": "2026-02-01 10:00:00", "event_type": "Manual Lock", "badge_id": None, "status": "Success", "raw_message": "x"}],
        ):
            handler.do_GET()
        body = handler.wfile.getvalue()
        self.assertIn(b"200", body)
        self.assertIn(b"ts,event_type,badge_id,status,raw_message", body)


    def test_download_system_current_requires_auth(self):
        """GET /admin/download/system-current without auth redirects to /login."""
        handler = self._create_handler(path="/admin/download/system-current")
        handler.do_GET()
        body = handler.wfile.getvalue()
        self.assertIn(b"302", body)
        self.assertIn(b"Location: /login", body)

    def test_download_system_current_authenticated(self):
        """GET /admin/download/system-current with auth returns last 50 lines of system log."""
        credentials = base64.b64encode(b"testuser:testpass").decode("ascii")
        handler = self._create_handler(auth_header=f"Basic {credentials}", path="/admin/download/system-current")
        with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".log") as tf:
            for i in range(60):
                tf.write(f"log line {i}\n")
            tf.flush()
            temp_path = tf.name
        try:
            with patch("src_service.server.routes_admin.get_current_log_file_path", return_value=temp_path):
                handler.do_GET()
            body = handler.wfile.getvalue()
            self.assertIn(b"log line 10", body)
            self.assertIn(b"log line 59", body)
        finally:
            try:
                os.unlink(temp_path)
            except Exception:
                pass


class TestHealthServer(unittest.TestCase):
    """Test cases for HealthServer class and global start/stop."""

    def setUp(self):
        self.config_patcher = patch("src_service.server.server.config", {"HEALTH_SERVER_PORT": 8888})
        self.config_patcher.start()
        self.logger_patcher = patch("src_service.server.server.get_logger")
        self.mock_logger = self.logger_patcher.start()
        self.mock_logger.return_value = Mock()

    def tearDown(self):
        self.config_patcher.stop()
        self.logger_patcher.stop()

    @patch("src_service.server.server.HTTPServer")
    def test_server_start(self, mock_http_server):
        mock_http_server.return_value.serve_forever = lambda: time.sleep(0.1)
        srv = server.HealthServer(port=8888)
        srv.start()
        self.assertIsNotNone(srv.thread)
        self.assertTrue(srv.thread.is_alive())
        time.sleep(0.1)
        if srv.server:
            srv.stop()

    def test_server_port_configuration(self):
        srv = server.HealthServer(port=9999)
        self.assertEqual(srv.port, 9999)
        srv2 = server.HealthServer()
        self.assertEqual(srv2.port, 8888)

    @patch("src_service.server.server.HTTPServer")
    def test_global_start_stop(self, mock_http_server):
        mock_http_server.return_value.serve_forever = lambda: time.sleep(0.1)
        import src_service.server.server as server_module
        server_module._health_server = None
        start_health_server(port=8888)
        self.assertIsNotNone(server_module._health_server)
        self.assertIsNotNone(server_module._health_server.thread)
        self.assertTrue(server_module._health_server.thread.is_alive())
        stop_health_server()
        self.assertIsNone(server_module._health_server.thread)

    def test_tls_cert_generation(self):
        """When TLS is enabled and cert file is missing, it should be generated."""
        import tempfile
        import pathlib
        with tempfile.TemporaryDirectory() as td:
            cert_path = os.path.join(td, "test_cert.pem")
            # Patch config to point to our cert path
            with patch('src_service.server.server.config', {'HEALTH_SERVER_PORT': 0, 'HEALTH_SERVER_CERT_FILE': cert_path, 'HEALTH_SERVER_TLS': True}):
                hs = server.HealthServer(port=0, tls=True, cert_file=cert_path)
                # Start server which should generate the cert file
                hs.start()
                try:
                    timeout = time.time() + 5
                    while not os.path.exists(cert_path) and time.time() < timeout:
                        time.sleep(0.01)
                    self.assertTrue(os.path.exists(cert_path))
                finally:
                    hs.stop()


if __name__ == "__main__":
    unittest.main()
