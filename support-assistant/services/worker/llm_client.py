"""
LLM Client Interfaces and Adapters for Groq API & Offline Mock Engine
Complies with Specification Section 4, 9.1 (Model Tiering), and Final Tech Stack.
"""

from typing import Protocol, Optional, Any
from dataclasses import dataclass, field
import os
import json
import re
import logging
from decimal import Decimal, InvalidOperation

logger = logging.getLogger("services.worker.llm_client")


def _format_inr_amount(value: Any) -> str:
    """Format numeric amounts safely when tools return money as JSON strings."""
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return ""
    if not amount.is_finite() or amount == 0:
        return ""
    return f"₹{amount:,.2f}"


def _focused_product_spec_answer(
    product_name: str,
    specs: dict[str, Any],
    question: str,
) -> Optional[str]:
    """Answer a focused product follow-up from its matching catalog specification."""
    text = question.lower()
    topic_fields = (
        (("core", "cores", "cpu", "processor"), ("processor", "cpu", "core"), "processor"),
        (("ram", "memory"), ("memory", "ram"), "memory"),
        (("storage", "ssd", "drive", "capacity"), ("storage", "ssd", "drive", "capacity"), "storage"),
        (("display", "screen", "resolution", "refresh rate"), ("display", "screen", "resolution", "refresh"), "display"),
        (("graphics", "gpu", "video card"), ("graphics", "gpu", "video"), "graphics"),
        (("battery", "battery life"), ("battery", "capacity"), "battery"),
        (("port", "ports", "usb", "hdmi"), ("port", "usb", "hdmi"), "ports"),
        (("warranty", "guarantee"), ("warranty", "guarantee"), "warranty"),
        (("weight", "heavy", "light"), ("weight", "mass"), "weight"),
        (("dimension", "size", "thick"), ("dimension", "size", "thickness"), "dimensions"),
    )
    selected: Optional[tuple[str, str]] = None
    for cues, field_cues, label in topic_fields:
        if any(re.search(rf"\b{re.escape(cue)}\b", text) for cue in cues):
            selected = (label, "|".join(field_cues))
            break
    if selected is None:
        return None

    label, field_pattern = selected
    for field, value in specs.items():
        field_text = str(field).lower().replace("_", " ")
        value_text = str(value).strip()
        if not value_text:
            continue
        if any(re.search(rf"\b{cue}\b", field_text) for cue in field_pattern.split("|")):
            if label == "processor":
                core_match = re.search(r"\b(\d+)\s*[- ]?cores?\b", value_text, re.I)
                if core_match:
                    processor_name = re.split(r",\s*\d+\s*[- ]?cores?\b", value_text, maxsplit=1, flags=re.I)[0].strip()
                    return f"The **{product_name}** has **{core_match.group(1)} cores**, using the **{processor_name}** processor."
                return f"The listed processor for **{product_name}** is **{value_text}**, but the catalog does not specify its core count."
            return f"For **{product_name}**, the listed {label} specification is **{value_text}**."
    return f"I couldn’t find a {label} specification for **{product_name}** in the product listing."


def _product_overview_answer(product_name: str, specs: dict[str, Any]) -> Optional[str]:
    """Build a compact, customer-friendly overview from verified catalog fields."""
    preferred_fields = (
        ("Processor", ("processor", "cpu")),
        ("Graphics", ("graphics", "gpu")),
        ("Memory", ("memory", "ram")),
        ("Storage", ("storage", "ssd", "drive")),
        ("Display", ("display", "screen")),
    )
    selected: list[tuple[str, str]] = []
    normalized_specs = [(str(key).lower().replace("_", " "), str(value).strip()) for key, value in specs.items()]
    for label, cues in preferred_fields:
        match = next((
            (label, value) for key, value in normalized_specs
            if value and any(re.search(rf"\b{re.escape(cue)}\b", key) for cue in cues)
        ), None)
        if match:
            selected.append(match)
        if len(selected) == 5:
            break
    if not selected:
        return None

    selected_by_label = dict(selected)
    processor = selected_by_label.get("Processor")
    graphics = selected_by_label.get("Graphics")
    if processor and graphics:
        overview = f"**{product_name}** pairs **{processor}** with **{graphics}**."
        supporting = [
            f"**{label.lower()}:** {value}"
            for label, value in selected
            if label not in ("Processor", "Graphics")
        ]
        if supporting:
            overview += " The listing also includes " + ", ".join(supporting) + "."
    else:
        overview = f"**{product_name}** is listed with " + "; ".join(
            f"**{label.lower()}:** {value}" for label, value in selected
        ) + "."
    return overview + " If you share what you’ll use it for, I can help assess whether this configuration fits."

