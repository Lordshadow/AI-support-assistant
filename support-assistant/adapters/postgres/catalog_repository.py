"""
PostgreSQL Implementation of CatalogPort.
Complies with Specification Section 6, 7.1, and 8.2 (Filtered RAG).
"""

from typing import Optional, List, Dict, Any
from sqlalchemy import select, or_, and_

from core.ports import CatalogPort
from core.models import ProductMatch, ProductSpecs, PriceInfo, ProductSummary
from db.models import (
    ProductModel, ProductSpecModel, ProductPriceModel, KnowledgeChunk, KnowledgeVersion,
    KnowledgeVersionChunk, Tenant,
)
from db.session import get_async_session


class PostgresCatalogRepository:
    """Implements CatalogPort backed by PostgreSQL and knowledge_chunks."""

    def __init__(self, tenant_id: str = "tenant_novaretail", session_factory=None):
        self.tenant_id = tenant_id
        self._session_factory = session_factory

    async def find_product(self, text: str) -> List[ProductMatch]:
        query_text = text.strip().lower()
        if not query_text:
            return []

        async with get_async_session(tenant_id=self.tenant_id) as session:
            stmt = select(ProductModel).where(
                ProductModel.tenant_id == self.tenant_id,
                ProductModel.active == True
            )
            result = await session.execute(stmt)
            products = result.scalars().all()

        matches: List[ProductMatch] = []
        for p in products:
            p_name_lower = p.name.lower()
            aliases = p.aliases if isinstance(p.aliases, list) else []
            score = 0.0

            if query_text in p_name_lower or p_name_lower in query_text:
                score = 0.95 if query_text == p_name_lower else 0.85
            else:
                for alias in aliases:
                    if str(alias).lower() in query_text or query_text in str(alias).lower():
                        score = 0.90
                        break

            if score > 0.4:
                matches.append(
                    ProductMatch(
                        product_id=p.product_id,
                        name=p.name,
                        score=score,
                        category=p.category,
                    )
                )

        matches.sort(key=lambda m: m.score, reverse=True)
        return matches

    async def get_details(self, product_id: str) -> Optional[ProductSpecs]:
        async with get_async_session(tenant_id=self.tenant_id) as session:
            active_catalog_id = await session.scalar(
                select(Tenant.active_product_version).where(Tenant.tenant_id == self.tenant_id)
            )
            stmt = select(ProductModel).where(
                ProductModel.tenant_id == self.tenant_id,
                ProductModel.product_id == product_id,
            )
            result = await session.execute(stmt)
            p = result.scalars().first()
            if not p:
                return None

            spec_stmt = select(ProductSpecModel).where(ProductSpecModel.product_id == product_id)
            spec_stmt = spec_stmt.where(
                ProductSpecModel.version_id == active_catalog_id if active_catalog_id
                else ProductSpecModel.version_id.is_(None)
            )
            specs = (await session.execute(spec_stmt)).scalars().all()
            if not specs:
                # Older catalog versions predate versioned product_specs or reside in earlier version.
                specs = (await session.execute(select(ProductSpecModel).where(
                    ProductSpecModel.product_id == product_id
                ))).scalars().all()
            specs_dict = {s.spec_key: s.spec_value for s in specs}
            aliases_list = p.aliases if isinstance(p.aliases, list) else []
            return ProductSpecs(
                product_id=p.product_id,
                name=p.name,
                brand=p.brand,
                category=p.category,
                specs=specs_dict,
                aliases=aliases_list,
            )

    async def get_price(self, product_id: str) -> Optional[PriceInfo]:
        async with get_async_session(tenant_id=self.tenant_id) as session:
            stmt = select(ProductPriceModel).where(
                ProductPriceModel.product_id == product_id
            )
            result = await session.execute(stmt)
            price_row = result.scalars().first()
            if not price_row:
                return None

            return PriceInfo(
                product_id=price_row.product_id,
                price=price_row.price,
                discount_price=price_row.discount_price,
                currency=price_row.currency,
                in_stock=price_row.in_stock,
                active_offers=[],
            )

    async def search(
        self,
        category: Optional[str] = None,
        min_price: Optional[int] = None,
        max_price: Optional[int] = None,
        filters: Optional[dict] = None,
    ) -> List[ProductSummary]:
        async with get_async_session(tenant_id=self.tenant_id) as session:
            stmt = (
                select(ProductModel, ProductPriceModel)
                .join(ProductPriceModel, ProductModel.product_id == ProductPriceModel.product_id)
                .where(
                    ProductModel.tenant_id == self.tenant_id,
                    ProductModel.active == True,
                )
            )
            if category:
                stmt = stmt.where(ProductModel.category.ilike(f"%{category}%"))
            if min_price is not None:
                stmt = stmt.where(ProductPriceModel.price >= min_price)
            if max_price is not None:
                stmt = stmt.where(ProductPriceModel.price <= max_price)

            result = await session.execute(stmt)
            rows = result.all()

            summaries = []
            for p, pr in rows:
                summaries.append(
                    ProductSummary(
                        product_id=p.product_id,
                        name=p.name,
                        category=p.category,
                        price=pr.price,
                        in_stock=pr.in_stock,
                    )
                )
            return summaries

    async def search_product_docs(self, product_id: str, query: str) -> List[str]:
        """Vector-rank documentation with tenant, active-version, and product filters."""
        async with get_async_session(tenant_id=self.tenant_id) as session:
            active_catalog_id = await session.scalar(
                select(Tenant.active_product_version).where(Tenant.tenant_id == self.tenant_id)
            )
            stmt = select(KnowledgeChunk).where(
                KnowledgeChunk.tenant_id == self.tenant_id,
                KnowledgeChunk.product_id == product_id,
                KnowledgeChunk.source_type == "catalog",
            )
            if active_catalog_id:
                stmt = stmt.join(
                    KnowledgeVersionChunk,
                    KnowledgeVersionChunk.chunk_id == KnowledgeChunk.chunk_id,
                ).where(KnowledgeVersionChunk.version_id == active_catalog_id)
                version = await session.get(KnowledgeVersion, active_catalog_id)
                expected_model = (version.manifest or {}).get("embedding_model") if version else None
                if query.strip():
                    from ingestion.manifest_engine import _catalog_embedder
                    embedder = _catalog_embedder()
                    actual_model = getattr(embedder, "model", None)
                    if expected_model and actual_model != expected_model:
                        raise RuntimeError("Active catalog embedding model is unavailable or mismatched.")
                    query_vector = await embedder.embed_query(query)
                    if len(query_vector) != 1024:
                        raise RuntimeError("Query embedder returned an invalid vector dimension.")
                    stmt = stmt.order_by(KnowledgeChunk.embedding.cosine_distance(query_vector)).limit(10)
            result = await session.execute(stmt)
            chunks = result.scalars().all()
            return [c.text for c in chunks]

    async def search_policy(self, query: str) -> List[str]:
        """Tenant-wide return/refund policy search."""
        async with get_async_session(tenant_id=self.tenant_id) as session:
            stmt = select(KnowledgeChunk).where(
                KnowledgeChunk.tenant_id == self.tenant_id,
                KnowledgeChunk.source_type == "policy_clause",
            )
            result = await session.execute(stmt)
            chunks = result.scalars().all()
            return [c.text for c in chunks]
