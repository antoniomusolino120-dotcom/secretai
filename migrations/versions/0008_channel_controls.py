"""Independent response schedules and the selected booking destination."""
import json
from alembic import op
import sqlalchemy as sa

revision = '0008_channel_controls'
down_revision = '0007_personalization'


def upgrade():
    op.create_table('channel_controls',
        sa.Column('organization_id', sa.Integer, sa.ForeignKey('organizations.id'), primary_key=True),
        sa.Column('channel', sa.Text, primary_key=True),
        sa.Column('enabled', sa.Integer, nullable=False, server_default='0'),
        sa.Column('all_day', sa.Integer, nullable=False, server_default='1'),
        sa.Column('start_time', sa.Text, nullable=False, server_default='18:00'),
        sa.Column('end_time', sa.Text, nullable=False, server_default='09:00'),
        sa.Column('days_json', sa.Text, nullable=False, server_default='[0,1,2,3,4,5,6]'),
        sa.Column('revision', sa.Integer, nullable=False, server_default='1'))
    op.add_column('organizations', sa.Column('calendar_target', sa.Text, nullable=False, server_default='auto'))
    op.add_column('appointments', sa.Column('destination', sa.Text, nullable=False, server_default='auto'))
    op.add_column('appointments', sa.Column('created_by_ai', sa.Integer, nullable=False, server_default='0'))
    connection = op.get_bind()
    for row in connection.execute(sa.text('SELECT organization_id,result_json FROM booking_proposals WHERE result_json IS NOT NULL')).mappings():
        appointment = json.loads(row['result_json']).get('appointment', {})
        if appointment.get('id'):
            connection.execute(sa.text('UPDATE appointments SET created_by_ai=1 WHERE id=:id AND organization_id=:org'), {'id': appointment['id'], 'org': row['organization_id']})
    op.add_column('voice_calls', sa.Column('automation_revision', sa.Integer, nullable=False, server_default='0'))


def downgrade():
    op.drop_column('voice_calls', 'automation_revision')
    op.drop_column('appointments', 'created_by_ai')
    op.drop_column('appointments', 'destination')
    op.drop_column('organizations', 'calendar_target')
    op.drop_table('channel_controls')
