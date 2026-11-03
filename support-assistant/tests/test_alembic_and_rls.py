"""
Phase 1 Test Suite: Alembic Migrations, PostgreSQL Row-Level Security (RLS), and Repositories.
Complies with Specification Section 6, 10, 15.1.8, and Implementation Plan v4 (Phase 1 Gate).
"""

import unittest
import asyncio
from pathlib import Path
import os
import sys

# Ensure support-assistant is in sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic import command
import io

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import text, select

from db.models import (
    Base, Tenant, StaffUser, StaffTenantMembership, StaffSession,
    TenantPolicyConfig, RefundRequest, AuditEvent, ConversationSession,
    ConversationTurn, TurnRaw, SpendLedger, Escalation,
    KnowledgeVersion, KnowledgeChunk, IngestionJob,
    OrderModel, OrderItemModel, ProductModel, ProductSpecModel, ProductPriceModel
)
from db.session import get_async_session
from adapters.postgres import PostgresOrderRepository, PostgresCatalogRepository, PostgresRefundRepository
from core.models import RefundState, OrderStatus


def run_async(coro):
    return asyncio.run(coro)


class TestAlembicAndRLS(unittest.TestCase):

    def setUp(self):
        self.base_dir = Path(__file__).parent.parent
        self.ini_path = str(self.base_dir / "alembic.ini")
        self.cfg = Config(self.ini_path)

    def test_alembic_revisions_and_heads(self):
        """Verify Alembic script directory recognizes 001_core_and_rls as current head."""
        script = ScriptDirectory.from_config(self.cfg)
        heads = script.get_heads()
        self.assertEqual(heads, ["001_core_and_rls"])
        rev = script.get_revision("001_core_and_rls")
        self.assertIsNotNone(rev)
        self.assertIsNone(rev.down_revision)

    def test_offline_sql_generation_contains_all_rls_and_security_controls(self):
        """Generate static SQL from Alembic and verify all RLS and security DDL constraints."""
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            command.upgrade(self.cfg, "base:head", sql=True)
        sql = buf.getvalue()

        # 1. Extensions
        self.assertIn('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"', sql)
        self.assertIn("CREATE EXTENSION IF NOT EXISTS vector", sql)
        self.assertIn("CREATE EXTENSION IF NOT EXISTS pg_trgm", sql)

        # 2. Key Tables
        expected_tables = [
            "tenants", "staff_users", "staff_tenant_memberships", "staff_sessions",
            "tenant_policy_configs", "refund_requests", "audit_events",
            "conversation_sessions", "conversation_turns", "turn_raw",
            "spend_ledger", "escalations", "knowledge_versions",
            "knowledge_chunks", "knowledge_version_chunks", "ingestion_jobs"
        ]
        for tbl in expected_tables:
            self.assertIn(f"CREATE TABLE {tbl}", sql)

        # 3. Partial Unique Indexes
        self.assertIn("CREATE UNIQUE INDEX idx_refund_active_unique", sql)
        self.assertIn("WHERE state IN ('pending_approval', 'approved', 'processed')", sql)
        self.assertIn("CREATE UNIQUE INDEX idx_ingestion_single_active", sql)
        self.assertIn("WHERE status IN ('queued', 'running')", sql)

        # 4. Row Level Security on all tenant tables
        tenant_tables = [
            "staff_tenant_memberships", "staff_sessions", "tenant_policy_configs",
            "refund_requests", "audit_events", "conversation_sessions",
            "conversation_turns", "turn_raw", "spend_ledger", "escalations",
            "knowledge_versions", "knowledge_chunks", "ingestion_jobs"
        ]
        for tbl in tenant_tables:
            self.assertIn(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY;", sql)
            self.assertIn(f"ALTER TABLE {tbl} FORCE ROW LEVEL SECURITY;", sql)
            self.assertIn(f"CREATE POLICY tenant_isolation_policy ON {tbl}", sql)
            self.assertIn("USING (tenant_id = current_setting('app.tenant_id', true));", sql)

        # 5. Role Security & Immutability of audit_events
        self.assertIn("CREATE ROLE novaretail_app", sql)
        self.assertIn("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO novaretail_app;", sql)
        self.assertIn("REVOKE UPDATE, DELETE, TRUNCATE ON audit_events FROM novaretail_app;", sql)

    def test_offline_downgrade_sql_generation(self):
        """Verify downgrade static SQL cleans up all RLS policies and drops tables safely."""
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            command.downgrade(self.cfg, "head:base", sql=True)
        sql = buf.getvalue()

        self.assertIn("DROP POLICY IF EXISTS tenant_isolation_policy ON refund_requests;", sql)
        self.assertIn("ALTER TABLE refund_requests DISABLE ROW LEVEL SECURITY;", sql)
        self.assertIn("DROP TABLE tenants;", sql)
        self.assertIn("DELETE FROM alembic_version", sql)


class TestPostgresRepositories(unittest.TestCase):
    """Verifies Postgres repository adapters under domain Port protocols."""

    def setUp(self):
        self.test_engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            echo=False
        )

        async def init_schema():
            async with self.test_engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

        run_async(init_schema())

    def tearDown(self):
        async def dispose_engine():
            await self.test_engine.dispose()
        run_async(dispose_engine())

    def test_order_repository_and_tracking(self):
        """Test PostgresOrderRepository storing and querying orders with ownership checks."""
        async def run_test():
            # Seed an order in test database
            session_maker = async_sessionmaker(self.test_engine, expire_on_commit=False)
            from datetime import datetime, timezone, timedelta
            now = datetime.now(timezone.utc)

            async with session_maker() as session:
                async with session.begin():
                    # Seed tenant
                    tenant = Tenant(tenant_id="tenant_novaretail", name="NovaRetail")
                    session.add(tenant)

                    order = OrderModel(
                        order_id="ORD-9001",
                        tenant_id="tenant_novaretail",
                        customer_id="CUST-10",
                        total_amount_inr=1499,
                        status="Delivered",
                        tracking_number="AWB-9988",
                        courier_name="BlueDart",
                        shipping_address="12 Park Street, Kolkata",
                        created_at=now - timedelta(days=3),
                        delivered_at=now - timedelta(days=1),
                    )
                    session.add(order)
                    item = OrderItemModel(
                        item_id="ITM-901",
                        order_id="ORD-9001",
                        product_id="P1041",
                        product_name="Pulse Buds 141",
                        category="electronics",
                        price=1499,
                        quantity=1,
                    )
                    session.add(item)

            repo = PostgresOrderRepository(tenant_id="tenant_novaretail")
            # Override get_async_session to bind to our in-memory engine for this test
            from unittest.mock import patch
            from db import session as db_session

            @db_session.asynccontextmanager
            async def mock_get_session(tenant_id=None):
                async with session_maker() as sess:
                    async with sess.begin():
                        yield sess

            with patch("adapters.postgres.order_repository.get_async_session", side_effect=mock_get_session):
                # 1. Ownership check: authorized customer
                order_res = await repo.get_order("CUST-10", "ORD-9001")
                self.assertIsNotNone(order_res)
                self.assertEqual(order_res.order_id, "ORD-9001")
                self.assertEqual(len(order_res.items), 1)
                self.assertEqual(order_res.items[0].product_name, "Pulse Buds 141")

                # 2. Ownership check: wrong customer returns None
                wrong_customer = await repo.get_order("CUST-WRONG", "ORD-9001")
                self.assertIsNone(wrong_customer)

                # 3. Tracking history
                tracking = await repo.get_tracking("CUST-10", "ORD-9001")
                self.assertTrue(len(tracking) >= 3)
                self.assertEqual(tracking[-1].status, "Delivered")

        run_async(run_test())

    def test_refund_repository_idempotency_and_routing(self):
        """Test PostgresRefundRepository auto-refund vs supervisor escalation routing."""
        async def run_test():
            session_maker = async_sessionmaker(self.test_engine, expire_on_commit=False)
            from datetime import datetime, timezone, timedelta
            from unittest.mock import patch
            from db import session as db_session

            now = datetime.now(timezone.utc)

            # Seed tenant and mock order
            async with session_maker() as session:
                async with session.begin():
                    tenant = Tenant(tenant_id="tenant_novaretail", name="NovaRetail")
                    session.add(tenant)
                    # Small order (under limit)
                    o1 = OrderModel(
                        order_id="ORD-SMALL",
                        tenant_id="tenant_novaretail",
                        customer_id="CUST-1",
                        total_amount_inr=1500,
                        status="Delivered",
                        created_at=now - timedelta(days=5),
                        delivered_at=now - timedelta(days=2),
                    )
                    session.add(o1)
                    session.add(OrderItemModel(
                        item_id="ITM-1",
                        order_id="ORD-SMALL",
                        product_id="P1",
                        product_name="Pulse Buds 141",
                        category="electronics",
                        price=1500,
                        quantity=1
                    ))

                    # High value order (over limit)
                    o2 = OrderModel(
                        order_id="ORD-LARGE",
                        tenant_id="tenant_novaretail",
                        customer_id="CUST-1",
                        total_amount_inr=4500,
                        status="Delivered",
                        created_at=now - timedelta(days=5),
                        delivered_at=now - timedelta(days=2),
                    )
                    session.add(o2)
                    session.add(OrderItemModel(
                        item_id="ITM-2",
                        order_id="ORD-LARGE",
                        product_id="P2",
                        product_name="Nova Watch Pro",
                        category="wearables",
                        price=4500,
                        quantity=1
                    ))

            @db_session.asynccontextmanager
            async def mock_get_session(tenant_id=None):
                async with session_maker() as sess:
                    async with sess.begin():
                        yield sess

            order_repo = PostgresOrderRepository(tenant_id="tenant_novaretail")
            refund_repo = PostgresRefundRepository(order_port=order_repo, tenant_id="tenant_novaretail", auto_limit_inr=2000)

            with patch("adapters.postgres.order_repository.get_async_session", side_effect=mock_get_session), \
                 patch("adapters.postgres.refund_repository.get_async_session", side_effect=mock_get_session):

                # 1. Under ₹2,000 should be auto-processed
                res1 = await refund_repo.request_refund(
                    customer_id="CUST-1",
                    order_id="ORD-SMALL",
                    amount_inr=1500,
                    reason="Defective microphone",
                    idempotency_key="IDEM-TEST-001"
                )
                self.assertEqual(res1.state, RefundState.PROCESSED)
                self.assertIn("automatically", res1.message)

                # 2. Idempotent retry: returns identical result without duplicate record
                res1_retry = await refund_repo.request_refund(
                    customer_id="CUST-1",
                    order_id="ORD-SMALL",
                    amount_inr=1500,
                    reason="Defective microphone",
                    idempotency_key="IDEM-TEST-001"
                )
                self.assertEqual(res1_retry.refund_id, res1.refund_id)

                # 3. Over ₹2,000 (₹4,500) routes to pending_approval for supervisor review
                res2 = await refund_repo.request_refund(
                    customer_id="CUST-1",
                    order_id="ORD-LARGE",
                    amount_inr=4500,
                    reason="Battery issue",
                    idempotency_key="IDEM-TEST-002"
                )
                self.assertEqual(res2.state, RefundState.PENDING_APPROVAL)
                self.assertIn("exceeds auto-approval threshold", res2.message)

                # 4. Staff decision recording
                res2_approved = await refund_repo.record_staff_decision(
                    refund_id=res2.refund_id,
                    state=RefundState.APPROVED,
                    decided_by="staff_mgr_01",
                    note="Verified customer logs, approved."
                )
                self.assertEqual(res2_approved.state, RefundState.APPROVED)
                self.assertEqual(res2_approved.decided_by, "staff_mgr_01")

        run_async(run_test())

    def test_catalog_repository_search_and_specs(self):
        """Test PostgresCatalogRepository product lookups, live pricing, and specs."""
        async def run_test():
            session_maker = async_sessionmaker(self.test_engine, expire_on_commit=False)
            from unittest.mock import patch
            from db import session as db_session

            async with session_maker() as session:
                async with session.begin():
                    # Seed tenant
                    tenant = Tenant(tenant_id="tenant_novaretail", name="NovaRetail")
                    session.add(tenant)

                    p = ProductModel(
                        product_id="P1041",
                        tenant_id="tenant_novaretail",
                        name="Pulse Buds 141",
                        brand="NovaAudio",
                        category="electronics",
                        aliases=["buds 141", "pb141"],
                        active=True,
                    )
                    session.add(p)
                    session.add(ProductSpecModel(
                        spec_id="SP-1",
                        product_id="P1041",
                        spec_key="battery_life",
                        spec_value="42 hours",
                        unit="hours"
                    ))
                    session.add(ProductPriceModel(
                        product_id="P1041",
                        price=1499,
                        discount_price=1299,
                        in_stock=True
                    ))

            @db_session.asynccontextmanager
            async def mock_get_session(tenant_id=None):
                async with session_maker() as sess:
                    async with sess.begin():
                        yield sess

            catalog_repo = PostgresCatalogRepository(tenant_id="tenant_novaretail")
            with patch("adapters.postgres.catalog_repository.get_async_session", side_effect=mock_get_session):
                # 1. find_product by alias
                matches = await catalog_repo.find_product("pb141")
                self.assertTrue(len(matches) > 0)
                self.assertEqual(matches[0].product_id, "P1041")

                # 2. get_details
                specs = await catalog_repo.get_details("P1041")
                self.assertIsNotNone(specs)
                self.assertEqual(specs.specs.get("battery_life"), "42 hours")

                # 3. get_price
                price = await catalog_repo.get_price("P1041")
                self.assertIsNotNone(price)
                self.assertEqual(price.price, 1499)
                self.assertEqual(price.discount_price, 1299)
                self.assertTrue(price.in_stock)

                # 4. search by category
                results = await catalog_repo.search(category="electronics", min_price=1000, max_price=2000)
                self.assertEqual(len(results), 1)
                self.assertEqual(results[0].product_id, "P1041")

        run_async(run_test())



if __name__ == "__main__":
    unittest.main()
