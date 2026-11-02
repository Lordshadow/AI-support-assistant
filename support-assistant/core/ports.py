"""
Ports (Abstract Interfaces) for Customer Support Assistant
Complies with Specification Section 6 (Modular Design: Ports & Adapters).

These interfaces define what the core domain needs. Adapters implement them.
The core domain never references concrete database models or vendor SDKs.
"""

from typing import Protocol, Optional
from datetime import datetime
try:
    from core.models import (
        Order, TrackingEvent, ProductMatch, ProductSpecs,
        PriceInfo, ProductSummary, RefundResult, RefundState
    )
except ImportError:
    from .models import (
        Order, TrackingEvent, ProductMatch, ProductSpecs,
        PriceInfo, ProductSummary, RefundResult, RefundState
    )


class OrderPort(Protocol):
    """Port for retrieving order information and shipping tracking."""

    async def get_order(self, customer_id: str, order_id: str) -> Optional[Order]:
        """Fetch order belonging to customer_id. Returns None if not found or not owned."""
        ...

    async def list_recent_orders(self, customer_id: str, limit: int = 5) -> list[Order]:
        """List the customer's most recent orders."""
        ...

    async def get_tracking(self, customer_id: str, order_id: str) -> list[TrackingEvent]:
        """Fetch shipping tracking timeline for an owned order."""
        ...


class CatalogPort(Protocol):
    """Port for catalog lookups, specs, live pricing, and policy documents."""

    async def find_product(self, text: str) -> list[ProductMatch]:
        """Hybrid search resolving customer text to canonical product candidates."""
        ...

    async def get_details(self, product_id: str) -> Optional[ProductSpecs]:
        """Fetch structured technical specifications."""
        ...

    async def get_price(self, product_id: str) -> Optional[PriceInfo]:
        """Fetch live price, discounts, and real-time stock."""
        ...

    async def search(
        self,
        category: Optional[str] = None,
        min_price: Optional[int] = None,
        max_price: Optional[int] = None,
        filters: Optional[dict] = None
    ) -> list[ProductSummary]:
        """Browse catalog by category and price range using live prices."""
        ...

    async def search_product_docs(self, product_id: str, query: str) -> list[str]:
        """Search documentation/FAQs strictly filtered by product_id."""
        ...

    async def search_policy(self, query: str) -> list[str]:
        """Search return and refund policy clauses."""
        ...


class RefundPort(Protocol):
    """Port for checking refund eligibility and executing refund actions."""

    async def check_eligibility(
        self,
        customer_id: str,
        order_id: str,
        item_id: Optional[str] = None
    ) -> tuple[bool, str, int]:
        """
        Check if an order/item is eligible.
        Returns: (is_eligible, policy_reason, eligible_amount_inr)
        """
        ...

    async def request_refund(
        self,
        customer_id: str,
        order_id: str,
        amount_inr: int,
        reason: str,
        idempotency_key: str
    ) -> RefundResult:
        """Submit a refund request with an idempotency key."""
        ...

    async def get_status(self, refund_id: str) -> Optional[RefundResult]:
        """Fetch current state of a refund request."""
        ...

    async def record_staff_decision(
        self,
        refund_id: str,
        state: RefundState,
        decided_by: str,
        note: Optional[str] = None
    ) -> RefundResult:
        """Staff Support Desk approval or rejection of a pending refund."""
        ...


class ChannelPort(Protocol):
    """Port for outbound communication across Web widget and WhatsApp."""

    async def send_text(self, recipient_id: str, text: str) -> bool:
        """Send a plain text message to the customer."""
        ...

    async def send_quick_replies(
        self,
        recipient_id: str,
        prompt: str,
        options: list[tuple[str, str]]
    ) -> bool:
        """Send a message with selectable options/buttons (e.g. for look-alikes)."""
        ...


class SpeechPort(Protocol):
    """Port for transcribing customer voice notes (WhatsApp / Web)."""

    async def transcribe(self, audio_bytes: bytes, content_type: str) -> str:
        """Transcribe audio to text in English/Tamil/Tanglish."""
        ...
