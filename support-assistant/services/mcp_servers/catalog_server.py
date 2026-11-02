"""
MCP Catalog Server (Read-Only)
Exposes product catalog search, specifications, live pricing, and policy search.
Complies with Specification Section 7.1.
"""

from typing import Optional, Any
from core.ports import CatalogPort


class MCPCatalogServer:
    """Tool server for Catalog operations."""

    def __init__(self, catalog_adapter: CatalogPort):
        self.catalog = catalog_adapter

    async def find_product(self, name_text: str) -> dict[str, Any]:
        """Resolve customer product name to canonical IDs."""
        matches = await self.catalog.find_product(name_text)
        return {
            "found": len(matches) > 0,
            "candidates": [
                {
                    "product_id": m.product_id,
                    "name": m.name,
                    "score": round(m.score, 2),
                    "category": m.category
                }
                for m in matches
            ]
        }

    async def get_product_price(self, product_id: str) -> dict[str, Any]:
        """Fetch live price, discounts, and stock."""
        info = await self.catalog.get_price(product_id)
        if not info:
            return {"found": False, "error": f"Product '{product_id}' not found."}
        return {
            "found": True,
            "product_id": info.product_id,
            "price": info.price,
            "discount_price": info.discount_price,
            "currency": info.currency,
            "in_stock": info.in_stock,
            "active_offers": info.active_offers
        }

    async def get_product_details(self, product_id: str) -> dict[str, Any]:
        """Fetch exact technical specifications."""
        specs = await self.catalog.get_details(product_id)
        if not specs:
            return {"found": False, "error": f"Product '{product_id}' not found."}
        return {
            "found": True,
            "product_id": specs.product_id,
            "name": specs.name,
            "brand": specs.brand,
            "category": specs.category,
            "specs": specs.specs
        }

    async def search_product_docs(self, product_id: str, question: str) -> dict[str, Any]:
        """Search product-specific manuals and FAQs."""
        chunks = await self.catalog.search_product_docs(product_id, question)
        return {
            "product_id": product_id,
            "question": question,
            "chunks": chunks
        }

    async def search_policy(self, question: str) -> dict[str, Any]:
        """Search store return, refund, and shipping policies."""
        clauses = await self.catalog.search_policy(question)
        return {
            "question": question,
            "clauses": clauses
        }
