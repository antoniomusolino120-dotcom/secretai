"""Encrypted integration tokens, selected calendars and AI proposals."""
from alembic import op
import sqlalchemy as sa

revision = "0003_integrations"
down_revision = "0002_product"


def upgrade():
    op.add_column("google_connections", sa.Column("read_calendar_ids_json", sa.Text, nullable=False, server_default='["primary"]'))
    op.add_column("google_oauth_states", sa.Column("verifier_ciphertext", sa.Text))
    metadata = sa.MetaData()
    metadata.reflect(op.get_bind())
    sa.Table("channel_credentials", metadata,
             sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id"), primary_key=True),
             sa.Column("provider", sa.Text, primary_key=True),
             sa.Column("token_ciphertext", sa.Text, nullable=False),
             sa.Column("expires_at", sa.BigInteger))
    sa.Table("booking_proposals", metadata, sa.Column("id", sa.Text, primary_key=True),
             sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id"), nullable=False),
             sa.Column("conversation_id", sa.Integer),
             sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id")),
             sa.Column("payload_json", sa.Text, nullable=False),
             sa.Column("expires_at", sa.BigInteger, nullable=False),
             sa.Column("result_json", sa.Text),
             sa.ForeignKeyConstraint(["conversation_id", "organization_id"], ["conversations.id", "conversations.organization_id"]))
    metadata.create_all(op.get_bind(), checkfirst=True)


def downgrade():
    raise RuntimeError("Restore a backup to roll back the schema")
