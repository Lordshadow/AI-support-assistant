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

from core.models import SessionContext
from core.router.router import AIRouter, RouteDecision
from services.mcp_servers.dispatcher import MCPToolDispatcher
from services.worker.llm_client import LLMClient, MockLLMClient, ToolCall
from services.worker.spend_manager import spend_manager
from services.worker.turn_recorder import TurnRecorder


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

    async def process_turn(
        self,
        user_message: str,
        ctx: SessionContext
    ) -> OrchestratorResponse:
        start_time = time.perf_counter()

        # 1. Routing & Normalization Step
        decision: RouteDecision = await self.router.route_message(user_message, ctx)
        lang = decision.normalized.language

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
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_message}
        ]
        tools_called_log: list[str] = []

        # First LLM Call: Plan tools or reply
        model_tier = "large" if decision.route_type == "large_model" else "small"
        llm_resp = await self.llm.chat(
            messages=messages,
            tools=self.dispatcher.get_tool_schemas(),
            model_tier=model_tier
        )

        final_reply = llm_resp.content
        requires_action = None
        synth_resp = None

        if llm_resp.tool_calls:
            # Execute requested tools via Dispatcher
            tool_results_messages = []
            for tc in llm_resp.tool_calls:
                tools_called_log.append(tc.name)
                res = await self.dispatcher.execute_tool(tc.name, tc.arguments, ctx)

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
                "content": None,
                "tool_calls": [
                    {"id": tc.call_id, "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)}}
                    for tc in llm_resp.tool_calls
                ]
            })
            messages.extend(tool_results_messages)

            # Second LLM Call: Synthesize grounded response
            synth_resp = await self.llm.chat(
                messages=messages,
                model_tier=model_tier
            )
            final_reply = synth_resp.content

        latency = round((time.perf_counter() - start_time) * 1000, 2)

        # 7. Record Turn Trace & Spend Accounting (Spec 14.1, R4, R5)
        prompt_tokens = llm_resp.token_usage.get("prompt_tokens", 0)
        completion_tokens = llm_resp.token_usage.get("completion_tokens", 0)
        if synth_resp:
            prompt_tokens += synth_resp.token_usage.get("prompt_tokens", 0)
            completion_tokens += synth_resp.token_usage.get("completion_tokens", 0)

        tool_calls_payload = [
            {"call_id": tc.call_id, "name": tc.name, "arguments": tc.arguments}
            for tc in llm_resp.tool_calls
        ]

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
            turn_id = None

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
