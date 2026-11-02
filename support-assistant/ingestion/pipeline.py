"""
Knowledge Ingestion Pipeline
Loads raw product manuals, FAQs, and store policies; chunks them per Section 5.3;
embeds them; and prepares records for PostgreSQL pgvector insertion.
"""

import json
from pathlib import Path
from typing import Any, Optional

from ingestion.chunker import KnowledgeChunker
from ingestion.embedder import BaseEmbedder, DeterministicLocalEmbedder, cosine_similarity


class IngestionPipeline:
    """End-to-end ingestion and vector indexing pipeline."""

    def __init__(self, embedder: Optional[BaseEmbedder] = None):
        self.embedder = embedder or DeterministicLocalEmbedder(dimension=1024)
        self.indexed_chunks: list[dict[str, Any]] = []

    async def ingest_products_file(self, products_file_path: Path) -> int:
        with open(products_file_path, "r", encoding="utf-8") as f:
            products = json.load(f)

        count = 0
        for p in products:
            chunks = KnowledgeChunker.chunk_product_doc(
                product_id=p["product_id"],
                product_name=p["name"],
                brand=p["brand"],
                category=p["category"],
                raw_text=p.get("documentation", "")
            )
            # Embed all chunks
            texts = [c["text"] for c in chunks]
            embeddings = await self.embedder.embed_documents(texts)
            for chunk, emb in zip(chunks, embeddings):
                chunk["embedding"] = emb
                self.indexed_chunks.append(chunk)
                count += 1

        return count

    async def ingest_policy_file(self, policy_file_path: Path) -> int:
        with open(policy_file_path, "r", encoding="utf-8") as f:
            policy_text = f.read()

        chunks = KnowledgeChunker.chunk_policy_doc(
            raw_policy_text=policy_text,
            doc_id="POL-RETURNS-V1",
            doc_version="1.0"
        )
        texts = [c["text"] for c in chunks]
        embeddings = await self.embedder.embed_documents(texts)
        for chunk, emb in zip(chunks, embeddings):
            chunk["embedding"] = emb
            self.indexed_chunks.append(chunk)

        return len(chunks)

    async def search(
        self,
        query: str,
        product_id: Optional[str] = None,
        source_type: Optional[str] = None,
        top_k: int = 3
    ) -> list[tuple[dict[str, Any], float]]:
        """
        Simulates PostgreSQL Filtered RAG query:
        SELECT * FROM knowledge_chunks WHERE product_id = :p_id ORDER BY embedding <=> :q LIMIT :k
        """
        query_vec = await self.embedder.embed_query(query)
        candidates: list[tuple[dict[str, Any], float]] = []

        for chunk in self.indexed_chunks:
            # 1. Relational filters
            if product_id and chunk.get("product_id") != product_id:
                continue
            if source_type and chunk.get("source_type") != source_type:
                continue

            # 2. Vector distance (cosine similarity)
            sim = cosine_similarity(query_vec, chunk["embedding"])
            candidates.append((chunk, sim))

        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates[:top_k]
