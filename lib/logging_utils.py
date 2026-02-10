"""Logging utilities with local file and Google Sheets integration."""
import logging
from logging.handlers import TimedRotatingFileHandler
import threading
from typing import Optional
from datetime import datetime, date, timedelta
import os
import re

from .config import config
from .metrics_storage import ingest_action_log_file

# Global logger instance
logger = None
logger_lock = threading.Lock()

# Additional per-purpose loggers
action_logger = None
action_logger_lock = threading.Lock()

watchdog_logger = None
watchdog_logger_lock = threading.Lock()

# Timestamps for tracking sync events
last_google_log_success = None
last_badge_download = None
last_google_error = None
last_data_connection = None

# Thread-safe lock for timestamp updates
timestamp_lock = threading.Lock()


def setup_logger(log_file: Optional[str] = None) -> logging.Logger:
    """
    Set up rotating file logger with 7-day retention.

    Args:
        log_file: Path to log file. If None, uses config default.

    Returns:
        Configured logger instance.
    """
    global logger

    if logger is not None:
        return logger

    with logger_lock:
        if logger is not None:  # Double-check after acquiring lock
            return logger

        log_file_param = log_file
        log_file = log_file or config["LOG_FILE"]

        # Ensure log directory exists
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)

        # Create logger
        logger = logging.getLogger("door_controller")

        # Default level is INFO from config
        level_name = str(config.get("LOG_LEVEL", "INFO")).upper()
        level = getattr(logging, level_name, logging.INFO)
        logger.setLevel(level)

        # Create rotating file handler (rotates daily, keeps 7 days)
        if log_file_param is None:
            handler = DailyNamedFileHandler(log_file, config["LOG_RETENTION_DAYS"])
        else:
            handler = TimedRotatingFileHandler(
                log_file,
                when='midnight',
                interval=1,
                backupCount=config["LOG_RETENTION_DAYS"],
                encoding='utf-8'
            )

        # Create formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        handler.setFormatter(formatter)

        # Add handler to logger
        logger.addHandler(handler)

        # Also log to console
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

        logger.info("Logger initialized")

        return logger


def get_logger() -> logging.Logger:
    """Get the global logger instance, initializing if necessary."""
    global logger
    if logger is None:
        return setup_logger()
    return logger


def _build_derived_file(base_log_file: str, suffix: str) -> str:
    """Return a new file path derived from base_log_file by inserting suffix before the extension."""
    log_dir, base_name, ext = _parse_log_base(base_log_file)
    return os.path.join(log_dir, f"{base_name}{suffix}{ext}")


def _make_handler_for_file(log_file: str, retention_days: int):
    """Create a handler for a file path that rotates daily and keeps `retention_days` files."""
    return DailyNamedFileHandler(log_file, retention_days)


def get_action_logger() -> logging.Logger:
    """Get (and create if needed) the action-specific logger that writes to *_action-YYYY-MM-DD.ext"""
    global action_logger
    if action_logger is not None:
        return action_logger

    with action_logger_lock:
        if action_logger is not None:
            return action_logger

        name = "door_action"
        action_logger = logging.getLogger(name)

        # Avoid adding duplicate handlers on repeated imports or calls
        if action_logger.handlers:
            return action_logger

        # Use configured override if present, otherwise derive from LOG_FILE
        action_log_file = config.get("ACTION_LOG_FILE")
        if not action_log_file:
            action_log_file = _build_derived_file(config["LOG_FILE"], "_action")

        retention = int(config.get("LOG_RETENTION_DAYS", 7))
        handler = _make_handler_for_file(action_log_file, retention)

        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        handler.setFormatter(formatter)
        action_logger.addHandler(handler)
        action_logger.setLevel(get_logger().level)
        action_logger.propagate = False

        return action_logger


def get_watchdog_logger() -> logging.Logger:
    """Get (and create if needed) the watchdog logger that writes to *_watchdog-YYYY-MM-DD.ext"""
    global watchdog_logger
    if watchdog_logger is not None:
        return watchdog_logger

    with watchdog_logger_lock:
        if watchdog_logger is not None:
            return watchdog_logger

        name = "watchdog"
        watchdog_logger = logging.getLogger(name)

        if watchdog_logger.handlers:
            return watchdog_logger

        watchdog_log_file = config.get("WATCHDOG_LOG_FILE")
        if not watchdog_log_file:
            watchdog_log_file = _build_derived_file(config["LOG_FILE"], "_watchdog")

        retention = int(config.get("LOG_RETENTION_DAYS", 7))
        handler = _make_handler_for_file(watchdog_log_file, retention)

        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        handler.setFormatter(formatter)
        watchdog_logger.addHandler(handler)
        watchdog_logger.setLevel(get_logger().level)
        watchdog_logger.propagate = False

        return watchdog_logger


