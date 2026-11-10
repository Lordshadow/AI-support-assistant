import asyncio
import math
import unittest
from unittest.mock import patch
import httpx

from ingestion.embedder import (
    DeterministicLocalEmbedder,
    NIMEmbedder,
    cosine_similarity,
)


class TestEmbedder(unittest.TestCase):
    """Unit tests for Task 3: Multilingual Embedder & Offline Test Adapter."""

    def setUp(self):
        self.embedder = DeterministicLocalEmbedder(dimension=1024, model="baai/bge-m3")

    def test_embedding_dimensions_and_l2_normalization(self):
        text = "Pulse Buds 141 wireless earbuds with long playback."
        vector = asyncio.run(self.embedder.embed_query(text))

        self.assertEqual(len(vector), 1024)
        norm = math.sqrt(sum(x * x for x in vector))
        self.assertAlmostEqual(norm, 1.0, places=4)

    def test_multilingual_tamil_query_matches_english_product_page(self):
        # English document indexed in vector DB
        doc_text = "Pulse Buds 141 - Battery life: Provides up to 42 hours of total playback time."
        doc_vec = asyncio.run(self.embedder.embed_query(doc_text))

        # Tamil query about battery life
        tamil_query = "Pulse Buds 141 பேட்டரி எவ்வளவு நேரம் வரும்?"
        tamil_vec = asyncio.run(self.embedder.embed_query(tamil_query))

        sim_tamil = cosine_similarity(doc_vec, tamil_vec)
        self.assertGreater(sim_tamil, 0.20, f"Expected positive similarity for Tamil query, got {sim_tamil}")

        # Irrelevant document should have much lower similarity
        unrelated_doc = "Google Play ₹500 Gift Card - Digital code delivered via SMS."
        unrelated_vec = asyncio.run(self.embedder.embed_query(unrelated_doc))
        sim_unrelated = cosine_similarity(unrelated_vec, tamil_vec)
        self.assertGreater(sim_tamil, sim_unrelated + 0.15)

    def test_tanglish_query_matches_english_concept(self):
        doc_text = "Order delivery timeline: Items process in 24 hours and deliver in 3 to 5 business days."
        doc_vec = asyncio.run(self.embedder.embed_query(doc_text))

        tanglish_query = "En order eppo varum status sollunga"
        tanglish_vec = asyncio.run(self.embedder.embed_query(tanglish_query))

        sim = cosine_similarity(doc_vec, tanglish_vec)
        self.assertGreater(sim, 0.10)

    def test_batch_embed_documents(self):
        docs = [
            "Pulse Buds 141 - Battery: 42 hours total playback.",
            "Pulse Buds 131 - Battery: 60 hours total playback.",
            "Nova Watch Pro - Battery: 7 days normal usage.",
        ]
        vectors = asyncio.run(self.embedder.embed_documents(docs))
        self.assertEqual(len(vectors), 3)
        for vec in vectors:
            self.assertEqual(len(vec), 1024)
            norm = math.sqrt(sum(x * x for x in vec))
            self.assertAlmostEqual(norm, 1.0, places=4)

    def test_nim_embedder_retries_and_timeout(self):
        attempts = []

        async def mock_post(client_self, url, json=None, headers=None):
            attempts.append(url)
            if len(attempts) < 2:
                mock_resp = httpx.Response(503, json={"error": "service unavailable"})
                mock_resp.request = httpx.Request("POST", url)
                return mock_resp
            mock_resp = httpx.Response(
                200,
                json={"data": [{"embedding": [0.05] * 1024}], "model": "baai/bge-m3"}
            )
            mock_resp.request = httpx.Request("POST", url)
            return mock_resp

        nim = NIMEmbedder(
            api_key="nvapi-test",
            model="baai/bge-m3",
            base_url="https://nim.api.nvidia.com/v1",
            dimension=1024,
        )

        with patch("httpx.AsyncClient.post", new=mock_post):
            resp = asyncio.run(nim._request("https://nim.api.nvidia.com/v1/embeddings", {}, {}))
            self.assertIn("data", resp)
            self.assertEqual(len(attempts), 2)


if __name__ == "__main__":
    unittest.main()
