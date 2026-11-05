"""Use a portable, non-reserved name for the throttling window."""
from alembic import op
import sqlalchemy as sa

revision = "0005_rate_window"
down_revision = "0004_billing"


def upgrade():
    op.alter_column("rate_limits", "window", new_column_name="window_start", existing_type=sa.BigInteger())


def downgrade():
    op.alter_column("rate_limits", "window_start", new_column_name="window", existing_type=sa.BigInteger())
