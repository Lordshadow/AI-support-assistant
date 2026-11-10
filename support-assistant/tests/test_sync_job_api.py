import asyncio
from datetime import datetime, timezone, timedelta
import hashlib
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from db.models import (
    Base, Tenant, StaffUser, StaffTenantMembership, StaffSession,
    IngestionJob, IngestionRun, IngestionItem, AuditEvent,
)
from services.dashboard_api.auth import hash_password
from services.dashboard_api.knowledge import router as knowledge_router


class TestSyncJobAPI(unittest.TestCase):
    """Unit and API integration tests for Task 5: Sync Job, Lock & Dashboard API."""

    def setUp(self):
        self.db_file = f"test_api_job_{datetime.now().timestamp()}.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.db_file}", echo=False)
        self.session_maker = async_sessionmaker(self.engine, expire_on_commit=False)

        async def init_schema():
            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

        asyncio.run(init_schema())

        # Seed tenant and staff accounts
        async def seed_data():
            async with self.session_maker() as session:
                async with session.begin():
                    t = Tenant(tenant_id="tenant_novaretail", name="NovaRetail")
                    session.add(t)

                    # Admin
                    u_adm = StaffUser(
                        staff_id="staff_adm", email="admin@novaretail.com",
                        full_name="Admin", password_hash=hash_password("admin_pass"),
                    )
                    # Manager
                    u_mgr = StaffUser(
                        staff_id="staff_mgr", email="mgr@novaretail.com",
                        full_name="Manager", password_hash=hash_password("mgr_pass"),
                    )
                    # Executive
                    u_exec = StaffUser(
                        staff_id="staff_exec", email="exec@novaretail.com",
                        full_name="Executive", password_hash=hash_password("exec_pass"),
                    )
                    session.add_all([u_adm, u_mgr, u_exec])

                    m_adm = StaffTenantMembership(staff_id="staff_adm", tenant_id="tenant_novaretail", role="admin")
                    m_mgr = StaffTenantMembership(staff_id="staff_mgr", tenant_id="tenant_novaretail", role="manager")
                    m_exec = StaffTenantMembership(staff_id="staff_exec", tenant_id="tenant_novaretail", role="executive")
                    session.add_all([m_adm, m_mgr, m_exec])

                    now = datetime.now(timezone.utc)
                    future = now + timedelta(hours=8)
                    csrf_hash = hashlib.sha256("csrf".encode()).hexdigest()
                    s_adm = StaffSession(session_id="sess_adm", staff_id="staff_adm", tenant_id="tenant_novaretail", active_tenant_id="tenant_novaretail", expires_at=future, csrf_hash=csrf_hash)
                    s_mgr = StaffSession(session_id="sess_mgr", staff_id="staff_mgr", tenant_id="tenant_novaretail", active_tenant_id="tenant_novaretail", expires_at=future, csrf_hash=csrf_hash)
                    s_exec = StaffSession(session_id="sess_exec", staff_id="staff_exec", tenant_id="tenant_novaretail", active_tenant_id="tenant_novaretail", expires_at=future, csrf_hash=csrf_hash)
                    session.add_all([s_adm, s_mgr, s_exec])

        asyncio.run(seed_data())

        app = FastAPI()
        app.include_router(knowledge_router)
        self.app = app
        self.client = TestClient(app)

        from db import session as db_session
        @db_session.asynccontextmanager
        async def mock_get_session(tenant_id=None):
            async with self.session_maker() as sess:
                async with sess.begin():
                    yield sess

        self.patcher1 = patch("services.dashboard_api.knowledge.get_async_session", side_effect=mock_get_session)
        self.patcher2 = patch("services.dashboard_api.dependencies.get_async_session", side_effect=mock_get_session)
        self.patcher1.start()
        self.patcher2.start()

    def tearDown(self):
        self.patcher1.stop()
        self.patcher2.stop()
        import os
        try:
            if os.path.exists(self.db_file):
                os.remove(self.db_file)
        except OSError:
            pass

    def test_sync_requires_manager_or_admin_role(self):
        # Executive is forbidden (403)
        res_exec = self.client.post("/api/admin/v1/knowledge/catalog/sync", headers={"Authorization": "Bearer sess_exec", "X-CSRF-Token": "csrf"})
        self.assertEqual(res_exec.status_code, 403)

        # Manager is allowed
        with patch("services.dashboard_api.knowledge._run_catalog_ingestion"):
            res_mgr = self.client.post("/api/admin/v1/knowledge/catalog/sync", headers={"Authorization": "Bearer sess_mgr", "X-CSRF-Token": "csrf"})
            self.assertEqual(res_mgr.status_code, 200)
            self.assertEqual(res_mgr.json()["status"], "queued")
            self.assertIn("job_id", res_mgr.json())

    def test_concurrency_lock_blocks_simultaneous_sync(self):
        # 1. Trigger first job
        with patch("services.dashboard_api.knowledge._run_catalog_ingestion"):
            res1 = self.client.post("/api/admin/v1/knowledge/catalog/sync", headers={"Authorization": "Bearer sess_adm", "X-CSRF-Token": "csrf"})
            self.assertEqual(res1.status_code, 200)

            # 2. Trigger second job while first is still queued/running -> expect 409 Conflict
            res2 = self.client.post("/api/admin/v1/knowledge/catalog/sync", headers={"Authorization": "Bearer sess_adm", "X-CSRF-Token": "csrf"})
            self.assertEqual(res2.status_code, 409)
            self.assertIn("already running", res2.json()["detail"])

    def test_health_check_endpoint(self):
        with patch("ingestion.shop_catalog.ShopCatalogConnector.fetch_page", new=AsyncMock(return_value={"products": []})):
            res = self.client.get("/api/admin/v1/knowledge/catalog/health", headers={"Authorization": "Bearer sess_adm"})
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertIn("checks", data)
            self.assertIn("vector_db", data["checks"])
            self.assertIn("embedding", data["checks"])
            self.assertIn("stores_api", data["checks"])

    def test_list_and_get_catalog_runs(self):
        async def seed_run():
            async with self.session_maker() as session:
                async with session.begin():
                    run = IngestionRun(
                        run_id="run_test_123",
                        job_id="job_test_123",
                        tenant_id="tenant_novaretail",
                        status="succeeded",
                        stats={"total_items": 4, "chunks_indexed": 32},
                        logs=[{"event": "run_started"}, {"event": "run_finished"}],
                        errors=[],
                    )
                    session.add(run)

        asyncio.run(seed_run())

        # List runs
        res_list = self.client.get("/api/admin/v1/knowledge/catalog/runs", headers={"Authorization": "Bearer sess_mgr"})
        self.assertEqual(res_list.status_code, 200)
        runs = res_list.json()
        self.assertTrue(len(runs) >= 1)
        self.assertEqual(runs[0]["run_id"], "run_test_123")

        # Drill down into one run
        res_one = self.client.get("/api/admin/v1/knowledge/catalog/runs/run_test_123", headers={"Authorization": "Bearer sess_mgr"})
        self.assertEqual(res_one.status_code, 200)
        data = res_one.json()
        self.assertEqual(data["run_id"], "run_test_123")
        self.assertEqual(data["stats"]["chunks_indexed"], 32)
        self.assertEqual(len(data["logs"]), 2)

    def test_cancel_catalog_job_role_and_lifecycle(self):
        # 1. Trigger sync job
        with patch("services.dashboard_api.knowledge._run_catalog_ingestion"):
            res_sync = self.client.post("/api/admin/v1/knowledge/catalog/sync", headers={"Authorization": "Bearer sess_adm", "X-CSRF-Token": "csrf"})
            self.assertEqual(res_sync.status_code, 200)
            job_id = res_sync.json()["job_id"]

        # 2. Executive is forbidden to cancel
        res_exec = self.client.post(f"/api/admin/v1/knowledge/catalog/jobs/{job_id}/cancel", headers={"Authorization": "Bearer sess_exec", "X-CSRF-Token": "csrf"})
        self.assertEqual(res_exec.status_code, 403)

        # 3. Manager cancels job
        res_cancel = self.client.post(f"/api/admin/v1/knowledge/catalog/jobs/{job_id}/cancel", headers={"Authorization": "Bearer sess_mgr", "X-CSRF-Token": "csrf"})
        self.assertEqual(res_cancel.status_code, 200)
        self.assertEqual(res_cancel.json()["status"], "cancelled")

        # 4. Attempting to cancel already cancelled job is idempotent (returns 200)
        res_repeat = self.client.post(f"/api/admin/v1/knowledge/catalog/jobs/{job_id}/cancel", headers={"Authorization": "Bearer sess_mgr", "X-CSRF-Token": "csrf"})
        self.assertEqual(res_repeat.status_code, 200)
        self.assertEqual(res_repeat.json()["status"], "cancelled")

        # 5. Lock is released: new sync succeeds immediately without 409
        with patch("services.dashboard_api.knowledge._run_catalog_ingestion"):
            res_new_sync = self.client.post("/api/admin/v1/knowledge/catalog/sync", headers={"Authorization": "Bearer sess_adm", "X-CSRF-Token": "csrf"})
            self.assertEqual(res_new_sync.status_code, 200)

    def test_cancel_active_catalog_job_endpoint(self):
        # 1. Cancel with no active job returns 404
        res_none = self.client.post("/api/admin/v1/knowledge/catalog/cancel", headers={"Authorization": "Bearer sess_adm", "X-CSRF-Token": "csrf"})
        self.assertEqual(res_none.status_code, 404)

        # 2. Trigger sync job
        with patch("services.dashboard_api.knowledge._run_catalog_ingestion"):
            res_sync = self.client.post("/api/admin/v1/knowledge/catalog/sync", headers={"Authorization": "Bearer sess_adm", "X-CSRF-Token": "csrf"})
            self.assertEqual(res_sync.status_code, 200)

        # 3. Cancel active job without specifying job_id
        res_cancel = self.client.post("/api/admin/v1/knowledge/catalog/cancel", headers={"Authorization": "Bearer sess_adm", "X-CSRF-Token": "csrf"})
        self.assertEqual(res_cancel.status_code, 200)
        self.assertEqual(res_cancel.json()["status"], "cancelled")


if __name__ == "__main__":
    unittest.main()
