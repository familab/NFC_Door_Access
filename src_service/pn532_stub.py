"""PN532 stub for development when hardware libraries are unavailable.
"""
import time

class PN532Stub:
    """Minimal PN532-like interface used by the application."""

    def __init__(self, *args, **kwargs):
        # Optionally could simulate reads from a file or env in future
        self._last_activity = time.time()

    def SAM_configuration(self):
        # No-op
        return

    def read_passive_target(self, timeout=0.1):
        # Always return None (no card). Developers can extend this to
        # simulate card reads by patching this method in tests or using
        # environment driven behavior.
        time.sleep(timeout)
        return None
