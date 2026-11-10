"""
SQLAlchemy ORM Models for NovaRetail Support Assistant & Master Control Dashboard.
Mirrors Alembic migration 001_core_and_rls with strict multi-tenant schema.
"""

from datetime import datetime, timezone
import uuid
from typing import Optional, List, Dict, Any

from sqlalchemy import (
    Column, String, Integer, Float, Boolean, Text, DateTime, Time, Numeric,
    ForeignKey, UniqueConstraint, Index, func
)
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.dialects.postgresql import JSONB, ARRAY

try:
    from pgvector.sqlalchemy import Vector
except ImportError:
    import sqlalchemy as sa
    class Vector(sa.types.UserDefinedType):
        def __init__(self, dim=1024):
            self.dim = dim
        def get_col_spec(self, **kw):
            return f"vector({self.dim})"

Base = declarative_base()


class Tenant(Base):
    __tablename__ = "tenants"

    tenant_id = Column(String(64), primary_key=True)
    name = Column(String(255), nullable=False)
    working_hours_start = Column(Time(), server_default="09:00:00", nullable=False)
    working_hours_end = Column(Time(), server_default="18:00:00", nullable=False)
    timezone = Column(String(64), server_default="Asia/Kolkata", nullable=False)
    daily_spend_cap_inr = Column(Integer(), server_default="2500", nullable=False)
    monthly_spend_cap_inr = Column(Integer(), server_default="50000", nullable=False)
    spend_mode = Column(String(32), server_default="normal", nullable=False)
    active_policy_version = Column(String(64), nullable=True)
    active_product_version = Column(String(64), nullable=True)
    refund_turnaround_hours = Column(Integer(), server_default="24", nullable=False)
    widget_origins = Column(JSONB, server_default="[]", nullable=False)
    widget_config = Column(JSONB, server_default="{\"name\":\"NovaRetail Support\",\"greeting\":\"Hi! How can I help you today?\",\"primaryColor\":\"#0284c7\",\"theme\":\"light\",\"launcherSide\":\"right\",\"quickPrompts\":[\"Track my order\",\"Product questions\"],\"autoOpen\":false}", nullable=False)
    jwks_url = Column(String(255), nullable=True)
    issuer = Column(String(255), nullable=True)
    audience = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class StaffUser(Base):
    __tablename__ = "staff_users"

    staff_id = Column(String(64), primary_key=True)
    email = Column(String(255), nullable=False, unique=True, index=True)
    full_name = Column(String(255), nullable=False)
    password_hash = Column(String(255), nullable=False)
    mfa_secret = Column(String(64), nullable=True)
    failed_attempts = Column(Integer(), server_default="0", nullable=False)
    locked_until = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class StaffTenantMembership(Base):
    __tablename__ = "staff_tenant_memberships"

    id = Column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    staff_id = Column(String(64), ForeignKey("staff_users.staff_id", ondelete="CASCADE"), nullable=False)
    tenant_id = Column(String(64), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False)
    role = Column(String(32), nullable=False)  # 'executive', 'manager', 'admin'
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("staff_id", "tenant_id", name="uq_staff_tenant_membership"),
        Index("idx_stm_tenant_staff", "tenant_id", "staff_id"),
    )


class StaffSession(Base):
    __tablename__ = "staff_sessions"

    session_id = Column(String(128), primary_key=True)
    staff_id = Column(String(64), ForeignKey("staff_users.staff_id", ondelete="CASCADE"), nullable=False)
    tenant_id = Column(
        String(64),
        ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
        default=lambda context: context.get_current_parameters().get("active_tenant_id"),
        nullable=False,
    )
    active_tenant_id = Column(String(64), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    csrf_hash = Column(String(128), nullable=False)

    __table_args__ = (
        Index("idx_staff_sessions_staff", "staff_id"),
        Index("idx_staff_sessions_tenant", "tenant_id"),
        Index("idx_staff_sessions_active_tenant", "active_tenant_id"),
    )


class TenantPolicyConfig(Base):
    __tablename__ = "tenant_policy_configs"

    id = Column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(64), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False)
    auto_refund_limit_inr = Column(Integer(), server_default="2000", nullable=False)
    return_window_days = Column(Integer(), server_default="30", nullable=False)
    max_auto_refund_per_customer_monthly_inr = Column(Integer(), server_default="10000", nullable=False)
    version = Column(Integer(), server_default="1", nullable=False)
    updated_by = Column(String(64), ForeignKey("staff_users.staff_id"), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_tpc_tenant_version", "tenant_id", "version"),
    )


