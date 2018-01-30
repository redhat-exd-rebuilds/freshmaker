"""Add unique constraint to Compose.odcs_compose_id

Revision ID: e06434b3ef5e
Revises: b17231ee8220
Create Date: 2017-12-27 14:53:42.321947

"""

# revision identifiers, used by Alembic.
revision = 'e06434b3ef5e'
down_revision = 'b17231ee8220'

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

from freshmaker import db


def upgrade():
    connection = op.get_bind()

    # There might be duplicated odcs_compose_ids in a composes table, so at
    # first find them.
    result = connection.execute(
        text(
            'SELECT odcs_compose_id FROM composes '
            'GROUP BY odcs_compose_id HAVING COUNT(*) > 1'
        )
    )

    # For every duplicate compose, merge the compose records together.
    for row in result:
        odcs_compose_id = row[0]

        # Find out all the DB ids of duplicated this odcs_compose_id.
        compose_ids = connection.execute(
            text(
                'SELECT id FROM composes '
                'WHERE odcs_compose_id = :odcs_compose_id'
            ).bindparams(odcs_compose_id=odcs_compose_id)
        ).fetchall()

        # compose_ids should be always have at least two rows here, because
        # we have only duplicated composes here...
        # Use the first compose id as a main one.
        main_compose_id = compose_ids[0][0]
        # Others will be merged with main compose and removed later.
        composes_to_merge = [row[0] for row in compose_ids[1:]]

        # For each ArtifactBuild, update the compose_id from id in
        # "composes_to_merge" to "main_compose_id".
        # Then remove the merged compose from 'composes' table
        for compose_to_merge_id in composes_to_merge:
            artifact_builds = connection.execute(
                text(
                    'UPDATE artifact_build_composes '
                    'SET compose_id = :main_compose_id '
                    'WHERE compose_id = :compose_to_merge_id'
                ).bindparams(main_compose_id=main_compose_id,
                             compose_to_merge_id=compose_to_merge_id)
            )

            connection.execute(
                text(
                    'DELETE FROM composes '
                    'WHERE id = :compose_to_merge_id'
                ).bindparams(compose_to_merge_id=compose_to_merge_id)
            )

    op.create_index('idx_odcs_compose_id', 'composes', ['odcs_compose_id'], unique=True)


def downgrade():
    # We do not deduplicate data on downgrade, because we cannot get
    # the original state and the duplicates were bug in database handling
    # anyway.
    op.drop_index('idx_odcs_compose_id', table_name='composes')
