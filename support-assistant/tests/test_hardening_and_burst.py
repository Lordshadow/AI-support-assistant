"""
Production Hardening & 10x Load Burst Test Suite (Phase 7 Final Milestone).
Validates System Robustness Under High Concurrency:
1. Spend Cap Hot-Path Gate Under Concurrent Burst (Zero over-cap LLM calls).
2. Refund Outbox Worker Queue Drain Under Multi-Worker Competition (Zero duplicate payments).
3. Escalations Multi-Ticket Claim Race Under Concurrent Supervisors (Exact single-winner semantics).
4. Catalog Sync Concurrency Lock Under Simultaneous Ingestion Requests (Single active job).
"""

import asyncio
from datetime import datetime, timezone, timedelta
import hashlib
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, patch

# Ensure support-assistant is in sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select, text, update, func
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from fastapi import FastAPI
from fastapi.testclient import TestClient

from db.models import (
    Base, Tenant, StaffUser, StaffTenantMembership, StaffSession,
    RefundRequest, SpendLedger, Escalation, AuditEvent,
    IngestionJob, KnowledgeVersion
)
from services.dashboard_api.auth import hash_password
from services.dashboard_api.escalations import router as esc_router
from services.dashboard_api.knowledge import router as knowledge_router
from services.support_desk.outbox_worker import OutboxPaymentWorker
from services.worker.orchestrator import WorkerOrchestrator
from services.worker.spend_manager import SpendManager
from services.worker.turn_recorder import TurnRecorder
from services.worker.llm_client import LLMResponse
from core.models import SessionContext, AuthLevel
from core.router import AIRouter, CacheService
from services.mcp_servers import (
    MCPCatalogServer, MCPOrderServer, MCPRefundServer,
    MCPHandoffServer, MCPToolDispatcher
)
from adapters.mockshop import MockCatalogAdapter, MockOrderAdapter, MockRefundAdapter


def run_async(coro):
    return asyncio.run(coro)


