"""
Unit & Integration Test Suite for Widget Configuration API and Master Control Dashboard Integration.
Validates Spec 16.1, 16.2 and Master Control Dashboard widget embed integration.
"""

import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch, MagicMock

# Ensure support-assistant is in sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from starlette.requests import Request
from services.dashboard_api.widget import router as widget_router, get_widget_config
from services.dashboard_api.dependencies import StaffSessionContext
from services.dashboard_api.app import create_dashboard_api


class TestWidgetConfigAndDashboard(unittest.TestCase):

    def setUp(self):
        self.staff_admin = StaffSessionContext(
            staff_id="staff_widget_admin",
            email="admin@novaretail.com",
            full_name="Widget Admin",
            tenant_id="tenant_novaretail",
            role="admin",
            session_id="sess_widget_test_123",
            is_stepped_up=False,
        )

        self.staff_executive = StaffSessionContext(
            staff_id="staff_widget_exec",
            email="exec@novaretail.com",
            full_name="Widget Executive",
            tenant_id="demo-shop",
            role="executive",
            session_id="sess_widget_test_456",
            is_stepped_up=False,
        )

    def test_widget_router_registration_in_dashboard_api(self):
        """Verify widget router is mounted in create_dashboard_api()."""
        app = create_dashboard_api()
        self.assertIn(widget_router, [getattr(r, "original_router", None) for r in app.routes])

    def test_get_widget_config_default_payload(self):
        """Verify default configuration returns all required metadata and snippet."""
        req = Request({"type": "http", "headers": [(b"host", b"api.novaretail.com:8000")], "path": "/"})
        res = get_widget_config(req, self.staff_admin)

        self.assertEqual(res["tenant_id"], "tenant_novaretail")
        self.assertEqual(res["script_path"], "/widget/v1/widget.js")
        self.assertEqual(res["demo_url"], "http://api.novaretail.com:8000/widget/index.html")
        self.assertIn("https://shop.novaretail.com", res["allowed_origins"])
        self.assertIn("security_spec", res)
        self.assertIn("shadow_dom", res["security_spec"])
        self.assertIn("xss_protection", res["security_spec"])
        self.assertIn("origin_guard", res["security_spec"])
        self.assertIn("default_snippet", res)
        self.assertIn("widget/v1/widget.js", res["default_snippet"])
        self.assertIn('data-tenant="tenant_novaretail"', res["default_snippet"])

    def test_get_widget_config_custom_tenant(self):
        """Verify configuration binds to the executive's active tenant."""
        req = Request({"type": "http", "headers": [(b"host", b"demo.novaretail.com")], "path": "/"})
        res = get_widget_config(req, self.staff_executive)

        self.assertEqual(res["tenant_id"], "demo-shop")
        self.assertIn('data-tenant="demo-shop"', res["default_snippet"])

    def test_get_widget_config_respects_custom_origins_env(self):
        """Custom WIDGET_ALLOWED_ORIGINS environment variable is parsed and reflected."""
        req = Request({"type": "http", "headers": [(b"host", b"localhost:8000")], "path": "/"})
        with patch.dict(os.environ, {"WIDGET_ALLOWED_ORIGINS": "https://store.custom.com,https://staging.custom.com"}):
            res = get_widget_config(req, self.staff_admin)
            self.assertIn("https://store.custom.com", res["allowed_origins"])
            self.assertIn("https://staging.custom.com", res["allowed_origins"])

    def test_get_widget_config_https_forwarded_proto(self):
        """Verify scheme inference when behind TLS proxy (X-Forwarded-Proto: https)."""
        req = Request({
            "type": "http",
            "headers": [
                (b"host", b"control.novaretail.com"),
                (b"x-forwarded-proto", b"https"),
            ],
            "path": "/",
        })
        res = get_widget_config(req, self.staff_admin)
        self.assertTrue(res["script_url"].startswith("https://control.novaretail.com"))
        self.assertTrue(res["api_base"].startswith("https://control.novaretail.com"))


if __name__ == "__main__":
    unittest.main()
