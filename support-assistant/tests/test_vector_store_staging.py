import asyncio
from datetime import datetime, timezone
import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from db.models import Base, Tenant, KnowledgeVersion, KnowledgeChunk, KnowledgeVersionChunk
from ingestion.manifest_engine import KnowledgeManifestEngine
from core.router.cache import CacheService
from adapters.postgres.vector_store import PostgresVectorStore
from ingestion.embedder import DeterministicLocalEmbedder


class TestVectorStoreStaging(unittest.TestCase):
    """Unit and staging tests for Task 4: Vector Store & Staging Index."""

    def setUp(self):
        self.db_file = f"test_staging_{datetime.now().timestamp()}.db"
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

    def tearDown(self):
        import os
        try:
            if os.path.exists(self.db_file):
                os.remove(self.db_file)
        except OSError:
            pass

    def test_resync_with_no_changes_reuses_embeddings_zero_embed_calls(self):
        """Verify content-hashed deduplication causes 0 embed calls on unchanged sync."""
        tenant_id = "tenant_test_sync"
        staff_id = "staff_sync_mgr"

        products = [
            {
                "product_id": "P1041",
                "name": "Pulse Buds 141",
                "brand": "NovaAudio",
                "category": "electronics",
                "description": "High performance wireless earbuds with 42 hours playback.",
                "faqs": [{"question": "Battery?", "answer": "42 hours total"}],
                "specifications": [{"label": "driver", "value": "10mm"}],
            }
        ]

        async def run_sync_sequence():
            async with self.session_maker() as session:
                async with session.begin():
                    t = Tenant(tenant_id=tenant_id, name="Test Tenant")
                    session.add(t)

            # First sync: computes embeddings
            async with self.session_maker() as session:
                async with session.begin():
                    job1 = await self.manifest_engine.run_catalog_ingestion_job(
                        tenant_id=tenant_id,
                        staff_id=staff_id,
                        session=session,
                        products_override=products,
                    )
                    v1_id = job1.stats["version_id"]
                    self.assertEqual(job1.stats["added"], 1)

            # Promote v1
            async with self.session_maker() as session:
                async with session.begin():
                    await self.manifest_engine.run_version_eval(tenant_id, v1_id, session)
                    await self.manifest_engine.promote_version(
                        tenant_id=tenant_id,
                        version_id=v1_id,
                        staff_id=staff_id,
                        staff_role="manager",
                        is_stepped_up=True,
                        session=session,
                    )

            # Second sync: identical products -> expect 0 embedder calls
            mock_embed = AsyncMock()
            with patch("ingestion.manifest_engine._catalog_embedder") as mock_factory:
                embedder_mock = DeterministicLocalEmbedder()
                embedder_mock.embed_documents = mock_embed
                mock_factory.return_value = embedder_mock

                async with self.session_maker() as session:
                    async with session.begin():
                        job2 = await self.manifest_engine.run_catalog_ingestion_job(
                            tenant_id=tenant_id,
                            staff_id=staff_id,
                            session=session,
                            products_override=products,
                        )
                        self.assertEqual(job2.stats["unchanged"], 1)
                        self.assertEqual(job2.stats["added"], 0)
                        self.assertEqual(job2.stats["updated"], 0)

            # Assert embed_documents was NEVER called on unchanged sync!
            self.assertEqual(mock_embed.call_count, 0)

        asyncio.run(run_sync_sequence())

    def test_promotion_invalidates_product_faq_cache_keys_and_rollback_restores(self):
        """Verify targeted cache invalidation of faq:{product_id}:* on promote and rollback."""
        tenant_id = "tenant_test_cache"
        staff_id = "staff_cache_mgr"

        products = [
            {
                "product_id": "P1041",
                "name": "Pulse Buds 141",
                "brand": "NovaAudio",
                "category": "electronics",
                "description": "High performance earbuds.",
                "faqs": [{"question": "Battery?", "answer": "42 hours"}],
            }
        ]

        async def run_cache_sequence():
            async with self.session_maker() as session:
                async with session.begin():
                    t = Tenant(tenant_id=tenant_id, name="Test Tenant")
                    session.add(t)

            # Run sync v1
            async with self.session_maker() as session:
                async with session.begin():
                    job1 = await self.manifest_engine.run_catalog_ingestion_job(
                        tenant_id=tenant_id,
                        staff_id=staff_id,
                        session=session,
                        products_override=products,
                    )
                    v1_id = job1.stats["version_id"]

            # Populate cache with product FAQ keys
            faq_key = self.cache_service.key_faq("P1041", "battery")
            price_key = self.cache_service.key_price("P1041")
            self.cache_service.set(faq_key, "Cached answer", 3600)
            self.cache_service.set(price_key, 1299, 45)
            self.assertIsNotNone(self.cache_service.get(faq_key))

            # Promote v1 -> should invalidate product cache keys
            async with self.session_maker() as session:
                async with session.begin():
                    await self.manifest_engine.run_version_eval(tenant_id, v1_id, session)
                    await self.manifest_engine.promote_version(
                        tenant_id=tenant_id,
                        version_id=v1_id,
                        staff_id=staff_id,
                        staff_role="manager",
                        is_stepped_up=True,
                        session=session,
                    )

            # Keys must be invalidated!
            self.assertIsNone(self.cache_service.get(faq_key))
            self.assertIsNone(self.cache_service.get(price_key))

            # Re-populate cache and perform rollback
            self.cache_service.set(faq_key, "Cached answer v2", 3600)
            async with self.session_maker() as session:
                async with session.begin():
                    # Seed an archived version to rollback to
                    archived = KnowledgeVersion(
                        version_id="ver_cat_archived",
                        tenant_id=tenant_id,
                        type="catalog",
                        status="archived",
                        manifest={"products": {"P1041": {"name": "Pulse Buds 141"}}},
                        promoted_at=datetime.now(timezone.utc),
                    )
                    session.add(archived)

            # Rollback
            async with self.session_maker() as session:
                async with session.begin():
                    rolled_back = await self.manifest_engine.rollback_version(
                        tenant_id=tenant_id,
                        version_type="catalog",
                        staff_id=staff_id,
                        staff_role="manager",
                        session=session,
                    )
                    self.assertEqual(rolled_back.version_id, "ver_cat_archived")

            # Must invalidate cache on rollback too
            self.assertIsNone(self.cache_service.get(faq_key))

        asyncio.run(run_cache_sequence())


if __name__ == "__main__":
    unittest.main()
