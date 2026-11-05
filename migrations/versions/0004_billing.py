"""Subscription reconciliation and atomic usage accounting."""
from alembic import op
import sqlalchemy as sa

revision = "0004_billing"
down_revision = "0003_integrations"


def upgrade():
    metadata = sa.MetaData()
    metadata.reflect(op.get_bind())
    sa.Table("billing_accounts", metadata,
             sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id"), primary_key=True),
             sa.Column("stripe_customer_id", sa.Text, nullable=False, unique=True),
             sa.Column("stripe_subscription_id", sa.Text, unique=True),
             sa.Column("plan", sa.Text, nullable=False, server_default=""),
             sa.Column("status", sa.Text, nullable=False, server_default="incomplete"),
             sa.Column("period_start", sa.BigInteger, nullable=False, server_default="0"),
             sa.Column("period_end", sa.BigInteger, nullable=False, server_default="0"),
             sa.Column("cancel_at_period_end", sa.Integer, nullable=False, server_default="0"),
             sa.Column("risk_review", sa.Integer, nullable=False, server_default="0"),
             sa.Column("updated_at", sa.BigInteger, nullable=False, server_default="0"))
    sa.Table("stripe_events", metadata, sa.Column("id", sa.Text, primary_key=True),
             sa.Column("type", sa.Text, nullable=False), sa.Column("created_at", sa.BigInteger, nullable=False))
    sa.Table("usage_events", metadata,
             sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id"), primary_key=True),
             sa.Column("key", sa.Text, primary_key=True), sa.Column("metric", sa.Text, nullable=False),
             sa.Column("amount", sa.Integer, nullable=False), sa.Column("period_start", sa.BigInteger, nullable=False),
             sa.Column("created_at", sa.BigInteger, nullable=False))
    metadata.create_all(op.get_bind(), checkfirst=True)
    op.create_index("ix_usage_period", "usage_events", ["organization_id", "period_start", "metric"])


def downgrade():
    raise RuntimeError("Restore a backup to roll back the schema")
