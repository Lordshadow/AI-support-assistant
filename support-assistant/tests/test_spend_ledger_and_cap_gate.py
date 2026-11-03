"""
Test Suite: R4 Spend Ledger, Hot-Path Budget Gate & Reports API.
Validates Requirement R4, Spec 6.2, 11.1, and Phase 3 Gate:
"All 14.1 columns populated; spend cap hot-path blocks model calls."
"""

import unittest
import asyncio
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sys

# Ensure support-assistant is in sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import select
from fastapi import FastAPI
from fastapi.testclient import TestClient

from db.models import (
    Base, Tenant, StaffUser, StaffTenantMembership, StaffSession,
    SpendLedger, ConversationSession, ConversationTurn
)
from services.dashboard_api.reports import router as reports_router
from services.dashboard_api.auth import hash_password
from services.worker.spend_manager import (
    SpendManager, compute_cost_inr, PRICING_TABLE_INR
)
from services.worker.orchestrator import WorkerOrchestrator
from services.worker.llm_client import MockLLMClient
from core.models import SessionContext
from core.router import AIRouter, CacheService
from services.mcp_servers import (
    MCPCatalogServer, MCPOrderServer, MCPRefundServer,
    MCPHandoffServer, MCPToolDispatcher
)
from adapters.mockshop import MockCatalogAdapter, MockOrderAdapter, MockRefundAdapter


def run_async(coro):
    return asyncio.run(coro)


