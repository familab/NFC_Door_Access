"""Unit tests for door control module."""
import unittest
from unittest.mock import Mock, MagicMock, patch
import threading
import time
from datetime import datetime
import lib.door_control as door_control

# Badge id used in unit tests for logable actions
UNIT_TEST_BADGE = 'unit_test'

class MockGPIO:
    """Mock GPIO module for testing."""
    HIGH = 1
    LOW = 0

    def __init__(self):
        self.outputs = {}

    def output(self, pin, value):
        self.outputs[pin] = value


class TestDoorStatus(unittest.TestCase):
    """Test cases for door status tracking."""

    def setUp(self):
        """Reset door status before each test."""
        door_control._door_is_open = False
        door_control._door_status_updated = datetime.now()

    def test_set_door_status(self):
        """Test setting door status (include badge id in logs)."""
        door_control.set_door_status(True, badge_id=UNIT_TEST_BADGE)
        self.assertTrue(door_control.get_door_status())

        door_control.set_door_status(False, badge_id=UNIT_TEST_BADGE)
        self.assertFalse(door_control.get_door_status())

    def test_get_door_status_updated(self):
        """Test getting door status update timestamp."""
        before = datetime.now()
        time.sleep(0.01)
        door_control.set_door_status(True, badge_id=UNIT_TEST_BADGE)
        updated = door_control.get_door_status_updated()

        self.assertGreater(updated, before)

    def test_thread_safety(self):
        """Test that door status operations are thread-safe."""
        results = []

        def toggle_status():
            for _ in range(100):
                door_control.set_door_status(True, badge_id=UNIT_TEST_BADGE)
                door_control.set_door_status(False, badge_id=UNIT_TEST_BADGE)
                results.append(door_control.get_door_status())

        threads = [threading.Thread(target=toggle_status) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should complete without errors
        self.assertEqual(len(results), 500)

    def test_set_door_status_passes_badge_id(self):
        """Ensure set_door_status forwards badge_id to record_action when provided."""
        with patch('lib.door_control.record_action') as mock_record:
            door_control.set_door_status(True, badge_id='ABC123')
            mock_record.assert_called_with('Door OPEN/UNLOCKED', 'ABC123')
            mock_record.reset_mock()

            door_control.set_door_status(False, badge_id=9876)
            mock_record.assert_called_with('Door CLOSED/LOCKED', '9876')


class TestDoorController(unittest.TestCase):
    """Test cases for DoorController class."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_gpio = MockGPIO()
        self.gpio_lock = threading.Lock()
        self.relay_pin = 17

        # Reset door status
        door_control._door_is_open = False

        # Patch logger
        self.logger_patcher = patch('lib.door_control.get_logger')
        self.mock_logger = self.logger_patcher.start()
        self.mock_logger.return_value = Mock()

        self.controller = door_control.DoorController(
            self.mock_gpio,
            self.relay_pin,
            self.gpio_lock
        )

    def tearDown(self):
        """Clean up test fixtures."""
        self.logger_patcher.stop()
        # Cancel any pending timers
        if self.controller.unlock_timer:
            self.controller.unlock_timer.cancel()

    def test_unlock_door(self):
        """Test unlocking the door (include badge id in logs)."""
        self.controller.unlock_door(duration=1, badge_id=UNIT_TEST_BADGE)

        # Check GPIO was set HIGH
        self.assertEqual(self.mock_gpio.outputs[self.relay_pin], MockGPIO.HIGH)

        # Check status was updated
        self.assertTrue(door_control.get_door_status())

        # Check timer was set
        self.assertIsNotNone(self.controller.unlock_timer)
        self.assertTrue(self.controller.unlock_timer.is_alive())

        # Clean up timer
        self.controller.unlock_timer.cancel()

    def test_lock_door(self):
        """Test locking the door."""
        # First unlock
        door_control.set_door_status(True, badge_id=UNIT_TEST_BADGE)
        self.mock_gpio.outputs[self.relay_pin] = MockGPIO.HIGH

        # Then lock
        self.controller.lock_door(badge_id=UNIT_TEST_BADGE)

        # Check GPIO was set LOW
        self.assertEqual(self.mock_gpio.outputs[self.relay_pin], MockGPIO.LOW)

        # Check status was updated
        self.assertFalse(door_control.get_door_status())

    def test_unlock_temporarily(self):
        """Test temporary unlock (include badge id in logs)."""
        initial_status = door_control.get_door_status()

        self.controller.unlock_temporarily(duration=1, badge_id=UNIT_TEST_BADGE)

        # Check door was unlocked
        self.assertEqual(self.mock_gpio.outputs[self.relay_pin], MockGPIO.HIGH)
        self.assertTrue(door_control.get_door_status())

        # Wait for auto-lock
        time.sleep(1.2)

        # Door should be locked again
        self.assertEqual(self.mock_gpio.outputs[self.relay_pin], MockGPIO.LOW)
        self.assertFalse(door_control.get_door_status())

    def test_unlock_temporarily_passes_badge_id(self):
        """Ensure temporary unlock attributes open/close actions to the badge."""
        with patch('lib.door_control.record_action') as mock_record:
            self.controller.unlock_temporarily(duration=0.1, badge_id='abc123')
            # Opening should be recorded immediately
            mock_record.assert_any_call('Door OPEN/UNLOCKED', 'abc123')

            # Wait for auto-lock and verify closing was recorded with same badge id
            time.sleep(0.25)
            mock_record.assert_any_call('Door CLOSED/LOCKED', 'abc123')

    def test_unlock_door_already_unlocked(self):
        """Test unlocking when already unlocked."""
        # First unlock
        self.controller.unlock_door(duration=10, badge_id=UNIT_TEST_BADGE)
        initial_timer = self.controller.unlock_timer

        # Try to unlock again
        self.controller.unlock_door(duration=10, badge_id=UNIT_TEST_BADGE)

        # Original timer should be cancelled
        self.assertIsNot(self.controller.unlock_timer, initial_timer)

        # Clean up
        self.controller.unlock_timer.cancel()

    def test_lock_door_cancels_timer(self):
        """Test that locking cancels unlock timer (include badge id in logs)."""
        self.controller.unlock_door(duration=10, badge_id=UNIT_TEST_BADGE)
        self.assertTrue(self.controller.unlock_timer.is_alive())

        self.controller.lock_door(badge_id=UNIT_TEST_BADGE)

        # Timer should be cancelled
        self.assertIsNone(self.controller.unlock_timer)


if __name__ == '__main__':
    unittest.main()
