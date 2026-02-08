"""Unit tests for logging utilities module."""
import unittest
import tempfile
import os
import logging
from datetime import datetime
from unittest.mock import patch
import lib.logging_utils as logging_utils


class TestLoggingUtils(unittest.TestCase):
    """Test cases for logging utilities."""

    def setUp(self):
        """Set up test fixtures."""
        # Reset global logger
        logging_utils.logger = None
        logging_utils.last_google_log_success = None
        logging_utils.last_badge_download = None
        logging_utils.last_google_error = None
        # Track temp files for cleanup after handlers are closed
        self._temp_files = []

    def test_setup_logger(self):
        """Test logger setup with rotating file handler."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            log_file = f.name

        try:
            logger = logging_utils.setup_logger(log_file)
            self.assertIsNotNone(logger)
            self.assertEqual(logger.name, "door_controller")
            self.assertEqual(logger.level, logging.INFO)

            # Verify we can log
            logger.info("Test message")

            # Check log file was created
            self.assertTrue(os.path.exists(log_file))
        finally:
            # Defer removal until handlers are closed in tearDown
            self._temp_files.append(log_file)

    def test_get_logger_singleton(self):
        """Test that get_logger returns singleton instance."""
        logger1 = logging_utils.get_logger()
        logger2 = logging_utils.get_logger()
        self.assertIs(logger1, logger2)

    def test_record_action(self):
        """Test recording actions to log."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            log_file = f.name

        try:
            logging_utils.setup_logger(log_file)

            # Record various actions
            logging_utils.record_action("Door Opened")
            logging_utils.record_action("Badge Scanned", "ABC123", "Granted")
            logging_utils.record_action("Invalid Badge", "XYZ789", "Denied")

            # Read log file
            with open(log_file, 'r') as f:
                log_contents = f.read()

            self.assertIn("Door Opened", log_contents)
            self.assertIn("ABC123", log_contents)
            self.assertIn("Granted", log_contents)
            self.assertIn("XYZ789", log_contents)
            self.assertIn("Denied", log_contents)
        finally:
            # Defer removal until handlers are closed in tearDown
            self._temp_files.append(log_file)

    def test_update_last_google_error(self):
        """Test updating last Google Sheets error message."""
        logging_utils.update_last_google_error("Connection error")
        last_error = logging_utils.get_last_google_error()
        self.assertEqual(last_error, "Connection error")

    def test_update_timestamps(self):
        """Test timestamp update functions."""
        # Test Google log success
        logging_utils.update_last_google_log_success()
        timestamp1 = logging_utils.get_last_google_log_success()
        self.assertIsNotNone(timestamp1)

        # Test badge download
        logging_utils.setup_logger()
        logging_utils.update_last_badge_download(success=True)
        timestamp2 = logging_utils.get_last_badge_download()
        self.assertIsNotNone(timestamp2)

    def tearDown(self):
        """Clean up logger handlers after each test to allow file deletion on Windows."""
        # Close and remove handlers to release file locks
        if logging_utils.logger:
            for h in logging_utils.logger.handlers[:]:
                try:
                    h.flush()
                    h.close()
                except Exception:
                    pass
                try:
                    logging_utils.logger.removeHandler(h)
                except Exception:
                    pass
            logging.shutdown()
            logging_utils.logger = None

        # Clean up temp files after handlers are closed
        for p in getattr(self, '_temp_files', []):
            try:
                if os.path.exists(p):
                    os.unlink(p)
            except Exception:
                pass

    def test_get_log_file_size(self):
        """Test getting log file size."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"Test data" * 100)
            log_file = f.name

        try:
            with patch('lib.logging_utils.config', {"LOG_FILE": log_file}):
                size = logging_utils.get_log_file_size()
                self.assertGreater(size, 0)
        finally:
            if os.path.exists(log_file):
                os.unlink(log_file)

    def test_log_pn532_error(self):
        """Test PN532 error logging."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            log_file = f.name

        try:
            logging_utils.setup_logger(log_file)

            test_error = Exception("PN532 read failed")
            logging_utils.log_pn532_error(test_error)

            with open(log_file, 'r') as f:
                log_contents = f.read()

            self.assertIn("PN532 Error", log_contents)
            self.assertIn("PN532 read failed", log_contents)
        finally:
            # Defer removal until handlers are closed in tearDown
            self._temp_files.append(log_file)


if __name__ == '__main__':
    unittest.main()
