"""Baseline, including the original local database (no data is deleted)."""
from alembic import op
import sqlalchemy as sa

revision = "0001_baseline"
down_revision = None


def upgrade():
    metadata = sa.MetaData()
    sa.Table("organizations", metadata, sa.Column("id", sa.Integer, primary_key=True),
             sa.Column("name", sa.Text, nullable=False))
    sa.Table("users", metadata, sa.Column("id", sa.Integer, primary_key=True),
             sa.Column("email", sa.Text, nullable=False, unique=True),
             sa.Column("password_hash", sa.Text, nullable=False), sa.Column("salt", sa.Text, nullable=False))
    sa.Table("memberships", metadata,
             sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), primary_key=True),
             sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id"), primary_key=True),
             sa.Column("role", sa.Text, nullable=False), sa.CheckConstraint("role IN ('owner','member')"))
    sa.Table("sessions", metadata, sa.Column("token_hash", sa.Text, primary_key=True),
             sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
             sa.Column("expires_at", sa.BigInteger, nullable=False))
    sa.Table("services", metadata, sa.Column("id", sa.Integer, primary_key=True),
             sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id"), nullable=False),
             sa.Column("name", sa.Text, nullable=False), sa.Column("duration_minutes", sa.Integer, nullable=False))
    sa.Table("appointments", metadata, sa.Column("id", sa.Integer, primary_key=True),
             sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id"), nullable=False),
             sa.Column("customer", sa.Text, nullable=False), sa.Column("service_id", sa.Integer, nullable=False),
             sa.Column("starts_at", sa.Text, nullable=False), sa.Column("ends_at", sa.Text, nullable=False))
    sa.Table("meta_channels", metadata,
             sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id"), nullable=False),
             sa.Column("provider", sa.Text, nullable=False), sa.Column("external_id", sa.Text, nullable=False),
             sa.UniqueConstraint("provider", "external_id"))
    sa.Table("meta_messages", metadata, sa.Column("id", sa.Integer, primary_key=True),
             sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id"), nullable=False),
             sa.Column("provider", sa.Text, nullable=False), sa.Column("message_id", sa.Text, nullable=False),
             sa.Column("sender_id", sa.Text, nullable=False), sa.Column("body", sa.Text, nullable=False),
             sa.Column("received_at", sa.BigInteger, nullable=False), sa.UniqueConstraint("provider", "message_id"))
    sa.Table("google_connections", metadata,
             sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id"), primary_key=True),
             sa.Column("token_ciphertext", sa.Text, nullable=False),
             sa.Column("calendar_id", sa.Text, nullable=False, server_default="primary"))
    sa.Table("google_oauth_states", metadata, sa.Column("state_hash", sa.Text, primary_key=True),
             sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id"), nullable=False),
             sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
             sa.Column("expires_at", sa.BigInteger, nullable=False))
    metadata.create_all(op.get_bind(), checkfirst=True)


def downgrade():
    raise RuntimeError("Baseline downgrade is destructive; restore the documented backup instead")
