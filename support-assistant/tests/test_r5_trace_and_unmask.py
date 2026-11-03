"""
Test Suite: Spec 14.1 Trace Store, DPDP Masked Transcripts & Audited Manager Unmask.
Validates Requirement R5 and Sections 14.1, 14.3, 16.4.
"""

import unittest
import asyncio
from datetime import datetime, timezone, timedelta
import secrets
from pathlib import Path
import sys

# Ensure support-assistant is on sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import select
from fastapi import FastAPI
from fastapi.testclient import TestClient

from db.models import (
    Base, Tenant, StaffUser, StaffTenantMembership, StaffSession,
    ConversationSession, ConversationTurn, TurnRaw, AuditEvent
)
from services.dashboard_api.conversations import router as conv_router
from services.dashboard_api.auth import hash_password, mark_session_stepped_up, _step_up_tracker
from services.worker.turn_recorder import TurnRecorder


def run_async(coro):
    return asyncio.run(coro)


class TestR5TraceAndUnmask(unittest.TestCase):

    def setUp(self):
        _step_up_tracker.clear()
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
        self.session_maker = async_sessionmaker(self.engine, expire_on_commit=False)

        async def init_schema():
            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

        run_async(init_schema())

        self.app = FastAPI()
        self.app.include_router(conv_router)
        self.client = TestClient(self.app)

        from unittest.mock import patch
        from db import session as db_session

        @db_session.asynccontextmanager
        async def mock_get_session(tenant_id=None):
            async with self.session_maker() as sess:
                async with sess.begin():
                    yield sess

        self.patcher1 = patch("services.dashboard_api.conversations.get_async_session", side_effect=mock_get_session)
        self.patcher2 = patch("services.dashboard_api.dependencies.get_async_session", side_effect=mock_get_session)
        self.patcher3 = patch("services.worker.turn_recorder.get_async_session", side_effect=mock_get_session)
        self.patcher1.start()
        self.patcher2.start()
        self.patcher3.start()

    def tearDown(self):
        _step_up_tracker.clear()
        self.patcher1.stop()
        self.patcher2.stop()
        self.patcher3.stop()
        run_async(self.engine.dispose())

    def test_spec_14_1_columns_populated_on_turn_record(self):
        """Verify all Spec 14.1 trace columns are populated and PII is scrubbed."""
        async def run_test():
            # Seed tenant
            async with self.session_maker() as sess:
                async with sess.begin():
                    sess.add(Tenant(tenant_id="tenant_novaretail", name="NovaRetail"))

            turn_id = await TurnRecorder.record_turn(
                tenant_id="tenant_novaretail",
                conv_id="CONV-101",
                customer_id="CUST-77",
                user_input_raw="Hello, my phone is 9876543210 and email is cust@example.com",
                assistant_response_raw="I received your contact. How can I help with Pulse Buds 141?",
                intent="product_inquiry",
                latency_ms=185,
                tokens_prompt=120,
                tokens_completion=45,
                tool_calls=[{"name": "find_product", "arguments": {"name_text": "Pulse Buds"}}],
                grounding_score=0.98,
                channel="web",
                model_name="llama-3.1-8b-instant"
            )

            # Query database
            async with self.session_maker() as sess:
                turn = await sess.get(ConversationTurn, turn_id)
                self.assertIsNotNone(turn)
                # Verify all 14.1 columns
                self.assertEqual(turn.conv_id, "CONV-101")
                self.assertEqual(turn.tenant_id, "tenant_novaretail")
                self.assertEqual(turn.intent, "product_inquiry")
                self.assertEqual(turn.latency_ms, 185)
                self.assertEqual(turn.tokens_prompt, 120)
                self.assertEqual(turn.tokens_completion, 45)
                self.assertEqual(len(turn.tool_calls_json), 1)
                self.assertEqual(turn.grounding_score, 0.98)

                # Verify masking
                self.assertNotIn("9876543210", turn.user_input_masked)
                self.assertNotIn("cust@example.com", turn.user_input_masked)
                self.assertIn("******3210", turn.user_input_masked)

                # Verify raw store
                raw = await sess.get(TurnRaw, turn_id)
                self.assertIsNotNone(raw)
                self.assertIn("9876543210", raw.user_input_raw)
                self.assertIn("cust@example.com", raw.user_input_raw)

        run_async(run_test())

    def test_audited_transcript_and_trace_read(self):
        """Verify reading dialogue and trace creates audit_events records."""
        now = datetime.now(timezone.utc)
        import hashlib
        csrf = "csrf_test_99"
        csrf_hash = hashlib.sha256(csrf.encode()).hexdigest()

        async def seed():
            async with self.session_maker() as sess:
                async with sess.begin():
                    sess.add(Tenant(tenant_id="tenant_novaretail", name="NovaRetail"))
                    # Executive staff
                    sess.add(StaffUser(
                        staff_id="staff_exec",
                        email="exec@novaretail.com",
                        full_name="Exec User",
                        password_hash=hash_password("Pass1!"),
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
                    # Conversation and turn
                    sess.add(ConversationSession(
                        conv_id="CONV-AUDIT",
                        tenant_id="tenant_novaretail",
                        channel="web",
                        customer_id="CUST-1",
                    ))
                    sess.add(ConversationTurn(
                        turn_id="TURN-AUDIT-1",
                        conv_id="CONV-AUDIT",
                        tenant_id="tenant_novaretail",
                        step_index=0,
                        user_input_masked="What is return policy?",
                        assistant_response_masked="30 days return window.",
                        intent="policy_query",
                        latency_ms=120,
                        tokens_prompt=50,
                        tokens_completion=20,
                        tool_calls_json=[],
                        grounding_score=1.0,
                    ))

        run_async(seed())

        # 1. Read transcript
        res = self.client.get(
            "/api/admin/v1/conversations/CONV-AUDIT",
            cookies={"session_id": "sess_exec"}
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.json()["turns"]), 1)

        # 2. Read turn trace
        res_trace = self.client.get(
            "/api/admin/v1/conversations/CONV-AUDIT/turns/TURN-AUDIT-1/trace",
            cookies={"session_id": "sess_exec"}
        )
        self.assertEqual(res_trace.status_code, 200)
        self.assertEqual(res_trace.json()["intent"], "policy_query")

        # 3. Verify audit events logged in DB
        async def check_audits():
            async with self.session_maker() as sess:
                audits = (await sess.execute(select(AuditEvent))).scalars().all()
                actions = [a.action for a in audits]
                self.assertIn("view_conversation_transcript", actions)
                self.assertIn("view_turn_trace", actions)

        run_async(check_audits())

    def test_manager_only_step_up_unmask_workflow(self):
        """
        Verify Spec 14.3 / 16.4 DPDP Unmask Workflow:
        - Executive blocked (403 Forbidden).
        - Manager without step-up blocked (403 Step-up required).
        - Manager with step-up succeeds, receives unmasked text, and logs audit event with reason.
        """
        now = datetime.now(timezone.utc)
        import hashlib
        csrf = "csrf_unmask_token"
        csrf_hash = hashlib.sha256(csrf.encode()).hexdigest()

        async def seed():
            async with self.session_maker() as sess:
                async with sess.begin():
                    sess.add(Tenant(tenant_id="tenant_novaretail", name="NovaRetail"))
                    # Executive
                    sess.add(StaffUser(
                        staff_id="staff_exec",
                        email="exec@novaretail.com",
                        full_name="Exec User",
                        password_hash=hash_password("Pass1!"),
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
                        full_name="Manager User",
                        password_hash=hash_password("Pass1!"),
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

                    # Conversation with sensitive turn
                    sess.add(ConversationSession(
                        conv_id="CONV-SENSITIVE",
                        tenant_id="tenant_novaretail",
                        channel="web",
                        customer_id="CUST-42",
                    ))
                    sess.add(ConversationTurn(
                        turn_id="TURN-S-1",
                        conv_id="CONV-SENSITIVE",
                        tenant_id="tenant_novaretail",
                        step_index=0,
                        user_input_masked="My phone is ******3210",
                        assistant_response_masked="Verified.",
                    ))
                    sess.add(TurnRaw(
                        turn_id="TURN-S-1",
                        tenant_id="tenant_novaretail",
                        user_input_raw="My phone is 9876543210 and card is 4111-2222-3333-4444",
                        assistant_response_raw="Verified.",
                    ))

        run_async(seed())

        unmask_payload = {"reason": "Investigating unauthorized order claim #ORD-4491"}

        # 1. Executive attempts unmask -> 403 Forbidden (Only Managers can unmask PII)
        res_exec = self.client.post(
            "/api/admin/v1/conversations/CONV-SENSITIVE/unmask",
            json=unmask_payload,
            cookies={"session_id": "sess_exec"},
            headers={"X-CSRF-Token": csrf}
        )
        self.assertEqual(res_exec.status_code, 403)
        self.assertIn("Forbidden", res_exec.json()["detail"])

        # 2. Manager without active step-up -> 403 Step-Up Required
        res_mgr_no_step = self.client.post(
            "/api/admin/v1/conversations/CONV-SENSITIVE/unmask",
            json=unmask_payload,
            cookies={"session_id": "sess_mgr"},
            headers={"X-CSRF-Token": csrf}
        )
        self.assertEqual(res_mgr_no_step.status_code, 403)
        self.assertEqual(res_mgr_no_step.json()["detail"]["code"], "STEP_UP_REQUIRED")

        # 3. Manager WITH step-up -> 200 OK with unmasked data
        mark_session_stepped_up("sess_mgr", duration_minutes=5)
        res_mgr_step = self.client.post(
            "/api/admin/v1/conversations/CONV-SENSITIVE/unmask",
            json=unmask_payload,
            cookies={"session_id": "sess_mgr"},
            headers={"X-CSRF-Token": csrf}
        )
        self.assertEqual(res_mgr_step.status_code, 200)
        data = res_mgr_step.json()
        self.assertEqual(data["unmasked_by"], "staff_mgr")
        self.assertEqual(len(data["unmasked_turns"]), 1)
        self.assertIn("9876543210", data["unmasked_turns"][0]["user_raw"])
        self.assertIn("4111-2222-3333-4444", data["unmasked_turns"][0]["user_raw"])

        # 4. Verify immutable audit event recorded in DB
        async def verify_unmask_audit():
            async with self.session_maker() as sess:
                audit = (
                    await sess.execute(
                        select(AuditEvent).where(AuditEvent.action == "unmask_pii_transcript")
                    )
                ).scalars().first()
                self.assertIsNotNone(audit)
                self.assertEqual(audit.actor_id, "staff_mgr")
                self.assertEqual(audit.actor_role, "manager")
                self.assertIn("ORD-4491", audit.details.get("reason", ""))

        run_async(verify_unmask_audit())


if __name__ == "__main__":
    unittest.main()
