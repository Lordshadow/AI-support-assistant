"""
Unit and Integration Tests for PostgreSQL Schema, Ingestion Chunker, Embedder, and Pipeline
Validates Specification Section 4, 5.1, 5.2, 5.3, and 8.2 (Filtered RAG).
"""

import unittest
from pathlib import Path
import sys

# Add support-assistant to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from ingestion import (
    KnowledgeChunker, DeterministicLocalEmbedder,
    cosine_similarity, IngestionPipeline
)


def run_sync(coro):
    """Drive in-memory coroutine without socket dependencies."""
    try:
        coro.send(None)
    except StopIteration as e:
        return e.value


class TestIngestionAndDB(unittest.TestCase):

    def setUp(self):
        self.base_dir = Path(__file__).parent.parent
        self.sql_path = self.base_dir / "db" / "init.sql"
        self.compose_path = self.base_dir.parent / "docker-compose.yml"
        self.products_path = self.base_dir / "data" / "sample_products.json"
        self.policy_path = self.base_dir / "data" / "returns_policy.txt"
        self.embedder = DeterministicLocalEmbedder(dimension=1024)

    def test_init_sql_schema_definitions(self):
        self.assertTrue(self.sql_path.exists())
        with open(self.sql_path, "r", encoding="utf-8") as f:
            sql = f.read()

        # Check required extensions
        self.assertIn("CREATE EXTENSION IF NOT EXISTS vector", sql)
        self.assertIn("CREATE EXTENSION IF NOT EXISTS pg_trgm", sql)

        # Check required tables
        self.assertIn("CREATE TABLE IF NOT EXISTS products", sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS product_specs", sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS product_prices", sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS knowledge_chunks", sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS orders", sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS refund_requests", sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS traces", sql)

        # Check HNSW vector index
        self.assertIn("USING hnsw (embedding vector_cosine_ops)", sql)

    def test_docker_compose_config(self):
        self.assertTrue(self.compose_path.exists())
        with open(self.compose_path, "r", encoding="utf-8") as f:
            compose = f.read()
        self.assertIn("image: pgvector/pgvector:pg16", compose)
        self.assertIn("image: redis:7-alpine", compose)

    def test_chunk_product_doc_prefixing_rule(self):
        raw_doc = (
            "### Battery Life\n"
            "Provides up to 42 hours total playback time.\n\n"
            "### Pairing\n"
            "Open the case near smartphone and pair.\n\n"
            "Buy Now and add to cart for instant checkout"  # Boilerplate to exclude
        )
        chunks = KnowledgeChunker.chunk_product_doc(
            product_id="P1041",
            product_name="Pulse Buds 141",
            brand="NovaAudio",
            category="electronics",
            raw_text=raw_doc
        )

        self.assertEqual(len(chunks), 2)
        # Verify prefixing rule from Section 5.3:
        for c in chunks:
            self.assertTrue(c["text"].startswith("Pulse Buds 141"))
            self.assertEqual(c["product_id"], "P1041")
            self.assertEqual(c["metadata"]["brand"], "NovaAudio")

        # Verify boilerplate was excluded
        self.assertNotIn("Buy Now", chunks[0]["text"])
        self.assertNotIn("Buy Now", chunks[1]["text"])

    def test_chunk_policy_doc_by_clause(self):
        policy_text = (
            "Policy Clause 1.0 (Return Window): Physical items can be returned within 30 days.\n\n"
            "Policy Clause 6.0 (Digital Goods): Digital game codes are strictly non-refundable."
        )
        chunks = KnowledgeChunker.chunk_policy_doc(policy_text)
        self.assertEqual(len(chunks), 2)

        c1 = chunks[0]
        self.assertEqual(c1["metadata"]["clause_number"], "1.0")
        self.assertEqual(c1["metadata"]["clause_title"], "Return Window")
        self.assertIn("30 days", c1["text"])

        c2 = chunks[1]
        self.assertEqual(c2["metadata"]["clause_number"], "6.0")
        self.assertEqual(c2["metadata"]["clause_title"], "Digital Goods")
        self.assertIn("strictly non-refundable", c2["text"])

    def test_deterministic_local_embedder(self):
        emb = run_sync(self.embedder.embed_query("Pulse Buds battery playtime"))
        self.assertEqual(len(emb), 1024)

        # L2 norm should equal 1.0 (within float tolerance)
        norm = sum(x * x for x in emb)
        self.assertAlmostEqual(norm, 1.0, places=4)

        # Semantic alignment check
        emb_similar = run_sync(self.embedder.embed_query("Pulse Buds playback hours"))
        emb_unrelated = run_sync(self.embedder.embed_query("Organic agricultural fertilizer"))

        sim_related = cosine_similarity(emb, emb_similar)
        sim_unrelated = cosine_similarity(emb, emb_unrelated)
        self.assertGreater(sim_related, sim_unrelated)

    def test_ingestion_pipeline_end_to_end_and_filtered_rag(self):
        pipeline = IngestionPipeline(embedder=self.embedder)

        # Ingest both datasets
        prod_count = run_sync(pipeline.ingest_products_file(self.products_path))
        policy_count = run_sync(pipeline.ingest_policy_file(self.policy_path))

        self.assertGreater(prod_count, 0)
        self.assertGreater(policy_count, 0)
        self.assertEqual(len(pipeline.indexed_chunks), prod_count + policy_count)

        # Test Filtered RAG (Section 8.2) for Pulse Buds 141
        # Query: 'battery playback hours' with product_id='P1041'
        results = run_sync(pipeline.search(
            query="battery playback hours",
            product_id="P1041",
            top_k=2
        ))

        self.assertTrue(len(results) > 0)
        for chunk, sim in results:
            self.assertEqual(chunk["product_id"], "P1041")
            self.assertIn("Pulse Buds 141", chunk["text"])
            # Zero leakage of P1031 (Buds 131)
            self.assertNotIn("Pulse Buds 131", chunk["text"])

        # Test Policy retrieval
        policy_results = run_sync(pipeline.search(
            query="digital gift cards refund",
            source_type="policy_clause",
            top_k=1
        ))
        self.assertEqual(len(policy_results), 1)
        top_policy, _ = policy_results[0]
        self.assertEqual(top_policy["metadata"]["clause_number"], "6.0")
        self.assertIn("strictly non-refundable", top_policy["text"])


if __name__ == "__main__":
    unittest.main()
