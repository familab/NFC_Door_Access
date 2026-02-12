"""Authentication helpers: Basic auth checks, session cookies, and login guard."""
import base64
import secrets
import time
from http import cookies
from typing import Optional
from urllib.parse import quote

from ..config import config
from ..logging_utils import get_logger


_SESSION_STORE = {}
_OAUTH_STATE_STORE = {}
_OAUTH_STATE_TTL_SECONDS = 600


def _now_ts() -> int:
    return int(time.time())


def _session_cookie_name() -> str:
    return str(config.get("AUTH_SESSION_COOKIE_NAME", "door_session"))


def _session_ttl_seconds() -> int:
    try:
        return int(config.get("AUTH_SESSION_TTL_SECONDS", 8 * 60 * 60))
    except Exception:
        return 8 * 60 * 60


def _parse_cookies(handler) -> cookies.SimpleCookie:
    jar = cookies.SimpleCookie()
    try:
        raw = handler.headers.get("Cookie") if hasattr(handler, "headers") else None
    except Exception:
        raw = None
    if raw:
        try:
            jar.load(raw)
        except Exception:
            pass
    return jar


def _clean_expired_sessions() -> None:
    now = _now_ts()
    expired = [sid for sid, data in _SESSION_STORE.items() if data.get("expires_at", 0) <= now]
    for sid in expired:
        _SESSION_STORE.pop(sid, None)


def create_session(user_email: str) -> str:
    _clean_expired_sessions()
    session_id = secrets.token_urlsafe(32)
    ttl = _session_ttl_seconds()
    _SESSION_STORE[session_id] = {
        "user_email": user_email,
        "created_at": _now_ts(),
        "expires_at": _now_ts() + ttl,
    }
    return session_id


def get_session(handler) -> Optional[dict]:
    _clean_expired_sessions()
    jar = _parse_cookies(handler)
    cookie_name = _session_cookie_name()
    if cookie_name not in jar:
        return None
    session_id = jar[cookie_name].value
    session = _SESSION_STORE.get(session_id)
    if not session:
        return None
    if session.get("expires_at", 0) <= _now_ts():
        _SESSION_STORE.pop(session_id, None)
        return None
    return session


def clear_session(handler) -> None:
    jar = _parse_cookies(handler)
    cookie_name = _session_cookie_name()
    if cookie_name in jar:
        _SESSION_STORE.pop(jar[cookie_name].value, None)


def set_session_cookie(handler, session_id: str) -> None:
    ttl = _session_ttl_seconds()
    cookie = cookies.SimpleCookie()
    cookie[_session_cookie_name()] = session_id
    cookie[_session_cookie_name()]["path"] = "/"
    cookie[_session_cookie_name()]["httponly"] = True
    cookie[_session_cookie_name()]["samesite"] = "Lax"
    cookie[_session_cookie_name()]["max-age"] = str(ttl)
    handler.send_header("Set-Cookie", cookie.output(header="").strip())


def clear_session_cookie(handler) -> None:
    cookie = cookies.SimpleCookie()
    cookie[_session_cookie_name()] = ""
    cookie[_session_cookie_name()]["path"] = "/"
    cookie[_session_cookie_name()]["httponly"] = True
    cookie[_session_cookie_name()]["samesite"] = "Lax"
    cookie[_session_cookie_name()]["max-age"] = "0"
    handler.send_header("Set-Cookie", cookie.output(header="").strip())


def check_basic_auth(handler) -> bool:
    """Check HTTP Basic Auth. Returns True if authenticated."""
    auth_header = None
    try:
        auth_header = handler.headers.get("Authorization") if hasattr(handler, "headers") else None
    except Exception:
        auth_header = None
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
    except Exception as exc:
        get_logger().warning(f"Auth check failed: {exc}")
        return False


def send_auth_required(handler):
    """Send 401 Unauthorized."""
    handler.send_response(401)
    handler.send_header("WWW-Authenticate", 'Basic realm="Door Controller"')
    handler.send_header("Content-type", "text/html; charset=utf-8")
    handler.end_headers()
    handler.wfile.write(b"<html><body><h1>401 Unauthorized</h1></body></html>")


def is_authenticated(handler, allow_basic: bool = True, allow_session: bool = True) -> bool:
    if allow_session and get_session(handler):
        return True
    if allow_basic and check_basic_auth(handler):
        return True
    return False


def get_current_user(handler) -> Optional[dict]:
    """Get current authenticated user info. Returns dict with 'email' and 'auth_method' or None."""
    session = get_session(handler)
    if session:
        return {
            "email": session.get("user_email"),
            "auth_method": "google_oauth"
        }
    if check_basic_auth(handler):
        return {
            "email": config.get("HEALTH_SERVER_USERNAME"),
            "auth_method": "basic_auth"
        }
    return None


def _sanitize_next(next_path: Optional[str]) -> str:
    if not next_path:
        return "/admin"
    if not next_path.startswith("/"):
        return "/admin"
    if next_path.startswith("//"):
        return "/admin"
    return next_path


def redirect_to_login(handler, next_path: Optional[str] = None) -> None:
    safe_next = _sanitize_next(next_path)
    location = f"/login?next={quote(safe_next)}"
    handler.send_response(302)
    handler.send_header("Location", location)
    handler.send_header("Content-Length", "0")
    handler.end_headers()
    try:
        handler.wfile.flush()
    except Exception:
        pass


def login_required(fn):
    """Decorator to require auth for non-API routes and redirect to /login if missing."""

    def wrapper(handler, *args, **kwargs):
        if is_authenticated(handler, allow_basic=True, allow_session=True):
            return fn(handler, *args, **kwargs)
        # If OAuth is enabled, redirect to login page; otherwise send Basic Auth challenge
        if config.get("GOOGLE_OAUTH_ENABLED"):
            redirect_to_login(handler, getattr(handler, "path", "/admin"))
        else:
            send_auth_required(handler)
        return True

    return wrapper


def save_oauth_state(state: str, next_path: str) -> None:
    _OAUTH_STATE_STORE[state] = {
        "next": _sanitize_next(next_path),
        "expires_at": _now_ts() + _OAUTH_STATE_TTL_SECONDS,
    }


def pop_oauth_state(state: str) -> Optional[str]:
    data = _OAUTH_STATE_STORE.pop(state, None)
    if not data:
        return None
    if data.get("expires_at", 0) <= _now_ts():
        return None
    return data.get("next")


def _normalize_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item).strip() for item in value if str(item).strip()]
    raw = str(value)
    if not raw.strip():
        return []
    parts = [p.strip() for p in raw.replace(",", ";").split(";")]
    return [p for p in parts if p]


def is_email_whitelisted(email: str) -> bool:
    if not email:
        return False
    email = email.strip().lower()
    allowed_emails = _normalize_list(config.get("AUTH_WHITELIST_EMAILS", []))
    allowed_domains = _normalize_list(config.get("AUTH_WHITELIST_DOMAINS", []))

    if not allowed_emails and not allowed_domains:
        return True

    if email in [e.lower() for e in allowed_emails]:
        return True

    if "@" not in email:
        return False
    domain = email.split("@", 1)[1]
    domain = domain.lower()

    for entry in allowed_domains:
        entry = entry.lower()
        if not entry:
            continue
        if entry.startswith("*."):
            suffix = entry[2:]
            if domain == suffix or domain.endswith("." + suffix):
                return True
        elif entry.startswith("."):
            suffix = entry[1:]
            if domain == suffix or domain.endswith("." + suffix):
                return True
        else:
            if domain == entry:
                return True
    return False