def record_action(action: str, badge_id: Optional[str] = None, status: str = "Success"):
    """
    Record a door action to local log and the action-specific log file.

    Args:
        action: Description of the action (e.g., "Door Unlocked", "Badge Scanned")
        badge_id: Optional badge ID for badge-related actions
        status: Status of the action (default: "Success")
    """
    log = get_logger()
    act_log = get_action_logger()

    # Format log message
    if badge_id:
        message = f"{action} - Badge: {badge_id} - Status: {status}"
    else:
        message = f"{action} - Status: {status}"

    # Determine severity
    if status.lower() in ["success", "granted"]:
        level = "info"
    elif status.lower() in ["denied", "rejected"]:
        level = "warning"
    else:
        level = "error"

    # Log to main logger
    getattr(log, level)(message)
    # Also log to action-specific logger (separate file)
    try:
        getattr(act_log, level)(message)
    except Exception:
        # Ensure action logging never breaks main flow
        log.exception("Failed to log to action logger")


def update_last_google_error(message: str):
    """Update the last Google Sheets error message."""
    global last_google_error
    with timestamp_lock:
        last_google_error = message


def update_last_google_log_success():
    """Manually update the last Google log success timestamp."""
    global last_google_log_success
    with timestamp_lock:
        last_google_log_success = datetime.now()


def update_last_data_connection():
    """Update the last data connection timestamp (any data retrieval)."""
    global last_data_connection
    with timestamp_lock:
        last_data_connection = datetime.now()


def initialize_last_badge_download_from_csv():
    """Initialize last_badge_download from CSV file mtime if available."""
    global last_badge_download
    try:
        csv_path = config.get("CSV_FILE")
        if csv_path and os.path.exists(csv_path):
            with timestamp_lock:
                last_badge_download = datetime.fromtimestamp(os.path.getmtime(csv_path))
    except Exception:
        pass


def update_last_badge_download(success: bool = True):
    """
    Update the last badge download timestamp.

    Args:
        success: Whether the download was successful
    """
    global last_badge_download
    with timestamp_lock:
        last_badge_download = datetime.now()

    if success:
        get_logger().info("Badge list downloaded successfully")
    else:
        get_logger().warning("Badge list download failed")

    # As part of daily badge list download, clean old logs
    try:
        cleanup_old_logs()
    except Exception:
        pass


def get_last_google_log_success() -> Optional[datetime]:
    """Get the timestamp of the last successful Google Sheets log."""
    with timestamp_lock:
        return last_google_log_success


def get_last_badge_download() -> Optional[datetime]:
    """Get the timestamp of the last badge list download."""
    with timestamp_lock:
        return last_badge_download


def get_last_data_connection() -> Optional[datetime]:
    """Get the timestamp of the last data retrieval from any source."""
    with timestamp_lock:
        return last_data_connection


def get_last_google_error() -> Optional[str]:
    """Get the last Google Sheets error message."""
    with timestamp_lock:
        return last_google_error


def log_pn532_error(error: Exception):
    """
    Log a PN532 RFID reader error.

    Args:
        error: The exception that occurred
    """
    get_logger().error(f"PN532 Error: {error}")


def log_pn532_success():
    """Log a successful PN532 read."""
    get_logger().debug("PN532 read successful")


# Simple cache for log file size to avoid repeated filesystem stat calls
_log_size_cache = {"modified": None, "size": 0}
_log_size_cache_lock = threading.Lock()


def get_log_file_size() -> int:
    """
    Get the size of the current log file in bytes.

    Results are cached for `HEALTH_CACHE_DURATION_MINUTES` (default 5) to reduce
    repeated filesystem calls during frequent health checks.

    Returns:
        File size in bytes, or 0 if file doesn't exist
    """
    from datetime import datetime, timedelta

    duration = int(config.get("HEALTH_CACHE_DURATION_MINUTES", 5) or 5)
    with _log_size_cache_lock:
        modified = _log_size_cache["modified"]
        if modified and (datetime.now() - modified) <= timedelta(minutes=duration):
            return int(_log_size_cache["size"])

    import os
    log_file = get_current_log_file_path()
    try:
        size = os.path.getsize(log_file)
    except FileNotFoundError:
        size = 0

    with _log_size_cache_lock:
        _log_size_cache["modified"] = datetime.now()
        _log_size_cache["size"] = size
    return size


