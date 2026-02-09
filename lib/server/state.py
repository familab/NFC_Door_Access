"""Shared state and helpers for the HTTP server (no route imports to avoid circular deps)."""
import os
import socket
import threading
from datetime import datetime
from typing import Optional, List

from ..config import config
from ..logging_utils import get_logger, get_current_log_file_path

# Content types
TEXT_HTML = "text/html"
APPLICATION_JSON = "application/json"

# Global state for health monitoring
_app_start_time = datetime.now()
_last_pn532_success = None
_last_pn532_error = None
_pn532_lock = threading.Lock()

# Badge refresh callback (set by start.py)
_badge_refresh_fn = None

# Rate limit: last time each action was allowed (seconds since epoch)
_last_badge_refresh_time = 0.0
_last_state_refresh_time = 0.0
_rate_limit_seconds = 300  # 5 minutes
_rate_limit_lock = threading.Lock()


def update_pn532_success():
    """Update the timestamp of the last successful PN532 read."""
    global _last_pn532_success
    with _pn532_lock:
        _last_pn532_success = datetime.now()


def update_pn532_error(error: str):
    """Update the last PN532 error."""
    global _last_pn532_error
    with _pn532_lock:
        _last_pn532_error = error


def get_pn532_status():
    """Get PN532 status information."""
    with _pn532_lock:
        return {
            "last_success": _last_pn532_success,
            "last_error": _last_pn532_error,
        }


def set_badge_refresh_callback(fn):
    """Register a callback for manual badge refresh. Callback may return bool or (bool, info)."""
    global _badge_refresh_fn
    _badge_refresh_fn = fn


def get_badge_refresh_callback():
    """Return the registered badge refresh callback or None."""
    return _badge_refresh_fn


def check_rate_limit_badge_refresh() -> tuple[bool, str]:
    """Return (True, '') if allowed, else (False, error_message)."""
    import time as _time
    global _last_badge_refresh_time
    with _rate_limit_lock:
        now = _time.time()
        if now - _last_badge_refresh_time < _rate_limit_seconds:
            wait = int(_rate_limit_seconds - (now - _last_badge_refresh_time))
            return False, f"Rate limited. Try again in {wait} seconds."
        _last_badge_refresh_time = now
    return True, ""


def check_rate_limit_state_refresh() -> tuple[bool, str]:
    """Return (True, '') if allowed, else (False, error_message)."""
    import time as _time
    global _last_state_refresh_time
    with _rate_limit_lock:
        now = _time.time()
        if now - _last_state_refresh_time < _rate_limit_seconds:
            wait = int(_rate_limit_seconds - (now - _last_state_refresh_time))
            return False, f"Rate limited. Try again in {wait} seconds."
        _last_state_refresh_time = now
    return True, ""


def format_timestamp(dt: Optional[datetime]) -> str:
    """Format a datetime for display."""
    if dt is None:
        return "Never"
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def get_local_ips() -> List[str]:
    """Return local IPv4 addresses, excluding 127.* and 172.*."""
    ips = set()
    try:
        hostname = socket.gethostname()
        for res in socket.getaddrinfo(hostname, None):
            family, sockaddr = res[0], res[4]
            if family == socket.AF_INET:
                ip = sockaddr[0]
                if not (ip.startswith("127.") or ip.startswith("172.")):
                    ips.add(ip)
    except Exception:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if not (ip.startswith("127.") or ip.startswith("172.")):
            ips.add(ip)
    except Exception:
        pass
    return sorted(ips)


def get_uptime() -> str:
    """Application uptime as formatted string."""
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
    """Disk space info (free_mb, total_mb, used_mb, percent_used)."""
    try:
        stat = os.statvfs("/")
        free_bytes = stat.f_bavail * stat.f_frsize
        total_bytes = stat.f_blocks * stat.f_frsize
        used_bytes = total_bytes - free_bytes
        return {
            "free_mb": free_bytes / (1024 * 1024),
            "total_mb": total_bytes / (1024 * 1024),
            "used_mb": used_bytes / (1024 * 1024),
            "percent_used": (used_bytes / total_bytes) * 100 if total_bytes > 0 else 0,
        }
    except Exception as e:
        get_logger().warning(f"Failed to get disk space: {e}")
        return {"free_mb": 0, "total_mb": 0, "used_mb": 0, "percent_used": 0}


def read_log_tail(path: str, last_n: int) -> str:
    """Read last N lines from a file. Returns '' on error."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
            if not lines:
                return ""
            tail = lines[-last_n:]
            return "\n".join(line.rstrip("\n") for line in tail)
    except Exception:
        return ""


def read_log_full(path: str) -> str:
    """Read full file content. Returns '' on error."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return ""


def get_seconds_until_next_badge_refresh() -> int:
    """Return seconds until next scheduled badge refresh based on CSV mtime.

    Uses `BADGE_REFRESH_INTERVAL_SECONDS` and the CSV file modification time to
    calculate how long until the next scheduled refresh should run.
    Returns 0 if refresh should run immediately (no CSV present or interval elapsed).
    """
    import time as _time
    interval = int(config.get("BADGE_REFRESH_INTERVAL_SECONDS", 24 * 60 * 60) or 0)
    if interval <= 0:
        return 0

    csv_path = config.get("CSV_FILE")
    try:
        if csv_path and os.path.exists(csv_path):
            mtime = os.path.getmtime(csv_path)
            elapsed = max(0, _time.time() - mtime)
            wait = int(max(0, interval - elapsed))
            return wait
    except Exception:
        # If anything goes wrong just allow immediate refresh
        return 0

    # No CSV file -> should refresh immediately
    return 0



