"""Validated, deterministic product normalization and chunk construction."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CatalogFAQ(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)
    question: str = Field(min_length=1, max_length=2000)
    answer: str = Field(min_length=1, max_length=12000)


class CatalogSpec(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)
    label: str = Field(min_length=1, max_length=128)
    value: str = Field(min_length=1, max_length=2000)
    unit: str | None = Field(default=None, max_length=32)

    @classmethod
    def model_validate_source(cls, value: Any) -> "CatalogSpec":
        if isinstance(value, dict):
            value = {
                "label": value.get("label") or value.get("key") or value.get("spec_key"),
                "value": value.get("value") or value.get("spec_value"),
                "unit": value.get("unit"),
            }
        return cls.model_validate(value)


class CatalogProduct(BaseModel):
    """Allowlisted source contract; volatile or unrelated fields are discarded."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)
    product_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    brand: str = Field(default="Generic", max_length=128)
    category: str = Field(default="General", max_length=64)
    description: str = Field(default="", max_length=50000)
    faqs: list[CatalogFAQ] = Field(default_factory=list, max_length=1000)
    specifications: list[dict[str, Any]] = Field(default_factory=list, max_length=1000)
    price: int | None = Field(default=None, ge=0)
    discount_price: int | None = Field(default=None, ge=0)
    currency: str = Field(default="INR", max_length=8)
    in_stock: bool | None = None

    @field_validator("product_id", mode="before")
    @classmethod
    def coerce_product_id(cls, value: Any) -> str:
        return str(value).strip() if value is not None else ""

    @classmethod
    def model_validate_source(cls, value: Any) -> "CatalogProduct":
        if not isinstance(value, dict):
            raise ValueError("Catalog product must be an object.")
        return cls.model_validate({
            "product_id": value.get("product_id", value.get("id")),
            "name": value.get("name", value.get("title")),
            "brand": value.get("brand") or "Generic",
            "category": value.get("category") or "General",
            "description": value.get("description") or "",
            "faqs": value.get("faqs") or [],
            "specifications": value.get("specifications") or [],
            "price": value.get("price"),
            "discount_price": value.get("discount_price", value.get("sale_price")),
            "currency": value.get("currency") or "INR",
            "in_stock": value.get("in_stock", value.get("available")),
        })

    def normalized_specs(self) -> list[CatalogSpec]:
        unique: dict[str, CatalogSpec] = {}
        for item in self.specifications:
            spec = CatalogSpec.model_validate_source(item)
            unique[spec.label] = spec
        return list(unique.values())

    def content_hash(self) -> str:
        payload = self.model_dump(mode="json", exclude={"specifications"})
        return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


_BOILERPLATE = re.compile(
    r"^(home|menu|navigation|skip to content|search|cart|my account|sign in|log in|"
    r"add to cart|buy now|checkout|related products|you may also like|share|reviews?)\b",
    re.IGNORECASE,
)
_VOLATILE = re.compile(r"\b(?:price|in stock|out of stock|stock status|offer price|discount price|order status)\s*[:=-]", re.I)


def _clean_text(text: str) -> str:
    lines = []
    for line in text.splitlines():
        value = re.sub(r"\s+", " ", line).strip()
        if not value or _BOILERPLATE.match(value) or _VOLATILE.search(value):
            continue
        lines.append(value)
    return " ".join(lines)


def build_product_chunks(
    product: CatalogProduct,
    *,
    doc_version: str,
    min_chunks: int = 5,
    max_chunks: int = 15,
) -> list[dict[str, Any]]:
    """Build product-prefixed answer chunks; specifications never enter this output."""
    if min_chunks < 1 or max_chunks < min_chunks:
        raise ValueError("Invalid catalog chunk bounds.")

    units: list[tuple[str, str]] = []
    description = _clean_text(product.description)
    if description:
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", description) if s.strip()]
        units.extend(("description", sentence) for sentence in sentences)
    for faq in product.faqs:
        q, a = _clean_text(faq.question), _clean_text(faq.answer)
        if q and a:
            units.append(("faq", f"Frequently asked question: {q} Answer: {a}"))

    if not units:
        fallback_desc = f"{product.name} from brand {product.brand} in category {product.category}."
        units.append(("description", fallback_desc))

    # Keep FAQ units intact where possible. If the source provides fewer than target
    # units, split the longest answer-bearing units without duplicating content.
    while len(units) < min_chunks:
        index = max(range(len(units)), key=lambda i: len(units[i][1].split()))
        kind, value = units[index]
        words = value.split()
        if len(words) < 2:
            break
        middle = len(words) // 2
        units[index:index + 1] = [(kind, " ".join(words[:middle])), (kind, " ".join(words[middle:]))]

    while len(units) > max_chunks:
        index = min(range(len(units) - 1), key=lambda i: len(units[i][1]) + len(units[i + 1][1]))
        left_kind, left_text = units[index]
        right_kind, right_text = units[index + 1]
        units[index:index + 2] = [(left_kind if left_kind == right_kind else "product", f"{left_text} {right_text}")]

    result = []
    for kind, content in units:
        text = f"{product.name} - {content}"
        metadata = {
            "product_id": product.product_id,
            "name": product.name,
            "brand": product.brand,
            "category": product.category,
            "source_type": "catalog",
            "doc_version": doc_version,
            "content_type": kind,
        }
        result.append({"text": text, "metadata": metadata, "content_hash": hashlib.sha256(
            json.dumps({"text": text, "metadata": metadata}, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest()})
    return result
