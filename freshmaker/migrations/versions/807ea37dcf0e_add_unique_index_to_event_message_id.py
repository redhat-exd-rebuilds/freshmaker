"""Add unique index to Event.message_id

Revision ID: 807ea37dcf0e
Revises: e06434b3ef5e
Create Date: 2018-01-05 11:17:48.343156

"""

# revision identifiers, used by Alembic.
revision = '807ea37dcf0e'
down_revision = 'e06434b3ef5e'

from alembic import op
import sqlalchemy as sa


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_index('idx_event_message_id', 'events', ['message_id'], unique=True)
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index('idx_event_message_id', table_name='events')
    # ### end Alembic commands ###
