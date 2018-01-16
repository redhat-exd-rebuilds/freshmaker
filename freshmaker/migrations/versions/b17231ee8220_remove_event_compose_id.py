"""Remove Event.compose_id

Revision ID: b17231ee8220
Revises: 6004dadc9ac4
Create Date: 2017-12-25 10:51:05.484216

"""

# revision identifiers, used by Alembic.
revision = 'b17231ee8220'
down_revision = '6004dadc9ac4'

import logging
logger = logging.getLogger(__name__)

from itertools import count
from six import next
import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

from freshmaker import db
from freshmaker.models import ArtifactBuild, ArtifactBuildCompose
from freshmaker.models import Event, Compose


def upgrade():
    # First, we must migrate data from Event.compose_id to Compose model
    session = db.session
    connection = op.get_bind()

    for row in connection.execute('SELECT id, compose_id FROM events'):
        event_id, odcs_compose_id = row

        # Skip the events with NULL/None compose_id.
        if odcs_compose_id is None:
            continue

        logger.info('Create Compose with odcs_compose_id %s from Event %s',
                    odcs_compose_id, event_id)
        connection.execute(
            text(
                'INSERT INTO composes (odcs_compose_id) VALUES (:compose_id)'
            ).bindparams(compose_id=odcs_compose_id),
            autocommit=True
        )

        result = connection.execute(
            text(
                'SELECT id FROM composes WHERE odcs_compose_id = :compose_id'
            ).bindparams(compose_id=odcs_compose_id)
        )
        new_compose_id = result.fetchall()[0][0]

        build_ids = connection.execute(
            text(
                'SELECT DISTINCT id FROM artifact_builds '
                'WHERE event_id = :event_id'
            ).bindparams(event_id=event_id)
        )

        with connection.begin():
            for row in build_ids:
                build_id, = row
                connection.execute(
                    text(
                        'INSERT INTO artifact_build_composes (build_id, compose_id) '
                        'VALUES (:build_id, :compose_id)'
                    ).bindparams(build_id=build_id,
                                 compose_id=new_compose_id)
                )

    # Now, migration is doable
    with op.batch_alter_table("events") as batch_op:
        batch_op.drop_column('compose_id')


def downgrade():
    # First, we have to restore Event.compose_id
    with op.batch_alter_table("events") as batch_op:
        batch_op.add_column(sa.Column('compose_id', sa.Integer(), nullable=True))

    # It is time to restore data from Compose model back to Event.compose_id
    session = db.session
    connection = op.get_bind()

    with connection.begin():
        for compose in session.query(Compose).all():
            if len(compose.builds) == 0:
                raise ValueError(
                    'Compose {} is not associated with any ArtifactBuild. '
                    'This must be a problem in production. Or may not be a '
                    'problem due to dirty data in development environment. '
                    'Please confirm and handle by yourself.'.format(compose.id))
            event = compose.builds[0].build.event
            logger.info(
                'Restore odcs compose id %s from Compose %s back to Event %s',
                compose.odcs_compose_id, compose.id, event.id)
            connection.execute(
                'UPDATE events SET compose_id = {} WHERE id = {}'.format(
                    compose.odcs_compose_id, event.id))

        logger.info('Clear data from ArtifactBuildCompose')
        connection.execute('DELETE FROM artifact_build_composes')
        logger.info('Clear data from Compose')
        connection.execute('DELETE FROM composes')
