"""Seed fake records and exercise the live API in a disposable QA stack.

Run only inside the isolated Compose QA container:
    python -m scripts.qa_live_workflows

The script refuses non-test environments, generates temporary staff passwords,
and uses only the ``tenant_novaretail`` demo dataset and a uniquely named QA tenant.
"""

from __future__ import annotations

import asyncio
import os
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import select

from db.models import (
    ConversationSession,
    ConversationTurn,
    Escalation,
    SpendLedger,
    StaffTenantMembership,
    StaffUser,
)
from db.session import get_sync_session
from scripts.seed_demo_db import seed_demo_data
from services.dashboard_api.auth import hash_password


TENANT_ID = "tenant_novaretail"


def _seed_qa_staff_and_workflows(run_tag: str, admin_password: str) -> None:
    now = datetime.now(timezone.utc)
    with get_sync_session(tenant_id=TENANT_ID) as session:
        admin_id = f"qa-admin-{run_tag}"
        admin_email = f"qa-admin-{run_tag}@example.com"
        admin = session.get(StaffUser, admin_id)
        if admin is None:
            admin = StaffUser(
                staff_id=admin_id,
                email=admin_email,
                full_name="QA Admin",
                password_hash=hash_password(admin_password),
                created_at=now,
            )
            session.add(admin)
            session.flush()
        else:
            admin.password_hash = hash_password(admin_password)
            admin.failed_attempts = 0
            admin.locked_until = None

        membership = session.execute(
            select(StaffTenantMembership).where(
                StaffTenantMembership.staff_id == admin_id,
                StaffTenantMembership.tenant_id == TENANT_ID,
            )
        ).scalars().first()
        if membership is None:
            session.add(StaffTenantMembership(
                id=f"qa-membership-{run_tag}",
                staff_id=admin_id,
                tenant_id=TENANT_ID,
                role="admin",
                created_at=now,
            ))

        conv_id = f"qa-conversation-{run_tag}"
        conversation = session.get(ConversationSession, conv_id)
        if conversation is None:
            session.add(ConversationSession(
                conv_id=conv_id,
                tenant_id=TENANT_ID,
                channel="web",
                customer_id="demo_customer_00001",
                handoff_state="open",
                last_user_message_at=now,
                created_at=now,
            ))
            session.flush()

        turn_id = f"qa-turn-{run_tag}"
        if session.get(ConversationTurn, turn_id) is None:
            session.add(ConversationTurn(
                turn_id=turn_id,
                conv_id=conv_id,
                tenant_id=TENANT_ID,
                step_index=1,
                user_input_masked="Where is my order? My phone is [PHONE REDACTED]",
                assistant_response_masked="I can check that order for you.",
                intent="order_status",
                latency_ms=120,
                tokens_prompt=10,
                tokens_completion=8,
                tool_calls_json=[{"name": "list_recent_orders", "arguments": {}}],
                grounding_score=1.0,
                created_at=now,
            ))

        spend_id = f"qa-spend-{run_tag}"
        if session.get(SpendLedger, spend_id) is None:
            session.add(SpendLedger(
                id=spend_id,
                tenant_id=TENANT_ID,
                turn_id=turn_id,
                purpose="chat",
                model="qa-gpt-4o-mini",
                prompt_tokens=10,
                completion_tokens=8,
                cost_inr=0.12,
                created_at=now,
            ))

        esc_id = f"qa-escalation-{run_tag}"
        escalation = session.get(Escalation, esc_id)
        if escalation is None:
            session.add(Escalation(
                esc_id=esc_id,
                conv_id=conv_id,
                tenant_id=TENANT_ID,
                reason="qa_workflow_test",
                summary="Disposable QA escalation for live API workflow verification.",
                priority="high",
                state="open",
                created_at=now,
            ))
        else:
            escalation.state = "open"
            escalation.assigned_to = None
            escalation.resolved_at = None
            escalation.resolution_note = None
            conversation.handoff_state = "open"

        admin_esc_id = f"qa-admin-escalation-{run_tag}"
        admin_escalation = session.get(Escalation, admin_esc_id)
        if admin_escalation is None:
            session.add(Escalation(
                esc_id=admin_esc_id,
                conv_id=conv_id,
                tenant_id=TENANT_ID,
                reason="qa_admin_workflow_test",
                summary="Disposable QA escalation for admin dashboard access verification.",
                priority="medium",
                state="open",
                created_at=now,
            ))
        else:
            admin_escalation.state = "open"
            admin_escalation.assigned_to = None
            admin_escalation.resolved_at = None
            admin_escalation.resolution_note = None


