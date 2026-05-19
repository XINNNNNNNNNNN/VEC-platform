"""phase_q3b_add_shift_satisfaction

Revision ID: 614f8c045cb6
Revises: fee0c6af072f
Create Date: 2026-05-19 11:50:03.725610

Phase Q-3b: add survey_responses.shift_satisfaction Integer 1..5.

Captures the S5-Q2 effort×reward satisfaction Likert added to the
Step 5 compare page. Replaces the v2 "minimum SEK that would make
shifting worth" question (deleted) which had explicit anchor bias.
v3 reframes this as direct satisfaction with the SEK-extra amount
the platform actually computed.

Nullable because pre-Q-3b sessions don't have an answer; analytics
filters on session timestamp (pre/post-migration) to scope rows.

batch_alter_table is required for SQLite — env.py sets
render_as_batch=True globally; wrapper is a no-op on PostgreSQL.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '614f8c045cb6'
down_revision: Union[str, Sequence[str], None] = 'fee0c6af072f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('survey_responses', schema=None) as b:
        b.add_column(sa.Column(
            'shift_satisfaction',
            sa.Integer(),
            nullable=True,
        ))


def downgrade() -> None:
    with op.batch_alter_table('survey_responses', schema=None) as b:
        b.drop_column('shift_satisfaction')
