"""pilot prep unique survey responses

Revision ID: 904b52105716
Revises: c8f3e2a4b7d1
Create Date: 2026-05-13 10:15:51.695501

Pilot deployment hardening: survey_responses lacked UNIQUE on
session_id, allowing a participant who pressed Submit twice (or used
browser back+forward+resubmit) to produce duplicate rows. The
analysis pipeline would then double-count their answers.

Safety net: dedupe before the constraint goes on, keeping the
latest row per session_id (MAX(id), since survey_responses.id is
the autoincrement insert order). Current DB has 0 duplicates so
the DELETE is a no-op, but it guards against any session that
slipped through pre-deploy.

batch_alter_table is required for SQLite to add a UNIQUE constraint
on an existing table (SQLite cannot ALTER TABLE ADD CONSTRAINT
directly). alembic env_py already sets render_as_batch=True, but
the explicit `with op.batch_alter_table(...)` keeps the intent
visible and lets the migration emit the same idempotent shape under
non-SQLite backends if we ever migrate the analyst DB.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '904b52105716'
down_revision: Union[str, Sequence[str], None] = 'c8f3e2a4b7d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Dedupe any existing rows so the UNIQUE constraint can be added.
    # Keeps the latest row per session_id (highest id = latest insert).
    op.execute(
        """
        DELETE FROM survey_responses
        WHERE id NOT IN (
            SELECT MAX(id) FROM survey_responses GROUP BY session_id
        )
        """
    )

    with op.batch_alter_table('survey_responses') as batch_op:
        batch_op.create_unique_constraint(
            'uq_survey_responses_session_id', ['session_id']
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('survey_responses') as batch_op:
        batch_op.drop_constraint(
            'uq_survey_responses_session_id', type_='unique'
        )
