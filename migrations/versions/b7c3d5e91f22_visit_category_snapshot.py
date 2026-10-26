"""attendance.category_at_visit: remember the category on each Sunday

Revision ID: b7c3d5e91f22
Revises: a1f4c2d9e801
"""
from alembic import op
import sqlalchemy as sa

revision = 'b7c3d5e91f22'
down_revision = 'a1f4c2d9e801'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('attendance') as b:
        b.add_column(sa.Column('category_at_visit', sa.String(10), nullable=True))
    op.execute("UPDATE attendance SET category_at_visit = "
               "(SELECT category FROM people WHERE people.id = attendance.person_id)")


def downgrade():
    with op.batch_alter_table('attendance') as b:
        b.drop_column('category_at_visit')
