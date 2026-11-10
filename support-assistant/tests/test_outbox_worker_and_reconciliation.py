"""
Test Suite: Payment Outbox Worker, Lease Recovery, Timeout Reconciliation & WhatsApp Templates.
Complies with Specification Section 10 and Section 16.3.
"""

import unittest
import asyncio
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sys
from unittest.mock import AsyncMock, patch

# Ensure support-assistant is in sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import select

from db.models import Base, RefundRequest, ConversationSession, AuditEvent, Tenant
from services.support_desk.outbox_worker import MockPaymentGateway, OutboxPaymentWorker
from core.ports import RefundPort, ChannelPort


def run_async(coro):
    return asyncio.run(coro)


class MockRefundPort:
    def __init__(self):
        self.payment_outcomes = {}  # idempotency_key -> "paid" | "failed" | "timeout"
        self.query_status_outcomes = {}

    async def process_payment(self, order_id: str, amount_inr: int, idempotency_key: str):
        outcome = self.payment_outcomes.get(idempotency_key, "paid")
        if outcome == "timeout":
            raise TimeoutError("Gateway connection timed out")
        elif outcome == "failed":
            raise RuntimeError("Card declined")
        return {"status": "SUCCESS"}

    async def query_payment_status(self, idempotency_key: str):
        return self.query_status_outcomes.get(idempotency_key)


class MockChannelPort:
    def __init__(self):
        self.sent_messages = []

    async def send_text(self, recipient_id: str, text: str) -> bool:
        self.sent_messages.append((recipient_id, text))
        return True

    async def send_quick_replies(self, recipient_id: str, prompt: str, options: list):
        return True


