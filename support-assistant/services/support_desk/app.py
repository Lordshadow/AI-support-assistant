"""
Support Desk Staff Backend Service
Complies with Specification Section 10.3 (Staff approval for > ₹2,000 refunds), 14.2 (Why This Answer view), and R5 Explainability.

Provides:
- Pending refund approval queue endpoints.
- Staff decision submission (Approve / Reject with notes and audit trail).
- "Why This Answer" conversation trace inspection for customer care supervisors.
- Key operating metrics for support desk dashboard.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import json

from core.models import RefundState, RefundResult
from core.tracing.trace_collector import TraceCollector
from adapters.mockshop.refund_adapter import MockRefundAdapter


class SupportDeskService:
    """Manages supervisor approvals, 'Why This Answer' traces, and Support Desk workflows."""

    def __init__(self, refund_adapter: MockRefundAdapter, trace_collector: TraceCollector):
        self.refund_adapter = refund_adapter
        self.trace_collector = trace_collector

    async def get_pending_refunds(self) -> List[Dict[str, Any]]:
        """Returns all refund requests held for supervisor review (> ₹2,000 threshold)."""
        pending: List[Dict[str, Any]] = []
        for r in self.refund_adapter._refunds.values():
            if r.state == RefundState.PENDING_APPROVAL:
                pending.append({
                    "refund_id": r.refund_id,
                    "order_id": r.order_id,
                    "customer_id": r.customer_id,
                    "amount_inr": r.amount_inr,
                    "reason": r.reason,
                    "state": r.state.value,
                    "created_at": r.created_at.strftime("%Y-%m-%d %H:%M:%S UTC")
                })
        # Sort newest first
        pending.sort(key=lambda x: x["created_at"], reverse=True)
        return pending

    async def approve_refund(
        self,
        refund_id: str,
        staff_id: str,
        notes: Optional[str] = None
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Supervisor approves a pending refund > ₹2,000."""
        try:
            updated: RefundResult = await self.refund_adapter.record_staff_decision(
                refund_id=refund_id,
                state=RefundState.APPROVED,
                decided_by=staff_id,
                note=notes
            )
            return True, "Refund successfully approved.", {
                "refund_id": updated.refund_id,
                "order_id": updated.order_id,
                "state": updated.state.value,
                "amount_inr": updated.amount_inr,
                "decided_by": updated.decided_by,
                "decided_at": updated.decided_at.strftime("%Y-%m-%d %H:%M:%S UTC") if updated.decided_at else "",
                "note": updated.note
            }
        except KeyError:
            return False, f"Refund request '{refund_id}' does not exist.", None
        except Exception as e:
            return False, str(e), None

    async def reject_refund(
        self,
        refund_id: str,
        staff_id: str,
        notes: str
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Supervisor rejects a pending refund with mandatory notes."""
        if not notes or not notes.strip():
            return False, "Staff audit note is mandatory when rejecting a refund.", None

        try:
            updated: RefundResult = await self.refund_adapter.record_staff_decision(
                refund_id=refund_id,
                state=RefundState.REJECTED,
                decided_by=staff_id,
                note=notes
            )
            return True, "Refund successfully rejected.", {
                "refund_id": updated.refund_id,
                "order_id": updated.order_id,
                "state": updated.state.value,
                "amount_inr": updated.amount_inr,
                "decided_by": updated.decided_by,
                "decided_at": updated.decided_at.strftime("%Y-%m-%d %H:%M:%S UTC") if updated.decided_at else "",
                "note": updated.note
            }
        except KeyError:
            return False, f"Refund request '{refund_id}' does not exist.", None
        except Exception as e:
            return False, str(e), None

    def get_why_this_answer_trace(self, trace_id: str) -> Optional[Dict[str, Any]]:
        """Returns Section 14.2 Explainability View for staff review."""
        return self.trace_collector.get_why_this_answer(trace_id)

    async def get_metrics(self) -> Dict[str, Any]:
        """Calculates dashboard performance & policy compliance metrics."""
        total = len(self.refund_adapter._refunds)
        auto_approved = sum(1 for r in self.refund_adapter._refunds.values() if r.state == RefundState.PROCESSED)
        pending = sum(1 for r in self.refund_adapter._refunds.values() if r.state == RefundState.PENDING_APPROVAL)
        staff_approved = sum(1 for r in self.refund_adapter._refunds.values() if r.state == RefundState.APPROVED)
        rejected = sum(1 for r in self.refund_adapter._refunds.values() if r.state == RefundState.REJECTED)

        return {
            "total_refund_requests": total,
            "auto_approved_under_2000": auto_approved,
            "pending_supervisor_review": pending,
            "supervisor_approved": staff_approved,
            "rejected_by_policy_or_staff": rejected,
            "auto_approval_ratio": round(auto_approved / total, 2) if total > 0 else 1.0
        }
