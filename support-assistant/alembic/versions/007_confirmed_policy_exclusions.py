"""Persist explicitly confirmed refund exclusion categories."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "007_confirmed_policy_exclusions"
down_revision = "006_exact_order_refund_amounts"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "tenant_policy_configs",
        sa.Column("excluded_categories", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade():
    op.drop_column("tenant_policy_configs", "excluded_categories")
