"""Regression tests for strict order ownership and storefront import safety."""
import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parent.parent))

from adapters.postgres.order_repository import PostgresOrderRepository
from core.models import OrderStatus
from core.policy_engine import check_refund_eligibility


def run_sync(coro):
    try:
        coro.send(None)
    except StopIteration as result:
        return result.value


class TestOrderImportAndOwnership(unittest.TestCase):
    def setUp(self):
        self.repo = PostgresOrderRepository(tenant_id="test")

    def make_payload(self, **overrides):
        payload = {
            "order_id": "ORD-PAISE",
            "customer_id": "3",
            "status": "delivered",
            "created_at": "2026-10-01T00:00:00+00:00",
            "delivered_at": "2026-11-01T00:00:00+00:00",
            "total": "11188.82",
            "items": [{"product_id": "P1", "name": "Camera", "category": "electronics",
                       "unit_price": "11188.82", "quantity": 1, "is_digital": False}],
        }
        payload.update(overrides)
        return payload

    def test_import_preserves_paise_and_category(self):
        order = self.repo._dict_to_domain(self.make_payload(), "3")
        self.assertEqual(order.total_amount_inr, Decimal("11188.82"))
        self.assertEqual(order.items[0].price, Decimal("11188.82"))
        self.assertEqual(order.items[0].category, "electronics")
        self.assertTrue(order.items[0].refund_eligibility_verified)

    def test_unknown_status_and_item_type_are_not_refundable(self):
        order = self.repo._dict_to_domain(self.make_payload(status="completed", delivered_at=None, items=[
            {"product_id": "P1", "name": "Mystery item", "unit_price": "50.25"}
        ]), "3")
        self.assertEqual(order.status, OrderStatus.UNKNOWN)
        self.assertIsNone(order.delivered_at)
        eligible, _, amount = check_refund_eligibility(
            order,
            current_time=datetime.now(timezone.utc),
            return_window_days=30,
            excluded_categories=[],
        )
        self.assertFalse(eligible)
        self.assertEqual(amount, 0)

    def test_missing_or_invalid_delivery_time_stays_unknown(self):
        for value in (None, "not-a-date"):
            with self.subTest(value=value):
                payload = self.make_payload(delivered_at=value)
                order = self.repo._dict_to_domain(payload, "3")
                self.assertIsNone(order.delivered_at)

    def test_store_payload_customer_mismatch_is_rejected(self):
        with self.assertRaises(ValueError):
            self.repo._dict_to_domain(self.make_payload(customer_id="1"), "3")

    def test_identities_are_not_aliases(self):
        self.assertNotEqual("1", "3")
        self.assertNotEqual("3", "CUST-42")


