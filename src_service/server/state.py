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
_door_toggle_fn = None

# Badge refresh timing: Track last scheduled refresh attempt (not rate-limited click)
# Used to advance timer even if refresh fails (success or failure, mtime doesn't change)
_last_badge_refresh_attempt_time = 0.0  # seconds since epoch
_badge_refresh_attempt_lock = threading.Lock()

# Rate limit: last time each action was allowed (seconds since epoch)
_last_badge_refresh_time = 0.0
_last_state_refresh_time = 0.0
_last_metrics_reload_time = 0.0
_last_door_toggle_time = 0.0
_rate_limit_seconds = int(config.get("BADGE_REFRESH_RATE_LIMIT_SECONDS", 300) or 300)
_door_toggle_rate_limit_seconds = int(config.get("DOOR_TOGGLE_RATE_LIMIT_SECONDS", 5) or 5)
_rate_limit_lock = threading.Lock()

# Health caching (cached for a configurable number of minutes)
_health_cache_lock = threading.Lock()
_local_ips_cache = {"modified": None, "value": []}  # {'modified': datetime, 'value': List[str]}
_disk_space_cache = {"modified": None, "value": {"free_mb": 0, "total_mb": 0, "used_mb": 0, "percent_used": 0}}


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


def set_door_toggle_callback(fn):
    """Register a callback for manual door lock/unlock toggle."""
    global _door_toggle_fn
    _door_toggle_fn = fn


def get_door_toggle_callback():
    """Return the registered door toggle callback or None."""
    return _door_toggle_fn


def update_badge_refresh_attempt_time():
    """Record that a badge refresh was attempted (success or failure).

    Used to advance the timer even if refresh fails. Call this after each
    refresh attempt in the scheduled refresh loop.
    """
    import time as _time
    global _last_badge_refresh_attempt_time
    with _badge_refresh_attempt_lock:
        _last_badge_refresh_attempt_time = _time.time()


def get_last_badge_refresh_attempt_time() -> float:
    """Get the timestamp of the last badge refresh attempt (success or failure)."""
    global _last_badge_refresh_attempt_time
    with _badge_refresh_attempt_lock:
        return _last_badge_refresh_attempt_time


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


def check_rate_limit_metrics_reload() -> tuple[bool, str]:
    """Return (True, '') if allowed, else (False, error_message)."""
    import time as _time
    global _last_metrics_reload_time
    with _rate_limit_lock:
        now = _time.time()
        if now - _last_metrics_reload_time < _rate_limit_seconds:
            wait = int(_rate_limit_seconds - (now - _last_metrics_reload_time))
            return False, f"Rate limited. Try again in {wait} seconds."
        _last_metrics_reload_time = now
    return True, ""


def get_seconds_until_next_metrics_reload() -> int:
    """Return seconds until metrics reload is available again (based on rate limit)."""
    import time as _time
    global _last_metrics_reload_time
    with _rate_limit_lock:
        now = _time.time()
        elapsed = now - _last_metrics_reload_time
        wait = int(max(0, _rate_limit_seconds - elapsed))
        return wait


def check_rate_limit_door_toggle() -> tuple[bool, str]:
    """Return (True, '') if allowed, else (False, error_message)."""
    import time as _time
    global _last_door_toggle_time
    with _rate_limit_lock:
        now = _time.time()
        if now - _last_door_toggle_time < _door_toggle_rate_limit_seconds:
            wait = int(_door_toggle_rate_limit_seconds - (now - _last_door_toggle_time))
            return False, f"Rate limited. Try again in {wait} seconds."
        _last_door_toggle_time = now
    return True, ""


def format_timestamp(dt: Optional[datetime]) -> str:
    """Format a datetime for display."""
    if dt is None:
        return "Never"
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def get_local_ips() -> List[str]:
    """Return local IPv4 addresses, excluding 127.* and 172.*.

    Results are cached for `HEALTH_CACHE_DURATION_MINUTES` (default 5) to avoid
    repeated DNS/socket calls on each health page render. The cache stores a
    `modified` datetime and the `value` list and is refreshed when older than the
    configured duration.
    """
    from datetime import datetime, timedelta

    duration = int(config.get("HEALTH_CACHE_DURATION_MINUTES", 5) or 5)
    with _health_cache_lock:
        modified = _local_ips_cache["modified"]
        if modified and (datetime.now() - modified) <= timedelta(minutes=duration):
            return list(_local_ips_cache["value"])

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

    val = sorted(ips)
    with _health_cache_lock:
        _local_ips_cache["modified"] = datetime.now()
        _local_ips_cache["value"] = val
    return val


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


def get_uptime_seconds() -> int:
    """Application uptime as total seconds (for JavaScript auto-increment)."""
    uptime = datetime.now() - _app_start_time
    return int(uptime.total_seconds())


def get_disk_space() -> dict:
    """Disk space info (free_mb, total_mb, used_mb, percent_used).

    Cached similarly to `get_local_ips` using `HEALTH_CACHE_DURATION_MINUTES`.
    """
    from datetime import datetime, timedelta

    duration = int(config.get("HEALTH_CACHE_DURATION_MINUTES", 5) or 5)
    with _health_cache_lock:
        modified = _disk_space_cache["modified"]
        if modified and (datetime.now() - modified) <= timedelta(minutes=duration):
            return dict(_disk_space_cache["value"])

    try:
        stat = os.statvfs("/")
        free_bytes = stat.f_bavail * stat.f_frsize
        total_bytes = stat.f_blocks * stat.f_frsize
        used_bytes = total_bytes - free_bytes
        data = {
            "free_mb": free_bytes / (1024 * 1024),
            "total_mb": total_bytes / (1024 * 1024),
            "used_mb": used_bytes / (1024 * 1024),
            "percent_used": (used_bytes / total_bytes) * 100 if total_bytes > 0 else 0,
        }
    except Exception as e:
        get_logger().warning(f"Failed to get disk space: {e}")
        data = {"free_mb": 0, "total_mb": 0, "used_mb": 0, "percent_used": 0}

    with _health_cache_lock:
        _disk_space_cache["modified"] = datetime.now()
        _disk_space_cache["value"] = data
    return data


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
    """Return seconds until next scheduled badge refresh.

    Priority order:
    1. Use last refresh attempt time (success or failure) to ensure timer advances even on failure
    2. Fall back to CSV file modification time if no attempt recorded yet
    3. Return 0 if no reference point exists (refresh should run immediately)

    Uses `BADGE_REFRESH_INTERVAL_SECONDS` to calculate the interval.
    """
    import time as _time
    interval = int(config.get("BADGE_REFRESH_INTERVAL_SECONDS", 24 * 60 * 60) or 0)
    if interval <= 0:
        return 0

    # Prefer last refresh attempt time (updates even on failure)
    attempt_time = get_last_badge_refresh_attempt_time()
    if attempt_time > 0:
        elapsed = max(0, _time.time() - attempt_time)
        wait = int(max(0, interval - elapsed))
        return wait

    # Fall back to CSV file mtime if no attempt recorded yet
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

    # No reference point -> should refresh immediately
    return 0



