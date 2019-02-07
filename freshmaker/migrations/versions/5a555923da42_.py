"""Add requested_rebuilds column to events table.

Revision ID: 5a555923da42
Revises: 8eeddff9a4f3
Create Date: 2019-02-07 08:22:29.216868

"""

# revision identifiers, used by Alembic.
revision = '5a555923da42'
down_revision = '8eeddff9a4f3'

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column('events', sa.Column('requested_rebuilds', sa.String(), nullable=True))


def downgrade():
    op.drop_column('events', 'requested_rebuilds')
