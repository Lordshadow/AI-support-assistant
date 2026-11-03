"""
Test Suite: Escalations Queue, Atomic Claim Race & Bot Silencing Gate.
Validates Spec 5.2, 16.4, and Phase 4 Gate:
"Claim race has 1 winner; bot sends fixed template on open ticket."
"""

import unittest
import asyncio
from datetime import datetime, timezone, timedelta
import secrets
from pathlib import Path
import os
import sys

# Ensure support-assistant is in sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import select, text
from fastapi import FastAPI
from fastapi.testclient import TestClient

from db.models import (
    Base, Tenant, StaffUser, StaffTenantMembership, StaffSession,
    Escalation, ConversationSession, AuditEvent
)
from services.dashboard_api.escalations import router as esc_router
from services.dashboard_api.auth import hash_password
from services.worker.orchestrator import WorkerOrchestrator
from services.worker.llm_client import MockLLMClient
from services.worker.escalation_guard import escalation_guard
from core.models import SessionContext
from core.router import AIRouter, CacheService
from services.mcp_servers import (
    MCPCatalogServer, MCPOrderServer, MCPRefundServer,
    MCPHandoffServer, MCPToolDispatcher
)
from adapters.mockshop import MockCatalogAdapter, MockOrderAdapter, MockRefundAdapter


def run_async(coro):
    return asyncio.run(coro)


