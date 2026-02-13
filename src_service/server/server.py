"""Main HTTP server and request handler. Dispatches to public and admin routes."""
import json
import socket
import threading
import os
import ssl
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import urlsplit

from ..config import config
from ..logging_utils import get_logger
from ..openapi import get_openapi_spec

from .state import APPLICATION_JSON
from . import routes_public
from . import routes_admin
from . import routes_metrics
from . import routes_auth
from .auth import send_auth_required, login_required, is_authenticated


# Helper: generate a self-signed certificate (optional dependency: cryptography)
def _generate_self_signed_cert(cert_path: str):
    """Generate a self-signed cert at cert_path if it doesn't exist.

    Uses the `cryptography` package. If it's not available, an exception is raised.
    """
    if os.path.exists(cert_path):
        return
    logger = get_logger()
    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.backends import default_backend
    except Exception as e:
        logger.error(
            "cryptography package is required to auto-generate TLS certificates; install 'cryptography'"
        )
        raise

    logger.info(f"Generating self-signed certificate at {cert_path}")
    # Generate key
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048, backend=default_backend())

    # Build certificate
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, u"US"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, u"Local"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, u"Local"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, u"BadgeScanner"),
        x509.NameAttribute(NameOID.COMMON_NAME, u"localhost"),
    ])

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.utcnow())
        .not_valid_after(datetime.utcnow() + timedelta(days=3650))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(u"localhost")]), critical=False)
        .sign(key, hashes.SHA256(), default_backend())
    )

    # Ensure parent directory exists
    parent = os.path.dirname(cert_path)
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)

    # Write key + cert into a single PEM file
    with open(cert_path, "wb") as f:
        f.write(
            key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    # Restrict permissions where possible
    try:
        os.chmod(cert_path, 0o600)
    except Exception:
        # Not critical on Windows
        pass


NOT_FOUND = "Not Found"


@login_required
def _send_openapi_json(handler: BaseHTTPRequestHandler):
    """Send OpenAPI spec JSON (authenticated route).

    Determine request scheme (https/http) from common signals so the generated
    OpenAPI `servers` URL uses the same scheme as the incoming request. This
    helps avoid CORS/Swagger UI mixed-content problems when the health server
    sits behind a reverse proxy.

    Detection order:
    1. `X-Forwarded-Proto` header (if set by a proxy)
    2. Whether the underlying socket is an `ssl.SSLSocket`
    3. Fallback to `http`
    """
    try:
        host_header = handler.headers.get("Host")
        # Prefer explicit proxy header if present
        proto_hdr = None
        try:
            proto_hdr = handler.headers.get("X-Forwarded-Proto")
        except Exception:
            proto_hdr = None

        scheme = None
        if proto_hdr:
            scheme = proto_hdr.split(",", 1)[0].strip().lower()
        else:
            # If the request socket is SSL/TLS-wrapped, treat as https
            try:
                scheme = "https" if isinstance(handler.request, ssl.SSLSocket) else "http"
            except Exception:
                scheme = "http"

        # Construct a host value that includes the scheme so get_openapi_spec
        # preserves the correct protocol in the generated `servers` entry.
        host_for_spec = None
        if host_header:
            host_for_spec = f"{scheme}://{host_header}"
        else:
            host_for_spec = None

        get_logger().debug(f"OpenAPI request Host header: {host_header!r} proto={scheme!r}")
        spec = get_openapi_spec(host=host_for_spec)
        handler.send_response(200)
        handler.send_header("Content-type", APPLICATION_JSON)
        handler.end_headers()
        handler.wfile.write(json.dumps(spec).encode("utf-8"))
    except Exception as e:
        get_logger().error(f"Failed to generate OpenAPI spec: {e}")
        handler.send_error(500, f"Failed to generate OpenAPI spec: {e}")


class RequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler: public routes without auth, UI routes with login, /api with auth."""

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

    def _require_api_auth(self) -> bool:
        """Return True if request is allowed for /api routes."""
        if is_authenticated(self, allow_basic=True, allow_session=True):
            return True
        send_auth_required(self)
        return False

    def do_GET(self):
        try:
            get_logger().info(
                f"Health server request: {self.command} {self.path} from {self.client_address}"
            )
        except Exception:
            pass

        parsed = urlsplit(self.path)
        path = parsed.path
        raw_query = parsed.query

        if path == "/":
            self.send_response(302)
            self.send_header("Location", "/health")
            self.end_headers()
            return

        if path == "/health":
            routes_public.send_health_page(self)
            return

        if path == "/docs":
            routes_public.send_docs_page(self)
            return

        if path == "/login":
            routes_auth.send_login_page(self, raw_query)
            return

        if path == "/login/google":
            routes_auth.handle_google_login_start(self, raw_query)
            return

        if path == "/login/google/callback":
            routes_auth.handle_google_callback(self, raw_query)
            return

        if path == "/logout":
            routes_auth.handle_logout(self)
            return

        if path == "/openapi.json":
            _send_openapi_json(self)
            return

        if path == "/admin":
            routes_admin.send_admin_page(self)
            return

        if path == "/metrics":
            routes_metrics.send_metrics_page(self, raw_query)
            return

        if path == "/api/metrics":
            if not self._require_api_auth():
                return
            if routes_metrics.handle_unified_metrics_api(self, raw_query):
                return

        # Authenticated API: return current application version
        if path == "/api/version":
            if not self._require_api_auth():
                return
            try:
                from ..version import __version__
            except Exception:
                __version__ = "unknown"
            self.send_response(200)
            self.send_header("Content-type", APPLICATION_JSON)
            self.end_headers()
            self.wfile.write(json.dumps({"version": __version__}).encode("utf-8"))
            return

        if path.startswith("/admin/download/"):
            if routes_admin.handle_download(self, path):
                return
            self.send_error(404, NOT_FOUND)
            return

        self.send_error(404, NOT_FOUND)

    def do_POST(self):
        try:
            get_logger().info(
                f"Health server request: {self.command} {self.path} from {self.client_address}"
            )
        except Exception:
            pass

        parsed = urlsplit(self.path)
        path = parsed.path

        if path == "/login":
            routes_auth.handle_login_post(self)
            return

        if path == "/api/refresh_badges":
            if not self._require_api_auth():
                return
            if routes_admin.handle_post_refresh_badges(self):
                return

        if path == "/api/toggle":
            if not self._require_api_auth():
                return
            if routes_admin.handle_post_toggle(self):
                return

        if path == "/api/metrics/reload":
            if not self._require_api_auth():
                return
            if routes_metrics.handle_metrics_reload_post(self):
                return

        self.send_error(404, NOT_FOUND)

    def log_message(self, format, *args):
        get_logger().info(f"Health server: {format % args}")


class HealthServer:
    """HTTP/HTTPS server manager (same API as before for start.py compatibility)."""

    def __init__(self, port: Optional[int] = None, tls: Optional[bool] = None, cert_file: Optional[str] = None):
        # Allow port 0 (ephemeral port) so tests can start on an available port.
        if port is not None:
            self.port = port
        else:
            self.port = config["HEALTH_SERVER_PORT"]
        # TLS settings: default to config value if not explicitly provided
        if tls is None:
            self.tls = bool(config.get("HEALTH_SERVER_TLS", False))
        else:
            self.tls = bool(tls)
        self.cert_file = cert_file or config.get("HEALTH_SERVER_CERT_FILE")

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
                # Use ThreadingHTTPServer so multiple requests are handled concurrently
                self.server = ThreadingHTTPServer(("0.0.0.0", self.port), RequestHandler)

                if self.tls:
                    # Ensure cert exists (generate if missing)
                    cert_path = os.path.abspath(self.cert_file)
                    if not os.path.exists(cert_path):
                        try:
                            _generate_self_signed_cert(cert_path)
                        except Exception as e:
                            self.logger.error(f"Failed to generate TLS certificate: {e}")
                            # Fall back to non-TLS server if generation fails
                            self.logger.warning("Starting without TLS")
                            self.tls = False

                # Wrap server socket with TLS if requested
                if self.tls:
                    try:
                        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                        context.load_cert_chain(certfile=cert_path)
                        self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
                    except Exception as e:
                        self.logger.error(f"Failed to wrap server socket with TLS: {e}")
                        self.logger.warning("Starting without TLS")
                        self.tls = False

                actual_port = self.server.server_address[1] if self.server else self.port
                scheme = "https" if self.tls else "http"
                self.logger.info(f"Health server started on {scheme} port {actual_port}")
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


def start_health_server(port: Optional[int] = None, tls: Optional[bool] = None, cert_file: Optional[str] = None):
    """Start the global health server instance."""
    global _health_server
    if _health_server is None:
        _health_server = HealthServer(port=port, tls=tls, cert_file=cert_file)
    _health_server.start()


def stop_health_server():
    """Stop the global health server instance."""
    global _health_server
    if _health_server:
        _health_server.stop()
