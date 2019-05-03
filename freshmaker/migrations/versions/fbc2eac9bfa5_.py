"""Add rebuild_reason column.

Revision ID: fbc2eac9bfa5
Revises: 5bdd5566615a
Create Date: 2019-04-23 10:20:00.766108

"""

# revision identifiers, used by Alembic.
revision = 'fbc2eac9bfa5'
down_revision = '5bdd5566615a'

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column('artifact_builds', sa.Column('rebuild_reason', sa.Integer(), nullable=True))


def downgrade():
    op.drop_column('artifact_builds', 'rebuild_reason')
