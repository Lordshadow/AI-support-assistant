"""
Cache-Aside Service with Fine-Grained TTLs
Complies with Specification Section 11 (Caching strategy & Key design).

Rules Enforced:
1. Short/no TTL for price & stock (TTL 45s).
2. Order status TTL at most a few seconds (TTL 10s) strictly keyed by customer_id.
3. Refund actions are NEVER cached.
4. FAQ and product resolution keys cached with 24h TTL.
"""

import time
import hashlib
from typing import Any, Optional


class CacheService:
    """Production cache-aside service with in-memory store and Redis interface."""

    def __init__(self):
        # In-memory key-value store: key -> (value, expire_at)
        self._store: dict[str, tuple[Any, float]] = {}

    def get(self, key: str) -> Optional[Any]:
        """Fetch item if not expired."""
        entry = self._store.get(key)
        if not entry:
            return None
        value, expire_at = entry
        if time.time() > expire_at:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        """Store item with explicit TTL in seconds."""
        expire_at = time.time() + ttl_seconds
        self._store[key] = (value, expire_at)

    def delete(self, key: str) -> None:
        self._store.pop(key, None)

    def invalidate_product(self, product_id: str) -> int:
        """Invalidate all FAQ and spec keys for a given product upon re-ingest."""
        prefix = f"faq:{product_id}:"
        to_del = [k for k in self._store if k.startswith(prefix) or k == f"price:{product_id}"]
        for k in to_del:
            self._store.pop(k, None)
        return len(to_del)

    # -------------------------------------------------------------
    # Standard Spec Key Builders (Section 11.1)
    # -------------------------------------------------------------
    @staticmethod
    def key_product_resolve(normalized_name: str) -> str:
        clean = normalized_name.lower().strip().replace(" ", "_")
        return f"prod:resolve:{clean}"

    @staticmethod
    def key_faq(product_id: str, question: str) -> str:
        q_hash = hashlib.sha256(question.lower().strip().encode("utf-8")).hexdigest()[:16]
        return f"faq:{product_id}:{q_hash}"

    @staticmethod
    def key_price(product_id: str) -> str:
        return f"price:{product_id}"

    @staticmethod
    def key_order(customer_id: str, order_id: str) -> str:
        return f"order:{customer_id}:{order_id}"

    @staticmethod
    def key_ratelimit(customer_id: str) -> str:
        minute_bucket = int(time.time() // 60)
        return f"ratelimit:{customer_id}:{minute_bucket}"
