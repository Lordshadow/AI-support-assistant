import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
import os
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from adapters.postgres.refund_repository import PostgresRefundRepository
from core.models import Order, OrderItem, OrderStatus, RefundState


class FakeOrderPort:
    def __init__(self):
        now = datetime.now(timezone.utc)
        self.order = Order(
            order_id="ORD-TEST-123",
            customer_id="42",
            items=[OrderItem(
                item_id="ORD-TEST-123-ITM-1",
                product_id="551",
                product_name="Mulberry",
                category="Groceries",
                price=Decimal("607.38"),
                quantity=1,
                is_digital=False,
                refund_eligibility_verified=True,
            )],
            total_amount_inr=Decimal("607.38"),
            status=OrderStatus.DELIVERED,
            created_at=now,
            delivered_at=now,
        )

    async def get_order(self, customer_id, order_id, customer_token=None):
        return self.order if str(customer_id) == "42" and order_id == self.order.order_id else None


class FakeSession:
    def __init__(self):
        self.added = []

    async def execute(self, _stmt):
        return SimpleNamespace(scalars=lambda: SimpleNamespace(first=lambda: None))

    async def get(self, _model, _tenant_id):
        return SimpleNamespace(widget_config={"auto_refund_limit_inr": 2000})

    def add(self, row):
        self.added.append(row)


class StorefrontRefundIntegrationTests(unittest.TestCase):
    def test_auto_processed_row_has_no_non_staff_decided_by_actor(self):
        session = FakeSession()
        repo = PostgresRefundRepository(FakeOrderPort(), tenant_id="ApexStore")
        repo._create_storefront_refund = AsyncMock(return_value={
            "id": 17,
            "amount": 607.38,
            "status": "Processed",
        })

        @asynccontextmanager
        async def fake_session(*, tenant_id):
            self.assertEqual(tenant_id, "ApexStore")
            yield session

        with patch("adapters.postgres.refund_repository.get_async_session", fake_session):
            result = asyncio.run(repo.request_refund(
                customer_id="42",
                order_id="ORD-TEST-123",
                amount_inr=Decimal("607.38"),
                reason="The product was damaged.",
                idempotency_key="return-idem-60738",
                customer_token="signed-customer-token",
                storefront_verification_token="order-scoped-otp-token",
            ))

        self.assertEqual(result.state, RefundState.PROCESSED)
        self.assertEqual(result.amount_inr, Decimal("607.38"))
        self.assertEqual(len(session.added), 1)
        self.assertIsNone(session.added[0].decided_by)
        self.assertEqual(session.added[0].eligibility_snapshot["storefront_refund_id"], "17")
        repo._create_storefront_refund.assert_awaited_once()

    def test_storefront_api_receives_order_items_reason_and_idempotency(self):
        repo = PostgresRefundRepository(FakeOrderPort(), tenant_id="ApexStore")
        calls = []

        class FakeResponse:
            status_code = 201
            def json(self):
                return {"refund": {"id": 17, "amount": 607.38, "status": "Processed"}}

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *_args):
                return None
            async def post(self, url, headers, json):
                calls.append((url, headers, json))
                return FakeResponse()

        with patch.dict(os.environ, {
            "APEXSTORE_CATALOG_API_URL": "http://store.test/api/assistant/v1",
            "APEXSTORE_CATALOG_API_TOKEN": "service-token",
        }), patch("httpx.AsyncClient", FakeClient):
            result = asyncio.run(repo._create_storefront_refund(
                customer_id="42",
                order_id="ORD-TEST-123",
                reason="The product was damaged.",
                idempotency_key="return-idem-60738",
                customer_token="signed-customer-token",
                verification_token="order-scoped-otp-token",
            ))

        self.assertEqual(result, {"id": 17, "amount": 607.38, "status": "Processed"})
        self.assertEqual(calls[0][0], "http://store.test/api/assistant/v1/refunds")
        self.assertEqual(calls[0][1]["Idempotency-Key"], "return-idem-60738")
        self.assertEqual(calls[0][2]["reason"], "The product was damaged.")
        self.assertEqual(calls[0][2]["items"], [{"product_id": 551, "quantity": 1}])


if __name__ == "__main__":
    unittest.main()
