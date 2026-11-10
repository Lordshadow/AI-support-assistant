"""
Embedder Adapters for Knowledge Ingestion & RAG Retrieval
Supports:
1. DeterministicLocalEmbedder: Fast 1024-dim offline embeddings for tests & local development.
2. NIMEmbedder: NVIDIA NIM embedding microservice (e.g. bge-m3 or nv-embedqa-e5-v5).
3. GroqEmbedder: OpenAI-compatible embedding API.
"""

import asyncio
import math
import hashlib
import os
import random
import re
from typing import Protocol, Optional
import httpx


_CROSS_LINGUAL_SYNONYMS: dict[str, list[str]] = {
    # Tamil script
    "பேட்டரி": ["battery", "playback", "power"],
    "சார்ஜ்": ["charge", "charging", "battery"],
    "சார்ஜிங்": ["charging", "charge", "battery"],
    "நேரம்": ["time", "hours", "playback"],
    "விலை": ["price", "cost"],
    "ஆர்டர்": ["order", "delivery"],
    "ரீபண்ட்": ["refund", "return"],
    "திரும்ப": ["return", "refund"],
    "புல்ஸ்": ["pulse"],
    "பட்ஸ்": ["buds", "earbuds"],
    "இயர்பட்ஸ்": ["earbuds", "buds"],
    "வாட்ச்": ["watch", "smartwatch"],
    "தண்ணீர்": ["water", "resistant", "ipx4"],
    "உத்தரவாதம்": ["warranty", "guarantee"],
    # Tanglish terms
    "eppo": ["when", "delivery", "status"],
    "varum": ["arrive", "delivery", "status"],
    "sollunga": ["tell", "status", "info"],
    "evvalavu": ["how", "much", "time", "hours", "price"],
    "neram": ["time", "hours", "playback"],
    "backup": ["battery", "playback", "hours"],
    "thirumba": ["return", "refund"],
    "kaasu": ["money", "refund", "price"],
    "panam": ["money", "refund", "price"],
}


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
    Uses unicode token n-gram hash projections, multilingual synonym expansion, and L2 normalization.
    Ensures Tamil, Tanglish, and English strings have aligned semantic representations.
    Requires ZERO network calls and runs locally on any CPU.
    """

    def __init__(self, dimension: int = 1024, model: str = "baai/bge-m3"):
        self.dimension = dimension
        self.model = model

    def _embed_text(self, text: str) -> list[float]:
        vec = [0.0] * self.dimension
        tokens = re.findall(r"[\w]+", text.lower(), re.UNICODE)

        if not tokens:
            return vec

        for idx, token in enumerate(tokens):
            # Token unigram and bigram features
            h1 = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16) % self.dimension
            h2 = int(hashlib.sha1(token.encode("utf-8")).hexdigest(), 16) % self.dimension
            vec[h1] += 2.0
            vec[h2] += 1.0

            # Expand multilingual concept tokens directly at token position
            if token in _CROSS_LINGUAL_SYNONYMS:
                for syn in _CROSS_LINGUAL_SYNONYMS[token]:
                    hs1 = int(hashlib.md5(syn.encode("utf-8")).hexdigest(), 16) % self.dimension
                    hs2 = int(hashlib.sha1(syn.encode("utf-8")).hexdigest(), 16) % self.dimension
                    vec[hs1] += 2.5
                    vec[hs2] += 1.5

            # Subword character trigrams for typo resilience (e.g. "pluse" vs "pulse", "battry" vs "battery")
            if len(token) >= 4:
                for c_i in range(len(token) - 2):
                    trigram = token[c_i:c_i+3]
                    th = int(hashlib.md5(trigram.encode("utf-8")).hexdigest(), 16) % self.dimension
                    vec[th] += 0.8

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
        model: str,
        base_url: str,
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
        data = await self._request(url, payload, headers)
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
        data = await self._request(url, payload, headers)
        return data["data"][0]["embedding"]

    async def _request(self, url: str, payload: dict, headers: dict) -> dict:
        attempts = max(1, int(os.getenv("EMBEDDING_MAX_ATTEMPTS", "3")))
        timeout = max(1.0, float(os.getenv("EMBEDDING_TIMEOUT_SECONDS", "30")))
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=min(5.0, timeout))) as client:
            for attempt in range(attempts):
                try:
                    response = await client.post(url, json=payload, headers=headers)
                    if response.status_code not in (408, 425, 429) and response.status_code < 500:
                        response.raise_for_status()
                        return response.json()
                    if attempt == attempts - 1:
                        response.raise_for_status()
                except (httpx.TimeoutException, httpx.NetworkError):
                    if attempt == attempts - 1:
                        raise RuntimeError("Embedding service request failed after retries.") from None
                delay = min((0.25 * (2 ** attempt)) + random.uniform(0.0, 0.1), 5.0)
                await asyncio.sleep(delay)
        raise RuntimeError("Embedding service returned no response.")


def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    """Calculate cosine similarity between two dense vectors."""
    dot = sum(a * b for a, b in zip(v1, v2))
    norm_a = math.sqrt(sum(a * a for a in v1))
    norm_b = math.sqrt(sum(b * b for b in v2))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
