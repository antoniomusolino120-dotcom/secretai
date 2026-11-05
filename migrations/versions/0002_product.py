"""Tenant settings, CRM, inbox, audit and idempotent operations."""
from alembic import op
import sqlalchemy as sa

revision = "0002_product"
down_revision = "0001_baseline"


def upgrade():
    for table, columns in {
        "organizations": [sa.Column("timezone", sa.Text, nullable=False, server_default="Europe/Rome"),
                          sa.Column("instructions", sa.Text, nullable=False, server_default=""),
                          sa.Column("knowledge", sa.Text, nullable=False, server_default=""),
                          sa.Column("hours_json", sa.Text, nullable=False, server_default="{}"),
                          sa.Column("assistant_enabled", sa.Integer, nullable=False, server_default="0")],
        "users": [sa.Column("email_verified", sa.Integer, nullable=False, server_default="0")],
        "sessions": [sa.Column("csrf_hash", sa.Text)],
        "services": [sa.Column("price_cents", sa.Integer, nullable=False, server_default="0"),
                     sa.Column("active", sa.Integer, nullable=False, server_default="1")],
        "appointments": [sa.Column("status", sa.Text, nullable=False, server_default="confirmed"),
                         sa.Column("contact_id", sa.Integer),
                         sa.Column("external_event_id", sa.Text),
                         sa.Column("sync_status", sa.Text, nullable=False, server_default="local")],
    }.items():
        for column in columns:
            op.add_column(table, column)
    metadata = sa.MetaData()
    # Resolve foreign keys against existing tables, including compound tenant keys.
    metadata.reflect(op.get_bind())
    sa.Table("contacts", metadata, sa.Column("id", sa.Integer, primary_key=True),
             sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id"), nullable=False),
             sa.Column("name", sa.Text, nullable=False), sa.Column("email", sa.Text, nullable=False, server_default=""),
             sa.Column("phone", sa.Text, nullable=False, server_default=""),
             sa.Column("notes", sa.Text, nullable=False, server_default=""),
             sa.Column("created_at", sa.BigInteger, nullable=False),
             sa.UniqueConstraint("id", "organization_id"))
    sa.Table("conversations", metadata, sa.Column("id", sa.Integer, primary_key=True),
             sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id"), nullable=False),
             sa.Column("contact_id", sa.Integer), sa.Column("channel", sa.Text, nullable=False),
             sa.Column("external_id", sa.Text, nullable=False),
             sa.Column("status", sa.Text, nullable=False, server_default="ai"),
             sa.Column("updated_at", sa.BigInteger, nullable=False),
             sa.UniqueConstraint("organization_id", "channel", "external_id"),
             sa.UniqueConstraint("id", "organization_id"),
             sa.ForeignKeyConstraint(["contact_id", "organization_id"], ["contacts.id", "contacts.organization_id"]))
    sa.Table("messages", metadata, sa.Column("id", sa.Integer, primary_key=True),
             sa.Column("organization_id", sa.Integer, nullable=False),
             sa.Column("conversation_id", sa.Integer, nullable=False),
             sa.Column("direction", sa.Text, nullable=False), sa.Column("body", sa.Text, nullable=False),
             sa.Column("created_at", sa.BigInteger, nullable=False),
             sa.Column("delivery_status", sa.Text, nullable=False, server_default="received"),
             sa.Column("external_id", sa.Text),
             sa.UniqueConstraint("organization_id", "external_id"),
             sa.ForeignKeyConstraint(["conversation_id", "organization_id"], ["conversations.id", "conversations.organization_id"]))
    sa.Table("audit_events", metadata, sa.Column("id", sa.Integer, primary_key=True),
             sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id")),
             sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id")),
             sa.Column("action", sa.Text, nullable=False), sa.Column("entity_id", sa.Text, nullable=False),
             sa.Column("created_at", sa.BigInteger, nullable=False))
    sa.Table("idempotency_keys", metadata,
             sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id"), primary_key=True),
             sa.Column("key", sa.Text, primary_key=True), sa.Column("request_hash", sa.Text, nullable=False),
             sa.Column("response_json", sa.Text, nullable=False), sa.Column("created_at", sa.BigInteger, nullable=False))
    sa.Table("rate_limits", metadata, sa.Column("bucket", sa.Text, primary_key=True),
             sa.Column("window", sa.BigInteger, nullable=False), sa.Column("count", sa.Integer, nullable=False))
    sa.Table("auth_challenges", metadata, sa.Column("token_hash", sa.Text, primary_key=True),
             sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
             sa.Column("purpose", sa.Text, nullable=False), sa.Column("expires_at", sa.BigInteger, nullable=False))
    sa.Table("jobs", metadata, sa.Column("id", sa.Integer, primary_key=True),
             sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id"), nullable=False),
             sa.Column("kind", sa.Text, nullable=False), sa.Column("payload_json", sa.Text, nullable=False),
             sa.Column("dedupe_key", sa.Text, nullable=False, unique=True),
             sa.Column("status", sa.Text, nullable=False, server_default="pending"),
             sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
             sa.Column("available_at", sa.BigInteger, nullable=False),
             sa.Column("locked_until", sa.BigInteger), sa.Column("lease_token", sa.Text),
             sa.Column("last_error", sa.Text, nullable=False, server_default=""))
    metadata.create_all(op.get_bind(), checkfirst=True)
    op.create_index("ix_appointments_overlap", "appointments", ["organization_id", "status", "starts_at", "ends_at"])
    op.create_index("ix_messages_conversation", "messages", ["organization_id", "conversation_id", "id"])
    op.create_index("ix_audit_org", "audit_events", ["organization_id", "id"])
    op.create_index("ix_jobs_ready", "jobs", ["status", "available_at"])
    # Reject corrupt legacy service references before adding tenant constraints.
    bad = op.get_bind().execute(sa.text("SELECT a.id FROM appointments a LEFT JOIN services s ON s.id=a.service_id AND s.organization_id=a.organization_id WHERE s.id IS NULL LIMIT 1")).first()
    if bad:
        raise RuntimeError("Legacy appointment references an invalid tenant service; repair before migration")
    with op.batch_alter_table("services") as batch:
        batch.create_unique_constraint("uq_services_tenant", ["id", "organization_id"])
        batch.create_check_constraint("ck_service_duration", "duration_minutes >= 5 AND duration_minutes <= 480")
        batch.create_check_constraint("ck_service_price", "price_cents >= 0")
    with op.batch_alter_table("appointments") as batch:
        batch.create_foreign_key("fk_appointment_service_tenant", "services", ["service_id", "organization_id"], ["id", "organization_id"])
        batch.create_foreign_key("fk_appointment_contact_tenant", "contacts", ["contact_id", "organization_id"], ["id", "organization_id"])
        batch.create_check_constraint("ck_appointment_interval", "ends_at > starts_at")


def downgrade():
    raise RuntimeError("Restore a backup to roll back the schema without silent data loss")
