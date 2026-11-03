"""
Bot Silencing Guard (Spec 5.2, 16.4).
Checks whether a customer's conversation is currently escalated to human support.
Silences AI model calls while an escalation is open or assigned to an executive.
"""

import asyncio
from typing import Optional, Tuple, Set
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Escalation
from db.session import get_async_session


class EscalationGuard:
    """Evaluates whether the AI bot should remain silent during human takeover."""

    def __init__(self):
        # In-memory set for active fast checks: {conv_id}
        self._active_silenced_convs: Set[str] = set()

    def set_mock_silenced(self, conv_id: str, silenced: bool = True):
        """Helper for unit and integration testing."""
        if silenced:
            self._active_silenced_convs.add(conv_id)
        else:
            self._active_silenced_convs.discard(conv_id)

    async def is_bot_silenced(
        self,
        tenant_id: str,
        conv_id: str,
        session: Optional[AsyncSession] = None
    ) -> Tuple[bool, Optional[str]]:
        """
        Returns (is_silenced, escalation_state).
        If an escalation exists with state in ('open', 'assigned'), returns True.
        """
        # Fast in-memory check first
        if conv_id in self._active_silenced_convs:
            return True, "open"

        async def _check(s: AsyncSession) -> Tuple[bool, Optional[str]]:
            stmt = select(Escalation).where(
                Escalation.tenant_id == tenant_id,
                Escalation.conv_id == conv_id,
                Escalation.state.in_(["open", "assigned"])
            )
            esc = (await s.execute(stmt)).scalars().first()
            if esc:
                return True, esc.state
            return False, None

        if session:
            return await _check(session)

        try:
            async with asyncio.timeout(1.0):
                async with get_async_session(tenant_id=tenant_id) as s:
                    return await _check(s)
        except Exception:
            return False, None


escalation_guard = EscalationGuard()
