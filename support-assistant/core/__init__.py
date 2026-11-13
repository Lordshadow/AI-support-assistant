"""
Customer Support Core Domain Module
"""

from .models import (
    AuthLevel,
    SessionContext,
    ProductMatch,
    ProductSpecs,
    PriceInfo,
    ProductSummary,
    OrderItem,
    OrderStatus,
    TrackingEvent,
    Order,
    RefundState,
    RefundResult,
    CoreSecurityError,
    AuthLevelError,
    OwnershipError,
    PolicyViolationError,
)

from .ports import (
    OrderPort,
    CatalogPort,
    RefundPort,
    ChannelPort,
    SpeechPort,
)

from .policy_engine import (
    DEFAULT_REFUND_AUTO_LIMIT_INR,
    DEFAULT_MONTHLY_REFUND_CAP_INR,
    require_level,
    verify_order_ownership,
    check_refund_eligibility,
    evaluate_refund_state,
    generate_idempotency_key,
)

__all__ = [
    "AuthLevel",
    "SessionContext",
    "ProductMatch",
    "ProductSpecs",
    "PriceInfo",
    "ProductSummary",
    "OrderItem",
    "OrderStatus",
    "TrackingEvent",
    "Order",
    "RefundState",
    "RefundResult",
    "CoreSecurityError",
    "AuthLevelError",
    "OwnershipError",
    "PolicyViolationError",
    "OrderPort",
    "CatalogPort",
    "RefundPort",
    "ChannelPort",
    "SpeechPort",
    "DEFAULT_REFUND_AUTO_LIMIT_INR",
    "DEFAULT_MONTHLY_REFUND_CAP_INR",
    "require_level",
    "verify_order_ownership",
    "check_refund_eligibility",
    "evaluate_refund_state",
    "generate_idempotency_key",
]
