"""
Channel Gateway & Assistant API Service
Complies with Specification Section 15.1 (Auth Hierarchy & Channels) and 15.2 (FastAPI / ASGI Gateway).

Endpoints:
- POST /chat/messages: Web chat with JWT Bearer token parsing & session tracking
- GET  /webhooks/whatsapp: Meta webhook subscription verification
- POST /webhooks/whatsapp: Meta webhook event receiver with HMAC verification & deduplication
- POST /auth/otp/send: Step-up OTP challenge issuance
- POST /auth/otp/verify: Step-up OTP challenge verification
- GET  /health: Service health probe

Implements standard ASGI 3.0 interface for zero-dependency execution with uvicorn or any ASGI runner.
"""

from datetime import datetime, timezone, timedelta
import json
import logging
import os
import re
import hmac
import base64
from pathlib import Path
import re
from typing import Any, Callable, Dict, List, Optional, Tuple
import urllib.parse
import uuid
from dataclasses import replace

from pydantic import BaseModel, Field

from core.models import SessionContext, AuthLevel, PageContext
from services.assistant_api.jwt_auth import verify_customer_token
from services.assistant_api.otp_service import OTPService
from services.assistant_api.whatsapp_security import WhatsAppSecurity
from services.worker.orchestrator import WorkerOrchestrator, OrchestratorResponse

logger = logging.getLogger(__name__)


# ============================================================================
# Pydantic Schemas
# ============================================================================

class ChatMessageRequest(BaseModel):
    message: str = Field(..., min_length=1)
    conv_id: Optional[str] = None
    tenant_id: str = "demo-shop"
    channel: str = "web"
    customer_id: Optional[str] = None
    user_id: Optional[str] = None
    token: Optional[str] = None
    customer_token: Optional[str] = None
    page_context: Optional[Dict[str, Any]] = None


class ChatMessageResponse(BaseModel):
    conv_id: str
    reply: str
    language: str
    auth_level: str
    requires_step_up: bool
    trace_id: Optional[str] = None
    latency_ms: float = 0.0


class SendOTPRequest(BaseModel):
    conv_id: str
    tenant_id: str = "demo-shop"


class SendOTPResponse(BaseModel):
    challenge_id: str
    status: str
    destination: str


class VerifyOTPRequest(BaseModel):
    challenge_id: str
    candidate_code: str
    conv_id: str
    tenant_id: str = "demo-shop"


class VerifyOTPResponse(BaseModel):
    success: bool
    message: str
    auth_level: str


# ============================================================================
# Gateway Application
# ============================================================================

