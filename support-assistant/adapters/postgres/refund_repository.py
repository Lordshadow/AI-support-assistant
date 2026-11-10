"""
PostgreSQL Implementation of RefundPort.
Complies with Specification Sections 6, 7.3, and 10 (Refund Flow).
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
import uuid
from sqlalchemy import select, update

from core.ports import RefundPort, OrderPort
from core.models import RefundResult, RefundState
from core.policy_engine import check_refund_eligibility, evaluate_refund_state, DEFAULT_REFUND_AUTO_LIMIT_INR
from db.models import RefundRequest, Tenant
from db.session import get_async_session


class PostgresRefundRepository:
    """Implements RefundPort backed by PostgreSQL refund_requests table."""

    def __init__(
        self,
        order_port: OrderPort,
        tenant_id: str = "tenant_novaretail",
        auto_limit_inr: int = DEFAULT_REFUND_AUTO_LIMIT_INR,
    ):
        self._order_port = order_port
        self.tenant_id = tenant_id
        self._auto_limit_inr = auto_limit_inr
        # Mock payment status tracker for mock provider integration
        self._payment_transactions: dict[str, str] = {}

    def _to_domain(self, row: RefundRequest) -> RefundResult:
        state_enum = RefundState(row.state)
        if state_enum == RefundState.PROCESSED:
            msg = f"Refund of ₹{row.amount_inr:,} has been approved and processed automatically."
        elif state_enum == RefundState.PENDING_APPROVAL:
            msg = (
                f"Refund request of ₹{row.amount_inr:,} exceeds auto-approval threshold. "
                f"It has been routed to a support manager for review (Turnaround: ~24 hours)."
            )
        elif state_enum == RefundState.APPROVED:
            msg = f"Refund request has been approved by staff ({row.decided_by or 'Support Desk'})."
        elif state_enum == RefundState.REJECTED:
            msg = f"Refund request was rejected: {row.staff_note or 'Did not meet policy criteria.'}"
        else:
            msg = f"Refund status: {row.state}"

        return RefundResult(
            refund_id=row.refund_id,
            order_id=row.order_id,
            customer_id=row.customer_id,
            amount_inr=row.amount_inr,
            state=state_enum,
            idempotency_key=row.idempotency_key,
            reason=row.reason,
            message=msg,
            created_at=row.request_time,
            decided_by=row.decided_by,
            decided_at=row.decided_at,
            note=row.staff_note,
        )

    async def check_eligibility(
        self,
        customer_id: str,
        order_id: str,
        item_id: Optional[str] = None
    ) -> tuple[bool, str, Decimal | int]:
        order = await self._order_port.get_order(customer_id, order_id)
        if not order:
            return False, f"Order '{order_id}' was not found for this account.", 0

        now = datetime.now(timezone.utc)
        return check_refund_eligibility(order, item_id=item_id, current_time=now)

    async def request_refund(
        self,
        customer_id: str,
        order_id: str,
        amount_inr: Decimal | int,
        reason: str,
        idempotency_key: str
    ) -> RefundResult:
        amount_inr = Decimal(str(amount_inr)).quantize(Decimal("0.01"))
        if not amount_inr.is_finite() or amount_inr <= 0:
            raise ValueError("Refund amount must be a positive INR amount.")
        async with get_async_session(tenant_id=self.tenant_id) as session:
            # 1. Idempotency Check
            stmt = select(RefundRequest).where(
                RefundRequest.tenant_id == self.tenant_id,
                RefundRequest.idempotency_key == idempotency_key
            )
            existing = (await session.execute(stmt)).scalars().first()
            if existing:
                return self._to_domain(existing)

            # 2. Check Eligibility
            is_eligible, policy_reason, max_amount = await self.check_eligibility(customer_id, order_id)
            now = datetime.now(timezone.utc)
            refund_id = f"REF-{uuid.uuid4().hex[:8].upper()}"

            if not is_eligible:
                req = RefundRequest(
                    refund_id=refund_id,
                    tenant_id=self.tenant_id,
                    order_id=order_id,
                    customer_id=customer_id,
                    amount_inr=amount_inr,
                    state=RefundState.REJECTED.value,
                    idempotency_key=idempotency_key,
                    reason=reason,
                    request_time=now,
                    decided_by="policy_engine",
                    decided_at=now,
                    staff_note=policy_reason,
                    eligibility_snapshot={"eligible": False, "reason": policy_reason},
                )
                session.add(req)
                return self._to_domain(req)

            if amount_inr > Decimal(str(max_amount)):
                req = RefundRequest(
                    refund_id=refund_id,
                    tenant_id=self.tenant_id,
                    order_id=order_id,
                    customer_id=customer_id,
                    amount_inr=amount_inr,
                    state=RefundState.REJECTED.value,
                    idempotency_key=idempotency_key,
                    reason=reason,
                    request_time=now,
                    decided_by="policy_engine",
                    decided_at=now,
                    staff_note="Requested amount exceeds the verified eligible amount.",
                    eligibility_snapshot={"eligible": False, "reason": "amount_exceeds_eligible", "max_amount": str(max_amount)},
                )
                session.add(req)
                return self._to_domain(req)

            # 3. Determine initial state using the current tenant policy.
            tenant = await session.get(Tenant, self.tenant_id)
            cfg = (tenant.widget_config or {}) if tenant else {}
            auto_limit = Decimal(str(cfg.get("auto_refund_limit_inr", self._auto_limit_inr)))
            state = evaluate_refund_state(amount_inr, auto_limit_inr=auto_limit)
            req = RefundRequest(
                refund_id=refund_id,
                tenant_id=self.tenant_id,
                order_id=order_id,
                customer_id=customer_id,
                amount_inr=amount_inr,
                state=state.value,
                idempotency_key=idempotency_key,
                reason=reason,
                request_time=now,
                decided_by="auto_engine" if state == RefundState.PROCESSED else None,
                decided_at=now if state == RefundState.PROCESSED else None,
                eligibility_snapshot={"eligible": True, "max_amount": max_amount},
            )
            session.add(req)
            if state == RefundState.PROCESSED:
                self._payment_transactions[idempotency_key] = "paid"
            return self._to_domain(req)

    async def get_status(self, refund_id: str) -> Optional[RefundResult]:
        async with get_async_session(tenant_id=self.tenant_id) as session:
            stmt = select(RefundRequest).where(
                RefundRequest.tenant_id == self.tenant_id,
                RefundRequest.refund_id == refund_id
            )
            row = (await session.execute(stmt)).scalars().first()
            if not row:
                return None
            return self._to_domain(row)

    async def list_pending_refunds(self) -> list[RefundResult]:
        """Return tenant-scoped refund requests awaiting staff approval."""
        async with get_async_session(tenant_id=self.tenant_id) as session:
            stmt = (
                select(RefundRequest)
                .where(
                    RefundRequest.tenant_id == self.tenant_id,
                    RefundRequest.state == RefundState.PENDING_APPROVAL.value,
                )
                .order_by(RefundRequest.request_time.desc())
            )
            rows = (await session.execute(stmt)).scalars().all()
            return [self._to_domain(row) for row in rows]

    async def get_refund_metrics(self) -> dict[str, int]:
        """Return tenant-scoped refund state counts for the legacy desk API."""
        async with get_async_session(tenant_id=self.tenant_id) as session:
            stmt = select(RefundRequest.state).where(
                RefundRequest.tenant_id == self.tenant_id
            )
            states = (await session.execute(stmt)).scalars().all()
            return {
                "total": len(states),
                "auto_approved": sum(1 for state in states if state == RefundState.PROCESSED.value),
                "pending": sum(1 for state in states if state == RefundState.PENDING_APPROVAL.value),
                "staff_approved": sum(1 for state in states if state == RefundState.APPROVED.value),
                "rejected": sum(1 for state in states if state == RefundState.REJECTED.value),
            }

    async def record_staff_decision(
        self,
        refund_id: str,
        state: RefundState,
        decided_by: str,
        note: Optional[str] = None
    ) -> RefundResult:
        now = datetime.now(timezone.utc)
        async with get_async_session(tenant_id=self.tenant_id) as session:
            stmt = select(RefundRequest).where(
                RefundRequest.tenant_id == self.tenant_id,
                RefundRequest.refund_id == refund_id
            )
            row = (await session.execute(stmt)).scalars().first()
            if not row:
                raise ValueError(f"Refund '{refund_id}' does not exist.")

            row.state = state.value
            row.decided_by = decided_by
            row.decided_at = now
            row.staff_note = note
            return self._to_domain(row)

    async def process_payment(self, order_id: str, amount_inr: Decimal | int, idempotency_key: str) -> dict:
        """Call external payment gateway mock."""
        self._payment_transactions[idempotency_key] = "paid"
        return {"status": "SUCCESS", "idempotency_key": idempotency_key, "amount": amount_inr}

    async def query_payment_status(self, idempotency_key: str) -> Optional[str]:
        """Look up status from payment provider by idempotency key."""
        return self._payment_transactions.get(idempotency_key)
