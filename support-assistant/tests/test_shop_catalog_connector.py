import asyncio
import unittest
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

import httpx

from ingestion.shop_catalog import ShopCatalogConnector


class TestShopCatalogConnector(unittest.TestCase):
    @staticmethod
    def run_sync(coro):
        """Run immediately completing MockTransport coroutines without Windows loop sockets."""
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

    def run_connector(self, connector, coro):
        """Skip wall-clock pacing in unit tests; retry logic is tested separately."""
        with patch.object(connector, "_pace_request", new=AsyncMock()):
            return self.run_sync(coro)

    def test_fetch_products_reads_all_pages_with_server_token(self):
        requests = []

        def respond(request):
            requests.append(request)
            page = int(parse_qs(urlparse(str(request.url)).query)["page"][0])
            product = {"product_id": str(page), "name": f"Product {page}", "description": "Details", "faqs": []}
            return httpx.Response(200, json={"products": [product], "pagination": {"total": 2, "total_pages": 2}})

        connector = ShopCatalogConnector("http://shop/api/assistant/v1", "private-token", httpx.MockTransport(respond),
                                         requests_per_second=1000)
        products = self.run_connector(connector, connector.fetch_products())

        self.assertEqual([row["product_id"] for row in products], ["1", "2"])
        self.assertEqual(str(requests[0].url).split("?", 1)[0], "http://shop/api/assistant/v1/catalog/export")
        self.assertEqual(requests[0].headers["Authorization"], "Bearer private-token")
        self.assertEqual(parse_qs(urlparse(str(requests[1].url)).query)["page"], ["2"])

    def test_fetch_products_rejects_incomplete_export(self):
        transport = httpx.MockTransport(lambda _request: httpx.Response(
            200, json={"products": [], "pagination": {"total": 3, "total_pages": 1}}
        ))
        connector = ShopCatalogConnector("http://shop/api/assistant/v1", "private-token", transport,
                                         requests_per_second=1000)
        with self.assertRaisesRegex(ValueError, "incomplete"):
            self.run_connector(connector, connector.fetch_products())

    def test_connector_requires_server_side_configuration(self):
        from unittest.mock import patch

        empty_config = {
            "CATALOG_API_URL": "", "CATALOG_API_TOKEN": "",
            "APEXSTORE_CATALOG_API_URL": "", "APEXSTORE_CATALOG_API_TOKEN": "",
        }
        with patch.dict("os.environ", empty_config, clear=False):
            with self.assertRaisesRegex(RuntimeError, "CATALOG_API_URL"):
                ShopCatalogConnector()

    def test_generic_nested_page_api_supports_custom_auth_and_pagination(self):
        requests = []

        def respond(request):
            requests.append(request)
            page = int(parse_qs(urlparse(str(request.url)).query)["p"][0])
            row = {"id": f"P{page}", "title": f"Product {page}"}
            return httpx.Response(200, json={
                "data": {"items": [row]},
                "meta": {"count": 2, "pages": 2},
            })

        connector = ShopCatalogConnector(
            "https://store.example.com/api", "private-token", httpx.MockTransport(respond),
            endpoint_path="v2/products/export", products_path="data.items",
            total_path="meta.count", total_pages_path="meta.pages",
            page_param="p", page_size_param="per_page", auth_mode="header",
            token_header="X-Store-Token", page_size=1, requests_per_second=1000,
        )
        products = self.run_connector(connector, connector.fetch_products())

        self.assertEqual([row["id"] for row in products], ["P1", "P2"])
        self.assertTrue(str(requests[0].url).startswith("https://store.example.com/api/v2/products/export?"))
        self.assertEqual(requests[0].headers["X-Store-Token"], "private-token")
        self.assertEqual(parse_qs(urlparse(str(requests[1].url)).query)["p"], ["2"])

    def test_bare_array_with_total_headers_fetches_all_woocommerce_style_pages(self):
        requests = []

        def respond(request):
            requests.append(request)
            page = int(parse_qs(urlparse(str(request.url)).query)["page"][0])
            rows = [{"id": "P1", "name": "One"}] if page == 1 else [{"id": "P2", "name": "Two"}]
            return httpx.Response(200, json=rows, headers={"X-WP-Total": "2", "X-WP-TotalPages": "2"})

        connector = ShopCatalogConnector(
            "https://store.example.com/wp-json/wc/v3", "consumer:secret", httpx.MockTransport(respond),
            endpoint_path="products", products_path="", total_path="", total_pages_path="",
            page_size_param="per_page", total_header="X-WP-Total",
            total_pages_header="X-WP-TotalPages", auth_mode="basic", page_size=1,
            requests_per_second=1000,
        )
        products = self.run_connector(connector, connector.fetch_products())

        self.assertEqual([row["id"] for row in products], ["P1", "P2"])
        self.assertEqual(requests[0].headers["Authorization"], "Basic Y29uc3VtZXI6c2VjcmV0")
        self.assertEqual(parse_qs(urlparse(str(requests[0].url)).query)["per_page"], ["1"])

    def test_page_without_pagination_metadata_reads_until_short_page(self):
        seen_pages = []

        def respond(request):
            page = int(parse_qs(urlparse(str(request.url)).query)["page"][0])
            seen_pages.append(page)
            rows = [{"id": str(index), "name": f"Item {index}"} for index in range((page - 1) * 2 + 1, page * 2 + 1)]
            if page == 2:
                rows = rows[:1]
            return httpx.Response(200, json={"products": rows})

        connector = ShopCatalogConnector(
            "https://store.example.com/api", "token", httpx.MockTransport(respond),
            page_size=2, requests_per_second=1000,
        )
        products = self.run_connector(connector, connector.fetch_products())

        self.assertEqual(len(products), 3)
        self.assertEqual(seen_pages, [1, 2])

    def test_repeated_product_id_stops_a_broken_page_api_early(self):
        def respond(_request):
            return httpx.Response(200, json={
                "products": [{"id": "P1", "name": "One"}],
                "pagination": {"total": 2, "total_pages": 2},
            })

        connector = ShopCatalogConnector(
            "https://store.example.com/api", "token", httpx.MockTransport(respond),
            page_size=1,
        )
        with self.assertRaisesRegex(ValueError, "more than once"):
            self.run_connector(connector, connector.fetch_products())

    def test_connector_rejects_credentials_embedded_in_catalog_url(self):
        with self.assertRaisesRegex(ValueError, "credentials"):
            ShopCatalogConnector("https://user:password@store.example.com/api", "token")

    def test_generic_env_wins_while_legacy_apexstore_env_remains_compatible(self):
        from unittest.mock import patch

        generic = {"CATALOG_API_URL": "https://generic.example/api", "CATALOG_API_TOKEN": "generic-token"}
        legacy = {"APEXSTORE_CATALOG_API_URL": "https://apex.example/api", "APEXSTORE_CATALOG_API_TOKEN": "legacy-token"}
        with patch.dict("os.environ", {**generic, **legacy}, clear=False):
            connector = ShopCatalogConnector()
            self.assertEqual(connector.base_url, "https://generic.example/api")
            self.assertEqual(connector.token, "generic-token")

        with patch.dict("os.environ", {**generic, "CATALOG_API_URL": "", "CATALOG_API_TOKEN": "", **legacy}, clear=False):
            connector = ShopCatalogConnector()
            self.assertEqual(connector.base_url, "https://apex.example/api")
            self.assertEqual(connector.token, "legacy-token")

    def test_partial_generic_configuration_never_mixes_credentials_with_legacy_api(self):
        from unittest.mock import patch

        env = {
            "CATALOG_API_URL": "",
            "CATALOG_API_TOKEN": "new-provider-token",
            "APEXSTORE_CATALOG_API_URL": "https://apex.example/api",
            "APEXSTORE_CATALOG_API_TOKEN": "legacy-token",
        }
        with patch.dict("os.environ", env, clear=False):
            with self.assertRaisesRegex(RuntimeError, "CATALOG_API_URL"):
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
            result = self.run_connector(connector, connector.fetch_page())

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
            self.run_connector(connector, connector.fetch_page())
        self.assertEqual(len(attempts), 1)


if __name__ == "__main__":
    unittest.main()
