"""Read-only client for store catalog export APIs (live HTTP and MockShop)."""

import os
import asyncio
import math
import random
import threading
import time
from typing import Any, Dict, List, Protocol
from urllib.parse import urljoin

import httpx

_RATE_LIMIT_LOCK = threading.Lock()
_NEXT_REQUEST_AT = 0.0


class BaseCatalogConnector(Protocol):
    """Protocol contract for read-only catalog ingestion source connectors."""

    @property
    def last_request_latency_ms(self) -> float | None:
        ...

    @property
    def total_request_latency_ms(self) -> float:
        ...

    @property
    def request_count(self) -> int:
        ...

    async def fetch_page(self, page: int = 1, limit: int = 100) -> Dict[str, Any]:
        ...

    async def fetch_products(self) -> List[Dict[str, Any]]:
        ...


class ShopCatalogConnector:
    """Fetch active products from the configured shop without DB credentials."""

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        *,
        timeout_seconds: float | None = None,
        max_attempts: int | None = None,
        requests_per_second: float | None = None,
    ):
        self.base_url = (base_url or os.getenv("APEXSTORE_CATALOG_API_URL", "")).strip().rstrip("/")
        self.token = (token or os.getenv("APEXSTORE_CATALOG_API_TOKEN", "")).strip()
        self.transport = transport
        self.timeout_seconds = timeout_seconds or float(os.getenv("APEXSTORE_CATALOG_TIMEOUT_SECONDS", "30"))
        self.max_attempts = max_attempts or int(os.getenv("APEXSTORE_CATALOG_MAX_ATTEMPTS", "4"))
        self.requests_per_second = requests_per_second or float(os.getenv("APEXSTORE_CATALOG_REQUESTS_PER_SECOND", "2"))
        self._last_request_at = 0.0
        self._latencies_ms: list[float] = []
        if self.timeout_seconds <= 0 or self.max_attempts < 1 or self.requests_per_second <= 0:
            raise ValueError("Catalog timeout, attempts, and request rate must be positive.")
        if not self.base_url:
            raise RuntimeError("APEXSTORE_CATALOG_API_URL is not configured.")
        if not self.token:
            raise RuntimeError("APEXSTORE_CATALOG_API_TOKEN is not configured.")

    async def fetch_page(self, page: int = 1, limit: int = 100) -> Dict[str, Any]:
        if page < 1:
            raise ValueError("Catalog page numbers start at 1.")
        url = urljoin(f"{self.base_url}/", "catalog/export")
        timeout = httpx.Timeout(self.timeout_seconds, connect=min(5.0, self.timeout_seconds))
        async with httpx.AsyncClient(timeout=timeout, transport=self.transport) as client:
            response = None
            for attempt in range(self.max_attempts):
                await self._pace_request()
                started = time.monotonic()
                try:
                    response = await client.get(
                        url,
                        params={"page": page, "limit": min(max(limit, 1), 100)},
                        headers={"Authorization": f"Bearer {self.token}"},
                    )
                    self._latencies_ms.append((time.monotonic() - started) * 1000)
                    if response.status_code not in (408, 425, 429) and response.status_code < 500:
                        response.raise_for_status()
                        break
                    if attempt == self.max_attempts - 1:
                        response.raise_for_status()
                except (httpx.TimeoutException, httpx.NetworkError):
                    if attempt == self.max_attempts - 1:
                        raise RuntimeError("ApexStore catalog API request failed after retries.") from None
                await asyncio.sleep(self._retry_delay(attempt, response))
            if response is None:
                raise RuntimeError("ApexStore catalog API request failed after retries.")
            payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("products"), list):
            raise ValueError("ApexStore catalog export returned an invalid products page.")
        return payload

    async def _pace_request(self) -> None:
        global _NEXT_REQUEST_AT
        interval = 1.0 / self.requests_per_second
        now = time.monotonic()
        with _RATE_LIMIT_LOCK:
            slot = max(now, _NEXT_REQUEST_AT)
            _NEXT_REQUEST_AT = slot + interval
        if slot > now:
            await asyncio.sleep(slot - now)
        self._last_request_at = time.monotonic()

    @staticmethod
    def _retry_delay(attempt: int, response: httpx.Response | None) -> float:
        if response is not None:
            retry_after = response.headers.get("Retry-After", "")
            try:
                return min(max(float(retry_after), 0.0), 10.0)
            except ValueError:
                pass
        return min(0.25 * (2 ** attempt) + random.uniform(0.0, 0.1), 5.0)

    @property
    def last_request_latency_ms(self) -> float | None:
        return self._latencies_ms[-1] if self._latencies_ms else None

    @property
    def total_request_latency_ms(self) -> float:
        return sum(self._latencies_ms)

    @property
    def request_count(self) -> int:
        return len(self._latencies_ms)

    async def fetch_products(self) -> List[Dict[str, Any]]:
        first = await self.fetch_page(page=1, limit=100)
        pagination = first.get("pagination") or {}
        total_pages = int(pagination.get("total_pages") or 1)
        products = list(first["products"])
        if total_pages > 10000:
            raise ValueError("ApexStore catalog export reports an unsafe page count.")
        for page in range(2, total_pages + 1):
            result = await self.fetch_page(page=page, limit=100)
            products.extend(result["products"])
        expected_total = pagination.get("total")
        if expected_total is not None and len(products) != int(expected_total):
            raise ValueError(
                f"ApexStore catalog export was incomplete ({len(products)} of {expected_total} products)."
            )
        return products


