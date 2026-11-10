import asyncio
from datetime import datetime, timezone, timedelta
import hashlib
import os
import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from db.models import (
    Base, Tenant, KnowledgeVersion, KnowledgeChunk, KnowledgeVersionChunk,
    ProductModel, ProductSpecModel, IngestionJob, IngestionRun, IngestionItem,
    StaffUser, StaffTenantMembership, StaffSession,
)
from ingestion.manifest_engine import KnowledgeManifestEngine
from core.router.cache import CacheService
from adapters.postgres.vector_store import PostgresVectorStore
from ingestion.embedder import DeterministicLocalEmbedder, cosine_similarity
from ingestion.shop_catalog import MockShopCatalogConnector
from services.dashboard_api.auth import hash_password
from services.dashboard_api.knowledge import router as knowledge_router
from fastapi import FastAPI
from fastapi.testclient import TestClient


class TestRAGPipelineComprehensive(unittest.TestCase):
    """
    Comprehensive End-to-End Test Suite for RAG Ingestion Pipeline:
    1. Integration against MockShop (initial sync, 0-reembed resync, update, drop guard)
    2. Failure injection (API timeout, embedder mid-run failure, eval failure block)
    3. Retrieval evaluations (141 vs 131 lookalikes, typos, Tamil/Tanglish, cross-product isolation)
    4. Concurrency lock enforcement
    """

    def setUp(self):
        self.db_file = f"test_rag_comp_{datetime.now().timestamp()}.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.db_file}", echo=False)
        self.session_maker = async_sessionmaker(self.engine, expire_on_commit=False)
        self.cache_service = CacheService()
        self.vector_store = PostgresVectorStore()
        self.manifest_engine = KnowledgeManifestEngine(
            cache_service=self.cache_service,
            vector_store=self.vector_store,
        )

        async def init_schema():
            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

        asyncio.run(init_schema())

        # Seed default test tenant
        async def seed_tenant():
            async with self.session_maker() as session:
                async with session.begin():
                    t = Tenant(tenant_id="tenant_novaretail", name="NovaRetail")
                    session.add(t)

        asyncio.run(seed_tenant())

    def tearDown(self):
        try:
            if os.path.exists(self.db_file):
                os.remove(self.db_file)
        except OSError:
            pass

    # =========================================================================
    # 1. INTEGRATION AGAINST MOCKSHOP
    # =========================================================================

    def test_01_full_initial_sync_against_mockshop(self):
        """Initial full sync exports MockShop catalog, stages chunks, and extracts specs to relational DB."""
        async def run_test():
            connector = MockShopCatalogConnector()
            products = await connector.fetch_products()
            self.assertEqual(len(products), 4)

            async with self.session_maker() as session:
                async with session.begin():
                    job = await self.manifest_engine.run_catalog_ingestion_job(
                        tenant_id="tenant_novaretail",
                        staff_id="staff_mgr",
                        staff_role="manager",
                        session=session,
                        products_override=products,
                    )
                    self.assertEqual(job.status, "completed")
                    self.assertEqual(job.stats["added"], 4)
                    self.assertEqual(job.stats["unchanged"], 0)
                    self.assertEqual(job.stats["failed"], 0)
                    v_id = job.stats["version_id"]

                    # Check specs went to relational table
                    specs = (await session.execute(select(ProductSpecModel).where(
                        ProductSpecModel.version_id == v_id
                    ))).scalars().all()
                    self.assertTrue(len(specs) > 0)
                    driver_specs = [s for s in specs if s.spec_key in ("driver_size", "driver")]
                    self.assertTrue(len(driver_specs) >= 2)

                    # Check chunks are prefixed with product name
                    chunks = (await session.execute(select(KnowledgeChunk).where(
                        KnowledgeChunk.tenant_id == "tenant_novaretail"
                    ))).scalars().all()
                    self.assertTrue(len(chunks) >= 20)  # at least 5 chunks per product
                    for chunk in chunks:
                        # Live inventory, stock, and promotional offers must never be in vector chunks
                        self.assertNotIn("in stock", chunk.text.lower())
                        self.assertNotIn("special offer", chunk.text.lower())
                        if chunk.product_id != "P-GIFT500":
                            self.assertNotIn("₹", chunk.text)
                        # Chunks must be prefixed with product name
                        self.assertIn(" - ", chunk.text)

                    # Promote version to active
                    eval_res = await self.manifest_engine.run_version_eval("tenant_novaretail", v_id, session)
                    self.assertEqual(eval_res["status"], "passed")
                    promoted = await self.manifest_engine.promote_version(
                        tenant_id="tenant_novaretail",
                        version_id=v_id,
                        staff_id="staff_mgr",
                        staff_role="manager",
                        is_stepped_up=True,
                        session=session,
                    )
                    self.assertEqual(promoted.status, "active")

        asyncio.run(run_test())

    def test_02_resync_no_changes_zero_reembeds(self):
        """Second sync with identical catalog produces 0 re-embeds via chunk content-hashing."""
        async def run_test():
            connector = MockShopCatalogConnector()
            products = await connector.fetch_products()

            # Initial sync & promote
            async with self.session_maker() as session:
                async with session.begin():
                    job1 = await self.manifest_engine.run_catalog_ingestion_job(
                        tenant_id="tenant_novaretail",
                        staff_id="staff_mgr",
                        session=session,
                        products_override=products,
                    )
                    v1_id = job1.stats["version_id"]
                    await self.manifest_engine.run_version_eval("tenant_novaretail", v1_id, session)
                    await self.manifest_engine.promote_version(
                        tenant_id="tenant_novaretail",
                        version_id=v1_id,
                        staff_id="staff_mgr",
                        staff_role="manager",
                        is_stepped_up=True,
                        session=session,
                    )

            # Second sync with mock embedder
            mock_embed = AsyncMock()
            with patch("ingestion.manifest_engine._catalog_embedder") as mock_factory:
                embedder_mock = DeterministicLocalEmbedder()
                embedder_mock.embed_documents = mock_embed
                mock_factory.return_value = embedder_mock

                async with self.session_maker() as session:
                    async with session.begin():
                        job2 = await self.manifest_engine.run_catalog_ingestion_job(
                            tenant_id="tenant_novaretail",
                            staff_id="staff_mgr",
                            session=session,
                            products_override=products,
                        )
                        self.assertEqual(job2.stats["unchanged"], 4)
                        self.assertEqual(job2.stats["added"], 0)
                        self.assertEqual(job2.stats["updated"], 0)
                        self.assertEqual(job2.stats["failed"], 0)

            # Assert embedder was NEVER called
            self.assertEqual(mock_embed.call_count, 0)

        asyncio.run(run_test())

    def test_03_changed_product_reembeds_only_changed_product(self):
        """Modifying one product only re-embeds that single product while reusing others."""
        async def run_test():
            connector = MockShopCatalogConnector()
            products = await connector.fetch_products()

            # Initial sync & promote
            async with self.session_maker() as session:
                async with session.begin():
                    job1 = await self.manifest_engine.run_catalog_ingestion_job(
                        tenant_id="tenant_novaretail",
                        staff_id="staff_mgr",
                        session=session,
                        products_override=products,
                    )
                    v1_id = job1.stats["version_id"]
                    await self.manifest_engine.run_version_eval("tenant_novaretail", v1_id, session)
                    await self.manifest_engine.promote_version(
                        tenant_id="tenant_novaretail",
                        version_id=v1_id,
                        staff_id="staff_mgr",
                        staff_role="manager",
                        is_stepped_up=True,
                        session=session,
                    )

            # Modify P1041 description
            modified_products = [dict(p) for p in products]
            for p in modified_products:
                if p["product_id"] == "P1041":
                    p["description"] = "Updated description with enhanced BassBoost 2.0 audio architecture."

            mock_embed = AsyncMock(side_effect=DeterministicLocalEmbedder().embed_documents)
            with patch("ingestion.manifest_engine._catalog_embedder") as mock_factory:
                embedder_mock = DeterministicLocalEmbedder()
                embedder_mock.embed_documents = mock_embed
                mock_factory.return_value = embedder_mock

                async with self.session_maker() as session:
                    async with session.begin():
                        job2 = await self.manifest_engine.run_catalog_ingestion_job(
                            tenant_id="tenant_novaretail",
                            staff_id="staff_mgr",
                            session=session,
                            products_override=modified_products,
                        )
                        self.assertEqual(job2.stats["updated"], 1)
                        self.assertEqual(job2.stats["unchanged"], 3)
                        self.assertEqual(job2.stats["added"], 0)

            # Only 1 embed batch called (for P1041)
            self.assertEqual(mock_embed.call_count, 1)

        asyncio.run(run_test())

    def test_04_deletion_guard_aborts_excessive_drops(self):
        """Deletion guard aborts if active products drop by >50%, leaving active version intact."""
        async def run_test():
            connector = MockShopCatalogConnector()
            products = await connector.fetch_products()

            # Sync 4 products & promote
            async with self.session_maker() as session:
                async with session.begin():
                    job1 = await self.manifest_engine.run_catalog_ingestion_job(
                        tenant_id="tenant_novaretail",
                        staff_id="staff_mgr",
                        session=session,
                        products_override=products,
                    )
                    v1_id = job1.stats["version_id"]
                    await self.manifest_engine.run_version_eval("tenant_novaretail", v1_id, session)
                    await self.manifest_engine.promote_version(
                        tenant_id="tenant_novaretail",
                        version_id=v1_id,
                        staff_id="staff_mgr",
                        staff_role="manager",
                        is_stepped_up=True,
                        session=session,
                    )

            # Now simulate store returning only 1 product (75% drop)
            dropped_catalog = [products[0]]
            async with self.session_maker() as session:
                async with session.begin():
                    job2 = await self.manifest_engine.run_catalog_ingestion_job(
                        tenant_id="tenant_novaretail",
                        staff_id="staff_mgr",
                        session=session,
                        products_override=dropped_catalog,
                    )
                    self.assertEqual(job2.status, "failed")
                    self.assertIn("aborted", job2.error_message)

                    # Verify active version was NOT changed
                    tenant = await session.get(Tenant, "tenant_novaretail")
                    self.assertEqual(tenant.active_product_version, v1_id)

        asyncio.run(run_test())

    # =========================================================================
    # 2. FAILURE INJECTION TESTS
    # =========================================================================

    def test_05_failure_injection_stores_api_down(self):
        """When Stores API times out, sync fails safely without altering active knowledge."""
        async def run_test():
            with patch("ingestion.shop_catalog.get_catalog_connector") as mock_conn_factory:
                mock_conn = AsyncMock()
                mock_conn.fetch_products.side_effect = RuntimeError("504 Gateway Timeout from Stores API")
                mock_conn_factory.return_value = mock_conn

                async with self.session_maker() as session:
                    async with session.begin():
                        job = await self.manifest_engine.run_catalog_ingestion_job(
                            tenant_id="tenant_novaretail",
                            staff_id="staff_mgr",
                            session=session,
                            products_override=None,
                        )
                        self.assertEqual(job.status, "failed")
                        self.assertIn("Stores API", job.error_message)

                        run = await session.scalar(select(IngestionRun).where(IngestionRun.job_id == job.job_id))
                        self.assertEqual(run.status, "failed")

        asyncio.run(run_test())

    def test_06_failure_injection_mid_run_embedding_failure(self):
        """When embedder fails on one item, other items are staged and dead letter is recorded."""
        async def run_test():
            products = [
                {"product_id": "P_GOOD_1", "name": "Good Product 1", "category": "c", "description": "Valid product 1"},
                {"product_id": "P_BAD_2", "name": "Bad Product 2", "category": "c", "description": "Fails embedding"},
            ]

            real_embedder = DeterministicLocalEmbedder()
            async def failing_embed(docs):
                if any("Bad Product 2" in d for d in docs):
                    raise RuntimeError("NIM Embedder API 500: Out of memory on batch")
                return await real_embedder.embed_documents(docs)

            with patch("ingestion.manifest_engine._catalog_embedder") as mock_embed_factory:
                mock_emb = DeterministicLocalEmbedder()
                mock_emb.embed_documents = failing_embed
                mock_embed_factory.return_value = mock_emb

                async with self.session_maker() as session:
                    async with session.begin():
                        job = await self.manifest_engine.run_catalog_ingestion_job(
                            tenant_id="tenant_novaretail",
                            staff_id="staff_mgr",
                            session=session,
                            products_override=products,
                        )
                        # Job completes with partial staging
                        self.assertEqual(job.status, "completed")
                        self.assertEqual(job.stats["failed"], 1)
                        self.assertEqual(job.stats["products_processed"], 1)

                        # Assert dead letter logged
                        run = await session.scalar(select(IngestionRun).where(IngestionRun.job_id == job.job_id))
                        dead_letters = (await session.execute(select(IngestionItem).where(
                            IngestionItem.run_id == run.run_id
                        ))).scalars().all()
                        self.assertEqual(len(dead_letters), 1)
                        self.assertEqual(dead_letters[0].product_id, "P_BAD_2")
                        self.assertEqual(dead_letters[0].status, "dead_letter")

        asyncio.run(run_test())

    # =========================================================================
    # 3. RETRIEVAL EVALUATIONS
    # =========================================================================

    def test_07_retrieval_eval_lookalikes_141_vs_131(self):
        """Pulse Buds 141 and 131 look-alike queries match their respective products."""
        embedder = DeterministicLocalEmbedder()

        doc_141 = "Pulse Buds 141 - Wireless earbuds with 42 hours playback and BEAST mode 40ms low latency."
        doc_131 = "Pulse Buds 131 - Wireless earbuds with 60 hours playback and 13mm drivers."

        vec_141 = asyncio.run(embedder.embed_documents([doc_141]))[0]
        vec_131 = asyncio.run(embedder.embed_documents([doc_131]))[0]

        query_141 = asyncio.run(embedder.embed_query("Pulse Buds 141 low latency beast mode"))
        query_131 = asyncio.run(embedder.embed_query("Pulse Buds 131 driver size"))

        sim_141_to_141 = cosine_similarity(vec_141, query_141)
        sim_131_to_141 = cosine_similarity(vec_131, query_141)
        self.assertGreater(sim_141_to_141, sim_131_to_141)

        sim_131_to_131 = cosine_similarity(vec_131, query_131)
        sim_141_to_131 = cosine_similarity(vec_141, query_131)
        self.assertGreater(sim_131_to_131, sim_141_to_131)

    def test_08_retrieval_eval_typos_and_tamil_tanglish(self):
        """Embedder matches typos, pure Tamil script, and Tanglish queries."""
        embedder = DeterministicLocalEmbedder()

        doc_battery = "Pulse Buds 141 - Battery life: Provides up to 42 hours of total playback time with ASAP charge."
        doc_vec = asyncio.run(embedder.embed_documents([doc_battery]))[0]

        unrelated_doc = "Google Play ₹500 Gift Card - Digital code delivered via SMS."
        unrelated_vec = asyncio.run(embedder.embed_documents([unrelated_doc]))[0]

        # 1. Typos: "pluse budz 141 battry backup" matches 141 battery doc and beats unrelated
        query_typo = asyncio.run(embedder.embed_query("pulse budz 141 battry backup"))
        sim_typo = cosine_similarity(doc_vec, query_typo)
        sim_unrelated_typo = cosine_similarity(unrelated_vec, query_typo)
        self.assertGreater(sim_typo, 0.15)
        self.assertGreater(sim_typo, sim_unrelated_typo + 0.10)

        # 2. Tamil script: "Pulse Buds 141 பேட்டரி எவ்வளவு நேரம் வரும்?"
        query_tamil = asyncio.run(embedder.embed_query("Pulse Buds 141 பேட்டரி எவ்வளவு நேரம் வரும்?"))
        sim_tamil = cosine_similarity(doc_vec, query_tamil)
        sim_unrelated_tamil = cosine_similarity(unrelated_vec, query_tamil)
        self.assertGreater(sim_tamil, 0.20)
        self.assertGreater(sim_tamil, sim_unrelated_tamil + 0.10)

        # 3. Tanglish: "Pulse Buds 141 battery backup evvalavu neram"
        query_tanglish = asyncio.run(embedder.embed_query("Pulse Buds 141 battery backup evvalavu neram"))
        sim_tanglish = cosine_similarity(doc_vec, query_tanglish)
        sim_unrelated_tanglish = cosine_similarity(unrelated_vec, query_tanglish)
        self.assertGreater(sim_tanglish, 0.25)
        self.assertGreater(sim_tanglish, sim_unrelated_tanglish + 0.15)

    def test_09_strict_cross_product_chunk_isolation(self):
        """Querying product A with product_id filter must NEVER return chunks of product B."""
        async def run_test():
            connector = MockShopCatalogConnector()
            products = await connector.fetch_products()

            async with self.session_maker() as session:
                async with session.begin():
                    job = await self.manifest_engine.run_catalog_ingestion_job(
                        tenant_id="tenant_novaretail",
                        staff_id="staff_mgr",
                        session=session,
                        products_override=products,
                    )
                    v_id = job.stats["version_id"]

                    # Filter by product_id = 'P1041'
                    stmt = select(KnowledgeChunk).join(
                        KnowledgeVersionChunk, KnowledgeVersionChunk.chunk_id == KnowledgeChunk.chunk_id
                    ).where(
                        KnowledgeVersionChunk.version_id == v_id,
                        KnowledgeChunk.product_id == "P1041"
                    )
                    chunks = (await session.execute(stmt)).scalars().all()
                    self.assertTrue(len(chunks) > 0)
                    for c in chunks:
                        self.assertEqual(c.product_id, "P1041")
                        self.assertNotIn("Pulse Buds 131", c.text)

        asyncio.run(run_test())

    # =========================================================================
    # 4. CONCURRENCY TESTS
    # =========================================================================

    def test_10_concurrency_double_click_starts_only_one_job(self):
        """Two simultaneous sync requests start only 1 job; the second returns 409 Conflict."""
        app = FastAPI()
        app.include_router(knowledge_router)
        client = TestClient(app)

        # Seed staff
        async def seed_staff():
            async with self.session_maker() as session:
                async with session.begin():
                    u = StaffUser(staff_id="adm_concur", email="adm_concur@novaretail.com", full_name="A", password_hash=hash_password("pw"))
                    m = StaffTenantMembership(staff_id="adm_concur", tenant_id="tenant_novaretail", role="admin")
                    session.add_all([u, m])
                    csrf_hash = hashlib.sha256("csrf".encode()).hexdigest()
                    s = StaffSession(session_id="sess_concur", staff_id="adm_concur", tenant_id="tenant_novaretail", active_tenant_id="tenant_novaretail", expires_at=datetime.now(timezone.utc) + timedelta(hours=1), csrf_hash=csrf_hash)
                    session.add(s)

        asyncio.run(seed_staff())

        from db import session as db_session
        @db_session.asynccontextmanager
        async def mock_session(tenant_id=None):
            async with self.session_maker() as sess:
                async with sess.begin():
                    yield sess

        with patch("services.dashboard_api.knowledge.get_async_session", side_effect=mock_session), \
             patch("services.dashboard_api.dependencies.get_async_session", side_effect=mock_session), \
             patch("services.dashboard_api.knowledge._run_catalog_ingestion"):

            res1 = client.post("/api/admin/v1/knowledge/catalog/sync", headers={"Authorization": "Bearer sess_concur", "X-CSRF-Token": "csrf"})
            self.assertEqual(res1.status_code, 200)

            res2 = client.post("/api/admin/v1/knowledge/catalog/sync", headers={"Authorization": "Bearer sess_concur", "X-CSRF-Token": "csrf"})
            self.assertEqual(res2.status_code, 409)
            self.assertIn("already running", res2.json()["detail"])


if __name__ == "__main__":
    unittest.main()
