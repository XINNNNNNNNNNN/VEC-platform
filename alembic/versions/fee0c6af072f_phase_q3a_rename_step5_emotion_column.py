"""phase_q3a_rename_step5_emotion_column

Revision ID: fee0c6af072f
Revises: 83caa8b7347b
Create Date: 2026-05-19 11:32:04.442437

Phase Q-3a: rename survey_responses.step5_expectation_vs_reality
→ survey_responses.step5_disconfirmation_emotion.

The semantic of the column changes from cognitive comparison
('how does actual compare to expected?' — much-less .. much-more)
to emotional reaction ('how do you feel about this result?' —
very-disappointed .. very-pleased) per Oliver (1980) expectation-
disconfirmation theory. The Integer 1..5 range stays the same,
but the anchors invert in some semantic sense (a 1-much-less-than-
expected respondent might map onto a 1-very-disappointed OR a
5-very-pleased depending on whether they wanted high or low
savings). Pre-Q-3a dogfood data therefore SHOULD NOT be analysed
on the same scale as post-Q-3a pilot data — analytics filter rows
by the question version inferred from session timestamps relative
to the migration date.

batch_alter_table.alter_column(new_column_name=...) under SQLite
performs a safe table-rebuild rename that preserves all row values;
under PostgreSQL it issues a native ALTER TABLE RENAME COLUMN.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fee0c6af072f'
down_revision: Union[str, Sequence[str], None] = '83caa8b7347b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('survey_responses', schema=None) as b:
        b.alter_column(
            'step5_expectation_vs_reality',
            new_column_name='step5_disconfirmation_emotion',
        )


def downgrade() -> None:
    with op.batch_alter_table('survey_responses', schema=None) as b:
        b.alter_column(
            'step5_disconfirmation_emotion',
            new_column_name='step5_expectation_vs_reality',
        )
