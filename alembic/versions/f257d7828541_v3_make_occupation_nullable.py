"""v3_make_occupation_nullable

Revision ID: f257d7828541
Revises: 556a3c5004ba
Create Date: 2026-05-06 19:23:00.298437

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f257d7828541'
down_revision: Union[str, Sequence[str], None] = '556a3c5004ba'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Phase 3.X-fix-10: relax user_inputs.occupation from NOT NULL to
    NULLABLE.

    fix-10 makes Step 1 Q5 (occupation) conditionally rendered based on
    sessions.vec_familiarity (only the top 2 of the 5-pt scale see the
    question). When Q5 is hidden, submit_step1 writes occupation=NULL,
    which the previous NOT NULL constraint rejects. Loosening the
    constraint is safe — existing rows all have non-NULL values, and
    NULL on new rows now carries the meaningful interpretation "user
    was not asked because vec_familiarity is below the gate".
    """
    with op.batch_alter_table('user_inputs', schema=None) as b:
        b.alter_column(
            'occupation',
            existing_type=sa.String(length=64),
            nullable=True,
        )


def downgrade() -> None:
    """Downgrade schema.

    Note: this will fail if any rows have occupation=NULL at downgrade
    time (NOT NULL violation). Operator must back-fill before downgrade.
    """
    with op.batch_alter_table('user_inputs', schema=None) as b:
        b.alter_column(
            'occupation',
            existing_type=sa.String(length=64),
            nullable=False,
        )
