"""Unit tests for authentication and session management."""
import unittest
from unittest.mock import Mock, patch
from src_service.server.auth import (
    is_email_whitelisted,
    create_session,
    get_session,
    clear_session,
    check_basic_auth,
    get_current_user,
    _SESSION_STORE,
)


class TestEmailWhitelist(unittest.TestCase):
    """Test cases for email whitelist functionality."""

    def setUp(self):
        self.test_config = {
            "AUTH_WHITELIST_EMAILS": ["alice@example.com", "bob@example.com"],
            "AUTH_WHITELIST_DOMAINS": ["*.allowed.org", "familab.org"],
        }
        self.patcher = patch("src_service.server.auth.config", self.test_config)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    def test_exact_email_match(self):
        """Exact email in whitelist should be allowed."""
        self.assertTrue(is_email_whitelisted("alice@example.com"))
        self.assertTrue(is_email_whitelisted("bob@example.com"))

    def test_email_case_insensitive(self):
        """Email matching should be case-insensitive."""
        self.assertTrue(is_email_whitelisted("ALICE@example.com"))
        self.assertTrue(is_email_whitelisted("Bob@Example.COM"))

    def test_wildcard_domain_match(self):
        """Wildcard domain patterns should match subdomains."""
        self.assertTrue(is_email_whitelisted("user@sub.allowed.org"))
        self.assertTrue(is_email_whitelisted("test@deep.sub.allowed.org"))

    def test_exact_domain_match(self):
        """Exact domain should match."""
        self.assertTrue(is_email_whitelisted("user@familab.org"))

    def test_subdomain_not_allowed_for_exact_domain(self):
        """Subdomain should not match exact domain entry."""
        self.assertFalse(is_email_whitelisted("user@sub.familab.org"))

    def test_email_not_in_whitelist(self):
        """Email not in whitelist should be rejected."""
        self.assertFalse(is_email_whitelisted("unauthorized@example.com"))
        self.assertFalse(is_email_whitelisted("user@other.org"))

    def test_empty_email(self):
        """Empty email should be rejected."""
        self.assertFalse(is_email_whitelisted(""))
        self.assertFalse(is_email_whitelisted(None))

    def test_no_whitelist_allows_all(self):
        """When whitelist is empty, all emails should be allowed."""
        with patch("src_service.server.auth.config", {"AUTH_WHITELIST_EMAILS": [], "AUTH_WHITELIST_DOMAINS": []}):
            self.assertTrue(is_email_whitelisted("anyone@anywhere.com"))


class TestSessionManagement(unittest.TestCase):
    """Test cases for session creation and retrieval."""

    def setUp(self):
        _SESSION_STORE.clear()

    def tearDown(self):
        _SESSION_STORE.clear()

    def test_create_session(self):
        """Creating a session should return a session ID."""
        session_id = create_session("test@example.com")
        self.assertIsInstance(session_id, str)
        self.assertGreater(len(session_id), 20)

    def test_get_valid_session(self):
        """Getting a valid session should return session data."""
        session_id = create_session("test@example.com")

        handler = Mock()
        handler.headers.get.return_value = f"door_session={session_id}"

        session = get_session(handler)
        self.assertIsNotNone(session)
        self.assertEqual(session["user_email"], "test@example.com")

    def test_get_missing_session(self):
        """Getting a non-existent session should return None."""
        handler = Mock()
        handler.headers.get.return_value = "door_session=invalid_session_id"

        session = get_session(handler)
        self.assertIsNone(session)

    def test_get_session_no_cookie(self):
        """Getting session without cookie should return None."""
        handler = Mock()
        handler.headers.get.return_value = None

        session = get_session(handler)
        self.assertIsNone(session)

    def test_clear_session(self):
        """Clearing a session should remove it from the store."""
        session_id = create_session("test@example.com")

        handler = Mock()
        handler.headers.get.return_value = f"door_session={session_id}"

        clear_session(handler)

        # Session should no longer be retrievable
        session = get_session(handler)
        self.assertIsNone(session)


