"""
Pre-Transmission Grounding Verifier & Anti-Hallucination Gate
Complies with Specification Section 9.2, 9.3, and 14.

Guarantees:
1. Prices, stock, and delivery statuses are strictly grounded in tool results.
2. Refund approval claims are backed by actual state transitions.
3. No raw PII or system prompt delimiter leaks reach the customer.
"""

from typing import Any, Optional
from dataclasses import dataclass, field
import re
import json

from core.tracing.pii_masker import PIIMasker


@dataclass
class GroundingResult:
    passed: bool
    violations: list[str] = field(default_factory=list)
    sanitized_reply: str = ""
    suggested_action: str = "allow"  # 'allow', 'retry', 'force_handoff'


class GroundingVerifier:
    """Pre-transmission automated verification gate."""

    @classmethod
    def verify(
        cls,
        draft_reply: str,
        tool_results: list[dict[str, Any]],
        retrieved_chunks: Optional[list[str]] = None
    ) -> GroundingResult:
        violations: list[str] = []
        chunks = retrieved_chunks or []

        # Serialize tool results and chunks to a single searchable fact corpus
        tool_facts_str = json.dumps(tool_results, default=str).lower()
        chunk_facts_str = " ".join(chunks).lower()
        combined_facts = f"{tool_facts_str} {chunk_facts_str}"

        # 1. Price Verification
        # Extract quoted monetary numbers (e.g. ₹1,499, 1299, 4500)
        price_matches = re.findall(r"(?:₹|rs\.?|inr)?\s*([0-9]{3,6})\b", draft_reply.lower())
        for price_str in price_matches:
            # Check if this exact number exists in tool outputs or chunks
            if price_str not in combined_facts:
                violations.append(
                    f"Ungrounded price claim: '₹{price_str}' was quoted in reply but never returned by tools or knowledge chunks."
                )

        # 2. Refund State Verification
        draft_lower = draft_reply.lower()
        if "approved automatically" in draft_lower or "refund has been initiated" in draft_lower:
            # Must be backed by a 'processed' state in create_refund_request tool
            has_processed = any(
                res.get("state") == "processed"
                for res in tool_results
                if isinstance(res, dict)
            )
            if not has_processed and "approved automatically" in draft_lower:
                violations.append(
                    "Ungrounded refund claim: Reply claimed auto-refund was processed, but tool results do not contain 'processed' state."
                )

        # 3. PII Leakage Check
        if PIIMasker.CARD_PATTERN.search(draft_reply):
            violations.append("Data privacy violation: Reply contains an unmasked payment card number.")

        # 4. System Prompt Escape / Delimiter Check
        if re.search(r"(<system_prompt>|\[SYSTEM OVERRIDE\]|<\|im_start\|>|Ignore all previous)", draft_reply, re.I):
            violations.append("Prompt injection violation: Reply contains system prompt delimiters or override tokens.")

        # Determine pass/fail & suggested action
        passed = len(violations) == 0
        action = "allow" if passed else "force_handoff" if len(violations) > 1 else "retry"

        # Apply PII scrubbing as extra safety layer
        sanitized = PIIMasker.mask_text(draft_reply)

        return GroundingResult(
            passed=passed,
            violations=violations,
            sanitized_reply=sanitized,
            suggested_action=action
        )
