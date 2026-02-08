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
except ModuleNotFoundError:
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
    setup_logger,
    get_logger,
    record_action,
    log_to_google_sheets,
    update_last_badge_download,
    log_pn532_error
)
from lib.door_control import DoorController, set_door_status, get_door_status
from lib.health_server import HealthServer, update_pn532_success, update_pn532_error, set_badge_refresh_callback
from lib.watchdog import start_watchdog, stop_watchdog

# GPIO Pin Definitions (from config)
RELAY_PIN = config["RELAY_PIN"]
BUTTON_UNLOCK_PIN = config["BUTTON_UNLOCK_PIN"]
BUTTON_LOCK_PIN = config["BUTTON_LOCK_PIN"]

# Time for unlocking (from config)
UNLOCK_DURATION = config["UNLOCK_DURATION"]

# Local CSV backup file
CSV_FILE = config["CSV_FILE"]

# Initialize logging first
setup_logger()
logger = get_logger()

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

# Google Sheets Setup (lazy imports so start.py can run without these packages installed)
sheet = None
log_sheet = None
try:
    import gspread
    from oauth2client.service_account import ServiceAccountCredentials

    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(config["CREDS_FILE"], scope)
    client = gspread.authorize(creds)

    # RFID Sheets
    sheet = client.open(config["BADGE_SHEET_NAME"]).sheet1
    log_sheet = client.open(config["LOG_SHEET_NAME"]).sheet1

    logger.info("Google Sheets connection established")
    update_last_badge_download(success=True)
except ModuleNotFoundError as e:
    logger.warning(f"Google Sheets libraries not available: {e}. Continuing without Google Sheets.")
    sheet = None
    log_sheet = None
    update_last_badge_download(success=False)
except Exception as e:
    logger.warning(f"Failed to connect to Google Sheets: {e}")
    logger.warning("Will attempt to use local CSV fallback")
    sheet = None
    log_sheet = None
    update_last_badge_download(success=False)


# Register badge refresh callback so it can be invoked from the health page
from lib.health_server import set_badge_refresh_callback

def _refresh_badge_list():
    """Refresh badge list from Google Sheets and update local CSV backup.

    Returns:
        (success: bool, message: str)
    """
    try:
        if not sheet:
            logger.warning("Badge refresh requested but Google Sheets not connected")
            return False, "No Google Sheets connection"

        uids = [cell.strip() for cell in sheet.col_values(1) if cell]

        # Persist to local CSV fallback
        try:
            with open(CSV_FILE, 'w', newline='') as f:
                writer = csv.writer(f)
                for u in uids:
                    writer.writerow([u])
        except Exception as e:
            logger.warning(f"Failed to write local CSV fallback: {e}")

        update_last_badge_download(success=True)
        logger.info(f"Badge list refreshed: {len(uids)} entries")
        return True, f"{len(uids)} badges"
    except Exception as e:
        logger.exception("Badge refresh failed")
        update_last_badge_download(success=False)
        return False, str(e)

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


def unlock_door():
    """Unlock door for 1 hour using door controller."""
    door_controller.unlock_door(UNLOCK_DURATION)
    record_action("Manual Unlock (1 hour)")
    if log_sheet:
        log_to_google_sheets(log_sheet, "Manual Unlock (1 hour)", "Success")


def lock_door():
    """Lock door using door controller."""
    door_controller.lock_door()
    record_action("Manual Lock")
    if log_sheet:
        log_to_google_sheets(log_sheet, "Manual Lock", "Success")


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
    except FileNotFoundError:
        logger.error(f"Local CSV file '{CSV_FILE}' not found")
    except Exception as e:
        logger.error(f"Error reading local CSV: {e}")
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
    access_granted = False
    source = "unknown"

    try:
        if sheet:
            uids = [cell.lower() for cell in sheet.col_values(1)]
            if uid_hex in uids:
                access_granted = True
                source = "Google Sheets"
            update_last_badge_download(success=True)
    except Exception as e:
        # Any problem with Google Sheets falls back to CSV
        logger.warning(f"Google Sheets lookup failed: {e}")
        if check_local_csv(uid_hex):
            access_granted = True
            source = "Local CSV"

    return access_granted, source


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
                        door_controller.unlock_temporarily(config["DOOR_UNLOCK_BADGE_DURATION"])

                    # Log to Google Sheets (best effort)
                    if log_sheet:
                        log_to_google_sheets(log_sheet, uid_hex, "Granted")
                else:
                    logger.warning(f"Access DENIED for {uid_hex}")
                    record_action("Badge Scan", uid_hex, "Denied")

                    # Log to Google Sheets (best effort)
                    if log_sheet:
                        log_to_google_sheets(log_sheet, uid_hex, "Denied")

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
        health_server = HealthServer()
        health_server.start()

        logger.info("Starting watchdog...")
        start_watchdog()

        logger.info("Starting worker threads...")
        # Create separate threads for button monitoring and RFID checking
        button_thread = threading.Thread(target=monitor_buttons, args=(stop_event,), daemon=False, name="ButtonMonitor")
        rfid_thread = threading.Thread(target=check_rfid, args=(stop_event,), daemon=False, name="RFIDMonitor")

        # Start both threads
        button_thread.start()
        rfid_thread.start()

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
            if 'health_server' in locals() and health_server:
                health_server.stop()
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

