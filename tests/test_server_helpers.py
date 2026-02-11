"""Unit tests for `src_service.server.helpers` utilities."""
import unittest
from types import SimpleNamespace

from src_service.server.helpers import get_host_header, get_client_addr, get_public_ip


class TestServerHelpers(unittest.TestCase):
    def test_get_host_header_present(self):
        handler = SimpleNamespace(headers={"Host": "example.local:8080"})
        self.assertEqual(get_host_header(handler), "example.local:8080")

    def test_get_host_header_missing(self):
        handler = SimpleNamespace()
        self.assertIsNone(get_host_header(handler))

    def test_get_client_addr_present(self):
        handler = SimpleNamespace(client_address=("1.2.3.4", 4321))
        self.assertEqual(get_client_addr(handler), "1.2.3.4:4321")

    def test_get_client_addr_missing(self):
        handler = SimpleNamespace()
        self.assertIsNone(get_client_addr(handler))

    def test_get_public_ip_xff(self):
        handler = SimpleNamespace(headers={"X-Forwarded-For": "203.0.113.55, 10.0.0.1"})
        self.assertEqual(get_public_ip(handler), "203.0.113.55")

    def test_get_public_ip_xreal(self):
        handler = SimpleNamespace(headers={"X-Real-IP": "198.51.100.7"})
        self.assertEqual(get_public_ip(handler), "198.51.100.7")

    def test_get_public_ip_missing(self):
        handler = SimpleNamespace(headers={})
        self.assertIsNone(get_public_ip(handler))

    def test_graceful_on_malformed_headers(self):
        class BadHandler:
            @property
            def headers(self):
                raise RuntimeError("boom")

        h = BadHandler()
        self.assertIsNone(get_host_header(h))
        self.assertIsNone(get_public_ip(h))

    def test_graceful_on_bad_client_addr(self):
        class BadHandler:
            @property
            def client_address(self):
                raise RuntimeError("boom")

        h = BadHandler()
        self.assertIsNone(get_client_addr(h))

    def test_get_public_ip_prefers_xff_over_xreal(self):
        handler = SimpleNamespace(headers={"X-Forwarded-For": "203.0.113.55, 10.0.0.1", "X-Real-IP": "198.51.100.7"})
        self.assertEqual(get_public_ip(handler), "203.0.113.55")

    def test_get_public_ip_single_entry_whitespace(self):
        handler = SimpleNamespace(headers={"X-Forwarded-For": " 203.0.113.55 "})
        self.assertEqual(get_public_ip(handler), "203.0.113.55")

    def test_get_public_ip_empty_string(self):
        handler = SimpleNamespace(headers={"X-Forwarded-For": ""})
        # An empty header is treated as missing and the helper returns None
        self.assertIsNone(get_public_ip(handler))

    def test_get_host_header_empty_string(self):
        handler = SimpleNamespace(headers={"Host": ""})
        self.assertEqual(get_host_header(handler), "")

    def test_get_client_addr_with_str_port(self):
        handler = SimpleNamespace(client_address=("1.2.3.4", "4321"))
        self.assertEqual(get_client_addr(handler), "1.2.3.4:4321")

    def test_headers_like_object(self):
        class HeadersLike:
            def __init__(self, d):
                self.d = d
            def get(self, key):
                return self.d.get(key)

        handler = SimpleNamespace(headers=HeadersLike({"X-Real-IP": "198.51.100.7"}))
        self.assertEqual(get_public_ip(handler), "198.51.100.7")


if __name__ == "__main__":
    unittest.main()
