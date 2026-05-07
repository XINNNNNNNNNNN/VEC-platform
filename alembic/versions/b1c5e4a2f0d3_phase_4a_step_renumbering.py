"""phase_4a_step_renumbering

Revision ID: b1c5e4a2f0d3
Revises: f257d7828541
Create Date: 2026-05-07 12:00:00.000000

Phase 4-A renumbered the user-facing flow from 8 steps to 7 steps by
removing the original Step 2 (mock baseline display). Survey-response
columns named after the old step positions are renamed to match the
new flow:

  step4_q1_shift_intent       → step3_q1_shift_intent
  step4_q2_control_pref       → step3_q2_control_pref
  step5_q1_counterfactual     → step4_q1_counterfactual
  step5_q2_effort             → step4_q2_effort
  step6_expectation_vs_reality → step5_expectation_vs_reality
  step7_broader_impacts_shift → step6_broader_impacts_shift

Per Phase 4-A decision 2a, ``device_shifts.step``,
``daily_profiles.step``, ``bill_breakdowns.step`` data values are NOT
changed — they preserve their historical semantics (2=baseline,
3=customize, 5=respond) regardless of UI flow renumbering. The wire
field names in api/device_shift.py also keep the legacy step5_*
prefix because they're keyed by the data step value (still 5); the
mapping to the renamed DB column happens server-side.

``sessions.current_step`` historical values likewise are NOT touched —
existing rows remain at their pre-Phase-4-A values; new sessions write
the new flow positions (0..7 mid-flow, 8 = completed).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b1c5e4a2f0d3'
down_revision: Union[str, Sequence[str], None] = 'f257d7828541'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Rename the six survey_responses columns whose names embed the
    old flow positions. SQLite needs batch_alter_table for column
    renames (render_as_batch=True is set in env.py)."""
    with op.batch_alter_table('survey_responses', schema=None) as b:
        b.alter_column(
            'step4_q1_shift_intent',
            new_column_name='step3_q1_shift_intent',
            existing_type=sa.String(length=16),
            existing_nullable=True,
        )
        b.alter_column(
            'step4_q2_control_pref',
            new_column_name='step3_q2_control_pref',
            existing_type=sa.String(length=16),
            existing_nullable=True,
        )
        b.alter_column(
            'step5_q1_counterfactual',
            new_column_name='step4_q1_counterfactual',
            existing_type=sa.String(length=16),
            existing_nullable=True,
        )
        b.alter_column(
            'step5_q2_effort',
            new_column_name='step4_q2_effort',
            existing_type=sa.String(length=16),
            existing_nullable=True,
        )
        b.alter_column(
            'step6_expectation_vs_reality',
            new_column_name='step5_expectation_vs_reality',
            existing_type=sa.Integer(),
            existing_nullable=True,
        )
        b.alter_column(
            'step7_broader_impacts_shift',
            new_column_name='step6_broader_impacts_shift',
            existing_type=sa.Integer(),
            existing_nullable=True,
        )


def downgrade() -> None:
    """Reverse the rename. Existing data is preserved by alter_column."""
    with op.batch_alter_table('survey_responses', schema=None) as b:
        b.alter_column(
            'step3_q1_shift_intent',
            new_column_name='step4_q1_shift_intent',
            existing_type=sa.String(length=16),
            existing_nullable=True,
        )
        b.alter_column(
            'step3_q2_control_pref',
            new_column_name='step4_q2_control_pref',
            existing_type=sa.String(length=16),
            existing_nullable=True,
        )
        b.alter_column(
            'step4_q1_counterfactual',
            new_column_name='step5_q1_counterfactual',
            existing_type=sa.String(length=16),
            existing_nullable=True,
        )
        b.alter_column(
            'step4_q2_effort',
            new_column_name='step5_q2_effort',
            existing_type=sa.String(length=16),
            existing_nullable=True,
        )
        b.alter_column(
            'step5_expectation_vs_reality',
            new_column_name='step6_expectation_vs_reality',
            existing_type=sa.Integer(),
            existing_nullable=True,
        )
        b.alter_column(
            'step6_broader_impacts_shift',
            new_column_name='step7_broader_impacts_shift',
            existing_type=sa.Integer(),
            existing_nullable=True,
        )
