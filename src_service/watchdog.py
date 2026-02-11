"""Systemd watchdog heartbeat functionality."""
import time
from datetime import datetime
import threading
from typing import Optional

from .config import config
from .logging_utils import get_watchdog_logger


class Watchdog:
    """Systemd watchdog heartbeat manager."""

    def __init__(self, heartbeat_file: Optional[str] = None, interval: int = 10):
        """
        Initialize the watchdog.

        Args:
            heartbeat_file: Path to watchdog heartbeat file. If None, uses config default.
            interval: Heartbeat interval in seconds (default: 10)
        """
        self.heartbeat_file = heartbeat_file or config["WATCHDOG_FILE"]
        self.interval = interval
        self.running = False
        self.thread = None
        self.logger = get_watchdog_logger()

    def update_watchdog_heartbeat(self):
        """Write current timestamp to watchdog file."""
        try:
            with open(self.heartbeat_file, 'w') as f:
                timestamp = datetime.now().isoformat()
                f.write(timestamp)
            self.logger.debug(f"Watchdog heartbeat updated: {timestamp}")
        except Exception as e:
            self.logger.error(f"Failed to update watchdog heartbeat: {e}")

    def _heartbeat_loop(self):
        """Background loop for periodic heartbeat updates."""
        self.logger.info(f"Watchdog heartbeat loop started (interval: {self.interval}s)")

        while self.running:
            self.update_watchdog_heartbeat()
            time.sleep(self.interval)

        self.logger.info("Watchdog heartbeat loop stopped")

    def start(self):
        """Start the watchdog heartbeat in a background daemon thread."""
        if self.running:
            self.logger.warning("Watchdog already running")
            return

        self.running = True
        self.thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self.thread.start()
        self.logger.info("Watchdog started")

    def stop(self):
        """Stop the watchdog heartbeat."""
        if not self.running:
            return

        self.running = False
        if self.thread:
            self.thread.join(timeout=self.interval + 1)
        self.logger.info("Watchdog stopped")


# Global watchdog instance
_watchdog = None


def start_watchdog(heartbeat_file: Optional[str] = None, interval: int = 10):
    """
    Start the global watchdog instance.

    Args:
        heartbeat_file: Path to watchdog heartbeat file
        interval: Heartbeat interval in seconds
    """
    global _watchdog

    if _watchdog is None:
        _watchdog = Watchdog(heartbeat_file, interval)

    _watchdog.start()


def stop_watchdog():
    """Stop the global watchdog instance."""
    global _watchdog

    if _watchdog:
        _watchdog.stop()


def update_watchdog_heartbeat():
    """
    Update the watchdog heartbeat manually.
    This can be called from the main application loop.
    """
    global _watchdog

    if _watchdog:
        _watchdog.update_watchdog_heartbeat()
