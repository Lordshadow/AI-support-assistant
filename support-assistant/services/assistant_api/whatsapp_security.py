"""
WhatsApp Channel Security & Meta Webhook Verification
Complies with Specification Section 15.1.1 (WhatsApp HMAC verification & message deduplication).

Features:
- Validates Meta's X-Hub-Signature-256 header against raw payload using HMAC-SHA256.
- Handles Meta Webhook Verification Challenge (GET hub.mode, hub.challenge, hub.verify_token).
- In-memory message deduplication cache using WhatsApp Message IDs (wamid).
"""

from collections import OrderedDict
from datetime import datetime, timezone, timedelta
import hmac
import hashlib
import threading
from typing import Optional, Tuple


class WhatsAppSecurity:
    """Security utilities for Meta WhatsApp Cloud API webhooks."""

    def __init__(self, app_secret: str, verify_token: str, max_dedup_cache_size: int = 10000, dedup_ttl_seconds: int = 86400):
        self.app_secret = app_secret.encode("utf-8")
        self.verify_token = verify_token
        self.max_dedup_cache_size = max_dedup_cache_size
        self.dedup_ttl_seconds = dedup_ttl_seconds
        
        self._seen_messages: OrderedDict[str, datetime] = OrderedDict()
        self._lock = threading.Lock()

    def verify_webhook_subscription(
        self,
        mode: Optional[str],
        token: Optional[str],
        challenge: Optional[str]
    ) -> Tuple[bool, Optional[str]]:
        """
        Validates Meta's initial subscription handshake (GET request).
        Returns (is_valid, challenge_or_error_message).
        """
        if mode == "subscribe" and token == self.verify_token:
            return True, challenge
        return False, "Verification token or mode mismatch."

    def verify_signature(self, raw_body: bytes, signature_header: Optional[str]) -> bool:
        """
        Validates the X-Hub-Signature-256 header from Meta.
        Uses constant-time comparison to prevent timing attacks.
        """
        if not signature_header or not signature_header.startswith("sha256="):
            return False

        expected_signature = "sha256=" + hmac.new(
            self.app_secret,
            raw_body,
            hashlib.sha256
        ).hexdigest()

        return hmac.compare_digest(expected_signature, signature_header)

    def is_duplicate(self, message_id: str) -> bool:
        """
        Checks if a WhatsApp message ID (wamid) was already processed.
        Automatically purges expired IDs.
        """
        if not message_id:
            return False

        now = datetime.now(timezone.utc)
        with self._lock:
            # Purge expired entries from the front of the OrderedDict
            while self._seen_messages:
                oldest_id, timestamp = next(iter(self._seen_messages.items()))
                if (now - timestamp).total_seconds() > self.dedup_ttl_seconds:
                    self._seen_messages.pop(oldest_id)
                else:
                    break

            if message_id in self._seen_messages:
                return True

            # Register message ID
            if len(self._seen_messages) >= self.max_dedup_cache_size:
                self._seen_messages.popitem(last=False)

            self._seen_messages[message_id] = now
            return False