try:
    from openai import AsyncOpenAI
except ImportError:
    AsyncOpenAI = None


@dataclass
class ToolCall:
    call_id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    content: Optional[str]
    tool_calls: list[ToolCall] = field(default_factory=list)
    model_used: str = "mock-model"
    token_usage: dict[str, int] = field(default_factory=lambda: {"prompt_tokens": 100, "completion_tokens": 50})


class LLMClient(Protocol):
    """Protocol for LLM interactions."""

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        model_tier: str = "small"
    ) -> LLMResponse:
        ...


class GroqLLMClient:
    """
    Groq API client using OpenAI-compatible SDK.
    Supports tiered models:
    - Small Tier (default): openai/gpt-oss-20b (fallback: llama-3.1-8b-instant)
    - Large Tier (complex): openai/gpt-oss-120b (fallback: llama-3.3-70b-versatile)
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        small_model: Optional[str] = None,
        large_model: Optional[str] = None,
        fallback_to_mock: bool = True
    ):
        self.api_key = api_key or os.getenv("GROQ_API_KEY", "")
        self.small_model = small_model or os.getenv("GROQ_SMALL_MODEL", "openai/gpt-oss-20b")
        self.large_model = large_model or os.getenv("GROQ_LARGE_MODEL", "openai/gpt-oss-120b")
        self.fallback_to_mock = fallback_to_mock
        self._mock_client: Optional[Any] = None
        if AsyncOpenAI and self.api_key:
            self._client = AsyncOpenAI(
                base_url="https://api.groq.com/openai/v1",
                api_key=self.api_key
            )
        else:
            self._client = None

    def _get_mock_client(self) -> Any:
        if self._mock_client is None:
            self._mock_client = MockLLMClient()
        return self._mock_client

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        model_tier: str = "small"
    ) -> LLMResponse:
        if not self._client:
            if self.fallback_to_mock:
                return await self._get_mock_client().chat(messages, tools, model_tier)
            raise RuntimeError("Groq API client requires GROQ_API_KEY to be set in environment.")

        model = self.large_model if model_tier == "large" else self.small_model
        kwargs: dict[str, Any] = {"model": model, "messages": messages}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        try:
            resp = await self._client.chat.completions.create(**kwargs)
        except Exception as exc:
            err_str = str(exc).lower()
            if "not found" in err_str or "does not exist" in err_str or "decommissioned" in err_str:
                alt_model = "openai/gpt-oss-20b" if model != "openai/gpt-oss-20b" else "openai/gpt-oss-120b"
                logger.warning(
                    "Configured Groq model '%s' unavailable (%s). Retrying with alternative model '%s'...",
                    model, exc, alt_model
                )
                try:
                    kwargs["model"] = alt_model
                    resp = await self._client.chat.completions.create(**kwargs)
                    model = alt_model
                except Exception as exc2:
                    if self.fallback_to_mock:
                        logger.warning(
                            "Alternative Groq model '%s' also failed (%s). Falling back to deterministic MockLLMClient.",
                            alt_model, exc2
                        )
                        return await self._get_mock_client().chat(messages, tools, model_tier)
                    raise
            elif self.fallback_to_mock:
                logger.warning("Groq chat execution encountered error (%s); falling back to MockLLMClient.", exc)
                return await self._get_mock_client().chat(messages, tools, model_tier)
            else:
                raise

        choice = resp.choices[0]
        msg = choice.message

        tool_calls = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                tool_calls.append(ToolCall(
                    call_id=tc.id,
                    name=tc.function.name,
                    arguments=json.loads(tc.function.arguments)
                ))

        usage = {
            "prompt_tokens": resp.usage.prompt_tokens if resp.usage else 0,
            "completion_tokens": resp.usage.completion_tokens if resp.usage else 0
        }

        return LLMResponse(
            content=msg.content,
            tool_calls=tool_calls,
            model_used=model,
            token_usage=usage
        )


class MockLLMClient:
    """
    Deterministic rule-based LLM engine for offline testing and evaluation.
    Requires ZERO network calls or API keys.
    Accurately plans tool calls and composes grounded answers.
    """

    def __init__(self, default_model: str = "mock-groq-small"):
        self.default_model = default_model

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        model_tier: str = "small"
    ) -> LLMResponse:
        last_msg = messages[-1]
        role = last_msg.get("role")

        # 1. If last message is a tool output, synthesize customer-facing answer
        if role == "tool" or (len(messages) >= 2 and messages[-2].get("role") == "assistant" and messages[-2].get("tool_calls")):
            return self._synthesize_answer(messages)

        # 2. Plan Tool Calls based on user query
        user_text = last_msg.get("content", "").lower()
        conversation_text = " ".join(
            str(message.get("content", ""))
            for message in messages
            if message.get("role") in ("user", "assistant")
        ).lower()

        # Prompt injection detection: refuse override
        if "system override" in user_text or "ignore previous instructions" in user_text:
            return LLMResponse(
                content="I cannot follow system override directives. Store security and return policies remain strictly enforced.",
                model_used=f"mock-{model_tier}"
            )

        # Use the active page entity when the customer asks about the item in view.
        system_text = str(messages[0].get("content", ""))
        product_context = re.search(r"Product ID: ([A-Z0-9][A-Z0-9_-]{0,63})", system_text)
        order_context = re.search(r"Order ID: (ORD-[-A-Za-z0-9]+)", system_text)
        asks_product_info = any(word in user_text for word in (
            "about", "tell me", "overview", "key details", "feature", "spec",
            "battery", "warranty", "pair", "connect", "water", "display",
            "sensor", "compatible", "compatibility", "work with", "use it",
            "does it", "does ", "can it", "can ", "is it", "has ", "support",
            "include", "this product", "this item", "this device", "core", "cpu",
            "processor", "ram", "memory", "storage", "ssd", "graphics", "gpu",
            "screen", "resolution", "refresh rate", "ports", "weight", "dimensions",
        )) or bool(re.search(r"\bhow\s+(?:many|much)\b", user_text))
        asks_price = any(word in user_text for word in ("price", "cost", "discount", "stock", "available", "availability"))
        if product_context and (asks_product_info or asks_price):
            product_id = product_context.group(1).upper()
            calls = [
                ToolCall(
                    call_id="call_page_product_details",
                    name="get_product_details",
                    arguments={"product_id": product_id},
                ),
                ToolCall(
                    call_id="call_page_product_docs",
                    name="search_product_docs",
                    arguments={"product_id": product_id, "question": last_msg.get("content", "")},
                ),
            ]
            if asks_price:
                calls.append(ToolCall(
                    call_id="call_page_product_price",
                    name="get_product_price",
                    arguments={"product_id": product_id},
                ))
            return LLMResponse(
                content=None,
                tool_calls=calls,
                model_used=f"mock-{model_tier}"
            )
        if order_context and any(word in user_text for word in (
            "this order", "order status", "where is", "track", "delivery"
        )):
            return LLMResponse(
                content=None,
                tool_calls=[ToolCall(
                    call_id="call_page_order_status",
                    name="get_order_status",
                    arguments={"order_id": order_context.group(1).upper()},
                )],
                model_used=f"mock-{model_tier}"
            )

        # Order inquiries
        order_match = re.search(r"\bORD(?:[-_][A-Za-z0-9]+|\d+)(?:[-_][A-Za-z0-9]+)*\b", user_text, re.I)
        if not order_match and any(phrase in user_text for phrase in (
            "initiate refund", "process refund", "go ahead", "proceed", "do it", "yes"
        )) and any(word in user_text for word in ("refund", "return", "otp", "verification")):
            previous_orders = re.findall(r"\bORD(?:[-_][A-Za-z0-9]+|\d+)(?:[-_][A-Za-z0-9]+)*\b", conversation_text, re.I)
            if previous_orders:
                order_match = re.search(r"\bORD(?:[-_][A-Za-z0-9]+|\d+)(?:[-_][A-Za-z0-9]+)*\b", previous_orders[-1], re.I)
        if "refund" in user_text and order_match:
            order_id = order_match.group(0).upper().replace("_", "-")
            return LLMResponse(
                content=None,
                tool_calls=[
                    ToolCall(call_id="call_ref_01", name="check_refund_eligibility", arguments={"order_id": order_id}),
                    ToolCall(call_id="call_ref_02", name="create_refund_request", arguments={"order_id": order_id, "reason": user_text})
                ],
                model_used=f"mock-{model_tier}"
            )

        if order_match:
            order_id = order_match.group(0).upper().replace("_", "-")
            return LLMResponse(
                content=None,
                tool_calls=[ToolCall(call_id="call_ord_01", name="get_order_status", arguments={"order_id": order_id})],
                model_used=f"mock-{model_tier}"
            )

        # A refund request without an order ID is an action, not a policy FAQ.
        # List owned orders so the customer can choose one instead of receiving
        # a generic policy template or being asked to repeat context.
        if any(phrase in user_text for phrase in (
            "refund", "return", "refund process", "return process"
        )):
            return LLMResponse(
                content=None,
                tool_calls=[ToolCall(call_id="call_list_refund_orders", name="list_recent_orders", arguments={})],
                model_used=f"mock-{model_tier}"
            )

        # General order status or recent orders inquiry without a specific order ID
        is_order_query = any(phrase in user_text for phrase in (
            "my order", "my orders", "check my order", "where is my order", "track my order",
            "order status", "check order", "recent order", "recent orders", "check orders",
            "view order", "view orders", "status of order"
        )) or ("order" in user_text and any(w in user_text for w in ("check", "where", "track", "status", "list", "show", "what")))
        if is_order_query and not any(w in user_text for w in ("cancel", "refund", "return")):
            return LLMResponse(
                content=None,
                tool_calls=[ToolCall(call_id="call_list_ord_01", name="list_recent_orders", arguments={})],
                model_used=f"mock-{model_tier}"
            )

        # Generic Pulse Buds is ambiguous; never pick a model on the user's behalf.
        if "pulse buds" in user_text and not re.search(r"\b(?:141|131)\b", user_text):
            return LLMResponse(
                content=None,
                tool_calls=[ToolCall(call_id="call_find_01", name="find_product", arguments={"name_text": "Pulse Buds"})],
                model_used=f"mock-{model_tier}"
            )

        # Resolve product-specific questions through catalog tools. Keep this
        # deterministic fallback aligned with the products in MockCatalogAdapter.
        product = self._known_product(user_text)
        if product:
            product_id, product_name = product
            calls = [ToolCall(
                call_id="call_product_find_01",
                name="find_product",
                arguments={"name_text": product_name},
            )]
            asks_specs = asks_product_info
            if asks_price:
                calls.append(ToolCall(
                    call_id="call_product_price_01",
                    name="get_product_price",
                    arguments={"product_id": product_id},
                ))
            if asks_specs:
                calls.append(ToolCall(
                    call_id="call_product_details_01",
                    name="get_product_details",
                    arguments={"product_id": product_id},
                ))
            calls.append(ToolCall(
                call_id="call_product_docs_01",
                name="search_product_docs",
                arguments={"product_id": product_id, "question": user_text},
            ))
            return LLMResponse(content=None, tool_calls=calls, model_used=f"mock-{model_tier}")

        # Store policy and delivery questions use policy retrieval.
        if any(word in user_text for word in (
            "return", "policy", "window", "address", "shipping", "delivery", "warranty",
            "repair", "repairs", "damaged", "damage", "cover"
        )):
            return LLMResponse(
                content=None,
                tool_calls=[ToolCall(call_id="call_pol_01", name="search_policy", arguments={"question": user_text})],
                model_used=f"mock-{model_tier}"
            )

        # Keep unsupported questions in scope without repeating a broad service menu.
        return LLMResponse(
            content="I can help with NovaRetail products, orders, delivery, and returns. What would you like to check?",
            model_used=f"mock-{model_tier}"
        )

    @staticmethod
    def _known_product(user_text: str) -> Optional[tuple[str, str]]:
        """Return the canonical mock catalog product for an explicit product mention."""
        compact = re.sub(r"[^a-z0-9]+", " ", user_text.lower()).strip()
        products = (
            ("p1041", "P1041", "Pulse Buds 141"),
            ("pulse buds 141", "P1041", "Pulse Buds 141"),
            ("buds 141", "P1041", "Pulse Buds 141"),
            ("pb 141", "P1041", "Pulse Buds 141"),
            ("p1031", "P1031", "Pulse Buds 131"),
            ("pulse buds 131", "P1031", "Pulse Buds 131"),
            ("buds 131", "P1031", "Pulse Buds 131"),
            ("pb 131", "P1031", "Pulse Buds 131"),
            ("p2001", "P2001", "Nova Watch Pro"),
            ("nova watch pro", "P2001", "Nova Watch Pro"),
            ("watch pro", "P2001", "Nova Watch Pro"),
            ("p gift500", "P-GIFT500", "Google Play Gift Card"),
            ("google play", "P-GIFT500", "Google Play Gift Card"),
            ("gift card", "P-GIFT500", "Google Play Gift Card"),
        )
        for phrase, product_id, product_name in products:
            if phrase in compact:
                return product_id, product_name
        return None

    def _synthesize_answer(self, messages: list[dict[str, Any]]) -> LLMResponse:
        """Composes grounded answer strictly from tool outputs."""
        tool_outputs: list[str] = []
        tool_results: list[dict[str, Any]] = []
        for m in messages:
            if m.get("role") == "tool":
                content = m.get("content", "")
                tool_outputs.append(content)
                try:
                    parsed = json.loads(content)
                except (json.JSONDecodeError, TypeError):
                    continue
                if isinstance(parsed, dict):
                    tool_results.append(parsed)

        combined = " ".join(tool_outputs)

        # Explain authentication requirements returned by protected tools.
        auth_result = next((r for r in tool_results if r.get("needs_auth")), None)
        if auth_result:
            message = auth_result.get("message", "Please sign in to continue.")
            if "OTP" in message and "verification code (OTP)" not in message:
                message = message.replace("verification code", "verification code (OTP)")
            return LLMResponse(content=message, model_used=self.default_model)

        eligibility = next((r for r in tool_results if "is_eligible" in r), None)
        if eligibility and not eligibility.get("is_eligible"):
            reason = eligibility.get("policy_reason") or "the order does not meet the return requirements"
            return LLMResponse(content=f"I can’t submit this refund because {reason}.", model_used=self.default_model)

        # Explain completed or rejected refund actions from structured results.
        refund_result = next((r for r in tool_results if r.get("state")), None)
        if refund_result:
            state = str(refund_result.get("state", "")).lower()
            if state == "processed":
                amount = refund_result.get("amount_inr")
                amount_text = f" for ₹{amount:,}" if isinstance(amount, (int, float)) else ""
                return LLMResponse(content=f"Your refund{amount_text} was approved automatically and initiated to your original payment method. It should arrive in 3–5 business days.", model_used=self.default_model)
            if state == "pending_approval":
                return LLMResponse(content="Your refund request has been submitted to a senior supervisor for review. The review usually takes 24–48 hours.", model_used=self.default_model)
            if state in ("rejected", "ineligible"):
                return LLMResponse(content=refund_result.get("message") or "This order is not eligible for a refund.", model_used=self.default_model)

        # Check legacy refund messages for adapters that return plain strings.
        if "approved automatically" in combined:
            return LLMResponse(
                content="Your refund has been approved automatically and initiated to your original payment method. It will reflect in 3–5 business days.",
                model_used=self.default_model
            )
        if "exceeds the instant auto-refund limit" in combined:
            return LLMResponse(
                content="Your refund request exceeds the ₹2,000 auto-approval limit and has been submitted to a senior supervisor for review. Turnaround is 24–48 hours.",
                model_used=self.default_model
            )
        if "non-refundable" in combined:
            return LLMResponse(
                content="Under Store Policy 6.0, digital goods and gift cards are strictly non-refundable once delivered. If you need special assistance, I can connect you to a human supervisor.",
                model_used=self.default_model
            )
        if "otp_required" in combined:
            return LLMResponse(
                content="For financial security, please enter the one-time verification code (OTP) sent to your registered email address.",
                model_used=self.default_model
            )

        # Build concise replies from structured catalog and order results.
        product_match = next((
            candidate
            for result in tool_results
            for candidate in result.get("candidates", [])
            if isinstance(candidate, dict)
        ), None)
        product_name = product_match.get("name") if product_match else None
        price_result = next((r for r in tool_results if "discount_price" in r and "price" in r), None)
        details_result = next((r for r in tool_results if isinstance(r.get("specs"), dict)), None)
        if not product_name and details_result:
            product_name = details_result.get("name")

        last_user_text = next((
            str(m.get("content", "")) for m in reversed(messages) if m.get("role") == "user"
        ), "")
        asks_for_price = any(
            cue in last_user_text.lower()
            for cue in ("price", "cost", "how much", "discount", "stock", "available")
        )
        if details_result and details_result.get("found") and product_name and not asks_for_price:
            focused_answer = _focused_product_spec_answer(
                str(product_name), details_result.get("specs", {}), last_user_text
            )
            if focused_answer:
                return LLMResponse(content=focused_answer, model_used=self.default_model)
            if re.search(r"\b(?:tell\s+me\s+about|about\s+this\s+product|describe|overview|key\s+details)\b", last_user_text, re.I):
                overview = _product_overview_answer(str(product_name), details_result.get("specs", {}))
                if overview:
                    return LLMResponse(content=overview, model_used=self.default_model)

        answer_parts = []
        if price_result and price_result.get("found"):
            name = product_name or price_result.get("product_id") or "This product"
            regular = price_result.get("price")
            discounted = price_result.get("discount_price")
            if isinstance(discounted, (int, float)) and discounted < regular:
                answer_parts.append(f"{name} is ₹{discounted:,} (regular price ₹{regular:,}).")
            elif isinstance(regular, (int, float)):
                answer_parts.append(f"{name} costs ₹{regular:,}.")
        if price_result and price_result.get("found") and any(
            word in str(m.get("content", "")).lower() for m in messages if m.get("role") == "user"
            for word in ("stock", "available", "availability")
        ):
            answer_parts.append("It is currently in stock." if price_result.get("in_stock") else "It is currently out of stock.")

        if details_result and details_result.get("found"):
            specs = details_result.get("specs", {})
            if isinstance(specs, dict):
                answer_parts.extend(
                    f"{key.replace('_', ' ').title()}: {value}"
                    for key, value in list(specs.items())[:8]
                )

        chunks = next((r.get("chunks") for r in tool_results if isinstance(r.get("chunks"), list)), None)
        if chunks:
            answer_parts.extend(str(chunk)[:1200] for chunk in chunks[:2] if str(chunk).strip())
        policy_result = next((r for r in tool_results if isinstance(r.get("clauses"), list)), None)
        if policy_result is not None:
            clauses = policy_result["clauses"]
            if clauses:
                answer_parts.extend(
                    re.sub(r"^Policy Clause \d+\.\d+ \([^)]*\):\s*", "", str(clause))
                    for clause in clauses[:2]
                )
            else:
                answer_parts.append("I couldn’t find information that answers that policy question. Could you clarify what item or policy you mean?")

        order_result = next((r for r in tool_results if "order_id" in r and "status" in r), None)
        if order_result:
            if order_result.get("found") is False:
                answer_parts.append(order_result.get("message", f"I couldn’t find order {order_result['order_id']} in your account."))
            else:
                oid = order_result["order_id"]
                st = order_result["status"]
                items = ", ".join(i.get("name", "") for i in order_result.get("items", []))
                courier = order_result.get("courier_name")
                tracking = order_result.get("tracking_number")
                delivered_at = order_result.get("delivered_at")

                lines = [f"Order **{oid}**" + (f" ({items})" if items else "") + f" is currently **{st}**."]
                if courier and tracking:
                    lines.append(f"Shipped via **{courier}** (Tracking: `{tracking}`).")
                if delivered_at:
                    lines.append(f"Delivered on **{delivered_at}**.")
                answer_parts.append(" ".join(lines))

        tracking_result = next((r for r in tool_results if "events" in r and isinstance(r.get("events"), list)), None)
        if tracking_result:
            events = tracking_result.get("events", [])
            oid = tracking_result.get("order_id", "your order")
            if not events:
                answer_parts.append(f"No tracking updates are currently available for order **{oid}**.")
            else:
                track_lines = [f"Tracking updates for order **{oid}**:"]
                for ev in events:
                    loc = ev.get("location", "")
                    ev_st = ev.get("status", "")
                    details = ev.get("details", "")
                    track_lines.append(f"- **{ev_st}** ({loc}): {details}")
                answer_parts.append("\n".join(track_lines))

        recent_orders_result = next((r for r in tool_results if "orders" in r and isinstance(r.get("orders"), list)), None)
        if recent_orders_result is not None:
            orders_list = recent_orders_result.get("orders", [])
            if not orders_list:
                answer_parts.append("You have no recent orders in your account.")
            else:
                rows = []
                for o in orders_list:
                    oid = o.get("order_id")
                    st = o.get("status")
                    items = ", ".join(o.get("item_names") or [])
                    total = o.get("total_amount_inr")
                    total_str = f"₹{total:,}" if isinstance(total, (int, float)) else ""
                    date_str = o.get("created_at", "")
                    rows.append(f"| **{oid}** | {items or '—'} | {total_str or '—'} | **{st}** | {date_str} |")
                table_md = (
                    "Here are your recent orders:\n\n"
                    "| Order ID | Items | Total | Status | Date |\n"
                    "| :--- | :--- | :--- | :--- | :--- |\n"
                    + "\n".join(rows)
                    + "\n\nLet me know if you would like tracking details, return eligibility, or assistance with any of these orders."
                )
                answer_parts.append(table_md)

        if answer_parts:
            return LLMResponse(content=" ".join(answer_parts), model_used=self.default_model)

        refund_create_result = next((r for r in tool_results if "refund_id" in r and "state" in r), None)
        if refund_create_result:
            rid = refund_create_result.get("refund_id")
            state = refund_create_result.get("state")
            amt_str = _format_inr_amount(refund_create_result.get("amount_inr", 0))
            if state == "pending_approval":
                return LLMResponse(
                    content=(
                        f"Your refund request **{rid}** for {amt_str} has been submitted for supervisor approval.\n\n"
                        f"Our support team will review and approve the request shortly."
                    ),
                    model_used=self.default_model
                )
            else:
                return LLMResponse(
                    content=(
                        f"Your refund **{rid}** for {amt_str} has been processed successfully!\n\n"
                        f"The amount will be credited back to your original payment method."
                    ),
                    model_used=self.default_model
                )

        refund_elig_result = next((r for r in tool_results if "is_eligible" in r), None)
        if refund_elig_result:
            oid = refund_elig_result.get("order_id", "your order")
            if refund_elig_result.get("is_eligible"):
                amt = refund_elig_result.get("eligible_amount_inr", 0)
                try:
                    amount_value = Decimal(str(amt))
                except (InvalidOperation, TypeError, ValueError):
                    amount_value = Decimal("0")
                amt_str = _format_inr_amount(amt)
                if amount_value > Decimal("2000"):
                    return LLMResponse(
                        content=(
                            f"Great news! Order **{oid}** is eligible for a return and refund of **{amt_str}**.\n\n"
                            f"- **Policy Note:** Because this order exceeds the ₹2,000 instant refund threshold, "
                            f"your request will be submitted to our supervisor team for approval.\n"
                            f"- **Next Step:** Would you like me to submit this return request for supervisor review?"
                        ),
                        model_used=self.default_model
                    )
                else:
                    return LLMResponse(
                        content=(
                            f"Good news! Order **{oid}** is eligible for an instant refund of **{amt_str}**.\n\n"
                            f"- **Instant Refund:** Orders under ₹2,000 qualify for immediate automated processing.\n"
                            f"- **Verification:** We will verify your request with a quick security code (OTP). "
                            f"Would you like to proceed with the return?"
                        ),
                        model_used=self.default_model
                    )
            else:
                reason = refund_elig_result.get("policy_reason", "Order not found or not eligible under current policy.")
                return LLMResponse(
                    content=f"I’m sorry, but order **{oid}** is not eligible for a refund. Reason: {reason}",
                    model_used=self.default_model
                )

        no_match = next((r for r in tool_results if r.get("found") is False or r.get("error")), None)
        if no_match:
            return LLMResponse(content=no_match.get("message") or no_match.get("error") or "I couldn’t find a matching record.", model_used=self.default_model)

        return LLMResponse(
            content="I couldn’t find information that answers that question. Could you rephrase it or tell me the product or order involved?",
            model_used=self.default_model
        )
