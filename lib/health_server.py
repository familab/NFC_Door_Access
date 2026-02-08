"""Lightweight HTTP health check server with Basic Auth (stdlib only)."""
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import base64
import os
import time
from datetime import datetime, timedelta
from typing import Optional, List
import socket
import json

from .config import config, __version__
from .logging_utils import (
    logger,
    get_logger,
    get_last_google_log_success,
    get_last_badge_download,
    get_last_google_error,
    get_log_file_size,
    get_current_log_file_path,
    update_last_badge_download,
    record_action
)
from .door_control import get_door_status, get_door_status_updated
from .openapi import get_openapi_spec

# Common content types
TEXT_HTML = 'text/html'
APPLICATION_JSON = 'application/json'

# Global state for health monitoring
_app_start_time = datetime.now()
_last_pn532_success = None
_last_pn532_error = None

# Badge refresh callback (set by start.py)
_badge_refresh_fn = None

# Thread-safe lock for PN532 state
_pn532_lock = threading.Lock()


def update_pn532_success():
    """Update the timestamp of the last successful PN532 read."""
    global _last_pn532_success
    with _pn532_lock:
        _last_pn532_success = datetime.now()


def update_pn532_error(error: str):
    """
    Update the last PN532 error.

    Args:
        error: Error message
    """
    global _last_pn532_error
    with _pn532_lock:
        _last_pn532_error = error


def get_pn532_status():
    """Get PN532 status information."""
    with _pn532_lock:
        return {
            'last_success': _last_pn532_success,
            'last_error': _last_pn532_error
        }


def set_badge_refresh_callback(fn):
    """Register a callback for manual badge refresh.

    The callback should return either a boolean (success) or a tuple (success, info).
    """
    global _badge_refresh_fn
    _badge_refresh_fn = fn


def format_timestamp(dt: Optional[datetime]) -> str:
    """Format a datetime object for display."""
    if dt is None:
        return "Never"
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def get_local_ips() -> List[str]:
    """Return a list of local IPv4 addresses, excluding 127.* and 172.* addresses.

    Uses both getaddrinfo(hostname) and the UDP connect-to-public trick to discover
    candidate interfaces. Falls back gracefully on platforms without all APIs.
    """
    ips = set()

    try:
        hostname = socket.gethostname()
        for res in socket.getaddrinfo(hostname, None):
            family = res[0]
            sockaddr = res[4]
            if family == socket.AF_INET:
                ip = sockaddr[0]
                if not (ip.startswith('127.') or ip.startswith('172.')):
                    ips.add(ip)
    except Exception:
        # Ignore failures here and try other methods
        pass

    # Use a UDP socket to determine primary outbound IP (non-blocking)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        if not (ip.startswith('127.') or ip.startswith('172.')):
            ips.add(ip)
    except Exception:
        pass

    return sorted(ips)


