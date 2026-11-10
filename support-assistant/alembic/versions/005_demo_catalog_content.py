"""Add product content and customer profile fields for demo data."""
from alembic import op
from alembic import context
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "005_demo_catalog_content"
down_revision = "004_catalog_ingestion_runs"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    json_type = postgresql.JSONB() if is_postgres else sa.JSON()
    if context.is_offline_mode():
        op.add_column("products", sa.Column("description", sa.Text(), server_default="", nullable=False))
        op.add_column("products", sa.Column("faqs", json_type, server_default="[]", nullable=False))
        op.create_table(
            "customers",
            sa.Column("customer_id", sa.String(64), primary_key=True),
            sa.Column("tenant_id", sa.String(64), server_default="tenant_novaretail", nullable=False),
            sa.Column("phone_hash", sa.String(64), nullable=False, unique=True),
            sa.Column("email", sa.String(255), nullable=False, unique=True),
            sa.Column("full_name", sa.String(255), nullable=False),
            sa.Column("language_pref", sa.String(16), server_default="en", nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("idx_customers_tenant", "customers", ["tenant_id"])
        return
    inspector = sa.inspect(bind)

    product_columns = {column["name"] for column in inspector.get_columns("products")}
    if "description" not in product_columns:
        op.add_column("products", sa.Column("description", sa.Text(), server_default="", nullable=False))
    if "faqs" not in product_columns:
        op.add_column(
            "products",
            sa.Column("faqs", json_type, server_default="[]" if is_postgres else "[]", nullable=False),
        )

    if not inspector.has_table("customers"):
        op.create_table(
            "customers",
            sa.Column("customer_id", sa.String(64), primary_key=True),
            sa.Column("tenant_id", sa.String(64), server_default="tenant_novaretail", nullable=False),
            sa.Column("phone_hash", sa.String(64), nullable=False, unique=True),
            sa.Column("email", sa.String(255), nullable=False, unique=True),
            sa.Column("full_name", sa.String(255), nullable=False),
            sa.Column("language_pref", sa.String(16), server_default="en", nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("idx_customers_tenant", "customers", ["tenant_id"])
    else:
        customer_columns = {column["name"] for column in inspector.get_columns("customers")}
        additions = (
            ("tenant_id", sa.Column("tenant_id", sa.String(64), server_default="tenant_novaretail", nullable=False)),
            ("email", sa.Column("email", sa.String(255), server_default="", nullable=False)),
            ("full_name", sa.Column("full_name", sa.String(255), server_default="Demo Customer", nullable=False)),
        )
        for column_name, column in additions:
            if column_name not in customer_columns:
                op.add_column("customers", column)
        if "idx_customers_tenant" not in {
            index["name"] for index in inspector.get_indexes("customers")
        }:
            op.create_index("idx_customers_tenant", "customers", ["tenant_id"])


def downgrade():
    # Offline SQL generation cannot inspect a MockConnection. In the revision
    # chain this migration created these objects, so emit the deterministic DDL.
    if context.is_offline_mode():
        op.drop_index("idx_customers_tenant", table_name="customers")
        op.drop_table("customers")
        op.drop_column("products", "faqs")
        op.drop_column("products", "description")
        return
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("customers"):
        op.drop_index("idx_customers_tenant", table_name="customers")
        op.drop_table("customers")
    columns = {column["name"] for column in inspector.get_columns("products")}
    if "faqs" in columns:
        op.drop_column("products", "faqs")
    if "description" in columns:
        op.drop_column("products", "description")
