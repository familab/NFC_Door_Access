"""Unit tests for configuration module."""
import unittest
import os
import json
import tempfile
from lib.config import Config, DEFAULT_CONFIG


class TestConfig(unittest.TestCase):
    """Test cases for Config class."""

    def test_default_config(self):
        """Test that default configuration values are loaded."""
        config = Config()
        self.assertEqual(config["RELAY_PIN"], 17)
        self.assertEqual(config["UNLOCK_DURATION"], 3600)
        self.assertEqual(config["HEALTH_SERVER_PORT"], 8080)

    def test_config_file_override(self):
        """Test that config file overrides defaults."""
        # Create temporary config file
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            test_config = {"RELAY_PIN": 99, "UNLOCK_DURATION": 7200}
            json.dump(test_config, f)
            config_file = f.name

        try:
            config = Config(config_file)
            self.assertEqual(config["RELAY_PIN"], 99)
            self.assertEqual(config["UNLOCK_DURATION"], 7200)
            # Check that non-overridden values still use defaults
            self.assertEqual(config["HEALTH_SERVER_PORT"], 8080)
        finally:
            os.unlink(config_file)

    def test_environment_variable_override(self):
        """Test that environment variables override config."""
        os.environ["DOOR_RELAY_PIN"] = "42"
        os.environ["DOOR_HEALTH_PORT"] = "9090"

        try:
            config = Config()
            self.assertEqual(config["RELAY_PIN"], 42)
            self.assertEqual(config["HEALTH_SERVER_PORT"], 9090)
        finally:
            del os.environ["DOOR_RELAY_PIN"]
            del os.environ["DOOR_HEALTH_PORT"]

    def test_get_method(self):
        """Test the get method with default values."""
        config = Config()
        self.assertEqual(config.get("RELAY_PIN"), 17)
        self.assertIsNone(config.get("NONEXISTENT_KEY"))
        self.assertEqual(config.get("NONEXISTENT_KEY", "default"), "default")


if __name__ == '__main__':
    unittest.main()
