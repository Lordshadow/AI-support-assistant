"""PostgreSQL/pgvector implementation of the vector-store port."""

from sqlalchemy import select

from core.ports import VectorStorePort
from db.models import KnowledgeChunk, KnowledgeVersionChunk


class PostgresVectorStore(VectorStorePort):
    """Tenant-checked persistence for content-addressed chunks and version links."""

    async def get_chunk(self, tenant_id: str, chunk_id: str, session) -> KnowledgeChunk | None:
        chunk = await session.get(KnowledgeChunk, chunk_id)
        if chunk is not None and chunk.tenant_id != tenant_id:
            raise ValueError("Vector chunk is not owned by the current tenant.")
        return chunk

    async def upsert_chunk(
        self,
        tenant_id: str,
        chunk_id: str,
        product_id: str,
        text: str,
        embedding: list[float],
        metadata: dict,
        session,
    ) -> KnowledgeChunk:
        if len(embedding) != 1024:
            raise ValueError("Catalog vectors must have exactly 1024 dimensions.")
        chunk = await self.get_chunk(tenant_id, chunk_id, session)
        if chunk is None:
            chunk = KnowledgeChunk(chunk_id=chunk_id, tenant_id=tenant_id, source_type="catalog",
                product_id=product_id, text=text, embedding=embedding, metadata_=metadata)
            session.add(chunk)
        elif chunk.embedding is None:
            chunk.embedding = embedding
            chunk.text = text
            chunk.metadata_ = metadata
        return chunk

    async def link_version(self, version_id: str, chunk_id: str, session) -> None:
        link = await session.scalar(select(KnowledgeVersionChunk).where(
            KnowledgeVersionChunk.version_id == version_id,
            KnowledgeVersionChunk.chunk_id == chunk_id,
        ))
        if link is None:
            session.add(KnowledgeVersionChunk(version_id=version_id, chunk_id=chunk_id))
