"""
Language Normalizer and Entity Extractor
Complies with Specification Section 1.5 (R1), 8.1, and 13 (Multilingual & Voice).

Handles English, Tamil, and Tanglish (Tamil in Latin script).
Enforces rule: 'Keep product names, order numbers and amounts exact; do not translate them.'
"""

import re
from typing import Literal, Optional
from dataclasses import dataclass, field


@dataclass(frozen=True)
class NormalizedQuery:
    original_text: str
    cleaned_text: str
    language: Literal["en", "ta", "tanglish"]
    extracted_order_id: Optional[str] = None
    extracted_amount_inr: Optional[int] = None
    extracted_product_query: Optional[str] = None
    is_dispute: bool = False
    is_comparison: bool = False
    is_human_request: bool = False


class LanguageNormalizer:
    """Detects language, extracts canonical entities, and flags conversational complexity."""

    # Common Tanglish markers (Tamil words transliterated into Latin script)
    TANGLISH_MARKERS = [
        r"\benna\b", r"\beppo\b", r"\baachu\b", r"\bsollunga\b", r"\bkonjam\b",
        r"\bungaloda\b", r"\bvarum\b", r"\birukku\b", r"\billa\b", r"\bpannunga\b",
        r"\btheriyuma\b", r"\bkidaikkuma\b", r"\bvandhurucha\b", r"\bkaathirukken\b",
        r"\bvanakkam\b"
    ]

    # Human escalation trigger words
    HUMAN_MARKERS = [
        r"\bhuman\b", r"\bagent\b", r"\bexecutive\b", r"\bmanager\b",
        r"\bperson\b", r"\bescalate\b", r"\bmanushana\b", r"\baal kooda\b"
    ]

    # Dispute / Agitated customer markers
    DISPUTE_MARKERS = [
        r"\bangry\b", r"\bterrible\b", r"\bworst\b", r"\bfraud\b", r"\bscam\b",
        r"\bcheating\b", r"\bunacceptable\b", r"\bhorrible\b", r"\bpolice\b", r"\bcourt\b"
    ]

    @classmethod
    def detect_language(cls, text: str) -> Literal["en", "ta", "tanglish"]:
        # 1. Tamil Unicode Script Block (\u0B80 - \u0BFF)
        if any("\u0b80" <= char <= "\u0bff" for char in text):
            return "ta"

        # 2. Tanglish markers in Latin text
        text_lower = text.lower()
        for marker in cls.TANGLISH_MARKERS:
            if re.search(marker, text_lower):
                return "tanglish"

        return "en"

    @classmethod
    def normalize(cls, text: str) -> NormalizedQuery:
        lang = cls.detect_language(text)
        text_lower = text.lower().strip()

        # Extract Order ID (e.g., ORD-1029, ORD-5501)
        order_match = re.search(r"\bORD[-_]?\d+\b", text, re.I)
        order_id = order_match.group(0).upper().replace("_", "-") if order_match else None

        # Extract Amount (e.g. ₹1,499, Rs. 4500, 2000 rupees)
        amount_inr = None
        amt_match = re.search(r"(?:₹|rs\.?|inr)\s*([0-9,]+)", text_lower)
        if amt_match:
            try:
                amount_inr = int(amt_match.group(1).replace(",", ""))
            except ValueError:
                pass

        # Check for Human escalation
        is_human = any(bool(re.search(pat, text_lower)) for pat in cls.HUMAN_MARKERS)

        # Check for Customer Dispute
        is_dispute = any(bool(re.search(pat, text_lower)) for pat in cls.DISPUTE_MARKERS)

        # Check for Comparison ('vs', 'or', 'compare', 'difference')
        is_comparison = bool(re.search(r"\b(vs\.?|versus|compare|difference between)\b", text_lower))

        # Extract clean product candidate
        # Strip common stopwords while preserving numbers like 141, 131
        cleaned = re.sub(r"[^\w\s\u0b80-\u0bff-]", " ", text)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()

        return NormalizedQuery(
            original_text=text,
            cleaned_text=cleaned,
            language=lang,
            extracted_order_id=order_id,
            extracted_amount_inr=amount_inr,
            is_dispute=is_dispute,
            is_comparison=is_comparison,
            is_human_request=is_human
        )
