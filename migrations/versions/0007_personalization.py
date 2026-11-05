"""Owner vocabulary, intake snapshots and durable chat turns."""
from alembic import op
import sqlalchemy as sa
revision='0007_personalization'
down_revision='0006_runtime'

def upgrade():
    for name,default in [('description',''),('aliases_json','[]'),('intake_questions_json','[]')]:
        op.add_column('services',sa.Column(name,sa.Text,nullable=False,server_default=default))
    op.add_column('appointments',sa.Column('intake_json',sa.Text,nullable=False,server_default='[]'))
    op.add_column('booking_proposals',sa.Column('created_at',sa.BigInteger,nullable=False,server_default='0'))
    op.create_table('booking_intake_drafts',
        sa.Column('organization_id',sa.Integer,sa.ForeignKey('organizations.id'),primary_key=True),
        sa.Column('scope',sa.Text,primary_key=True),sa.Column('payload_json',sa.Text,nullable=False),
        sa.Column('questions_json',sa.Text,nullable=False),sa.Column('expires_at',sa.BigInteger,nullable=False))
    op.create_table('chat_turns',sa.Column('organization_id',sa.Integer,nullable=False),
        sa.Column('user_id',sa.Integer,sa.ForeignKey('users.id'),nullable=False),sa.Column('request_key',sa.Text,nullable=False),
        sa.Column('conversation_id',sa.Integer,nullable=False),sa.Column('request_hash',sa.Text,nullable=False),
        sa.Column('status',sa.Text,nullable=False,server_default='running'),sa.Column('response_json',sa.Text),
        sa.Column('created_at',sa.BigInteger,nullable=False),sa.PrimaryKeyConstraint('organization_id','user_id','request_key'),
        sa.ForeignKeyConstraint(['conversation_id','organization_id'],['conversations.id','conversations.organization_id']))
    op.create_index('ix_chat_turns_active','chat_turns',['organization_id','conversation_id','status'])

def downgrade():
    op.drop_index('ix_chat_turns_active',table_name='chat_turns');op.drop_table('chat_turns');op.drop_table('booking_intake_drafts')
    op.drop_column('booking_proposals','created_at');op.drop_column('appointments','intake_json')
    for name in ['intake_questions_json','aliases_json','description']:op.drop_column('services',name)
