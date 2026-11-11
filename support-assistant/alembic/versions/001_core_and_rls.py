"""001_core_and_rls

Revision ID: 001_core_and_rls
Revises: 
Create Date: 2026-11-03 13:15:00.000000

Core Schema with PostgreSQL 16 Row-Level Security (RLS) policies,
spec 15.1.8 staff accounts, spec 10 refunds with partial index,
spec 14.1 trace columns, R4 spend ledger, and content-addressed knowledge chunks.
"""
from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
try:
    from pgvector.sqlalchemy import Vector
except ImportError:
    class Vector(sa.types.UserDefinedType):
        def __init__(self, dim=1024):
            self.dim = dim
        def get_col_spec(self, **kw):
            return f"vector({self.dim})"

revision: str = '001_core_and_rls'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TENANT_TABLES = [
    "staff_tenant_memberships",
    "staff_sessions",
    "tenant_policy_configs",
    "refund_requests",
    "audit_events",
    "conversation_sessions",
    "conversation_turns",
    "turn_raw",
    "spend_ledger",
    "escalations",
    "knowledge_versions",
    "knowledge_chunks",
    "ingestion_jobs",
]


def _is_legacy_table(table_name: str, current_columns: set[str]) -> bool:
    """Detect tables created by the original init.sql before the ORM schema."""
    if context.is_offline_mode():
        return False
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table_name):
        return False
    return not current_columns.issubset(
        {column["name"] for column in inspector.get_columns(table_name)}
    )


def _preserve_legacy_schema() -> tuple[bool, bool]:
    """Move incompatible legacy tables aside before creating their current forms."""
    if context.is_offline_mode():
        return False, False

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    legacy_refunds = _is_legacy_table(
        "refund_requests", {"tenant_id", "request_time", "leased_until", "retry_count"}
    )
    legacy_chunks = _is_legacy_table(
        "knowledge_chunks", {"tenant_id", "chunk_id", "source_type", "metadata"}
    )

    if legacy_refunds:
        old_indexes = {idx["name"] for idx in inspector.get_indexes("refund_requests")}
        op.rename_table("refund_requests", "legacy_refund_requests")
        if "idx_refund_customer" in old_indexes:
            op.execute("ALTER INDEX idx_refund_customer RENAME TO idx_legacy_refund_customer")
    if legacy_chunks:
        op.rename_table("knowledge_chunks", "legacy_knowledge_chunks")
    return legacy_refunds, legacy_chunks


def _upgrade_legacy_commerce_tables() -> None:
    """Align the init.sql commerce tables with the current SQLAlchemy models."""
    if context.is_offline_mode():
        return

    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("products"):
        op.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(64) NOT NULL DEFAULT 'tenant_novaretail'")
        aliases = next((c for c in inspector.get_columns("products") if c["name"] == "aliases"), None)
        if aliases and "ARRAY" in str(aliases["type"]).upper():
            op.execute("ALTER TABLE products ALTER COLUMN aliases DROP DEFAULT")
            op.execute("ALTER TABLE products ALTER COLUMN aliases TYPE JSONB USING to_jsonb(aliases)")
            op.execute("ALTER TABLE products ALTER COLUMN aliases SET DEFAULT '[]'::jsonb")
    if inspector.has_table("orders"):
        op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(64) NOT NULL DEFAULT 'tenant_novaretail'")
    if inspector.has_table("product_specs"):
        spec_id = next((c for c in inspector.get_columns("product_specs") if c["name"] == "spec_id"), None)
        if spec_id and "UUID" in str(spec_id["type"]).upper():
            op.execute("ALTER TABLE product_specs ALTER COLUMN spec_id DROP DEFAULT")
            op.execute("ALTER TABLE product_specs ALTER COLUMN spec_id TYPE VARCHAR(64) USING spec_id::text")


