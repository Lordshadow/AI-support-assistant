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
from core.ports import RefundPort


class SupportDeskService:
    """Manages supervisor approvals, 'Why This Answer' traces, and Support Desk workflows."""

    def __init__(self, refund_adapter: RefundPort, trace_collector: TraceCollector):
        self.refund_adapter = refund_adapter
        self.trace_collector = trace_collector

    async def get_pending_refunds(self) -> List[Dict[str, Any]]:
        """Returns all refund requests held for supervisor review (> ₹2,000 threshold)."""
        if hasattr(self.refund_adapter, "list_pending_refunds"):
            refunds = await self.refund_adapter.list_pending_refunds()
        elif hasattr(self.refund_adapter, "_refunds"):
            # Backward-compatible test adapter support; production wiring uses
            # PostgresRefundRepository above and never reaches this branch.
            refunds = [
                refund for refund in self.refund_adapter._refunds.values()
                if refund.state == RefundState.PENDING_APPROVAL
            ]
        else:
            raise RuntimeError("Configured refund adapter does not support pending-refund listing.")
        return [
            {
                "refund_id": refund.refund_id,
                "order_id": refund.order_id,
                "customer_id": refund.customer_id,
                "amount_inr": refund.amount_inr,
                "reason": refund.reason,
                "state": refund.state.value,
                "created_at": refund.created_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
            }
            for refund in refunds
        ]

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
        if hasattr(self.refund_adapter, "get_refund_metrics"):
            counts = await self.refund_adapter.get_refund_metrics()
        elif hasattr(self.refund_adapter, "_refunds"):
            refunds = list(self.refund_adapter._refunds.values())
            counts = {
                "total": len(refunds),
                "auto_approved": sum(1 for refund in refunds if refund.state == RefundState.PROCESSED),
                "pending": sum(1 for refund in refunds if refund.state == RefundState.PENDING_APPROVAL),
                "staff_approved": sum(1 for refund in refunds if refund.state == RefundState.APPROVED),
                "rejected": sum(1 for refund in refunds if refund.state == RefundState.REJECTED),
            }
        else:
            raise RuntimeError("Configured refund adapter does not support refund metrics.")
        total = counts["total"]
        auto_approved = counts["auto_approved"]
        pending = counts["pending"]
        staff_approved = counts["staff_approved"]
        rejected = counts["rejected"]

        return {
            "total_refund_requests": total,
            "auto_approved_under_2000": auto_approved,
            "pending_supervisor_review": pending,
            "supervisor_approved": staff_approved,
            "rejected_by_policy_or_staff": rejected,
            "auto_approval_ratio": round(auto_approved / total, 2) if total > 0 else 1.0
        }
