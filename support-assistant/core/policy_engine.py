"""
Deterministic Business Policy Engine for Customer Support Assistant
Complies with Specification Sections 1.3, 10 (Refund Flow), and 15.1 (Auth & Ownership).

"The LLM understands and phrases. Code decides and acts."
All rules regarding money, identity, and permissions are enforced here in pure Python.
"""

import hashlib
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Optional

try:
    from core.models import (
        SessionContext, AuthLevel, Order, OrderStatus, OrderItem,
        RefundState, AuthLevelError, OwnershipError, PolicyViolationError
    )
except ImportError:
    from .models import (
        SessionContext, AuthLevel, Order, OrderStatus, OrderItem,
        RefundState, AuthLevelError, OwnershipError, PolicyViolationError
    )


# Tenant-level default policy constants (Configurable)
DEFAULT_RETURN_WINDOW_DAYS = 30
DEFAULT_REFUND_AUTO_LIMIT_INR = 2000
DEFAULT_MONTHLY_REFUND_CAP_INR = 5000


def require_level(ctx: SessionContext, required_level: AuthLevel) -> None:
    """
    Enforce that the session context meets or exceeds the required auth level.
    Raises AuthLevelError if insufficient.
    """
    if not ctx.level.satisfies(required_level):
        raise AuthLevelError(
            f"Action requires '{required_level.value}' level, but current level is '{ctx.level.value}'. "
            f"Requires {'login' if required_level == AuthLevel.IDENTIFIED else 'OTP verification'}."
        )


def verify_order_ownership(ctx: SessionContext, order: Order) -> None:
    """
    Enforce that the order strictly belongs to the customer in SessionContext.
    Prevents horizontal privilege escalation and order enumeration.
    """
    if not ctx.customer_id:
        raise AuthLevelError("Customer ID is missing from session context.")
    if order.customer_id != ctx.customer_id:
        # Generic message to avoid order number probing
        raise OwnershipError(f"Order '{order.order_id}' was not found for this account.")


def check_refund_eligibility(
    order: Order,
    item_id: Optional[str] = None,
    current_time: Optional[datetime] = None,
    return_window_days: int = DEFAULT_RETURN_WINDOW_DAYS
) -> tuple[bool, str, int]:
    """
    Pure deterministic eligibility verification:
    1. Order must be in DELIVERED status.
    2. Digital goods and gift cards are strictly non-refundable.
    3. Items cannot be refunded more than once.
    4. Must fall within the return window (30 days from delivery).

    Returns:
        tuple[is_eligible: bool, policy_reason: str, eligible_amount_inr: int]
    """
    if order.status != OrderStatus.DELIVERED:
        return (
            False,
            f"Order status is '{order.status.value}'. Refunds can only be requested for delivered orders.",
            0
        )

    now = current_time or datetime.now(timezone.utc)
    if order.delivered_at is None:
        return False, "Order delivery timestamp is missing. Please contact human support.", 0

    # Ensure timezone awareness for comparison
    delivered_at = order.delivered_at
    if delivered_at.tzinfo is None:
        delivered_at = delivered_at.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    # 1. Return window check
    elapsed = now - delivered_at
    if elapsed < timedelta(0):
        return False, "Order delivery timestamp is in the future. Please contact human support.", 0
    if elapsed > timedelta(days=return_window_days):
        days_past = elapsed.days
        return (
            False,
            f"Return window expired. Orders can only be returned within {return_window_days} days of delivery (delivered {days_past} days ago).",
            0
        )

    # 2. Check item-level policies
    target_items: list[OrderItem] = []
    if item_id:
        matched = [i for i in order.items if i.item_id == item_id]
        if not matched:
            return False, f"Item '{item_id}' not found in order '{order.order_id}'.", 0
        target_items = matched
    else:
        target_items = order.items

    # 3. Check digital goods & previous refund status
    eligible_amount = Decimal("0.00")
    for item in target_items:
        if item.is_refunded:
            return (
                False,
                f"Item '{item.product_name}' has already been refunded.",
                0
            )
        if not item.refund_eligibility_verified:
            return False, f"Refund eligibility details for '{item.product_name}' could not be verified. Please contact human support.", 0
        if item.is_digital or item.category.lower() == "digital":
            return (
                False,
                f"Item '{item.product_name}' is a digital product / gift card and is non-refundable once delivered under Store Policy 6.0.",
                0
            )
        eligible_amount += Decimal(str(item.price)) * item.quantity

    if eligible_amount <= 0:
        return False, "No eligible items for refund.", 0

    return True, "Order meets all return window and product policy requirements.", eligible_amount


def evaluate_refund_state(
    amount_inr: Decimal | int,
    auto_limit_inr: Decimal | int = DEFAULT_REFUND_AUTO_LIMIT_INR
) -> RefundState:
    """
    Determine whether refund can be auto-processed or requires executive approval:
    - Amount <= auto_limit_inr (e.g. ₹2,000) -> PROCESSED
    - Amount > auto_limit_inr               -> PENDING_APPROVAL
    """
    if Decimal(str(amount_inr)) <= Decimal(str(auto_limit_inr)):
        return RefundState.PROCESSED
    return RefundState.PENDING_APPROVAL


def generate_idempotency_key(
    tenant_id: str,
    customer_id: str,
    order_id: str,
    amount_inr: int,
    item_id: Optional[str] = None
) -> str:
    """
    Generate deterministic idempotency key for payment gateway safety.
    Prevents double-charging or double-refunding across network retries.
    """
    amount_key = format(Decimal(str(amount_inr)).quantize(Decimal("0.01")), "f")
    raw = f"{tenant_id}:{customer_id}:{order_id}:{item_id or 'all'}:{amount_key}"
    return "ref_idem_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
