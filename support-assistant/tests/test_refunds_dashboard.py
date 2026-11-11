"""Regression tests for refund decision and review-detail data contracts."""

import sys
import unittest
from fastapi import HTTPException
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from services.dashboard_api import refunds


class _SessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *_):
        return False


def _run_sync(coro):
    stack, value = [coro], None
    while stack:
        try:
            result = stack[-1].send(value)
            value = None
            if hasattr(result, "send"):
                stack.append(result)
            else:
                value = result
        except StopIteration as finished:
            stack.pop()
            value = finished.value
    return value


class TestRefundDashboard(unittest.TestCase):
    def test_rejection_requires_a_server_side_note(self):
        staff = SimpleNamespace(tenant_id="tenant-a", staff_id="manager-1", role="manager", is_stepped_up=False)
        with self.assertRaises(HTTPException) as caught:
            _run_sync(refunds._decide("REF-QA-3", "rejected", refunds.RefundDecision(notes="  "), staff))
        self.assertEqual(caught.exception.status_code, 422)

    def test_pending_detail_returns_only_persisted_checks_and_order_facts(self):
        refund = SimpleNamespace(
            refund_id="REF-QA-1", order_id="ORD-QA-1", customer_id="cust-1",
            amount_inr=2500, reason="Damaged item", state="pending_approval",
            request_time=SimpleNamespace(isoformat=lambda: "2026-11-10T10:00:00+00:00"),
            eligibility_snapshot={"eligible": True, "max_amount": "2500"},
            policy_version_applied="policy-v4",
        )
        item = SimpleNamespace(
            item_id="item-1", product_name="Headphones", quantity=1,
            price=1200, refund_eligibility_verified=True, is_digital=False, is_refunded=False,
        )
        order = SimpleNamespace(order_id="ORD-QA-1", items=[item])
        first_result, second_result = MagicMock(), MagicMock()
        first_result.scalars.return_value.all.return_value = [refund]
        second_result.scalars.return_value.all.return_value = [order]
        session = SimpleNamespace(execute=AsyncMock(side_effect=[first_result, second_result]))
        staff = SimpleNamespace(tenant_id="tenant-a")

        with patch.object(refunds, "get_async_session", return_value=_SessionContext(session)):
            result = _run_sync(refunds._list_pending(staff))

        self.assertEqual(result[0]["checks"], [{
            "name": "Refund eligibility at request time",
            "passed": True,
            "details": "Eligibility decision recorded.",
        }])
        self.assertEqual(result[0]["policy_version_applied"], "policy-v4")
        self.assertEqual(result[0]["customer_trust_level"], "unknown")
        self.assertEqual(result[0]["order_items"][0]["title"], "Headphones")
        self.assertTrue(result[0]["order_items"][0]["returnable"])

    def test_approval_succeeds_for_current_model_without_requester_column(self):
        refund = SimpleNamespace(
            refund_id="REF-QA-2", tenant_id="tenant-a", order_id="ORD-QA-2",
            state="pending_approval", amount_inr=2500,
        )
        fetch_result, update_result = MagicMock(), MagicMock(rowcount=1)
        fetch_result.scalars.return_value.first.return_value = refund
        session = SimpleNamespace(execute=AsyncMock(side_effect=[fetch_result, update_result]), add=MagicMock())
        staff = SimpleNamespace(tenant_id="tenant-a", staff_id="manager-1", role="manager", is_stepped_up=False)

        store_review = AsyncMock(return_value={"success": True, "store_refund_id": 17})
        with patch.object(refunds, "get_async_session", return_value=_SessionContext(session)), patch.object(
            refunds, "_review_store_refund", store_review
        ):
            response = _run_sync(refunds._decide("REF-QA-2", "approved", refunds.RefundDecision(notes="Reviewed"), staff))

        self.assertTrue(response["success"])
        self.assertEqual(response["state"], "processed")
        self.assertEqual(session.execute.await_count, 2)
        session.add.assert_called_once()
        store_review.assert_awaited_once_with(refund, "approved", "Reviewed")


if __name__ == "__main__":
    unittest.main()
