#!/usr/bin/env python3
"""
Door Controller - Raspberry Pi Zero RFID Access Control System

This application manages door access control using:
- PN532 NFC/RFID reader
- Google Sheets for badge management and logging
- GPIO-controlled door relay
- Physical unlock/lock buttons
- Health monitoring HTTP server
- Rotating local logs with Google Sheets failover
"""
import sys
import os

# Try to import Raspberry Pi GPIO, fall back to emulator/stub for development on Windows
try:
    import RPi.GPIO as GPIO
except Exception:
    try:
        # Some emulator packages may expose an alternative module name
        import RPi.GPIO_emulator as GPIO  # type: ignore
    except Exception:
        # Local stub as final fallback
        import importlib
        GPIO = importlib.import_module('lib.gpio_stub')
        print("Warning: RPi.GPIO not found; using GPIO stub for development.")
import time
import threading
import csv
from typing import Optional
try:
    import board
    import busio
    from adafruit_pn532.i2c import PN532_I2C
except Exception:
    board = None
    busio = None
    PN532_I2C = None
    # PN532 hardware libs not available; we will use a stub at initialization time

# Import new modules
from lib.config import config
from lib.logging_utils import (
    logger,
    record_action,
    log_pn532_error
)
from lib.data import GoogleSheetsData
from lib.door_control import DoorController, set_door_status, get_door_status
from lib.server import (
    start_health_server,
    stop_health_server,
    update_pn532_success,
    update_pn532_error,
    set_badge_refresh_callback,
    set_door_toggle_callback,
)
from lib.watchdog import start_watchdog, stop_watchdog

# GPIO Pin Definitions (from config)
RELAY_PIN = config["RELAY_PIN"]
BUTTON_UNLOCK_PIN = config["BUTTON_UNLOCK_PIN"]
BUTTON_LOCK_PIN = config["BUTTON_LOCK_PIN"]

# Time for unlocking (from config)
UNLOCK_DURATION = config["UNLOCK_DURATION"]

# Local CSV backup file
CSV_FILE = config["CSV_FILE"]

# Global `logger` is initialized in lib.logging_utils at import time
# Use the module-level `logger` imported above

# Log which backends are active for easier debugging in dev
try:
    gpio_backend = getattr(GPIO, '__name__', type(GPIO).__name__)
except Exception:
    gpio_backend = str(GPIO)

try:
    pn532_backend = 'PN532 hardware libs' if PN532_I2C is not None else 'PN532 stub'
except Exception:
    pn532_backend = 'PN532 stub'

logger.info("=" * 60)
logger.info(f"Door Controller Starting (GPIO backend: {gpio_backend}; PN532: {pn532_backend})")
logger.info("=" * 60)

# Google Sheets Setup (lazy imports handled inside data wrapper)
data_client = GoogleSheetsData()
data_client.connect()


def _refresh_badge_list():
    """Refresh badge list from Google Sheets and update local CSV backup.

    Returns:
        (success: bool, message: str)
    """
    return data_client.refresh_badge_list_to_csv(CSV_FILE)


def _schedule_daily_badge_refresh(stop_event: threading.Event):
    """Refresh badge CSV on a fixed interval while the app runs."""
    interval = int(config.get("BADGE_REFRESH_INTERVAL_SECONDS", 24 * 60 * 60))
    if interval <= 0:
        logger.warning("Badge refresh interval is <= 0; disabling scheduled refresh")
        return

    # Determine initial delay based on CSV mtime to avoid aggressive refresh after crashes
    try:
        if os.path.exists(CSV_FILE):
            last_modified = os.path.getmtime(CSV_FILE)
            elapsed = max(0, time.time() - last_modified)
        else:
            elapsed = interval + 1
    except Exception as e:
        logger.warning(f"Failed to read CSV mtime: {e}")
        elapsed = interval + 1

    initial_delay = max(0, interval - elapsed)
    logger.info(
        f"Daily badge refresh thread started (interval: {interval}s, initial delay: {int(initial_delay)}s)"
    )

    if initial_delay > 0:
        stop_event.wait(initial_delay)

    while not stop_event.is_set():
        try:
            success, message = data_client.refresh_badge_list_to_csv(CSV_FILE)
            if success:
                logger.info(f"Scheduled badge refresh completed: {message}")
            else:
                logger.warning(f"Scheduled badge refresh failed: {message}")
        except Exception as e:
            logger.warning(f"Scheduled badge refresh error: {e}")

        # Wait for next interval or stop
        stop_event.wait(interval)

    logger.info("Daily badge refresh thread exiting")

set_badge_refresh_callback(_refresh_badge_list)

