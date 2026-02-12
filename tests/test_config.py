"""Unit tests for configuration module."""
import unittest
import os
import json
import tempfile
from src_service.config import Config, DEFAULT_CONFIG


class TestConfig(unittest.TestCase):
    """Test cases for Config class."""

    def test_default_config(self):
        """Test that default configuration values are loaded."""
        config = Config()
        self.assertEqual(config["RELAY_PIN"], DEFAULT_CONFIG["RELAY_PIN"])
        self.assertEqual(config["UNLOCK_DURATION"], DEFAULT_CONFIG["UNLOCK_DURATION"])
        self.assertEqual(config["HEALTH_SERVER_PORT"], DEFAULT_CONFIG["HEALTH_SERVER_PORT"])
        self.assertEqual(config["METRICS_DB_PATH"], DEFAULT_CONFIG["METRICS_DB_PATH"])

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
            self.assertEqual(config["HEALTH_SERVER_PORT"], DEFAULT_CONFIG["HEALTH_SERVER_PORT"])
        finally:
            os.unlink(config_file)

    def test_environment_variable_override(self):
        """Test that environment variables override config."""
        os.environ["DOOR_RELAY_PIN"] = "42"
        os.environ["DOOR_HEALTH_PORT"] = "9090"
        os.environ["DOOR_METRICS_DB_PATH"] = "/tmp/metrics"

        try:
            config = Config()
            self.assertEqual(config["RELAY_PIN"], int(os.environ["DOOR_RELAY_PIN"]))
            self.assertEqual(config["HEALTH_SERVER_PORT"], int(os.environ["DOOR_HEALTH_PORT"]))
            self.assertEqual(config["METRICS_DB_PATH"], os.environ["DOOR_METRICS_DB_PATH"])
        finally:
            del os.environ["DOOR_RELAY_PIN"]
            del os.environ["DOOR_HEALTH_PORT"]
            del os.environ["DOOR_METRICS_DB_PATH"]

    def test_creds_file_override(self):
        """Test that creds.json settings are loaded into config."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            creds_config = {
                "auth_whitelist_emails": ["alpha@example.com", "beta@example.com"],
                "auth_whitelist_domains": ["*.example.org"],
                "google_oauth_enabled": True,
                "google_oauth_client_id": "client-id",
                "google_oauth_client_secret": "client-secret",
                "google_oauth_redirect_uri": "http://localhost:3667/login/google/callback",
                "google_oauth_scopes": ["openid", "email"],
            }
            json.dump(creds_config, f)
            creds_path = f.name

        os.environ["DOOR_CREDS_FILE"] = creds_path
        try:
            config = Config()
            self.assertEqual(config["AUTH_WHITELIST_EMAILS"], creds_config["auth_whitelist_emails"])
            self.assertEqual(config["AUTH_WHITELIST_DOMAINS"], creds_config["auth_whitelist_domains"])
            self.assertEqual(config["GOOGLE_OAUTH_ENABLED"], creds_config["google_oauth_enabled"])
            self.assertEqual(config["GOOGLE_OAUTH_CLIENT_ID"], creds_config["google_oauth_client_id"])
            self.assertEqual(config["GOOGLE_OAUTH_CLIENT_SECRET"], creds_config["google_oauth_client_secret"])
            self.assertEqual(config["GOOGLE_OAUTH_REDIRECT_URI"], creds_config["google_oauth_redirect_uri"])
            self.assertEqual(config["GOOGLE_OAUTH_SCOPES"], creds_config["google_oauth_scopes"])
        finally:
            del os.environ["DOOR_CREDS_FILE"]
            os.unlink(creds_path)

    def test_get_method(self):
        """Test the get method with default values."""
        config = Config()
        self.assertEqual(config.get("RELAY_PIN"), 17)
        self.assertIsNone(config.get("NONEXISTENT_KEY"))
        self.assertEqual(config.get("NONEXISTENT_KEY", "default"), "default")


if __name__ == '__main__':
    unittest.main()
