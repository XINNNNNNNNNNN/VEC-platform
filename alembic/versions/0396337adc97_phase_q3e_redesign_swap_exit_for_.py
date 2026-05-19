"""phase_q3e_redesign_swap_exit_for_constructive_rank

Revision ID: 0396337adc97
Revises: 382e5f070b35
Create Date: 2026-05-19 15:24:00.079518

Phase Q-3e-redesign: the Hirschman 4-reaction rank in S7-Q11
restructured from {exit / voice / loyalty / passive} to
{voice / loyalty / passive / constructive}.

Rationale: the old 'exit' rank conflicted with S7-Q9's red-line
exit threshold — a user who answered Q9 had already declared their
exit condition, so Q11's exit option was redundant. The new
'constructive' rank captures "stay actively engaged for grid /
environment benefit even when savings disappoint" — a behavior
pattern previously uncaptured. The constructive rank is a wait-
period behavior measurement, conceptually distinct from S1-Q6
Sloot trait measurement (Sloot asks 'how much do you usually
value environment'; this asks 'under stress, would you still
actively engage'). No overlap.

DB net change is zero column count; the column-level swap
preserves the 4-rank permutation invariant downstream callbacks
already enforce.

Pre-redesign test data note: a single test row in exit_thresholds
loses its hirschman_exit_rank value during this migration; the new
hirschman_constructive_rank column starts NULL. This is acceptable
because the column semantic is fundamentally changing.

batch_alter_table required for SQLite — env.py sets
render_as_batch=True globally; wrapper is a no-op on PostgreSQL.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0396337adc97'
down_revision: Union[str, Sequence[str], None] = '382e5f070b35'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('exit_thresholds', schema=None) as b:
        b.drop_column('hirschman_exit_rank')
        b.add_column(sa.Column(
            'hirschman_constructive_rank', sa.Integer(), nullable=True
        ))


def downgrade() -> None:
    with op.batch_alter_table('exit_thresholds', schema=None) as b:
        b.drop_column('hirschman_constructive_rank')
        b.add_column(sa.Column(
            'hirschman_exit_rank', sa.Integer(), nullable=True
        ))