# Lock object for managing GPIO access between threads
gpio_lock = threading.Lock()

# Global stop event used for graceful shutdown (Ctrl+C)
stop_event = threading.Event()

# Setup GPIO
try:
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(RELAY_PIN, GPIO.OUT)
    GPIO.setup(BUTTON_UNLOCK_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(BUTTON_LOCK_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    # Initially, keep the relay off (door locked)
    GPIO.output(RELAY_PIN, GPIO.LOW)
    set_door_status(False)

    logger.info("GPIO initialized successfully")
except Exception as e:
    logger.warning(f"Failed to initialize GPIO: {e}. Continuing with GPIO stub if available.")
    # Continue running in development mode; GPIO may be a stub module

# I2C setup for PN532
try:
    i2c = busio.I2C(board.SCL, board.SDA)
    pn532 = PN532_I2C(i2c, debug=False)
    pn532.SAM_configuration()
    logger.info("PN532 RFID reader initialized")
except Exception as e:
    logger.warning(f"Failed to initialize PN532: {e}. Using PN532 stub for development.")
    from lib.pn532_stub import PN532Stub
    pn532 = PN532Stub()

# Initialize door controller
door_controller = DoorController(GPIO, RELAY_PIN, gpio_lock)

# Button state tracking
last_unlock_time = 0
last_lock_time = 0
debounce_time = config["DEBOUNCE_TIME"]


def unlock_door(badge_id: Optional[str] = None):
    """Unlock door for 1 hour using door controller.

    Args:
        badge_id: Optional badge identifier to attribute this manual action to.
    """
    record_action("Manual Unlock (1 hour)", badge_id=badge_id)
    door_controller.unlock_door(UNLOCK_DURATION, badge_id=badge_id)
    try:
        data_client.log_access("Manual Unlock (1 hour)", "Success")
    except Exception:
        pass


def lock_door(badge_id: Optional[str] = None):
    """Lock door using door controller.

    Args:
        badge_id: Optional badge identifier to attribute this manual action to.
    """
    record_action("Manual Lock", badge_id=badge_id)
    door_controller.lock_door(badge_id=badge_id)
    try:
        data_client.log_access("Manual Lock", "Success")
    except Exception:
        pass


def _toggle_door_state(badge_id: Optional[str] = None):
    """Reuse existing manual lock/unlock actions and return the new lock state.

    Accepts optional badge_id which is forwarded to underlying actions for auditing.
    """
    if get_door_status():
        lock_door(badge_id=badge_id)
        return "locked"
    unlock_door(badge_id=badge_id)
    return "unlocked"


set_door_toggle_callback(_toggle_door_state)


# Fallback to CSV if Google Sheets is unavailable
def check_local_csv(uid):
    """
    Check if UID exists in local CSV backup.

    Args:
        uid: Badge UID to check

    Returns:
        True if UID found, False otherwise
    """
    try:
        with open(CSV_FILE, mode='r') as file:
            reader = csv.reader(file)
            for row in reader:
                if row and row[0].strip().lower() == uid.lower():
                    return True
    except FileNotFoundError as e:
        logger.error(f"Local CSV file '{CSV_FILE}' not found")
        raise e
    except Exception as e:
        logger.error(f"Error reading local CSV: {e}")
        raise e
    return False


# Manual polling function for buttons
def monitor_buttons(stop_event: threading.Event):
    """Monitor physical unlock/lock buttons with debouncing.

    The loop checks `stop_event` and exits when it's set for graceful shutdown.
    """
    global last_unlock_time, last_lock_time

    logger.info("Button monitoring thread started")

    while not stop_event.is_set():
        unlock_button_state = GPIO.input(BUTTON_UNLOCK_PIN)
        lock_button_state = GPIO.input(BUTTON_LOCK_PIN)

        current_time = time.time()

        # Unlock button check with debounce
        if unlock_button_state == GPIO.LOW:
            time.sleep(0.05)  # Check again after 50ms
            if GPIO.input(BUTTON_UNLOCK_PIN) == GPIO.LOW:  # Confirm it's still pressed
                if not get_door_status() and (current_time - last_unlock_time > debounce_time):
                    unlock_door()
                    last_unlock_time = current_time

        # Lock button check with debounce
        if lock_button_state == GPIO.LOW and (current_time - last_lock_time > debounce_time):
            if get_door_status():
                lock_door()
            last_lock_time = current_time

        # Short sleep so we can exit quickly when stop_event is set
        stop_event.wait(0.1)

    logger.info("Button monitoring thread exiting")


# RFID reading and authentication logic
from typing import Tuple

def _check_uid_from_sources(uid_hex: str) -> Tuple[bool, str]:
    """Helper to check UID against Google Sheets or local CSV. Returns (access_granted, source)."""
    try:
        if check_local_csv(uid_hex):
            return True, "Local CSV"
        return False, "Local CSV"
    except Exception as e:
        logger.warning(f"Local CSV lookup failed: {e}")

    try:
        if data_client.is_connected() and data_client.check_uid_in_sheet(uid_hex):
            return True, "Google Sheets"
        return False, "Google Sheets"
    except Exception as e:
        logger.warning(f"Google Sheets lookup failed: {e}")
        return False, "Google Sheets"


def check_rfid(stop_event: threading.Event):
    """Monitor PN532 RFID reader and authenticate badges."""
    logger.info("RFID monitoring thread started")

    while not stop_event.is_set():
        try:
            # Read the UID from the RFID card
            uid = pn532.read_passive_target(timeout=0.1)

            if uid:
                # Convert the UID to a hex string
                uid_hex = ''.join(format(x, '02X') for x in uid).lower()
                logger.info(f"Card scanned with UID: {uid_hex}")
                update_pn532_success()

                # Check sources for access
                access_granted, source = _check_uid_from_sources(uid_hex)

                # Process access decision
                if access_granted:
                    logger.info(f"Access GRANTED for {uid_hex} from {source}")
                    record_action("Badge Scan", uid_hex, "Granted")

                    # Unlock door temporarily if not already unlocked
                    if not get_door_status():
                        # Pass badge UID through so actions are attributed to this badge
                        door_controller.unlock_temporarily(config["DOOR_UNLOCK_BADGE_DURATION"], badge_id=uid_hex)

                    # Log to Google Sheets (best effort)
                    data_client.log_access(uid_hex, "Granted")
                else:
                    logger.warning(f"Access DENIED for {uid_hex}")
                    record_action("Badge Scan", uid_hex, "Denied")

                    # Log to Google Sheets (best effort)
                    data_client.log_access(uid_hex, "Denied")

                # Prevent multiple immediate reads but allow early exit on stop
                stop_event.wait(1)
            else:
                # Short delay to avoid busy loop, but wake on stop
                stop_event.wait(0.1)

        except Exception as e:
            logger.error(f"PN532 error in main loop: {e}")
            log_pn532_error(e)
            update_pn532_error(str(e))
            stop_event.wait(1)  # Back off on error and allow shutdown


def main():
    """Main application entry point."""
    try:
        logger.info("Starting health server...")
        # Use global start/stop helpers for the health server
        start_health_server()

        logger.info("Starting watchdog...")
        start_watchdog()

        logger.info("Starting worker threads...")
        # Create separate threads for button monitoring and RFID checking
        button_thread = threading.Thread(target=monitor_buttons, args=(stop_event,), daemon=False, name="ButtonMonitor")
        rfid_thread = threading.Thread(target=check_rfid, args=(stop_event,), daemon=False, name="RFIDMonitor")
        refresh_thread = threading.Thread(target=_schedule_daily_badge_refresh, args=(stop_event,), daemon=False, name="BadgeRefresh")

        # Start both threads
        button_thread.start()
        rfid_thread.start()
        refresh_thread.start()

        logger.info("All systems operational")
        logger.info(f"Health page available at http://127.0.0.1:{config['HEALTH_SERVER_PORT']}/health")
        logger.info(f"Health page credentials: {config['HEALTH_SERVER_USERNAME']} / {config['HEALTH_SERVER_PASSWORD']}")

        # Wait for both threads to finish (they won't in normal operation)
        while not stop_event.is_set():
            try:
                # Sleep briefly to keep main responsive to signals
                time.sleep(0.5)
            except KeyboardInterrupt:
                logger.info("Keyboard interrupt received, shutting down...")
                stop_event.set()

    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received, shutting down...")
        stop_event.set()

    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        stop_event.set()
        sys.exit(1)

    finally:
        # Trigger shutdown of components
        stop_event.set()
        logger.info("Stopping health server and watchdog...")
        try:
            # Stop global health server helper
            stop_health_server()
        except Exception:
            pass

        try:
            stop_watchdog()
        except Exception:
            pass

        # Join worker threads with timeout to avoid hanging
        logger.info("Waiting for worker threads to exit...")
        try:
            button_thread.join(timeout=3)
            rfid_thread.join(timeout=3)
            refresh_thread.join(timeout=3)
        except Exception:
            pass

        logger.info("Cleaning up GPIO...")
        try:
            GPIO.cleanup()
        except Exception:
            pass

        logger.info("Door Controller stopped")


if __name__ == "__main__":
    main()

