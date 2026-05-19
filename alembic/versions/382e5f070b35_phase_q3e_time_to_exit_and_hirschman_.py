"""phase_q3e_time_to_exit_and_hirschman_rank

Revision ID: 382e5f070b35
Revises: ad3265ac2c75
Create Date: 2026-05-19 12:26:06.986577

Phase Q-3e: add temporal + Hirschman behavioral-reaction columns
to exit_thresholds.

S7-Q10 Time-to-Exit:
  exit_lag_months — INT nullable. The participant's stated horizon
    (in months) before leaving a VEC whose savings stay at 50%
    of promised. Values 1/3/6/12/-1 where -1 encodes "Never leave"
    (right-censored from the Cox-hazard-model perspective).
    NULL means the question wasn't answered.

S7-Q11 Hirschman Rank (Hirschman 1970 exit/voice/loyalty + passive):
  hirschman_exit_rank     — INT nullable, 1=most likely .. 4=least likely
  hirschman_voice_rank    — INT nullable
  hirschman_loyalty_rank  — INT nullable
  hirschman_passive_rank  — INT nullable
  Submitted as a permutation of {1,2,3,4} per session. NULLs only
  appear on pre-Q-3e rows or partial submissions; analytics filter
  by session timestamp + IS NOT NULL.

batch_alter_table required for SQLite — env.py sets render_as_batch=True
globally; wrapper is a no-op on PostgreSQL.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '382e5f070b35'
down_revision: Union[str, Sequence[str], None] = 'ad3265ac2c75'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('exit_thresholds', schema=None) as b:
        b.add_column(sa.Column('exit_lag_months', sa.Integer(), nullable=True))
        b.add_column(sa.Column('hirschman_exit_rank', sa.Integer(), nullable=True))
        b.add_column(sa.Column('hirschman_voice_rank', sa.Integer(), nullable=True))
        b.add_column(sa.Column('hirschman_loyalty_rank', sa.Integer(), nullable=True))
        b.add_column(sa.Column('hirschman_passive_rank', sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('exit_thresholds', schema=None) as b:
        b.drop_column('hirschman_passive_rank')
        b.drop_column('hirschman_loyalty_rank')
        b.drop_column('hirschman_voice_rank')
        b.drop_column('hirschman_exit_rank')
        b.drop_column('exit_lag_months')
