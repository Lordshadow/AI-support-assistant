"""Persist tenant widget presentation settings."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "003_widget_config"
down_revision = "002_staff_session_active_tenant"
branch_labels = None
depends_on = None

def upgrade():
    defaults = '{"name":"NovaRetail Support","greeting":"Hi! How can I help you today?","primaryColor":"#0284c7","theme":"light","launcherSide":"right","quickPrompts":["Track my order","Product questions"],"autoOpen":false}'
    op.add_column("tenants", sa.Column("widget_config", postgresql.JSONB(), nullable=False, server_default=defaults))

def downgrade():
    op.drop_column("tenants", "widget_config")