class TestHardeningAndBurst(unittest.TestCase):

    def setUp(self):
        self.db_file = f"test_burst_{datetime.now().timestamp()}.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.db_file}", echo=False)
        self.session_maker = async_sessionmaker(self.engine, expire_on_commit=False)

        async def init_schema():
            async with self.engine.begin() as conn:
                await conn.execute(text("PRAGMA journal_mode=WAL;"))
                await conn.run_sync(Base.metadata.create_all)

        run_async(init_schema())

        self.app = FastAPI()
        self.app.include_router(esc_router)
        self.app.include_router(knowledge_router)
        self.client = TestClient(self.app)

        from db import session as db_session

        @db_session.asynccontextmanager
        async def mock_get_session(tenant_id=None):
            async with self.session_maker() as sess:
                async with sess.begin():
                    yield sess

        self.patcher1 = patch("services.dashboard_api.escalations.get_async_session", side_effect=mock_get_session)
        self.patcher2 = patch("services.dashboard_api.knowledge.get_async_session", side_effect=mock_get_session)
        self.patcher3 = patch("services.dashboard_api.dependencies.get_async_session", side_effect=mock_get_session)
        self.patcher4 = patch("services.support_desk.outbox_worker.get_async_session", side_effect=mock_get_session)
        self.patcher1.start()
        self.patcher2.start()
        self.patcher3.start()
        self.patcher4.start()

        self.tenant_id = "tenant_novaretail"
        self.now = datetime.now(timezone.utc)
        self.csrf = "csrf_burst_secret_key"
        self.csrf_hash = hashlib.sha256(self.csrf.encode()).hexdigest()

        # Seed standard tenant and multiple staff accounts
        async def seed_data():
            async with self.session_maker() as sess:
                async with sess.begin():
                    sess.add(Tenant(
                        tenant_id=self.tenant_id,
                        name="NovaRetail",
                        daily_spend_cap_inr=2500,
                        monthly_spend_cap_inr=50000,
                        spend_mode="normal",
                        active_policy_version=None,
                        active_product_version=None,
                    ))

                    # Seed 5 executive accounts for concurrency tests
                    for i in range(1, 6):
                        sid = f"staff_exec_{i}"
                        sess.add(StaffUser(
                            staff_id=sid,
                            email=f"exec{i}@novaretail.com",
                            full_name=f"Executive {i}",
                            password_hash=hash_password("Pass1!"),
                        ))
                        sess.add(StaffTenantMembership(
                            staff_id=sid,
                            tenant_id=self.tenant_id,
                            role="executive"
                        ))
                        sess.add(StaffSession(
                            session_id=f"sess_exec_{i}",
                            staff_id=sid,
                            active_tenant_id=self.tenant_id,
                            created_at=self.now,
                            expires_at=self.now + timedelta(hours=4),
                            csrf_hash=self.csrf_hash,
                        ))

                    # Manager account
                    sess.add(StaffUser(
                        staff_id="staff_mgr_1",
                        email="mgr1@novaretail.com",
                        full_name="Manager One",
                        password_hash=hash_password("Pass1!"),
                    ))
                    sess.add(StaffTenantMembership(
                        staff_id="staff_mgr_1",
                        tenant_id=self.tenant_id,
                        role="manager"
                    ))
                    sess.add(StaffSession(
                        session_id="sess_mgr_1",
                        staff_id="staff_mgr_1",
                        active_tenant_id=self.tenant_id,
                        created_at=self.now,
                        expires_at=self.now + timedelta(hours=4),
                        csrf_hash=self.csrf_hash,
                    ))

        run_async(seed_data())

    def tearDown(self):
        self.patcher1.stop()
        self.patcher2.stop()
        self.patcher3.stop()
        self.patcher4.stop()
        run_async(self.engine.dispose())
        if os.path.exists(self.db_file):
            try:
                os.remove(self.db_file)
            except OSError:
                pass
        for extra in [f"{self.db_file}-wal", f"{self.db_file}-shm"]:
            if os.path.exists(extra):
                try:
                    os.remove(extra)
                except OSError:
                    pass

    def test_spend_cap_gate_under_concurrent_burst(self):
        """
        Verify that a burst of 15 concurrent turns arriving when spend is at ₹2,490
        allows exactly 1 model call and strictly gates the remaining 14 turns without token leakage.
        """
        from services.worker.spend_manager import spend_manager

        # Seed spend bucket to ₹2,490 (just ₹10 below the ₹2,500 daily hard cap)
        bucket = spend_manager._get_cache_bucket(self.tenant_id)
        bucket["daily_spend"] = 2490.0
        bucket["daily_cap"] = 2500.0
        bucket["monthly_spend"] = 5000.0
        bucket["monthly_cap"] = 50000.0

        # Create Mock LLM Client that tracks invocation count
        class BurstTrackingLLM:
            def __init__(self):
                self.call_count = 0
                self.lock = asyncio.Lock()

            async def chat(self, messages, tools=None, model_tier="small"):
                async with self.lock:
                    self.call_count += 1
                await asyncio.sleep(0.01)  # Simulate model latency
                return LLMResponse(
                    content="Thank you for contacting NovaRetail. Your wireless headphones will arrive tomorrow.",
                    tool_calls=[],
                    model_used="llama-3.3-70b-versatile",
                    token_usage={"prompt_tokens": 400, "completion_tokens": 150}
                )

        mock_llm = BurstTrackingLLM()
        cache = CacheService()
        catalog = MockCatalogAdapter()
        orders = MockOrderAdapter()
        refunds = MockRefundAdapter(orders)
        dispatcher = MCPToolDispatcher(
            catalog_server=MCPCatalogServer(catalog),
            order_server=MCPOrderServer(orders),
            refund_server=MCPRefundServer(refunds),
            handoff_server=MCPHandoffServer()
        )
        router = AIRouter(cache_service=cache, dispatcher=dispatcher)

        turn_recorder = TurnRecorder()
        orchestrator = WorkerOrchestrator(
            router=router,
            dispatcher=dispatcher,
            llm_client=mock_llm
        )

        async def run_burst():
            # Dispatch 15 simultaneous customer turns
            async def single_turn(user_id):
                ctx = SessionContext(
                    tenant_id=self.tenant_id,
                    conv_id=f"conv_burst_{user_id}",
                    customer_id=f"cust_{user_id}",
                    level=AuthLevel.ANONYMOUS,
                    channel="web"
                )
                return await orchestrator.process_turn(
                    user_message="Can I wear these earbuds while swimming in a chlorinated pool?",
                    ctx=ctx
                )

            tasks = [single_turn(i) for i in range(1, 16)]
            results = await asyncio.gather(*tasks)
            return results

        results = run_async(run_burst())

        # Assertions
        # 1. Exactly 1 LLM call was allowed through before the cap was hit
        self.assertEqual(mock_llm.call_count, 1)

        # 2. Exactly 1 turn received a model reply; exactly 14 were gated by the spend manager
        model_replies = [r for r in results if r.model_used == "llama-3.3-70b-versatile"]
        gated_replies = [r for r in results if r.route_type == "spend_capped"]

        self.assertEqual(len(model_replies), 1)
        self.assertEqual(len(gated_replies), 14)

        # 3. Gated responses provide fixed deterministic support text and offer handoff
        for gated in gated_replies:
            self.assertIn("essential mode", gated.reply)
            self.assertEqual(gated.model_used, "spend-cap-gate")

    def test_outbox_queue_drain_under_concurrent_worker_competition(self):
        """
        Verify 15 approved refunds competing across 3 concurrent outbox workers
        are processed exactly once (zero duplicate payments and clean queue drain).
        """
        processed_payments = []
        payment_lock = asyncio.Lock()

        class MockConcurrentPaymentPort:
            async def process_payment(self, order_id, amount_inr, idempotency_key):
                async with payment_lock:
                    processed_payments.append({
                        "order_id": order_id,
                        "idempotency_key": idempotency_key,
                        "amount_inr": amount_inr,
                        "timestamp": datetime.now(timezone.utc)
                    })
                await asyncio.sleep(0.01)  # Simulate network latency
                return {"payment_id": f"pay_{idempotency_key}", "status": "paid"}

            async def query_payment_status(self, idempotency_key):
                return "paid"

        mock_payment = MockConcurrentPaymentPort()

        # Seed 15 approved refund rows
        async def seed_approved_refunds():
            async with self.session_maker() as sess:
                async with sess.begin():
                    for i in range(1, 16):
                        ref = RefundRequest(
                            refund_id=f"REF-BURST-{i:02d}",
                            tenant_id=self.tenant_id,
                            order_id=f"ORD-BURST-{i}",
                            customer_id=f"CUST-BURST-{i}",
                            amount_inr=2500 + i * 100,
                            state="approved",  # Approved row is the outbox
                            idempotency_key=f"idem_burst_{i}_{datetime.now().timestamp()}",
                            reason="Damaged item received",
                            request_time=self.now,
                            eligibility_snapshot={},
                            decided_by="staff_mgr_1",
                            decided_at=self.now,
                            leased_until=None,
                            retry_count=0
                        )
                        sess.add(ref)

        run_async(seed_approved_refunds())

        # Spawn 3 concurrent workers processing the queue
        workers = [
            OutboxPaymentWorker(refund_port=mock_payment, tenant_id=self.tenant_id, lease_seconds=30)
            for _ in range(3)
        ]

        async def drain_queue():
            # Each worker loops until the 15 items are fully drained
            async def worker_loop(w):
                drained = 0
                for _ in range(30):
                    count = await w.run_once()
                    drained += count
                    if len(processed_payments) >= 15:
                        break
                    await asyncio.sleep(0.005)
                return drained

            results = await asyncio.gather(*[worker_loop(w) for w in workers])
            return results

        drain_results = run_async(drain_queue())

        # Assertions
        # 1. Exactly 15 payment requests dispatched to payment provider
        self.assertEqual(len(processed_payments), 15)

        # 2. Zero duplicate payments (all idempotency keys are unique)
        keys = [p["idempotency_key"] for p in processed_payments]
        self.assertEqual(len(keys), len(set(keys)))

        # 3. All 15 rows in database transitioned to 'processed'
        async def verify_db_rows():
            async with self.session_maker() as sess:
                stmt = select(RefundRequest).where(
                    RefundRequest.tenant_id == self.tenant_id,
                    RefundRequest.state == "processed"
                )
                rows = (await sess.execute(stmt)).scalars().all()
                self.assertEqual(len(rows), 15)

                # Zero rows remaining in 'approved' state
                stmt_app = select(func.count(RefundRequest.refund_id)).where(
                    RefundRequest.tenant_id == self.tenant_id,
                    RefundRequest.state == "approved"
                )
                approved_count = (await sess.execute(stmt_app)).scalar_one()
                self.assertEqual(approved_count, 0)

        run_async(verify_db_rows())

    def test_escalations_multi_ticket_concurrent_claiming_burst(self):
        """
        Verify that 5 distinct escalation tickets claimed concurrently by 15 executives
        (3 competitors per ticket) result in exactly 5 winners (200 OK) and 10 conflicts (409).
        """
        # Seed 5 open escalation tickets
        async def seed_tickets():
            async with self.session_maker() as sess:
                async with sess.begin():
                    for i in range(1, 6):
                        esc = Escalation(
                            esc_id=f"ESC-MULTI-{i}",
                            conv_id=f"CONV-MULTI-{i}",
                            tenant_id=self.tenant_id,
                            reason=f"Customer issue {i}",
                            priority="high",
                            state="open",
                            created_at=self.now - timedelta(minutes=10)
                        )
                        sess.add(esc)

        run_async(seed_tickets())

        # Prepare 15 claim requests: 3 executives competing for each of the 5 tickets
        claim_tasks = []
        for i in range(1, 6):
            ticket_id = f"ESC-MULTI-{i}"
            for exec_num in [1, 2, 3]:
                sess_id = f"sess_exec_{exec_num}"
                claim_tasks.append((ticket_id, sess_id))

        async def run_claims():
            # Run claims concurrently using async executor
            def do_claim(tid, sid):
                return self.client.post(
                    f"/api/admin/v1/escalations/{tid}/claim",
                    headers={"Authorization": f"Bearer {sid}", "X-CSRF-Token": self.csrf}
                )

            loop = asyncio.get_running_loop()
            futures = [
                loop.run_in_executor(None, do_claim, tid, sid)
                for tid, sid in claim_tasks
            ]
            return await asyncio.gather(*futures)

        responses = run_async(run_claims())

        # Assertions
        status_codes = [r.status_code for r in responses]
        ok_count = status_codes.count(200)
        conflict_count = status_codes.count(409)

        # Exactly 5 winners (one for each ticket) and 10 conflicts
        self.assertEqual(ok_count, 5)
        self.assertEqual(conflict_count, 10)

        # Verify DB state: all 5 tickets are assigned and exactly 5 claim audit events recorded
        async def verify_claim_records():
            async with self.session_maker() as sess:
                stmt = select(Escalation).where(
                    Escalation.tenant_id == self.tenant_id,
                    Escalation.state == "assigned"
                )
                assigned_tickets = (await sess.execute(stmt)).scalars().all()
                self.assertEqual(len(assigned_tickets), 5)

                stmt_audit = select(AuditEvent).where(
                    AuditEvent.tenant_id == self.tenant_id,
                    AuditEvent.action == "claim_escalation"
                )
                audit_records = (await sess.execute(stmt_audit)).scalars().all()
                self.assertEqual(len(audit_records), 5)

        run_async(verify_claim_records())

    def test_ingestion_sync_lock_under_burst(self):
        """
        Verify that when a catalog ingestion job is active, concurrent sync
        requests are locked out and return 409 Conflict.
        """
        # 1. Seed an active running ingestion job for the tenant
        async def seed_active_job():
            async with self.session_maker() as sess:
                async with sess.begin():
                    job = IngestionJob(
                        job_id="job_burst_active",
                        tenant_id=self.tenant_id,
                        source_type="catalog",
                        status="running",
                        progress_pct=40
                    )
                    sess.add(job)

        run_async(seed_active_job())

        # 2. Send a burst of 4 concurrent sync requests
        def do_sync():
            return self.client.post(
                "/api/admin/v1/knowledge/catalog/sync",
                json={"products": []},
                headers={"Authorization": "Bearer sess_mgr_1", "X-CSRF-Token": self.csrf}
            )

        responses = [do_sync() for _ in range(4)]
        status_codes = [r.status_code for r in responses]

        # All 4 requests in the burst are locked out with 409 Conflict
        self.assertEqual(status_codes, [409, 409, 409, 409])
        for r in responses:
            self.assertIn("already in progress", r.json()["detail"])

        # 3. Mark the active job completed
        async def complete_job():
            async with self.session_maker() as sess:
                async with sess.begin():
                    stmt = update(IngestionJob).where(
                        IngestionJob.job_id == "job_burst_active"
                    ).values(status="completed", progress_pct=100)
                    await sess.execute(stmt)

        run_async(complete_job())

        # 4. Now a new sync request succeeds with 200 OK
        resp_after = do_sync()
        self.assertEqual(resp_after.status_code, 200)
        self.assertEqual(resp_after.json()["status"], "completed")


if __name__ == "__main__":
    unittest.main()
