"""
Spend Manager & Hot-Path Cap Enforcement (Requirement R4, Spec 6.2, 11.1).
Tracks daily (₹2,500) and monthly (₹50,000) token spend per tenant.
Enforces hard budget ceiling in chat hot-path, bypassing LLM when capped.
"""

from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple, Dict, Any
import uuid
import logging

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import SpendLedger, Tenant, AuditEvent
from db.session import get_async_session

logger = logging.getLogger(__name__)

# Token Pricing in INR per 1,000 tokens
PRICING_TABLE_INR = {
    # Groq Open-Weights
    "openai/gpt-oss-120b": {"prompt": 0.040, "completion": 0.060},
    "openai/gpt-oss-20b": {"prompt": 0.005, "completion": 0.008},
    "qwen/qwen3.8-27b": {"prompt": 0.015, "completion": 0.020},
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
                "in_flight": 0.0,
            }
            self._cache[tenant_id] = bucket
        return bucket

    async def is_spend_capped(
        self,
        tenant_id: str,
        reserve_inr: float = 15.0,
        session: Optional[AsyncSession] = None
    ) -> Tuple[bool, str]:
        """
        Hot-path budget gate check with concurrency-safe reservation.
        Returns: (is_capped: bool, reason: str)
        If daily spend + in-flight >= ₹2,500 or monthly spend >= 95% (₹47,500), blocks LLM call.
        """
        bucket = self._get_cache_bucket(tenant_id)
        async def refresh_from_db(db_session: AsyncSession) -> None:
            tenant = await db_session.get(Tenant, tenant_id)
            if not tenant:
                return
            bucket["daily_cap"] = float(tenant.daily_spend_cap_inr or 2500)
            bucket["monthly_cap"] = float(tenant.monthly_spend_cap_inr or 50000)
            now = datetime.now(timezone.utc)
            day_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
            month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
            daily_stmt = select(func.coalesce(func.sum(SpendLedger.cost_inr), 0.0)).where(
                SpendLedger.tenant_id == tenant_id, SpendLedger.created_at >= day_start
            )
            monthly_stmt = select(func.coalesce(func.sum(SpendLedger.cost_inr), 0.0)).where(
                SpendLedger.tenant_id == tenant_id, SpendLedger.created_at >= month_start
            )
            bucket["daily_spend"] = max(bucket["daily_spend"], float((await db_session.execute(daily_stmt)).scalar() or 0))
            bucket["monthly_spend"] = max(bucket["monthly_spend"], float((await db_session.execute(monthly_stmt)).scalar() or 0))

        try:
            if session is not None:
                await refresh_from_db(session)
            else:
                async with get_async_session(tenant_id=tenant_id) as db_session:
                    await refresh_from_db(db_session)
        except Exception:
            # Keep the last known safe caps and spend values if storage is unavailable.
            logger.exception("Failed to refresh persisted spend limits for tenant %s", tenant_id)
        effective_daily = bucket["daily_spend"] + bucket.get("in_flight", 0.0)

        # 1. Check daily ceiling (₹2,500)
        if effective_daily + reserve_inr >= bucket["daily_cap"]:
            return True, f"Daily spend cap of ₹{bucket['daily_cap']:,.2f} reached (Current: ₹{bucket['daily_spend']:,.2f})."

        # 2. Check monthly ceiling 95% threshold (₹47,500 of ₹50,000)
        monthly_threshold = bucket["monthly_cap"] * 0.95
        effective_monthly = bucket["monthly_spend"] + bucket.get("in_flight", 0.0)
        if effective_monthly + reserve_inr >= monthly_threshold:
            return True, f"Monthly spend reached 95% threshold (Current: ₹{bucket['monthly_spend']:,.2f} / ₹{bucket['monthly_cap']:,.2f})."

        # Reserve estimated cost for in-flight model call to prevent concurrent burst over-cap leakage
        bucket["in_flight"] = bucket.get("in_flight", 0.0) + reserve_inr

        # 3. Spend warning alert at 80% (₹40,000)
        if bucket["monthly_spend"] >= (bucket["monthly_cap"] * 0.80):
            alert_key = f"{tenant_id}:{bucket['month']}:80pct"
            if alert_key not in self._alerted_80:
                self._alerted_80.add(alert_key)
                print(f"[ALERT: SPEND_WARNING_80_PERCENT] Tenant '{tenant_id}' monthly spend reached ₹{bucket['monthly_spend']:,.2f}")

        return False, "Spend within limits"

    def release_reservation(self, tenant_id: str, reserved_inr: float = 15.0):
        """Releases reserved in-flight budget if model call was aborted or errored."""
        bucket = self._get_cache_bucket(tenant_id)
        bucket["in_flight"] = max(0.0, bucket.get("in_flight", 0.0) - reserved_inr)

    async def record_spend(
        self,
        tenant_id: str,
        turn_id: Optional[str],
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        purpose: str = "chat",
        reserved_inr: float = 15.0,
        session: Optional[AsyncSession] = None,
    ) -> float:
        """
        Updates in-memory fast meters and inserts row into spend_ledger.
        Releases in-flight reservation and applies actual computed INR cost.
        """
        cost_inr = compute_cost_inr(model, prompt_tokens, completion_tokens)
        bucket = self._get_cache_bucket(tenant_id)
        bucket["in_flight"] = max(0.0, bucket.get("in_flight", 0.0) - reserved_inr)
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
