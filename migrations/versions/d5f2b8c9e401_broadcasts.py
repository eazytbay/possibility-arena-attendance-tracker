"""broadcasts: admin-sent messages to a group, with one row per recipient

Revision ID: d5f2b8c9e401
Revises: c4e8a1f7b305
"""
from alembic import op
import sqlalchemy as sa

revision = 'd5f2b8c9e401'
down_revision = 'c4e8a1f7b305'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'broadcasts',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('created_by', sa.String(80), nullable=False),
        sa.Column('audience', sa.String(200), nullable=False),
        sa.Column('text', sa.String(1000), nullable=False),
        sa.Column('status', sa.String(10), nullable=False),
        sa.Column('error', sa.String(200), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        'broadcast_recipients',
        sa.Column('broadcast_id', sa.Integer(), sa.ForeignKey('broadcasts.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('person_id', sa.Integer(), sa.ForeignKey('people.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('status', sa.String(8), nullable=False),
        sa.Column('error', sa.String(200), nullable=True),
        sa.Column('provider_id', sa.String(64), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table('broadcast_recipients')
    op.drop_table('broadcasts')
