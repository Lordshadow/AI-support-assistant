"""In-memory budget gate and ledger tests that do not require PostgreSQL."""

import unittest
from types import SimpleNamespace

from services.worker.spend_manager import SpendManager, compute_cost_inr


def _run_sync(coro):
    """Drive async methods with fake sessions without constructing an OS event loop."""
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


class _ScalarResult:
    def scalar(self):
        return 0


class _Session:
    def __init__(self):
        self.rows = []

    async def get(self, _model, _tenant_id):
        return SimpleNamespace(daily_spend_cap_inr=100, monthly_spend_cap_inr=1000)

    async def execute(self, _statement):
        return _ScalarResult()

    def add(self, row):
        self.rows.append(row)


class TestSpendManagerUnits(unittest.TestCase):
    def test_reservations_block_concurrent_calls_before_daily_cap(self):
        manager = SpendManager()
        session = _Session()

        capped, reason = _run_sync(manager.is_spend_capped("tenant-qa", 60, session=session))
        self.assertFalse(capped)
        self.assertEqual(reason, "Spend within limits")
        self.assertEqual(manager._get_cache_bucket("tenant-qa")["in_flight"], 60)

        capped, reason = _run_sync(manager.is_spend_capped("tenant-qa", 40, session=session))
        self.assertTrue(capped)
        self.assertIn("Daily spend cap", reason)
        self.assertEqual(manager._get_cache_bucket("tenant-qa")["in_flight"], 60)

    def test_record_spend_persists_ledger_and_reconciles_reservation(self):
        manager = SpendManager()
        session = _Session()
        manager._get_cache_bucket("tenant-qa")["in_flight"] = 15

        cost = _run_sync(manager.record_spend(
            tenant_id="tenant-qa",
            turn_id="turn-qa-1",
            model="unknown-test-model",
            prompt_tokens=1000,
            completion_tokens=1000,
            reserved_inr=15,
            session=session,
        ))

        self.assertEqual(cost, compute_cost_inr("unknown-test-model", 1000, 1000))
        self.assertEqual(len(session.rows), 1)
        self.assertEqual(session.rows[0].turn_id, "turn-qa-1")
        self.assertEqual(session.rows[0].cost_inr, cost)
        bucket = manager._get_cache_bucket("tenant-qa")
        self.assertEqual(bucket["in_flight"], 0)
        self.assertEqual(bucket["daily_spend"], cost)
        self.assertEqual(bucket["monthly_spend"], cost)


if __name__ == "__main__":
    unittest.main()
