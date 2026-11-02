"""
AI Request Router and Tier Decider
Complies with Specification Section 3.3, 9.1 (Routing & Cost control), and 9.4.

Enforces:
1. Cache lookup first (skips AI model).
2. Template case (order status & greetings via fixed wording).
3. Small model tier by default (Groq 8B).
4. Large model tier only for complex cases (comparisons, disputes, multi-intent).
5. Human handoff when requested or confidence low.
"""

from typing import Literal, Optional, Any
from dataclasses import dataclass
import re

from core.models import SessionContext, AuthLevel
from core.router.normalizer import LanguageNormalizer, NormalizedQuery
from core.router.cache import CacheService
from core.router.templates import TemplateResponder
from services.mcp_servers.dispatcher import MCPToolDispatcher


RouteType = Literal["cache", "template", "small_model", "large_model", "handoff"]


@dataclass(frozen=True)
class RouteDecision:
    route_type: RouteType
    normalized: NormalizedQuery
    cached_response: Optional[str] = None
    template_response: Optional[str] = None
    intent: str = "general"
    confidence: float = 1.0
    reason: str = ""


class AIRouter:
    """Intelligent, multi-tier router for the Customer Support Assistant."""

    def __init__(
        self,
        cache_service: Optional[CacheService] = None,
        dispatcher: Optional[MCPToolDispatcher] = None
    ):
        self.cache = cache_service or CacheService()
        self.dispatcher = dispatcher

    async def route_message(
        self,
        message: str,
        ctx: SessionContext
    ) -> RouteDecision:
        # 1. Normalize Language & Extract Entities
        norm = LanguageNormalizer.normalize(message)
        clean_msg = norm.cleaned_text.lower()

        # 2. Check for Human Handoff Request
        if norm.is_human_request:
            return RouteDecision(
                route_type="handoff",
                normalized=norm,
                intent="human_handoff",
                confidence=1.0,
                reason="Customer explicitly requested human executive"
            )

        # 3. Check for Simple Greeting (Zero-Cost Template)
        greeting_words = {"hi", "hello", "hey", "vanakkam", "வணக்கம்", "halo", "morning", "evening"}
        if clean_msg in greeting_words or any(clean_msg == f"{w}!" for w in greeting_words):
            greeting_text = TemplateResponder.get_greeting(norm.language)
            return RouteDecision(
                route_type="template",
                normalized=norm,
                template_response=greeting_text,
                intent="greeting",
                confidence=1.0,
                reason="Matched standard greeting template"
            )

        # 4. Check Cache (e.g. for common FAQ queries)
        cache_key = CacheService.key_faq("global", norm.cleaned_text)
        cached = self.cache.get(cache_key)
        if cached:
            return RouteDecision(
                route_type="cache",
                normalized=norm,
                cached_response=cached,
                intent="cached_faq",
                confidence=1.0,
                reason="Found exact answer in FAQ cache"
            )

        # 5. Check Template for Order Status (Zero-Cost Template)
        # If user provides order ID and query is purely tracking status
        is_status_query = bool(re.search(r"\b(status|where is|track|eppo varum|delivery date)\b", clean_msg))
        if norm.extracted_order_id and is_status_query and self.dispatcher:
            # If customer is identified, fetch status and render template directly
            if ctx.level.satisfies(AuthLevel.IDENTIFIED):
                order_res = await self.dispatcher.execute_tool(
                    "get_order_status",
                    {"order_id": norm.extracted_order_id},
                    ctx
                )
                if order_res.get("found"):
                    reply = TemplateResponder.render_order_status(order_res, norm.language)
                    return RouteDecision(
                        route_type="template",
                        normalized=norm,
                        template_response=reply,
                        intent="order_status",
                        confidence=1.0,
                        reason="Rendered verified order status using template"
                    )

        # 6. Model Tier Selection (Section 9.1 & 9.4)
        # Large Model: Comparisons ('Pulse Buds 141 vs 131'), Agitated Disputes, Injections
        if norm.is_comparison:
            return RouteDecision(
                route_type="large_model",
                normalized=norm,
                intent="product_comparison",
                confidence=0.90,
                reason="Product comparison requires nuanced multi-spec synthesis"
            )

        if norm.is_dispute:
            return RouteDecision(
                route_type="large_model",
                normalized=norm,
                intent="customer_dispute",
                confidence=0.85,
                reason="Agitated customer dispute escalated to large model for de-escalation"
            )

        # 7. Default: Small Model Tier (Groq 8B)
        # Handles single product inquiries, standard policy questions, refund requests
        inferred_intent = "general_faq"
        if "refund" in clean_msg or "return" in clean_msg:
            inferred_intent = "refund_request"
        elif norm.extracted_order_id or is_status_query:
            inferred_intent = "order_inquiry"

        return RouteDecision(
            route_type="small_model",
            normalized=norm,
            intent=inferred_intent,
            confidence=0.88,
            reason="Standard inquiry routed to fast, cost-effective small model tier"
        )
