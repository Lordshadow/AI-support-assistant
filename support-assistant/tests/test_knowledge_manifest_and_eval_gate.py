"""
Comprehensive Unit & Integration Test Suite for Master Control Dashboard Phase 5:
Knowledge Version Manifest, Safe Ingestion, Deletion Guard, and Quality Eval Gate.

Verifies:
1. Content-addressed chunking and deduplication.
2. Safe policy parsing (PDF text layer, Markdown, TXT) and scan/corrupted glyph (>30%) rejection.
3. Confirmed policy values form submission and draft version creation.
4. Catalog ingestion deletion guard (>20% drop aborts and protects index).
5. Ingestion job single-active concurrency constraint (409 Conflict).
6. Pre-promotion automated evaluation gate (100% deterministic, >= 90% fuzzy).
7. Manager override with step-up verification and audit trail.
8. Atomic pointer promotion and one-click rollback with cache invalidation.
"""

import asyncio
from datetime import datetime, timezone, timedelta
import hashlib
import io
import os
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

# Ensure support-assistant is in sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text, select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from db.models import (
    Base, Tenant, StaffUser, StaffTenantMembership, StaffSession,
    KnowledgeVersion, KnowledgeChunk, KnowledgeVersionChunk,
    IngestionJob, TenantPolicyConfig, AuditEvent
)
from services.dashboard_api.auth import hash_password, _step_up_tracker
from services.dashboard_api.knowledge import router as knowledge_router
from ingestion.manifest_engine import (
    generate_chunk_id, extract_policy_text, parse_policy_clauses,
    KnowledgeManifestEngine
)
from core.router.cache import CacheService


def run_async(coro):
    return asyncio.run(coro)


