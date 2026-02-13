"""Tests for OpenAPI spec generator."""
import unittest
from src_service.openapi import get_openapi_spec
from src_service.version import __version__


class TestOpenAPISpec(unittest.TestCase):
    def test_version_matches_package_version(self):
        spec = get_openapi_spec()
        self.assertIn("info", spec)
        self.assertEqual(spec["info"]["version"], __version__)

    def test_server_url_uses_host_header(self):
        spec = get_openapi_spec(host="example.com:1234")
        self.assertIn("servers", spec)
        self.assertTrue(any("example.com" in s["url"] for s in spec["servers"]))

    def test_metrics_and_toggle_paths_present(self):
        spec = get_openapi_spec()
        paths = spec.get("paths", {})
        self.assertIn("/api/toggle", paths)
        # Unified metrics endpoint and reload
        self.assertIn("/api/metrics", paths)
        self.assertIn("/api/metrics/reload", paths)
        # Version endpoint
        self.assertIn("/api/version", paths)
        # Ensure response schema contains 'version' property
        ver_resp = paths["/api/version"]["get"]["responses"]["200"]
        self.assertIn("application/json", ver_resp.get("content", {}))
        schema = ver_resp["content"]["application/json"]["schema"]
        self.assertIn("version", schema.get("properties", {}))

if __name__ == '__main__':
    unittest.main()
