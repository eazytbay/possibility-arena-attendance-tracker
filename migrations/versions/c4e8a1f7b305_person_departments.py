"""person_departments: a person can serve in more than one department

Revision ID: c4e8a1f7b305
Revises: b7c3d5e91f22

The old people.department column is copied across and then left in place (no longer read by the app),
so rolling the code back does not need a database downgrade. Drop the column in a later migration.
"""
from alembic import op
import sqlalchemy as sa

revision = 'c4e8a1f7b305'
down_revision = 'b7c3d5e91f22'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'person_departments',
        sa.Column('person_id', sa.Integer(), sa.ForeignKey('people.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('department', sa.String(40), primary_key=True),
    )
    op.execute("INSERT INTO person_departments (person_id, department) "
               "SELECT id, department FROM people WHERE department IS NOT NULL AND department <> ''")


def downgrade():
    # Put each person's first department (alphabetical) back in the old column, then drop the table.
    op.execute("UPDATE people SET department = (SELECT MIN(department) FROM person_departments "
               "WHERE person_departments.person_id = people.id)")
    op.drop_table('person_departments')