class GatewayApp:
    """Production Channel Gateway and Assistant API Router."""

    def __init__(
        self,
        orchestrator: WorkerOrchestrator,
        otp_service: Optional[OTPService] = None,
        whatsapp_security: Optional[WhatsAppSecurity] = None,
        company_jwt_secret: Optional[str] = None,
        support_desk_service: Optional[Any] = None,
        tenant_origins: Optional[Dict[str, List[str]]] = None,
        dashboard_api: Optional[Any] = None,
        dependency_healthchecks: bool = False,
        otp_delivery: Optional[Any] = None,
        speech_adapter: Optional[Any] = None,
        tenant_aliases: Optional[Dict[str, str]] = None,
        openwa_shared_secret: Optional[str] = None,
    ):
        self.orchestrator = orchestrator
        self.otp_service = otp_service or OTPService()
        self.whatsapp_security = whatsapp_security
        self.company_jwt_secret = company_jwt_secret
        self.support_desk_service = support_desk_service
        self.dashboard_api = dashboard_api
        self.dependency_healthchecks = dependency_healthchecks
        self.otp_delivery = otp_delivery
        self.speech_adapter = speech_adapter
        self.openwa_shared_secret = (openwa_shared_secret or os.getenv("OPENWA_SHARED_SECRET", "")).strip()
        self._openwa_processed_ids: set[str] = set()
        self.tenant_aliases = dict(tenant_aliases or {})
        self.tenant_origins = tenant_origins if tenant_origins is not None else {
            "demo-shop": ["https://shop.novaretail.com", "http://localhost:3000", "http://127.0.0.1:3000"],
            "tenant_novaretail": ["https://shop.novaretail.com", "http://localhost:3000", "http://127.0.0.1:3000"],
            "ApexStore": ["https://shop.novaretail.com", "http://localhost:3000", "http://127.0.0.1:3000"],
        }
        self.static_dir = Path(__file__).parent.parent.parent / "static"

        # Session storage: (tenant_id, conv_id) -> SessionContext
        self._session_store: Dict[Tuple[str, str], SessionContext] = {}
        self._storefront_otp_challenges: Dict[str, Tuple[str, str, str]] = {}

    def is_origin_allowed(self, tenant_id: str, origin: Optional[str]) -> bool:
        """
        Validates request origin against tenant allowlist (Spec 16.1 & 16.2).
        Returns True if allowed, False if disallowed.
        """
        if not origin:
            return True  # Server-to-server or non-browser client without Origin header

        clean_origin = origin.rstrip("/")
        allowed = self.tenant_origins.get(tenant_id, [])
        # Browser traffic must match an explicit tenant origin. Empty and
        # wildcard lists fail closed; server-to-server clients may omit Origin.
        return bool(allowed) and "*" not in allowed and clean_origin in allowed

    def get_or_create_session(
        self,
        tenant_id: str,
        conv_id: str,
        auth_header: Optional[str] = None,
        channel: str = "web"
    ) -> SessionContext:
        """
        Resolves or constructs the SessionContext.
        Preserves active VERIFIED status if session was previously stepped up.
        """
        key = (tenant_id, conv_id)
        now = datetime.now(timezone.utc)

        # Check existing session
        existing = self._session_store.get(key)
        if existing and existing.level == AuthLevel.VERIFIED and existing.verified_until and now > existing.verified_until:
            existing = SessionContext(
                tenant_id=tenant_id,
                conv_id=conv_id,
                customer_id=existing.customer_id,
                level=AuthLevel.IDENTIFIED if existing.customer_id else AuthLevel.ANONYMOUS,
                channel=channel  # type: ignore
            )
            self._session_store[key] = existing

        if existing and not auth_header:
            return existing

        # Evaluate Bearer token if provided
        if auth_header:
            kwargs = {"auth_header": auth_header, "expected_tenant": tenant_id, "conv_id": conv_id}
            if self.company_jwt_secret:
                kwargs["secret"] = self.company_jwt_secret
            session = verify_customer_token(**kwargs)
            storefront_token = self._get_storefront_customer_token(auth_header, session.customer_id)
            if storefront_token:
                session = replace(session, storefront_customer_token=storefront_token)
        else:
            session = SessionContext(
                tenant_id=tenant_id,
                conv_id=conv_id,
                customer_id=None,
                level=AuthLevel.ANONYMOUS,
                channel=channel  # type: ignore
            )

        # If previous session was actively VERIFIED and not expired, preserve VERIFIED status
        if (
            existing
            and existing.level == AuthLevel.VERIFIED
            and existing.verified_until
            and now <= existing.verified_until
        ):
            if not existing.customer_id or not session.customer_id or existing.customer_id == session.customer_id:
                session = SessionContext(
                    tenant_id=tenant_id,
                    conv_id=conv_id,
                    customer_id=session.customer_id or existing.customer_id,
                    level=AuthLevel.VERIFIED,
                    channel=channel,  # type: ignore
                    verified_until=existing.verified_until,
                    storefront_customer_token=session.storefront_customer_token or existing.storefront_customer_token,
                    storefront_refund_verification_token=existing.storefront_refund_verification_token,
                )

        self._session_store[key] = session
        return session

    @staticmethod
    def _get_storefront_customer_token(auth_header: str, customer_id: Optional[str]) -> Optional[str]:
        """Carry ApexStore's signed token to its API, which verifies ownership cryptographically."""
        if not customer_id or not auth_header.startswith("Bearer "):
            return None
        raw_token = auth_header.split(" ", 1)[1].strip()
        try:
            import jwt
            header = jwt.get_unverified_header(raw_token)
            claims = jwt.decode(raw_token, options={"verify_signature": False, "verify_aud": False})
            if (
                # Treat this as an untrusted storefront credential and pass it
                # only to the shop API. Including malformed/legacy algorithms
                # here makes the repository fail closed instead of consulting
                # cached orders under claims the gateway has not verified.
                header.get("alg") in {"RS256", "HS256"}
                and claims.get("iss") in {"apexstore", "ApexStore"}
                and str(claims.get("sub")) == str(customer_id)
                and claims.get("exp", 0) > datetime.now(timezone.utc).timestamp()
            ):
                return raw_token
        except Exception:
            return None
        return None

    async def handle_chat_message(
        self,
        payload: Dict[str, Any],
        auth_header: Optional[str] = None
    ) -> Tuple[int, Dict[str, Any]]:
        """Handles POST /chat/messages."""
        try:
            req = ChatMessageRequest(**payload)
        except Exception as e:
            return 422, {"detail": str(e)}

        if not auth_header:
            if req.customer_token:
                auth_header = f"Bearer {req.customer_token}"
            elif req.token:
                auth_header = f"Bearer {req.token}"

        conv_id = req.conv_id or f"conv_{uuid.uuid4().hex[:12]}"
        request_tenant = req.tenant_id
        effective_tenant = self.tenant_aliases.get(request_tenant, request_tenant)
        page_context = self._parse_page_context(req.page_context)
        session = self.get_or_create_session(
            tenant_id=request_tenant,
            conv_id=conv_id,
            auth_header=auth_header,
            channel=req.channel
        )
        session = replace(session, tenant_id=effective_tenant, page_context=page_context)
        self._session_store[(effective_tenant, conv_id)] = session

        # customer_id/user_id in a public request are untrusted hints. Customer
        # identity must come from a verified customer token (auth_header above).

        orch_response: OrchestratorResponse = await self.orchestrator.process_turn(
            user_message=req.message,
            ctx=session
        )

        requires_step_up = (orch_response.requires_action == "needs_otp")

        resp = ChatMessageResponse(
            conv_id=conv_id,
            reply=orch_response.reply,
            language=orch_response.language,
            auth_level=session.level.value,
            requires_step_up=requires_step_up,
            trace_id=orch_response.trace_id,
            latency_ms=orch_response.latency_ms
        )
        return 200, resp.model_dump()

    @staticmethod
    def _parse_page_context(raw: Optional[Dict[str, Any]]) -> Optional[PageContext]:
        """Validate untrusted browser context before it enters the agent context."""
        if not raw:
            return None
        url = str(raw.get("url", ""))[:2048]
        page_type = str(raw.get("page_type", "other"))
        allowed_types = {
            "product_details", "product_listing", "cart", "checkout",
            "order_details", "dashboard", "other"
        }
        if not url or page_type not in allowed_types:
            return None

        def identifier(value: Any, pattern: str) -> Optional[str]:
            value = str(value).strip().upper() if value is not None else ""
            return value if value and re.fullmatch(pattern, value) else None

        return PageContext(
            url=url,
            page_type=page_type,  # type: ignore[arg-type]
            product_id=identifier(raw.get("product_id"), r"[A-Z0-9][A-Z0-9_-]{0,63}"),
            order_id=identifier(raw.get("order_id"), r"ORD-[-A-Za-z0-9]+"),
            cart_id=identifier(raw.get("cart_id"), r"CART-[A-Z0-9_-]+"),
            title=str(raw.get("title", ""))[:200] or None,
        )

    async def handle_whatsapp_webhook_get(
        self,
        query_params: Dict[str, str]
    ) -> Tuple[int, str]:
        """Handles GET /webhooks/whatsapp (Meta Verification Challenge)."""
        if self.whatsapp_security is None:
            return 503, "WhatsApp webhook is not configured."
        mode = query_params.get("hub.mode")
        token = query_params.get("hub.verify_token")
        challenge = query_params.get("hub.challenge")

        is_valid, result = self.whatsapp_security.verify_webhook_subscription(
            mode=mode,
            token=token,
            challenge=challenge
        )
        if is_valid:
            return 200, result or ""
        return 403, result or "Forbidden"

    async def handle_whatsapp_webhook_post(
        self,
        raw_body: bytes,
        signature_header: Optional[str]
    ) -> Tuple[int, Dict[str, Any]]:
        """Handles POST /webhooks/whatsapp (Meta Message Notification)."""
        if self.whatsapp_security is None:
            return 503, {"detail": "WhatsApp webhook is not configured."}
        # 1. Signature Check
        if not self.whatsapp_security.verify_signature(raw_body, signature_header):
            return 401, {"detail": "Invalid Meta webhook signature."}

        # 2. Parse Payload
        try:
            data = json.loads(raw_body.decode("utf-8"))
        except Exception:
            return 400, {"detail": "Invalid JSON body."}

        # Extract message elements from standard Meta Cloud API schema
        entry = (data.get("entry") or [{}])[0]
        change = (entry.get("changes") or [{}])[0]
        value = change.get("value") or {}
        messages = value.get("messages") or []

        if not messages:
            # Acknowledgement of delivery receipt or status update
            return 200, {"status": "event_acknowledged", "detail": "No user message to process"}

        msg = messages[0]
        message_id = msg.get("id", "")
        sender_phone = msg.get("from", "")
        msg_type = msg.get("type", "text")

        text_body = ""
        transcription_info = None

        if msg_type in ("audio", "voice"):
            audio_obj = msg.get("audio") or msg.get("voice") or {}
            if self.speech_adapter:
                audio_bytes = b""
                raw_audio_content = audio_obj.get("data") or audio_obj.get("audio_bytes")
                if raw_audio_content:
                    if isinstance(raw_audio_content, str):
                        import base64
                        try:
                            audio_bytes = base64.b64decode(raw_audio_content)
                        except Exception:
                            audio_bytes = raw_audio_content.encode("utf-8")
                    elif isinstance(raw_audio_content, bytes):
                        audio_bytes = raw_audio_content
                if not audio_bytes:
                    return 200, {
                        "status": "voice_media_unavailable",
                        "message_id": message_id,
                        "reply": "I couldn't access that voice note. Please send it again or type your message.",
                    }
                content_type = audio_obj.get("mime_type", "audio/ogg; codecs=opus")
                text_body = await self.speech_adapter.transcribe(audio_bytes, content_type)
                transcription_info = {
                    "is_voice": True,
                    "media_id": audio_obj.get("id"),
                    "transcript": text_body
                }
            else:
                return 200, {
                    "status": "voice_unsupported",
                    "message_id": message_id,
                    "sender": sender_phone,
                    "reply": "Voice notes are currently not supported because the speech-to-text service is not configured.",
                }
        else:
            text_obj = msg.get("text") or {}
            text_body = text_obj.get("body", "")

        # 3. Message Deduplication (prevent double execution on network retry)
        if self.whatsapp_security.is_duplicate(message_id):
            return 200, {"status": "duplicate_ignored", "message_id": message_id}

        # 4. Resolve WhatsApp Session
        conv_id = f"wa_{sender_phone}"
        session = self.get_or_create_session(
            tenant_id="demo-shop",
            conv_id=conv_id,
            auth_header=None,
            channel="whatsapp"
        )

        # 5. Process turn
        orch_response = await self.orchestrator.process_turn(
            user_message=text_body,
            ctx=session
        )

        resp_payload: Dict[str, Any] = {
            "status": "delivered",
            "message_id": message_id,
            "sender": sender_phone,
            "reply": orch_response.reply,
            "language": orch_response.language,
            "trace_id": orch_response.trace_id
        }
        if transcription_info:
            resp_payload["transcription"] = transcription_info

        return 200, resp_payload

    async def handle_openwa_message(self, payload: Dict[str, Any], authorization: Optional[str]) -> Tuple[int, Dict[str, Any]]:
        """Accept an authenticated message/media event from the OpenWA companion process."""
        if not self.openwa_shared_secret:
            return 503, {"detail": "OpenWA integration is not configured."}
        supplied = authorization or ""
        expected = f"Bearer {self.openwa_shared_secret}"
        if not supplied.isascii() or not hmac.compare_digest(supplied, expected):
            return 401, {"detail": "Unauthorized OpenWA integration request."}

        message_id = str(payload.get("message_id", ""))[:256]
        sender = str(payload.get("sender", ""))[:256]
        if not message_id or not sender or payload.get("from_me"):
            return 422, {"detail": "A valid incoming message ID and sender are required."}
        if message_id in self._openwa_processed_ids:
            return 200, {"status": "duplicate_ignored", "message_id": message_id}

        message_type = str(payload.get("type", "chat")).lower()
        user_message = str(payload.get("text", ""))[:8000]
        transcription_info = None
        if message_type in ("audio", "ptt", "voice"):
            encoded = payload.get("audio_base64")
            if not isinstance(encoded, str) or len(encoded) > 28_000_000 or self.speech_adapter is None:
                return 200, {"status": "voice_unsupported", "reply": "I couldn't process that voice note. Please type your message."}
            try:
                audio_bytes = base64.b64decode(encoded, validate=True)
            except Exception:
                return 422, {"detail": "Invalid audio data."}
            if not audio_bytes or len(audio_bytes) > 20 * 1024 * 1024:
                return 413, {"detail": "Audio is empty or exceeds the 20 MB limit."}
            try:
                user_message = await self.speech_adapter.transcribe(
                    audio_bytes, str(payload.get("mime_type") or "audio/ogg")[:128]
                )
            except Exception:
                logger.exception("OpenWA speech transcription failed")
                return 200, {"status": "voice_transcription_failed", "reply": "I couldn't understand that voice note. Please try again or type your message."}
            transcription_info = {"is_voice": True, "transcript": user_message}
            if not user_message:
                return 200, {"status": "voice_transcription_empty", "reply": "I couldn't hear a clear request. Please try again or type your message."}
        if not user_message.strip():
            return 200, {"status": "empty_message", "reply": "Please send a text message or a voice note."}

        self._openwa_processed_ids.add(message_id)
        if len(self._openwa_processed_ids) > 10000:
            self._openwa_processed_ids.clear()
            self._openwa_processed_ids.add(message_id)
        conv_id = f"wa_{sender}"
        session = self.get_or_create_session("demo-shop", conv_id, auth_header=None, channel="whatsapp")
        result = await self.orchestrator.process_turn(user_message=user_message, ctx=session)
        response = {"status": "processed", "message_id": message_id, "reply": result.reply,
                    "language": result.language, "trace_id": result.trace_id}
        if transcription_info:
            response["transcription"] = transcription_info
        return 200, response

    async def handle_send_otp(self, payload: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        """Handles POST /auth/otp/send."""
        try:
            req = SendOTPRequest(**payload)
        except Exception as e:
            return 422, {"detail": str(e)}

        if self.otp_delivery is None and not payload.get("_authorization"):
            return 503, {
                "detail": "OTP delivery is not configured.",
                "code": "OTP_DELIVERY_UNAVAILABLE",
            }

        session = self.get_or_create_session(
            tenant_id=req.tenant_id,
            conv_id=req.conv_id,
            auth_header=payload.get("_authorization")
        )
        if not session.customer_id:
            return 401, {"detail": "Sign in to verify your account email.", "code": "CUSTOMER_AUTH_REQUIRED"}

        order_id = str(payload.get("order_id") or "").strip().upper()
        if session.storefront_customer_token:
            if not re.fullmatch(r"ORD-[A-Z0-9_-]{1,60}", order_id):
                return 422, {"detail": "A valid order ID is required for refund verification."}
            base_url = os.getenv("APEXSTORE_CATALOG_API_URL", "").rstrip("/")
            api_token = os.getenv("APEXSTORE_CATALOG_API_TOKEN", "").strip()
            if not base_url or not api_token:
                return 503, {"detail": "Store refund verification is not configured."}
            try:
                import httpx
                # Storefront OTP delivery waits for SMTP; five seconds caused
                # the gateway to time out even when the email was sent.
                async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=3.0)) as client:
                    response = await client.post(
                        f"{base_url}/orders/{urllib.parse.quote(order_id, safe='')}/otp",
                        headers={"Authorization": f"Bearer {api_token}"},
                        json={
                            "customer_id": int(session.customer_id),
                            "customer_token": session.storefront_customer_token,
                        },
                    )
                if response.status_code != 200:
                    if response.status_code == 429:
                        return 429, {
                            "detail": "Please wait before requesting another refund verification code.",
                            "code": "OTP_RATE_LIMITED",
                        }
                    return 503, {"detail": "We could not send a refund verification code. Please try again."}
                sent_to = response.json().get("sent_to", "your account email")
                challenge_id = f"store_{uuid.uuid4().hex}"
                self._storefront_otp_challenges[challenge_id] = (req.tenant_id, req.conv_id, order_id)
                return 200, {"challenge_id": challenge_id, "status": "sent", "destination": sent_to}
            except Exception:
                debug_code = f"OTP-SEND-{uuid.uuid4().hex[:12].upper()}"
                logger.exception("Could not request storefront refund verification; debug_code=%s", debug_code)
                return 503, {
                    "detail": "We could not send a refund verification code. Please try again.",
                    "_debug_code": debug_code,
                }

        if self.otp_delivery is None:
            return 503, {
                "detail": "OTP delivery is not configured.",
                "code": "OTP_DELIVERY_UNAVAILABLE",
            }
        destination = await self._resolve_customer_email(session.customer_id, payload.get("_authorization"))
        if not destination:
            return 503, {"detail": "We could not access the verified email on your account.", "code": "CUSTOMER_EMAIL_UNAVAILABLE"}

        challenge_id, raw_code = self.otp_service.create_challenge(
            session=session,
            destination=destination
        )

        try:
            accepted = await self.otp_delivery.send_otp(destination, raw_code)
        except Exception:
            accepted = False
        if not accepted:
            self.otp_service.invalidate_challenge(challenge_id)
            return 502, {
                "detail": "OTP delivery could not be accepted.",
                "code": "OTP_DELIVERY_FAILED",
            }

        # Never return the raw code; acknowledge only after adapter acceptance.
        return 200, {
            "challenge_id": challenge_id,
            "status": "sent",
            "destination": self._mask_email(destination)
        }

    async def _resolve_customer_email(self, customer_id: str, auth_header: Optional[str]) -> Optional[str]:
        """Resolve email from the storefront using its signed customer token."""
        import httpx

        base_url = os.getenv("APEXSTORE_CATALOG_API_URL", "").rstrip("/")
        api_token = os.getenv("APEXSTORE_CATALOG_API_TOKEN", "").strip()
        customer_token = auth_header.split(" ", 1)[1].strip() if auth_header and auth_header.startswith("Bearer ") else ""
        if not base_url or not api_token or not customer_token or not str(customer_id).isdigit():
            return None
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(
                    f"{base_url}/customers/{customer_id}/email",
                    headers={"Authorization": f"Bearer {api_token}"},
                    params={"customer_token": customer_token},
                )
            if response.status_code != 200:
                return None
            email = response.json().get("email")
            if not isinstance(email, str) or len(email) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
                return None
            return email
        except Exception:
            logger.exception("Could not resolve verified customer email")
            return None

    @staticmethod
    def _mask_email(email: str) -> str:
        local, separator, domain = email.partition("@")
        return f"{local[:1]}***@{domain}" if separator else "your email"

    async def handle_verify_otp(self, payload: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        """Handles POST /auth/otp/verify."""
        try:
            req = VerifyOTPRequest(**payload)
        except Exception as e:
            return 422, {"detail": str(e)}

        key = (req.tenant_id, req.conv_id)
        session = self.get_or_create_session(
            req.tenant_id, req.conv_id, auth_header=payload.get("_authorization")
        )
        if not session.customer_id:
            return 401, {"success": False, "message": "Sign in to verify this code.", "auth_level": session.level.value}

        storefront_challenge = self._storefront_otp_challenges.get(req.challenge_id)
        if storefront_challenge:
            challenge_tenant, challenge_conv, order_id = storefront_challenge
            if (challenge_tenant, challenge_conv) != key:
                return 400, {"success": False, "message": "This verification challenge is invalid or expired.", "auth_level": session.level.value}
            base_url = os.getenv("APEXSTORE_CATALOG_API_URL", "").rstrip("/")
            api_token = os.getenv("APEXSTORE_CATALOG_API_TOKEN", "").strip()
            if not base_url or not api_token or not session.storefront_customer_token:
                return 503, {"success": False, "message": "Store refund verification is unavailable. Please try again.", "auth_level": session.level.value}
            try:
                import httpx
                async with httpx.AsyncClient(timeout=5.0) as client:
                    response = await client.post(
                        f"{base_url}/orders/{urllib.parse.quote(order_id, safe='')}/otp/verify",
                        headers={"Authorization": f"Bearer {api_token}"},
                        json={
                            "customer_id": int(session.customer_id),
                            "customer_token": session.storefront_customer_token,
                            "code": req.candidate_code,
                        },
                    )
                data = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
                if response.status_code != 200 or not data.get("verification_token"):
                    return 400, {"success": False, "message": "That code is invalid or expired. Please check it and try again.", "auth_level": session.level.value}
                verified_session = replace(
                    session,
                    level=AuthLevel.VERIFIED,
                    verified_until=datetime.now(timezone.utc) + timedelta(minutes=15),
                    storefront_refund_verification_token=data["verification_token"],
                )
                self._session_store[key] = verified_session
                self._storefront_otp_challenges.pop(req.challenge_id, None)
                return 200, {"success": True, "message": "Email verified successfully.", "auth_level": verified_session.level.value}
            except Exception:
                debug_code = f"OTP-VERIFY-{uuid.uuid4().hex[:12].upper()}"
                logger.exception("Could not verify storefront refund OTP; debug_code=%s", debug_code)
                return 503, {
                    "success": False,
                    "message": "Store refund verification is unavailable. Please try again.",
                    "auth_level": session.level.value,
                    "_debug_code": debug_code,
                }

        success, message, updated_session = self.otp_service.verify_otp(
            challenge_id=req.challenge_id,
            candidate_code=req.candidate_code,
            session=session
        )

        if success:
            self._session_store[key] = updated_session

        status_code = 200 if success else 400
        return status_code, {
            "success": success,
            "message": message,
            "auth_level": updated_session.level.value
        }

    async def handle_health(self) -> Tuple[int, Dict[str, Any]]:
        """Handles GET /health."""
        dependencies: Dict[str, str] = {}
        if self.dependency_healthchecks:
            try:
                from sqlalchemy import text
                from db.session import get_async_session
                async with get_async_session() as session:
                    await session.execute(text("SELECT 1"))
                dependencies["postgres"] = "healthy"
            except Exception:
                dependencies["postgres"] = "unhealthy"
            client = None
            try:
                from redis.asyncio import Redis
                import os
                client = Redis(
                    host=os.getenv("REDIS_HOST", "redis"),
                    port=int(os.getenv("REDIS_PORT", "6379")),
                    socket_connect_timeout=2,
                    socket_timeout=2,
                )
                await client.ping()
                dependencies["redis"] = "healthy"
            except Exception:
                dependencies["redis"] = "unhealthy"
            finally:
                if client is not None:
                    await client.aclose()
            if any(state != "healthy" for state in dependencies.values()):
                return 503, {
                    "status": "unhealthy",
                    "service": "novaretail-assistant-api",
                    "dependencies": dependencies,
                }
        return 200, {
            "status": "healthy",
            "service": "novaretail-assistant-api",
            "version": "1.0.0",
            "active_sessions": len(self._session_store),
            "dependencies": dependencies,
        }

    # ========================================================================
    # Standard ASGI 3.0 Handler
    # ========================================================================

    async def __call__(self, scope: Dict[str, Any], receive: Callable, send: Callable) -> None:
        """ASGI 3.0 application interface for uvicorn/hypercorn."""
        if scope["type"] != "http":
            return

        path = scope.get("path", "")
        if self.dashboard_api and (
            path.startswith("/api/admin/v1/") or path.startswith("/desk/refunds/")
        ):
            await self.dashboard_api(scope, receive, send)
            return

        method = scope["method"]
        path = path.rstrip("/") or "/"
        query_string = scope.get("query_string", b"").decode("utf-8")
        query_params = dict(urllib.parse.parse_qsl(query_string))

        # Extract headers
        headers_dict = {
            k.decode("latin1").lower(): v.decode("latin1")
            for k, v in scope.get("headers", [])
        }
        auth_header = headers_dict.get("authorization")
        sig_header = headers_dict.get("x-hub-signature-256")
        origin_header = headers_dict.get("origin") or headers_dict.get("referer")
        if origin_header and origin_header.startswith("http"):
            parsed_origin = urllib.parse.urlparse(origin_header)
            origin_header = f"{parsed_origin.scheme}://{parsed_origin.netloc}"

        # Read request body
        body = bytearray()
        while True:
            message = await receive()
            body.extend(message.get("body", b""))
            if not message.get("more_body", False):
                break
        raw_body = bytes(body)

        # Cross-origin widget requests use the same tenant origin policy as chat.
        cors_tenant = query_params.get("tenant_id", "")
        tenant_candidate = cors_tenant or "demo-shop"
        if raw_body:
            try:
                bdata = json.loads(raw_body.decode("utf-8"))
                if isinstance(bdata, dict) and bdata.get("tenant_id"):
                    tenant_candidate = bdata["tenant_id"]
            except Exception:
                pass
        active_tenant = cors_tenant or tenant_candidate

        if method == "OPTIONS" and (path.startswith("/chat/") or path.startswith("/auth/otp/") or path == "/widget/config"):
            if active_tenant:
                allowed = self.is_origin_allowed(active_tenant, origin_header)
            else:
                allowed = any(self.is_origin_allowed(t, origin_header) for t in self.tenant_origins)
            cors_headers = [(b"content-length", b"0")]
            if allowed and origin_header:
                cors_headers.extend([
                    (b"access-control-allow-origin", origin_header.encode("latin1")),
                    (b"access-control-allow-methods", b"GET, POST, OPTIONS"),
                    (b"access-control-allow-headers", b"Authorization, Content-Type"),
                    (b"access-control-max-age", b"600"), (b"vary", b"Origin"),
                ])
            await send({"type": "http.response.start", "status": 204 if allowed else 403, "headers": cors_headers})
            await send({"type": "http.response.body", "body": b""})
            return

        # Server-side Origin enforcement on /chat/* and /auth/otp/* (Spec 16.1, 16.2)
        if path.startswith("/chat/") or path.startswith("/auth/otp/"):
            if not self.is_origin_allowed(active_tenant, origin_header):
                status_code = 403
                response_body = json.dumps({
                    "detail": f"Origin '{origin_header}' is not authorized for tenant '{active_tenant}'."
                }).encode("utf-8")
                await send({
                    "type": "http.response.start",
                    "status": status_code,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(response_body)).encode("latin1")),
                    ]
                })
                await send({"type": "http.response.body", "body": response_body})
                return

        # Route matching
        status_code = 404
        response_body = b'{"detail": "Not Found"}'
        content_type = "application/json"
        debug_code: Optional[str] = None

        if path == "/health" and method == "GET":
            status_code, resp = await self.handle_health()
            response_body = json.dumps(resp).encode("utf-8")

        elif path == "/widget/config" and method == "GET":
            tenant_id = cors_tenant
            if not tenant_id or not self.is_origin_allowed(tenant_id, origin_header):
                status_code, response_body = 403, b'{"detail":"Widget origin is not authorized."}'
            else:
                try:
                    from db.models import Tenant
                    from db.session import get_async_session
                    async with get_async_session(tenant_id) as session:
                        tenant = await session.get(Tenant, tenant_id)
                        public_settings = tenant.widget_config if tenant and tenant.widget_config else {}
                    status_code, response_body = 200, json.dumps(public_settings).encode("utf-8")
                except Exception:
                    status_code, response_body = 503, b'{"detail":"Widget settings unavailable."}'

        elif path == "/chat/messages" and method == "POST":
            try:
                data = json.loads(raw_body.decode("utf-8")) if raw_body else {}
            except (json.JSONDecodeError, UnicodeDecodeError):
                status_code, response_body = 400, json.dumps({"detail": "Invalid JSON body."}).encode("utf-8")
            else:
                try:
                    status_code, resp = await self.handle_chat_message(data, auth_header=auth_header)
                    response_body = json.dumps(resp).encode("utf-8")
                except Exception as error:
                    debug_code = f"CHAT-{uuid.uuid4().hex[:12].upper()}"
                    logger.exception(
                        "Unhandled chat request failure; debug_code=%s exception_type=%s",
                        debug_code,
                        type(error).__name__,
                    )
                    status_code, response_body = 500, json.dumps({"detail": "Internal server error."}).encode("utf-8")

        elif path == "/webhooks/whatsapp" and method == "GET":
            status_code, resp_text = await self.handle_whatsapp_webhook_get(query_params)
            response_body = resp_text.encode("utf-8")
            content_type = "text/plain"

        elif path == "/webhooks/whatsapp" and method == "POST":
            status_code, resp = await self.handle_whatsapp_webhook_post(raw_body, sig_header)
            response_body = json.dumps(resp).encode("utf-8")

        elif path == "/integrations/openwa/messages" and method == "POST":
            try:
                payload = json.loads(raw_body.decode("utf-8"))
            except Exception:
                status_code, resp = 400, {"detail": "Invalid JSON body."}
            else:
                if not isinstance(payload, dict):
                    status_code, resp = 400, {"detail": "Expected a JSON object."}
                else:
                    status_code, resp = await self.handle_openwa_message(payload, auth_header)
            response_body = json.dumps(resp).encode("utf-8")

        elif path == "/auth/otp/send" and method == "POST":
            try:
                data = json.loads(raw_body.decode("utf-8")) if raw_body else {}
            except (json.JSONDecodeError, UnicodeDecodeError):
                status_code, response_body = 400, json.dumps({"detail": "Invalid JSON body."}).encode("utf-8")
            else:
                try:
                    data["_authorization"] = headers_dict.get("authorization")
                    status_code, resp = await self.handle_send_otp(data)
                    debug_code = resp.pop("_debug_code", debug_code) if isinstance(resp, dict) else debug_code
                    response_body = json.dumps(resp).encode("utf-8")
                except Exception as error:
                    logger.error(
                        "Unhandled OTP delivery request failure; exception_type=%s",
                        type(error).__name__,
                    )
                    status_code, response_body = 500, json.dumps({"detail": "Internal server error."}).encode("utf-8")

        elif path == "/auth/otp/verify" and method == "POST":
            try:
                data = json.loads(raw_body.decode("utf-8")) if raw_body else {}
            except (json.JSONDecodeError, UnicodeDecodeError):
                status_code, response_body = 400, json.dumps({"detail": "Invalid JSON body."}).encode("utf-8")
            else:
                try:
                    data["_authorization"] = headers_dict.get("authorization")
                    status_code, resp = await self.handle_verify_otp(data)
                    debug_code = resp.pop("_debug_code", debug_code) if isinstance(resp, dict) else debug_code
                    response_body = json.dumps(resp).encode("utf-8")
                except Exception as error:
                    logger.error(
                        "Unhandled OTP verification failure; exception_type=%s",
                        type(error).__name__,
                    )
                    status_code, response_body = 500, json.dumps({"detail": "Internal server error."}).encode("utf-8")

        elif path in ("/widget", "/widget/index.html") and method in ("GET", "HEAD"):
            widget_file = self.static_dir / "widget" / "index.html"
            if widget_file.exists():
                status_code = 200
                content_type = "text/html"
                if method == "GET":
                    with open(widget_file, "rb") as f:
                        response_body = f.read()

        elif path in ("/widget/v1/widget.js", "/widget.js") and method in ("GET", "HEAD"):
            widget_js_file = self.static_dir / "widget" / "v1" / "widget.js"
            if widget_js_file.exists():
                status_code = 200
                content_type = "application/javascript; charset=utf-8"
                if method == "GET":
                    with open(widget_js_file, "rb") as f:
                        response_body = f.read()

        elif path in ("/desk", "/desk/index.html") and method in ("GET", "HEAD"):
            desk_file = self.static_dir / "desk" / "index.html"
            if desk_file.exists():
                status_code = 200
                content_type = "text/html"
                if method == "GET":
                    with open(desk_file, "rb") as f:
                        response_body = f.read()

        elif path == "/desk/refunds/pending" and method == "GET":
            if self.support_desk_service:
                pending = await self.support_desk_service.get_pending_refunds()
                status_code = 200
                response_body = json.dumps(pending).encode("utf-8")
            else:
                status_code = 200
                response_body = b"[]"

        elif path.startswith("/desk/refunds/") and path.endswith("/approve") and method == "POST":
            refund_id = path.split("/")[3]
            try:
                data = json.loads(raw_body.decode("utf-8")) if raw_body else {}
                staff_id = data.get("staff_id", "staff_default")
                notes = data.get("notes")
                if self.support_desk_service:
                    ok, msg, res = await self.support_desk_service.approve_refund(refund_id, staff_id, notes)
                    status_code = 200 if ok else 400
                    response_body = json.dumps({"success": ok, "message": msg, "refund": res}).encode("utf-8")
                else:
                    status_code, response_body = 503, b'{"detail": "Support desk service unavailable"}'
            except Exception as e:
                status_code, response_body = 400, json.dumps({"detail": str(e)}).encode("utf-8")

        elif path.startswith("/desk/refunds/") and path.endswith("/reject") and method == "POST":
            refund_id = path.split("/")[3]
            try:
                data = json.loads(raw_body.decode("utf-8")) if raw_body else {}
                staff_id = data.get("staff_id", "staff_default")
                notes = data.get("notes", "")
                if self.support_desk_service:
                    ok, msg, res = await self.support_desk_service.reject_refund(refund_id, staff_id, notes)
                    status_code = 200 if ok else 400
                    response_body = json.dumps({"success": ok, "message": msg, "refund": res}).encode("utf-8")
                else:
                    status_code, response_body = 503, b'{"detail": "Support desk service unavailable"}'
            except Exception as e:
                status_code, response_body = 400, json.dumps({"detail": str(e)}).encode("utf-8")

        elif path.startswith("/desk/traces/") and method == "GET":
            trace_id = path.split("/")[-1]
            if self.support_desk_service:
                trace_view = self.support_desk_service.get_why_this_answer_trace(trace_id)
                if trace_view:
                    status_code = 200
                    response_body = json.dumps(trace_view).encode("utf-8")
                else:
                    status_code = 404
                    response_body = json.dumps({"detail": f"Trace '{trace_id}' not found."}).encode("utf-8")
            else:
                status_code = 503
                response_body = b'{"detail": "Support desk service unavailable"}'

        elif path == "/desk/stats" and method == "GET":
            if self.support_desk_service:
                metrics = await self.support_desk_service.get_metrics()
                status_code = 200
                response_body = json.dumps(metrics).encode("utf-8")
            else:
                status_code = 200
                response_body = b'{"status": "no_desk_service"}'

        # Send ASGI response
        headers_out = [
            (b"content-type", content_type.encode("latin1")),
            (b"content-length", str(len(response_body)).encode("latin1"))
        ]
        if (
            path in ("/widget/config", "/chat/messages", "/auth/otp/send", "/auth/otp/verify")
            and origin_header
            and active_tenant
            and self.is_origin_allowed(active_tenant, origin_header)
        ):
            headers_out.extend([
                (b"access-control-allow-origin", origin_header.encode("latin1")),
                (b"access-control-expose-headers", b"X-Debug-Code"),
                (b"vary", b"Origin"),
            ])
        if debug_code:
            headers_out.append((b"x-debug-code", debug_code.encode("ascii")))
        await send({
            "type": "http.response.start",
            "status": status_code,
            "headers": headers_out
        })
        await send({
            "type": "http.response.body",
            "body": response_body
        })


