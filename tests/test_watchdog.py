"""Unit tests for watchdog module."""
import unittest
from unittest.mock import Mock, patch, mock_open
import time
import os
import tempfile
import lib.watchdog as watchdog


class TestWatchdog(unittest.TestCase):
    """Test cases for Watchdog class."""

    def setUp(self):
        """Set up test fixtures."""
        # Reset global watchdog
        watchdog._watchdog = None

        # Create temp file for heartbeat
        self.temp_file = tempfile.NamedTemporaryFile(delete=False)
        self.heartbeat_file = self.temp_file.name
        self.temp_file.close()

        # Patch the provider used by Watchdog (patch the symbol in watchdog module)
        self.logger_patcher = patch('lib.watchdog.get_watchdog_logger')
        self.mock_logger = self.logger_patcher.start()
        self.mock_logger.return_value = Mock()

    def tearDown(self):
        """Clean up test fixtures."""
        self.logger_patcher.stop()

        # Clean up temp file
        if os.path.exists(self.heartbeat_file):
            os.unlink(self.heartbeat_file)

    def test_update_watchdog_heartbeat(self):
        """Test updating watchdog heartbeat file."""
        wd = watchdog.Watchdog(self.heartbeat_file)
        wd.update_watchdog_heartbeat()

        # Check file was written
        self.assertTrue(os.path.exists(self.heartbeat_file))

        # Check content is ISO format timestamp
        with open(self.heartbeat_file, 'r') as f:
            content = f.read()

        self.assertIn('T', content)  # ISO format contains 'T'
        self.assertIn(':', content)  # Time contains colons

    def test_watchdog_start_stop(self):
        """Test starting and stopping watchdog."""
        wd = watchdog.Watchdog(self.heartbeat_file, interval=1)

        # Start watchdog
        wd.start()
        self.assertTrue(wd.running)
        self.assertIsNotNone(wd.thread)
        self.assertTrue(wd.thread.is_alive())

        # Wait for at least one heartbeat
        time.sleep(1.5)

        # Check heartbeat file was updated
        self.assertTrue(os.path.exists(self.heartbeat_file))

        # Stop watchdog
        wd.stop()
        self.assertFalse(wd.running)

    def test_watchdog_multiple_heartbeats(self):
        """Test that watchdog updates heartbeat multiple times."""
        wd = watchdog.Watchdog(self.heartbeat_file, interval=0.5)
        wd.start()

        # Read initial timestamp
        time.sleep(0.6)
        with open(self.heartbeat_file, 'r') as f:
            timestamp1 = f.read()

        # Wait for another heartbeat
        time.sleep(0.6)
        with open(self.heartbeat_file, 'r') as f:
            timestamp2 = f.read()

        # Timestamps should be different
        self.assertNotEqual(timestamp1, timestamp2)

        wd.stop()

    def test_watchdog_already_running(self):
        """Test starting watchdog when already running."""
        wd = watchdog.Watchdog(self.heartbeat_file)
        wd.start()

        # Try to start again
        wd.start()

        # Should log warning
        self.mock_logger.return_value.warning.assert_called()

        wd.stop()

    def test_global_watchdog_functions(self):
        """Test global watchdog management functions."""
        # Start global watchdog
        watchdog.start_watchdog(self.heartbeat_file, interval=1)

        self.assertIsNotNone(watchdog._watchdog)
        self.assertTrue(watchdog._watchdog.running)

        # Manual update
        watchdog.update_watchdog_heartbeat()
        self.assertTrue(os.path.exists(self.heartbeat_file))

        # Stop global watchdog
        watchdog.stop_watchdog()
        self.assertFalse(watchdog._watchdog.running)

    def test_watchdog_error_handling(self):
        """Test watchdog handles file write errors gracefully."""
        # Use invalid path
        wd = watchdog.Watchdog("/invalid/path/file.txt")

        # Should not raise exception
        wd.update_watchdog_heartbeat()

        # Should log error
        self.mock_logger.return_value.error.assert_called()


if __name__ == '__main__':
    unittest.main()
