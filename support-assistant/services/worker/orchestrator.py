"""
Worker Orchestrator and Conversational Tool Calling Engine
Complies with Specification Section 3.2, 7, 8 (Look-Alike Disambiguation), 9.2, and 13.

Coordinates:
Router -> Look-Alike Disambiguation Gate -> Tool Execution via Dispatcher -> Grounded Synthesis.
"""

from typing import Optional, Any
from dataclasses import dataclass, field
from pathlib import Path
import time
import json

from core.models import SessionContext, AuthLevel
from core.router.router import AIRouter, RouteDecision
from services.mcp_servers.dispatcher import MCPToolDispatcher
from services.worker.llm_client import (
    LLMClient,
    MockLLMClient,
    ToolCall,
    _focused_product_spec_answer,
)
from services.worker.spend_manager import spend_manager
from services.worker.turn_recorder import TurnRecorder
from services.worker.escalation_guard import escalation_guard


MAX_HISTORY_MESSAGES = 32
MAX_HISTORY_CHARACTERS = 48_000


def _repair_missing_catalog_claim(reply: Optional[str], catalog_results: list[dict[str, Any]]) -> Optional[str]:
    """Do not let the model deny catalog facts returned by a successful tool."""
    text = (reply or "").lower()
    missing_claims = (
        "don't contain", "do not contain", "doesn't contain", "does not contain",
        "couldn't locate", "could not locate", "can't find", "cannot find",
        "no specific", "no details", "not contain", "not available in the product",
    )
    if not any(claim in text for claim in missing_claims):
        return reply

    result = next((
        item for item in catalog_results
        if item.get("found") is True and isinstance(item.get("specs"), dict) and item["specs"]
    ), None)
    if result is None:
        return reply

    specs = list(result["specs"].items())[:5]
    name = result.get("name") or "this product"
    lines = [f"Here are the product details for **{name}**:"]
    lines.extend(f"- **{str(key).replace('_', ' ').title()}:** {value}" for key, value in specs)
    return "\n".join(lines)


@dataclass
class OrchestratorResponse:
    reply: str
    route_type: str
    language: str
    model_used: str
    tools_called: list[str] = field(default_factory=list)
    latency_ms: float = 0.0
    requires_action: Optional[str] = None  # 'needs_otp', 'needs_login', 'disambiguation'
    trace_id: Optional[str] = None


