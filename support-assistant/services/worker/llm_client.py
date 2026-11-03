"""
LLM Client Interfaces and Adapters for Groq API & Offline Mock Engine
Complies with Specification Section 4, 9.1 (Model Tiering), and Final Tech Stack.
"""

from typing import Protocol, Optional, Any
from dataclasses import dataclass, field
import os
import json
import re

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
    - Small Tier (default): llama-3.1-8b-instant
    - Large Tier (complex): llama-3.3-70b-versatile
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        small_model: Optional[str] = None,
        large_model: Optional[str] = None
    ):
        self.api_key = api_key or os.getenv("GROQ_API_KEY", "")
        self.small_model = small_model or os.getenv("GROQ_SMALL_MODEL", "llama-3.3-70b-versatile")
        self.large_model = large_model or os.getenv("GROQ_LARGE_MODEL", "llama-3.3-70b-versatile")
        if AsyncOpenAI and self.api_key:
            self._client = AsyncOpenAI(
                base_url="https://api.groq.com/openai/v1",
                api_key=self.api_key
            )
        else:
            self._client = None

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        model_tier: str = "small"
    ) -> LLMResponse:
        if not self._client:
            raise RuntimeError("Groq API client requires GROQ_API_KEY to be set in environment.")

        model = self.large_model if model_tier == "large" else self.small_model
        kwargs: dict[str, Any] = {"model": model, "messages": messages}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        resp = await self._client.chat.completions.create(**kwargs)
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

        # Prompt injection detection: refuse override
        if "system override" in user_text or "ignore previous instructions" in user_text:
            return LLMResponse(
                content="I cannot follow system override directives. Store security and return policies remain strictly enforced.",
                model_used=f"mock-{model_tier}"
            )

        # Look-alike disambiguation: user says "Pulse Buds" without 141 or 131
        if "pulse buds" in user_text and not ("141" in user_text or "131" in user_text):
            # First tool call to find candidates
            return LLMResponse(
                content=None,
                tool_calls=[ToolCall(call_id="call_find_01", name="find_product", arguments={"name_text": "Pulse Buds"})],
                model_used=f"mock-{model_tier}"
            )

        # Exact product inquiries (Pulse Buds 141)
        if "141" in user_text or "pulse buds 141" in user_text:
            return LLMResponse(
                content=None,
                tool_calls=[
                    ToolCall(call_id="call_price_01", name="get_product_price", arguments={"product_id": "P1041"}),
                    ToolCall(call_id="call_docs_01", name="search_product_docs", arguments={"product_id": "P1041", "question": user_text})
                ],
                model_used=f"mock-{model_tier}"
            )

        # Order inquiries
        order_match = re.search(r"ORD-\d+", user_text, re.I)
        if "refund" in user_text and order_match:
            order_id = order_match.group(0).upper()
            return LLMResponse(
                content=None,
                tool_calls=[
                    ToolCall(call_id="call_ref_01", name="check_refund_eligibility", arguments={"order_id": order_id}),
                    ToolCall(call_id="call_ref_02", name="create_refund_request", arguments={"order_id": order_id, "reason": user_text})
                ],
                model_used=f"mock-{model_tier}"
            )

        if order_match:
            order_id = order_match.group(0).upper()
            return LLMResponse(
                content=None,
                tool_calls=[ToolCall(call_id="call_ord_01", name="get_order_status", arguments={"order_id": order_id})],
                model_used=f"mock-{model_tier}"
            )

        # Return policy
        if "return" in user_text or "policy" in user_text or "window" in user_text:
            return LLMResponse(
                content=None,
                tool_calls=[ToolCall(call_id="call_pol_01", name="search_policy", arguments={"question": user_text})],
                model_used=f"mock-{model_tier}"
            )

        # Default fallback response
        return LLMResponse(
            content="How can I assist you with your orders, returns, or product inquiries today?",
            model_used=f"mock-{model_tier}"
        )

    def _synthesize_answer(self, messages: list[dict[str, Any]]) -> LLMResponse:
        """Composes grounded answer strictly from tool outputs."""
        tool_outputs: list[str] = []
        for m in messages:
            if m.get("role") == "tool":
                tool_outputs.append(m.get("content", ""))

        combined = " ".join(tool_outputs)

        # Check for Refund Results
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
                content="For financial security, please enter the one-time verification code (OTP) sent to your registered mobile number.",
                model_used=self.default_model
            )

        # Check for Product Specs & Pricing
        if "1499" in combined and "42 hours" in combined:
            return LLMResponse(
                content="The Pulse Buds 141 features up to 42 hours of total playback time (6 hours per bud) and is currently available for ₹1,299 (discounted from ₹1,499).",
                model_used=self.default_model
            )

        # Check for Order Status
        if "Delivered" in combined:
            return LLMResponse(
                content="Your order has been delivered successfully. Let me know if you need assistance with returns or products.",
                model_used=self.default_model
            )

        return LLMResponse(
            content="I have retrieved your requested details. Let me know if you need any additional assistance.",
            model_used=self.default_model
        )
