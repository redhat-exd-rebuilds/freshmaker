"""Add event state and timestamp

Revision ID: 90f8444d5ab7
Revises: 2f5a2f4385a0
Create Date: 2017-11-20 23:16:44.079911

"""

# revision identifiers, used by Alembic.
revision = '90f8444d5ab7'
down_revision = '2f5a2f4385a0'

from alembic import op
import sqlalchemy as sa

from freshmaker.models import Event
from freshmaker.types import EventState


def upgrade():
    with op.batch_alter_table('events', schema=None) as batch_op:
        batch_op.add_column(sa.Column('state', sa.Integer(), server_default=str(EventState.INITIALIZED.value), nullable=False))
        batch_op.add_column(sa.Column('state_reason', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('time_created', sa.DateTime(), nullable=True))

    # update state to 'COMPLETE' for historical events
    op.execute(
        sa.update(Event).values({
            'state': op.inline_literal(EventState.COMPLETE.value)
        })
    )


def downgrade():
    with op.batch_alter_table('events', schema=None) as batch_op:
        batch_op.drop_column('state')
        batch_op.drop_column('state_reason')
        batch_op.drop_column('time_created')
