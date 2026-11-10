"""
MCP Handoff Server
Handles escalations to human support executives.
Complies with Specification Section 7.4 and 16.4.
"""

from typing import Any, Awaitable, Callable, Optional
import uuid
from datetime import datetime, timezone


class MCPHandoffServer:
    """Tool server for human escalations."""

    def __init__(
        self,
        persist_escalation: Optional[
            Callable[[str, str, str, str, str, Optional[str], str], Awaitable[None]]
        ] = None,
    ):
        self._escalations: list[dict[str, Any]] = []
        self._persist_escalation = persist_escalation

    async def handoff_to_human(
        self,
        reason: str,
        summary: str,
        conv_id: str = "conv_default",
        customer_id: Optional[str] = None,
        channel: str = "web",
    ) -> dict[str, Any]:
        """Create an escalation ticket for staff review."""
        ticket_id = f"ESC-{uuid.uuid4().hex[:6].upper()}"
        record = {
            "ticket_id": ticket_id,
            "conv_id": conv_id,
            "reason": reason,
            "summary": summary,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "pending_staff_pickup"
        }
        self._escalations.append(record)
        if self._persist_escalation:
            await self._persist_escalation(
                conv_id, reason, summary, ticket_id, "open", customer_id, channel
            )

        return {
            "success": True,
            "ticket_id": ticket_id,
            "message": (
                f"I have connected your issue to our human support team under reference #{ticket_id}. "
                f"An executive will review your conversation history and follow up shortly."
            )
        }