def get_uptime() -> str:
    """Get application uptime as a formatted string."""
    uptime = datetime.now() - _app_start_time
    days = uptime.days
    hours, remainder = divmod(uptime.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")

    return " ".join(parts)


def get_disk_space() -> dict:
    """Get disk space information."""
    try:
        stat = os.statvfs('/')
        free_bytes = stat.f_bavail * stat.f_frsize
        total_bytes = stat.f_blocks * stat.f_frsize
        used_bytes = total_bytes - free_bytes

        return {
            'free_mb': free_bytes / (1024 * 1024),
            'total_mb': total_bytes / (1024 * 1024),
            'used_mb': used_bytes / (1024 * 1024),
            'percent_used': (used_bytes / total_bytes) * 100 if total_bytes > 0 else 0
        }
    except Exception as e:
        get_logger().warning(f"Failed to get disk space: {e}")
        return {
            'free_mb': 0,
            'total_mb': 0,
            'used_mb': 0,
            'percent_used': 0
        }


class HealthCheckHandler(BaseHTTPRequestHandler):
    """HTTP request handler for health check endpoint."""

    def setup(self):
        """Wrap wfile in BytesIO for test environments (mocked request)."""
        # Call base setup to initialize rfile/wfile
        super().setup()
        # If the request is not a real socket (unit tests use Mock), swap wfile
        try:
            if not isinstance(self.request, socket.socket):
                from io import BytesIO
                if not hasattr(self.wfile, 'getvalue'):
                    # Preserve original writer if needed
                    self._original_wfile = self.wfile
                    self.wfile = BytesIO()
        except Exception:
            # Best-effort only; don't fail in production
            pass

    def do_GET(self):
        """Handle GET requests."""
        try:
            get_logger().info(f"Health server request: {self.command} {self.path} from {self.client_address}")
        except Exception:
            pass
        # Check Basic Auth
        if not self.check_auth():
            self.send_auth_required()
            return

        # Serve health page
        if self.path == '/' or self.path == '/health':
            self.send_health_page()
            return

        # Serve OpenAPI JSON (Swagger) and documentation page
        if self.path == '/openapi.json':
            try:
                # Log request headers and host for debugging (helps when breakpoints aren't hit)
                host_header = self.headers.get('Host')
                get_logger().debug(f"OpenAPI request headers: {dict(self.headers)}")
                get_logger().debug(f"OpenAPI request Host header: {host_header!r}")

                spec = get_openapi_spec(host=host_header)

                # Log resolved server URL from spec for troubleshooting
                server_url = spec.get('servers', [{}])[0].get('url')
                get_logger().debug(f"OpenAPI generated server URL: {server_url}")

                self.send_response(200)
                self.send_header('Content-type', APPLICATION_JSON)
                self.end_headers()
                self.wfile.write(json.dumps(spec).encode('utf-8'))
                return
            except Exception as e:
                get_logger().error(f"Failed to generate OpenAPI spec: {e}")
                self.send_error(500, f"Failed to generate OpenAPI spec: {e}")
                return

        if self.path == '/docs':
            # Simple Swagger UI page using CDN
            try:
                self.send_response(200)
                self.send_header('Content-type', TEXT_HTML)
                self.end_headers()
                html = """<!DOCTYPE html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>Door Controller API Docs</title>
    <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@4/swagger-ui.css" />
  </head>
  <body>
    <div id="swagger-ui"></div>
    <script src="https://unpkg.com/swagger-ui-dist@4/swagger-ui-bundle.js"></script>
    <script>
      window.onload = function() {
        const ui = SwaggerUIBundle({
          url: '/openapi.json',
          dom_id: '#swagger-ui',
          presets: [SwaggerUIBundle.presets.apis],
          layout: 'BaseLayout'
        });
      };
    </script>
  </body>
</html>"""
                self.wfile.write(html.encode('utf-8'))
                return
            except Exception as e:
                self.send_error(500, f"Failed to render docs: {e}")
                return

        self.send_error(404, "Not Found")

    def check_auth(self) -> bool:
        """
        Check HTTP Basic Authentication.

        Returns:
            True if authenticated, False otherwise
        """
        auth_header = self.headers.get('Authorization')
        if not auth_header:
            try:
                get_logger().warning("Health server auth failed: missing Authorization header")
            except Exception:
                pass
            return False

        try:
            # Parse "Basic <base64>" format
            auth_type, auth_data = auth_header.split(' ', 1)
            if auth_type.lower() != 'basic':
                return False

            # Decode base64
            decoded = base64.b64decode(auth_data).decode('utf-8')
            username, password = decoded.split(':', 1)

            # Check credentials
            expected_username = config["HEALTH_SERVER_USERNAME"]
            expected_password = config["HEALTH_SERVER_PASSWORD"]

            return username == expected_username and password == expected_password

        except Exception as e:
            get_logger().warning(f"Auth check failed: {e}")
            return False

    def send_auth_required(self):
        """Send 401 Unauthorized response."""
        self.send_response(401)
        self.send_header('WWW-Authenticate', 'Basic realm="Door Controller"')
        self.send_header('Content-type', TEXT_HTML)
        self.end_headers()
        self.wfile.write(b'<html><body><h1>401 Unauthorized</h1></body></html>')

    def do_POST(self):
        """Handle POST requests (used for badge refresh)."""
        try:
            get_logger().info(f"Health server request: {self.command} {self.path} from {self.client_address}")
        except Exception:
            pass
        # Check Basic Auth
        if not self.check_auth():
            self.send_auth_required()
            return

        if self.path == '/api/refresh_badges':
            # Trigger badge refresh callback if available; always return JSON
            if _badge_refresh_fn is None:
                get_logger().warning("Badge refresh requested but no callback is registered")
                try:
                    update_last_badge_download(success=False)
                except Exception:
                    pass

                self.send_response(503)
                self.send_header('Content-type', APPLICATION_JSON)
                self.end_headers()
                payload = json.dumps({'success': False, 'message': 'Badge refresh not available'})
                self.wfile.write(payload.encode('utf-8'))
                return

            try:
                result = _badge_refresh_fn()
                # Allow callbacks that return (bool, info) or just bool
                if isinstance(result, tuple):
                    success = bool(result[0])
                    info = str(result[1]) if len(result) > 1 else ''
                else:
                    success = bool(result)
                    info = ''

                update_last_badge_download(success=success)
                record_action('Manual Badge Refresh', status='Success' if success else 'Failure')

                status_code = 200 if success else 500
                self.send_response(status_code)
                self.send_header('Content-type', APPLICATION_JSON)
                self.end_headers()
                payload = json.dumps({'success': success, 'message': info})
                self.wfile.write(payload.encode('utf-8'))
                return

            except Exception as e:
                get_logger().error(f"Badge refresh failed: {e}")
                try:
                    update_last_badge_download(success=False)
                except Exception:
                    pass

                self.send_response(500)
                self.send_header('Content-type', APPLICATION_JSON)
                self.end_headers()
                payload = json.dumps({'success': False, 'message': str(e)})
                self.wfile.write(payload.encode('utf-8'))
                return

        self.send_error(404, "Not Found")

    def send_health_page(self):
        """Generate and send health check page."""
        # Gather health data
        door_status = "OPEN/UNLOCKED" if get_door_status() else "CLOSED/LOCKED"
        door_updated = format_timestamp(get_door_status_updated())

        last_google_log = format_timestamp(get_last_google_log_success())
        last_badge_dl = format_timestamp(get_last_badge_download())
        google_error = get_last_google_error() or "None"

        pn532_status = get_pn532_status()
        pn532_success = format_timestamp(pn532_status['last_success'])
        pn532_error = pn532_status['last_error'] or "None"

        uptime = get_uptime()
        log_size_bytes = get_log_file_size()
        log_size_mb = log_size_bytes / (1024 * 1024)

        disk = get_disk_space()

        # Current log file path (dated file name)
        try:
            current_log_file = get_current_log_file_path()
        except Exception:
            current_log_file = config.get("LOG_FILE", "")

        # Last log entry: read up to the last 50 lines from the current log file
        last_log_entry = "N/A"
        try:
            with open(current_log_file, 'r') as f:
                lines = f.readlines()
                if lines:
                    tail_lines = lines[-50:]
                    # Strip trailing newlines and join with newlines preserved for display
                    last_log_entry = "\n".join(l.rstrip('\n') for l in tail_lines)
        except Exception:
            pass

        # Build HTML
        refresh_interval = int(config.get("HEALTH_REFRESH_INTERVAL", 0) or 0)
        meta_refresh = f'<meta http-equiv="refresh" content="{refresh_interval}">' if refresh_interval > 0 else ''
        refresh_display = f"{refresh_interval}s" if refresh_interval > 0 else "Off"
        if refresh_interval > 0:
            refresh_html = f'Auto-refresh: {refresh_display} &nbsp; Next refresh in <span id="refreshCountdown">{refresh_interval}</span>s'
        else:
            refresh_html = 'Auto-refresh: Off'

        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Door Controller Health</title>
    {meta_refresh}
    <link rel="icon" href="https://images.squarespace-cdn.com/content/v1/65fbda49f5eb7e7df1ae5f87/1711004274233-C9RL74H38DXHYWBDMLSS/favicon.ico?format=100w">
    <style>
        body {{ font-family: monospace; margin: 20px; background: #1e1e1e; color: #d4d4d4; }}
        h1 {{ color: #4ec9b0; }}
        table {{ border-collapse: collapse; width: 100%; max-width: 800px; }}
        th, td {{ border: 1px solid #555; padding: 10px; text-align: left; }}
        th {{ background: #2d2d30; color: #4ec9b0; }}
        tr:nth-child(even) {{ background: #252526; }}
        .status-ok {{ color: #4ec9b0; font-weight: bold; }}
        .status-warning {{ color: #dcdcaa; font-weight: bold; }}
        .status-error {{ color: #f48771; font-weight: bold; }}
        .timestamp {{ color: #9cdcfe; }}
        .toast {{ position: fixed; right: 20px; bottom: 20px; background: #333; color: #fff; padding: 10px 14px; border-radius: 6px; box-shadow: 0 2px 8px rgba(0,0,0,0.5); display: none; z-index: 9999; }}
        .toast.success {{ background: #4ec9b0; color: #1e1e1e; }}
        .toast.error {{ background: #f48771; }}
    </style>
</head>
<body>
    <h1>Door Controller Health Status</h1>
    <p class="timestamp">Version: {__version__}</p>
    <p class="timestamp">Generated: {format_timestamp(datetime.now())}</p>
    <p class="timestamp">{refresh_html} &nbsp; <button id="refreshBtn" style="background:#4ec9b0;color:#1e1e1e;padding:6px;border:none;border-radius:4px;cursor:pointer;">Refresh Badge List</button></p>
    <div id="toast" class="toast"></div>
    <p class="timestamp">Machine: {socket.gethostname()}</p>
    <p class="timestamp">Local IPs: {', '.join(get_local_ips()) or 'None'}</p>
    <table>
        <tr>
            <th>Metric</th>
            <th>Value</th>
        </tr>
        <tr>
            <td>Door Status</td>
            <td class="{'status-warning' if get_door_status() else 'status-ok'}">{door_status}</td>
        </tr>
        <tr>
            <td>Door Status Updated</td>
            <td>{door_updated}</td>
        </tr>
        <tr>
            <td>Application Uptime</td>
            <td class="status-ok">{uptime}</td>
        </tr>
        <tr>
            <td>Last Google Sheets Log</td>
            <td>{last_google_log}</td>
        </tr>
        <tr>
            <td>Last Badge Download</td>
            <td>{last_badge_dl}</td>
        </tr>
        <tr>
            <td>Google Sheets Last Error</td>
            <td class="{'status-ok' if google_error == 'None' else 'status-error'}">{google_error}</td>
        </tr>
        <tr>
            <td>PN532 Last Success</td>
            <td>{pn532_success}</td>
        </tr>
        <tr>
            <td>PN532 Last Error</td>
            <td class="{'status-ok' if pn532_error == 'None' else 'status-error'}">{pn532_error}</td>
        </tr>
        <tr>
            <td>Log File Size</td>
            <td>{log_size_mb:.2f} MB</td>
        </tr>
        <tr>
            <td>Current Log File</td>
            <td style="font-size:0.9em; word-break:break-all;">{current_log_file}</td>
        </tr>
        <tr>
            <td>Disk Free Space</td>
            <td>{disk['free_mb']:.2f} MB / {disk['total_mb']:.2f} MB ({disk['percent_used']:.1f}% used)</td>
        </tr>
        <tr>
            <td>Last 50 Log Entries</td>
            <td style="font-size: 0.9em; word-break: break-all;">
                <pre style="white-space: pre-wrap; max-height: 240px; overflow: auto; margin:0;">{last_log_entry}</pre>
            </td>
        </tr>
    </table>
    <script>
    (function() {{
        const interval = {refresh_interval};
        if (interval > 0) {{
            let countdown = interval;
            const el = document.getElementById('refreshCountdown');
            if (el) el.textContent = countdown;
            setInterval(function() {{
                countdown -= 1;
                if (el) el.textContent = countdown;
                if (countdown <= 0) {{
                    location.reload();
                }}
            }}, 1000);
        }}

        // Badge refresh button - uses AJAX and shows toast notifications
        const refreshBtn = document.getElementById('refreshBtn');
        const toastEl = document.getElementById('toast');

        function showToast(message, kind='success', timeout=4000) {{
            if (!toastEl) return;
            toastEl.textContent = message;
            toastEl.className = 'toast ' + (kind === 'success' ? 'success' : 'error');
            toastEl.style.display = 'block';
            setTimeout(function() {{ toastEl.style.display = 'none'; }}, timeout);
        }}

        async function doRefresh() {{
            if (!refreshBtn) return;
            const original = refreshBtn.textContent;
            refreshBtn.disabled = true;
            refreshBtn.textContent = 'Refreshing...';

            try {{
                const resp = await fetch('/api/refresh_badges', {{ method: 'POST', headers: {{ 'X-Requested-With': 'XMLHttpRequest' }}, redirect: 'manual' }});

                // Prefer JSON response
                const ct = resp.headers.get('Content-Type') || '';
                if (ct.includes('application/json')) {{
                    const j = await resp.json();
                    if (resp.ok) {{
                        showToast(j.message || 'Badge list refreshed', 'success');
                    }} else {{
                        showToast(j.message || 'Badge refresh failed', 'error');
                    }}
                }} else if (resp.status >= 200 && resp.status < 400) {{
                    showToast('Badge list refreshed', 'success');
                }} else {{
                    const txt = await resp.text();
                    showToast(txt || ('Error: ' + resp.status), 'error');
                }}
            }} catch (e) {{
                showToast('Network error: ' + e.message, 'error');
            }} finally {{
                if (refreshBtn) {{ refreshBtn.disabled = false; refreshBtn.textContent = original; }}
            }}
        }}

        if (refreshBtn) {{
            refreshBtn.addEventListener('click', function (e) {{
                e.preventDefault();
                doRefresh();
            }});
        }}
    }})();
    </script>
</body>
</html>"""

        # Send response
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))

    def log_message(self, format, *args):
        """Override to use our logger instead of stderr."""
        get_logger().info(f"Health server: {format % args}")


class HealthServer:
    """Health check HTTP server manager."""

    def __init__(self, port: Optional[int] = None):
        """
        Initialize the health server.

        Args:
            port: Port to listen on. If None, uses config default.
        """
        self.port = port or config["HEALTH_SERVER_PORT"]
        self.server = None
        self.thread = None
        self.running = False
        self.logger = get_logger()

    def start(self):
        """Start the health server in a background daemon thread."""
        if self.running:
            self.logger.warning("Health server already running")
            return

        self.running = True

        def run_server():
            try:
                self.server = HTTPServer(('0.0.0.0', self.port), HealthCheckHandler)
                self.logger.info(f"Health server started on port {self.port}")
                self.server.serve_forever()
            except Exception as e:
                self.logger.error(f"Health server error: {e}")
            finally:
                self.running = False

        self.thread = threading.Thread(target=run_server, daemon=True)
        self.thread.start()
        self.logger.info("Health server thread started")

    def stop(self):
        """Stop the health server gracefully."""
        if not self.running:
            return

        self.logger.info("Stopping health server")
        self.running = False

        if self.server:
            try:
                self.server.shutdown()
                self.server.server_close()
            except Exception as e:
                self.logger.warning(f"Error shutting down server: {e}")

        # Join the serving thread to ensure clean shutdown
        if self.thread:
            try:
                self.thread.join(timeout=3)
            except Exception as e:
                self.logger.warning(f"Health server thread did not exit cleanly: {e}")

        self.server = None
        self.thread = None
        self.logger.info("Health server stopped")


# Global health server instance
_health_server = None


def start_health_server(port: Optional[int] = None):
    """
    Start the global health server instance.

    Args:
        port: Port to listen on (overrides config if provided)
    """
    global _health_server

    if _health_server is None:
        _health_server = HealthServer(port=port)

    _health_server.start()


def stop_health_server():
    """Stop the global health server instance."""
    global _health_server

    if _health_server:
        _health_server.stop()