def _assert_response(response: httpx.Response, expected_status: int, label: str) -> None:
    if response.status_code != expected_status:
        raise AssertionError(
            f"{label}: expected HTTP {expected_status}, got {response.status_code}: "
            f"{response.text[:400]}"
        )


def _passed(label: str) -> None:
    print(f"PASS {label}")


async def _run_workflows(run_tag: str, admin_email: str, admin_password: str) -> None:
    base_url = os.getenv("QA_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    manager_email = f"qa-manager-{run_tag}@example.com"
    manager_password = secrets.token_urlsafe(24)
    owner_email = f"qa-owner-{run_tag}@example.com"
    owner_password = secrets.token_urlsafe(24)
    new_tenant_id = f"qa_{run_tag}"
    admin_headers: dict[str, str] = {}

    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as admin:
        health = await admin.get("/health")
        _assert_response(health, 200, "assistant health")
        _passed("assistant health")

        login = await admin.post("/api/admin/v1/auth/login", json={
            "email": admin_email,
            "password": admin_password,
            "tenant_id": TENANT_ID,
        })
        _assert_response(login, 200, "QA admin login")
        admin_headers["X-CSRF-Token"] = login.json()["csrf_token"]
        _passed("admin login and tenant session")

        admin_esc_id = f"qa-admin-escalation-{run_tag}"
        admin_queue = await admin.get("/api/admin/v1/escalations", params={"state": "open"})
        _assert_response(admin_queue, 200, "admin open escalation queue")
        if not any(row["esc_id"] == admin_esc_id for row in admin_queue.json()["escalations"]):
            raise AssertionError("admin could not view the seeded escalation")
        admin_claim = await admin.post(
            f"/api/admin/v1/escalations/{admin_esc_id}/claim", headers=admin_headers
        )
        _assert_response(admin_claim, 200, "admin escalation claim")
        admin_resolution = await admin.post(
            f"/api/admin/v1/escalations/{admin_esc_id}/resolve",
            headers=admin_headers,
            json={"resolution_note": "Resolved in the disposable admin dashboard QA workflow."},
        )
        _assert_response(admin_resolution, 200, "admin escalation resolution")
        _passed("admin escalation view, claim, and resolution")

        staff_list = await admin.get("/api/admin/v1/auth/staff")
        _assert_response(staff_list, 200, "admin staff listing")
        _passed("staff administration list")

        staff_create = await admin.post(
            "/api/admin/v1/auth/staff",
            headers=admin_headers,
            json={
                "email": manager_email,
                "password": manager_password,
                "full_name": "QA Manager",
                "role": "manager",
            },
        )
        _assert_response(staff_create, 200, "manager account provisioning")
        manager_id = staff_create.json()["staff_id"]
        listed_staff = await admin.get("/api/admin/v1/auth/staff")
        _assert_response(listed_staff, 200, "staff list after provisioning")
        if not any(row["staff_id"] == manager_id for row in listed_staff.json()):
            raise AssertionError("created manager account is absent from the staff list")
        _passed("manager provisioning and account listing")

        settings = await admin.get("/api/admin/v1/settings")
        _assert_response(settings, 200, "tenant settings read")
        widget_settings = await admin.get("/api/admin/v1/widget/settings")
        _assert_response(widget_settings, 200, "widget settings read")
        widget_config = await admin.get("/api/admin/v1/widget/config")
        _assert_response(widget_config, 200, "widget embed configuration")
        _passed("settings and widget configuration reads")

        order = await admin.get("/api/admin/v1/orders/demo_order_00001")
        _assert_response(order, 200, "tenant order lookup")
        if order.json().get("items") is None:
            raise AssertionError("order lookup omitted its line items")
        _passed("order details and line items")

        admin_search = await admin.get(
            "/api/admin/v1/search", params={"q": "demo_order_00001"}
        )
        _assert_response(admin_search, 200, "global order search")
        if not any(row["id"] == "demo_order_00001" for row in admin_search.json()["results"]):
            raise AssertionError("global search did not return the matching order")
        _passed("global search deep-link records")

        pending = await admin.get("/api/admin/v1/refunds/pending")
        _assert_response(pending, 200, "pending refund list")
        low_pending = [row for row in pending.json() if float(row["amount_inr"]) <= 2000]
        if len(low_pending) < 2:
            raise AssertionError("demo seed did not produce two low-value pending refunds")
        approved_id, rejected_id = low_pending[0]["refund_id"], low_pending[1]["refund_id"]
        decision = await admin.post(
            f"/api/admin/v1/refunds/{approved_id}/approve",
            headers=admin_headers,
            json={"notes": "QA approval after eligibility review."},
        )
        _assert_response(decision, 200, "refund approval")
        if decision.json().get("state") != "approved":
            raise AssertionError("refund approval did not persist the approved state")
        rejection = await admin.post(
            f"/api/admin/v1/refunds/{rejected_id}/reject",
            headers=admin_headers,
            json={"notes": "QA rejection with required staff documentation."},
        )
        _assert_response(rejection, 200, "refund rejection with note")
        if rejection.json().get("state") != "rejected":
            raise AssertionError("refund rejection did not persist the rejected state")
        _passed("refund approval and documented rejection")

        tenant_create = await admin.post(
            "/api/admin/v1/auth/tenants",
            headers=admin_headers,
            json={
                "tenant_id": new_tenant_id,
                "name": f"QA Workspace {run_tag}",
                "owner_email": owner_email,
                "owner_name": "QA Workspace Owner",
                "owner_password": owner_password,
            },
        )
        _assert_response(tenant_create, 201, "tenant workspace provisioning")
        _passed("tenant workspace and owner provisioning")

        async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as manager:
            manager_login = await manager.post("/api/admin/v1/auth/login", json={
                "email": manager_email,
                "password": manager_password,
                "tenant_id": TENANT_ID,
            })
            _assert_response(manager_login, 200, "manager login")
            manager_headers = {"X-CSRF-Token": manager_login.json()["csrf_token"]}

            forbidden_staff = await manager.get("/api/admin/v1/auth/staff")
            _assert_response(forbidden_staff, 403, "manager staff-admin restriction")
            _passed("role-based staff administration restriction")

            metrics = await manager.get("/api/admin/v1/reports/metrics", params={"days": 7})
            _assert_response(metrics, 200, "performance report metrics")
            spend = await manager.get("/api/admin/v1/reports/spend")
            _assert_response(spend, 200, "spend report")
            export = await manager.get("/api/admin/v1/reports/export.csv", params={"days": 7})
            _assert_response(export, 200, "CSV report export")
            _passed("metrics, spend, and CSV reports")

            search = await manager.get(
                "/api/admin/v1/search", params={"q": "demo_order_00001"}
            )
            _assert_response(search, 200, "manager global search")
            detail = await manager.get("/api/admin/v1/orders/demo_order_00001")
            _assert_response(detail, 200, "manager order lookup")
            _passed("manager order search and detail")

            conv_id = f"qa-conversation-{run_tag}"
            transcript = await manager.get(f"/api/admin/v1/conversations/{conv_id}")
            _assert_response(transcript, 200, "masked conversation transcript")
            if "[PHONE REDACTED]" not in transcript.text:
                raise AssertionError("transcript did not return the masked phone placeholder")
            trace = await manager.get(
                f"/api/admin/v1/conversations/{conv_id}/turns/qa-turn-{run_tag}/trace"
            )
            _assert_response(trace, 200, "conversation trace evidence")
            trace_data = trace.json()
            if trace_data.get("model_name") != "qa-gpt-4o-mini" or trace_data.get("cost_inr") != 0.12:
                raise AssertionError("conversation trace omitted model or cost ledger evidence")
            if not any(call.get("name") == "list_recent_orders" for call in trace_data.get("tool_calls", [])):
                raise AssertionError("conversation trace omitted its recorded tool invocation")
            _passed("masked conversation and trace evidence")

            esc_id = f"qa-escalation-{run_tag}"
            queue = await manager.get("/api/admin/v1/escalations", params={"state": "open"})
            _assert_response(queue, 200, "open escalation queue")
            if not any(row["esc_id"] == esc_id for row in queue.json()["escalations"]):
                raise AssertionError("seeded escalation is missing from the open queue")
            claim = await manager.post(f"/api/admin/v1/escalations/{esc_id}/claim", headers=manager_headers)
            _assert_response(claim, 200, "escalation claim")
            resolution = await manager.post(
                f"/api/admin/v1/escalations/{esc_id}/resolve",
                headers=manager_headers,
                json={"resolution_note": "Resolved in the disposable QA workflow."},
            )
            _assert_response(resolution, 200, "escalation resolution")
            _passed("escalation claim and documented resolution")

            versions = await manager.get("/api/admin/v1/knowledge/versions")
            _assert_response(versions, 200, "knowledge versions")
            invalid_draft = await manager.post(
                "/api/admin/v1/knowledge/policy/draft",
                headers=manager_headers,
                json={
                    "filename": "empty-qa-policy.md",
                    "clauses": [],
                    "confirmed_policy": {
                        "return_window_days": 30,
                        "excluded_categories": [],
                        "auto_refund_limit_inr": 2000,
                    },
                },
            )
            _assert_response(invalid_draft, 400, "empty policy draft validation")
            _passed("knowledge version read and invalid draft guard")

            owner = await httpx.AsyncClient(base_url=base_url, timeout=30.0).__aenter__()
            try:
                owner_login = await owner.post("/api/admin/v1/auth/login", json={
                    "email": owner_email,
                    "password": owner_password,
                    "tenant_id": new_tenant_id,
                })
                _assert_response(owner_login, 200, "new tenant owner login")
                cross_tenant_order = await owner.get("/api/admin/v1/orders/demo_order_00001")
                _assert_response(cross_tenant_order, 404, "cross-tenant order isolation")
                _passed("cross-tenant order isolation")
            finally:
                await owner.aclose()

            # Test the public chat transport after staff workflows. This is a
            # regression guard against trusting a caller-supplied customer_id.
            forged_identity = await manager.post(
                f"/chat/messages?tenant_id={TENANT_ID}",
                json={
                    "message": "Hello",
                    "tenant_id": TENANT_ID,
                    "customer_id": "demo_customer_00001",
                    "conv_id": f"qa-forged-identity-{run_tag}",
                },
            )
            _assert_response(forged_identity, 200, "unauthenticated chat with forged customer id")
            if forged_identity.json().get("auth_level") != "anonymous":
                raise AssertionError(
                    "unauthenticated customer_id upgraded the chat session to "
                    f"{forged_identity.json().get('auth_level')!r}"
                )
            _passed("customer identity requires a signed customer token")

            manager_session_id = manager.cookies.get("session_id")
            if not manager_session_id:
                raise AssertionError("manager login did not set a session cookie")
            revoked = await admin.delete(
                f"/api/admin/v1/auth/sessions/{manager_session_id}",
                headers=admin_headers,
            )
            _assert_response(revoked, 200, "manager session revocation")
            revoked_access = await manager.get("/api/admin/v1/settings")
            _assert_response(revoked_access, 401, "revoked session access denial")
            _passed("session revocation and access denial")

        async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as new_owner:
            owner_login = await new_owner.post("/api/admin/v1/auth/login", json={
                "email": owner_email,
                "password": owner_password,
                "tenant_id": new_tenant_id,
            })
            _assert_response(owner_login, 200, "tenant owner login")
            _passed("provisioned tenant owner can sign in")


def main() -> None:
    if os.getenv("APP_ENV", "").lower() != "test":
        raise SystemExit("Refusing to seed or exercise a non-test application environment.")
    run_tag = secrets.token_hex(4)
    admin_password = secrets.token_urlsafe(24)
    seed_counts = seed_demo_data(reset=True)
    _seed_qa_staff_and_workflows(run_tag, admin_password)
    print("SEEDED " + ", ".join(f"{key}={value}" for key, value in seed_counts.items()))
    asyncio.run(_run_workflows(
        run_tag,
        f"qa-admin-{run_tag}@example.com",
        admin_password,
    ))
    print("ALL LIVE QA WORKFLOWS PASSED")


if __name__ == "__main__":
    main()