class RefundRequest(Base):
    __tablename__ = "refund_requests"

    refund_id = Column(String(64), primary_key=True)
    tenant_id = Column(String(64), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False)
    order_id = Column(String(64), nullable=False)
    customer_id = Column(String(64), nullable=False)
    item_ref = Column(String(64), server_default="ALL", nullable=False)
    amount_inr = Column(Numeric(12, 2), nullable=False)
    state = Column(String(32), server_default="pending_approval", nullable=False)
    idempotency_key = Column(String(128), nullable=False, unique=True)
    reason = Column(Text, nullable=False)
    request_time = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    eligibility_snapshot = Column(JSONB, server_default="{}", nullable=False)
    policy_version_applied = Column(String(64), nullable=True)
    decided_by = Column(String(64), ForeignKey("staff_users.staff_id"), nullable=True)
    decided_at = Column(DateTime(timezone=True), nullable=True)
    staff_note = Column(Text, nullable=True)
    leased_until = Column(DateTime(timezone=True), nullable=True)
    retry_count = Column(Integer(), server_default="0", nullable=False)
    notified_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_refund_tenant_state", "tenant_id", "state"),
        Index("idx_refund_customer", "tenant_id", "customer_id"),
    )


class AuditEvent(Base):
    __tablename__ = "audit_events"

    event_id = Column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(64), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False)
    actor_id = Column(String(64), nullable=False)
    actor_role = Column(String(32), nullable=False)
    action = Column(String(64), nullable=False)
    resource_type = Column(String(64), nullable=False)
    resource_id = Column(String(128), nullable=False)
    details = Column(JSONB, server_default="{}", nullable=False)
    ip_address = Column(String(45), nullable=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_audit_tenant_ts", "tenant_id", "timestamp"),
    )


class ConversationSession(Base):
    __tablename__ = "conversation_sessions"

    conv_id = Column(String(64), primary_key=True)
    tenant_id = Column(String(64), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False)
    channel = Column(String(32), server_default="web", nullable=False)
    customer_id = Column(String(64), nullable=False)
    last_user_message_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    handoff_state = Column(String(32), server_default="none", nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_conv_tenant_cust", "tenant_id", "customer_id"),
    )


class ConversationTurn(Base):
    __tablename__ = "conversation_turns"

    turn_id = Column(String(64), primary_key=True)
    conv_id = Column(String(64), ForeignKey("conversation_sessions.conv_id", ondelete="CASCADE"), nullable=False)
    tenant_id = Column(String(64), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False)
    step_index = Column(Integer(), server_default="0", nullable=False)
    user_input_masked = Column(Text, nullable=False)
    assistant_response_masked = Column(Text, nullable=False)
    intent = Column(String(64), nullable=True)
    latency_ms = Column(Integer(), nullable=True)
    tokens_prompt = Column(Integer(), server_default="0", nullable=False)
    tokens_completion = Column(Integer(), server_default="0", nullable=False)
    tool_calls_json = Column(JSONB, server_default="[]", nullable=False)
    grounding_score = Column(Float(), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_turns_conv_step", "conv_id", "step_index"),
        Index("idx_turns_tenant_created", "tenant_id", "created_at"),
    )


class TurnRaw(Base):
    __tablename__ = "turn_raw"

    turn_id = Column(String(64), ForeignKey("conversation_turns.turn_id", ondelete="CASCADE"), primary_key=True)
    tenant_id = Column(String(64), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False)
    user_input_raw = Column(Text, nullable=False)
    assistant_response_raw = Column(Text, nullable=False)
    contact_details = Column(JSONB, server_default="{}", nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_turn_raw_tenant", "tenant_id"),
    )


