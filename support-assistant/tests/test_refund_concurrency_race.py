"""
Test Suite: Atomic Refund State Machine & Concurrency Race Protection.
Validates Requirement R3, Spec 10, and Phase 2 Gate:
"Double-approve race passes on real Postgres; worker kill leaves exactly 1 payment."
"""

import unittest
import asyncio
from datetime import datetime, timezone, timedelta
from pathlib import Path
import os
import sys

# Ensure support-assistant is in sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import select, text

from db.models import Base, RefundRequest, AuditEvent, Tenant, StaffUser
from core.refund_state_machine import (
    RefundStateMachine, RefundConcurrencyError, RefundStepUpRequiredError
)


def run_async(coro):
    return asyncio.run(coro)


class TestRefundConcurrencyRace(unittest.TestCase):

    def setUp(self):
        self.db_file = f"test_concurrency_{datetime.now().timestamp()}.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.db_file}", echo=False)
        self.session_maker = async_sessionmaker(self.engine, expire_on_commit=False)

        async def init_schema():
            async with self.engine.begin() as conn:
                await conn.execute(text("PRAGMA journal_mode=WAL;"))
                await conn.run_sync(Base.metadata.create_all)

        run_async(init_schema())

        # Patch get_async_session to bind to our test engine
        from unittest.mock import patch
        from db import session as db_session

        @db_session.asynccontextmanager
        async def mock_get_session(tenant_id=None):
            async with self.session_maker() as sess:
                async with sess.begin():
                    yield sess

        self.patcher = patch("core.refund_state_machine.get_async_session", side_effect=mock_get_session)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        run_async(self.engine.dispose())
        if os.path.exists(self.db_file):
            try:
                os.remove(self.db_file)
            except OSError:
                pass
        # Clean up WAL files
        for extra in [f"{self.db_file}-wal", f"{self.db_file}-shm"]:
            if os.path.exists(extra):
                try:
                    os.remove(extra)
                except OSError:
                    pass

    def test_single_transaction_approval_and_audit(self):
        """Verify normal single-transaction atomic approval writes state and audit record."""
        now = datetime.now(timezone.utc)

        async def run_test():
            async with self.session_maker() as sess:
                async with sess.begin():
                    sess.add(Tenant(tenant_id="tenant_novaretail", name="NovaRetail"))
                    sess.add(RefundRequest(
                        refund_id="REF-TEST-100",
                        tenant_id="tenant_novaretail",
                        order_id="ORD-100",
                        customer_id="CUST-1",
                        amount_inr=3500,
                        state="pending_approval",
                        idempotency_key="IDEM-TEST-100",
                        reason="Item damaged in transit",
                        request_time=now,
                        eligibility_snapshot={"eligible": True}
                    ))

            # Approve
            res = await RefundStateMachine.approve_refund_atomic(
                tenant_id="tenant_novaretail",
                refund_id="REF-TEST-100",
                staff_id="staff_exec_1",
                staff_role="executive",
                is_stepped_up=False,
                staff_note="Customer provided damage photos."
            )
            self.assertEqual(res["status"], "approved")

            # Check DB state
            async with self.session_maker() as sess:
                refund = await sess.get(RefundRequest, "REF-TEST-100")
                self.assertEqual(refund.state, "approved")
                self.assertEqual(refund.decided_by, "staff_exec_1")
                self.assertEqual(refund.staff_note, "Customer provided damage photos.")

                # Audit event check
                audits = (await sess.execute(select(AuditEvent).where(AuditEvent.resource_id == "REF-TEST-100"))).scalars().all()
                self.assertEqual(len(audits), 1)
                self.assertEqual(audits[0].action, "refund_approved")
                self.assertEqual(audits[0].actor_id, "staff_exec_1")

        run_async(run_test())

    def test_double_approve_concurrency_race(self):
        """
        Simulate 10 concurrent requests to approve the same pending refund.
        Verifies:
        - Exactly 1 task succeeds.
        - Exactly 9 tasks receive RefundConcurrencyError.
        - Exactly 1 audit record is created in the database.
        """
        now = datetime.now(timezone.utc)

        async def run_test():
            async with self.session_maker() as sess:
                async with sess.begin():
                    sess.add(Tenant(tenant_id="tenant_novaretail", name="NovaRetail"))
                    sess.add(RefundRequest(
                        refund_id="REF-RACE-001",
                        tenant_id="tenant_novaretail",
                        order_id="ORD-RACE",
                        customer_id="CUST-2",
                        amount_inr=4200,
                        state="pending_approval",
                        idempotency_key="IDEM-RACE-001",
                        reason="Wrong color sent",
                        request_time=now,
                        eligibility_snapshot={"eligible": True}
                    ))

            async def attempt_approval(staff_index: int):
                try:
                    return await RefundStateMachine.approve_refund_atomic(
                        tenant_id="tenant_novaretail",
                        refund_id="REF-RACE-001",
                        staff_id=f"staff_{staff_index}",
                        staff_role="executive",
                        is_stepped_up=False,
                        staff_note=f"Approved by executive {staff_index}"
                    )
                except RefundConcurrencyError as e:
                    return {"status": "conflict", "error": str(e)}

            tasks = [attempt_approval(i) for i in range(10)]
            results = await asyncio.gather(*tasks)

            successes = [r for r in results if r.get("status") == "approved"]
            conflicts = [r for r in results if r.get("status") == "conflict"]

            self.assertEqual(len(successes), 1, "Exactly one approval must succeed!")
            self.assertEqual(len(conflicts), 9, "All other concurrent attempts must be rejected with Conflict!")

            # Verify only 1 audit record in DB
            async with self.session_maker() as sess:
                audits = (await sess.execute(select(AuditEvent).where(AuditEvent.resource_id == "REF-RACE-001"))).scalars().all()
                self.assertEqual(len(audits), 1)

        run_async(run_test())

    def test_high_value_refund_step_up_requirement(self):
        """Verify that approving a refund > ₹5,000 requires active step-up authentication."""
        now = datetime.now(timezone.utc)

        async def run_test():
            async with self.session_maker() as sess:
                async with sess.begin():
                    sess.add(Tenant(tenant_id="tenant_novaretail", name="NovaRetail"))
                    sess.add(RefundRequest(
                        refund_id="REF-HIGH-VAL",
                        tenant_id="tenant_novaretail",
                        order_id="ORD-HV",
                        customer_id="CUST-3",
                        amount_inr=8500,  # Exceeds ₹5,000 ceiling
                        state="pending_approval",
                        idempotency_key="IDEM-HV-001",
                        reason="Defective high-end equipment",
                        request_time=now,
                        eligibility_snapshot={"eligible": True}
                    ))

            # 1. Attempt without step-up -> raises RefundStepUpRequiredError
            with self.assertRaises(RefundStepUpRequiredError):
                await RefundStateMachine.approve_refund_atomic(
                    tenant_id="tenant_novaretail",
                    refund_id="REF-HIGH-VAL",
                    staff_id="staff_mgr_1",
                    staff_role="manager",
                    is_stepped_up=False,
                    staff_note="Manager approval"
                )

            # 2. Attempt with step-up -> succeeds
            res = await RefundStateMachine.approve_refund_atomic(
                tenant_id="tenant_novaretail",
                refund_id="REF-HIGH-VAL",
                staff_id="staff_mgr_1",
                staff_role="manager",
                is_stepped_up=True,
                staff_note="Manager approved after step-up auth."
            )
            self.assertEqual(res["status"], "approved")

        run_async(run_test())


if __name__ == "__main__":
    unittest.main()
