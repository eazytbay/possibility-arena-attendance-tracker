"""sms greetings: opt-in flag and message log

Revision ID: a1f4c2d9e801
Revises: 0c97830adcc3
"""
from alembic import op
import sqlalchemy as sa

revision = 'a1f4c2d9e801'
down_revision = '0c97830adcc3'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('people') as b:
        b.add_column(sa.Column('sms_opt_in', sa.Boolean(), nullable=False, server_default=sa.true()))
    op.create_table(
        'message_log',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('person_id', sa.Integer(), sa.ForeignKey('people.id'), nullable=False),
        sa.Column('kind', sa.String(12), nullable=False),
        sa.Column('period_key', sa.String(10), nullable=False),
        sa.Column('status', sa.String(8), nullable=False),
        sa.Column('attempts', sa.SmallInteger(), nullable=False),
        sa.Column('provider_id', sa.String(64), nullable=True),
        sa.Column('error', sa.String(200), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('person_id', 'kind', 'period_key', name='uq_message_once'),
    )
    op.create_index('ix_message_log_person_id', 'message_log', ['person_id'])


def downgrade():
    op.drop_index('ix_message_log_person_id', table_name='message_log')
    op.drop_table('message_log')
    with op.batch_alter_table('people') as b:
        b.drop_column('sms_opt_in')
