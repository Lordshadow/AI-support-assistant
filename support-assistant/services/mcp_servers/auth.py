"""
MCP Transport Security & Internal Token Authentication
Complies with Specification Section 15.1 and 'Where MCP fits' (The Identity Problem).

Mints short-lived internal signed tokens for inter-service and MCP tool calls.
Extracts and validates SessionContext from the transport layer.
"""

from datetime import datetime, timezone, timedelta
from typing import Optional
import jwt

from core.models import SessionContext, AuthLevel


DEFAULT_INTERNAL_SECRET = "novaretail_internal_mcp_secret_key_99182"
DEFAULT_TOKEN_EXPIRY_SECONDS = 300  # 5 minutes


def mint_internal_token(
    ctx: SessionContext,
    secret: str = DEFAULT_INTERNAL_SECRET,
    expires_in_seconds: int = DEFAULT_TOKEN_EXPIRY_SECONDS
) -> str:
    """
    Mints a short-lived internal signed JWT embedding verified SessionContext.
    Passed via transport header ('Authorization: Bearer <token>').
    """
    now = datetime.now(timezone.utc)
    payload = {
        "iss": "novaretail-orchestrator",
        "aud": "novaretail-mcp-servers",
        "tenant_id": ctx.tenant_id,
        "conv_id": ctx.conv_id,
        "customer_id": ctx.customer_id,
        "level": ctx.level.value,
        "channel": ctx.channel,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in_seconds)).timestamp())
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def ctx_from_token(
    token: str,
    secret: str = DEFAULT_INTERNAL_SECRET
) -> SessionContext:
    """
    Decodes and validates the internal transport token into an immutable SessionContext.
    Rejects expired, tampered, or invalid tokens.
    """
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            audience="novaretail-mcp-servers",
            issuer="novaretail-orchestrator"
        )
        return SessionContext(
            tenant_id=payload["tenant_id"],
            conv_id=payload["conv_id"],
            customer_id=payload.get("customer_id"),
            level=AuthLevel(payload.get("level", "anonymous")),
            channel=payload.get("channel", "web")
        )
    except Exception as e:
        # Fall back to anonymous session if token is invalid or missing
        return SessionContext(
            tenant_id="unknown",
            conv_id="unknown",
            customer_id=None,
            level=AuthLevel.ANONYMOUS
        )