def _parse_log_base(log_file: str):
    log_dir = os.path.dirname(log_file) or "."
    base = os.path.basename(log_file)
    base_name, ext = os.path.splitext(base)
    ext = ext or ".txt"
    return log_dir, base_name, ext


def _get_dated_log_path(log_file: str, for_date: date) -> str:
    log_dir, base_name, ext = _parse_log_base(log_file)
    return os.path.join(log_dir, f"{base_name}-{for_date:%Y-%m-%d}{ext}")


def get_current_log_file_path() -> str:
    log_file = config["LOG_FILE"]
    if os.path.exists(log_file):
        return log_file

    dated_path = _get_dated_log_path(log_file, date.today())
    if os.path.exists(dated_path):
        return dated_path

    return log_file


def get_current_action_log_file_path() -> str:
    """Return the path to the current (today's) action log file."""
    action_log_file = config.get("ACTION_LOG_FILE")
    if not action_log_file:
        action_log_file = _build_derived_file(config["LOG_FILE"], "_action")
    dated_path = _get_dated_log_path(action_log_file, date.today())
    if os.path.exists(dated_path):
        return dated_path
    if os.path.exists(action_log_file):
        return action_log_file
    return dated_path


def cleanup_old_logs(retention_days: Optional[int] = None):
    retention_days = retention_days or config["LOG_RETENTION_DAYS"]
    log_file = config["LOG_FILE"]
    log_dir, base_name, ext = _parse_log_base(log_file)

    if not os.path.exists(log_dir):
        return

    # Consider base, action, and watchdog derived file names
    suffixes = ["", "_action", "_watchdog"]
    cutoff = date.today() - timedelta(days=retention_days)

    for name in os.listdir(log_dir):
        for suffix in suffixes:
            pattern = re.compile(rf"^{re.escape(base_name + suffix)}-(\d{{4}}-\d{{2}}-\d{{2}}){re.escape(ext)}$")
            match = pattern.match(name)
            if not match:
                continue
            try:
                file_date = datetime.strptime(match.group(1), "%Y-%m-%d").date()
            except ValueError:
                continue
            if file_date < cutoff:
                try:
                    full_path = os.path.join(log_dir, name)
                    # Persist action log history into monthly sqlite metrics before deletion.
                    if suffix == "_action":
                        ingest_action_log_file(full_path)
                    os.remove(full_path)
                except Exception:
                    pass
            break

class DailyNamedFileHandler(logging.Handler):
    """Log handler that writes to a dated log file and rolls over daily."""

    def __init__(self, base_log_file: str, retention_days: int):
        super().__init__()
        self.base_log_file = base_log_file
        self.retention_days = retention_days
        self._current_date = None
        self._stream = None
        self._open_for_date(date.today())

    def _open_for_date(self, target_date: date):
        if self._stream:
            try:
                self._stream.close()
            except Exception:
                pass

        log_dir, _, _ = _parse_log_base(self.base_log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)

        self._current_date = target_date
        self.baseFilename = _get_dated_log_path(self.base_log_file, target_date)
        self._stream = open(self.baseFilename, "a", encoding="utf-8")

    def emit(self, record):
        try:
            today = date.today()
            if self._current_date != today:
                self._open_for_date(today)
                cleanup_old_logs(self.retention_days)

            msg = self.format(record)
            self._stream.write(msg + "\n")
            self.flush()
        except Exception:
            self.handleError(record)

    def flush(self):
        if self._stream:
            try:
                self._stream.flush()
            except Exception:
                pass

    def close(self):
        try:
            if self._stream:
                self._stream.close()
        finally:
            self._stream = None
            super().close()


# Initialize logger at import time so other modules can use `logger` directly
initialize_last_badge_download_from_csv()
logger = setup_logger()
# ensure other logs are created and rotated as well
try:
    get_action_logger()
    get_watchdog_logger()
except Exception:
    # Do not raise on import-time logger initialization failures
    logger.exception("Failed to initialize action/watchdog loggers")
