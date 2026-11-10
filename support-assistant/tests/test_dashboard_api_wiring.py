"""Regression checks for dashboard routing and authentication gates."""

import unittest
import os
import uuid
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from services.assistant_api.gateway_app import create_default_app
from db.models import AuditEvent, RefundRequest, StaffSession, StaffTenantMembership, StaffUser, Tenant
from services.dashboard_api.auth import hash_password


class TestDashboardApiWiring(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # This test checks route wiring only. Live dependency readiness is
        # covered by the container health probe and must not inherit suite env.
        self._healthcheck_setting = patch.dict(os.environ, {"ENABLE_DEPENDENCY_HEALTHCHECKS": "false"})
        self._healthcheck_setting.start()
        self.app = create_default_app()
        self.client = AsyncClient(
            transport=ASGITransport(app=self.app),
            base_url="http://testserver",
        )

    async def asyncTearDown(self):
        await self.client.aclose()
        self._healthcheck_setting.stop()

    async def test_admin_routes_are_mounted_and_require_a_session(self):
        for path in (
            "/api/admin/v1/auth/sessions",
            "/api/admin/v1/reports",
            "/api/admin/v1/refunds/pending",
        ):
            with self.subTest(path=path):
                response = await self.client.get(path)
                self.assertEqual(response.status_code, 401)

    async def test_legacy_refund_routes_no_longer_bypass_auth(self):
        response = await self.client.get("/desk/refunds/pending")
        self.assertEqual(response.status_code, 401)

        response = await self.client.post(
            "/desk/refunds/REF-TEST/approve",
            json={"staff_id": "spoofed-staff", "notes": "test"},
        )
        self.assertEqual(response.status_code, 401)

    async def test_gateway_health_route_remains_available(self):
        response = await self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "healthy")


@unittest.skipUnless(
    os.getenv("TEST_DATABASE_URL") and os.getenv("DATABASE_ASYNC_URL"),
    "requires isolated QA PostgreSQL and application-role URLs",
)
class TestDashboardApiPostgresIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_login_reports_and_refund_review(self):
        admin_engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
        admin_sessions = async_sessionmaker(admin_engine, expire_on_commit=False)
        suffix = uuid.uuid4().hex[:10]
        staff_id = f"qa-staff-{suffix}"
        email = f"qa-{suffix}@example.com"
        refund_id = f"QA-REFUND-{suffix}"
        app = create_default_app()

        async with admin_sessions() as session:
            async with session.begin():
                if not await session.get(Tenant, "tenant_novaretail"):
                    session.add(Tenant(tenant_id="tenant_novaretail", name="NovaRetail"))
                session.add(StaffUser(
                    staff_id=staff_id,
                    email=email,
                    full_name="QA Manager",
                    password_hash=hash_password("TestPass!234"),
                ))
                # Flush the referenced row before inserting its membership;
                # these ORM models have no relationship for unit-of-work ordering.
                await session.flush()
                session.add(StaffTenantMembership(
                    staff_id=staff_id,
                    tenant_id="tenant_novaretail",
                    role="manager",
                ))
                session.add(RefundRequest(
                    refund_id=refund_id,
                    tenant_id="tenant_novaretail",
                    order_id=f"QA-ORDER-{suffix}",
                    customer_id=f"QA-CUSTOMER-{suffix}",
                    amount_inr=3000,
                    reason="Dashboard integration fixture",
                    state="pending_approval",
                    idempotency_key=f"qa-idem-{suffix}",
                ))

        client = AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")
        try:
            login = await client.post("/api/admin/v1/auth/login", json={
                "email": email,
                "password": "TestPass!234",
            })
            self.assertEqual(login.status_code, 200, login.text)
            csrf_token = login.json()["csrf_token"]

            report = await client.get("/api/admin/v1/reports")
            self.assertEqual(report.status_code, 200, report.text)
            self.assertIn("spend_daily_cap_inr", report.json())

            pending = await client.get("/api/admin/v1/refunds/pending")
            self.assertEqual(pending.status_code, 200, pending.text)
            self.assertTrue(any(row["refund_id"] == refund_id for row in pending.json()))

            approved = await client.post(
                f"/api/admin/v1/refunds/{refund_id}/approve",
                json={"notes": "QA approval"},
                headers={"X-CSRF-Token": csrf_token},
            )
            self.assertEqual(approved.status_code, 200, approved.text)
            self.assertEqual(approved.json()["state"], "approved")
        finally:
            await client.aclose()
            async with admin_sessions() as session:
                async with session.begin():
                    await session.execute(delete(AuditEvent).where(AuditEvent.actor_id == staff_id))
                    await session.execute(delete(RefundRequest).where(RefundRequest.refund_id == refund_id))
                    await session.execute(delete(StaffSession).where(StaffSession.staff_id == staff_id))
                    await session.execute(delete(StaffTenantMembership).where(StaffTenantMembership.staff_id == staff_id))
                    await session.execute(delete(StaffUser).where(StaffUser.staff_id == staff_id))
            await admin_engine.dispose()
