"""Add bundle_pullspec_overrides to artifact_builds

Revision ID: fcba8824bf8d
Revises: 2358b6f55f24
Create Date: 2021-01-11 21:36:49.189627

"""

# revision identifiers, used by Alembic.
revision = 'fcba8824bf8d'
down_revision = '2358b6f55f24'

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column('artifact_builds', sa.Column('bundle_pullspec_overrides', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('artifact_builds', 'bundle_pullspec_overrides')
