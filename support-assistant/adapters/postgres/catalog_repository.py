"""
PostgreSQL Implementation of CatalogPort.
Complies with Specification Section 6, 7.1, and 8.2 (Filtered RAG).
"""

from typing import Optional, List, Dict, Any
from sqlalchemy import select, or_, and_
from sqlalchemy.orm import selectinload

from core.ports import CatalogPort
from core.models import ProductMatch, ProductSpecs, PriceInfo, ProductSummary
from db.models import ProductModel, ProductSpecModel, ProductPriceModel, KnowledgeChunk
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
            stmt = (
                select(ProductModel)
                .options(selectinload(ProductModel.specs))
                .where(
                    ProductModel.tenant_id == self.tenant_id,
                    ProductModel.product_id == product_id,
                )
            )
            result = await session.execute(stmt)
            p = result.scalars().first()
            if not p:
                return None

            specs_dict = {s.spec_key: s.spec_value for s in (p.specs or [])}
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
        """Filtered RAG on btree index (tenant_id, product_id)."""
        async with get_async_session(tenant_id=self.tenant_id) as session:
            stmt = select(KnowledgeChunk).where(
                KnowledgeChunk.tenant_id == self.tenant_id,
                KnowledgeChunk.product_id == product_id,
            )
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
