"""Configuration management for the door controller."""
import os
import json
from typing import Optional

# Import version
try:
    from .version import __version__
except ImportError:
    __version__ = "0.0.0-unknown"

# Default configuration values
DEFAULT_CONFIG = {
    # GPIO Pin Definitions
    "RELAY_PIN": 17,  # Relay control pin for the door latch
    "BUTTON_UNLOCK_PIN": 27,  # Unlock button pin
    "BUTTON_LOCK_PIN": 22,  # Lock button pin

    # Timing
    "UNLOCK_DURATION": 3600,  # 1 hour in seconds
    "DOOR_UNLOCK_BADGE_DURATION": 5,  # 5 seconds for badge unlock
    "DEBOUNCE_TIME": 0.5,  # Half a second debounce time
    "BADGE_REFRESH_RATE_LIMIT_SECONDS": 60,  # Rate limit for manual badge refresh clicks (5 minutes)
    "DOOR_TOGGLE_RATE_LIMIT_SECONDS": 5,  # Rate limit for door toggle requests (5 seconds)

    # File paths
    "CSV_FILE": "google_sheet_data.csv",
    "CREDS_FILE": "../creds.json",
    "LOG_FILE": "logs/door_controller.log",
    "METRICS_DB_PATH": "logs/metrics",
    # Watchdog heartbeat file (single, non-dated file). It records the last time the watchdog ran.
    "WATCHDOG_FILE": "logs/door_controller_watchdog_heartbeat.txt",

    # Google Sheets
    "BADGE_SHEET_NAME": "Badge List - Access Control",
    "LOG_SHEET_NAME": "Access Door Log",

    # Health Server
    "HEALTH_SERVER_PORT": 3667, # door
    "HEALTH_SERVER_USERNAME": "admin",
    "HEALTH_SERVER_PASSWORD": "changeme",
    "HEALTH_REFRESH_INTERVAL": 300,  # 5 minutes

    # TLS / HTTPS for health server
    "HEALTH_SERVER_TLS": False,
    "HEALTH_SERVER_CERT_FILE": "cert.pem",

    # Health cache duration: how long (minutes) to keep health metrics cached
    "HEALTH_CACHE_DURATION_MINUTES": 5,

    # Badge refresh scheduling
    "BADGE_REFRESH_INTERVAL_SECONDS": 24 * 60 * 60,

    # Logging
    "LOG_LEVEL": "INFO",
    "LOG_RETENTION_DAYS": 7,
    "LOG_MAX_BYTES": 10 * 1024 * 1024,  # 10MB

    # Optional per-purpose log files (if not provided, derived from LOG_FILE)
    "ACTION_LOG_FILE": None,
    "WATCHDOG_LOG_FILE": None,

    # Auth/session settings
    "AUTH_SESSION_TTL_SECONDS": 8 * 60 * 60,
    "AUTH_SESSION_COOKIE_NAME": "door_session",
    "AUTH_WHITELIST_EMAILS": [],
    "AUTH_WHITELIST_DOMAINS": [],

    # Google OAuth2
    "GOOGLE_OAUTH_ENABLED": False,
    "GOOGLE_OAUTH_CLIENT_ID": "",
    "GOOGLE_OAUTH_CLIENT_SECRET": "",
    "GOOGLE_OAUTH_REDIRECT_URI": "",
    "GOOGLE_OAUTH_SCOPES": ["openid", "https://www.googleapis.com/auth/userinfo.email"],
    "GOOGLE_OAUTH_ALLOW_HTTP": False,  # Allow OAuth over HTTP (for dev/tunnels)
}