class TestOutboxWorkerAndReconciliation(unittest.TestCase):

    def setUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
        self.session_maker = async_sessionmaker(self.engine, expire_on_commit=False)

        async def init_schema():
            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

        run_async(init_schema())

        from db import session as db_session

        @db_session.asynccontextmanager
        async def mock_get_session(tenant_id=None):
            async with self.session_maker() as sess:
                async with sess.begin():
                    yield sess

        self.patcher = patch("services.support_desk.outbox_worker.get_async_session", side_effect=mock_get_session)
        self.patcher.start()

        self.refund_port = MockRefundPort()
        self.channel_port = MockChannelPort()
        self.worker = OutboxPaymentWorker(
            refund_port=self.refund_port,
            channel_port=self.channel_port,
            tenant_id="tenant_novaretail",
            lease_seconds=120
        )

    def tearDown(self):
        self.patcher.stop()
        run_async(self.engine.dispose())

    def test_outbox_worker_leases_and_processes_payment(self):
        """Verify worker claims approved refund, dispatches payment, marks processed."""
        now = datetime.now(timezone.utc)

        async def run_test():
            async with self.session_maker() as sess:
                async with sess.begin():
                    sess.add(Tenant(tenant_id="tenant_novaretail", name="NovaRetail"))
                    sess.add(RefundRequest(
                        refund_id="REF-OUT-1",
                        tenant_id="tenant_novaretail",
                        order_id="ORD-101",
                        customer_id="CUST-1",
                        amount_inr=3000,
                        state="approved",
                        idempotency_key="IDEM-OUT-1",
                        reason="Damaged item",
                        request_time=now
                    ))

            count = await self.worker.run_once()
            self.assertEqual(count, 1)

            # DB check: state must be 'processed' and lease cleared
            async with self.session_maker() as sess:
                refund = await sess.get(RefundRequest, "REF-OUT-1")
                self.assertEqual(refund.state, "processed")
                self.assertIsNone(refund.leased_until)

        run_async(run_test())

    def test_lease_timeout_recovery_after_worker_crash(self):
        """Verify that an expired lease from a crashed worker is safely re-claimed."""
        now = datetime.now(timezone.utc)
        expired_lease = now - timedelta(seconds=10)

        async def run_test():
            async with self.session_maker() as sess:
                async with sess.begin():
                    sess.add(Tenant(tenant_id="tenant_novaretail", name="NovaRetail"))
                    sess.add(RefundRequest(
                        refund_id="REF-CRASH-1",
                        tenant_id="tenant_novaretail",
                        order_id="ORD-102",
                        customer_id="CUST-2",
                        amount_inr=2500,
                        state="approved",
                        idempotency_key="IDEM-CRASH-1",
                        reason="Item missing accessories",
                        request_time=now,
                        leased_until=expired_lease  # simulated crash lease
                    ))

            # New worker run claims the row because lease expired
            count = await self.worker.run_once()
            self.assertEqual(count, 1)

            async with self.session_maker() as sess:
                refund = await sess.get(RefundRequest, "REF-CRASH-1")
                self.assertEqual(refund.state, "processed")

        run_async(run_test())

    def test_payment_timeout_reconciliation_never_marks_failed(self):
        """
        Verify that an ambiguous network timeout triggers status lookup by idempotency key
        and NEVER marks 'failed' on timeout.
        """
        now = datetime.now(timezone.utc)
        idem_key = "IDEM-TIMEOUT-1"
        self.refund_port.payment_outcomes[idem_key] = "timeout"
        # Gateway status query is ambiguous (returns None / pending)
        self.refund_port.query_status_outcomes[idem_key] = None

        async def run_test():
            async with self.session_maker() as sess:
                async with sess.begin():
                    sess.add(Tenant(tenant_id="tenant_novaretail", name="NovaRetail"))
                    sess.add(RefundRequest(
                        refund_id="REF-TIME-1",
                        tenant_id="tenant_novaretail",
                        order_id="ORD-103",
                        customer_id="CUST-3",
                        amount_inr=4000,
                        state="approved",
                        idempotency_key=idem_key,
                        reason="Defective display",
                        request_time=now
                    ))

            count = await self.worker.run_once()
            self.assertEqual(count, 1)

            async with self.session_maker() as sess:
                refund = await sess.get(RefundRequest, "REF-TIME-1")
                # MUST NOT be marked failed! Remains approved with backoff lease
                self.assertEqual(refund.state, "approved")
                self.assertEqual(refund.retry_count, 1)
                leased_ts = refund.leased_until if refund.leased_until.tzinfo else refund.leased_until.replace(tzinfo=timezone.utc)
                self.assertTrue(leased_ts > now)

            # Now simulate gateway confirms "paid" on next query
            self.refund_port.query_status_outcomes[idem_key] = "paid"
            # Simulate lease has elapsed
            async with self.session_maker() as sess:
                async with sess.begin():
                    r = await sess.get(RefundRequest, "REF-TIME-1")
                    r.leased_until = None

            count2 = await self.worker.run_once()
            self.assertEqual(count2, 1)

            async with self.session_maker() as sess:
                refund2 = await sess.get(RefundRequest, "REF-TIME-1")
                self.assertEqual(refund2.state, "processed")

        run_async(run_test())

    def test_whatsapp_notification_template_outside_24h_window(self):
        """Verify Spec 16.3: WhatsApp approval outside 24h uses Meta approved template."""
        now = datetime.now(timezone.utc)
        last_msg_30h_ago = now - timedelta(hours=30)

        async def run_test():
            async with self.session_maker() as sess:
                async with sess.begin():
                    sess.add(Tenant(tenant_id="tenant_novaretail", name="NovaRetail"))
                    # Conversation session on WhatsApp channel > 24 hours inactive
                    sess.add(ConversationSession(
                        conv_id="CONV-WA-1",
                        tenant_id="tenant_novaretail",
                        channel="whatsapp",
                        customer_id="CUST-WA-USER",
                        last_user_message_at=last_msg_30h_ago,
                    ))
                    sess.add(RefundRequest(
                        refund_id="REF-WA-1",
                        tenant_id="tenant_novaretail",
                        order_id="ORD-WA-88",
                        customer_id="CUST-WA-USER",
                        amount_inr=3200,
                        state="approved",
                        idempotency_key="IDEM-WA-1",
                        reason="Refund request",
                        request_time=now
                    ))

            await self.worker.run_once()

            # Verify message sent via channel port
            self.assertTrue(len(self.channel_port.sent_messages) > 0)
            recipient, msg = self.channel_port.sent_messages[0]
            self.assertEqual(recipient, "CUST-WA-USER")
            self.assertTrue(msg.startswith("template:refund_update_v1"))
            self.assertIn("order_id=ORD-WA-88", msg)

        run_async(run_test())

    def test_mock_payment_gateway_is_idempotent(self):
        async def run_test():
            gateway = MockPaymentGateway()
            first = await gateway.process_payment("ORD-QA", 1250, "idem-qa")
            second = await gateway.process_payment("ORD-QA", 1250, "idem-qa")
            self.assertEqual(first, second)
            self.assertEqual(await gateway.query_payment_status("idem-qa"), "paid")

        run_async(run_test())

    def test_worker_run_loop_writes_and_clears_heartbeat(self):
        async def run_test():
            worker = OutboxPaymentWorker(refund_port=MockRefundPort())
            stop_event = asyncio.Event()
            passes = 0

            async def one_pass():
                nonlocal passes
                passes += 1
                stop_event.set()
                return 0

            worker.run_once = one_pass
            heartbeat = Path("test_outbox_worker.heartbeat")
            await worker.run_forever(0.25, stop_event, str(heartbeat))
            self.assertEqual(passes, 1)
            self.assertFalse(heartbeat.exists())

        run_async(run_test())


if __name__ == "__main__":
    unittest.main()
