"""Logging utilities with local file and Google Sheets integration."""
import logging
from logging.handlers import TimedRotatingFileHandler
import time
import threading
from typing import Optional
from datetime import datetime

from .config import config

# Global logger instance
logger = None
logger_lock = threading.Lock()

# Timestamps for tracking sync events
last_google_log_success = None
last_badge_download = None
last_google_error = None

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

        log_file = log_file or config["LOG_FILE"]

        # Create logger
        logger = logging.getLogger("door_controller")
        logger.setLevel(logging.INFO)

        # Create rotating file handler (rotates daily, keeps 7 days)
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


def record_action(action: str, badge_id: Optional[str] = None, status: str = "Success"):
    """
    Record a door action to local log and optionally Google Sheets.

    Args:
        action: Description of the action (e.g., "Door Unlocked", "Badge Scanned")
        badge_id: Optional badge ID for badge-related actions
        status: Status of the action (default: "Success")
    """
    log = get_logger()

    # Format log message
    if badge_id:
        message = f"{action} - Badge: {badge_id} - Status: {status}"
    else:
        message = f"{action} - Status: {status}"

    # Always log locally
    if status.lower() in ["success", "granted"]:
        log.info(message)
    elif status.lower() in ["denied", "rejected"]:
        log.warning(message)
    else:
        log.error(message)


def log_to_google_sheets(log_sheet, uid: str, status: str) -> bool:
    """
    Attempt to log access event to Google Sheets (best-effort).

    Args:
        log_sheet: Google Sheets worksheet object
        uid: Badge UID or action description
        status: Status of the access attempt

    Returns:
        True if successful, False otherwise
    """
    global last_google_log_success, last_google_error

    try:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        log_sheet.append_row([timestamp, uid, status])

        with timestamp_lock:
            last_google_log_success = datetime.now()

        get_logger().debug(f"Successfully logged to Google Sheets: {uid} - {status}")
        return True

    except Exception as e:
        with timestamp_lock:
            last_google_error = str(e)

        get_logger().warning(f"Failed to log to Google Sheets: {e}")
        return False


def update_last_google_log_success():
    """Manually update the last Google log success timestamp."""
    global last_google_log_success
    with timestamp_lock:
        last_google_log_success = datetime.now()


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


def get_last_google_log_success() -> Optional[datetime]:
    """Get the timestamp of the last successful Google Sheets log."""
    with timestamp_lock:
        return last_google_log_success


def get_last_badge_download() -> Optional[datetime]:
    """Get the timestamp of the last badge list download."""
    with timestamp_lock:
        return last_badge_download


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


def get_log_file_size() -> int:
    """
    Get the size of the current log file in bytes.

    Returns:
        File size in bytes, or 0 if file doesn't exist
    """
    import os
    log_file = config["LOG_FILE"]
    try:
        return os.path.getsize(log_file)
    except FileNotFoundError:
        return 0
