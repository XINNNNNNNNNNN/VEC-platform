"""phase_q1a_quiz_columns

Revision ID: e0f62eb775ef
Revises: 7c4d9f1e2a8b
Create Date: 2026-05-18 16:01:36.008478

Phase Q-1a: ``user_inputs`` gains six quiz columns for VEC questionnaire
v3 S1-Q6 (5-item objective knowledge quiz).

Columns added
-------------
quiz_q1 .. quiz_q5  Integer nullable
    Per-item correctness. 1 = correct answer selected, 0 = incorrect
    or "don't know" selected, NULL = quiz not yet taken (transient
    state between Welcome submit and the not-yet-built /dash/quiz
    page).

quiz_score  Integer nullable
    Sum of quiz_q1..q5 (0..5). Computed at quiz submit in Phase Q-1d.
    Stored rather than derived to make composite_expertise_z post-hoc
    calculation cheap and to avoid recomputation in analysis.

Why nullable
------------
Existing rows (incl. the Welcome -> Step1 transient rows that Phase
O-fix-11 introduced) predate the quiz UI. NULL on these rows is the
meaningful "quiz not taken" state. Once /dash/quiz ships in Phase
Q-1d, all sessions that complete the flow will write non-NULL values;
analysis pipelines filter NULL when computing composite_expertise_z.

Why these columns and not a separate quiz_responses table
---------------------------------------------------------
Each session takes the quiz once and we store the resolved
correct/incorrect bit per item, not the raw choice. A 1:1 join with
user_inputs is the only access pattern, so denormalising into
user_inputs avoids an extra JOIN on every expertise analysis query.

The 9-item Sloot motivation scale (Phase Q-3f) WILL get its own
table (motivation_scale) because it's a 1:N relationship and the
order of items is randomised per session. Different access pattern,
different storage shape.

batch_alter_table convention
----------------------------
SQLite natively supports add_column without table rewrite, so the
batch wrapper is not strictly required here. We use it anyway for
two reasons:
1. env.py sets render_as_batch=True globally; every existing
   migration in this repo uses op.batch_alter_table for column ops.
   Matching style keeps diffs uniform.
2. If the project ever migrates the analyst DB to PostgreSQL, the
   batch wrapper becomes a no-op there — same migration code works
   on both backends.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e0f62eb775ef'
down_revision: Union[str, Sequence[str], None] = '7c4d9f1e2a8b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('user_inputs', schema=None) as b:
        b.add_column(sa.Column('quiz_q1', sa.Integer(), nullable=True))
        b.add_column(sa.Column('quiz_q2', sa.Integer(), nullable=True))
        b.add_column(sa.Column('quiz_q3', sa.Integer(), nullable=True))
        b.add_column(sa.Column('quiz_q4', sa.Integer(), nullable=True))
        b.add_column(sa.Column('quiz_q5', sa.Integer(), nullable=True))
        b.add_column(sa.Column('quiz_score', sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('user_inputs', schema=None) as b:
        b.drop_column('quiz_score')
        b.drop_column('quiz_q5')
        b.drop_column('quiz_q4')
        b.drop_column('quiz_q3')
        b.drop_column('quiz_q2')
        b.drop_column('quiz_q1')
