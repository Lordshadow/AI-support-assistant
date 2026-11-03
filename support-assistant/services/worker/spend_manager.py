"""
Spend Manager & Hot-Path Cap Enforcement (Requirement R4, Spec 6.2, 11.1).
Tracks daily (₹2,500) and monthly (₹50,000) token spend per tenant.
Enforces hard budget ceiling in chat hot-path, bypassing LLM when capped.
"""

from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple, Dict, Any
import uuid

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import SpendLedger, Tenant, AuditEvent
from db.session import get_async_session

# Token Pricing in INR per 1,000 tokens
PRICING_TABLE_INR = {
    # Groq Llama 3.3 70B: ~$0.59 / $0.79 per 1M tokens (~₹0.05 / ₹0.065 per 1k)
    "llama-3.3-70b-versatile": {"prompt": 0.050, "completion": 0.065},
    # Groq Llama 3.1 8B: ~$0.05 / $0.08 per 1M tokens (~₹0.005 / ₹0.008 per 1k)
    "llama-3.1-8b-instant": {"prompt": 0.005, "completion": 0.008},
    # NVIDIA NIM / Multilingual Embeddings (BGE-M3)
    "nvidia-nim-embedding": {"prompt": 0.010, "completion": 0.010},
    # Default fallback rate
    "default": {"prompt": 0.020, "completion": 0.030},
}


def compute_cost_inr(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Calculate cost in INR for model call."""
    rates = PRICING_TABLE_INR.get(model, PRICING_TABLE_INR["default"])
    cost = (prompt_tokens / 1000.0) * rates["prompt"] + (completion_tokens / 1000.0) * rates["completion"]
    return round(cost, 4)


class SpendManager:
    """In-memory fast cache backed by spend_ledger and tenants table."""

    def __init__(self, tenant_id: str = "tenant_novaretail"):
        self.tenant_id = tenant_id
        # In-memory accumulators: {tenant_id: {"daily": float, "monthly": float, "date": str}}
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._alerted_80: set = set()

    def _get_cache_bucket(self, tenant_id: str) -> Dict[str, Any]:
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        month_str = datetime.now(timezone.utc).strftime("%Y-%m")
        bucket = self._cache.get(tenant_id)

        if not bucket or bucket.get("date") != today_str:
            bucket = {
                "date": today_str,
                "month": month_str,
                "daily_spend": 0.0,
                "monthly_spend": 0.0,
                "daily_cap": 2500.0,
                "monthly_cap": 50000.0,
            }
            self._cache[tenant_id] = bucket
        return bucket

    async def is_spend_capped(self, tenant_id: str, session: Optional[AsyncSession] = None) -> Tuple[bool, str]:
        """
        Hot-path budget gate check.
        Returns: (is_capped: bool, reason: str)
        If daily spend >= ₹2,500 or monthly spend >= 95% (₹47,500), blocks LLM call.
        """
        bucket = self._get_cache_bucket(tenant_id)

        # 1. Check daily ceiling (₹2,500)
        if bucket["daily_spend"] >= bucket["daily_cap"]:
            return True, f"Daily spend cap of ₹{bucket['daily_cap']:,.2f} reached (Current: ₹{bucket['daily_spend']:,.2f})."

        # 2. Check monthly ceiling 95% threshold (₹47,500 of ₹50,000)
        monthly_threshold = bucket["monthly_cap"] * 0.95
        if bucket["monthly_spend"] >= monthly_threshold:
            return True, f"Monthly spend reached 95% threshold (Current: ₹{bucket['monthly_spend']:,.2f} / ₹{bucket['monthly_cap']:,.2f})."

        # 3. Spend warning alert at 80% (₹40,000)
        if bucket["monthly_spend"] >= (bucket["monthly_cap"] * 0.80):
            alert_key = f"{tenant_id}:{bucket['month']}:80pct"
            if alert_key not in self._alerted_80:
                self._alerted_80.add(alert_key)
                # Emit structured spend alert
                # In production, this bridges to webhook/monitoring
                print(f"[ALERT: SPEND_WARNING_80_PERCENT] Tenant '{tenant_id}' monthly spend reached ₹{bucket['monthly_spend']:,.2f}")

        return False, "Spend within limits"

    async def record_spend(
        self,
        tenant_id: str,
        turn_id: Optional[str],
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        purpose: str = "chat",
        session: Optional[AsyncSession] = None,
    ) -> float:
        """
        Updates in-memory fast meters and inserts row into spend_ledger.
        Returns the computed INR cost.
        """
        cost_inr = compute_cost_inr(model, prompt_tokens, completion_tokens)
        bucket = self._get_cache_bucket(tenant_id)
        bucket["daily_spend"] += cost_inr
        bucket["monthly_spend"] += cost_inr

        # Async DB persist
        async def _persist(s: AsyncSession):
            row = SpendLedger(
                id=f"SPEND-{uuid.uuid4().hex[:12].upper()}",
                tenant_id=tenant_id,
                turn_id=turn_id,
                purpose=purpose,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost_inr=cost_inr,
                created_at=datetime.now(timezone.utc)
            )
            s.add(row)

        if session:
            await _persist(session)
        else:
            async with get_async_session(tenant_id=tenant_id) as s:
                await _persist(s)

        return cost_inr

    def set_mock_spend(self, tenant_id: str, daily: float, monthly: float):
        """Helper for testing budget thresholds."""
        bucket = self._get_cache_bucket(tenant_id)
        bucket["daily_spend"] = daily
        bucket["monthly_spend"] = monthly


# Global singleton instance
spend_manager = SpendManager()
