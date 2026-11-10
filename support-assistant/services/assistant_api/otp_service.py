"""
OTP Step-up Authentication Service
Complies with Specification Section 15.1.3 (OTP Step-up).

Features:
- 6-digit numeric OTP generation using secrets module.
- SHA-256 hashed storage with per-challenge cryptographic salt.
- 5-minute Time-To-Live (TTL).
- Max 3 attempts before challenge invalidation.
- Constant-time comparison via hmac.compare_digest.
- State transitions SessionContext to AuthLevel.VERIFIED.
"""

from dataclasses import dataclass, replace
from datetime import datetime, timezone, timedelta
import hashlib
import hmac
import secrets
from typing import Dict, Optional, Tuple

from core.models import SessionContext, AuthLevel


DEFAULT_OTP_TTL_MINUTES = 5
MAX_ATTEMPTS = 3
VERIFIED_SESSION_TTL_MINUTES = 15


@dataclass
class OTPRecord:
    challenge_id: str
    tenant_id: str
    conv_id: str
    customer_id: Optional[str]
    destination: str
    salt: str
    hashed_code: str
    created_at: datetime
    expires_at: datetime
    attempts: int = 0
    is_verified: bool = False
    is_invalidated: bool = False


class OTPService:
    """Manages OTP lifecycle for step-up verification."""

    def __init__(self, ttl_minutes: int = DEFAULT_OTP_TTL_MINUTES, max_attempts: int = MAX_ATTEMPTS):
        self.ttl_minutes = ttl_minutes
        self.max_attempts = max_attempts
        self._challenges: Dict[str, OTPRecord] = {}

    def _hash_code(self, code: str, salt: str) -> str:
        """Derives SHA-256 digest of code + salt."""
        return hashlib.sha256(f"{salt}:{code}".encode("utf-8")).hexdigest()

    def invalidate_challenge(self, challenge_id: str) -> None:
        """Invalidate a challenge when the delivery adapter rejects it."""
        record = self._challenges.get(challenge_id)
        if record:
            record.is_invalidated = True

    def generate_otp_code(self) -> str:
        """Generates a secure 6-digit numeric OTP string."""
        number = secrets.randbelow(900000) + 100000
        return str(number)

    def create_challenge(
        self,
        session: SessionContext,
        destination: str,
        fixed_code_for_test: Optional[str] = None
    ) -> Tuple[str, str]:
        """
        Creates an OTP challenge for the session.
        Returns:
            (challenge_id, raw_code)
        """
        code = fixed_code_for_test if fixed_code_for_test else self.generate_otp_code()
        challenge_id = f"otp_{secrets.token_hex(8)}"
        salt = secrets.token_hex(16)
        hashed_code = self._hash_code(code, salt)

        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(minutes=self.ttl_minutes)

        record = OTPRecord(
            challenge_id=challenge_id,
            tenant_id=session.tenant_id,
            conv_id=session.conv_id,
            customer_id=str(session.customer_id) if session.customer_id is not None else None,
            destination=destination,
            salt=salt,
            hashed_code=hashed_code,
            created_at=now,
            expires_at=expires_at,
            attempts=0,
            is_verified=False,
            is_invalidated=False
        )

        self._challenges[challenge_id] = record
        return challenge_id, code

    def verify_otp(
        self,
        challenge_id: str,
        candidate_code: str,
        session: SessionContext
    ) -> Tuple[bool, str, SessionContext]:
        """
        Verifies the user-submitted OTP candidate.
        Uses constant-time comparison to prevent timing leaks.
        Transitions session to AuthLevel.VERIFIED on success.

        Returns:
            (success: bool, message: str, updated_session: SessionContext)
        """
        record = self._challenges.get(challenge_id)
        if not record:
            return False, "OTP challenge not found or expired.", session

        now = datetime.now(timezone.utc)

        if record.is_invalidated:
            return False, "This OTP has been invalidated due to too many failed attempts.", session

        if record.is_verified:
            return False, "This OTP challenge has already been verified and consumed.", session

        if (record.tenant_id, record.conv_id, record.customer_id) != (
            session.tenant_id, session.conv_id,
            str(session.customer_id) if session.customer_id is not None else None,
        ):
            return False, "OTP challenge does not belong to this customer session.", session

        if now > record.expires_at:
            record.is_invalidated = True
            return False, "OTP code has expired. Please request a new one.", session

        record.attempts += 1
        candidate_hash = self._hash_code(candidate_code.strip(), record.salt)

        if not hmac.compare_digest(candidate_hash, record.hashed_code):
            remaining = self.max_attempts - record.attempts
            if remaining <= 0:
                record.is_invalidated = True
                return False, "Invalid OTP code. Maximum attempts exceeded. Challenge invalidated.", session
            return False, f"Invalid OTP code. {remaining} attempt(s) remaining.", session

        # Code matched successfully!
        record.is_verified = True
        verified_until = now + timedelta(minutes=VERIFIED_SESSION_TTL_MINUTES)
        
        # Upgrade SessionContext to VERIFIED
        updated_session = replace(
            session,
            level=AuthLevel.VERIFIED,
            verified_until=verified_until
        )

        return True, "OTP successfully verified.", updated_session
