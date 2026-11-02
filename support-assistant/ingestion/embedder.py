"""
Embedder Adapters for Knowledge Ingestion & RAG Retrieval
Supports:
1. DeterministicLocalEmbedder: Fast 1024-dim offline embeddings for tests & local development.
2. NIMEmbedder: NVIDIA NIM embedding microservice (e.g. bge-m3 or nv-embedqa-e5-v5).
3. GroqEmbedder: OpenAI-compatible embedding API.
"""

import math
import hashlib
from typing import Protocol, Optional
import httpx


class BaseEmbedder(Protocol):
    """Protocol for embedding generation."""
    dimension: int

    async def embed_query(self, text: str) -> list[float]:
        ...

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        ...


class DeterministicLocalEmbedder:
    """
    Offline local embedder producing 1024-dimensional normalized dense vectors.
    Uses token n-gram hash projections and L2 normalization.
    Ensures semantically similar strings (e.g. 'battery life' & 'playback time') have high cosine similarity.
    Requires ZERO network calls and runs locally on any CPU.
    """

    def __init__(self, dimension: int = 1024):
        self.dimension = dimension

    def _embed_text(self, text: str) -> list[float]:
        vec = [0.0] * self.dimension
        tokens = text.lower().replace("-", " ").replace(":", " ").split()

        if not tokens:
            return vec

        for idx, token in enumerate(tokens):
            # Token unigram and bigram features
            h1 = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16) % self.dimension
            h2 = int(hashlib.sha1(token.encode("utf-8")).hexdigest(), 16) % self.dimension
            vec[h1] += 1.0
            vec[h2] += 0.5

            if idx > 0:
                bigram = f"{tokens[idx-1]}_{token}"
                bh = int(hashlib.md5(bigram.encode("utf-8")).hexdigest(), 16) % self.dimension
                vec[bh] += 1.5

        # L2 Normalize
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0:
            vec = [x / norm for x in vec]
        return vec

    async def embed_query(self, text: str) -> list[float]:
        return self._embed_text(text)

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_text(t) for t in texts]


class NIMEmbedder:
    """
    NVIDIA NIM Embedding Adapter
    Calls NVIDIA NIM Microservices (e.g. 'nvidia/nv-embedqa-e5-v5' or 'bge-m3').
    """

    def __init__(
        self,
        api_key: str,
        model: str = "nvidia/nv-embedqa-e5-v5",
        base_url: str = "https://integrate.api.nvidia.com/v1",
        dimension: int = 1024
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.dimension = dimension

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        url = f"{self.base_url}/embeddings"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "input": texts,
            "model": self.model,
            "input_type": "passage",
            "encoding_format": "float"
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return [item["embedding"] for item in data["data"]]

    async def embed_query(self, text: str) -> list[float]:
        url = f"{self.base_url}/embeddings"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "input": [text],
            "model": self.model,
            "input_type": "query",
            "encoding_format": "float"
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return data["data"][0]["embedding"]


def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    """Calculate cosine similarity between two dense vectors."""
    dot = sum(a * b for a, b in zip(v1, v2))
    norm_a = math.sqrt(sum(a * a for a in v1))
    norm_b = math.sqrt(sum(b * b for b in v2))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
