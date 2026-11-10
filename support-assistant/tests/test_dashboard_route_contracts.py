"""Dashboard API route and unauthenticated-access contract checks."""

import json
import unittest

from services.dashboard_api.app import create_dashboard_api


def _run_sync(coro):
    """Drive ASGI's immediate async path without opening sockets or a DB connection."""
    stack, value = [coro], None
    while stack:
        try:
            result = stack[-1].send(value)
            value = None
            if hasattr(result, "send"):
                stack.append(result)
            else:
                value = result
        except StopIteration as finished:
            stack.pop()
            value = finished.value
    return value


def _request(app, method, path, body=b""):
    response = {"status": None, "headers": {}, "body": bytearray()}

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(event):
        if event["type"] == "http.response.start":
            response["status"] = event["status"]
            response["headers"] = dict(event.get("headers", []))
        elif event["type"] == "http.response.body":
            response["body"].extend(event.get("body", b""))

    _run_sync(app({
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }, receive, send))
    response["json"] = json.loads(response["body"]) if response["body"] else None
    return response


class TestDashboardRouteContracts(unittest.TestCase):
    def setUp(self):
        self.app = create_dashboard_api()

    def test_operational_routes_are_mounted(self):
        schema_paths = self.app.openapi()["paths"]
        mounted = {
            (path, method.upper())
            for path, operations in schema_paths.items()
            for method in operations
        }
        expected = {
            ("/api/admin/v1/reports", "GET"),
            ("/api/admin/v1/refunds/pending", "GET"),
            ("/api/admin/v1/escalations", "GET"),
            ("/api/admin/v1/conversations", "GET"),
            ("/api/admin/v1/knowledge/versions", "GET"),
            ("/api/admin/v1/settings", "GET"),
            ("/api/admin/v1/auth/staff", "GET"),
            ("/api/admin/v1/search", "GET"),
            ("/api/admin/v1/orders/{order_id}", "GET"),
        }
        self.assertTrue(expected.issubset(mounted), f"Missing dashboard routes: {expected - mounted}")

    def test_sensitive_read_routes_require_staff_authentication(self):
        for path in (
            "/api/admin/v1/reports",
            "/api/admin/v1/refunds/pending",
            "/api/admin/v1/escalations",
            "/api/admin/v1/conversations",
            "/api/admin/v1/settings",
            "/api/admin/v1/auth/staff",
            "/api/admin/v1/orders/ORD-QA-1",
        ):
            with self.subTest(path=path):
                response = _request(self.app, "GET", path)
                self.assertEqual(response["status"], 401, response["json"])


if __name__ == "__main__":
    unittest.main()
