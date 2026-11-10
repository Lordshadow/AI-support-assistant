"""
Payment Outbox Worker Daemon (Spec 10, 16.3).
Claims approved refund rows using FOR UPDATE SKIP LOCKED with 120-second lease timeout.
Reconciles ambiguous timeouts by idempotency key and dispatches Meta WhatsApp templates.
"""

import asyncio
import logging
import os
import signal
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List

from sqlalchemy import select, update, text
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import RefundRequest, ConversationSession, AuditEvent
from db.session import get_async_session
from core.ports import ChannelPort, RefundPort

logger = logging.getLogger(__name__)


class OutboxPaymentWorker:
    """Daemon leasing and processing approved refunds acting as the transactional outbox."""

    def __init__(
        self,
        refund_port: RefundPort,
        channel_port: Optional[ChannelPort] = None,
        tenant_id: str = "tenant_novaretail",
        lease_seconds: int = 120,
    ):
        self.refund_port = refund_port
        self.channel_port = channel_port
        self.tenant_id = tenant_id
        self.lease_seconds = lease_seconds
        self._running = False

    async def claim_next_approved_refund(self, session: AsyncSession) -> Optional[RefundRequest]:
        """
        Claims exactly one approved refund using FOR UPDATE SKIP LOCKED.
        Protects against crashed workers via lease expiration.
        """
        now = datetime.now(timezone.utc)
        is_postgres = session.bind.dialect.name == "postgresql"

        stmt = (
            select(RefundRequest)
            .where(
                RefundRequest.tenant_id == self.tenant_id,
                RefundRequest.state == "approved",
                (RefundRequest.leased_until == None) | (RefundRequest.leased_until < now)
            )
            .limit(1)
        )
        if is_postgres:
            stmt = stmt.with_for_update(skip_locked=True)

        result = await session.execute(stmt)
        refund = result.scalars().first()
        if not refund:
            return None

        # Stamp lease timeout with conditional update for multi-worker safety
        lease_deadline = now + timedelta(seconds=self.lease_seconds)
        stmt_lease = (
            update(RefundRequest)
            .where(
                RefundRequest.refund_id == refund.refund_id,
                RefundRequest.state == "approved",
                (RefundRequest.leased_until == None) | (RefundRequest.leased_until < now)
            )
            .values(leased_until=lease_deadline)
            .execution_options(synchronize_session=False)
        )
        res = await session.execute(stmt_lease)
        if res.rowcount != 1:
            return None
        refund.leased_until = lease_deadline
        await session.flush()
        return refund

    async def process_claimed_refund(self, refund_id: str, session: AsyncSession) -> Dict[str, Any]:
        """
        Dispatches payment to gateway and notifies customer.
        Reconciles network timeouts via stored idempotency key.
        """
        now = datetime.now(timezone.utc)
        refund = await session.get(RefundRequest, refund_id)
        if not refund or refund.state != "approved":
            return {"status": "skipped", "reason": "Not in approved state"}

        # 1. Dispatch payment via RefundPort
        payment_status = None
        try:
            payment_res = await self.refund_port.process_payment(
                order_id=refund.order_id,
                amount_inr=refund.amount_inr,
                idempotency_key=refund.idempotency_key
            )
            payment_status = "paid"
        except TimeoutError:
            # Spec Rule: A timeout is ambiguous. Query gateway by idempotency key!
            payment_status = await self.refund_port.query_payment_status(refund.idempotency_key)
        except Exception as e:
            # Gateway rejected
            payment_status = "failed"

        # 2. Update state based on reconciliation
        if payment_status == "paid":
            refund.state = "processed"
            refund.leased_until = None
            audit_action = "payment_dispatched"
        elif payment_status == "failed":
            refund.state = "failed"
            refund.leased_until = None
            audit_action = "payment_failed"
        else:
            # Ambiguous timeout: back off lease, NEVER mark failed
            refund.retry_count += 1
            backoff_sec = min(300, 30 * (2 ** min(refund.retry_count, 4)))
            refund.leased_until = now + timedelta(seconds=backoff_sec)
            audit_action = "payment_timeout_requeued"
            await session.flush()
            return {"status": "requeued", "retry_count": refund.retry_count}

        # 3. Log audit event
        import uuid
        audit = AuditEvent(
            event_id=f"AUD-{refund.refund_id}-{uuid.uuid4().hex[:8]}",
            tenant_id=self.tenant_id,
            actor_id="system_outbox_worker",
            actor_role="system",
            action=audit_action,
            resource_type="refund_request",
            resource_id=refund.refund_id,
            details={"payment_status": payment_status, "idempotency_key": refund.idempotency_key},
            timestamp=now
        )
        session.add(audit)

        # 4. Customer Notification (Meta WhatsApp Template guard - Spec 16.3)
        if self.channel_port and refund.state == "processed":
            await self._dispatch_customer_notification(refund, session)

        await session.flush()
        return {"status": refund.state, "refund_id": refund.refund_id}

    async def _dispatch_customer_notification(self, refund: RefundRequest, session: AsyncSession):
        now = datetime.now(timezone.utc)
        # Check conversation session for channel and last user activity
        stmt = (
            select(ConversationSession)
            .where(
                ConversationSession.tenant_id == self.tenant_id,
                ConversationSession.customer_id == refund.customer_id
            )
            .order_by(ConversationSession.last_user_message_at.desc())
        )
        conv = (await session.execute(stmt)).scalars().first()

        if conv and conv.channel == "whatsapp":
            last_msg_ts = conv.last_user_message_at
            if last_msg_ts.tzinfo is None:
                last_msg_ts = last_msg_ts.replace(tzinfo=timezone.utc)
            elapsed = now - last_msg_ts
            if elapsed > timedelta(hours=24):
                # Outside 24-hour customer care window: MUST use pre-approved WhatsApp template
                msg = (
                    f"template:refund_update_v1 "
                    f"parameters:[order_id={refund.order_id}, amount_inr={refund.amount_inr:,}]"
                )
            else:
                msg = f"Your refund of ₹{refund.amount_inr:,} for order {refund.order_id} has been processed successfully."
        else:
            msg = f"Your refund of ₹{refund.amount_inr:,} for order {refund.order_id} has been processed successfully."

        try:
            await self.channel_port.send_text(refund.customer_id, msg)
            refund.notified_at = now
        except Exception:
            pass  # Notification failure should not roll back processed payment

    async def run_once(self) -> int:
        """Runs one polling pass. Returns count of processed items."""
        processed_count = 0
        async with get_async_session(tenant_id=self.tenant_id) as session:
            claimed = await self.claim_next_approved_refund(session)
            if claimed:
                await self.process_claimed_refund(claimed.refund_id, session)
                processed_count += 1
        return processed_count

    async def run_forever(
        self,
        poll_interval: float = 2.0,
        stop_event: Optional[asyncio.Event] = None,
        heartbeat_path: str = "/tmp/outbox-worker.heartbeat",
    ) -> None:
        """Poll until stopped; only advance readiness after a successful DB pass."""
        stop_event = stop_event or asyncio.Event()
        heartbeat = Path(heartbeat_path)
        while not stop_event.is_set():
            try:
                await self.run_once()
                heartbeat.touch()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Outbox worker polling pass failed")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=poll_interval)
            except asyncio.TimeoutError:
                continue
        heartbeat.unlink(missing_ok=True)


class MockPaymentGateway:
    """Local-only idempotent payment port; never contacts an external provider."""

    def __init__(self) -> None:
        self._payments: dict[str, dict[str, Any]] = {}

    async def process_payment(
        self, order_id: str, amount_inr: int, idempotency_key: str
    ) -> dict[str, Any]:
        return self._payments.setdefault(
            idempotency_key,
            {"status": "paid", "order_id": order_id, "amount_inr": amount_inr},
        )

    async def query_payment_status(self, idempotency_key: str) -> str:
        payment = self._payments.get(idempotency_key)
        return payment["status"] if payment else "unknown"


async def _run_service() -> None:
    poll_interval = max(0.25, float(os.getenv("OUTBOX_POLL_INTERVAL", "2")))
    tenant_id = os.getenv("TENANT_ID", "tenant_novaretail")
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    worker = OutboxPaymentWorker(
        refund_port=MockPaymentGateway(),
        tenant_id=tenant_id,
    )
    await worker.run_forever(poll_interval=poll_interval, stop_event=stop_event)


if __name__ == "__main__":
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    asyncio.run(_run_service())