class TestSpendLedgerAndCapGate(unittest.TestCase):

    def setUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
        self.session_maker = async_sessionmaker(self.engine, expire_on_commit=False)

        async def init_schema():
            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

        run_async(init_schema())

        self.app = FastAPI()
        self.app.include_router(reports_router)
        self.client = TestClient(self.app)

        from unittest.mock import patch
        from db import session as db_session

        @db_session.asynccontextmanager
        async def mock_get_session(tenant_id=None):
            async with self.session_maker() as sess:
                async with sess.begin():
                    yield sess

        self.patcher1 = patch("services.dashboard_api.reports.get_async_session", side_effect=mock_get_session)
        self.patcher2 = patch("services.dashboard_api.dependencies.get_async_session", side_effect=mock_get_session)
        self.patcher3 = patch("services.worker.spend_manager.get_async_session", side_effect=mock_get_session)
        self.patcher4 = patch("services.worker.turn_recorder.get_async_session", side_effect=mock_get_session)
        self.patcher1.start()
        self.patcher2.start()
        self.patcher3.start()
        self.patcher4.start()

        # Build Orchestrator components
        self.cache = CacheService()
        self.catalog = MockCatalogAdapter()
        self.orders = MockOrderAdapter()
        self.refunds = MockRefundAdapter(self.orders, auto_limit_inr=2000)

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

    def test_compute_cost_inr_formula(self):
        """Verify model pricing matches specification formula."""
        # Llama 3.3 70B: 1000 prompt tokens = ₹0.05, 1000 completion tokens = ₹0.065
        cost_70b = compute_cost_inr("llama-3.3-70b-versatile", prompt_tokens=1000, completion_tokens=1000)
        self.assertAlmostEqual(cost_70b, 0.115, places=3)

        # Llama 3.1 8B: 1000 prompt = ₹0.005, 1000 completion = ₹0.008
        cost_8b = compute_cost_inr("llama-3.1-8b-instant", prompt_tokens=1000, completion_tokens=1000)
        self.assertAlmostEqual(cost_8b, 0.013, places=3)

    def test_hot_path_spend_cap_enforcement_blocks_model_calls(self):
        """
        Verify chat worker hot-path budget gate:
        - When under daily cap: invokes LLM normally.
        - When daily spend >= ₹2,500: skips LLM entirely and transitions to essential menu with human handoff.
        """
        from services.worker.spend_manager import spend_manager

        ctx = SessionContext(
            tenant_id="tenant_budget_test",
            conv_id="CONV-BUDGET-1",
            customer_id="CUST-42",
            channel="web"
        )

        async def run_test():
            # 1. Normal state: spend is 0, model call proceeds
            spend_manager.set_mock_spend("tenant_budget_test", daily=100.0, monthly=1000.0)
            res1 = await self.orchestrator.process_turn(
                user_message="Tell me about Pulse Buds 141 battery life",
                ctx=ctx
            )
            self.assertNotEqual(res1.route_type, "spend_capped")
            self.assertNotEqual(res1.model_used, "spend-cap-gate")

            # 2. Daily cap reached (₹2,500)
            spend_manager.set_mock_spend("tenant_budget_test", daily=2500.0, monthly=10000.0)
            res2 = await self.orchestrator.process_turn(
                user_message="Tell me about Pulse Buds 141 battery life",
                ctx=ctx
            )
            # Must be intercepted by spend cap gate
            self.assertEqual(res2.route_type, "spend_capped")
            self.assertEqual(res2.model_used, "spend-cap-gate")
            self.assertEqual(res2.requires_action, "handoff")
            self.assertIn("essential mode due to daily high traffic", res2.reply)

            # 3. Monthly cap 95% threshold reached (₹47,500 of ₹50,000)
            spend_manager.set_mock_spend("tenant_budget_test", daily=50.0, monthly=47500.0)
            res3 = await self.orchestrator.process_turn(
                user_message="Tell me about Pulse Buds 141 battery life",
                ctx=ctx
            )
            self.assertEqual(res3.route_type, "spend_capped")
            self.assertEqual(res3.model_used, "spend-cap-gate")

        run_async(run_test())

    def test_reports_api_spend_meters_and_metrics(self):
        """Test /api/admin/v1/reports/spend and /reports/metrics aggregations."""
        now = datetime.now(timezone.utc)
        import hashlib
        csrf = "csrf_report_test"
        csrf_hash = hashlib.sha256(csrf.encode()).hexdigest()

        async def seed():
            async with self.session_maker() as sess:
                async with sess.begin():
                    sess.add(Tenant(
                        tenant_id="tenant_novaretail",
                        name="NovaRetail",
                        daily_spend_cap_inr=2500,
                        monthly_spend_cap_inr=50000
                    ))
                    # Staff user: Manager
                    sess.add(StaffUser(
                        staff_id="staff_mgr_rep",
                        email="mgr_rep@novaretail.com",
                        full_name="Report Manager",
                        password_hash=hash_password("Pass1!"),
                    ))
                    sess.add(StaffTenantMembership(
                        staff_id="staff_mgr_rep",
                        tenant_id="tenant_novaretail",
                        role="manager"
                    ))
                    sess.add(StaffSession(
                        session_id="sess_mgr_rep",
                        staff_id="staff_mgr_rep",
                        active_tenant_id="tenant_novaretail",
                        created_at=now,
                        expires_at=now + timedelta(hours=1),
                        csrf_hash=csrf_hash
                    ))

                    # Seed spend entries
                    sess.add(SpendLedger(
                        id="SP-1",
                        tenant_id="tenant_novaretail",
                        purpose="chat",
                        model="llama-3.1-8b-instant",
                        prompt_tokens=1000,
                        completion_tokens=500,
                        cost_inr=0.009,
                        created_at=now - timedelta(hours=2)
                    ))
                    sess.add(SpendLedger(
                        id="SP-2",
                        tenant_id="tenant_novaretail",
                        purpose="chat",
                        model="llama-3.3-70b-versatile",
                        prompt_tokens=2000,
                        completion_tokens=800,
                        cost_inr=0.152,
                        created_at=now - timedelta(hours=1)
                    ))

                    # Seed conversations and turns
                    sess.add(ConversationSession(
                        conv_id="CONV-M-1",
                        tenant_id="tenant_novaretail",
                        channel="web",
                        customer_id="CUST-1",
                        handoff_state="none"  # Deflected
                    ))
                    sess.add(ConversationTurn(
                        turn_id="T-M-1",
                        conv_id="CONV-M-1",
                        tenant_id="tenant_novaretail",
                        step_index=0,
                        user_input_masked="Where is my order?",
                        assistant_response_masked="Your order is in transit.",
                        latency_ms=150,
                    ))

                    sess.add(ConversationSession(
                        conv_id="CONV-M-2",
                        tenant_id="tenant_novaretail",
                        channel="web",
                        customer_id="CUST-2",
                        handoff_state="open"  # Escalated
                    ))
                    sess.add(ConversationTurn(
                        turn_id="T-M-2",
                        conv_id="CONV-M-2",
                        tenant_id="tenant_novaretail",
                        step_index=0,
                        user_input_masked="Talk to manager",
                        assistant_response_masked="Routing to human.",
                        latency_ms=250,
                    ))

        run_async(seed())

        # 1. Test /reports/spend
        res_spend = self.client.get(
            "/api/admin/v1/reports/spend",
            cookies={"session_id": "sess_mgr_rep"}
        )
        self.assertEqual(res_spend.status_code, 200)
        data_spend = res_spend.json()
        self.assertEqual(data_spend["daily"]["cap_inr"], 2500)
        self.assertEqual(data_spend["monthly"]["cap_inr"], 50000)
        self.assertTrue(len(data_spend["models"]) >= 2)

        # 2. Test /reports/metrics
        res_metrics = self.client.get(
            "/api/admin/v1/reports/metrics?days=7",
            cookies={"session_id": "sess_mgr_rep"}
        )
        self.assertEqual(res_metrics.status_code, 200)
        data_metrics = res_metrics.json()
        self.assertEqual(data_metrics["conversations"]["total"], 2)
        self.assertEqual(data_metrics["conversations"]["deflected"], 1)
        self.assertEqual(data_metrics["conversations"]["deflection_rate_pct"], 50.0)
        self.assertTrue(data_metrics["latency_ms"]["average"] > 0)


if __name__ == "__main__":
    unittest.main()
