"""
Test Suite: Staff Authentication, Argon2id, RFC 6238 TOTP MFA, Server Sessions & RBAC.
Complies with Specification Section 15.1.8.
"""

import unittest
import asyncio
import hashlib
from datetime import datetime, timezone, timedelta
import secrets
from pathlib import Path
import sys

# Ensure support-assistant is on sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from fastapi import FastAPI, Depends, Request, Response
from fastapi.testclient import TestClient

from db.models import Base, StaffUser, StaffTenantMembership, StaffSession, Tenant
from services.dashboard_api.auth import (
    router as auth_router, hash_password, verify_password,
    generate_totp_secret, verify_totp, is_session_stepped_up, mark_session_stepped_up,
    _step_up_tracker
)
from services.dashboard_api.dependencies import (
    get_current_staff, require_roles, require_step_up, StaffSessionContext
)
import pyotp


def run_async(coro):
    return asyncio.run(coro)


class TestStaffAuthAndSessions(unittest.TestCase):

    def setUp(self):
        _step_up_tracker.clear()
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
        self.session_maker = async_sessionmaker(self.engine, expire_on_commit=False)

        async def init_schema():
            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

        run_async(init_schema())

        # Build test FastAPI app
        self.app = FastAPI()
        self.app.include_router(auth_router)

        # Protected test routes for RBAC
        @self.app.post("/test/refund/approve")
        async def approve_route(staff: StaffSessionContext = Depends(require_roles("executive", "manager"))):
            return {"status": "ok", "role": staff.role}

        @self.app.post("/test/policy/change-limit")
        async def change_limit_route(
            staff: StaffSessionContext = Depends(require_roles("manager")),
            _step: StaffSessionContext = Depends(require_step_up)
        ):
            return {"status": "policy_updated", "staff_id": staff.staff_id}

        @self.app.post("/test/admin/settings")
        async def admin_route(staff: StaffSessionContext = Depends(require_roles("admin"))):
            return {"status": "settings_updated", "role": staff.role}

        self.client = TestClient(self.app)

        # Patch get_async_session to bind to our in-memory engine
        from unittest.mock import patch
        from db import session as db_session

        @db_session.asynccontextmanager
        async def mock_get_session(tenant_id=None):
            async with self.session_maker() as sess:
                async with sess.begin():
                    yield sess

        self.patcher = patch("services.dashboard_api.auth.get_async_session", side_effect=mock_get_session)
        self.patcher2 = patch("services.dashboard_api.dependencies.get_async_session", side_effect=mock_get_session)
        self.patcher.start()
        self.patcher2.start()

    def tearDown(self):
        self.patcher.stop()
        self.patcher2.stop()
        run_async(self.engine.dispose())

    def test_argon2id_hashing_and_verification(self):
        """Verify Argon2id password hash generation and verification."""
        pw = "SuperSecurePassword123!"
        hashed = hash_password(pw)
        self.assertTrue(hashed.startswith("$argon2id$"))
        self.assertTrue(verify_password(hashed, pw))
        self.assertFalse(verify_password(hashed, "WrongPassword"))

    def test_totp_mfa_generation_and_verification(self):
        """Verify RFC 6238 TOTP validation with pyotp."""
        secret = generate_totp_secret()
        totp = pyotp.TOTP(secret)
        code = totp.now()

        self.assertTrue(verify_totp(secret, code))
        self.assertFalse(verify_totp(secret, "000000"))

    def test_full_auth_login_mfa_and_session(self):
        """Test full login -> MFA challenge -> session cookie + CSRF token flow."""
        mfa_sec = generate_totp_secret()
        now = datetime.now(timezone.utc)

        # Seed staff user and tenant in DB
        async def seed():
            async with self.session_maker() as sess:
                async with sess.begin():
                    sess.add(Tenant(tenant_id="tenant_novaretail", name="NovaRetail"))
                    user = StaffUser(
                        staff_id="staff_exec_1",
                        email="exec@novaretail.com",
                        full_name="Priya Raman",
                        password_hash=hash_password("ValidPassword99!"),
                        mfa_secret=mfa_sec,
                    )
                    sess.add(user)
                    sess.add(StaffTenantMembership(
                        staff_id="staff_exec_1",
                        tenant_id="tenant_novaretail",
                        role="executive"
                    ))

        run_async(seed())

        # 1. First step: login with password
        res1 = self.client.post("/api/admin/v1/auth/login", json={
            "email": "exec@novaretail.com",
            "password": "ValidPassword99!"
        })
        self.assertEqual(res1.status_code, 200)
        data1 = res1.json()
        self.assertEqual(data1["status"], "mfa_required")
        ticket = data1["mfa_ticket"]

        # 2. Invalid TOTP code returns 401
        res_bad = self.client.post("/api/admin/v1/auth/mfa/verify", json={
            "mfa_ticket": ticket,
            "code": "111222"
        })
        self.assertEqual(res_bad.status_code, 401)

        # 3. Valid TOTP code issues session and CSRF token
        valid_code = pyotp.TOTP(mfa_sec).now()
        res2 = self.client.post("/api/admin/v1/auth/mfa/verify", json={
            "mfa_ticket": ticket,
            "code": valid_code
        })
        self.assertEqual(res2.status_code, 200)
        data2 = res2.json()
        self.assertEqual(data2["status"], "authenticated")
        self.assertEqual(data2["role"], "executive")
        self.assertIn("csrf_token", data2)
        csrf_token = data2["csrf_token"]
        session_id = res2.cookies.get("session_id")
        self.assertIsNotNone(session_id)

        # 4. State-mutating request without CSRF header is rejected with 403 Forbidden
        res_no_csrf = self.client.post(
            "/test/refund/approve",
            cookies={"session_id": session_id}
        )
        self.assertEqual(res_no_csrf.status_code, 403)
        self.assertIn("Missing X-CSRF-Token", res_no_csrf.json()["detail"])

        # 5. State-mutating request WITH valid CSRF header succeeds
        res_with_csrf = self.client.post(
            "/test/refund/approve",
            cookies={"session_id": session_id},
            headers={"X-CSRF-Token": csrf_token}
        )
        self.assertEqual(res_with_csrf.status_code, 200)
        self.assertEqual(res_with_csrf.json()["role"], "executive")

    def test_role_matrix_separation_and_admin_blocking(self):
        """
        Verify strict Spec 15.1.8 RBAC:
        Admin CANNOT approve refunds.
        Executive CANNOT change policy limits.
        """
        now = datetime.now(timezone.utc)
        csrf = "csrf_token_test_123"
        import hashlib
        csrf_hash = hashlib.sha256(csrf.encode()).hexdigest()

        # Seed 3 staff accounts: executive, manager, admin
        async def seed():
            async with self.session_maker() as sess:
                async with sess.begin():
                    sess.add(Tenant(tenant_id="tenant_novaretail", name="NovaRetail"))
                    # Admin
                    sess.add(StaffUser(
                        staff_id="staff_admin",
                        email="admin@novaretail.com",
                        full_name="System Admin",
                        password_hash=hash_password("Pass123!"),
                    ))
                    sess.add(StaffTenantMembership(
                        staff_id="staff_admin",
                        tenant_id="tenant_novaretail",
                        role="admin"
                    ))
                    sess.add(StaffSession(
                        session_id="sess_admin",
                        staff_id="staff_admin",
                        active_tenant_id="tenant_novaretail",
                        created_at=now,
                        expires_at=now + timedelta(hours=1),
                        csrf_hash=csrf_hash
                    ))

                    # Executive
                    sess.add(StaffUser(
                        staff_id="staff_exec",
                        email="exec@novaretail.com",
                        full_name="Executive Staff",
                        password_hash=hash_password("Pass123!"),
                    ))
                    sess.add(StaffTenantMembership(
                        staff_id="staff_exec",
                        tenant_id="tenant_novaretail",
                        role="executive"
                    ))
                    sess.add(StaffSession(
                        session_id="sess_exec",
                        staff_id="staff_exec",
                        active_tenant_id="tenant_novaretail",
                        created_at=now,
                        expires_at=now + timedelta(hours=1),
                        csrf_hash=csrf_hash
                    ))

                    # Manager
                    sess.add(StaffUser(
                        staff_id="staff_mgr",
                        email="mgr@novaretail.com",
                        full_name="Support Manager",
                        password_hash=hash_password("Pass123!"),
                    ))
                    sess.add(StaffTenantMembership(
                        staff_id="staff_mgr",
                        tenant_id="tenant_novaretail",
                        role="manager"
                    ))
                    sess.add(StaffSession(
                        session_id="sess_mgr",
                        staff_id="staff_mgr",
                        active_tenant_id="tenant_novaretail",
                        created_at=now,
                        expires_at=now + timedelta(hours=1),
                        csrf_hash=csrf_hash
                    ))

        run_async(seed())

        # 1. Admin attempts to approve refund -> 403 Forbidden!
        res_admin_refund = self.client.post(
            "/test/refund/approve",
            cookies={"session_id": "sess_admin"},
            headers={"X-CSRF-Token": csrf}
        )
        self.assertEqual(res_admin_refund.status_code, 403)
        self.assertIn("Forbidden", res_admin_refund.json()["detail"])

        # 2. Executive attempts to change money policy rules -> 403 Forbidden!
        res_exec_policy = self.client.post(
            "/test/policy/change-limit",
            cookies={"session_id": "sess_exec"},
            headers={"X-CSRF-Token": csrf}
        )
        self.assertEqual(res_exec_policy.status_code, 403)

        # 3. Manager attempts to change money policy rules without step-up -> 403 Step-up required!
        res_mgr_no_stepup = self.client.post(
            "/test/policy/change-limit",
            cookies={"session_id": "sess_mgr"},
            headers={"X-CSRF-Token": csrf}
        )
        self.assertEqual(res_mgr_no_stepup.status_code, 403)
        self.assertEqual(res_mgr_no_stepup.json()["detail"]["code"], "STEP_UP_REQUIRED")

        # 4. Mark manager session stepped-up -> succeeds!
        mark_session_stepped_up("sess_mgr", duration_minutes=5)
        res_mgr_stepup = self.client.post(
            "/test/policy/change-limit",
            cookies={"session_id": "sess_mgr"},
            headers={"X-CSRF-Token": csrf}
        )
        self.assertEqual(res_mgr_stepup.status_code, 200)
        self.assertEqual(res_mgr_stepup.json()["status"], "policy_updated")

    def test_admin_staff_provisioning(self):
        """Verify Admin can create and list executives/managers, and non-admins are blocked."""
        now = datetime.now(timezone.utc)
        csrf = secrets.token_hex(16)
        csrf_hash = hashlib.sha256(csrf.encode("utf-8")).hexdigest()

        # Seed admin and manager sessions
        async def seed_users():
            async with self.session_maker() as session:
                async with session.begin():
                    session.add(Tenant(tenant_id="demo-shop", name="Demo Shop"))
                    session.add_all([
                        StaffUser(
                            staff_id="adm_01",
                            email="admin@novaretail.com",
                            full_name="Admin",
                            password_hash=hash_password("Pass123!"),
                            created_at=now
                        ),
                        StaffUser(
                            staff_id="mgr_01",
                            email="manager@novaretail.com",
                            full_name="Manager",
                            password_hash=hash_password("Pass123!"),
                            created_at=now
                        ),
                        StaffTenantMembership(id="m_adm", staff_id="adm_01", tenant_id="demo-shop", role="admin"),
                        StaffTenantMembership(id="m_mgr", staff_id="mgr_01", tenant_id="demo-shop", role="manager"),
                        StaffSession(
                            session_id="sess_adm",
                            staff_id="adm_01",
                            tenant_id="demo-shop",
                            active_tenant_id="demo-shop",
                            csrf_hash=csrf_hash,
                            expires_at=now + timedelta(hours=8)
                        ),
                        StaffSession(
                            session_id="sess_mgr",
                            staff_id="mgr_01",
                            tenant_id="demo-shop",
                            active_tenant_id="demo-shop",
                            csrf_hash=csrf_hash,
                            expires_at=now + timedelta(hours=8)
                        ),
                    ])
        run_async(seed_users())

        # 1. Non-admin (manager) blocked from listing or creating staff
        res_mgr_list = self.client.get(
            "/api/admin/v1/auth/staff",
            cookies={"session_id": "sess_mgr"}
        )
        self.assertEqual(res_mgr_list.status_code, 403)

        res_mgr_create = self.client.post(
            "/api/admin/v1/auth/staff",
            cookies={"session_id": "sess_mgr"},
            headers={"X-CSRF-Token": csrf},
            json={"email": "newexec@novaretail.com", "password": "Password123!", "full_name": "New Exec", "role": "executive"}
        )
        self.assertEqual(res_mgr_create.status_code, 403)

        # 2. Admin creates a new executive
        res_create_exec = self.client.post(
            "/api/admin/v1/auth/staff",
            cookies={"session_id": "sess_adm"},
            headers={"X-CSRF-Token": csrf},
            json={"email": "newexec@novaretail.com", "password": "Password123!", "full_name": "New Exec", "role": "executive"}
        )
        self.assertEqual(res_create_exec.status_code, 200)
        self.assertEqual(res_create_exec.json()["status"], "created")
        self.assertEqual(res_create_exec.json()["role"], "executive")

        # 3. Duplicate email rejected with 409
        res_dup = self.client.post(
            "/api/admin/v1/auth/staff",
            cookies={"session_id": "sess_adm"},
            headers={"X-CSRF-Token": csrf},
            json={"email": "newexec@novaretail.com", "password": "Password123!", "full_name": "New Exec", "role": "executive"}
        )
        self.assertEqual(res_dup.status_code, 409)

        # 4. Invalid role rejected with 400
        res_inv = self.client.post(
            "/api/admin/v1/auth/staff",
            cookies={"session_id": "sess_adm"},
            headers={"X-CSRF-Token": csrf},
            json={"email": "invalid@novaretail.com", "password": "Password123!", "full_name": "Invalid", "role": "superman"}
        )
        self.assertEqual(res_inv.status_code, 400)

        # 5. Admin lists staff members
        res_list = self.client.get(
            "/api/admin/v1/auth/staff",
            cookies={"session_id": "sess_adm"}
        )
        self.assertEqual(res_list.status_code, 200)
        emails = [s["email"] for s in res_list.json()]
        self.assertIn("newexec@novaretail.com", emails)
        self.assertIn("admin@novaretail.com", emails)



if __name__ == "__main__":
    unittest.main()
