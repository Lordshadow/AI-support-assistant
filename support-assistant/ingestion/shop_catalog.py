"""Read-only clients for configured catalog APIs and the local MockShop."""

import asyncio
import math
import os
import random
import re
import threading
import time
from typing import Any, Dict, List, Protocol
from urllib.parse import urlsplit

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


def _read_path(value: Any, path: str) -> Any:
    """Read a simple dot-separated object path; an empty path means the root."""
    if not path or path == ".":
        return value
    current = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _env_value(name: str, legacy_name: str | None = None, default: str = "") -> str:
    value = os.getenv(name)
    if value:
        return value
    if legacy_name:
        value = os.getenv(legacy_name)
        if value:
            return value
    return default


class RestCatalogConnector:
    """Fetch a paginated catalog through a generic, read-only REST API.

    The connector supports configurable endpoint/JSON paths, page query parameters,
    token authentication, common pagination headers, and the canonical product
    field aliases normalized by ``CatalogProduct``. APIs with cursor pagination or
    a substantially different product schema need a source adapter or API facade.
    """

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        *,
        timeout_seconds: float | None = None,
        max_attempts: int | None = None,
        requests_per_second: float | None = None,
        endpoint_path: str | None = None,
        products_path: str | None = None,
        total_path: str | None = None,
        total_pages_path: str | None = None,
        page_param: str | None = None,
        page_size_param: str | None = None,
        page_size: int | None = None,
        total_header: str | None = None,
        total_pages_header: str | None = None,
        auth_mode: str | None = None,
        token_header: str | None = None,
    ):
        if base_url is not None or token is not None:
            configured_url = base_url if base_url is not None else _env_value(
                "CATALOG_API_URL", "APEXSTORE_CATALOG_API_URL")
            configured_token = token if token is not None else _env_value(
                "CATALOG_API_TOKEN", "APEXSTORE_CATALOG_API_TOKEN")
        else:
            generic_url = os.getenv("CATALOG_API_URL", "").strip()
            generic_token = os.getenv("CATALOG_API_TOKEN", "").strip()
            if generic_url or generic_token:
                # Never mix a new provider's token with a legacy ApexStore URL (or vice versa).
                configured_url, configured_token = generic_url, generic_token
            else:
                configured_url = os.getenv("APEXSTORE_CATALOG_API_URL", "")
                configured_token = os.getenv("APEXSTORE_CATALOG_API_TOKEN", "")
        self.base_url = configured_url.strip().rstrip("/")
        self.token = configured_token.strip()
        self.endpoint_path = (endpoint_path or _env_value("CATALOG_API_PATH", default="catalog/export")).strip()
        self.products_path = (products_path if products_path is not None else
                              _env_value("CATALOG_API_PRODUCTS_PATH", default="products")).strip()
        self.total_path = (total_path if total_path is not None else
                           _env_value("CATALOG_API_TOTAL_PATH", default="pagination.total")).strip()
        self.total_pages_path = (total_pages_path if total_pages_path is not None else
                                 _env_value("CATALOG_API_TOTAL_PAGES_PATH", default="pagination.total_pages")).strip()
        self.page_param = (page_param or _env_value("CATALOG_API_PAGE_PARAM", default="page")).strip()
        self.page_size_param = (page_size_param or
                                _env_value("CATALOG_API_PAGE_SIZE_PARAM", default="limit")).strip()
        self.total_header = (total_header if total_header is not None else
                             _env_value("CATALOG_API_TOTAL_HEADER")).strip()
        self.total_pages_header = (total_pages_header if total_pages_header is not None else
                                   _env_value("CATALOG_API_TOTAL_PAGES_HEADER")).strip()
        self.auth_mode = (auth_mode or _env_value("CATALOG_API_AUTH_MODE", default="bearer")).strip().lower()
        self.token_header = (token_header or _env_value("CATALOG_API_TOKEN_HEADER", default="X-API-Key")).strip()
        self.transport = transport
        self.timeout_seconds = (timeout_seconds if timeout_seconds is not None else float(_env_value(
            "CATALOG_API_TIMEOUT_SECONDS", "APEXSTORE_CATALOG_TIMEOUT_SECONDS", "30")))
        self.max_attempts = (max_attempts if max_attempts is not None else int(_env_value(
            "CATALOG_API_MAX_ATTEMPTS", "APEXSTORE_CATALOG_MAX_ATTEMPTS", "4")))
        self.requests_per_second = (requests_per_second if requests_per_second is not None else float(_env_value(
            "CATALOG_API_REQUESTS_PER_SECOND", "APEXSTORE_CATALOG_REQUESTS_PER_SECOND", "2")))
        self.page_size = page_size if page_size is not None else int(_env_value("CATALOG_API_PAGE_SIZE", default="100"))
        self._last_request_at = 0.0
        self._latencies_ms: list[float] = []
        if (self.timeout_seconds <= 0 or self.max_attempts < 1 or self.requests_per_second <= 0
                or not 1 <= self.page_size <= 100):
            raise ValueError("Catalog timeout, attempts, rate, and page size must be within supported bounds.")
        if not self.page_param or not self.page_size_param or self.page_param == self.page_size_param:
            raise ValueError("Catalog page and page-size query parameter names must be distinct and non-empty.")
        if not self.endpoint_path or self.endpoint_path.startswith(("http://", "https://")):
            raise ValueError("CATALOG_API_PATH must be a relative path under CATALOG_API_URL.")
        endpoint = urlsplit(self.endpoint_path)
        if endpoint.netloc or endpoint.query or endpoint.fragment:
            raise ValueError("CATALOG_API_PATH cannot contain a host, query, or fragment.")
        if not self.base_url:
            raise RuntimeError("CATALOG_API_URL is not configured.")
        parsed_base = urlsplit(self.base_url)
        if parsed_base.scheme not in {"http", "https"} or not parsed_base.hostname:
            raise ValueError("CATALOG_API_URL must be an absolute HTTP or HTTPS URL.")
        if parsed_base.username or parsed_base.password or parsed_base.query or parsed_base.fragment:
            raise ValueError("CATALOG_API_URL cannot contain credentials, a query, or a fragment.")
        if self.auth_mode not in {"bearer", "header", "basic", "none"}:
            raise ValueError("CATALOG_API_AUTH_MODE must be bearer, header, basic, or none.")
        if self.auth_mode != "none" and not self.token:
            raise RuntimeError("CATALOG_API_TOKEN is not configured.")
        if self.auth_mode == "basic" and (":" not in self.token or not all(self.token.split(":", 1))):
            raise ValueError("Basic authentication requires CATALOG_API_TOKEN in username:password format.")
        if self.auth_mode == "header" and not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", self.token_header):
            raise ValueError("CATALOG_API_TOKEN_HEADER is not a valid HTTP header name.")

    def _auth(self) -> tuple[dict[str, str], tuple[str, str] | None]:
        if self.auth_mode == "bearer":
            return {"Authorization": f"Bearer {self.token}"}, None
        if self.auth_mode == "header":
            return {self.token_header: self.token}, None
        if self.auth_mode == "basic":
            username, password = self.token.split(":", 1)
            return {}, (username, password)
        return {}, None

    @staticmethod
    def _optional_int(value: Any, label: str) -> int | None:
        if value is None or value == "":
            return None
        try:
            result = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Configured catalog API returned an invalid {label}.") from exc
        if result < 0:
            raise ValueError(f"Configured catalog API returned a negative {label}.")
        return result

    async def fetch_page(self, page: int = 1, limit: int = 100) -> Dict[str, Any]:
        if page < 1:
            raise ValueError("Catalog page numbers start at 1.")
        url = f"{self.base_url}/{self.endpoint_path.lstrip('/')}"
        timeout = httpx.Timeout(self.timeout_seconds, connect=min(5.0, self.timeout_seconds))
        auth_headers, basic_auth = self._auth()
        async with httpx.AsyncClient(timeout=timeout, transport=self.transport) as client:
            response = None
            for attempt in range(self.max_attempts):
                await self._pace_request()
                started = time.monotonic()
                try:
                    response = await client.get(
                        url,
                        params={self.page_param: page,
                                self.page_size_param: min(max(limit, 1), 100)},
                        headers=auth_headers,
                        auth=basic_auth,
                    )
                    self._latencies_ms.append((time.monotonic() - started) * 1000)
                    if response.status_code not in (408, 425, 429) and response.status_code < 500:
                        response.raise_for_status()
                        break
                    if attempt == self.max_attempts - 1:
                        response.raise_for_status()
                except (httpx.TimeoutException, httpx.NetworkError):
                    if attempt == self.max_attempts - 1:
                        raise RuntimeError("Configured catalog API request failed after retries.") from None
                await asyncio.sleep(self._retry_delay(attempt, response))
            if response is None:
                raise RuntimeError("Configured catalog API request failed after retries.")
            try:
                payload = response.json()
            except ValueError as exc:
                raise ValueError("Configured catalog API returned invalid JSON.") from exc
            products = _read_path(payload, self.products_path)
            if not isinstance(products, list):
                raise ValueError("Configured catalog API product path did not resolve to a list.")
            total = _read_path(payload, self.total_path) if self.total_path else None
            total_pages = _read_path(payload, self.total_pages_path) if self.total_pages_path else None
            if self.total_header:
                total = response.headers.get(self.total_header, total)
            if self.total_pages_header:
                total_pages = response.headers.get(self.total_pages_header, total_pages)
            normalized_total = self._optional_int(total, "total")
            normalized_pages = self._optional_int(total_pages, "total pages")
            if normalized_pages is not None and normalized_pages > 10000:
                raise ValueError("Configured catalog API reports an unsafe page count.")
        return {"products": products,
                "pagination": {"total": normalized_total, "total_pages": normalized_pages,
                               "page": page, "limit": min(max(limit, 1), 100)}}

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
        first = await self.fetch_page(page=1, limit=self.page_size)
        pagination = first.get("pagination") or {}
        products = list(first["products"])
        total_pages = pagination.get("total_pages")
        expected_total = pagination.get("total")
        seen_ids: set[str] = set()

        def remember_ids(page_products: list[Any]) -> None:
            for item in page_products:
                if not isinstance(item, dict):
                    continue
                product_id = item.get("product_id") or item.get("id")
                if product_id is None:
                    continue  # The normalizer will record a bounded, item-level validation failure.
                stable_id = str(product_id).strip()
                if stable_id in seen_ids:
                    raise ValueError("Configured catalog API returned a product ID more than once across pages.")
                seen_ids.add(stable_id)

        remember_ids(first["products"])
        page = 2
        while (page <= total_pages if total_pages is not None else
               len(first["products"]) == self.page_size):
            if page > 10000:
                raise ValueError("Configured catalog API reports an unsafe page count.")
            result = await self.fetch_page(page=page, limit=self.page_size)
            remember_ids(result["products"])
            products.extend(result["products"])
            if total_pages is None and len(result["products"]) < self.page_size:
                break
            page += 1
        if expected_total is not None and len(products) != expected_total:
            raise ValueError(
                f"Configured catalog API export was incomplete ({len(products)} of {expected_total} products)."
            )
        return products


# Backward-compatible import name used by existing tests and integrations.
ShopCatalogConnector = RestCatalogConnector


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

    """Return the configured REST adapter, or fail clearly if it is not configured."""
    return RestCatalogConnector(base_url=base_url, token=token, transport=transport, **kwargs)
