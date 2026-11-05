"""Voice, browser teaching, OAuth and synchronization runtime state."""
from alembic import op
import sqlalchemy as sa
revision = '0006_runtime'
down_revision = '0005_rate_window'

def upgrade():
    m = sa.MetaData(); m.reflect(op.get_bind())
    def table(name, *columns, **kwargs):
        return sa.Table(name, m, *columns, **kwargs)
    def org(): return sa.Column('organization_id', sa.Integer, sa.ForeignKey('organizations.id'), nullable=False)
    def col(name, default='', **kw): return sa.Column(name, sa.Text, nullable=False, server_default=default, **kw)
    table('voice_routes', sa.Column('id', sa.Text, primary_key=True), org(), col('name'), col('transfer_channel'), col('greeting', 'Sono SecretAI, la segretaria virtuale. Come posso aiutarti?'), sa.Column('enabled', sa.Integer, nullable=False, server_default='0'))
    table('voice_calls', sa.Column('id', sa.Text, primary_key=True), org(), sa.Column('route_id', sa.Text, sa.ForeignKey('voice_routes.id'), nullable=False), sa.Column('conversation_id', sa.Integer, sa.ForeignKey('conversations.id'), nullable=False), col('status', 'created'), sa.Column('created_at', sa.BigInteger, nullable=False), sa.Column('ended_at', sa.BigInteger), sa.Column('seconds', sa.Integer, nullable=False, server_default='0'))
    table('browser_procedures', sa.Column('id', sa.Text, primary_key=True), org(), col('name'), col('origin'), col('state_ciphertext'), sa.Column('version', sa.Integer, nullable=False, server_default='0'), sa.Column('approved', sa.Integer, nullable=False, server_default='0'), sa.Column('steps_json', sa.Text, nullable=False, server_default='[]'), sa.Column('updated_at', sa.BigInteger, nullable=False))
    table('browser_runs', sa.Column('id', sa.Text, primary_key=True), org(), sa.Column('procedure_id', sa.Text, sa.ForeignKey('browser_procedures.id'), nullable=False), sa.Column('version', sa.Integer, nullable=False), col('status', 'pending'), col('idempotency_key'), col('request_hash'), sa.Column('appointment_id',sa.Integer,sa.ForeignKey('appointments.id')), col('operation','create'), col('variables_ciphertext'), sa.Column('step', sa.Integer, nullable=False, server_default='0'), col('result_json', '{}'), sa.Column('created_at', sa.BigInteger, nullable=False), sa.UniqueConstraint('organization_id','idempotency_key'))
    table('meta_oauth_states', sa.Column('state_hash', sa.Text, primary_key=True), org(), sa.Column('user_id', sa.Integer, nullable=False), col('provider'), sa.Column('expires_at', sa.BigInteger, nullable=False))
    table('google_cursors', org(), col('calendar_id'), col('sync_token'), sa.Column('updated_at', sa.BigInteger, nullable=False, server_default='0'), sa.PrimaryKeyConstraint('organization_id','calendar_id'))
    table('google_watches', sa.Column('id', sa.Text, primary_key=True), org(), col('calendar_id'), col('token_hash'), col('resource_id'), sa.Column('expires_at', sa.BigInteger, nullable=False), sa.Column('last_message', sa.BigInteger, nullable=False, server_default='0'))
    table('external_busy', org(), col('calendar_id'), col('event_id'), col('starts_at'), col('ends_at'), sa.PrimaryKeyConstraint('organization_id','calendar_id','event_id'))
    table('appointment_holds',org(),sa.Column('appointment_id',sa.Integer,sa.ForeignKey('appointments.id'),nullable=False),col('starts_at'),col('ends_at'),sa.PrimaryKeyConstraint('organization_id','appointment_id','starts_at'))
    table('runtime_heartbeats', sa.Column('name', sa.Text, primary_key=True), sa.Column('seen_at', sa.BigInteger, nullable=False))
    table('scheduler_ticks', sa.Column('name', sa.Text, primary_key=True), sa.Column('tick', sa.BigInteger, nullable=False))
    m.create_all(op.get_bind(), checkfirst=True)
    op.add_column('channel_credentials',sa.Column('oauth_user_id',sa.Text,nullable=False,server_default=''))
    op.add_column('conversations', sa.Column('identity_verified', sa.Integer, nullable=False, server_default='0'))
    op.add_column('appointments', sa.Column('booking_token_hash', sa.Text))
    op.add_column('appointments',sa.Column('external_reference',sa.Text,nullable=False,server_default=''))
    op.add_column('services',sa.Column('automation_json',sa.Text,nullable=False,server_default='{}'))
    op.create_index('ix_external_busy_slot','external_busy',['organization_id','starts_at','ends_at'])

def downgrade():
    raise RuntimeError('Restore a verified backup to roll back integration state')
