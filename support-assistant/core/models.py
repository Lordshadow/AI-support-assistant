"""
Domain Models and Data Structures for Customer Support Assistant
Complies with Specification Sections 1.3, 5, 6, 10, and 15.1.
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Literal, Optional


class AuthLevel(str, Enum):
    ANONYMOUS = "anonymous"
    IDENTIFIED = "identified"
    VERIFIED = "verified"
    STAFF = "staff"

    @classmethod
    def rank(cls, level: "AuthLevel") -> int:
        hierarchy = {
            cls.ANONYMOUS: 1,
            cls.IDENTIFIED: 2,
            cls.VERIFIED: 3,
            cls.STAFF: 4
        }
        return hierarchy[level]

    def satisfies(self, required: "AuthLevel") -> bool:
        return self.rank(self) >= self.rank(required)


PageType = Literal[
    "product_details",
    "product_listing",
    "cart",
    "checkout",
    "order_details",
    "dashboard",
    "other",
]


@dataclass(frozen=True)
class PageContext:
    """Validated, transport-supplied browsing context for the current turn."""

    url: str
    page_type: PageType
    product_id: Optional[str] = None
    order_id: Optional[str] = None
    cart_id: Optional[str] = None
    title: Optional[str] = None


@dataclass(frozen=True)
class SessionContext:
    """
    Immutable identity and authorization context.
    Injected at transport layer (headers/JWT).
    NEVER populated or overridden by LLM message arguments.
    """
    tenant_id: str
    conv_id: str
    customer_id: Optional[str] = None
    level: AuthLevel = AuthLevel.ANONYMOUS
    channel: Literal["web", "whatsapp"] = "web"
    verified_until: Optional[datetime] = None
    page_context: Optional[PageContext] = None
    # Kept only in memory and inside the short-lived signed MCP transport token.
    # Never render or log this value; storefront APIs validate its signature.
    storefront_customer_token: Optional[str] = field(default=None, repr=False, compare=False)
    # Order-scoped token issued by the storefront after its OTP verification.
    storefront_refund_verification_token: Optional[str] = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class ProductMatch:
    product_id: str
    name: str
    score: float
    category: str


@dataclass(frozen=True)
class ProductSpecs:
    product_id: str
    name: str
    brand: str
    category: str
    specs: dict[str, str] = field(default_factory=dict)
    aliases: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PriceInfo:
    product_id: str
    price: Decimal | int
    discount_price: Optional[int]
    currency: str = "INR"
    in_stock: bool = True
    active_offers: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ProductSummary:
    product_id: str
    name: str
    category: str
    price: int
    in_stock: bool


@dataclass(frozen=True)
class OrderItem:
    item_id: str
    product_id: str
    product_name: str
    category: str  # e.g., "electronics", "digital", "apparel"
    price: int
    quantity: int = 1
    is_digital: bool = False
    is_refunded: bool = False
    refund_eligibility_verified: bool = True


class OrderStatus(str, Enum):
    PROCESSING = "Processing"
    SHIPPED = "Shipped"
    OUT_FOR_DELIVERY = "Out for Delivery"
    DELIVERED = "Delivered"
    CANCELLED = "Cancelled"
    RETURNED = "Returned"
    UNKNOWN = "Unknown"


@dataclass(frozen=True)
class TrackingEvent:
    timestamp: datetime
    location: str
    status: str
    details: str


@dataclass(frozen=True)
class Order:
    order_id: str
    customer_id: str
    items: list[OrderItem]
    total_amount_inr: Decimal | int
    status: OrderStatus
    created_at: datetime
    delivered_at: Optional[datetime] = None
    tracking_number: Optional[str] = None
    courier_name: Optional[str] = None
    shipping_address: Optional[str] = None


class RefundState(str, Enum):
    REQUESTED = "requested"
    PROCESSED = "processed"            # Auto-refunded (<= ₹2,000)
    PENDING_APPROVAL = "pending_approval"  # Over limit (> ₹2,000), awaits human
    APPROVED = "approved"              # Approved by staff
    REJECTED = "rejected"              # Rejected by staff or policy
    FAILED = "failed"                  # Payment gateway error


@dataclass(frozen=True)
class RefundResult:
    refund_id: str
    order_id: str
    customer_id: str
    amount_inr: Decimal | int
    state: RefundState
    idempotency_key: str
    reason: str
    message: str
    created_at: datetime
    decided_by: Optional[str] = None
    decided_at: Optional[datetime] = None
    note: Optional[str] = None


# Domain Exceptions
class CoreSecurityError(Exception):
    """Base domain security exception."""


class AuthLevelError(CoreSecurityError):
    """Raised when current session level is insufficient for an action."""


class OwnershipError(CoreSecurityError):
    """Raised when a user attempts to access an order not belonging to them."""


class PolicyViolationError(Exception):
    """Raised when an action violates business policies."""
