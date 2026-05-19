"""phase_q3_followup_s4q1_reservation_price_redesign

Revision ID: fd911a36ae33
Revises: 0396337adc97
Create Date: 2026-05-19 16:27:00.887320

Phase Q-3-followup: S4-Q1 redesigned from "would you shift more
devices if savings 2x?" (single enum 'yes'/'no'/'maybe') into a
conditional per-device reservation-price elicitation. The new
column stores a JSON list of device names the user would
reconsider shifting if savings were higher.

  drop: survey_responses.step4_q1_counterfactual (String enum)
  add:  survey_responses.step4_q1_reconsider_devices (Text JSON)

Conceptual rationale: the new column measures EXTENSIVE-MARGIN
reservation elasticity per device, which directly supports policy
targeting (e.g., "heat pumps have 0% reconsider rate but EVs have
80%" -> Ei should target EV smart-charging incentives, not heat
pump shifting mandates).

Pre-redesign rows note: any existing rows lose their
step4_q1_counterfactual value during this migration. The new
step4_q1_reconsider_devices column starts NULL. Acceptable
because (a) pre-redesign was a single dogfood test row, (b) the
semantic is fundamentally changing.

batch_alter_table required for SQLite — env.py sets
render_as_batch=True globally; no-op on PostgreSQL.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fd911a36ae33'
down_revision: Union[str, Sequence[str], None] = '0396337adc97'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('survey_responses', schema=None) as b:
        b.drop_column('step4_q1_counterfactual')
        b.add_column(sa.Column(
            'step4_q1_reconsider_devices', sa.Text(), nullable=True
        ))


def downgrade() -> None:
    with op.batch_alter_table('survey_responses', schema=None) as b:
        b.drop_column('step4_q1_reconsider_devices')
        b.add_column(sa.Column(
            'step4_q1_counterfactual', sa.String(16), nullable=True
        ))
