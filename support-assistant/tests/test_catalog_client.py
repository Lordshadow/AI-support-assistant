import os
import unittest
from unittest.mock import patch
import httpx

from ingestion.shop_catalog import (
    BaseCatalogConnector,
    ShopCatalogConnector,
    MockShopCatalogConnector,
    get_catalog_connector,
)
from adapters.mockshop.catalog_adapter import MockCatalogAdapter


class TestCatalogClient(unittest.TestCase):
    """Unit tests for Task 1: Stores API Client & Adapters."""

    @staticmethod
    def run_sync(coro):
        """Drive in-memory connector coroutines without a platform event loop."""
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

    def test_mock_catalog_adapter_export_excludes_volatile_and_includes_specs(self):
        adapter = MockCatalogAdapter()
        products = adapter.export_catalog()

        self.assertGreaterEqual(len(products), 3)
        product_ids = {p["product_id"] for p in products}
        self.assertIn("P1041", product_ids)
        self.assertIn("P1031", product_ids)
        self.assertIn("P2001", product_ids)

        for p in products:
            # Required fields
            self.assertIn("product_id", p)
            self.assertIn("name", p)
            self.assertIn("brand", p)
            self.assertIn("category", p)
            self.assertIn("description", p)
            self.assertIn("faqs", p)
            self.assertIn("specifications", p)
            self.assertIsInstance(p["faqs"], list)
            self.assertIsInstance(p["specifications"], list)

            # Volatile fields MUST NOT be present in catalog export
            self.assertNotIn("price", p)
            self.assertNotIn("stock", p)
            self.assertNotIn("discount_price", p)
            self.assertNotIn("active_offers", p)
            self.assertNotIn("order_id", p)
            self.assertNotIn("order_status", p)

    def test_mock_shop_catalog_connector_pagination(self):
        connector = MockShopCatalogConnector()

        # Page 1 with limit 2
        page1 = self.run_sync(connector.fetch_page(page=1, limit=2))
        self.assertEqual(len(page1["products"]), 2)
        self.assertEqual(page1["pagination"]["page"], 1)
        self.assertEqual(page1["pagination"]["limit"], 2)
        self.assertGreater(page1["pagination"]["total"], 2)
        self.assertGreater(page1["pagination"]["total_pages"], 1)

        # Page 2 with limit 2
        page2 = self.run_sync(connector.fetch_page(page=2, limit=2))
        self.assertGreaterEqual(len(page2["products"]), 1)
        self.assertEqual(page2["pagination"]["page"], 2)

        # Disjoint pages
        p1_ids = [p["product_id"] for p in page1["products"]]
        p2_ids = [p["product_id"] for p in page2["products"]]
        self.assertTrue(set(p1_ids).isdisjoint(set(p2_ids)))

        # Fetch all
        all_products = self.run_sync(connector.fetch_products())
        self.assertEqual(len(all_products), page1["pagination"]["total"])
        self.assertGreaterEqual(connector.request_count, 3)
        self.assertGreater(connector.total_request_latency_ms, 0)

    def test_get_catalog_connector_factory(self):
        # 1. Explicit mock
        conn_mock = get_catalog_connector(use_mock=True)
        self.assertIsInstance(conn_mock, MockShopCatalogConnector)

        # 2. CATALOG_SOURCE=mockshop in env
        with patch.dict(os.environ, {"CATALOG_SOURCE": "mockshop"}):
            conn_env_mock = get_catalog_connector()
            self.assertIsInstance(conn_env_mock, MockShopCatalogConnector)

        # 3. Live HTTP connector with explicit credentials
        conn_live = get_catalog_connector(
            base_url="https://store.example.com/api",
            token="test-secret-token",
            transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"products": [], "pagination": {}}))
        )
        self.assertIsInstance(conn_live, ShopCatalogConnector)
        self.assertEqual(conn_live.base_url, "https://store.example.com/api")
        self.assertEqual(conn_live.token, "test-secret-token")

    def test_shop_connector_retry_with_backoff_and_jitter(self):
        attempts = []

        async def no_wait(_delay):
            return None

        def mock_handler(request):
            attempts.append(request)
            if len(attempts) < 3:
                return httpx.Response(503, headers={"Retry-After": "0.01"})
            return httpx.Response(
                200,
                json={"products": [{"product_id": "P1", "name": "Test"}], "pagination": {"total": 1, "total_pages": 1}}
            )

        connector = ShopCatalogConnector(
            base_url="http://api.test",
            token="bearer-token",
            transport=httpx.MockTransport(mock_handler),
            max_attempts=4,
            requests_per_second=500,
        )
        with patch("ingestion.shop_catalog.asyncio.sleep", new=no_wait):
            result = self.run_sync(connector.fetch_page(page=1, limit=10))

        self.assertEqual(len(attempts), 3)
        self.assertEqual(len(result["products"]), 1)
        self.assertEqual(result["products"][0]["product_id"], "P1")


if __name__ == "__main__":
    unittest.main()