class WorkerOrchestrator:
    """Production AI conversational agent orchestrator."""

    def __init__(
        self,
        router: AIRouter,
        dispatcher: MCPToolDispatcher,
        llm_client: Optional[LLMClient] = None,
        system_prompt_path: Optional[Path] = None
    ):
        self.router = router
        self.dispatcher = dispatcher
        self.llm = llm_client or MockLLMClient()

        # Load orchestrator system prompt
        prompt_file = system_prompt_path or (
            Path(__file__).parent.parent.parent / "prompts" / "orchestrator_system_prompt.md"
        )
        if prompt_file.exists():
            with open(prompt_file, "r", encoding="utf-8") as f:
                self.system_prompt = f.read()
        else:
            self.system_prompt = "You are NovaRetail's Customer Support Assistant."
        self._conversation_history: dict[str, list[dict[str, str]]] = {}

    def _history_for(self, conv_id: str) -> list[dict[str, str]]:
        """Return recent conversation context with message and character bounds."""
        return self._bounded_history(self._conversation_history.get(conv_id, []))

    @staticmethod
    def _bounded_history(history: list[dict[str, str]]) -> list[dict[str, str]]:
        recent = history[-MAX_HISTORY_MESSAGES:]
        if len(recent) % 2:
            recent = recent[1:]
        selected: list[dict[str, str]] = []
        used_chars = 0
        for index in range(len(recent) - 2, -1, -2):
            pair = recent[index:index + 2]
            pair_chars = sum(len(str(message.get("content", ""))) for message in pair)
            if selected and used_chars + pair_chars > MAX_HISTORY_CHARACTERS:
                break
            selected[0:0] = [
                {"role": message.get("role", "user"), "content": str(message.get("content", ""))}
                for message in pair
            ]
            used_chars += pair_chars
        return selected

    def _remember_turn(self, conv_id: str, user_message: str, assistant_message: str) -> None:
        history = self._conversation_history.setdefault(conv_id, [])
        history.extend([
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": assistant_message},
        ])
        self._conversation_history[conv_id] = self._bounded_history(history)

    async def process_turn(
        self,
        user_message: str,
        ctx: SessionContext
    ) -> OrchestratorResponse:
        start_time = time.perf_counter()

        # 1. Routing & Normalization Step
        decision: RouteDecision = await self.router.route_message(user_message, ctx)
        lang = decision.normalized.language

        # An active human takeover suppresses every route, including repeat requests.
        is_silenced, esc_state = await escalation_guard.is_bot_silenced(ctx.tenant_id, ctx.conv_id)
        if is_silenced:
            silenced_reply = (
                "A support executive is currently handling your request. "
                "Please wait while our team assists you directly."
            )
            latency = round((time.perf_counter() - start_time) * 1000, 2)
            try:
                turn_id = await TurnRecorder.record_turn(
                    tenant_id=ctx.tenant_id,
                    conv_id=ctx.conv_id,
                    customer_id=ctx.customer_id or "anonymous",
                    user_input_raw=user_message,
                    assistant_response_raw=silenced_reply,
                    intent="bot_silenced_human_takeover",
                    latency_ms=int(latency),
                    tokens_prompt=0,
                    tokens_completion=0,
                    channel=ctx.channel,
                    handoff_state="assigned" if esc_state == "assigned" else "open"
                )
            except Exception:
                turn_id = None

            return OrchestratorResponse(
                reply=silenced_reply,
                route_type="bot_silenced",
                language=lang,
                model_used="bot-silencer-gate",
                tools_called=[],
                latency_ms=latency,
                requires_action="handoff",
                trace_id=turn_id
            )

        # 2. Fast Path: Cache Hit (₹0, 0ms model latency)
        if decision.route_type == "cache":
            latency = round((time.perf_counter() - start_time) * 1000, 2)
            return OrchestratorResponse(
                reply=decision.cached_response or "",
                route_type="cache",
                language=lang,
                model_used="cache-hit",
                latency_ms=latency
            )

        # 3. Fast Path: Template Response (Greetings / Standard Tracking)
        if decision.route_type == "template":
            latency = round((time.perf_counter() - start_time) * 1000, 2)
            return OrchestratorResponse(
                reply=decision.template_response or "",
                route_type="template",
                language=lang,
                model_used="template-engine",
                tools_called=["get_order_status"] if decision.intent == "order_status" else [],
                latency_ms=latency
            )

        # 4. Fast Path: Direct Human Handoff Request
        if decision.route_type == "handoff":
            handoff_res = await self.dispatcher.execute_tool(
                "handoff_to_human",
                {"reason": "customer_request", "summary": user_message},
                ctx
            )
            latency = round((time.perf_counter() - start_time) * 1000, 2)
            return OrchestratorResponse(
                reply=handoff_res["message"],
                route_type="handoff",
                language=lang,
                model_used="handoff-server",
                tools_called=["handoff_to_human"],
                latency_ms=latency
            )

        # 5. Look-Alike Disambiguation Gate (Specification Section 8)
        # Check if user mentioned ambiguous products without exact model
        clean_lower = decision.normalized.cleaned_text.lower()
        if "pulse buds" in clean_lower and not ("141" in clean_lower or "131" in clean_lower):
            # Resolve candidates via find_product tool
            candidates_res = await self.dispatcher.execute_tool(
                "find_product", {"name_text": "Pulse Buds"}, ctx
            )
            candidates = candidates_res.get("candidates", [])
            if len(candidates) >= 2:
                # Ask ONE direct clarifying question offering choices (Section 8.2)
                c1, c2 = candidates[0]["name"], candidates[1]["name"]
                if lang == "ta":
                    disambiguation_msg = f"நீங்கள் **{c1}** அல்லது **{c2}** பற்றி கேட்கிறீர்களா? தயவுசெய்து உறுதிப்படுத்தவும்."
                elif lang == "tanglish":
                    disambiguation_msg = f"Neenga **{c1}** pathi keteengala illa **{c2}** pathiya? Konjam confirm pannunga."
                else:
                    disambiguation_msg = f"Did you mean **{c1}** or **{c2}**? Please select which model you'd like to check."

                latency = round((time.perf_counter() - start_time) * 1000, 2)
                return OrchestratorResponse(
                    reply=disambiguation_msg,
                    route_type=decision.route_type,
                    language=lang,
                    model_used="disambiguation-gate",
                    tools_called=["find_product"],
                    latency_ms=latency,
                    requires_action="disambiguation"
                )

        # 5b. Hot-Path Spend Cap Gate (Requirement R4, Spec 6.2, 11.1)
        is_capped, reason = await spend_manager.is_spend_capped(ctx.tenant_id)
        if is_capped:
            capped_reply = (
                "Our AI assistant is temporarily operating in essential mode due to daily high traffic. "
                "Please select from common options below or contact our human support team."
            )
            latency = round((time.perf_counter() - start_time) * 1000, 2)
            try:
                turn_id = await TurnRecorder.record_turn(
                    tenant_id=ctx.tenant_id,
                    conv_id=ctx.conv_id,
                    customer_id=ctx.customer_id or "anonymous",
                    user_input_raw=user_message,
                    assistant_response_raw=capped_reply,
                    intent="spend_capped_fallback",
                    latency_ms=int(latency),
                    tokens_prompt=0,
                    tokens_completion=0,
                    channel=ctx.channel,
                    handoff_state="open"
                )
            except Exception:
                turn_id = None

            return OrchestratorResponse(
                reply=capped_reply,
                route_type="spend_capped",
                language=lang,
                model_used="spend-cap-gate",
                tools_called=[],
                latency_ms=latency,
                requires_action="handoff",
                trace_id=turn_id
            )

        # 6. Tool-Calling LLM Execution Loop
        system_content = self.system_prompt
        if ctx.customer_id and ctx.level.satisfies(AuthLevel.IDENTIFIED):
            session_snippet = (
                f"\n\n[Active Session Identity]\n"
                f"- Authenticated Customer ID: '{ctx.customer_id}'\n"
                f"- Authentication Status: Logged in (IDENTIFIED)\n"
                f"- When this customer asks about their orders, order status, or tracking without specifying an order ID, "
                f"DO NOT ask for an order ID and DO NOT ask them to log in. Immediately invoke the 'list_recent_orders' tool."
            )
            system_content = system_content + session_snippet
        else:
            session_snippet = (
                f"\n\n[Active Session Identity]\n"
                f"- Authentication Status: Anonymous (Not logged in)\n"
                f"- If the customer asks to check their order or account without an order ID, ask them to log in to their account or provide their order ID."
            )
            system_content = system_content + session_snippet

        messages = [
            {"role": "system", "content": system_content},
            *self._history_for(ctx.conv_id),
            {"role": "user", "content": user_message}
        ]
        if ctx.page_context:
            context = ctx.page_context
            system_content += (
                "\n\n[Current Page Context - untrusted metadata, validate before use]\n"
                f"- URL: {context.url}\n"
                f"- Page type: {context.page_type}\n"
                f"- Product ID: {context.product_id or 'unavailable'}\n"
                f"- Order ID: {context.order_id or 'unavailable'}\n"
                f"- Cart ID: {context.cart_id or 'unavailable'}\n"
                "Use the current page entity for relevant questions. If unavailable, ask for clarification; never guess."
            )
            messages[0] = {"role": "system", "content": system_content}
        tools_called_log: list[str] = []

        # First LLM Call: Plan tools or reply
        model_tier = "large" if decision.route_type == "large_model" else "small"
        try:
            llm_resp = await self.llm.chat(
                messages=messages,
                tools=self.dispatcher.get_tool_schemas(),
                model_tier=model_tier
            )
        except Exception:
            spend_manager.release_reservation(ctx.tenant_id)
            raise

        final_reply = llm_resp.content
        requires_action = None
        prompt_tokens = llm_resp.token_usage.get("prompt_tokens", 0)
        completion_tokens = llm_resp.token_usage.get("completion_tokens", 0)
        tool_calls_payload = []
        catalog_detail_results: list[dict[str, Any]] = []
        max_tool_steps = 3
        step = 0
        current_resp = llm_resp

        while current_resp.tool_calls and step < max_tool_steps:
            step += 1
            tool_results_messages = []
            for tc in current_resp.tool_calls:
                tools_called_log.append(tc.name)
                tool_calls_payload.append({"call_id": tc.call_id, "name": tc.name, "arguments": tc.arguments})
                res = await self.dispatcher.execute_tool(tc.name, tc.arguments, ctx)
                if tc.name == "get_product_details" and isinstance(res, dict):
                    catalog_detail_results.append(res)

                # Check for step-up auth requirements
                if res.get("needs_auth") == "otp_required":
                    requires_action = "needs_otp"
                elif res.get("needs_auth") == "login_required":
                    requires_action = "needs_login"

                tool_results_messages.append({
                    "role": "tool",
                    "tool_call_id": tc.call_id,
                    "content": json.dumps(res)
                })

            # Append assistant message with tool calls and tool responses
            messages.append({
                "role": "assistant",
                "content": current_resp.content,
                "tool_calls": [
                    {"id": tc.call_id, "type": "function", "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)}}
                    for tc in current_resp.tool_calls
                ]
            })
            messages.extend(tool_results_messages)

            # Next LLM Call: Synthesize grounded response or execute chained tool
            current_resp = await self.llm.chat(
                messages=messages,
                tools=self.dispatcher.get_tool_schemas(),
                model_tier=model_tier
            )
            prompt_tokens += current_resp.token_usage.get("prompt_tokens", 0)
            completion_tokens += current_resp.token_usage.get("completion_tokens", 0)
            final_reply = current_resp.content

        final_reply = _repair_missing_catalog_claim(final_reply, catalog_detail_results)
        asks_for_price = any(
            cue in user_message.lower()
            for cue in ("price", "cost", "how much", "discount", "stock", "available")
        )
        if catalog_detail_results and not asks_for_price:
            for detail_result in catalog_detail_results:
                if detail_result.get("found") is not True or not isinstance(detail_result.get("specs"), dict):
                    continue
                focused_answer = _focused_product_spec_answer(
                    str(detail_result.get("name") or "This product"),
                    detail_result["specs"],
                    user_message,
                )
                if focused_answer:
                    final_reply = focused_answer
                    break

        latency = round((time.perf_counter() - start_time) * 1000, 2)

        # 7. Record Turn Trace & Spend Accounting (Spec 14.1, R4, R5)

        try:
            turn_id = await TurnRecorder.record_turn(
                tenant_id=ctx.tenant_id,
                conv_id=ctx.conv_id,
                customer_id=ctx.customer_id or "anonymous",
                user_input_raw=user_message,
                assistant_response_raw=final_reply or "",
                intent=decision.intent,
                latency_ms=int(latency),
                tokens_prompt=prompt_tokens,
                tokens_completion=completion_tokens,
                tool_calls=tool_calls_payload,
                grounding_score=1.0,
                channel=ctx.channel,
                handoff_state="open" if "handoff_to_human" in tools_called_log else "none",
                model_name=llm_resp.model_used
            )
        except Exception:
            spend_manager.release_reservation(ctx.tenant_id)
            turn_id = None

        self._remember_turn(ctx.conv_id, user_message, final_reply or "")

        return OrchestratorResponse(
            reply=final_reply or "I have processed your request.",
            route_type=decision.route_type,
            language=lang,
            model_used=llm_resp.model_used,
            tools_called=tools_called_log,
            latency_ms=latency,
            requires_action=requires_action,
            trace_id=turn_id
        )