def create_default_app() -> GatewayApp:
    """Factory creating fully wired production GatewayApp with all services."""
    import os
    from adapters.postgres import (
        PostgresCatalogRepository,
        PostgresOrderRepository,
        PostgresRefundRepository,
    )
    from services.mcp_servers import (
        MCPCatalogServer, MCPOrderServer, MCPRefundServer,
        MCPHandoffServer, MCPToolDispatcher
    )
    from core.router.cache import CacheService
    from core.router.router import AIRouter
    from core.tracing.trace_collector import TraceCollector
    from services.worker.llm_client import GroqLLMClient, MockLLMClient
    from services.support_desk.app import SupportDeskService
    from services.dashboard_api.app import create_dashboard_api
    from db.models import ConversationSession, Escalation
    from db.session import get_async_session
    from sqlalchemy import select

    tenant_id = os.getenv("NOVARETAIL_TENANT_ID", "tenant_novaretail").strip()
    if not tenant_id:
        raise RuntimeError("NOVARETAIL_TENANT_ID must be configured.")

    catalog = PostgresCatalogRepository(tenant_id=tenant_id)
    orders = PostgresOrderRepository(tenant_id=tenant_id)
    refunds = PostgresRefundRepository(
        order_port=orders,
        tenant_id=tenant_id,
        auto_limit_inr=2000,
    )

    async def persist_escalation(
        conv_id: str,
        reason: str,
        summary: str,
        ticket_id: str,
        state: str,
        customer_id: Optional[str],
        channel: str,
    ) -> None:
        async with get_async_session(tenant_id=tenant_id) as session:
            existing = (
                await session.execute(
                    select(Escalation).where(
                        Escalation.tenant_id == tenant_id,
                        Escalation.conv_id == conv_id,
                        Escalation.state.in_(["open", "assigned"]),
                    )
                )
            ).scalars().first()
            if existing:
                return

            conversation = await session.get(ConversationSession, conv_id)
            if not conversation:
                session.add(
                    ConversationSession(
                        conv_id=conv_id,
                        tenant_id=tenant_id,
                        customer_id=customer_id or "anonymous",
                        channel=channel,
                        handoff_state="open",
                    )
                )
            else:
                if customer_id and conversation.customer_id == "anonymous":
                    conversation.customer_id = customer_id
                conversation.handoff_state = "open"

            session.add(
                Escalation(
                    esc_id=ticket_id,
                    conv_id=conv_id,
                    tenant_id=tenant_id,
                    reason=reason,
                    summary=summary,
                    state=state,
                    created_at=datetime.now(timezone.utc),
                )
            )

    dispatcher = MCPToolDispatcher(
        catalog_server=MCPCatalogServer(catalog),
        order_server=MCPOrderServer(orders),
        refund_server=MCPRefundServer(refunds),
        handoff_server=MCPHandoffServer(persist_escalation=persist_escalation)
    )

    cache = CacheService()
    router = AIRouter(cache_service=cache, dispatcher=dispatcher)
    collector = TraceCollector()

    groq_api_key = os.getenv("GROQ_API_KEY", "").strip()
    if groq_api_key:
        llm = GroqLLMClient(api_key=groq_api_key)
    else:
        llm = MockLLMClient()

    whatsapp_app_secret = os.getenv("WHATSAPP_APP_SECRET", "").strip()
    whatsapp_verify_token = os.getenv("WHATSAPP_VERIFY_TOKEN", "").strip()
    whatsapp_security = (
        WhatsAppSecurity(app_secret=whatsapp_app_secret, verify_token=whatsapp_verify_token)
        if whatsapp_app_secret and whatsapp_verify_token
        else None
    )

    orchestrator = WorkerOrchestrator(
        router=router,
        dispatcher=dispatcher,
        llm_client=llm
    )

    desk_service = SupportDeskService(
        refund_adapter=refunds,
        trace_collector=collector
    )

    speech_adapter = None
    if groq_api_key:
        try:
            from adapters.speech.whisper_adapter import GroqWhisperAdapter
            speech_adapter = GroqWhisperAdapter(api_key=groq_api_key)
        except Exception:
            pass
    elif os.getenv("APP_ENV", "development").lower() != "production":
        from adapters.speech.whisper_adapter import MockSpeechAdapter
        speech_adapter = MockSpeechAdapter()

    return GatewayApp(
        orchestrator=orchestrator,
        whatsapp_security=whatsapp_security,
        support_desk_service=desk_service,
        company_jwt_secret=os.getenv("STOREFRONT_JWT_SECRET"),
        dashboard_api=create_dashboard_api(),
        dependency_healthchecks=os.getenv("ENABLE_DEPENDENCY_HEALTHCHECKS", "false").lower() == "true",
        tenant_origins=_configured_tenant_origins(os.getenv("WIDGET_ALLOWED_ORIGINS")),
        tenant_aliases={"ApexStore": tenant_id},
        otp_delivery=(
            MockOTPDeliveryAdapter()
            if os.getenv("OTP_DELIVERY_MODE", "").lower() == "mock"
            else SMTPOTPDeliveryAdapter.from_environment()
        ),
        speech_adapter=speech_adapter,
        openwa_shared_secret=os.getenv("OPENWA_SHARED_SECRET"),
    )


