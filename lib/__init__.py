"""Library modules for the door controller."""

from .config import config, __version__
from .logging_utils import (
    setup_logger,
    get_logger,
    record_action,
    update_last_badge_download,
    log_pn532_error,
    get_last_google_log_success,
    get_last_badge_download,
    get_last_google_error,
    get_log_file_size,
    update_last_google_error,
)
from .data import GoogleSheetsData
from .door_control import DoorController, set_door_status, get_door_status, get_door_status_updated
from .health_server import HealthServer, update_pn532_success, update_pn532_error
from .watchdog import start_watchdog, stop_watchdog, update_watchdog_heartbeat

__all__ = [
    'config',
    '__version__',
    'setup_logger',
    'get_logger',
    'record_action',
    'update_last_badge_download',
    'log_pn532_error',
    'get_last_google_log_success',
    'get_last_badge_download',
    'get_last_google_error',
    'get_log_file_size',
    'update_last_google_error',
    'GoogleSheetsData',
    'DoorController',
    'set_door_status',
    'get_door_status',
    'get_door_status_updated',
    'HealthServer',
    'update_pn532_success',
    'update_pn532_error',
    'start_watchdog',
    'stop_watchdog',
    'update_watchdog_heartbeat',
]
