"""Preserve exact INR values and record refund eligibility data quality."""
from alembic import op
import sqlalchemy as sa

revision = "006_exact_order_refund_amounts"
down_revision = "005_demo_catalog_content"
branch_labels = None
depends_on = None


def upgrade():
    for table, column in (
        ("orders", "total_amount_inr"),
        ("order_items", "price"),
        ("refund_requests", "amount_inr"),
    ):
        with op.batch_alter_table(table) as batch:
            batch.alter_column(column, existing_type=sa.Integer(), type_=sa.Numeric(12, 2), existing_nullable=False)
    with op.batch_alter_table("order_items") as batch:
        batch.add_column(sa.Column("refund_eligibility_verified", sa.Boolean(), server_default=sa.true(), nullable=False))


def downgrade():
    with op.batch_alter_table("order_items") as batch:
        batch.drop_column("refund_eligibility_verified")
        batch.alter_column("price", existing_type=sa.Numeric(12, 2), type_=sa.Integer(), existing_nullable=False)
    with op.batch_alter_table("orders") as batch:
        batch.alter_column("total_amount_inr", existing_type=sa.Numeric(12, 2), type_=sa.Integer(), existing_nullable=False)
    with op.batch_alter_table("refund_requests") as batch:
        batch.alter_column("amount_inr", existing_type=sa.Numeric(12, 2), type_=sa.Integer(), existing_nullable=False)
