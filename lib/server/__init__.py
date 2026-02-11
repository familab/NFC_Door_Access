"""HTTP health and admin server. Re-exports public API for start.py and backwards compatibility."""
from .server import (
    HealthServer,
    RequestHandler,
    start_health_server,
    stop_health_server,
)
from .state import (
    update_pn532_success,
    update_pn532_error,
    get_pn532_status,
    set_badge_refresh_callback,
    set_door_toggle_callback,
    update_badge_refresh_attempt_time,
    format_timestamp,
    get_uptime,
    get_uptime_seconds,
    get_disk_space,
)

__all__ = [
    "HealthServer",
    "RequestHandler",
    "start_health_server",
    "stop_health_server",
    "update_pn532_success",
    "update_pn532_error",
    "get_pn532_status",
    "set_badge_refresh_callback",
    "set_door_toggle_callback",
    "update_badge_refresh_attempt_time",
    "format_timestamp",
    "get_uptime",
    "get_uptime_seconds",
    "get_disk_space",
]
