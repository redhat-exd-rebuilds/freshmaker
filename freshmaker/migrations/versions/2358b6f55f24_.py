"""Add time done for Freshmaker events

Revision ID: 2358b6f55f24
Revises: fbc2eac9bfa5
Create Date: 2019-06-20 10:00:31.190304

"""

revision = '2358b6f55f24'
down_revision = 'fbc2eac9bfa5'

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column('events', sa.Column('time_done', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('events', 'time_done')