class Config:
    """Configuration manager with environment variable override support."""

    def __init__(self, config_file: Optional[str] = None):
        self.config = DEFAULT_CONFIG.copy()

        # Load from config file (default to config.json in current directory if not specified)
        if config_file is None:
            config_file = "config.json"
        if config_file and os.path.exists(config_file):
            with open(config_file, 'r') as f:
                file_config = json.load(f)
                self.config.update(file_config)

        # Override with environment variables (including CREDS_FILE path)
        self._load_from_env()

        # Load optional secrets from creds.json (after env vars so CREDS_FILE path is correct)
        self._load_from_creds()

    def _load_from_creds(self):
        """Load auth/OAuth settings from creds.json when available."""
        creds_file = self.config.get("CREDS_FILE")
        if not creds_file or not os.path.exists(creds_file):
            return
        try:
            with open(creds_file, "r") as f:
                creds = json.load(f)
        except Exception:
            return

        creds_mappings = {
            "auth_whitelist_emails": "AUTH_WHITELIST_EMAILS",
            "auth_whitelist_domains": "AUTH_WHITELIST_DOMAINS",
            "google_oauth_enabled": "GOOGLE_OAUTH_ENABLED",
            "google_oauth_client_id": "GOOGLE_OAUTH_CLIENT_ID",
            "google_oauth_client_secret": "GOOGLE_OAUTH_CLIENT_SECRET",
            "google_oauth_redirect_uri": "GOOGLE_OAUTH_REDIRECT_URI",
            "google_oauth_scopes": "GOOGLE_OAUTH_SCOPES",
            "google_oauth_allow_http": "GOOGLE_OAUTH_ALLOW_HTTP",
        }

        for creds_key, config_key in creds_mappings.items():
            value = None
            if creds_key in creds:
                value = creds.get(creds_key)
            else:
                upper_key = creds_key.upper()
                value = creds.get(upper_key)
            if value is None:
                continue
            if isinstance(self.config.get(config_key), bool):
                if isinstance(value, bool):
                    self.config[config_key] = value
                elif isinstance(value, str):
                    self.config[config_key] = value.lower() in ("true", "1", "yes", "on")
                else:
                    self.config[config_key] = bool(value)
            elif isinstance(self.config.get(config_key), int):
                try:
                    self.config[config_key] = int(value)
                except Exception:
                    continue
            elif isinstance(self.config.get(config_key), (list, dict)):
                if isinstance(value, str):
                    try:
                        self.config[config_key] = json.loads(value)
                    except Exception:
                        items = [v.strip() for v in value.replace(",", ";").split(";") if v.strip()]
                        self.config[config_key] = items
                else:
                    self.config[config_key] = value
            else:
                self.config[config_key] = value

    def _load_from_env(self):
        """Load configuration from environment variables."""
        env_mappings = {
            "DOOR_RELAY_PIN": "RELAY_PIN",
            "DOOR_UNLOCK_PIN": "BUTTON_UNLOCK_PIN",
            "DOOR_LOCK_PIN": "BUTTON_LOCK_PIN",
            "DOOR_UNLOCK_DURATION": "UNLOCK_DURATION",
            "DOOR_CSV_FILE": "CSV_FILE",
            "DOOR_CREDS_FILE": "CREDS_FILE",
            "DOOR_LOG_FILE": "LOG_FILE",
            "DOOR_METRICS_DB_PATH": "METRICS_DB_PATH",
            "DOOR_HEALTH_PORT": "HEALTH_SERVER_PORT",
            "DOOR_HEALTH_USERNAME": "HEALTH_SERVER_USERNAME",
            "DOOR_HEALTH_PASSWORD": "HEALTH_SERVER_PASSWORD",
            "DOOR_HEALTH_REFRESH": "HEALTH_REFRESH_INTERVAL",
            "DOOR_HEALTH_TLS": "HEALTH_SERVER_TLS",
            "DOOR_HEALTH_CERT_FILE": "HEALTH_SERVER_CERT_FILE",
            "DOOR_ACTION_LOG_FILE": "ACTION_LOG_FILE",
            "DOOR_WATCHDOG_LOG_FILE": "WATCHDOG_LOG_FILE",
            "DOOR_AUTH_SESSION_TTL_SECONDS": "AUTH_SESSION_TTL_SECONDS",
            "DOOR_AUTH_SESSION_COOKIE_NAME": "AUTH_SESSION_COOKIE_NAME",
            "DOOR_AUTH_WHITELIST_EMAILS": "AUTH_WHITELIST_EMAILS",
            "DOOR_AUTH_WHITELIST_DOMAINS": "AUTH_WHITELIST_DOMAINS",
            "DOOR_GOOGLE_OAUTH_ENABLED": "GOOGLE_OAUTH_ENABLED",
            "DOOR_GOOGLE_OAUTH_CLIENT_ID": "GOOGLE_OAUTH_CLIENT_ID",
            "DOOR_GOOGLE_OAUTH_CLIENT_SECRET": "GOOGLE_OAUTH_CLIENT_SECRET",
            "DOOR_GOOGLE_OAUTH_REDIRECT_URI": "GOOGLE_OAUTH_REDIRECT_URI",
            "DOOR_GOOGLE_OAUTH_SCOPES": "GOOGLE_OAUTH_SCOPES",
        }

        for env_key, config_key in env_mappings.items():
            value = os.environ.get(env_key)
            if value is not None:
                # Convert to appropriate type
                if isinstance(self.config[config_key], bool):
                    self.config[config_key] = value.lower() in ("true", "1", "yes", "on")
                elif isinstance(self.config[config_key], int):
                    self.config[config_key] = int(value)
                elif isinstance(self.config[config_key], (list, dict)):
                    try:
                        self.config[config_key] = json.loads(value)
                    except Exception:
                        items = [v.strip() for v in value.replace(",", ";").split(";") if v.strip()]
                        self.config[config_key] = items
                else:
                    self.config[config_key] = value

    def get(self, key: str, default=None):
        """Get configuration value."""
        return self.config.get(key, default)

    def __getitem__(self, key: str):
        """Get configuration value using dictionary syntax."""
        return self.config[key]


# Global configuration instance
config = Config()
