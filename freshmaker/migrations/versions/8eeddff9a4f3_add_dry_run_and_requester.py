"""Add dry_run and requester to events table.

Revision ID: 8eeddff9a4f3
Revises: 807ea37dcf0e
Create Date: 2018-11-02 09:07:26.898276

"""

# revision identifiers, used by Alembic.
revision = '8eeddff9a4f3'
down_revision = '807ea37dcf0e'

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column('events', sa.Column('dry_run', sa.Boolean(), nullable=True))
    op.add_column('events', sa.Column('requester', sa.String(), nullable=True))


def downgrade():
    op.drop_column('events', 'requester')
    op.drop_column('events', 'dry_run')
