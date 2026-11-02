"""
MCP Refund Server (State-Changing)
Handles refund eligibility and creation with OTP step-up verification.
Complies with Specification Section 7.3, 10 (Refund Flow), and 15.1 (Auth levels).
"""

from typing import Optional, Any
from core.ports import RefundPort
from core.models import AuthLevel
from core.policy_engine import generate_idempotency_key
from services.mcp_servers.auth import ctx_from_token


class MCPRefundServer:
    """Tool server for Refund operations."""

    def __init__(self, refund_adapter: RefundPort):
        self.refunds = refund_adapter

    async def check_refund_eligibility(
        self,
        order_id: str,
        auth_token: str,
        item_id: Optional[str] = None
    ) -> dict[str, Any]:
        """Check if an order/item is eligible for refund."""
        ctx = ctx_from_token(auth_token)
        if not ctx.level.satisfies(AuthLevel.IDENTIFIED):
            return {
                "authorized": False,
                "needs_auth": "login_required",
                "message": "Please log in to check refund eligibility."
            }

        is_eligible, reason, amount = await self.refunds.check_eligibility(
            customer_id=ctx.customer_id,
            order_id=order_id,
            item_id=item_id
        )

        return {
            "order_id": order_id,
            "is_eligible": is_eligible,
            "policy_reason": reason,
            "eligible_amount_inr": amount
        }

    async def create_refund_request(
        self,
        order_id: str,
        reason: str,
        auth_token: str,
        amount_inr: Optional[int] = None
    ) -> dict[str, Any]:
        """
        Creates a refund request.
        Requires VERIFIED session (OTP step-up).
        Enforces auto-refund under ₹2,000 vs supervisor approval over ₹2,000.
        """
        ctx = ctx_from_token(auth_token)

        # 1. Enforce Step-up OTP Verification (Section 15.1.1 & 15.1.4)
        if not ctx.level.satisfies(AuthLevel.VERIFIED):
            return {
                "authorized": False,
                "needs_auth": "otp_required",
                "message": (
                    "To process a refund for your security, we require a quick verification code. "
                    "Please enter the OTP sent to your registered mobile number."
                )
            }

        # 2. Determine refund amount if not supplied by model
        if amount_inr is None:
            _, _, max_amount = await self.refunds.check_eligibility(ctx.customer_id, order_id)
            amount_inr = max_amount

        # 3. Generate deterministic idempotency key
        idem_key = generate_idempotency_key(
            tenant_id=ctx.tenant_id,
            customer_id=ctx.customer_id,
            order_id=order_id,
            amount_inr=amount_inr
        )

        # 4. Submit refund request through adapter
        result = await self.refunds.request_refund(
            customer_id=ctx.customer_id,
            order_id=order_id,
            amount_inr=amount_inr,
            reason=reason,
            idempotency_key=idem_key
        )

        return {
            "refund_id": result.refund_id,
            "order_id": result.order_id,
            "amount_inr": result.amount_inr,
            "state": result.state.value,
            "message": result.message,
            "created_at": result.created_at.strftime("%Y-%m-%d %H:%M:%S UTC")
        }

    async def get_refund_status(self, refund_id: str, auth_token: str) -> dict[str, Any]:
        """Check status of an existing refund request."""
        ctx = ctx_from_token(auth_token)
        if not ctx.level.satisfies(AuthLevel.IDENTIFIED):
            return {
                "authorized": False,
                "needs_auth": "login_required",
                "message": "Please log in to check your refund status."
            }

        result = await self.refunds.get_status(refund_id)
        if not result or result.customer_id != ctx.customer_id:
            return {"found": False, "message": f"Refund request '{refund_id}' was not found."}

        return {
            "found": True,
            "refund_id": result.refund_id,
            "order_id": result.order_id,
            "amount_inr": result.amount_inr,
            "state": result.state.value,
            "message": result.message,
            "decided_by": result.decided_by,
            "note": result.note
        }
