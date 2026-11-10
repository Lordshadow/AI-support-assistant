"""PostgreSQL-only data-preservation assertions for the legacy schema upgrade."""

import asyncio
import os
import unittest

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "requires isolated QA PostgreSQL database")
class TestLegacyMigrationDataPreservation(unittest.TestCase):
    def test_legacy_fixture_rows_are_preserved_and_migrated(self):
        async def verify():
            engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
            try:
                async with engine.connect() as conn:
                    legacy_refund = await conn.execute(text(
                        "SELECT refund_id FROM legacy_refund_requests WHERE refund_id='QA-REFUND'"
                    ))
                    migrated_refund = await conn.execute(text(
                        "SELECT tenant_id, state FROM refund_requests WHERE refund_id='QA-REFUND'"
                    ))
                    legacy_chunk = await conn.execute(text(
                        "SELECT chunk_id FROM legacy_knowledge_chunks WHERE chunk_id='QA-CHUNK'"
                    ))
                    migrated_chunk = await conn.execute(text(
                        "SELECT tenant_id, metadata->>'legacy_doc_id' "
                        "FROM knowledge_chunks WHERE chunk_id='QA-CHUNK'"
                    ))
                self.assertEqual(legacy_refund.scalar_one(), "QA-REFUND")
                tenant_id, state = migrated_refund.one()
                self.assertEqual(tenant_id, "tenant_novaretail")
                self.assertIn(state, {"pending_approval", "processed"})
                self.assertEqual(legacy_chunk.scalar_one(), "QA-CHUNK")
                self.assertEqual(migrated_chunk.one(), ("tenant_novaretail", "QA-DOC"))
            finally:
                await engine.dispose()

        asyncio.run(verify())
