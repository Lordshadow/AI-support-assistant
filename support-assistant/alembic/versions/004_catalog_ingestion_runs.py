"""Durable catalog run/item history and versioned product specifications."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "004_catalog_ingestion_runs"
down_revision = "003_widget_config"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    is_postgres = getattr(bind, "dialect", None) is not None and bind.dialect.name == "postgresql"
    json_type = postgresql.JSONB() if is_postgres else sa.JSON()
    try:
        inspector = sa.inspect(bind)
    except Exception:
        inspector = None

    has_table = (lambda t: inspector.has_table(t)) if inspector else (lambda t: False)

    # 1. Base commerce entities if not already created
    if not has_table("products"):
        op.create_table(
            "products",
            sa.Column("product_id", sa.String(64), primary_key=True),
            sa.Column("tenant_id", sa.String(64), server_default="tenant_novaretail", nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("brand", sa.String(128), nullable=False),
            sa.Column("category", sa.String(64), nullable=False),
            sa.Column("aliases", json_type, server_default="[]", nullable=False),
            sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        if is_postgres:
            op.create_index("idx_products_category", "products", ["category"])

    if not has_table("product_specs"):
        op.create_table(
            "product_specs",
            sa.Column("spec_id", sa.String(64), primary_key=True),
            sa.Column("product_id", sa.String(64), sa.ForeignKey("products.product_id", ondelete="CASCADE"), nullable=False),
            sa.Column("spec_key", sa.String(128), nullable=False),
            sa.Column("spec_value", sa.Text(), nullable=False),
            sa.Column("unit", sa.String(32), nullable=True),
            sa.Column("version_id", sa.String(64), sa.ForeignKey("knowledge_versions.version_id", ondelete="CASCADE"), nullable=True),
            sa.UniqueConstraint("product_id", "spec_key", "version_id", name="uq_product_specs_product_key_ver"),
        )
        op.create_index("idx_specs_product_id", "product_specs", ["product_id"])
        op.create_index("idx_product_specs_version_product", "product_specs", ["version_id", "product_id"])
    else:
        if is_postgres:
            op.execute("ALTER TABLE product_specs DROP CONSTRAINT IF EXISTS uq_product_specs_product_key")
        columns = [c["name"] for c in inspector.get_columns("product_specs")] if inspector else []
        if "version_id" not in columns:
            op.add_column("product_specs", sa.Column("version_id", sa.String(64), nullable=True))
            if is_postgres:
                op.create_foreign_key(
                    "fk_product_specs_version", "product_specs", "knowledge_versions",
                    ["version_id"], ["version_id"], ondelete="CASCADE",
                )
            op.create_index("idx_product_specs_version_product", "product_specs", ["version_id", "product_id"])

    if not has_table("product_prices"):
        op.create_table(
            "product_prices",
            sa.Column("product_id", sa.String(64), sa.ForeignKey("products.product_id", ondelete="CASCADE"), primary_key=True),
            sa.Column("price", sa.Integer(), nullable=False),
            sa.Column("discount_price", sa.Integer(), nullable=True),
            sa.Column("currency", sa.String(8), server_default="INR", nullable=False),
            sa.Column("in_stock", sa.Boolean(), server_default=sa.true(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )

    if not has_table("orders"):
        op.create_table(
            "orders",
            sa.Column("order_id", sa.String(64), primary_key=True),
            sa.Column("tenant_id", sa.String(64), server_default="tenant_novaretail", nullable=False),
            sa.Column("customer_id", sa.String(64), nullable=False),
            sa.Column("total_amount_inr", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("tracking_number", sa.String(128), nullable=True),
            sa.Column("courier_name", sa.String(64), nullable=True),
            sa.Column("shipping_address", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("idx_orders_customer", "orders", ["customer_id"])

    if not has_table("order_items"):
        op.create_table(
            "order_items",
            sa.Column("item_id", sa.String(64), primary_key=True),
            sa.Column("order_id", sa.String(64), sa.ForeignKey("orders.order_id", ondelete="CASCADE"), nullable=False),
            sa.Column("product_id", sa.String(64), nullable=True),
            sa.Column("product_name", sa.String(255), nullable=False),
            sa.Column("category", sa.String(64), nullable=False),
            sa.Column("price", sa.Integer(), nullable=False),
            sa.Column("quantity", sa.Integer(), server_default="1", nullable=False),
            sa.Column("is_digital", sa.Boolean(), server_default=sa.false(), nullable=False),
            sa.Column("is_refunded", sa.Boolean(), server_default=sa.false(), nullable=False),
        )
        op.create_index("idx_order_items_order", "order_items", ["order_id"])

    # 2. Durable ingestion run and item tables
    if not has_table("ingestion_runs"):
        op.create_table(
            "ingestion_runs",
            sa.Column("run_id", sa.String(64), primary_key=True),
            sa.Column("job_id", sa.String(64), sa.ForeignKey("ingestion_jobs.job_id", ondelete="CASCADE"), nullable=False, unique=True),
            sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("stats", json_type, server_default="{}", nullable=False),
            sa.Column("errors", json_type, server_default="[]", nullable=False),
            sa.Column("logs", json_type, server_default="[]", nullable=False),
            sa.Column("promoted_version_id", sa.String(64), nullable=True),
        )
        op.create_index("idx_ingestion_runs_tenant_started", "ingestion_runs", ["tenant_id", "started_at"])

    if not has_table("ingestion_items"):
        op.create_table(
            "ingestion_items",
            sa.Column("item_id", sa.String(64), primary_key=True),
            sa.Column("run_id", sa.String(64), sa.ForeignKey("ingestion_runs.run_id", ondelete="CASCADE"), nullable=False),
            sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False),
            sa.Column("product_id", sa.String(64), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
            sa.Column("content_hash", sa.String(64), nullable=True),
            sa.Column("error_code", sa.String(64), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("idx_ingestion_items_run_status", "ingestion_items", ["run_id", "status"])
        op.create_index("idx_ingestion_items_tenant_product", "ingestion_items", ["tenant_id", "product_id"])

    if is_postgres:
        for table in ("ingestion_runs", "ingestion_items"):
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
            op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
            op.execute(
                f"CREATE POLICY {table}_tenant_isolation ON {table} "
                "USING (tenant_id = current_setting('app.tenant_id', true)) "
                "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
            )
        # Grant permissions to application role novaretail_app
        op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO novaretail_app;")
        op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO novaretail_app;")


def downgrade():
    bind = op.get_bind()
    is_postgres = getattr(bind, "dialect", None) is not None and bind.dialect.name == "postgresql"
    try:
        inspector = sa.inspect(bind)
    except Exception:
        inspector = None

    has_table = (lambda t: inspector.has_table(t)) if inspector else (lambda t: True)
    if has_table("ingestion_items"):
        op.drop_table("ingestion_items")
    if has_table("ingestion_runs"):
        op.drop_table("ingestion_runs")
    if has_table("product_specs"):
        columns = [c["name"] for c in inspector.get_columns("product_specs")] if inspector else []
        if not inspector or "version_id" in columns:
            op.drop_index("idx_product_specs_version_product", table_name="product_specs")
            if is_postgres:
                op.drop_constraint("fk_product_specs_version", "product_specs", type_="foreignkey")
            op.drop_column("product_specs", "version_id")
