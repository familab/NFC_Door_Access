"""Unit tests for logging utilities module."""
import unittest
import tempfile
import os
import logging
from datetime import datetime
from unittest.mock import patch
from src_service.config import config
import src_service.logging_utils as logging_utils


class TestLoggingUtils(unittest.TestCase):
    """Test cases for logging utilities."""

    def setUp(self):
        """Set up test fixtures."""
        # Reset global logger
        logging_utils.logger = None
        logging_utils.last_google_log_success = None
        logging_utils.last_badge_download = None
        logging_utils.last_google_error = None
        logging_utils.last_data_connection = None
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

            # Record various actions (include unit_test badge id for tests)
            logging_utils.record_action("Door Opened", "unit_test", "Success")
            logging_utils.record_action("Badge Scanned", "ABC123", "Granted")
            logging_utils.record_action("Invalid Badge", "XYZ789", "Denied")

            # Read log file
            with open(log_file, 'r') as f:
                log_contents = f.read()

            self.assertIn("Door Opened", log_contents)
            self.assertIn("unit_test", log_contents)
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

        # Test data connection
        logging_utils.update_last_data_connection()
        timestamp_data = logging_utils.get_last_data_connection()
        self.assertIsNotNone(timestamp_data)

        # Test badge download
        logging_utils.setup_logger()
        logging_utils.update_last_badge_download(success=True)
        timestamp2 = logging_utils.get_last_badge_download()
        self.assertIsNotNone(timestamp2)

    def tearDown(self):
        """Clean up logger handlers after each test to allow file deletion on Windows."""
        # Close and remove handlers to release file locks for main logger
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

        # Also close action and watchdog logger handlers if present
        if getattr(logging_utils, 'action_logger', None):
            for h in logging_utils.action_logger.handlers[:]:
                try:
                    h.flush()
                    h.close()
                except Exception:
                    pass
                try:
                    logging_utils.action_logger.removeHandler(h)
                except Exception:
                    pass
            logging_utils.action_logger = None

        if getattr(logging_utils, 'watchdog_logger', None):
            for h in logging_utils.watchdog_logger.handlers[:]:
                try:
                    h.flush()
                    h.close()
                except Exception:
                    pass
                try:
                    logging_utils.watchdog_logger.removeHandler(h)
                except Exception:
                    pass
            logging_utils.watchdog_logger = None

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
            with patch('src_service.logging_utils.config', {"LOG_FILE": log_file}):
                size = logging_utils.get_log_file_size()
                self.assertGreater(size, 0)
        finally:
            if os.path.exists(log_file):
                os.unlink(log_file)

    def test_get_log_file_size_cache(self):
        """Ensure get_log_file_size caches results and refreshes after expiry."""
        import os
        from datetime import datetime, timedelta

        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"A" * 100)
            log_file = f.name

        try:
            with patch('src_service.logging_utils.config', {"LOG_FILE": log_file, "HEALTH_CACHE_DURATION_MINUTES": 5}):
                size1 = logging_utils.get_log_file_size()
                self.assertGreater(size1, 0)

                # Shrink the file on disk
                with open(log_file, 'wb') as f2:
                    f2.write(b"B" * 10)

                # Immediate call should return cached (old) size
                size2 = logging_utils.get_log_file_size()
                self.assertEqual(size1, size2)

                # Expire cache and verify fresh value is returned
                logging_utils._log_size_cache['modified'] = datetime.now() - timedelta(minutes=10)
                size3 = logging_utils.get_log_file_size()
                self.assertNotEqual(size1, size3)
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

    def test_action_logger_file_created(self):
        """Test that record_action writes to action-specific dated file."""
        import tempfile
        from datetime import datetime

        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = os.path.join(tmpdir, "door_controller.txt")
            # Ensure config points to the test log directory so derived files are created there
            config.config["LOG_FILE"] = log_file
            config.config["ACTION_LOG_FILE"] = None
            config.config["LOG_RETENTION_DAYS"] = 7

            logging_utils.setup_logger(log_file)

            # Force recreation of action logger to pick up derived path
            logging_utils.action_logger = None
            # Remove any existing handlers on the named logger to ensure a fresh handler is created
            import logging as _logging
            existing = _logging.getLogger('door_action')
            for h in existing.handlers[:]:
                try:
                    h.flush()
                    h.close()
                except Exception:
                    pass
                try:
                    existing.removeHandler(h)
                except Exception:
                    pass

            act_logger = logging_utils.get_action_logger()

            logging_utils.record_action("Door Opened", "ABC123", "Success")

            expected = os.path.join(tmpdir, f"door_controller_action-{datetime.now():%Y-%m-%d}.txt")

            handler_paths = [getattr(h, 'baseFilename', None) for h in act_logger.handlers]
            # Ensure we created a handler that writes to the expected path
            self.assertTrue(any(p and os.path.abspath(p) == os.path.abspath(expected) for p in handler_paths),
                            msg=f"Expected handler writing to {expected}, handlers: {handler_paths}, dir: {os.listdir(tmpdir)}")

            for h in act_logger.handlers:
                try:
                    h.flush()
                except Exception:
                    pass

            # Now the file should exist and contain our message
            self.assertTrue(os.path.exists(expected))
            with open(expected, 'r', encoding='utf-8') as f:
                contents = f.read()
            self.assertIn("Door Opened", contents)

            # Close and remove action logger handlers so TemporaryDirectory cleanup can remove files on Windows
            for h in act_logger.handlers[:]:
                try:
                    h.flush()
                    h.close()
                except Exception:
                    pass
                try:
                    act_logger.removeHandler(h)
                except Exception:
                    pass
            logging_utils.action_logger = None

            # Close main logger handlers for this test log file as well
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
                logging_utils.logger = None

            # Defer cleanup (if anything remains)
            self._temp_files.append(expected)
    def test_cleanup_old_logs_removes_derived_files(self):
        """Test cleanup removes base, action, and watchdog dated files older than retention."""
        import tempfile
        from datetime import date, timedelta

        with tempfile.TemporaryDirectory() as tmpdir:
            base = os.path.join(tmpdir, "door_controller")
            old_date = date.today() - timedelta(days=10)
            names = [
                f"{os.path.basename(base)}-{old_date:%Y-%m-%d}.txt",
                f"{os.path.basename(base)}_action-{old_date:%Y-%m-%d}.txt",
                f"{os.path.basename(base)}_watchdog-{old_date:%Y-%m-%d}.txt",
            ]
            for n in names:
                with open(os.path.join(tmpdir, n), 'w', encoding='utf-8') as f:
                    f.write('old')

            recent_name = f"{os.path.basename(base)}-{date.today():%Y-%m-%d}.txt"
            with open(os.path.join(tmpdir, recent_name), 'w', encoding='utf-8') as f:
                f.write('recent')

            config.config["LOG_FILE"] = os.path.join(tmpdir, "door_controller.txt")
            config.config["LOG_RETENTION_DAYS"] = 7

            # Act
            logging_utils.cleanup_old_logs(retention_days=7)

            # Assert old removed, recent remains
            for n in names:
                self.assertFalse(os.path.exists(os.path.join(tmpdir, n)))
            self.assertTrue(os.path.exists(os.path.join(tmpdir, recent_name)))

    def test_watchdog_logger_file_created(self):
        """Test that watchdog logger creates a dated file and writes messages."""
        import tempfile
        from datetime import datetime

        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = os.path.join(tmpdir, "door_controller.txt")
            config.config["LOG_FILE"] = log_file
            config.config["WATCHDOG_LOG_FILE"] = None
            config.config["LOG_RETENTION_DAYS"] = 7

            logging_utils.setup_logger(log_file)
            # Force recreation
            logging_utils.watchdog_logger = None
            import logging as _logging
            existing = _logging.getLogger('watchdog')
            for h in existing.handlers[:]:
                try:
                    h.flush()
                    h.close()
                except Exception:
                    pass
                try:
                    existing.removeHandler(h)
                except Exception:
                    pass

            wd_logger = logging_utils.get_watchdog_logger()
            wd_logger.info("heartbeat")

            expected = os.path.join(tmpdir, f"door_controller_watchdog-{datetime.now():%Y-%m-%d}.txt")
            handler_paths = [getattr(h, 'baseFilename', None) for h in wd_logger.handlers]
            self.assertTrue(any(p and os.path.abspath(p) == os.path.abspath(expected) for p in handler_paths))

            for h in wd_logger.handlers:
                try:
                    h.flush()
                except Exception:
                    pass

            self.assertTrue(os.path.exists(expected))
            with open(expected, 'r', encoding='utf-8') as f:
                contents = f.read()
            self.assertIn("heartbeat", contents)

            # cleanup handlers to avoid file locks
            for h in wd_logger.handlers[:]:
                try:
                    h.flush(); h.close()
                except Exception:
                    pass
                try:
                    wd_logger.removeHandler(h)
                except Exception:
                    pass
            logging_utils.watchdog_logger = None

            # Close main logger handlers for this test log file as well
            if logging_utils.logger:
                for h in logging_utils.logger.handlers[:]:
                    try:
                        h.flush(); h.close()
                    except Exception:
                        pass
                    try:
                        logging_utils.logger.removeHandler(h)
                    except Exception:
                        pass
                logging_utils.logger = None

            # Defer cleanup (if anything remains)
            self._temp_files.append(expected)
            self._temp_files.append(log_file)

    def test_config_overrides_create_custom_files(self):
        """Test explicit ACTION_LOG_FILE and WATCHDOG_LOG_FILE in config are used."""
        import tempfile
        from datetime import datetime

        with tempfile.TemporaryDirectory() as tmpdir:
            action_base = os.path.join(tmpdir, "custom_action.txt")
            watchdog_base = os.path.join(tmpdir, "custom_watchdog.txt")

            config.config["ACTION_LOG_FILE"] = action_base
            config.config["WATCHDOG_LOG_FILE"] = watchdog_base
            config.config["LOG_RETENTION_DAYS"] = 7

            # Reset and create loggers
            logging_utils.action_logger = None
            logging_utils.watchdog_logger = None

            # Remove existing named loggers handlers
            import logging as _logging
            for name in ("door_action", "watchdog"):
                existing = _logging.getLogger(name)
                for h in existing.handlers[:]:
                    try:
                        h.flush(); h.close()
                    except Exception:
                        pass
                    try:
                        existing.removeHandler(h)
                    except Exception:
                        pass

            act_logger = logging_utils.get_action_logger()
            wd_logger = logging_utils.get_watchdog_logger()

            act_logger.info("act message")
            wd_logger.info("wd message")

            expected_act = os.path.join(tmpdir, f"custom_action-{datetime.now():%Y-%m-%d}.txt")
            expected_wd = os.path.join(tmpdir, f"custom_watchdog-{datetime.now():%Y-%m-%d}.txt")

            for h in act_logger.handlers:
                try:
                    h.flush()
                except Exception:
                    pass
            for h in wd_logger.handlers:
                try:
                    h.flush()
                except Exception:
                    pass

            self.assertTrue(os.path.exists(expected_act))
            self.assertTrue(os.path.exists(expected_wd))

            with open(expected_act, 'r', encoding='utf-8') as f:
                self.assertIn("act message", f.read())
            with open(expected_wd, 'r', encoding='utf-8') as f:
                self.assertIn("wd message", f.read())

            # cleanup
            for h in act_logger.handlers[:]:
                try:
                    h.flush(); h.close()
                except Exception:
                    pass
                try:
                    act_logger.removeHandler(h)
                except Exception:
                    pass
            logging_utils.action_logger = None

            for h in wd_logger.handlers[:]:
                try:
                    h.flush(); h.close()
                except Exception:
                    pass
                try:
                    wd_logger.removeHandler(h)
                except Exception:
                    pass
            logging_utils.watchdog_logger = None

            self._temp_files.extend([expected_act, expected_wd])

    def test_retention_honored_by_cleanup(self):
        """Test that cleanup respects LOG_RETENTION_DAYS setting."""
        import tempfile
        from datetime import date, timedelta

        with tempfile.TemporaryDirectory() as tmpdir:
            base = os.path.join(tmpdir, "door_controller")
            old_date = date.today() - timedelta(days=3)
            names = [
                f"{os.path.basename(base)}-{old_date:%Y-%m-%d}.txt",
                f"{os.path.basename(base)}_action-{old_date:%Y-%m-%d}.txt",
                f"{os.path.basename(base)}_watchdog-{old_date:%Y-%m-%d}.txt",
            ]
            for n in names:
                with open(os.path.join(tmpdir, n), 'w', encoding='utf-8') as f:
                    f.write('old')

            config.config["LOG_FILE"] = os.path.join(tmpdir, "door_controller.txt")
            config.config["LOG_RETENTION_DAYS"] = 2

            logging_utils.cleanup_old_logs()

            for n in names:
                self.assertFalse(os.path.exists(os.path.join(tmpdir, n)))

    def test_cleanup_ingests_action_log_before_delete(self):
        """Cleanup should ingest old action logs before deletion."""
        import tempfile
        from datetime import date, timedelta

        with tempfile.TemporaryDirectory() as tmpdir:
            old_date = date.today() - timedelta(days=10)
            action_name = f"door_controller_action-{old_date:%Y-%m-%d}.txt"
            action_path = os.path.join(tmpdir, action_name)
            with open(action_path, "w", encoding="utf-8") as handle:
                handle.write("2026-02-08 12:00:00 - door_action - INFO - Manual Lock - Status: Success\n")

            config.config["LOG_FILE"] = os.path.join(tmpdir, "door_controller.txt")
            config.config["LOG_RETENTION_DAYS"] = 7
            with patch("src_service.logging_utils.ingest_action_log_file") as ingest_mock:
                logging_utils.cleanup_old_logs(retention_days=7)
                ingest_mock.assert_called_once_with(action_path)
            self.assertFalse(os.path.exists(action_path))


if __name__ == '__main__':
    unittest.main()
