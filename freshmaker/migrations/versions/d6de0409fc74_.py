"""Add original_nvr and rebuilt_nvr columns.

Revision ID: d6de0409fc74
Revises: 3f56425964cf
Create Date: 2017-10-10 12:57:59.802658

"""

# revision identifiers, used by Alembic.
revision = 'd6de0409fc74'
down_revision = '3f56425964cf'

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column('artifact_builds', sa.Column('original_nvr', sa.String(), nullable=True))
    op.add_column('artifact_builds', sa.Column('rebuilt_nvr', sa.String(), nullable=True))


def downgrade():
    op.drop_column('artifact_builds', 'rebuilt_nvr')
    op.drop_column('artifact_builds', 'original_nvr')