class TestOrderRepositoryOwnership(unittest.TestCase):
    def test_order_and_recent_list_are_strictly_customer_scoped(self):
        import adapters.postgres.order_repository as order_module

        class Result:
            def __init__(self, rows):
                self.rows = rows
            def scalars(self):
                return self
            def first(self):
                return self.rows[0] if self.rows else None
            def all(self):
                return self.rows

        class Session:
            def __init__(self):
                self.rows = [
                    type("Row", (), dict(order_id="ORD-1", tenant_id="test", customer_id="1", total_amount_inr=100,
                                          status="Delivered", created_at=datetime.now(timezone.utc), delivered_at=None,
                                          items=[], tracking_number=None, courier_name=None, shipping_address=None))(),
                    type("Row", (), dict(order_id="ORD-3", tenant_id="test", customer_id="3", total_amount_inr=300,
                                          status="Delivered", created_at=datetime.now(timezone.utc), delivered_at=None,
                                          items=[], tracking_number=None, courier_name=None, shipping_address=None))(),
                    type("Row", (), dict(order_id="ORD-CUST", tenant_id="test", customer_id="CUST-42", total_amount_inr=420,
                                          status="Delivered", created_at=datetime.now(timezone.utc), delivered_at=None,
                                          items=[], tracking_number=None, courier_name=None, shipping_address=None))(),
                ]
            async def execute(self, statement):
                params = statement.compile().params
                rows = self.rows
                for key, value in params.items():
                    if key == "order_id_1":
                        rows = [row for row in rows if row.order_id == value]
                    elif key == "customer_id_1":
                        rows = [row for row in rows if row.customer_id == value]
                    elif key.startswith("customer_id_1_"):
                        rows = [row for row in rows if row.customer_id in value]
                return Result(rows)

        class SessionContext:
            async def __aenter__(self):
                return Session()
            async def __aexit__(self, *args):
                return False

        original = order_module.get_async_session
        order_module.get_async_session = lambda **kwargs: SessionContext()
        try:
            repo = PostgresOrderRepository(tenant_id="test")
            self.assertIsNone(run_sync(repo.get_order("1", "ORD-3")))
            self.assertIsNone(run_sync(repo.get_order("3", "ORD-CUST")))
            self.assertIsNone(run_sync(repo.get_order("CUST-42", "ORD-1")))
            self.assertEqual([o.order_id for o in run_sync(repo.list_recent_orders("1"))], ["ORD-1"])
            self.assertEqual([o.order_id for o in run_sync(repo.list_recent_orders("3"))], ["ORD-3"])
            self.assertEqual([o.order_id for o in run_sync(repo.list_recent_orders("CUST-42"))], ["ORD-CUST"])
        finally:
            order_module.get_async_session = original

    def test_store_fallback_cannot_return_an_order_for_another_customer(self):
        from contextlib import asynccontextmanager
        from unittest.mock import patch
        import adapters.postgres.order_repository as order_module

        class Result:
            def scalars(self): return self
            def first(self): return None
            def all(self): return []

        class Session:
            async def execute(self, statement): return Result()
            async def get(self, *args): return None
            def add(self, row): pass
            async def commit(self): pass

        @asynccontextmanager
        async def session_scope(**kwargs):
            yield Session()

        payload = {
            "order_id": "ORD-LEAK", "customer_id": "1", "status": "Delivered",
            "created_at": "2026-11-01T00:00:00+00:00", "delivered_at": "2026-11-02T00:00:00+00:00",
            "total": "10.25", "items": [{"name": "Item", "category": "electronics", "price": "10.25"}],
        }

        class Response:
            status_code = 200
            def json(self): return {"order": payload}

        class Client:
            def __init__(self, **kwargs): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *args): return False
            async def get(self, *args, **kwargs): return Response()

        original_session = order_module.get_async_session
        order_module.get_async_session = session_scope
        try:
            repo = PostgresOrderRepository("test", store_api_url="https://store.invalid", store_api_token="token")
            with patch.object(order_module.httpx, "AsyncClient", Client):
                self.assertIsNone(run_sync(repo.get_order("3", "ORD-LEAK")))
        finally:
            order_module.get_async_session = original_session

    def test_storefront_order_lookup_forwards_signed_token_and_skips_local_cache(self):
        from unittest.mock import patch
        import adapters.postgres.order_repository as order_module

        payload = {
            "order_id": "ORD-LIVE-1", "customer_id": "7", "status": "Processing",
            "created_at": "2026-11-10T00:00:00+00:00", "total": "25.00",
            "items": [{"product_id": "P1", "name": "Demo item", "category": "electronics", "unit_price": "25.00", "quantity": 1}],
        }

        class Response:
            status_code = 200
            def json(self): return {"order": payload}

        class Client:
            params = None
            def __init__(self, **kwargs): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *args): return False
            async def get(self, url, **kwargs):
                self.__class__.params = kwargs["params"]
                return Response()

        repo = PostgresOrderRepository("test", store_api_url="https://store.invalid", store_api_token="machine-token")
        with patch.object(order_module.httpx, "AsyncClient", Client), \
             patch.object(order_module, "get_async_session", side_effect=AssertionError("must not trust local cache for storefront token")):
            order = run_sync(repo.get_order("7", "ORD-LIVE-1", customer_token="signed-customer-token"))

        self.assertEqual(order.order_id, "ORD-LIVE-1")
        self.assertEqual(Client.params["customer_id"], "7")
        self.assertEqual(Client.params["customer_token"], "signed-customer-token")

    def test_rejected_storefront_token_does_not_fall_back_to_cached_order(self):
        from unittest.mock import patch
        import adapters.postgres.order_repository as order_module

        class Response:
            status_code = 404

        class Client:
            def __init__(self, **kwargs): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *args): return False
            async def get(self, *args, **kwargs): return Response()

        repo = PostgresOrderRepository("test", store_api_url="https://store.invalid", store_api_token="machine-token")
        with patch.object(order_module.httpx, "AsyncClient", Client), \
             patch.object(order_module, "get_async_session", side_effect=AssertionError("rejected tokens must not read cached orders")):
            order = run_sync(repo.get_order("7", "ORD-LIVE-1", customer_token="rejected-token"))

        self.assertIsNone(order)


if __name__ == "__main__":
    unittest.main()
