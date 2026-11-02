"""
PII Masking Utility for Privacy & DPDP Compliance
Complies with Specification Section 14.3 (Privacy under DPDP Act) and 15.1.11.

Masks sensitive personal identifiers (phone numbers, email addresses, payment cards)
in logs, audit traces, and customer-facing drafts.
"""

import re


class PIIMasker:
    """Production PII scrubber conforming to DPDP data minimization standards."""

    # Regex patterns
    EMAIL_PATTERN = re.compile(r"\b([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*([A-Za-z0-9])@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")
    PHONE_PATTERN = re.compile(r"(?:\+91[\-\s]?)?[6-9]\d{9}\b")
    CARD_PATTERN = re.compile(r"\b(?:\d{4}[-\s]?){3}(\d{4})\b")
    OTP_PATTERN = re.compile(r"\b(?:otp|code|verification code)[\s:=]+(\d{4,6})\b", re.I)

    @classmethod
    def mask_email(cls, email: str) -> str:
        """e.g., cust42@example.com -> c***2@example.com"""
        match = cls.EMAIL_PATTERN.search(email)
        if not match:
            return email
        first, last, domain = match.group(1), match.group(2), match.group(3)
        return f"{first}***{last}@{domain}"

    @classmethod
    def mask_phone(cls, phone: str) -> str:
        """e.g., 9876543210 -> ******3210, +91 9876543210 -> +91 ******3210"""
        digits = re.sub(r"\D", "", phone)
        if len(digits) >= 10:
            last_four = digits[-4:]
            prefix = "+91 " if "+91" in phone else ""
            return f"{prefix}******{last_four}"
        return phone

    @classmethod
    def mask_card(cls, card: str) -> str:
        """e.g., 4111-2222-3333-4444 -> ****-****-****-4444"""
        match = cls.CARD_PATTERN.search(card)
        if match:
            last_four = match.group(1)
            return f"****-****-****-{last_four}"
        return card

    @classmethod
    def mask_text(cls, text: str) -> str:
        """
        Comprehensive scrubber for logs and audit trace payloads.
        Masks emails, phone numbers, credit cards, and OTPs.
        """
        if not text:
            return ""

        # 1. Mask credit cards
        scrubbed = cls.CARD_PATTERN.sub(r"****-****-****-\1", text)

        # 2. Mask phone numbers
        def _replace_phone(m):
            num = m.group(0)
            digits = re.sub(r"\D", "", num)
            return f"******{digits[-4:]}"

        scrubbed = cls.PHONE_PATTERN.sub(_replace_phone, scrubbed)

        # 3. Mask emails
        scrubbed = cls.EMAIL_PATTERN.sub(r"\1***\2@\3", scrubbed)

        # 4. Mask OTP codes
        scrubbed = cls.OTP_PATTERN.sub(r"code: ******", scrubbed)

        return scrubbed
