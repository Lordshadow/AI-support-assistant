---
name: vectordb-hybrid-retrieval
description: Production-grade vector database engineering, pgvector and Qdrant optimization, hybrid search with Reciprocal Rank Fusion (RRF), cross-encoder re-ranking, HNSW index tuning, and multi-tenant isolation.
license: MIT
---

# Production-Grade VectorDB & Hybrid Retrieval

## Purpose & Scope
This skill defines engineering standards for implementing production-grade vector search, hybrid retrieval (dense semantic + sparse lexical BM25/tsvector), Reciprocal Rank Fusion (RRF), cross-encoder re-ranking, and strict multi-tenant isolation on **pgvector** and dedicated vector stores.

---

## 1. Hybrid Search Architecture

Pure vector search struggles with exact keywords, SKUs, model numbers, and acronyms. Production retrieval combines dense semantic vectors with sparse lexical text indexing.

```text
               ┌──────────────────────┐
               │    User Search Query │
               └──────────┬───────────┘
                          │
            ┌─────────────┴─────────────┐
            ▼                           ▼
 ┌──────────────────────┐   ┌──────────────────────┐
 │ Dense Semantic Query │   │ Sparse Lexical Query │
 │ - OpenAI/Voyage Embed│   │ - PostgreSQL tsvector│
 │ - HNSW Index Search  │   │ - websearch_to_tsquery
 └──────────┬───────────┘   └──────────┬───────────┘
            │ Top-30 Candidates        │ Top-30 Candidates
            └─────────────┬─────────────┘
                          ▼
            ┌───────────────────────────┐
            │  Reciprocal Rank Fusion   │
            │  (RRF: k=60 merge scoring)│
            └─────────────┬─────────────┘
                          │ Top-15 Candidates
                          ▼
            ┌───────────────────────────┐
            │ Cross-Encoder Re-ranker   │
            │ (Cohere / BGE-Reranker)   │
            └─────────────┬─────────────┘
                          │ Top-5 High-Precision Chunks
                          ▼
            ┌───────────────────────────┐
            │   LLM Generation Context  │
            └───────────────────────────┘
```

---

## 2. Reciprocal Rank Fusion (RRF) Implementation

RRF normalizes and fuses ranked lists without needing score calibration across disparate distance metrics.

Formula:
$$RRF(d) = \sum_{m \in M} \frac{1}{k + r_m(d)}$$ (standard constant $k = 60$)

```python
from collections import defaultdict

def reciprocal_rank_fusion(
    dense_results: list[dict],
    lexical_results: list[dict],
    k: int = 60,
    top_n: int = 5
) -> list[dict]:
    """Merges dense semantic and lexical keyword results using Reciprocal Rank Fusion."""
    rrf_scores = defaultdict(float)
    doc_store = {}

    # Score dense vector rankings
    for rank, doc in enumerate(dense_results, start=1):
        doc_id = doc["id"]
        rrf_scores[doc_id] += 1.0 / (k + rank)
        doc_store[doc_id] = doc

    # Score lexical text rankings
    for rank, doc in enumerate(lexical_results, start=1):
        doc_id = doc["id"]
        rrf_scores[doc_id] += 1.0 / (k + rank)
        if doc_id not in doc_store:
            doc_store[doc_id] = doc

    # Sort documents descending by aggregated RRF score
    sorted_doc_ids = sorted(rrf_scores.keys(), key=lambda did: rrf_scores[did], reverse=True)
    
    ranked_docs = []
    for did in sorted_doc_ids[:top_n]:
        item = doc_store[did].copy()
        item["rrf_score"] = rrf_scores[did]
        ranked_docs.append(item)

    return ranked_docs
```

---

## 3. PostgreSQL & pgvector Production Hardening

### 3.1 Schema & HNSW Index Definition
Always use HNSW (Hierarchical Navigable Small World) indexes over IVFFlat for production workloads. HNSW supports incremental inserts without rebuild degradation and offers predictable query latency.

```sql
-- Enable extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Table definition with strict tenant scoping
CREATE TABLE knowledge_embeddings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR(64) NOT NULL,
    document_id VARCHAR(128) NOT NULL,
    chunk_index INT NOT NULL,
    content TEXT NOT NULL,
    embedding vector(1536) NOT NULL,
    tsv_content tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    content_hash VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Compound index for fast tenant filtering
CREATE INDEX idx_knowledge_tenant ON knowledge_embeddings (tenant_id);

-- HNSW vector index tuned for accuracy and query throughput
CREATE INDEX idx_knowledge_hnsw ON knowledge_embeddings 
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);

-- Full-text GIN index for lexical search
CREATE INDEX idx_knowledge_tsv ON knowledge_embeddings USING GIN (tsv_content);
```

### 3.2 SQL-Level Tenant Isolation
**Mandatory Rule:** Never fetch vectors across all tenants and filter in Python application memory. Multi-tenancy must be enforced directly inside the database query to prevent data cross-contamination and ensure index scan efficiency.

```python
HYBRID_QUERY = """
WITH semantic_search AS (
    SELECT id, content, metadata,
           ROW_NUMBER() OVER () as rank
    FROM knowledge_embeddings
    WHERE tenant_id = :tenant_id
    ORDER BY embedding <=> :query_vector
    LIMIT :top_candidates
),
lexical_search AS (
    SELECT id, content, metadata,
           ROW_NUMBER() OVER () as rank
    FROM knowledge_embeddings
    WHERE tenant_id = :tenant_id
      AND tsv_content @@ websearch_to_tsquery('english', :query_text)
    ORDER BY ts_rank_cd(tsv_content, websearch_to_tsquery('english', :query_text)) DESC
    LIMIT :top_candidates
)
SELECT 
    COALESCE(s.id, l.id) AS id,
    COALESCE(s.content, l.content) AS content,
    COALESCE(s.metadata, l.metadata) AS metadata,
    COALESCE(1.0 / (60 + s.rank), 0.0) + COALESCE(1.0 / (60 + l.rank), 0.0) AS rrf_score
FROM semantic_search s
FULL OUTER JOIN lexical_search l ON s.id = l.id
ORDER BY rrf_score DESC
LIMIT :limit;
"""
```

---

## 4. Embedding Caching & Deterministic Fingerprints

To eliminate redundant embedding API calls and contain operational costs:
1. **Content Hashing:** Compute `sha256(chunk_text + json(sorted_metadata))` before calling the embedding API.
2. **Embedding Cache:** Check an in-database or Redis cache by hash. If unchanged, reuse the vector.
3. **Model Fingerprinting:** Store the embedding model name (e.g. `text-embedding-3-small`), dimension count (`1536`), and distance metric (`cosine`) alongside the index version. If the model or dimension changes, trigger a clean staged rebuild.