class TestBasicAuth(unittest.TestCase):
    """Test cases for HTTP Basic Auth."""

    def setUp(self):
        self.test_config = {
            "HEALTH_SERVER_USERNAME": "testuser",
            "HEALTH_SERVER_PASSWORD": "testpass",
        }
        self.patcher = patch("src_service.server.auth.config", self.test_config)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    def test_valid_basic_auth(self):
        """Valid Basic Auth credentials should authenticate."""
        import base64
        credentials = base64.b64encode(b"testuser:testpass").decode("ascii")

        handler = Mock()
        handler.headers.get.return_value = f"Basic {credentials}"

        self.assertTrue(check_basic_auth(handler))

    def test_invalid_basic_auth(self):
        """Invalid Basic Auth credentials should fail."""
        import base64
        credentials = base64.b64encode(b"wronguser:wrongpass").decode("ascii")

        handler = Mock()
        handler.headers.get.return_value = f"Basic {credentials}"

        self.assertFalse(check_basic_auth(handler))

    def test_missing_auth_header(self):
        """Missing Authorization header should fail."""
        handler = Mock()
        handler.headers.get.return_value = None

        self.assertFalse(check_basic_auth(handler))

    def test_wrong_auth_type(self):
        """Non-Basic auth type should fail."""
        handler = Mock()
        handler.headers.get.return_value = "Bearer some_token"

        self.assertFalse(check_basic_auth(handler))


class TestGetCurrentUser(unittest.TestCase):
    """Test cases for getting current authenticated user."""

    def setUp(self):
        _SESSION_STORE.clear()
        self.test_config = {
            "HEALTH_SERVER_USERNAME": "testuser",
            "HEALTH_SERVER_PASSWORD": "testpass",
        }
        self.patcher = patch("src_service.server.auth.config", self.test_config)
        self.patcher.start()

    def tearDown(self):
        _SESSION_STORE.clear()
        self.patcher.stop()

    def test_get_current_user_with_session(self):
        """User with valid session should return Google OAuth user info."""
        session_id = create_session("oauth_user@example.com")

        handler = Mock()
        handler.headers.get.return_value = f"door_session={session_id}"

        user_info = get_current_user(handler)
        self.assertIsNotNone(user_info)
        self.assertEqual(user_info["email"], "oauth_user@example.com")
        self.assertEqual(user_info["auth_method"], "google_oauth")

    def test_get_current_user_with_basic_auth(self):
        """User with valid Basic Auth should return Basic Auth user info."""
        import base64
        credentials = base64.b64encode(b"testuser:testpass").decode("ascii")

        handler = Mock()
        handler.headers.get.side_effect = lambda key: f"Basic {credentials}" if key == "Authorization" else None

        user_info = get_current_user(handler)
        self.assertIsNotNone(user_info)
        self.assertEqual(user_info["email"], "testuser")
        self.assertEqual(user_info["auth_method"], "basic_auth")

    def test_get_current_user_session_takes_precedence(self):
        """When both session and Basic Auth present, session should take precedence."""
        session_id = create_session("oauth_user@example.com")
        import base64
        credentials = base64.b64encode(b"testuser:testpass").decode("ascii")

        handler = Mock()
        # Mock headers to return session cookie for "Cookie" and basic auth for "Authorization"
        def get_header(key):
            if key == "Cookie":
                return f"door_session={session_id}"
            elif key == "Authorization":
                return f"Basic {credentials}"
            return None

        handler.headers.get.side_effect = get_header

        user_info = get_current_user(handler)
        self.assertIsNotNone(user_info)
        self.assertEqual(user_info["email"], "oauth_user@example.com")
        self.assertEqual(user_info["auth_method"], "google_oauth")

    def test_get_current_user_no_auth(self):
        """User with no authentication should return None."""
        handler = Mock()
        handler.headers.get.return_value = None

        user_info = get_current_user(handler)
        self.assertIsNone(user_info)

    def test_get_current_user_invalid_session(self):
        """User with invalid session and no Basic Auth should return None."""
        handler = Mock()
        handler.headers.get.side_effect = lambda key: "door_session=invalid_id" if key == "Cookie" else None

        user_info = get_current_user(handler)
        self.assertIsNone(user_info)

    def test_get_current_user_invalid_basic_auth(self):
        """User with invalid Basic Auth should return None."""
        import base64
        credentials = base64.b64encode(b"wronguser:wrongpass").decode("ascii")

        handler = Mock()
        handler.headers.get.side_effect = lambda key: f"Basic {credentials}" if key == "Authorization" else None

        user_info = get_current_user(handler)
        self.assertIsNone(user_info)


if __name__ == '__main__':
    unittest.main()