def _configured_tenant_origins(raw: Optional[str]) -> Optional[Dict[str, List[str]]]:
    """Parse explicit allowlist configuration; absent config uses secure defaults."""
    if raw is None:
        return None
    origins = [value.strip().rstrip("/") for value in raw.split(",") if value.strip()]
    return {
        "demo-shop": origins,
        "tenant_novaretail": origins,
        "ApexStore": origins,
    }


class MockOTPDeliveryAdapter:
    """Local QA-only OTP sink; never sends externally or exposes codes over HTTP."""

    def __init__(self):
        self.deliveries: List[Dict[str, str]] = []

    async def send_otp(self, destination: str, code: str) -> bool:
        self.deliveries.append({"destination": destination, "code": code})
        return True


class SMTPOTPDeliveryAdapter:
    """Send step-up codes by email through the configured SMTP service."""

    def __init__(self, host: str, port: int, username: str, password: str, sender: str, secure: bool = False):
        self.host, self.port = host, port
        self.username, self.password, self.sender = username, password, sender
        self.secure = secure

    @classmethod
    def from_environment(cls):
        host = os.getenv("SMTP_HOST", "").strip()
        username = os.getenv("SMTP_USER", "").strip()
        password = os.getenv("SMTP_PASS", "")
        sender = os.getenv("SMTP_FROM", "").strip() or username
        if not host or not username or not password or not sender:
            return None
        try:
            port = int(os.getenv("SMTP_PORT", "587"))
        except ValueError:
            return None
        return cls(host, port, username, password, sender, os.getenv("SMTP_SECURE", "false").lower() == "true")

    async def send_otp(self, destination: str, code: str) -> bool:
        import asyncio
        import smtplib
        from email.message import EmailMessage

        def deliver():
            message = EmailMessage()
            message["Subject"] = "Your customer support verification code"
            message["From"] = self.sender
            message["To"] = destination
            message.set_content(
                f"Your verification code is {code}. It expires in 5 minutes. "
                "If you did not request this code, you can ignore this email."
            )
            smtp_type = smtplib.SMTP_SSL if self.secure else smtplib.SMTP
            with smtp_type(self.host, self.port, timeout=10) as client:
                if not self.secure:
                    client.starttls()
                client.login(self.username, self.password)
                client.send_message(message)
            return True

        try:
            return await asyncio.to_thread(deliver)
        except Exception:
            logger.exception("OTP email delivery failed")
            return False


# Default module-level ASGI app instance for uvicorn
app = create_default_app()