def _copy_legacy_data(legacy_refunds: bool, legacy_chunks: bool) -> None:
    """Copy compatible legacy data while retaining the source tables for audit/rollback."""
    if context.is_offline_mode():
        return
    op.execute(
        "INSERT INTO tenants (tenant_id, name) VALUES ('tenant_novaretail', 'NovaRetail') "
        "ON CONFLICT (tenant_id) DO NOTHING"
    )
    _upgrade_legacy_commerce_tables()

    if legacy_refunds:
        op.execute("""
            INSERT INTO refund_requests (
                refund_id, tenant_id, order_id, customer_id, item_ref, amount_inr,
                state, idempotency_key, reason, request_time, staff_note, decided_at,
                decided_by
            )
            SELECT refund_id, 'tenant_novaretail', order_id, customer_id, 'ALL', amount_inr,
                CASE WHEN state IN ('pending_approval', 'approved', 'processed', 'rejected', 'failed')
                     THEN state ELSE 'pending_approval' END,
                idempotency_key, reason, created_at, note, decided_at,
                CASE WHEN EXISTS (SELECT 1 FROM staff_users s WHERE s.staff_id = legacy_refund_requests.decided_by)
                     THEN decided_by ELSE NULL END
            FROM legacy_refund_requests
            ON CONFLICT DO NOTHING
        """)
    if legacy_chunks:
        op.execute("""
            INSERT INTO knowledge_chunks (
                chunk_id, tenant_id, source_type, product_id, text, embedding, metadata, created_at
            )
            SELECT chunk_id, 'tenant_novaretail', source_type, product_id, text, embedding,
                COALESCE(metadata, '{}'::jsonb) || jsonb_build_object(
                    'legacy_doc_id', doc_id,
                    'legacy_doc_version', doc_version,
                    'effective_date', effective_date
                ), created_at
            FROM legacy_knowledge_chunks
            ON CONFLICT (chunk_id) DO NOTHING
        """)


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    legacy_refunds, legacy_chunks = _preserve_legacy_schema()

    # 1. Extensions for PostgreSQL
    if is_postgres:
        op.execute("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\";")
        op.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")

    # 2. Tenants Table
    op.create_table(
        "tenants",
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("working_hours_start", sa.Time(), server_default="09:00:00", nullable=False),
        sa.Column("working_hours_end", sa.Time(), server_default="18:00:00", nullable=False),
        sa.Column("timezone", sa.String(64), server_default="Asia/Kolkata", nullable=False),
        sa.Column("daily_spend_cap_inr", sa.Integer(), server_default="2500", nullable=False),
        sa.Column("monthly_spend_cap_inr", sa.Integer(), server_default="50000", nullable=False),
        sa.Column("spend_mode", sa.String(32), server_default="normal", nullable=False),
        sa.Column("active_policy_version", sa.String(64), nullable=True),
        sa.Column("active_product_version", sa.String(64), nullable=True),
        sa.Column("refund_turnaround_hours", sa.Integer(), server_default="24", nullable=False),
        sa.Column("widget_origins", postgresql.JSONB() if is_postgres else sa.JSON(), server_default="[]" if is_postgres else "[]", nullable=False),
        sa.Column("jwks_url", sa.String(255), nullable=True),
        sa.Column("issuer", sa.String(255), nullable=True),
        sa.Column("audience", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # 3. Staff Users Table (Spec 15.1.8 - Per-person accounts with Argon2id & TOTP MFA)
    op.create_table(
        "staff_users",
        sa.Column("staff_id", sa.String(64), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("mfa_secret", sa.String(64), nullable=True),
        sa.Column("failed_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_index("idx_staff_users_email", "staff_users", ["email"])

    # 4. Staff Tenant Memberships Table (Multi-tenant RBAC)
    op.create_table(
        "staff_tenant_memberships",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("staff_id", sa.String(64), sa.ForeignKey("staff_users.staff_id", ondelete="CASCADE"), nullable=False),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),  # 'executive', 'manager', 'admin'
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("staff_id", "tenant_id", name="uq_staff_tenant_membership"),
    )
    op.create_index("idx_stm_tenant_staff", "staff_tenant_memberships", ["tenant_id", "staff_id"])

    # 5. Staff Sessions Table (Opaque server-side sessions with CSRF token)
    op.create_table(
        "staff_sessions",
        sa.Column("session_id", sa.String(128), primary_key=True),
        sa.Column("staff_id", sa.String(64), sa.ForeignKey("staff_users.staff_id", ondelete="CASCADE"), nullable=False),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False),
        sa.Column("active_tenant_id", sa.String(64), sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("csrf_hash", sa.String(128), nullable=False),
    )
    op.create_index("idx_staff_sessions_staff", "staff_sessions", ["staff_id"])
    op.create_index("idx_staff_sessions_tenant", "staff_sessions", ["tenant_id"])
    op.create_index("idx_staff_sessions_active_tenant", "staff_sessions", ["active_tenant_id"])

    # 6. Tenant Policy Configs (Append-only versioned money rules - Spec 16.4)
    op.create_table(
        "tenant_policy_configs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False),
        sa.Column("auto_refund_limit_inr", sa.Integer(), server_default="2000", nullable=False),
        sa.Column("return_window_days", sa.Integer(), server_default="30", nullable=False),
        sa.Column("max_auto_refund_per_customer_monthly_inr", sa.Integer(), server_default="10000", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("updated_by", sa.String(64), sa.ForeignKey("staff_users.staff_id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_tpc_tenant_version", "tenant_policy_configs", ["tenant_id", "version"])

    # 7. Refund Requests Table (Spec 10 with outbox lease columns)
    op.create_table(
        "refund_requests",
        sa.Column("refund_id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False),
        sa.Column("order_id", sa.String(64), nullable=False),
        sa.Column("customer_id", sa.String(64), nullable=False),
        sa.Column("item_ref", sa.String(64), server_default="ALL", nullable=False),
        sa.Column("amount_inr", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(32), server_default="pending_approval", nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("request_time", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("eligibility_snapshot", postgresql.JSONB() if is_postgres else sa.JSON(), server_default="{}" if is_postgres else "{}", nullable=False),
        sa.Column("policy_version_applied", sa.String(64), nullable=True),
        sa.Column("decided_by", sa.String(64), sa.ForeignKey("staff_users.staff_id"), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("staff_note", sa.Text(), nullable=True),
        sa.Column("leased_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_refund_tenant_state", "refund_requests", ["tenant_id", "state"])
    op.create_index("idx_refund_customer", "refund_requests", ["tenant_id", "customer_id"])

    # Partial unique index preventing duplicate refund claims on active states
    if is_postgres:
        op.execute(
            """
            CREATE UNIQUE INDEX idx_refund_active_unique 
            ON refund_requests (tenant_id, order_id, item_ref)
            WHERE state IN ('pending_approval', 'approved', 'processed');
            """
        )

    # 8. Audit Events Table (Insert & select only - append-only log)
    op.create_table(
        "audit_events",
        sa.Column("event_id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_id", sa.String(64), nullable=False),
        sa.Column("actor_role", sa.String(32), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("resource_id", sa.String(128), nullable=False),
        sa.Column("details", postgresql.JSONB() if is_postgres else sa.JSON(), server_default="{}" if is_postgres else "{}", nullable=False),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_audit_tenant_ts", "audit_events", ["tenant_id", "timestamp"])

    # 9. Conversation Sessions Table
    op.create_table(
        "conversation_sessions",
        sa.Column("conv_id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel", sa.String(32), server_default="web", nullable=False),
        sa.Column("customer_id", sa.String(64), nullable=False),
        sa.Column("last_user_message_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("handoff_state", sa.String(32), server_default="none", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_conv_tenant_cust", "conversation_sessions", ["tenant_id", "customer_id"])

    # 10. Conversation Turns Table (Spec 14.1 Complete Trace Columns)
    op.create_table(
        "conversation_turns",
        sa.Column("turn_id", sa.String(64), primary_key=True),
        sa.Column("conv_id", sa.String(64), sa.ForeignKey("conversation_sessions.conv_id", ondelete="CASCADE"), nullable=False),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False),
        sa.Column("step_index", sa.Integer(), server_default="0", nullable=False),
        sa.Column("user_input_masked", sa.Text(), nullable=False),
        sa.Column("assistant_response_masked", sa.Text(), nullable=False),
        sa.Column("intent", sa.String(64), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("tokens_prompt", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tokens_completion", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tool_calls_json", postgresql.JSONB() if is_postgres else sa.JSON(), server_default="[]" if is_postgres else "[]", nullable=False),
        sa.Column("grounding_score", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_turns_conv_step", "conversation_turns", ["conv_id", "step_index"])
    op.create_index("idx_turns_tenant_created", "conversation_turns", ["tenant_id", "created_at"])

    # 11. Turn Raw Table (DPDP Sensitive Unmasked Store)
    op.create_table(
        "turn_raw",
        sa.Column("turn_id", sa.String(64), sa.ForeignKey("conversation_turns.turn_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_input_raw", sa.Text(), nullable=False),
        sa.Column("assistant_response_raw", sa.Text(), nullable=False),
        sa.Column("contact_details", postgresql.JSONB() if is_postgres else sa.JSON(), server_default="{}" if is_postgres else "{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_turn_raw_tenant", "turn_raw", ["tenant_id"])

    # 12. Spend Ledger Table (R4 Token Usage & INR Cost Accounting)
    op.create_table(
        "spend_ledger",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False),
        sa.Column("turn_id", sa.String(64), nullable=True),
        sa.Column("purpose", sa.String(32), server_default="chat", nullable=False),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("completion_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cost_inr", sa.Float(), server_default="0.0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_spend_tenant_created", "spend_ledger", ["tenant_id", "created_at"])

    # 13. Escalations Table (Spec 5.2 Human Queue)
    op.create_table(
        "escalations",
        sa.Column("esc_id", sa.String(64), primary_key=True),
        sa.Column("conv_id", sa.String(64), sa.ForeignKey("conversation_sessions.conv_id", ondelete="CASCADE"), nullable=False),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("priority", sa.String(32), server_default="medium", nullable=False),
        sa.Column("state", sa.String(32), server_default="open", nullable=False),
        sa.Column("assigned_to", sa.String(64), sa.ForeignKey("staff_users.staff_id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
    )
    op.create_index("idx_esc_tenant_state", "escalations", ["tenant_id", "state"])

    # 14. Knowledge Versions Table (Manifest Pointer)
    op.create_table(
        "knowledge_versions",
        sa.Column("version_id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), server_default="draft", nullable=False),
        sa.Column("manifest", postgresql.JSONB() if is_postgres else sa.JSON(), server_default="{}" if is_postgres else "{}", nullable=False),
        sa.Column("created_by", sa.String(64), sa.ForeignKey("staff_users.staff_id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_kv_tenant_type_status", "knowledge_versions", ["tenant_id", "type", "status"])

    # 15. Knowledge Chunks Table (Content-addressed vector store)
    op.create_table(
        "knowledge_chunks",
        sa.Column("chunk_id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("product_id", sa.String(64), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1024) if is_postgres else sa.JSON(), nullable=True),
        sa.Column("metadata", postgresql.JSONB() if is_postgres else sa.JSON(), server_default="{}" if is_postgres else "{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_kc_tenant_product", "knowledge_chunks", ["tenant_id", "product_id"])

    if is_postgres:
    op.execute("""
        CREATE INDEX idx_knowledge_chunks_embedding_hnsw
        ON knowledge_chunks
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64);
    """)

    # 16. Knowledge Version Chunks Table (Many-to-Many manifest mapping)
    op.create_table(
        "knowledge_version_chunks",
        sa.Column("version_id", sa.String(64), sa.ForeignKey("knowledge_versions.version_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("chunk_id", sa.String(64), sa.ForeignKey("knowledge_chunks.chunk_id", ondelete="CASCADE"), primary_key=True),
    )

    # 17. Ingestion Jobs Table (Async catalog/policy ingest state machine)
    op.create_table(
        "ingestion_jobs",
        sa.Column("job_id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), server_default="queued", nullable=False),
        sa.Column("progress_pct", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("stats", postgresql.JSONB() if is_postgres else sa.JSON(), server_default="{}" if is_postgres else "{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    if is_postgres:
        op.execute(
            """
            CREATE UNIQUE INDEX idx_ingestion_single_active 
            ON ingestion_jobs (tenant_id, source_type)
            WHERE status IN ('queued', 'running');
            """
        )

    # Import legacy rows before RLS policies are enabled. The original tables
    # remain intact so the upgrade never destroys source data.
    _copy_legacy_data(legacy_refunds, legacy_chunks)

    # 18. Apply PostgreSQL Row-Level Security (RLS) across all tenant tables
    if is_postgres:
        for table in TENANT_TABLES:
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
            predicate = "tenant_id = current_setting('app.tenant_id', true)"
            if table == "staff_tenant_memberships":
                predicate += " OR staff_id = current_setting('app.staff_id', true)"
            elif table == "staff_sessions":
                predicate += " OR session_id = current_setting('app.session_id', true)"
            op.execute(
                f"""
                CREATE POLICY tenant_isolation_policy ON {table}
                USING ({predicate});
                """
            )

        # 19. Set up application role privileges
        op.execute(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'novaretail_app') THEN
                END IF;
            END
            $$;
            """
        )
        op.execute("GRANT USAGE ON SCHEMA public TO novaretail_app;")
        op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO novaretail_app;")
        # Spec requirement: audit_events is append-only / immutable for application role!
        op.execute("REVOKE UPDATE, DELETE, TRUNCATE ON audit_events FROM novaretail_app;")


def downgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        for table in reversed(TENANT_TABLES):
            op.execute(f"DROP POLICY IF EXISTS tenant_isolation_policy ON {table};")
            op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
            op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")

    op.drop_table("ingestion_jobs")
    op.drop_table("knowledge_version_chunks")
    op.drop_table("knowledge_chunks")
    op.drop_table("knowledge_versions")
    op.drop_table("escalations")
    op.drop_table("spend_ledger")
    op.drop_table("turn_raw")
    op.drop_table("conversation_turns")
    op.drop_table("conversation_sessions")
    op.drop_table("audit_events")
    op.drop_table("refund_requests")
    op.drop_table("tenant_policy_configs")
    op.drop_table("staff_sessions")
    op.drop_table("staff_tenant_memberships")
    op.drop_table("staff_users")
    op.drop_table("tenants")
