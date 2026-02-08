"""Door control module with thread-safe status tracking."""
import threading
from datetime import datetime
from typing import Optional

from .config import config
from .logging_utils import get_logger, record_action

# Global door state
_door_status_lock = threading.Lock()
_door_is_open = False
_door_status_updated = datetime.now()


def set_door_status(is_open: bool):
    """
    Set the door status in a thread-safe manner.

    Args:
        is_open: True if door is open/unlocked, False if closed/locked
    """
    global _door_is_open, _door_status_updated

    with _door_status_lock:
        previous_status = _door_is_open
        _door_is_open = is_open
        _door_status_updated = datetime.now()

        # Log status change
        if previous_status != is_open:
            status_str = "OPEN/UNLOCKED" if is_open else "CLOSED/LOCKED"
            get_logger().info(f"Door status changed to: {status_str}")
            record_action(f"Door {status_str}")


def get_door_status() -> bool:
    """
    Get the current door status in a thread-safe manner.

    Returns:
        True if door is open/unlocked, False if closed/locked
    """
    with _door_status_lock:
        return _door_is_open


def get_door_status_updated() -> datetime:
    """
    Get the timestamp when door status was last updated.

    Returns:
        Datetime of last status update
    """
    with _door_status_lock:
        return _door_status_updated


class DoorController:
    """
    Door controller class that manages GPIO and door state.
    This class wraps the existing GPIO logic with enhanced status tracking.
    """

    def __init__(self, gpio_module, relay_pin: int, gpio_lock: threading.Lock):
        """
        Initialize the door controller.

        Args:
            gpio_module: The RPi.GPIO module
            relay_pin: GPIO pin number for the relay
            gpio_lock: Threading lock for GPIO operations
        """
        self.gpio = gpio_module
        self.relay_pin = relay_pin
        self.gpio_lock = gpio_lock
        self.unlock_timer = None
        self.logger = get_logger()

    def unlock_door(self, duration: Optional[int] = None):
        """
        Unlock the door for a specified duration.

        Args:
            duration: Unlock duration in seconds. If None, uses config default.
        """
        duration = duration or config["UNLOCK_DURATION"]

        with self.gpio_lock:
            currently_open = get_door_status()

            # If the door is currently closed, physically unlock it
            if not currently_open:
                self.gpio.output(self.relay_pin, self.gpio.HIGH)
                set_door_status(True)
                self.logger.info(f"Door unlocked for {duration} seconds")
            else:
                # Door already open - just refresh timer
                self.logger.info(f"Door already unlocked, refreshing timer to {duration} seconds")

            # Refresh unlock timer in all cases
            if self.unlock_timer is not None:
                try:
                    self.unlock_timer.cancel()
                except Exception:
                    pass

            self.unlock_timer = threading.Timer(duration, self.lock_door)
            self.unlock_timer.start()

    def lock_door(self):
        """Lock the door."""
        with self.gpio_lock:
            if self.unlock_timer is not None:
                self.unlock_timer.cancel()
                self.unlock_timer = None

            if get_door_status():  # Only lock if currently unlocked
                self.gpio.output(self.relay_pin, self.gpio.LOW)
                set_door_status(False)
                self.logger.info("Door locked")

    def unlock_temporarily(self, duration: int):
        """
        Unlock the door temporarily (e.g., for badge scan).

        Args:
            duration: Duration in seconds
        """
        with self.gpio_lock:
            previous_status = get_door_status()

            self.gpio.output(self.relay_pin, self.gpio.HIGH)
            set_door_status(True)
            self.logger.info(f"Door unlocked temporarily for {duration} seconds")

            # Use threading.Timer for non-blocking delay
            def relock():
                with self.gpio_lock:
                    # Only relock if we're not in a longer unlock period
                    if not (self.unlock_timer and self.unlock_timer.is_alive()):
                        self.gpio.output(self.relay_pin, self.gpio.LOW)
                        set_door_status(False)
                        self.logger.info("Door auto-locked after temporary unlock")

            timer = threading.Timer(duration, relock)
            timer.start()
