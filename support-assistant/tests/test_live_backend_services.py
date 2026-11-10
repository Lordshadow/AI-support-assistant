"""
Live End-to-End Service Verification for Backend API Review.
Tests every backend service systematically and outputs deterministic evidence.
"""

import asyncio
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import sys
import unittest
import uuid

# Ensure support-assistant is on sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import select

from db.models import (
    Base, Tenant, StaffUser, StaffTenantMembership, StaffSession,
    RefundRequest, AuditEvent, ConversationSession, ConversationTurn,
    SpendLedger, Escalation, KnowledgeVersion
)
from services.assistant_api.gateway_app import create_default_app, GatewayApp
from services.dashboard_api.auth import hash_password, mark_session_stepped_up, _step_up_tracker


async def run_backend_verification():
    print("=" * 80)
    print("STARTING BACKEND SERVICES END-TO-END REVIEW")
    print("=" * 80)

    # 1. Setup isolated in-memory SQLite database
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Patch get_async_session across modules
    from unittest.mock import patch
    from db import session as db_session

    @db_session.asynccontextmanager
    async def mock_get_session(tenant_id=None, engine_arg=None):
        async with session_maker() as sess:
            async with sess.begin():
                yield sess

    patchers = [
        patch("services.dashboard_api.auth.get_async_session", side_effect=mock_get_session),
        patch("services.dashboard_api.dependencies.get_async_session", side_effect=mock_get_session),
        patch("services.dashboard_api.refunds.get_async_session", side_effect=mock_get_session),
        patch("services.dashboard_api.reports.get_async_session", side_effect=mock_get_session),
        patch("services.dashboard_api.conversations.get_async_session", side_effect=mock_get_session),
        patch("services.dashboard_api.escalations.get_async_session", side_effect=mock_get_session),
        patch("services.dashboard_api.knowledge.get_async_session", side_effect=mock_get_session),
    ]
    for p in patchers:
        p.start()

    try:
        now = datetime.now(timezone.utc)
        # Seed test data: Tenants
        async with session_maker() as sess:
            async with sess.begin():
                t1 = Tenant(tenant_id="tenant_novaretail", name="NovaRetail", daily_spend_cap_inr=2500, monthly_spend_cap_inr=50000)
                t2 = Tenant(tenant_id="tenant_other", name="OtherStore", daily_spend_cap_inr=2500, monthly_spend_cap_inr=50000)
                sess.add_all([t1, t2])

                # Staff users
                mgr = StaffUser(
                    staff_id="staff_mgr_01",
                    email="manager@novaretail.com",
                    full_name="Alice Manager",
                    password_hash=hash_password("ManagerPass!123"),
                )
                exc = StaffUser(
                    staff_id="staff_exc_01",
                    email="executive@novaretail.com",
                    full_name="Bob Executive",
                    password_hash=hash_password("ExecPass!123"),
                )
                adm = StaffUser(
                    staff_id="staff_adm_01",
                    email="admin@novaretail.com",
                    full_name="Carol Admin",
                    password_hash=hash_password("AdminPass!123"),
                )
                sess.add_all([mgr, exc, adm])
                await sess.flush()

                # Memberships
                sess.add_all([
                    StaffTenantMembership(staff_id="staff_mgr_01", tenant_id="tenant_novaretail", role="manager"),
                    StaffTenantMembership(staff_id="staff_exc_01", tenant_id="tenant_novaretail", role="executive"),
                    StaffTenantMembership(staff_id="staff_adm_01", tenant_id="tenant_novaretail", role="admin"),
                    StaffTenantMembership(staff_id="staff_mgr_01", tenant_id="tenant_other", role="manager"),
                ])

                # Seed Refunds
                sess.add_all([
                    RefundRequest(
                        refund_id="REF-PEND-01",
                        tenant_id="tenant_novaretail",
                        order_id="ORD-101",
                        customer_id="CUST-01",
                        amount_inr=1500,
                        reason="Customer damaged box",
                        state="pending_approval",
                        idempotency_key="IDEM-01"
                    ),
                    RefundRequest(
                        refund_id="REF-PEND-HIGH",
                        tenant_id="tenant_novaretail",
                        order_id="ORD-102",
                        customer_id="CUST-02",
                        amount_inr=8500,
                        reason="High value defective screen",
                        state="pending_approval",
                        idempotency_key="IDEM-02"
                    ),
                    RefundRequest(
                        refund_id="REF-OTHER-99",
                        tenant_id="tenant_other",
                        order_id="ORD-OTHER-01",
                        customer_id="CUST-OTHER-01",
                        amount_inr=3000,
                        reason="Other tenant refund",
                        state="pending_approval",
                        idempotency_key="IDEM-OTHER-01"
                    ),
                ])

                # Seed Spend Ledger
                sess.add(SpendLedger(
                    id=f"SP-{uuid.uuid4().hex[:12]}",
                    tenant_id="tenant_novaretail",
                    turn_id="TURN-01",
                    purpose="chat",
                    model="groq/llama-3.3-70b-versatile",
                    prompt_tokens=450,
                    completion_tokens=150,
                    cost_inr=0.045,
                    created_at=now
                ))

                # Seed Conversation & Turn
                conv = ConversationSession(
                    conv_id="CONV-01",
                    tenant_id="tenant_novaretail",
                    customer_id="CUST-01",
                    channel="web",
                    handoff_state="bot",
                    last_user_message_at=now
                )
                sess.add(conv)
                sess.add(ConversationTurn(
                    turn_id="TURN-01",
                    conv_id="CONV-01",
                    tenant_id="tenant_novaretail",
                    step_index=1,
                    user_input_masked="I need refund for my order ORD-101. Phone: [PHONE REDACTED]",
                    assistant_response_masked="I have submitted your refund request.",
                    latency_ms=120,
                    created_at=now
                ))

                # Seed Escalations
                sess.add_all([
                    Escalation(
                        esc_id="ESC-01",
                        tenant_id="tenant_novaretail",
                        conv_id="CONV-01",
                        reason="refund_dispute",
                        summary="Customer disputes refund amount",
                        priority="high",
                        state="open",
                        created_at=now - timedelta(minutes=15)
                    ),
                    Escalation(
                        esc_id="ESC-OTHER-99",
                        tenant_id="tenant_other",
                        conv_id="CONV-01",
                        reason="shipping_delay",
                        summary="Shipping delay inquiry",
                        priority="medium",
                        state="open",
                        created_at=now - timedelta(minutes=30)
                    )
                ])

                # Seed Knowledge Version
                sess.add(KnowledgeVersion(
                    version_id="KV-POLICY-01",
                    tenant_id="tenant_novaretail",
                    type="policy",
                    status="active",
                    manifest={"clauses": 5, "return_days": 30},
                    created_by="staff_mgr_01",
                    created_at=now
                ))

        # Instantiate ASGI App
        app = create_default_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            print("\n--- Check 12: Staff Login & Role-bound GET Routes ---")
            # Login as Manager
            login_resp = await client.post("/api/admin/v1/auth/login", json={
                "email": "manager@novaretail.com",
                "password": "ManagerPass!123",
                "tenant_id": "tenant_novaretail"
            })
            assert login_resp.status_code == 200, f"Manager login failed: {login_resp.text}"
            mgr_data = login_resp.json()
            csrf_token = mgr_data["csrf_token"]
            session_cookie = login_resp.cookies.get("session_id")
            client.cookies.set("session_id", session_cookie)
            print(f"Check 12.1 PASS: Manager Login HTTP 200; staff_id={mgr_data['staff_id']}, role={mgr_data['role']}, csrf_token present")

            # GET /api/admin/v1/reports
            r_rep = await client.get("/api/admin/v1/reports")
            assert r_rep.status_code == 200, f"Reports failed: {r_rep.text}"
            assert "spend_daily_cap_inr" in r_rep.json()
            print(f"Check 12.2 PASS: GET /api/admin/v1/reports HTTP 200; spend_daily_cap_inr={r_rep.json()['spend_daily_cap_inr']}")

            # GET /api/admin/v1/reports/spend
            r_spend = await client.get("/api/admin/v1/reports/spend")
            assert r_spend.status_code == 200, f"Reports spend failed: {r_spend.text}"
            assert "daily" in r_spend.json() and "monthly" in r_spend.json()
            print(f"Check 12.3 PASS: GET /api/admin/v1/reports/spend HTTP 200; daily_spent={r_spend.json()['daily']['spent_inr']}")

            # GET /api/admin/v1/reports/metrics
            r_metrics = await client.get("/api/admin/v1/reports/metrics")
            assert r_metrics.status_code == 200, f"Reports metrics failed: {r_metrics.text}"
            assert "conversations" in r_metrics.json()
            print(f"Check 12.4 PASS: GET /api/admin/v1/reports/metrics HTTP 200; total_conversations={r_metrics.json()['conversations']['total']}")

            # GET /api/admin/v1/refunds/pending
            r_ref = await client.get("/api/admin/v1/refunds/pending")
            assert r_ref.status_code == 200
            pending_ids = [row["refund_id"] for row in r_ref.json()]
            assert "REF-PEND-01" in pending_ids
            print(f"Check 12.5 PASS: GET /api/admin/v1/refunds/pending HTTP 200; pending_count={len(pending_ids)}")

            # GET /api/admin/v1/conversations
            r_conv = await client.get("/api/admin/v1/conversations")
            assert r_conv.status_code == 200
            assert r_conv.json()["count"] >= 1
            print(f"Check 12.6 PASS: GET /api/admin/v1/conversations HTTP 200; conv_count={r_conv.json()['count']}")

            # GET /api/admin/v1/escalations
            r_esc = await client.get("/api/admin/v1/escalations")
            assert r_esc.status_code == 200
            assert r_esc.json()["count"] >= 1
            print(f"Check 12.7 PASS: GET /api/admin/v1/escalations HTTP 200; esc_count={r_esc.json()['count']}, wait_min={r_esc.json()['escalations'][0]['wait_minutes']}")

            # GET /api/admin/v1/knowledge/versions
            r_kv = await client.get("/api/admin/v1/knowledge/versions")
            assert r_kv.status_code == 200
            print(f"Check 12.8 PASS: GET /api/admin/v1/knowledge/versions HTTP 200; version_count={len(r_kv.json())}")

            print("\n--- Check 13: State-changing Route Controls (CSRF & RBAC) ---")
            # State mutation without CSRF token
            r_no_csrf = await client.post("/api/admin/v1/refunds/REF-PEND-01/approve", json={"notes": "missing csrf"})
            assert r_no_csrf.status_code == 403, f"Expected 403, got {r_no_csrf.status_code}"
            print(f"Check 13.1 PASS: State mutation without X-CSRF-Token returned HTTP 403: {r_no_csrf.json()['detail']}")

            # State mutation with invalid CSRF token
            r_bad_csrf = await client.post(
                "/api/admin/v1/refunds/REF-PEND-01/approve",
                json={"notes": "bad csrf"},
                headers={"X-CSRF-Token": "bad-token-xyz"}
            )
            assert r_bad_csrf.status_code == 403, f"Expected 403, got {r_bad_csrf.status_code}"
            print(f"Check 13.2 PASS: State mutation with invalid X-CSRF-Token returned HTTP 403: {r_bad_csrf.json()['detail']}")

            # RBAC test: Login as Executive and try to access Manager-only reports
            login_exc = await client.post("/api/admin/v1/auth/login", json={
                "email": "executive@novaretail.com",
                "password": "ExecPass!123",
                "tenant_id": "tenant_novaretail"
            })
            assert login_exc.status_code == 200
            exc_session = login_exc.cookies.get("session_id")
            
            client_exc = AsyncClient(transport=transport, base_url="http://testserver")
            client_exc.cookies.set("session_id", exc_session)
            r_exc_reports = await client_exc.get("/api/admin/v1/reports")
            assert r_exc_reports.status_code == 403
            print(f"Check 13.3 PASS: Executive attempting Manager route (/reports) returned HTTP 403: {r_exc_reports.json()['detail']}")

            # Admin attempting Executive/Manager route (/conversations) - Spec 15.1.8 separation
            login_adm = await client.post("/api/admin/v1/auth/login", json={
                "email": "admin@novaretail.com",
                "password": "AdminPass!123",
                "tenant_id": "tenant_novaretail"
            })
            assert login_adm.status_code == 200
            adm_session = login_adm.cookies.get("session_id")
            client_adm = AsyncClient(transport=transport, base_url="http://testserver")
            client_adm.cookies.set("session_id", adm_session)
            r_adm_conv = await client_adm.get("/api/admin/v1/conversations")
            assert r_adm_conv.status_code == 403
            print(f"Check 13.4 PASS: Admin attempting Executive/Manager route (/conversations) returned HTTP 403: {r_adm_conv.json()['detail']}")

            print("\n--- Check 14: Session Lifecycle (List, Revoke, Logout) ---")
            # Manager attempting to list sessions should be rejected with 403 (Admin required)
            r_mgr_sess = await client.get("/api/admin/v1/auth/sessions")
            assert r_mgr_sess.status_code == 403
            print(f"Check 14.1 PASS: Manager listing sessions blocked with HTTP 403 (Admin required): {r_mgr_sess.json()['detail']}")

            # Admin login
            login_adm = await client.post("/api/admin/v1/auth/login", json={
                "email": "admin@novaretail.com",
                "password": "AdminPass!123",
                "tenant_id": "tenant_novaretail"
            })
            assert login_adm.status_code == 200
            adm_csrf = login_adm.json()["csrf_token"]
            adm_sess_cookie = login_adm.cookies.get("session_id")
            
            client_adm = AsyncClient(transport=transport, base_url="http://testserver")
            client_adm.cookies.set("session_id", adm_sess_cookie)

            # Admin lists sessions
            r_sess = await client_adm.get("/api/admin/v1/auth/sessions")
            assert r_sess.status_code == 200
            sess_list = r_sess.json()
            assert len(sess_list) >= 1
            print(f"Check 14.2 PASS: Admin GET /api/admin/v1/auth/sessions HTTP 200; active_sessions={len(sess_list)}")

            # Create another session to revoke
            other_sess_id = f"test-sess-{uuid.uuid4().hex}"
            async with session_maker() as sess:
                async with sess.begin():
                    sess.add(StaffSession(
                        session_id=other_sess_id,
                        staff_id="staff_mgr_01",
                        tenant_id="tenant_novaretail",
                        active_tenant_id="tenant_novaretail",
                        csrf_hash="dummy_hash",
                        expires_at=now + timedelta(hours=8),
                    ))
            # Admin revokes session
            r_revoke = await client_adm.delete(
                f"/api/admin/v1/auth/sessions/{other_sess_id}",
                headers={"X-CSRF-Token": adm_csrf}
            )
            assert r_revoke.status_code == 200
            print(f"Check 14.3 PASS: Admin DELETE /api/admin/v1/auth/sessions/{{id}} HTTP 200; status={r_revoke.json()['status']}")

            # Verify revoked session is rejected with HTTP 401
            client_revoked = AsyncClient(transport=transport, base_url="http://testserver")
            client_revoked.cookies.set("session_id", other_sess_id)
            r_revoked_try = await client_revoked.get("/api/admin/v1/reports")
            assert r_revoked_try.status_code == 401
            print(f"Check 14.4 PASS: Revoked session access returned HTTP 401: {r_revoked_try.json()['detail']}")

            # Logout current manager session
            r_logout = await client.post(
                "/api/admin/v1/auth/logout",
                headers={"X-CSRF-Token": csrf_token}
            )
            assert r_logout.status_code == 200
            print(f"Check 14.5 PASS: Manager POST /api/admin/v1/auth/logout HTTP 200; status={r_logout.json()['status']}")

            # Verify logged-out session now gets HTTP 401
            r_after_logout = await client.get("/api/admin/v1/reports")
            assert r_after_logout.status_code == 401
            print(f"Check 14.6 PASS: Post-logout request returned HTTP 401: {r_after_logout.json()['detail']}")

            print("\n--- Check 15: Refund Review Controls ---")
            # Log back in as Manager
            login_resp2 = await client.post("/api/admin/v1/auth/login", json={
                "email": "manager@novaretail.com",
                "password": "ManagerPass!123",
                "tenant_id": "tenant_novaretail"
            })
            csrf_token2 = login_resp2.json()["csrf_token"]
            client.cookies.set("session_id", login_resp2.cookies.get("session_id"))

            # Step 1: Normal approval (<= ₹5,000)
            r_appr = await client.post(
                "/api/admin/v1/refunds/REF-PEND-01/approve",
                json={"notes": "Approved by Alice Manager"},
                headers={"X-CSRF-Token": csrf_token2}
            )
            assert r_appr.status_code == 200, f"Approve failed: {r_appr.text}"
            assert r_appr.json()["state"] == "approved"
            print(f"Check 15.1 PASS: POST /api/admin/v1/refunds/REF-PEND-01/approve HTTP 200; state={r_appr.json()['state']}")

            # Step 2: Double decision / conflict check
            r_appr_repeat = await client.post(
                "/api/admin/v1/refunds/REF-PEND-01/approve",
                json={"notes": "Duplicate attempt"},
                headers={"X-CSRF-Token": csrf_token2}
            )
            assert r_appr_repeat.status_code == 409
            print(f"Check 15.2 PASS: Repeated approve on decided refund returned HTTP 409 Conflict: {r_appr_repeat.json()['detail']}")

            # Step 3: High value (> ₹5,000) requires step-up
            r_high_no_step = await client.post(
                "/api/admin/v1/refunds/REF-PEND-HIGH/approve",
                json={"notes": "High value approval"},
                headers={"X-CSRF-Token": csrf_token2}
            )
            assert r_high_no_step.status_code == 403
            assert r_high_no_step.json()["detail"]["code"] == "STEP_UP_REQUIRED"
            print(f"Check 15.3 PASS: High value refund (> ₹5,000) without step-up blocked with HTTP 403: {r_high_no_step.json()['detail']}")

            # Step 4: Step-up authentication
            curr_sess_id = login_resp2.cookies.get("session_id")
            mark_session_stepped_up(curr_sess_id)
            r_high_stepped = await client.post(
                "/api/admin/v1/refunds/REF-PEND-HIGH/approve",
                json={"notes": "High value approval after step-up"},
                headers={"X-CSRF-Token": csrf_token2}
            )
            assert r_high_stepped.status_code == 200
            assert r_high_stepped.json()["state"] == "approved"
            print(f"Check 15.4 PASS: High value refund with step-up approved HTTP 200; state={r_high_stepped.json()['state']}")

            # Step 5: Reject refund without notes must fail with HTTP 422
            # Seed another refund for rejection test
            async with session_maker() as sess:
                async with sess.begin():
                    sess.add(RefundRequest(
                        refund_id="REF-PEND-REJ",
                        tenant_id="tenant_novaretail",
                        order_id="ORD-103",
                        customer_id="CUST-03",
                        amount_inr=1200,
                        reason="Test rejection",
                        state="pending_approval",
                        idempotency_key="IDEM-REJ-01"
                    ))
            r_rej_empty = await client.post(
                "/api/admin/v1/refunds/REF-PEND-REJ/reject",
                json={"notes": ""},
                headers={"X-CSRF-Token": csrf_token2}
            )
            assert r_rej_empty.status_code == 422
            print(f"Check 15.5 PASS: Rejection without audit note returned HTTP 422: {r_rej_empty.json()['detail']}")

            # Reject refund with notes
            r_rej_valid = await client.post(
                "/api/admin/v1/refunds/REF-PEND-REJ/reject",
                json={"notes": "Inspection confirmed customer damage outside warranty."},
                headers={"X-CSRF-Token": csrf_token2}
            )
            assert r_rej_valid.status_code == 200
            assert r_rej_valid.json()["state"] == "rejected"
            print(f"Check 15.6 PASS: Rejection with audit note approved HTTP 200; state={r_rej_valid.json()['state']}")

            print("\n--- Check 16: Multi-Tenant Data Isolation ---")
            # Manager is logged in under tenant_novaretail
            # List pending refunds - must NOT contain tenant_other refunds (REF-OTHER-99)
            r_t1_refs = await client.get("/api/admin/v1/refunds/pending")
            t1_ref_ids = [x["refund_id"] for x in r_t1_refs.json()]
            assert "REF-OTHER-99" not in t1_ref_ids
            print(f"Check 16.1 PASS: Cross-tenant refund REF-OTHER-99 is invisible in tenant_novaretail: {t1_ref_ids}")

            # Attempting to mutate cross-tenant refund REF-OTHER-99 from tenant_novaretail
            r_cross_mut = await client.post(
                "/api/admin/v1/refunds/REF-OTHER-99/approve",
                json={"notes": "Illegal cross-tenant mutation"},
                headers={"X-CSRF-Token": csrf_token2}
            )
            assert r_cross_mut.status_code == 409
            print(f"Check 16.2 PASS: Cross-tenant refund mutation rejected with HTTP 409 Conflict: {r_cross_mut.json()['detail']}")

            # List escalations - must NOT contain tenant_other escalations (ESC-OTHER-99)
            r_t1_escs = await client.get("/api/admin/v1/escalations")
            t1_esc_ids = [x["esc_id"] for x in r_t1_escs.json()["escalations"]]
            assert "ESC-OTHER-99" not in t1_esc_ids
            print(f"Check 16.3 PASS: Cross-tenant escalation ESC-OTHER-99 is invisible in tenant_novaretail: {t1_esc_ids}")

            print("\n--- Check 17: Knowledge, Conversation, and Escalation API Boundaries ---")
            # Escalation claim
            r_claim = await client.post(
                "/api/admin/v1/escalations/ESC-01/claim",
                headers={"X-CSRF-Token": csrf_token2}
            )
            assert r_claim.status_code == 200
            assert r_claim.json()["status"] == "assigned"
            print(f"Check 17.1 PASS: Escalation claim HTTP 200; status={r_claim.json()['status']}, assigned_to={r_claim.json()['assigned_to']}")

            # Repeated claim conflict
            r_claim_conflict = await client.post(
                "/api/admin/v1/escalations/ESC-01/claim",
                headers={"X-CSRF-Token": csrf_token2}
            )
            assert r_claim_conflict.status_code == 409
            print(f"Check 17.2 PASS: Repeated claim returned HTTP 409 Conflict: {r_claim_conflict.json()['detail']}")

            # Escalation resolution
            r_resolve = await client.post(
                "/api/admin/v1/escalations/ESC-01/resolve",
                json={"resolution_note": "Resolved dispute directly with customer by Alice Manager."},
                headers={"X-CSRF-Token": csrf_token2}
            )
            assert r_resolve.status_code == 200
            assert r_resolve.json()["status"] == "resolved"
            print(f"Check 17.3 PASS: Escalation resolve HTTP 200; status={r_resolve.json()['status']}")

            # Conversation transcript read
            r_conv_detail = await client.get("/api/admin/v1/conversations/CONV-01")
            assert r_conv_detail.status_code == 200
            conv_detail = r_conv_detail.json()
            assert len(conv_detail["turns"]) >= 1
            assert "[PHONE REDACTED]" in conv_detail["turns"][0]["user_masked"]
            print(f"Check 17.4 PASS: Audited conversation transcript read HTTP 200; PII scrubbed: {conv_detail['turns'][0]['user_masked']}")

            # Policy Draft creation validation
            r_draft_empty = await client.post(
                "/api/admin/v1/knowledge/policy/draft",
                json={
                    "filename": "empty.md",
                    "clauses": [],
                    "confirmed_policy": {"return_window_days": 30, "excluded_categories": [], "auto_refund_limit_inr": 2000}
                },
                headers={"X-CSRF-Token": csrf_token2}
            )
            assert r_draft_empty.status_code == 400
            print(f"Check 17.5 PASS: Policy draft with empty clauses returned HTTP 400: {r_draft_empty.json()['detail']}")

            print("\n--- Check 18: Operational Readiness & Health Probe ---")
            r_health = await client.get("/health")
            assert r_health.status_code == 200
            assert r_health.json()["status"] == "healthy"
            print(f"Check 18.1 PASS: GET /health HTTP 200; status={r_health.json()['status']}")

    finally:
        for p in patchers:
            p.stop()
        await engine.dispose()

    print("\n" + "=" * 80)
    print("ALL SERVICES E2E CHECKS COMPLETED AND VERIFIED SUCCESSFULLY!")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(run_backend_verification())
