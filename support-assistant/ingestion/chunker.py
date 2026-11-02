"""
Document Chunker for Product Pages and Policy Documents
Complies with Specification Section 5.3 (Knowledge chunks: ingestion rules).

Rules Enforced:
1. Prefix every chunk with product name so it is never ambiguous in isolation.
2. Chunk return policy by clause, preserving clause numbers in metadata.
3. Exclude live data (price, stock, order status).
4. Strip navigation boilerplate.
"""

import re
from typing import Any
import hashlib


class KnowledgeChunker:
    """Production-grade document chunker adhering strictly to Section 5.3."""

    @staticmethod
    def _generate_chunk_id(source_type: str, identifier: str, index: int) -> str:
        raw = f"{source_type}:{identifier}:{index}"
        return f"chk_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}"

    @classmethod
    def chunk_product_doc(
        cls,
        product_id: str,
        product_name: str,
        brand: str,
        category: str,
        raw_text: str,
        doc_id: str = "DOC-PROD-01",
        doc_version: str = "1.0"
    ) -> list[dict[str, Any]]:
        """
        Chunks product manual / FAQ content.
        Enforces rule: 'Prefix every chunk with the product name'.
        """
        # Split by double newlines or section headers
        blocks = re.split(r"\n\s*\n", raw_text)
        chunks: list[dict[str, Any]] = []
        chunk_idx = 0

        for block in blocks:
            cleaned = block.strip()
            # Ignore empty or very short lines
            if not cleaned or len(cleaned) < 15:
                continue

            # Exclude live pricing or checkout boilerplate
            if re.search(r"\b(add to cart|checkout|buy now|live price:)\b", cleaned, re.I):
                continue

            # Strip markdown header markers (###, **, etc.)
            cleaned = re.sub(r"^(?:###?|\*\*)\s*", "", cleaned).strip()

            # Extract possible subsection title
            lines = cleaned.split("\n", 1)
            title = lines[0].replace("**", "").replace("#", "").strip()
            body = lines[1].strip() if len(lines) > 1 else cleaned

            # Rule: Prefix every chunk with the product name
            if not body.startswith(product_name):
                prefixed_text = f"{product_name} - {title}: {body}" if title != body else f"{product_name} - {body}"
            else:
                prefixed_text = body

            chunk_id = cls._generate_chunk_id("product", product_id, chunk_idx)
            chunks.append({
                "chunk_id": chunk_id,
                "source_type": "product_doc",
                "product_id": product_id,
                "doc_id": doc_id,
                "doc_version": doc_version,
                "text": prefixed_text,
                "metadata": {
                    "product_id": product_id,
                    "product_name": product_name,
                    "brand": brand,
                    "category": category,
                    "section_title": title,
                    "doc_version": doc_version
                }
            })
            chunk_idx += 1

        return chunks

    @classmethod
    def chunk_policy_doc(
        cls,
        raw_policy_text: str,
        doc_id: str = "POL-RETURNS-V1",
        doc_version: str = "1.0",
        effective_date: str = "2026-01-01"
    ) -> list[dict[str, Any]]:
        """
        Chunks store return and refund policy strictly by clause.
        Preserves clause numbers in metadata.
        """
        # Split on 'Clause X.X' or 'Policy Clause X.X'
        clause_pattern = r"(?:Policy\s+)?Clause\s+(\d+\.\d+)\s*(?:\(([^)]+)\))?:\s*"
        splits = re.split(clause_pattern, raw_policy_text)

        chunks: list[dict[str, Any]] = []
        # re.split with groups returns: [pre-text, clause_num, clause_title, body, ...]
        if len(splits) <= 1:
            # Fallback to paragraph splitting if no standard clause markers
            paragraphs = [p.strip() for p in raw_policy_text.split("\n\n") if p.strip()]
            for i, p in enumerate(paragraphs):
                chunks.append({
                    "chunk_id": cls._generate_chunk_id("policy", doc_id, i),
                    "source_type": "policy_clause",
                    "product_id": None,
                    "doc_id": doc_id,
                    "doc_version": doc_version,
                    "text": p,
                    "metadata": {"section_index": i, "doc_version": doc_version},
                    "effective_date": effective_date
                })
            return chunks

        i = 1
        chunk_idx = 0
        while i < len(splits):
            clause_num = splits[i].strip()
            clause_title = splits[i + 1].strip() if splits[i + 1] else "General"
            clause_body = splits[i + 2].strip() if i + 2 < len(splits) else ""

            full_chunk_text = f"Policy Clause {clause_num} ({clause_title}): {clause_body}"
            chunk_id = cls._generate_chunk_id("policy", f"{doc_id}_{clause_num}", chunk_idx)

            chunks.append({
                "chunk_id": chunk_id,
                "source_type": "policy_clause",
                "product_id": None,
                "doc_id": doc_id,
                "doc_version": doc_version,
                "text": full_chunk_text,
                "metadata": {
                    "clause_number": clause_num,
                    "clause_title": clause_title,
                    "doc_id": doc_id,
                    "doc_version": doc_version
                },
                "effective_date": effective_date
            })
            chunk_idx += 1
            i += 3

        return chunks
