"""Main HTTP server and request handler. Dispatches to public and admin routes."""
import base64
import json
import socket
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional

from ..config import config
from ..logging_utils import get_logger
from ..openapi import get_openapi_spec

from .state import APPLICATION_JSON, TEXT_HTML
from . import routes_public
from . import routes_admin


# Paths that do not require authentication
PUBLIC_PATHS = {"/", "/health", "/docs"}


def _check_auth(handler: BaseHTTPRequestHandler) -> bool:
    """Check HTTP Basic Auth. Returns True if authenticated."""
    auth_header = handler.headers.get("Authorization")
    if not auth_header:
        try:
            get_logger().warning("Health server auth failed: missing Authorization header")
        except Exception:
            pass
        return False
    try:
        auth_type, auth_data = auth_header.split(" ", 1)
        if auth_type.lower() != "basic":
            return False
        decoded = base64.b64decode(auth_data).decode("utf-8")
        username, password = decoded.split(":", 1)
        return (
            username == config["HEALTH_SERVER_USERNAME"]
            and password == config["HEALTH_SERVER_PASSWORD"]
        )
    except Exception as e:
        get_logger().warning(f"Auth check failed: {e}")
        return False


def _send_auth_required(handler: BaseHTTPRequestHandler):
    """Send 401 Unauthorized."""
    handler.send_response(401)
    handler.send_header("WWW-Authenticate", 'Basic realm="Door Controller"')
    handler.send_header("Content-type", TEXT_HTML)
    handler.end_headers()
    handler.wfile.write(b"<html><body><h1>401 Unauthorized</h1></body></html>")


def _send_openapi_json(handler: BaseHTTPRequestHandler):
    """Send OpenAPI spec JSON (authenticated route)."""
    try:
        host_header = handler.headers.get("Host")
        get_logger().debug(f"OpenAPI request Host header: {host_header!r}")
        spec = get_openapi_spec(host=host_header)
        handler.send_response(200)
        handler.send_header("Content-type", APPLICATION_JSON)
        handler.end_headers()
        handler.wfile.write(json.dumps(spec).encode("utf-8"))
    except Exception as e:
        get_logger().error(f"Failed to generate OpenAPI spec: {e}")
        handler.send_error(500, f"Failed to generate OpenAPI spec: {e}")


class RequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler: public routes without auth, all others with Basic Auth."""

    def setup(self):
        super().setup()
        try:
            if not isinstance(self.request, socket.socket):
                from io import BytesIO
                if not hasattr(self.wfile, "getvalue"):
                    self._original_wfile = self.wfile
                    self.wfile = BytesIO()
        except Exception:
            pass

    def _require_auth(self) -> bool:
        """Return True if request is allowed (either public path or authenticated)."""
        path = self.path.split("?")[0]
        if path in PUBLIC_PATHS:
            return True
        if _check_auth(self):
            return True
        _send_auth_required(self)
        return False

    def do_GET(self):
        try:
            get_logger().info(
                f"Health server request: {self.command} {self.path} from {self.client_address}"
            )
        except Exception:
            pass

        path = self.path.split("?")[0]

        if path in ("/", "/health"):
            routes_public.send_health_page(self)
            return

        if path == "/docs":
            routes_public.send_docs_page(self)
            return

        if not self._require_auth():
            return

        if path == "/openapi.json":
            _send_openapi_json(self)
            return

        if path == "/admin":
            routes_admin.send_admin_page(self)
            return

        if path.startswith("/admin/download/"):
            if routes_admin.handle_download(self, path):
                return
            self.send_error(404, "Not Found")
            return

        self.send_error(404, "Not Found")

    def do_POST(self):
        try:
            get_logger().info(
                f"Health server request: {self.command} {self.path} from {self.client_address}"
            )
        except Exception:
            pass

        path = self.path.split("?")[0]

        if path == "/api/refresh_badges":
            if not self._require_auth():
                return
            if routes_admin.handle_post_refresh_badges(self):
                return

        self.send_error(404, "Not Found")

    def log_message(self, format, *args):
        get_logger().info(f"Health server: {format % args}")


class HealthServer:
    """HTTP server manager (same API as before for start.py compatibility)."""

    def __init__(self, port: Optional[int] = None):
        self.port = port or config["HEALTH_SERVER_PORT"]
        self.server = None
        self.thread = None
        self.running = False
        self.logger = get_logger()

    def start(self):
        if self.running:
            self.logger.warning("Health server already running")
            return
        self.running = True

        def run_server():
            try:
                self.server = HTTPServer(("0.0.0.0", self.port), RequestHandler)
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
        if self.thread:
            try:
                self.thread.join(timeout=3)
            except Exception as e:
                self.logger.warning(f"Health server thread did not exit cleanly: {e}")
        self.server = None
        self.thread = None
        self.logger.info("Health server stopped")


_health_server: Optional[HealthServer] = None


def start_health_server(port: Optional[int] = None):
    """Start the global health server instance."""
    global _health_server
    if _health_server is None:
        _health_server = HealthServer(port=port)
    _health_server.start()


def stop_health_server():
    """Stop the global health server instance."""
    global _health_server
    if _health_server:
        _health_server.stop()
