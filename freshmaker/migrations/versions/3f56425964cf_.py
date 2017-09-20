"""Add state_reason to artifact_builds table.

Revision ID: 3f56425964cf
Revises: 300b86758bb1
Create Date: 2017-09-20 11:38:18.176512

"""

# revision identifiers, used by Alembic.
revision = '3f56425964cf'
down_revision = '300b86758bb1'

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column('artifact_builds', sa.Column('state_reason', sa.String(), nullable=True))


def downgrade():
    op.drop_column('artifact_builds', 'state_reason')
