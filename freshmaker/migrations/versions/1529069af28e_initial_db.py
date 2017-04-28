"""Initial database

Revision ID: 1529069af28e
Revises: None
Create Date: 2017-04-28 13:43:23.340055

"""

# revision identifiers, used by Alembic.
revision = '1529069af28e'
down_revision = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.create_table('events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('message_id', sa.String(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('artifact_builds',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('type', sa.Integer(), nullable=True),
    sa.Column('state', sa.Integer(), nullable=False),
    sa.Column('time_submitted', sa.DateTime(), nullable=False),
    sa.Column('time_completed', sa.DateTime(), nullable=True),
    sa.Column('dep_of_id', sa.Integer(), nullable=True),
    sa.Column('event_id', sa.Integer(), nullable=True),
    sa.Column('build_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['dep_of_id'], ['artifact_builds.id'], ),
    sa.ForeignKeyConstraint(['event_id'], ['events.id'], ),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('artifact_builds')
    op.drop_table('events')
