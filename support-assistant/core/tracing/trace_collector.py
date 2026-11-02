"""
Per-Turn Audit Trace Collector & 'Why This Answer' Inspector
Complies with Specification Section 14.1 (Per-turn trace fields), 14.2, and R5 Explainability.

Records complete factual evidence for every conversation turn.
Enforces DPDP PII masking before persisting to DB or logs.
"""

from typing import Any, Optional
from dataclasses import dataclass, field
import uuid
from datetime import datetime, timezone

from core.tracing.pii_masker import PIIMasker
from core.tracing.grounding_verifier import GroundingResult


@dataclass
class TurnTrace:
    trace_id: str
    conv_id: str
    msg_id: str
    timestamp: str
    customer_message: str
    detected_language: str
    route_type: str
    intent: str
    confidence: float
    auth_level: str
    resolved_product_id: Optional[str] = None
    retrieved_chunk_ids: list[str] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    model_used: str = "none"
    latency_ms: float = 0.0
    grounding_passed: bool = True
    grounding_violations: list[str] = field(default_factory=list)
    final_reply: str = ""
    refund_decision: Optional[dict[str, Any]] = None


class TraceCollector:
    """Stores per-turn evidence traces and powers the 'Why This Answer' view for staff."""

    def __init__(self):
        # In-memory store: trace_id -> TurnTrace
        self._traces: dict[str, TurnTrace] = {}
        # Index: (conv_id, msg_id) -> trace_id
        self._msg_index: dict[str, str] = {}

    def record_turn(
        self,
        conv_id: str,
        customer_message: str,
        detected_language: str,
        route_type: str,
        intent: str,
        auth_level: str,
        final_reply: str,
        confidence: float = 1.0,
        resolved_product_id: Optional[str] = None,
        retrieved_chunk_ids: Optional[list[str]] = None,
        tool_calls: Optional[list[dict[str, Any]]] = None,
        model_used: str = "none",
        latency_ms: float = 0.0,
        grounding_result: Optional[GroundingResult] = None,
        refund_decision: Optional[dict[str, Any]] = None,
        msg_id: Optional[str] = None
    ) -> TurnTrace:
        trace_id = f"trc_{uuid.uuid4().hex[:12]}"
        message_id = msg_id or f"msg_{uuid.uuid4().hex[:8]}"

        # Apply DPDP PII masking to customer message and final reply before archiving
        safe_msg = PIIMasker.mask_text(customer_message)
        safe_reply = PIIMasker.mask_text(final_reply)

        # Sanitize tool arguments to remove any potential personal data
        safe_tools = []
        for tc in (tool_calls or []):
            safe_tc = {
                "name": tc.get("name") or tc.get("tool_name"),
                "arguments": PIIMasker.mask_text(str(tc.get("arguments", {}))),
                "status": tc.get("status", "success")
            }
            safe_tools.append(safe_tc)

        trace = TurnTrace(
            trace_id=trace_id,
            conv_id=conv_id,
            msg_id=message_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            customer_message=safe_msg,
            detected_language=detected_language,
            route_type=route_type,
            intent=intent,
            confidence=confidence,
            auth_level=auth_level,
            resolved_product_id=resolved_product_id,
            retrieved_chunk_ids=retrieved_chunk_ids or [],
            tool_calls=safe_tools,
            model_used=model_used,
            latency_ms=latency_ms,
            grounding_passed=grounding_result.passed if grounding_result else True,
            grounding_violations=grounding_result.violations if grounding_result else [],
            final_reply=safe_reply,
            refund_decision=refund_decision
        )

        self._traces[trace_id] = trace
        self._msg_index[f"{conv_id}:{message_id}"] = trace_id
        return trace

    def get_turn_trace(self, trace_id: str) -> Optional[TurnTrace]:
        return self._traces.get(trace_id)

    def get_why_this_answer(self, trace_id: str) -> Optional[dict[str, Any]]:
        """
        The 'Why This Answer' view for Support Desk staff (Section 14.2).
        Presents the evidence, tools, grounding checks, and route for staff verification.
        """
        trace = self._traces.get(trace_id)
        if not trace:
            return None

        return {
            "trace_id": trace.trace_id,
            "conversation_id": trace.conv_id,
            "timestamp": trace.timestamp,
            "routing_explanation": {
                "route_type": trace.route_type,
                "inferred_intent": trace.intent,
                "confidence_score": trace.confidence,
                "model_selected": trace.model_used
            },
            "factual_grounding": {
                "passed_gate": trace.grounding_passed,
                "violations_detected": trace.grounding_violations,
                "resolved_product": trace.resolved_product_id,
                "knowledge_chunks_consulted": trace.retrieved_chunk_ids
            },
            "tools_executed": trace.tool_calls,
            "latency": f"{trace.latency_ms} ms",
            "audit_trail": {
                "auth_level": trace.auth_level,
                "sanitized_user_input": trace.customer_message,
                "sanitized_bot_output": trace.final_reply
            }
        }