class TestEscalationsAndBotSilencing(unittest.TestCase):

    def setUp(self):
        self.db_file = f"test_escalations_{datetime.now().timestamp()}.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.db_file}", echo=False)
        self.session_maker = async_sessionmaker(self.engine, expire_on_commit=False)

        async def init_schema():
            async with self.engine.begin() as conn:
                await conn.execute(text("PRAGMA journal_mode=WAL;"))
                await conn.run_sync(Base.metadata.create_all)

        run_async(init_schema())

        self.app = FastAPI()
        self.app.include_router(esc_router)
        self.client = TestClient(self.app)

        from unittest.mock import patch
        from db import session as db_session

        @db_session.asynccontextmanager
        async def mock_get_session(tenant_id=None):
            async with self.session_maker() as sess:
                async with sess.begin():
                    yield sess

        self.patcher1 = patch("services.dashboard_api.escalations.get_async_session", side_effect=mock_get_session)
        self.patcher2 = patch("services.dashboard_api.dependencies.get_async_session", side_effect=mock_get_session)
        self.patcher3 = patch("services.worker.escalation_guard.get_async_session", side_effect=mock_get_session)
        self.patcher4 = patch("services.worker.turn_recorder.get_async_session", side_effect=mock_get_session)
        self.patcher1.start()
        self.patcher2.start()
        self.patcher3.start()
        self.patcher4.start()

        # Build Orchestrator
        self.cache = CacheService()
        self.catalog = MockCatalogAdapter()
        self.orders = MockOrderAdapter()
        self.refunds = MockRefundAdapter(self.orders)
        self.dispatcher = MCPToolDispatcher(
            catalog_server=MCPCatalogServer(self.catalog),
            order_server=MCPOrderServer(self.orders),
            refund_server=MCPRefundServer(self.refunds),
            handoff_server=MCPHandoffServer()
        )
        self.router = AIRouter(cache_service=self.cache, dispatcher=self.dispatcher)
        self.orchestrator = WorkerOrchestrator(
            router=self.router,
            dispatcher=self.dispatcher,
            llm_client=MockLLMClient()
        )

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

    def test_escalations_listing_and_wait_time(self):
        """Verify listing open tickets with calculated wait times in minutes."""
        now = datetime.now(timezone.utc)
        import hashlib
        csrf = "csrf_esc_test"
        csrf_hash = hashlib.sha256(csrf.encode()).hexdigest()

        async def seed():
            async with self.session_maker() as sess:
                async with sess.begin():
                    sess.add(Tenant(tenant_id="tenant_novaretail", name="NovaRetail"))
                    sess.add(StaffUser(
                        staff_id="staff_exec_1",
                        email="exec1@novaretail.com",
                        full_name="Exec One",
                        password_hash=hash_password("Pass1!"),
                    ))
                    sess.add(StaffTenantMembership(
                        staff_id="staff_exec_1",
                        tenant_id="tenant_novaretail",
                        role="executive"
                    ))
                    sess.add(StaffSession(
                        session_id="sess_exec_1",
                        staff_id="staff_exec_1",
                        active_tenant_id="tenant_novaretail",
                        created_at=now,
                        expires_at=now + timedelta(hours=1),
                        csrf_hash=csrf_hash
                    ))
                    # Escalation created 25 minutes ago
                    sess.add(Escalation(
                        esc_id="ESC-T-1",
                        conv_id="CONV-10",
                        tenant_id="tenant_novaretail",
                        reason="Customer frustrated with delivery delay",
                        summary="Order ORD-1002 delayed by 3 days",
                        priority="high",
                        state="open",
                        created_at=now - timedelta(minutes=25)
                    ))

        run_async(seed())

        res = self.client.get(
            "/api/admin/v1/escalations?state=open",
            cookies={"session_id": "sess_exec_1"}
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(len(data["escalations"]), 1)
        ticket = data["escalations"][0]
        self.assertEqual(ticket["esc_id"], "ESC-T-1")
        self.assertEqual(ticket["priority"], "high")
        self.assertAlmostEqual(ticket["wait_minutes"], 25.0, delta=1.0)

    def test_atomic_claim_concurrency_race(self):
        """
        Gate Test: Simulate 5 concurrent staff claiming the same open ticket.
        Verifies:
        - Exactly 1 executive claims the ticket (status: 'assigned').
        - Exactly 4 executives receive 409 Conflict.
        - Exactly 1 claim audit event is inserted.
        """
        now = datetime.now(timezone.utc)
        import hashlib

        async def seed():
            async with self.session_maker() as sess:
                async with sess.begin():
                    sess.add(Tenant(tenant_id="tenant_novaretail", name="NovaRetail"))
                    # Create 5 staff sessions
                    for i in range(5):
                        staff_id = f"staff_claim_{i}"
                        sess.add(StaffUser(
                            staff_id=staff_id,
                            email=f"claim{i}@novaretail.com",
                            full_name=f"Staff Claim {i}",
                            password_hash=hash_password("Pass1!"),
                        ))
                        sess.add(StaffTenantMembership(
                            staff_id=staff_id,
                            tenant_id="tenant_novaretail",
                            role="executive"
                        ))
                        csrf = f"csrf_{i}"
                        sess.add(StaffSession(
                            session_id=f"sess_claim_{i}",
                            staff_id=staff_id,
                            active_tenant_id="tenant_novaretail",
                            created_at=now,
                            expires_at=now + timedelta(hours=1),
                            csrf_hash=hashlib.sha256(csrf.encode()).hexdigest()
                        ))

                    sess.add(ConversationSession(
                        conv_id="CONV-RACE-1",
                        tenant_id="tenant_novaretail",
                        channel="web",
                        customer_id="CUST-RACE",
                        handoff_state="open"
                    ))
                    sess.add(Escalation(
                        esc_id="ESC-RACE-1",
                        conv_id="CONV-RACE-1",
                        tenant_id="tenant_novaretail",
                        reason="Human takeover requested",
                        priority="urgent",
                        state="open",
                        created_at=now
                    ))

        run_async(seed())

        async def claim_task(i: int):
            # Run test client request in async executor
            def do_request():
                csrf = f"csrf_{i}"
                return self.client.post(
                    "/api/admin/v1/escalations/ESC-RACE-1/claim",
                    cookies={"session_id": f"sess_claim_{i}"},
                    headers={"X-CSRF-Token": csrf}
                )
            return await asyncio.to_thread(do_request)

        async def run_race():
            tasks = [claim_task(i) for i in range(5)]
            return await asyncio.gather(*tasks)

        responses = run_async(run_race())

        successes = [r for r in responses if r.status_code == 200]
        conflicts = [r for r in responses if r.status_code == 409]

        self.assertEqual(len(successes), 1, "Exactly one staff claim must succeed!")
        self.assertEqual(len(conflicts), 4, "All other concurrent claims must receive 409 Conflict!")

        # Verify DB ticket is assigned and exactly 1 audit event was written
        async def verify_db():
            async with self.session_maker() as sess:
                esc = await sess.get(Escalation, "ESC-RACE-1")
                self.assertEqual(esc.state, "assigned")

                audits = (await sess.execute(
                    select(AuditEvent).where(AuditEvent.resource_id == "ESC-RACE-1")
                )).scalars().all()
                self.assertEqual(len(audits), 1)
                self.assertEqual(audits[0].action, "claim_escalation")

        run_async(verify_db())

    def test_bot_silenced_during_open_or_assigned_escalation(self):
        """
        Gate Test: Verify that when an escalation ticket is active (open or assigned),
        the AI bot completely suppresses model calls and responds with a fixed support template.
        """
        now = datetime.now(timezone.utc)

        async def seed():
            async with self.session_maker() as sess:
                async with sess.begin():
                    sess.add(Tenant(tenant_id="tenant_silence_test", name="NovaRetail"))
                    sess.add(ConversationSession(
                        conv_id="CONV-SILENCE-1",
                        tenant_id="tenant_silence_test",
                        channel="web",
                        customer_id="CUST-SILENT",
                        handoff_state="open"
                    ))
                    sess.add(Escalation(
                        esc_id="ESC-SILENCE-1",
                        conv_id="CONV-SILENCE-1",
                        tenant_id="tenant_silence_test",
                        reason="Customer demanded supervisor",
                        priority="high",
                        state="open",
                        created_at=now
                    ))

        run_async(seed())

        ctx = SessionContext(
            tenant_id="tenant_silence_test",
            conv_id="CONV-SILENCE-1",
            customer_id="CUST-SILENT",
            channel="web"
        )

        async def check_bot():
            # Customer sends message while ticket is open
            res = await self.orchestrator.process_turn(
                user_message="Are you there? I am waiting for an answer!",
                ctx=ctx
            )
            # Verify bot was silenced
            self.assertEqual(res.route_type, "bot_silenced")
            self.assertEqual(res.model_used, "bot-silencer-gate")
            self.assertEqual(res.requires_action, "handoff")
            self.assertIn("A support executive is currently handling your request", res.reply)

        run_async(check_bot())

    def test_escalation_resolution_workflow(self):
        """Verify resolving an escalation clears handoff state and records resolution notes."""
        now = datetime.now(timezone.utc)
        import hashlib
        csrf = "csrf_resolve"
        csrf_hash = hashlib.sha256(csrf.encode()).hexdigest()

        async def seed():
            async with self.session_maker() as sess:
                async with sess.begin():
                    sess.add(Tenant(tenant_id="tenant_novaretail", name="NovaRetail"))
                    sess.add(StaffUser(
                        staff_id="staff_mgr_res",
                        email="mgr_res@novaretail.com",
                        full_name="Manager Res",
                        password_hash=hash_password("Pass1!"),
                    ))
                    sess.add(StaffTenantMembership(
                        staff_id="staff_mgr_res",
                        tenant_id="tenant_novaretail",
                        role="manager"
                    ))
                    sess.add(StaffSession(
                        session_id="sess_mgr_res",
                        staff_id="staff_mgr_res",
                        active_tenant_id="tenant_novaretail",
                        created_at=now,
                        expires_at=now + timedelta(hours=1),
                        csrf_hash=csrf_hash
                    ))
                    sess.add(ConversationSession(
                        conv_id="CONV-RES-1",
                        tenant_id="tenant_novaretail",
                        channel="web",
                        customer_id="CUST-RES",
                        handoff_state="assigned"
                    ))
                    sess.add(Escalation(
                        esc_id="ESC-RES-1",
                        conv_id="CONV-RES-1",
                        tenant_id="tenant_novaretail",
                        reason="Address change inquiry",
                        priority="medium",
                        state="assigned",
                        assigned_to="staff_mgr_res",
                        created_at=now - timedelta(minutes=10)
                    ))

        run_async(seed())

        # Resolve ticket with note
        res = self.client.post(
            "/api/admin/v1/escalations/ESC-RES-1/resolve",
            json={"resolution_note": "Called customer directly and updated shipping address in courier system."},
            cookies={"session_id": "sess_mgr_res"},
            headers={"X-CSRF-Token": csrf}
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "resolved")

        # Verify DB state
        async def verify_resolved():
            async with self.session_maker() as sess:
                esc = await sess.get(Escalation, "ESC-RES-1")
                self.assertEqual(esc.state, "resolved")
                self.assertIsNotNone(esc.resolved_at)
                self.assertIn("courier system", esc.resolution_note)

                conv = await sess.get(ConversationSession, "CONV-RES-1")
                self.assertEqual(conv.handoff_state, "resolved")

        run_async(verify_resolved())


if __name__ == "__main__":
    unittest.main()
