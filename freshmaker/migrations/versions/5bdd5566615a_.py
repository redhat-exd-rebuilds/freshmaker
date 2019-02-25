"""Add requester_metadata to Events table.

Revision ID: 5bdd5566615a
Revises: 5a555923da42
Create Date: 2019-02-25 15:02:13.847086

"""

# revision identifiers, used by Alembic.
revision = '5bdd5566615a'
down_revision = '5a555923da42'

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column('events', sa.Column('requester_metadata', sa.String(), nullable=True))


def downgrade():
    op.drop_column('events', 'requester_metadata')