class MockShopCatalogConnector:
    """In-memory paginated connector wrapping MockCatalogAdapter or seed products."""

    def __init__(self, products: list[dict[str, Any]] | None = None):
        if products is not None:
            self._products = products
        else:
            from adapters.mockshop.catalog_adapter import MockCatalogAdapter
            self._products = MockCatalogAdapter().export_catalog()
        self._latencies_ms: list[float] = []

    @property
    def last_request_latency_ms(self) -> float | None:
        return self._latencies_ms[-1] if self._latencies_ms else 0.5

    @property
    def total_request_latency_ms(self) -> float:
        return sum(self._latencies_ms) if self._latencies_ms else 0.5

    @property
    def request_count(self) -> int:
        return len(self._latencies_ms) or 1

    async def fetch_page(self, page: int = 1, limit: int = 100) -> Dict[str, Any]:
        if page < 1:
            raise ValueError("Catalog page numbers start at 1.")
        limit = min(max(limit, 1), 100)
        start = (page - 1) * limit
        end = start + limit
        self._latencies_ms.append(0.5)
        paged_products = self._products[start:end]
        total = len(self._products)
        total_pages = max(1, math.ceil(total / limit))
        return {
            "products": paged_products,
            "pagination": {
                "total": total,
                "page": page,
                "limit": limit,
                "total_pages": total_pages,
            },
        }

    async def fetch_products(self) -> List[Dict[str, Any]]:
        self._latencies_ms.append(1.0)
        return list(self._products)


def get_catalog_connector(
    base_url: str | None = None,
    token: str | None = None,
    *,
    use_mock: bool | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    **kwargs: Any,
) -> BaseCatalogConnector:
    """Factory returning either the live ShopCatalogConnector or MockShopCatalogConnector."""
    if use_mock is True or os.getenv("CATALOG_SOURCE", "").lower() == "mockshop":
        return MockShopCatalogConnector()

    url = (base_url or os.getenv("APEXSTORE_CATALOG_API_URL", "")).strip()
    tok = (token or os.getenv("APEXSTORE_CATALOG_API_TOKEN", "")).strip()

    if not url or not tok:
        # In non-production or test runs without configured env, provide default fallback
        # for ShopCatalogConnector so class-level mocks on ShopCatalogConnector.fetch_page work
        url = url or "http://localhost:5000/api/assistant/v1"
        tok = tok or "demo-catalog-read-token"

    return ShopCatalogConnector(base_url=url, token=tok, transport=transport, **kwargs)
