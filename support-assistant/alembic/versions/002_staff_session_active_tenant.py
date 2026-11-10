"""Align staff session tenant naming with the authenticated session model."""

from alembic import context, op
import sqlalchemy as sa

revision = "002_staff_session_active_tenant"
down_revision = "001_core_and_rls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if context.is_offline_mode():
        return
    op.execute(
        "INSERT INTO tenants (tenant_id, name) VALUES ('tenant_novaretail', 'NovaRetail') "
        "ON CONFLICT (tenant_id) DO NOTHING"
    )
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("staff_sessions"):
        return
    columns = {column["name"] for column in inspector.get_columns("staff_sessions")}
    if "active_tenant_id" not in columns:
        op.add_column("staff_sessions", sa.Column("active_tenant_id", sa.String(64), nullable=True))
        op.execute("UPDATE staff_sessions SET active_tenant_id = tenant_id WHERE active_tenant_id IS NULL")
        op.alter_column("staff_sessions", "active_tenant_id", nullable=False)
        op.create_foreign_key(
            "fk_staff_sessions_active_tenant_id_tenants",
            "staff_sessions",
            "tenants",
            ["active_tenant_id"],
            ["tenant_id"],
            ondelete="CASCADE",
        )
        inspector = sa.inspect(op.get_bind())
    indexes = {index["name"] for index in inspector.get_indexes("staff_sessions")}
    if "idx_staff_sessions_active_tenant" not in indexes:
        op.create_index("idx_staff_sessions_active_tenant", "staff_sessions", ["active_tenant_id"])

    op.execute("DROP POLICY IF EXISTS tenant_isolation_policy ON staff_tenant_memberships")
    op.execute("""
        CREATE POLICY tenant_isolation_policy ON staff_tenant_memberships
        USING (
            tenant_id = current_setting('app.tenant_id', true)
            OR staff_id = current_setting('app.staff_id', true)
        )
    """)
    op.execute("DROP POLICY IF EXISTS tenant_isolation_policy ON staff_sessions")
    op.execute("""
        CREATE POLICY tenant_isolation_policy ON staff_sessions
        USING (
            tenant_id = current_setting('app.tenant_id', true)
            OR session_id = current_setting('app.session_id', true)
        )
    """)

    inspector = sa.inspect(op.get_bind())
    for table_name in ("products", "orders"):
        if inspector.has_table(table_name):
            op.execute(
                f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS "
                "tenant_id VARCHAR(64) NOT NULL DEFAULT 'tenant_novaretail'"
            )
    if inspector.has_table("products"):
        aliases = next((c for c in inspector.get_columns("products") if c["name"] == "aliases"), None)
        if aliases and "ARRAY" in str(aliases["type"]).upper():
            op.execute("ALTER TABLE products ALTER COLUMN aliases DROP DEFAULT")
            op.execute("ALTER TABLE products ALTER COLUMN aliases TYPE JSONB USING to_jsonb(aliases)")
            op.execute("ALTER TABLE products ALTER COLUMN aliases SET DEFAULT '[]'::jsonb")
    if inspector.has_table("product_specs"):
        spec_id = next((c for c in inspector.get_columns("product_specs") if c["name"] == "spec_id"), None)
        if spec_id and "UUID" in str(spec_id["type"]).upper():
            op.execute("ALTER TABLE product_specs ALTER COLUMN spec_id DROP DEFAULT")
            op.execute("ALTER TABLE product_specs ALTER COLUMN spec_id TYPE VARCHAR(64) USING spec_id::text")


def downgrade() -> None:
    if context.is_offline_mode():
        return
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("staff_sessions"):
        indexes = {index["name"] for index in inspector.get_indexes("staff_sessions")}
        if "idx_staff_sessions_active_tenant" in indexes:
            op.drop_index("idx_staff_sessions_active_tenant", table_name="staff_sessions")
        columns = {column["name"] for column in inspector.get_columns("staff_sessions")}
        if "active_tenant_id" in columns:
            op.drop_column("staff_sessions", "active_tenant_id")
