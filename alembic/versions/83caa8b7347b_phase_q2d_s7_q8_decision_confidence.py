"""phase_q2d_s7_q8_decision_confidence

Revision ID: 83caa8b7347b
Revises: 144049b2d153
Create Date: 2026-05-19 11:18:16.197345

Phase Q-2d: add the post-information decision-confidence column to
exit_thresholds.

exit_thresholds.entry_threshold_decision_confidence
  Integer, nullable. Holds the S7-Q8 Final Decision Confidence
  1-5 Likert captured immediately after the S7-Q7 entry-threshold
  slider in Step 7. Pairs with user_inputs.entry_threshold_decision_confidence
  (Q-2a's S0-Q3) for the ΔConfidence = S7-Q8 - S0-Q3 analysis: how
  the journey through the platform changes the participant's
  certainty about their stated threshold.

  Nullable because:
  - existing rows from pre-Q-2d sessions have no answer (they were
    submitted before the question existed)
  - the ExitThreshold row is created at Step 7 submit, so a partial
    workflow (started Step 7, didn't submit) leaves no row at all —
    not a null column

batch_alter_table is required because SQLite cannot ALTER TABLE ADD
COLUMN with certain constraint combinations. env.py sets
render_as_batch=True globally; the wrapper is a no-op on PostgreSQL.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '83caa8b7347b'
down_revision: Union[str, Sequence[str], None] = '144049b2d153'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('exit_thresholds', schema=None) as b:
        b.add_column(sa.Column(
            'entry_threshold_decision_confidence',
            sa.Integer(),
            nullable=True,
        ))


def downgrade() -> None:
    with op.batch_alter_table('exit_thresholds', schema=None) as b:
        b.drop_column('entry_threshold_decision_confidence')
