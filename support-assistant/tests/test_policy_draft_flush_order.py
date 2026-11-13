import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from db.models import KnowledgeChunk, KnowledgeVersion, KnowledgeVersionChunk
from ingestion.manifest_engine import KnowledgeManifestEngine


class ForeignKeyCheckingSession:
    def __init__(self):
        self.pending = []
        self.versions = set()
        self.chunks = set()
        self.links = []

    async def get(self, model, row_id):
        if model is KnowledgeChunk:
            return next((row for row in self.pending if isinstance(row, model) and row.chunk_id == row_id), None)
        return None

    def add(self, row):
        self.pending.append(row)

    async def flush(self):
        for row in self.pending:
            if isinstance(row, KnowledgeVersion):
                self.versions.add(row.version_id)
            elif isinstance(row, KnowledgeChunk):
                self.chunks.add(row.chunk_id)
            elif isinstance(row, KnowledgeVersionChunk):
                if row.version_id not in self.versions:
                    raise AssertionError("Version link flushed before its version row")
                if row.chunk_id not in self.chunks:
                    raise AssertionError("Version link flushed before its chunk row")
                self.links.append(row)
        self.pending.clear()


class TestPolicyDraftFlushOrder(unittest.TestCase):
    def test_parents_are_flushed_before_version_chunk_links(self):
        session = ForeignKeyCheckingSession()
        engine = KnowledgeManifestEngine()

        async def create_draft():
            return await engine.create_policy_draft(
                tenant_id="tenant-demo",
                staff_id="staff-demo",
                filename="demo_refund_policy.md",
                clauses=[{
                    "clause_id": "D-1",
                    "title": "Return window",
                    "text": "Physical items may be returned within 30 days.",
                }],
                confirmed_values={
                    "return_window_days": 30,
                    "excluded_categories": ["digital"],
                    "auto_refund_limit_inr": 0,
                },
                session=session,
            )

        pending = create_draft()
        try:
            version = pending.send(None)
        except StopIteration as completed:
            version = completed.value
        else:
            self.fail("The fake session should complete without an event loop")

        self.assertIn(version.version_id, session.versions)
        self.assertEqual(len(session.chunks), 1)
        self.assertEqual(len(session.links), 1)
        self.assertFalse(session.pending)


if __name__ == "__main__":
    unittest.main()
