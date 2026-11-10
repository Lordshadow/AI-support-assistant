import asyncio
import unittest
from urllib.parse import parse_qs, urlparse

import httpx

from ingestion.shop_catalog import ShopCatalogConnector


class TestShopCatalogConnector(unittest.TestCase):
    def test_fetch_products_reads_all_pages_with_server_token(self):
        requests = []

        def respond(request):
            requests.append(request)
            page = int(parse_qs(urlparse(str(request.url)).query)["page"][0])
            product = {"product_id": str(page), "name": f"Product {page}", "description": "Details", "faqs": []}
            return httpx.Response(200, json={"products": [product], "pagination": {"total": 2, "total_pages": 2}})

        connector = ShopCatalogConnector("http://shop/api/assistant/v1", "private-token", httpx.MockTransport(respond))
        products = asyncio.run(connector.fetch_products())

        self.assertEqual([row["product_id"] for row in products], ["1", "2"])
        self.assertEqual(str(requests[0].url).split("?", 1)[0], "http://shop/api/assistant/v1/catalog/export")
        self.assertEqual(requests[0].headers["Authorization"], "Bearer private-token")
        self.assertEqual(parse_qs(urlparse(str(requests[1].url)).query)["page"], ["2"])

    def test_fetch_products_rejects_incomplete_export(self):
        transport = httpx.MockTransport(lambda _request: httpx.Response(
            200, json={"products": [], "pagination": {"total": 3, "total_pages": 1}}
        ))
        connector = ShopCatalogConnector("http://shop/api/assistant/v1", "private-token", transport)
        with self.assertRaisesRegex(ValueError, "incomplete"):
            asyncio.run(connector.fetch_products())

    def test_connector_requires_server_side_configuration(self):
        from unittest.mock import patch

        with patch.dict("os.environ", {"APEXSTORE_CATALOG_API_URL": "", "APEXSTORE_CATALOG_API_TOKEN": ""}, clear=False):
            with self.assertRaisesRegex(RuntimeError, "APEXSTORE_CATALOG_API_URL"):
                ShopCatalogConnector()

    def test_fetch_page_retries_transient_failures_without_leaking_credentials(self):
        from unittest.mock import patch

        attempts = []

        def respond(request):
            attempts.append(request)
            if len(attempts) == 1:
                return httpx.Response(503, headers={"Retry-After": "0"})
            return httpx.Response(200, json={"products": [], "pagination": {"total_pages": 1}})

        connector = ShopCatalogConnector(
            "http://shop/api/assistant/v1", "private-token", httpx.MockTransport(respond),
            max_attempts=2, requests_per_second=1000,
        )
        with patch("ingestion.shop_catalog.asyncio.sleep", new=__import__("unittest.mock").mock.AsyncMock()):
            result = asyncio.run(connector.fetch_page())

        self.assertEqual(result["products"], [])
        self.assertEqual(len(attempts), 2)
        self.assertEqual(attempts[1].headers["Authorization"], "Bearer private-token")

    def test_fetch_page_does_not_retry_client_errors(self):
        attempts = []

        def respond(request):
            attempts.append(request)
            return httpx.Response(403, json={"error": "FORBIDDEN"})

        connector = ShopCatalogConnector(
            "http://shop/api/assistant/v1", "private-token", httpx.MockTransport(respond),
            max_attempts=4, requests_per_second=1000,
        )
        with self.assertRaises(httpx.HTTPStatusError):
            asyncio.run(connector.fetch_page())
        self.assertEqual(len(attempts), 1)


if __name__ == "__main__":
    unittest.main()