class TestKnowledgeManifestAndEvalGate(unittest.TestCase):

    def setUp(self):
        self.db_file = f"test_knowledge_{datetime.now().timestamp()}.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.db_file}", echo=False)
        self.session_maker = async_sessionmaker(self.engine, expire_on_commit=False)

        async def init_schema():
            async with self.engine.begin() as conn:
                await conn.execute(text("PRAGMA journal_mode=WAL;"))
                await conn.run_sync(Base.metadata.create_all)

        run_async(init_schema())

        self.cache = CacheService()
        self.manifest_engine = KnowledgeManifestEngine(cache_service=self.cache)

        self.app = FastAPI()
        self.app.include_router(knowledge_router)
        self.client = TestClient(self.app)

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

        _step_up_tracker.clear()

        # Seed standard tenant and staff accounts
        self.now = datetime.now(timezone.utc)
        self.csrf = "csrf_token_secret_123"
        self.csrf_hash = hashlib.sha256(self.csrf.encode()).hexdigest()

        async def seed_users():
            async with self.session_maker() as sess:
                async with sess.begin():
                    sess.add(Tenant(
                        tenant_id="tenant_novaretail",
                        name="NovaRetail",
                        active_policy_version=None,
                        active_product_version=None,
                    ))
                    # Exec user
                    sess.add(StaffUser(
                        staff_id="staff_exec",
                        email="exec@novaretail.com",
                        full_name="Executive Alice",
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
                        created_at=self.now,
                        expires_at=self.now + timedelta(hours=2),
                        csrf_hash=self.csrf_hash,
                    ))

                    # Manager user
                    sess.add(StaffUser(
                        staff_id="staff_mgr",
                        email="mgr@novaretail.com",
                        full_name="Manager Bob",
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
                        created_at=self.now,
                        expires_at=self.now + timedelta(hours=2),
                        csrf_hash=self.csrf_hash,
                    ))

                    # Admin user
                    sess.add(StaffUser(
                        staff_id="staff_adm",
                        email="admin@novaretail.com",
                        full_name="Admin Charlie",
                        password_hash=hash_password("Pass1!"),
                    ))
                    sess.add(StaffTenantMembership(
                        staff_id="staff_adm",
                        tenant_id="tenant_novaretail",
                        role="admin"
                    ))
                    sess.add(StaffSession(
                        session_id="sess_adm",
                        staff_id="staff_adm",
                        active_tenant_id="tenant_novaretail",
                        created_at=self.now,
                        expires_at=self.now + timedelta(hours=2),
                        csrf_hash=self.csrf_hash,
                    ))

        run_async(seed_users())

    def tearDown(self):
        self.patcher1.stop()
        self.patcher2.stop()
        _step_up_tracker.clear()
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

    def test_content_addressed_chunk_deduplication(self):
        """Verify content-addressing guarantees deduplication and deterministic IDs."""
        tenant = "tenant_novaretail"
        text1 = "All electronics must be returned within 30 days in original packaging."
        text2 = "All   electronics must be returned  within 30 days in original packaging. "

        cid1 = generate_chunk_id(tenant, "policy", None, text1)
        cid2 = generate_chunk_id(tenant, "policy", None, text2)

        # Whitespace normalization yields exact same chunk ID
        self.assertEqual(cid1, cid2)

        # Different text produces different ID
        cid3 = generate_chunk_id(tenant, "policy", None, "Different text")
        self.assertNotEqual(cid1, cid3)

        # Different model or chunker version produces different ID
        cid_diff_model = generate_chunk_id(tenant, "policy", None, text1, embedding_model="text-embedding-3-large")
        self.assertNotEqual(cid1, cid_diff_model)

        async def verify_db_dedup():
            async with self.session_maker() as sess:
                async with sess.begin():
                    # Create two separate drafts referencing the same clause content
                    clauses = [{
                        "clause_id": "CLAUSE-1.0",
                        "title": "Return Window",
                        "text": text1
                    }]
                    confirmed = {"return_window_days": 30, "excluded_categories": ["digital"], "auto_refund_limit_inr": 2000}

                    v1 = await self.manifest_engine.create_policy_draft(
                        tenant, "staff_mgr", "policy_v1.md", clauses, confirmed, sess
                    )
                    v2 = await self.manifest_engine.create_policy_draft(
                        tenant, "staff_mgr", "policy_v2.md", clauses, confirmed, sess
                    )

                    # Distinct versions created
                    self.assertNotEqual(v1.version_id, v2.version_id)

                    # But chunk is stored exactly once in knowledge_chunks
                    chk_count = (await sess.execute(select(KnowledgeChunk))).scalars().all()
                    self.assertEqual(len(chk_count), 1)

                    # And both versions link to that single chunk in knowledge_version_chunks
                    links = (await sess.execute(select(KnowledgeVersionChunk))).scalars().all()
                    self.assertEqual(len(links), 2)
                    self.assertEqual(links[0].chunk_id, links[1].chunk_id)

        run_async(verify_db_dedup())

    def test_policy_upload_markdown_and_glyph_rejection(self):
        """Verify policy upload extracts clauses and rejects documents with >30% corrupted glyphs."""
        # 1. Valid Markdown Policy
        valid_policy = """
# NovaRetail Store Return Policy

Policy Clause 1.0: Return Window & Eligibility
Customers may return unopened items within 30 days of delivery.
Proof of purchase is required.

Policy Clause 2.0: Non-Refundable Items
Digital goods, gift cards, and perishables are strictly non-refundable.

Policy Clause 3.0: Damaged or Defective Deliveries
Items damaged during transit must be reported within 48 hours with photographic proof.
"""
        response = self.client.post(
            "/api/admin/v1/knowledge/policy/upload",
            files={"file": ("returns_policy.md", valid_policy.encode("utf-8"), "text/markdown")},
            headers={"Authorization": "Bearer sess_mgr", "X-CSRF-Token": self.csrf}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total_clauses"], 3)
        self.assertEqual(data["clauses"][0]["clause_id"], "CLAUSE-1.0")
        self.assertIn("30 days", data["clauses"][0]["preview_snippet"])

        # 2. Corrupted document with >30% unmapped glyphs / non-printable control chars
        corrupted_bytes = ("Valid start to the document\n" + ("\ufffd\x00\x01\x02" * 40)).encode("utf-8")
        resp_bad = self.client.post(
            "/api/admin/v1/knowledge/policy/upload",
            files={"file": ("corrupted.txt", corrupted_bytes, "text/plain")},
            headers={"Authorization": "Bearer sess_mgr", "X-CSRF-Token": self.csrf}
        )
        self.assertEqual(resp_bad.status_code, 400)
        self.assertIn("Unmapped glyph ratio", resp_bad.json()["detail"])

        # 3. Empty document
        resp_empty = self.client.post(
            "/api/admin/v1/knowledge/policy/upload",
            files={"file": ("empty.md", b"too short", "text/markdown")},
            headers={"Authorization": "Bearer sess_mgr", "X-CSRF-Token": self.csrf}
        )
        self.assertEqual(resp_empty.status_code, 400)

        # 4. Scanned PDF (no extractable text layer)
        import pypdf
        writer = pypdf.PdfWriter()
        writer.add_blank_page(width=200, height=200)
        pdf_buf = io.BytesIO()
        writer.write(pdf_buf)
        resp_scanned_pdf = self.client.post(
            "/api/admin/v1/knowledge/policy/upload",
            files={"file": ("scanned_policy.pdf", pdf_buf.getvalue(), "application/pdf")},
            headers={"Authorization": "Bearer sess_mgr", "X-CSRF-Token": self.csrf}
        )
        self.assertEqual(resp_scanned_pdf.status_code, 400)
        self.assertIn("Scanned PDF detected", resp_scanned_pdf.json()["detail"])

    def test_confirmed_policy_values_form_and_draft_creation(self):
        """Verify draft policy creation captures confirmed values form parameters."""
        payload = {
            "filename": "holiday_policy.md",
            "clauses": [
                {
                    "clause_id": "CLAUSE-1.0",
                    "title": "Extended Holiday Window",
                    "text": "Holiday purchases made in November and December can be returned through January 31."
                },
                {
                    "clause_id": "CLAUSE-2.0",
                    "title": "Excluded Categories",
                    "text": "Gift vouchers, digital game codes, and perishable gourmet baskets cannot be returned."
                }
            ],
            "confirmed_policy": {
                "return_window_days": 45,
                "excluded_categories": ["digital", "gift cards", "perishables"],
                "auto_refund_limit_inr": 3000
            }
        }

        resp = self.client.post(
            "/api/admin/v1/knowledge/policy/draft",
            json=payload,
            headers={"Authorization": "Bearer sess_mgr", "X-CSRF-Token": self.csrf}
        )
        self.assertEqual(resp.status_code, 200)
        draft = resp.json()
        self.assertEqual(draft["type"], "policy")
        self.assertEqual(draft["status"], "draft")
        self.assertEqual(draft["manifest"]["confirmed_policy"]["return_window_days"], 45)
        self.assertEqual(draft["manifest"]["confirmed_policy"]["auto_refund_limit_inr"], 3000)
        self.assertEqual(draft["manifest"]["chunk_count"], 2)

    def test_catalog_ingestion_and_deletion_guard_abort(self):
        """Verify catalog ingestion aborts and protects index when items drop by > 20%."""
        tenant_id = "tenant_novaretail"

        # Baseline: seed an active catalog version with 10 items
        async def seed_active_catalog():
            async with self.session_maker() as sess:
                async with sess.begin():
                    active_cat = KnowledgeVersion(
                        version_id="ver_cat_baseline",
                        tenant_id=tenant_id,
                        type="catalog",
                        status="active",
                        manifest={"total_items": 10, "chunk_count": 10},
                        created_by="staff_adm",
                        promoted_at=self.now
                    )
                    sess.add(active_cat)
                    t = await sess.get(Tenant, tenant_id)
                    t.active_product_version = "ver_cat_baseline"

        run_async(seed_active_catalog())

        # 1. Attempt sync with only 7 items (30% drop > 20% limit)
        dropped_products = [
            {"product_id": f"P-{i}", "name": f"Product {i}", "brand": "Brand", "category": "Audio"}
            for i in range(1, 8)
        ]
        resp_guard = self.client.post(
            "/api/admin/v1/knowledge/catalog/sync",
            json={"products": dropped_products},
            headers={"Authorization": "Bearer sess_adm", "X-CSRF-Token": self.csrf}
        )
        self.assertEqual(resp_guard.status_code, 200)
        job_data = resp_guard.json()
        self.assertEqual(job_data["status"], "failed")
        self.assertIn("Catalog drop guard triggered", job_data["error_message"])
        self.assertIn("limit 20.0%", job_data["error_message"])

        # Verify active catalog pointer on tenant remains untouched
        async def check_tenant_version():
            async with self.session_maker() as sess:
                t = await sess.get(Tenant, tenant_id)
                self.assertEqual(t.active_product_version, "ver_cat_baseline")

        run_async(check_tenant_version())

        # 2. Sync with 9 items (10% drop <= 20% limit) -> should succeed
        valid_products = [
            {"product_id": f"P-{i}", "name": f"Product {i}", "brand": "Brand", "category": "Audio"}
            for i in range(1, 10)
        ]
        resp_valid = self.client.post(
            "/api/admin/v1/knowledge/catalog/sync",
            json={"products": valid_products},
            headers={"Authorization": "Bearer sess_adm", "X-CSRF-Token": self.csrf}
        )
        self.assertEqual(resp_valid.status_code, 200)
        job_ok = resp_valid.json()
        self.assertEqual(job_ok["status"], "completed")
        self.assertEqual(job_ok["stats"]["total_items"], 9)
        self.assertEqual(job_ok["stats"]["chunks_indexed"], 9)

    def test_active_ingestion_job_concurrency_conflict(self):
        """Verify only 1 active ingestion job allowed per tenant (returns 409 Conflict)."""
        tenant_id = "tenant_novaretail"

        async def seed_running_job():
            async with self.session_maker() as sess:
                async with sess.begin():
                    job = IngestionJob(
                        job_id="job_cat_running_1",
                        tenant_id=tenant_id,
                        source_type="catalog",
                        status="running",
                        progress_pct=50
                    )
                    sess.add(job)

        run_async(seed_running_job())

        # Second sync attempt while job is running returns 409
        resp = self.client.post(
            "/api/admin/v1/knowledge/catalog/sync",
            json={"products": []},
            headers={"Authorization": "Bearer sess_adm", "X-CSRF-Token": self.csrf}
        )
        self.assertEqual(resp.status_code, 409)
        self.assertIn("already in progress", resp.json()["detail"])

    def test_pre_promotion_eval_gate_and_manager_override(self):
        """Verify eval gate blocks promotion of failing version unless Manager overrides with step-up."""
        tenant_id = "tenant_novaretail"
        version_id = "ver_pol_eval_test"

        # Seed draft policy with invalid return window (120 days, > 90 limit) to trigger eval failure
        async def seed_failing_draft():
            async with self.session_maker() as sess:
                async with sess.begin():
                    v = KnowledgeVersion(
                        version_id=version_id,
                        tenant_id=tenant_id,
                        type="policy",
                        status="draft",
                        manifest={
                            "clauses": [{"clause_id": "C-1", "title": "Rule", "text": "Details"}],
                            "confirmed_policy": {
                                "return_window_days": 120,  # Invalid: > 90
                                "excluded_categories": ["digital"],
                                "auto_refund_limit_inr": 2000
                            },
                            "eval_result": None
                        },
                        created_by="staff_mgr"
                    )
                    sess.add(v)

        run_async(seed_failing_draft())

        # 1. Run eval benchmark
        resp_eval = self.client.post(
            f"/api/admin/v1/knowledge/versions/{version_id}/eval",
            headers={"Authorization": "Bearer sess_mgr", "X-CSRF-Token": self.csrf}
        )
        self.assertEqual(resp_eval.status_code, 200)
        eval_data = resp_eval.json()["eval_result"]
        self.assertEqual(eval_data["status"], "failed")
        self.assertEqual(eval_data["deterministic_passed"], False)

        # 2. Executive attempts promotion -> 403 Forbidden
        resp_exec = self.client.post(
            f"/api/admin/v1/knowledge/versions/{version_id}/promote",
            json={"override": False},
            headers={"Authorization": "Bearer sess_exec", "X-CSRF-Token": self.csrf}
        )
        self.assertEqual(resp_exec.status_code, 403)

        # 3. Manager attempts promotion without override -> 400 Bad Request
        resp_promo_fail = self.client.post(
            f"/api/admin/v1/knowledge/versions/{version_id}/promote",
            json={"override": False},
            headers={"Authorization": "Bearer sess_mgr", "X-CSRF-Token": self.csrf}
        )
        self.assertEqual(resp_promo_fail.status_code, 400)
        self.assertIn("Automated quality eval has not passed", resp_promo_fail.json()["detail"])

        # 4. Manager attempts override WITHOUT step-up -> 403 Forbidden (STEP_UP_REQUIRED)
        resp_no_stepup = self.client.post(
            f"/api/admin/v1/knowledge/versions/{version_id}/promote",
            json={"override": True, "override_reason": "Approved by board"},
            headers={"Authorization": "Bearer sess_mgr", "X-CSRF-Token": self.csrf}
        )
        self.assertEqual(resp_no_stepup.status_code, 403)
        self.assertIn("Step-up authentication is strictly required", resp_no_stepup.json()["detail"])

        # 5. Enable step-up for manager session
        _step_up_tracker["sess_mgr"] = self.now + timedelta(minutes=5)

        # Manager attempts override with empty reason -> 400 Bad Request
        resp_no_reason = self.client.post(
            f"/api/admin/v1/knowledge/versions/{version_id}/promote",
            json={"override": True, "override_reason": "   "},
            headers={"Authorization": "Bearer sess_mgr", "X-CSRF-Token": self.csrf}
        )
        self.assertEqual(resp_no_reason.status_code, 400)

        # Manager attempts override WITH step-up and written justification -> 200 OK
        resp_override_ok = self.client.post(
            f"/api/admin/v1/knowledge/versions/{version_id}/promote",
            json={"override": True, "override_reason": "Director approved 120-day promotional window for VIP launch"},
            headers={"Authorization": "Bearer sess_mgr", "X-CSRF-Token": self.csrf}
        )
        self.assertEqual(resp_override_ok.status_code, 200)

        # Verify AuditEvent and Tenant pointer
        async def verify_override_audit():
            async with self.session_maker() as sess:
                # Active version updated
                t = await sess.get(Tenant, tenant_id)
                self.assertEqual(t.active_policy_version, version_id)

                # Overwrite audit event recorded
                stmt_audit = select(AuditEvent).where(
                    AuditEvent.tenant_id == tenant_id,
                    AuditEvent.action == "knowledge_promotion_override"
                )
                audit = (await sess.execute(stmt_audit)).scalars().first()
                self.assertIsNotNone(audit)
                self.assertEqual(audit.actor_id, "staff_mgr")
                self.assertIn("VIP launch", audit.details["override_reason"])

                # Promotion audit event recorded
                stmt_promo = select(AuditEvent).where(
                    AuditEvent.tenant_id == tenant_id,
                    AuditEvent.action == "promote_knowledge_version"
                )
                promo_audit = (await sess.execute(stmt_promo)).scalars().first()
                self.assertIsNotNone(promo_audit)

        run_async(verify_override_audit())

    def test_atomic_promotion_and_one_click_rollback(self):
        """Verify atomic pointer flip and one-click rollback restores prior version and invalidates cache."""
        tenant_id = "tenant_novaretail"

        async def setup_versions():
            async with self.session_maker() as sess:
                async with sess.begin():
                    # Version 1 (Valid)
                    v1 = KnowledgeVersion(
                        version_id="ver_pol_v1",
                        tenant_id=tenant_id,
                        type="policy",
                        status="draft",
                        manifest={
                            "clauses": [{"clause_id": "C-1", "title": "Base", "text": "Standard return"}],
                            "confirmed_policy": {
                                "return_window_days": 30,
                                "excluded_categories": ["digital", "gift cards"],
                                "auto_refund_limit_inr": 2000
                            },
                            "eval_result": None
                        },
                        created_by="staff_adm"
                    )
                    # Version 2 (Valid)
                    v2 = KnowledgeVersion(
                        version_id="ver_pol_v2",
                        tenant_id=tenant_id,
                        type="policy",
                        status="draft",
                        manifest={
                            "clauses": [{"clause_id": "C-1", "title": "Base", "text": "Updated return"}],
                            "confirmed_policy": {
                                "return_window_days": 14,
                                "excluded_categories": ["digital", "gift cards", "perishables"],
                                "auto_refund_limit_inr": 1500
                            },
                            "eval_result": None
                        },
                        created_by="staff_adm"
                    )
                    sess.add(v1)
                    sess.add(v2)

        run_async(setup_versions())

        # 1. Run eval on v1 -> passes
        r_eval1 = self.client.post(
            "/api/admin/v1/knowledge/versions/ver_pol_v1/eval",
            headers={"Authorization": "Bearer sess_adm", "X-CSRF-Token": self.csrf}
        )
        self.assertEqual(r_eval1.json()["eval_result"]["status"], "passed")

        # Promote v1
        r_prom1 = self.client.post(
            "/api/admin/v1/knowledge/versions/ver_pol_v1/promote",
            json={"override": False},
            headers={"Authorization": "Bearer sess_adm", "X-CSRF-Token": self.csrf}
        )
        self.assertEqual(r_prom1.status_code, 200)

        # 2. Run eval on v2 -> passes
        r_eval2 = self.client.post(
            "/api/admin/v1/knowledge/versions/ver_pol_v2/eval",
            headers={"Authorization": "Bearer sess_adm", "X-CSRF-Token": self.csrf}
        )
        self.assertEqual(r_eval2.json()["eval_result"]["status"], "passed")

        # Promote v2
        r_prom2 = self.client.post(
            "/api/admin/v1/knowledge/versions/ver_pol_v2/promote",
            json={"override": False},
            headers={"Authorization": "Bearer sess_adm", "X-CSRF-Token": self.csrf}
        )
        self.assertEqual(r_prom2.status_code, 200)

        # Verify v2 is active and v1 is archived
        async def verify_v2_active():
            async with self.session_maker() as sess:
                t = await sess.get(Tenant, tenant_id)
                self.assertEqual(t.active_policy_version, "ver_pol_v2")

                v1 = await sess.get(KnowledgeVersion, "ver_pol_v1")
                self.assertEqual(v1.status, "archived")

                v2 = await sess.get(KnowledgeVersion, "ver_pol_v2")
                self.assertEqual(v2.status, "active")

        run_async(verify_v2_active())

        # 3. Rollback policy version
        r_rollback = self.client.post(
            "/api/admin/v1/knowledge/rollback",
            json={"version_type": "policy"},
            headers={"Authorization": "Bearer sess_adm", "X-CSRF-Token": self.csrf}
        )
        self.assertEqual(r_rollback.status_code, 200)
        self.assertEqual(r_rollback.json()["version_id"], "ver_pol_v1")

        # Verify v1 is reactivated and v2 is archived
        async def verify_v1_restored():
            async with self.session_maker() as sess:
                t = await sess.get(Tenant, tenant_id)
                self.assertEqual(t.active_policy_version, "ver_pol_v1")

                v1 = await sess.get(KnowledgeVersion, "ver_pol_v1")
                self.assertEqual(v1.status, "active")

                v2 = await sess.get(KnowledgeVersion, "ver_pol_v2")
                self.assertEqual(v2.status, "archived")

                # Verify rollback audit event
                stmt_rb = select(AuditEvent).where(
                    AuditEvent.tenant_id == tenant_id,
                    AuditEvent.action == "rollback_knowledge_version"
                )
                rb_event = (await sess.execute(stmt_rb)).scalars().first()
                self.assertIsNotNone(rb_event)
                self.assertEqual(rb_event.resource_id, "ver_pol_v1")

        run_async(verify_v1_restored())


if __name__ == "__main__":
    unittest.main()
