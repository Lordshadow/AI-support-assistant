"""
MockShop Refund Adapter
Implements RefundPort protocol with idempotency, policy enforcement, and staff decision recording.
Complies with Specification Section 6, 7.3, and 10 (Refund flow).
"""

from datetime import datetime, timezone
from typing import Optional
import uuid

from core.models import RefundResult, RefundState, OrderStatus
from core.policy_engine import (
    check_refund_eligibility, evaluate_refund_state,
    DEFAULT_REFUND_AUTO_LIMIT_INR
)
from adapters.mockshop.order_adapter import MockOrderAdapter


class MockRefundAdapter:
    """In-memory concrete implementation of RefundPort."""

    def __init__(self, order_adapter: MockOrderAdapter, auto_limit_inr: int = DEFAULT_REFUND_AUTO_LIMIT_INR):
        self._order_adapter = order_adapter
        self._auto_limit_inr = auto_limit_inr
        self._refunds: dict[str, RefundResult] = {}
        self._idempotency_index: dict[str, str] = {}  # idempotency_key -> refund_id

    async def check_eligibility(
        self,
        customer_id: str,
        order_id: str,
        item_id: Optional[str] = None,
        customer_token: Optional[str] = None,
    ) -> tuple[bool, str, int]:
        order = await self._order_adapter.get_order(customer_id, order_id)
        if not order:
            return False, f"Order '{order_id}' was not found for this account.", 0

        return check_refund_eligibility(order, item_id=item_id, current_time=self._order_adapter.now)

    async def request_refund(
        self,
        customer_id: str,
        order_id: str,
        amount_inr: int,
        reason: str,
        idempotency_key: str,
        customer_token: Optional[str] = None,
    ) -> RefundResult:
        # 1. Idempotency Check: prevent duplicate processing on retries
        if idempotency_key in self._idempotency_index:
            existing_id = self._idempotency_index[idempotency_key]
            return self._refunds[existing_id]

        # 2. Ownership & Eligibility check
        is_eligible, policy_reason, max_amount = await self.check_eligibility(customer_id, order_id)
        now = datetime.now(timezone.utc)
        refund_id = f"REF-{uuid.uuid4().hex[:8].upper()}"

        if not is_eligible:
            result = RefundResult(
                refund_id=refund_id,
                order_id=order_id,
                customer_id=customer_id,
                amount_inr=amount_inr,
                state=RefundState.REJECTED,
                idempotency_key=idempotency_key,
                reason=reason,
                message=f"Refund request ineligible: {policy_reason}",
                created_at=now
            )
            self._refunds[refund_id] = result
            self._idempotency_index[idempotency_key] = refund_id
            return result

        # 3. Determine state: Auto-processed (<= ₹2,000) vs Pending Approval (> ₹2,000)
        state = evaluate_refund_state(amount_inr, auto_limit_inr=self._auto_limit_inr)
        if state == RefundState.PROCESSED:
            message = (
                f"Refund of ₹{amount_inr:,} has been approved automatically and initiated to your "
                f"original payment method (3–5 business days)."
            )
        else:
            message = (
                f"Refund request of ₹{amount_inr:,} exceeds the instant auto-refund limit (₹{self._auto_limit_inr:,}). "
                f"It has been submitted for senior supervisor review in the Support Desk (turnaround 24–48 hours)."
            )

        result = RefundResult(
            refund_id=refund_id,
            order_id=order_id,
            customer_id=customer_id,
            amount_inr=amount_inr,
            state=state,
            idempotency_key=idempotency_key,
            reason=reason,
            message=message,
            created_at=now
        )

        self._refunds[refund_id] = result
        self._idempotency_index[idempotency_key] = refund_id
        return result

    async def get_status(self, refund_id: str) -> Optional[RefundResult]:
        return self._refunds.get(refund_id)

    async def record_staff_decision(
        self,
        refund_id: str,
        state: RefundState,
        decided_by: str,
        note: Optional[str] = None
    ) -> RefundResult:
        """Staff Support Desk approval or rejection of a pending refund."""
        existing = self._refunds.get(refund_id)
        if not existing:
            raise KeyError(f"Refund request '{refund_id}' does not exist.")

        now = datetime.now(timezone.utc)
        updated = RefundResult(
            refund_id=existing.refund_id,
            order_id=existing.order_id,
            customer_id=existing.customer_id,
            amount_inr=existing.amount_inr,
            state=state,
            idempotency_key=existing.idempotency_key,
            reason=existing.reason,
            message=(
                f"Refund was approved by staff ({decided_by})."
                if state == RefundState.APPROVED
                else f"Refund was rejected by staff ({decided_by})."
            ),
            created_at=existing.created_at,
            decided_by=decided_by,
            decided_at=now,
            note=note
        )
        self._refunds[refund_id] = updated
        return updated
