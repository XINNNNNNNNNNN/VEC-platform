"""phase_q1b_drop_expert_columns

Revision ID: 2ab1adab2450
Revises: e0f62eb775ef
Create Date: 2026-05-18 16:10:25.960106

Phase Q-1b: drop the three expert-only columns from ``survey_responses``.

VEC questionnaire v3 removes the Step 7 "expert block" — three questions
(``expert_q1_realism`` 5-Likert, ``expert_q2_barrier`` single-choice,
``expert_q3_comment`` 200-char textarea) that were previously rendered
only to participants with vec_familiarity ∈ {very_familiar,
have_participated}. v3's RQ7 (expert vs lay comparison) instead uses
ALL existing items post-hoc, computing composite_expertise_z =
z(occupation self-report) + z(quiz_score) — no separate expert
questions needed.

The columns dropped here have been collecting NULLs for the
non-expert majority anyway (172 internal-test sessions had vast
majority NULL on these). Phase O dogfood DB was wiped 2026-05-13,
so the production DB has zero rows; no data loss risk.

The matching UI changes (delete _expert_block, delete _EXPERT_Q*_OPTIONS,
strip eq1/eq2/eq3 from submit_survey callback) ship in the same
phase as separate commits.

batch_alter_table is required because SQLite cannot ALTER TABLE DROP
COLUMN natively — it rebuilds the table. env.py sets
render_as_batch=True globally so this works on both SQLite (dev) and
PostgreSQL (prod).

Downgrade
---------
Re-adds the three columns with the original types (Integer,
String(32), String(256)), all nullable. Data does NOT come back — drop
is destructive. Acceptable because the only environment where these
ever held real values was the pre-Q-1b dogfood DB which was wiped.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2ab1adab2450'
down_revision: Union[str, Sequence[str], None] = 'e0f62eb775ef'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('survey_responses', schema=None) as b:
        b.drop_column('expert_q3_comment')
        b.drop_column('expert_q2_barrier')
        b.drop_column('expert_q1_realism')


def downgrade() -> None:
    with op.batch_alter_table('survey_responses', schema=None) as b:
        b.add_column(sa.Column('expert_q1_realism', sa.Integer(), nullable=True))
        b.add_column(sa.Column('expert_q2_barrier', sa.String(length=32), nullable=True))
        b.add_column(sa.Column('expert_q3_comment', sa.String(length=256), nullable=True))
