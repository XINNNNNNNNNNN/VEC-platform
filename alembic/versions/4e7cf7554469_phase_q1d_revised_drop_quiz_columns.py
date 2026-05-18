"""phase_q1d_revised_drop_quiz_columns

Revision ID: 4e7cf7554469
Revises: eb2ec30ae77d
Create Date: 2026-05-18 17:55:20.071740

Phase Q-1d (revised): cancel the planned S1-Q6 objective-knowledge quiz
and drop the 6 user_inputs columns added by Phase Q-1a in preparation.

Decision rationale
------------------
Phase Q-1a (commit 6654519) added quiz_q1..5 + quiz_score to user_inputs
on the assumption that v3 questionnaire S1-Q6 (5-item objective
knowledge quiz) would be added to the platform via a dedicated
/dash/quiz page.

After design review the research team has decided that the quiz creates
significant "exam anxiety" risk for pilot participants without
proportionate research benefit. Expertise will instead be defined from
two existing self-report measures already collected:

    composite_expertise_z =
        z(sessions.vec_familiarity ordinal 1..5)
        + z(user_inputs.occupation binary 0/1)

Both signals are already being collected (vec_familiarity at Welcome,
occupation at Step 1) and require no new UI work. The quiz columns
have never received a real write — no /dash/quiz page was built — so
data loss is not a concern.

Schema change
-------------
Drop 6 nullable Integer columns from user_inputs:
    quiz_q1, quiz_q2, quiz_q3, quiz_q4, quiz_q5, quiz_score

batch_alter_table is required because SQLite cannot ALTER TABLE
DROP COLUMN natively. env.py sets render_as_batch=True globally; the
wrapper is a no-op on PostgreSQL.

Downgrade re-adds the 6 columns as nullable Integer with NULL default,
matching the original Q-1a definition.

Questionnaire numbering
-----------------------
Side effect (handled in v3 documentation, not in code):
- The original S1-Q6 (quiz) is cancelled.
- The Sloot 9-item motivation scale, previously numbered S1-Q7, is
  renumbered S1-Q6.
- Future Phase Q-3f (Sloot implementation) will use the S1-Q6 label.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4e7cf7554469'
down_revision: Union[str, Sequence[str], None] = 'eb2ec30ae77d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('user_inputs', schema=None) as b:
        b.drop_column('quiz_score')
        b.drop_column('quiz_q5')
        b.drop_column('quiz_q4')
        b.drop_column('quiz_q3')
        b.drop_column('quiz_q2')
        b.drop_column('quiz_q1')


def downgrade() -> None:
    with op.batch_alter_table('user_inputs', schema=None) as b:
        b.add_column(sa.Column('quiz_q1', sa.Integer(), nullable=True))
        b.add_column(sa.Column('quiz_q2', sa.Integer(), nullable=True))
        b.add_column(sa.Column('quiz_q3', sa.Integer(), nullable=True))
        b.add_column(sa.Column('quiz_q4', sa.Integer(), nullable=True))
        b.add_column(sa.Column('quiz_q5', sa.Integer(), nullable=True))
        b.add_column(sa.Column('quiz_score', sa.Integer(), nullable=True))
