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

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, Callable, Dict, Optional, Tuple
import urllib.parse
import uuid

from pydantic import BaseModel, Field

from core.models import SessionContext, AuthLevel
from services.assistant_api.jwt_auth import verify_customer_token
from services.assistant_api.otp_service import OTPService
from services.assistant_api.whatsapp_security import WhatsAppSecurity
from services.worker.orchestrator import WorkerOrchestrator, OrchestratorResponse


# ============================================================================
# Pydantic Schemas
# ============================================================================

class ChatMessageRequest(BaseModel):
    message: str = Field(..., min_length=1)
    conv_id: Optional[str] = None
    tenant_id: str = "demo-shop"
    channel: str = "web"


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
    destination: str
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
        support_desk_service: Optional[Any] = None
    ):
        self.orchestrator = orchestrator
        self.otp_service = otp_service or OTPService()
        self.whatsapp_security = whatsapp_security or WhatsAppSecurity(
            app_secret="test_whatsapp_secret_9941",
            verify_token="novaretail_verify_token_secure"
        )
        self.company_jwt_secret = company_jwt_secret
        self.support_desk_service = support_desk_service
        self.static_dir = Path(__file__).parent.parent.parent / "static"

        # Session storage: (tenant_id, conv_id) -> SessionContext
        self._session_store: Dict[Tuple[str, str], SessionContext] = {}

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

        # Check existing session for active verified status
        existing = self._session_store.get(key)
        if existing and existing.level == AuthLevel.VERIFIED:
            if existing.verified_until and now <= existing.verified_until:
                return existing

        # Evaluate Bearer token if provided
        if auth_header:
            kwargs = {"auth_header": auth_header, "expected_tenant": tenant_id, "conv_id": conv_id}
            if self.company_jwt_secret:
                kwargs["secret"] = self.company_jwt_secret
            session = verify_customer_token(**kwargs)
        else:
            session = SessionContext(
                tenant_id=tenant_id,
                conv_id=conv_id,
                customer_id=None,
                level=AuthLevel.ANONYMOUS,
                channel=channel  # type: ignore
            )

        self._session_store[key] = session
        return session

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

        conv_id = req.conv_id or f"conv_{uuid.uuid4().hex[:12]}"
        session = self.get_or_create_session(
            tenant_id=req.tenant_id,
            conv_id=conv_id,
            auth_header=auth_header,
            channel=req.channel
        )

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

    async def handle_whatsapp_webhook_get(
        self,
        query_params: Dict[str, str]
    ) -> Tuple[int, str]:
        """Handles GET /webhooks/whatsapp (Meta Verification Challenge)."""
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

        return 200, {
            "status": "delivered",
            "message_id": message_id,
            "sender": sender_phone,
            "reply": orch_response.reply,
            "language": orch_response.language,
            "trace_id": orch_response.trace_id
        }

    async def handle_send_otp(self, payload: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        """Handles POST /auth/otp/send."""
        try:
            req = SendOTPRequest(**payload)
        except Exception as e:
            return 422, {"detail": str(e)}

        session = self.get_or_create_session(
            tenant_id=req.tenant_id,
            conv_id=req.conv_id
        )

        challenge_id, raw_code = self.otp_service.create_challenge(
            session=session,
            destination=req.destination
        )

        # In production, raw_code is dispatched via SMS/WhatsApp gateway and omitted from response.
        return 200, {
            "challenge_id": challenge_id,
            "status": "sent",
            "destination": req.destination
        }

    async def handle_verify_otp(self, payload: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        """Handles POST /auth/otp/verify."""
        try:
            req = VerifyOTPRequest(**payload)
        except Exception as e:
            return 422, {"detail": str(e)}

        key = (req.tenant_id, req.conv_id)
        session = self.get_or_create_session(req.tenant_id, req.conv_id)

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
        return 200, {
            "status": "healthy",
            "service": "novaretail-assistant-api",
            "version": "1.0.0",
            "active_sessions": len(self._session_store)
        }

    # ========================================================================
    # Standard ASGI 3.0 Handler
    # ========================================================================

    async def __call__(self, scope: Dict[str, Any], receive: Callable, send: Callable) -> None:
        """ASGI 3.0 application interface for uvicorn/hypercorn."""
        if scope["type"] != "http":
            return

        method = scope["method"]
        path = scope["path"].rstrip("/") or "/"
        query_string = scope.get("query_string", b"").decode("utf-8")
        query_params = dict(urllib.parse.parse_qsl(query_string))

        # Extract headers
        headers_dict = {
            k.decode("latin1").lower(): v.decode("latin1")
            for k, v in scope.get("headers", [])
        }
        auth_header = headers_dict.get("authorization")
        sig_header = headers_dict.get("x-hub-signature-256")

        # Read request body
        body = bytearray()
        while True:
            message = await receive()
            body.extend(message.get("body", b""))
            if not message.get("more_body", False):
                break
        raw_body = bytes(body)

        # Route matching
        status_code = 404
        response_body = b'{"detail": "Not Found"}'
        content_type = "application/json"

        if path == "/health" and method == "GET":
            status_code, resp = await self.handle_health()
            response_body = json.dumps(resp).encode("utf-8")

        elif path == "/chat/messages" and method == "POST":
            try:
                data = json.loads(raw_body.decode("utf-8")) if raw_body else {}
                status_code, resp = await self.handle_chat_message(data, auth_header=auth_header)
                response_body = json.dumps(resp).encode("utf-8")
            except Exception as e:
                status_code, response_body = 400, json.dumps({"detail": str(e)}).encode("utf-8")

        elif path == "/webhooks/whatsapp" and method == "GET":
            status_code, resp_text = await self.handle_whatsapp_webhook_get(query_params)
            response_body = resp_text.encode("utf-8")
            content_type = "text/plain"

        elif path == "/webhooks/whatsapp" and method == "POST":
            status_code, resp = await self.handle_whatsapp_webhook_post(raw_body, sig_header)
            response_body = json.dumps(resp).encode("utf-8")

        elif path == "/auth/otp/send" and method == "POST":
            try:
                data = json.loads(raw_body.decode("utf-8")) if raw_body else {}
                status_code, resp = await self.handle_send_otp(data)
                response_body = json.dumps(resp).encode("utf-8")
            except Exception as e:
                status_code, response_body = 400, json.dumps({"detail": str(e)}).encode("utf-8")

        elif path == "/auth/otp/verify" and method == "POST":
            try:
                data = json.loads(raw_body.decode("utf-8")) if raw_body else {}
                status_code, resp = await self.handle_verify_otp(data)
                response_body = json.dumps(resp).encode("utf-8")
            except Exception as e:
                status_code, response_body = 400, json.dumps({"detail": str(e)}).encode("utf-8")

        elif path in ("/widget", "/widget/index.html") and method == "GET":
            widget_file = self.static_dir / "widget" / "index.html"
            if widget_file.exists():
                status_code = 200
                content_type = "text/html"
                with open(widget_file, "rb") as f:
                    response_body = f.read()

        elif path in ("/desk", "/desk/index.html") and method == "GET":
            desk_file = self.static_dir / "desk" / "index.html"
            if desk_file.exists():
                status_code = 200
                content_type = "text/html"
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
        await send({
            "type": "http.response.start",
            "status": status_code,
            "headers": [
                (b"content-type", content_type.encode("latin1")),
                (b"content-length", str(len(response_body)).encode("latin1"))
            ]
        })
        await send({
            "type": "http.response.body",
            "body": response_body
        })


def create_default_app() -> GatewayApp:
    """Factory creating fully wired production GatewayApp with all services."""
    import os
    from adapters.mockshop import MockCatalogAdapter, MockOrderAdapter, MockRefundAdapter
    from services.mcp_servers import (
        MCPCatalogServer, MCPOrderServer, MCPRefundServer,
        MCPHandoffServer, MCPToolDispatcher
    )
    from core.router.cache import CacheService
    from core.router.router import AIRouter
    from core.tracing.trace_collector import TraceCollector
    from services.worker.llm_client import GroqLLMClient, MockLLMClient
    from services.support_desk.app import SupportDeskService

    catalog = MockCatalogAdapter()
    orders = MockOrderAdapter()
    refunds = MockRefundAdapter(orders, auto_limit_inr=2000)

    dispatcher = MCPToolDispatcher(
        catalog_server=MCPCatalogServer(catalog),
        order_server=MCPOrderServer(orders),
        refund_server=MCPRefundServer(refunds),
        handoff_server=MCPHandoffServer()
    )

    cache = CacheService()
    router = AIRouter(cache_service=cache, dispatcher=dispatcher)
    collector = TraceCollector()

    groq_api_key = os.getenv("GROQ_API_KEY", "").strip()
    if groq_api_key:
        llm = GroqLLMClient(api_key=groq_api_key)
    else:
        llm = MockLLMClient()

    orchestrator = WorkerOrchestrator(
        router=router,
        dispatcher=dispatcher,
        llm_client=llm
    )

    desk_service = SupportDeskService(
        refund_adapter=refunds,
        trace_collector=collector
    )

    return GatewayApp(
        orchestrator=orchestrator,
        support_desk_service=desk_service,
        company_jwt_secret=os.getenv("STOREFRONT_JWT_SECRET")
    )


# Default module-level ASGI app instance for uvicorn
app = create_default_app()