class SpendLedger(Base):
    __tablename__ = "spend_ledger"

    id = Column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(64), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False)
    turn_id = Column(String(64), nullable=True)
    purpose = Column(String(32), server_default="chat", nullable=False)
    model = Column(String(64), nullable=False)
    prompt_tokens = Column(Integer(), server_default="0", nullable=False)
    completion_tokens = Column(Integer(), server_default="0", nullable=False)
    cost_inr = Column(Float(), server_default="0.0", nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_spend_tenant_created", "tenant_id", "created_at"),
    )


class Escalation(Base):
    __tablename__ = "escalations"

    esc_id = Column(String(64), primary_key=True)
    conv_id = Column(String(64), ForeignKey("conversation_sessions.conv_id", ondelete="CASCADE"), nullable=False)
    tenant_id = Column(String(64), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False)
    reason = Column(Text, nullable=False)
    summary = Column(Text, nullable=True)
    priority = Column(String(32), server_default="medium", nullable=False)
    state = Column(String(32), server_default="open", nullable=False)  # 'open', 'assigned', 'resolved'
    assigned_to = Column(String(64), ForeignKey("staff_users.staff_id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolution_note = Column(Text, nullable=True)

    __table_args__ = (
        Index("idx_esc_tenant_state", "tenant_id", "state"),
    )


class KnowledgeVersion(Base):
    __tablename__ = "knowledge_versions"

    version_id = Column(String(64), primary_key=True)
    tenant_id = Column(String(64), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False)
    type = Column(String(32), nullable=False)  # 'policy', 'catalog'
    status = Column(String(32), server_default="draft", nullable=False)  # 'draft', 'active', 'archived'
    manifest = Column(JSONB, server_default="{}", nullable=False)
    created_by = Column(String(64), ForeignKey("staff_users.staff_id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    promoted_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_kv_tenant_type_status", "tenant_id", "type", "status"),
    )


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"

    chunk_id = Column(String(64), primary_key=True)
    tenant_id = Column(String(64), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False)
    source_type = Column(String(32), nullable=False)
    product_id = Column(String(64), nullable=True)
    text = Column(Text, nullable=False)
    embedding = Column(Vector(1024), nullable=True)
    metadata_ = Column("metadata", JSONB, server_default="{}", nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_kc_tenant_product", "tenant_id", "product_id"),
    )


class KnowledgeVersionChunk(Base):
    __tablename__ = "knowledge_version_chunks"

    version_id = Column(String(64), ForeignKey("knowledge_versions.version_id", ondelete="CASCADE"), primary_key=True)
    chunk_id = Column(String(64), ForeignKey("knowledge_chunks.chunk_id", ondelete="CASCADE"), primary_key=True)


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"

    job_id = Column(String(64), primary_key=True)
    tenant_id = Column(String(64), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False)
    source_type = Column(String(32), nullable=False)  # 'catalog', 'policy'
    status = Column(String(32), server_default="queued", nullable=False)  # 'queued', 'running', 'completed', 'failed'
    progress_pct = Column(Integer(), server_default="0", nullable=False)
    error_message = Column(Text, nullable=True)
    stats = Column(JSONB, server_default="{}", nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    run_id = Column(String(64), primary_key=True)
    job_id = Column(String(64), ForeignKey("ingestion_jobs.job_id", ondelete="CASCADE"), nullable=False, unique=True)
    tenant_id = Column(String(64), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False)
    status = Column(String(32), nullable=False)
    started_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    stats = Column(JSONB, server_default="{}", nullable=False)
    errors = Column(JSONB, server_default="[]", nullable=False)
    logs = Column(JSONB, server_default="[]", nullable=False)
    promoted_version_id = Column(String(64), nullable=True)
    __table_args__ = (Index("idx_ingestion_runs_tenant_started", "tenant_id", "started_at"),)


class IngestionItem(Base):
    __tablename__ = "ingestion_items"

    item_id = Column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id = Column(String(64), ForeignKey("ingestion_runs.run_id", ondelete="CASCADE"), nullable=False)
    tenant_id = Column(String(64), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False)
    product_id = Column(String(64), nullable=False)
    status = Column(String(32), nullable=False)
    attempts = Column(Integer(), server_default="0", nullable=False)
    content_hash = Column(String(64), nullable=True)
    error_code = Column(String(64), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    __table_args__ = (
        Index("idx_ingestion_items_run_status", "run_id", "status"),
        Index("idx_ingestion_items_tenant_product", "tenant_id", "product_id"),
    )


# E-commerce Core Entities (Backing OrderPort and CatalogPort in PostgreSQL)
class ProductModel(Base):
    __tablename__ = "products"

    product_id = Column(String(64), primary_key=True)
    tenant_id = Column(String(64), default="tenant_novaretail", nullable=False)
    name = Column(String(255), nullable=False)
    brand = Column(String(128), nullable=False)
    category = Column(String(64), nullable=False)
    description = Column(Text, nullable=False, default="")
    faqs = Column(JSONB, server_default="[]", nullable=False)
    aliases = Column(JSONB, server_default="[]", nullable=False)
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    specs = relationship("ProductSpecModel", back_populates="product", cascade="all, delete-orphan")
    pricing = relationship("ProductPriceModel", back_populates="product", uselist=False, cascade="all, delete-orphan")


class ProductSpecModel(Base):
    __tablename__ = "product_specs"

    spec_id = Column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    product_id = Column(String(64), ForeignKey("products.product_id", ondelete="CASCADE"), nullable=False)
    spec_key = Column(String(128), nullable=False)
    spec_value = Column(Text, nullable=False)
    unit = Column(String(32), nullable=True)
    version_id = Column(String(64), ForeignKey("knowledge_versions.version_id", ondelete="CASCADE"), nullable=True)

    product = relationship("ProductModel", back_populates="specs")


class ProductPriceModel(Base):
    __tablename__ = "product_prices"

    product_id = Column(String(64), ForeignKey("products.product_id", ondelete="CASCADE"), primary_key=True)
    price = Column(Integer(), nullable=False)
    discount_price = Column(Integer(), nullable=True)
    currency = Column(String(8), server_default="INR", nullable=False)
    in_stock = Column(Boolean, default=True, nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    product = relationship("ProductModel", back_populates="pricing")


class CustomerModel(Base):
    __tablename__ = "customers"

    customer_id = Column(String(64), primary_key=True)
    tenant_id = Column(String(64), default="tenant_novaretail", nullable=False)
    phone_hash = Column(String(64), nullable=False, unique=True)
    email = Column(String(255), nullable=False, unique=True)
    full_name = Column(String(255), nullable=False)
    language_pref = Column(String(16), default="en", nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class OrderModel(Base):
    __tablename__ = "orders"

    order_id = Column(String(64), primary_key=True)
    tenant_id = Column(String(64), default="tenant_novaretail", nullable=False)
    customer_id = Column(String(64), nullable=False, index=True)
    total_amount_inr = Column(Numeric(12, 2), nullable=False)
    status = Column(String(32), nullable=False)
    tracking_number = Column(String(128), nullable=True)
    courier_name = Column(String(64), nullable=True)
    shipping_address = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    delivered_at = Column(DateTime(timezone=True), nullable=True)

    items = relationship("OrderItemModel", back_populates="order", cascade="all, delete-orphan")


class OrderItemModel(Base):
    __tablename__ = "order_items"

    item_id = Column(String(64), primary_key=True)
    order_id = Column(String(64), ForeignKey("orders.order_id", ondelete="CASCADE"), nullable=False)
    product_id = Column(String(64), nullable=True)
    product_name = Column(String(255), nullable=False)
    category = Column(String(64), nullable=False)
    price = Column(Numeric(12, 2), nullable=False)
    quantity = Column(Integer(), default=1, nullable=False)
    is_digital = Column(Boolean, default=False, nullable=False)
    is_refunded = Column(Boolean, default=False, nullable=False)
    refund_eligibility_verified = Column(Boolean, default=True, nullable=False)

    order = relationship("OrderModel", back_populates="items")
