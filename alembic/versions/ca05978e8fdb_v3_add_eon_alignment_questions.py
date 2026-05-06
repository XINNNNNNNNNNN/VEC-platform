"""v3_add_eon_alignment_questions

Revision ID: ca05978e8fdb
Revises: 199229e83cbd
Create Date: 2026-05-06 15:32:33.430655

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ca05978e8fdb'
down_revision: Union[str, Sequence[str], None] = '199229e83cbd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Phase 3.X-fix-7: align platform with the E.ON B2C survey so KTH/E.ON
    can compare answers across the two studies.

      sessions.vec_familiarity     — E.ON Q9, 5-point single choice asked
                                      at Step 0 *before* the first prior
                                      expectation slider so it serves as
                                      a covariate for the info-calibration
                                      A/B/C arm.
      survey_responses.fairness_likert — E.ON Q11, 1..7 Likert ("how fair
                                      is preferential treatment for VEC
                                      participants?") asked at Step 7.
      survey_responses.drivers_top3 — E.ON Q13, max-3 multi-select stored
                                      as a JSON-encoded list of strings.
                                      Asked at Step 8 just before demos.
    """
    with op.batch_alter_table('sessions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('vec_familiarity', sa.String(length=32), nullable=True))

    with op.batch_alter_table('survey_responses', schema=None) as batch_op:
        batch_op.add_column(sa.Column('drivers_top3', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('fairness_likert', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('survey_responses', schema=None) as batch_op:
        batch_op.drop_column('fairness_likert')
        batch_op.drop_column('drivers_top3')

    with op.batch_alter_table('sessions', schema=None) as batch_op:
        batch_op.drop_column('vec_familiarity')
