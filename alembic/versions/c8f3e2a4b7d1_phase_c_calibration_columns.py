"""phase_c_calibration_columns

Revision ID: c8f3e2a4b7d1
Revises: b1c5e4a2f0d3
Create Date: 2026-05-07 18:00:00.000000

Phase C: ``user_inputs`` gains five calibration columns.

The two existing columns ``pv_kwp`` and ``bess_kwh`` are reused as the
canonical user-edited capacity values (rather than introducing parallel
``pv_kw`` / ``bess_kwh_v2`` columns and leaving the originals dead).
``pv_kwp`` is already load-bearing — engine/mock.py:_get_pv_generation
reads it as ``peak_kw = pv_kwp * 0.6`` — so reusing it means Phase C
user calibrations of PV capacity already affect bills via the existing
fix-18 recalculate path, even though Phase D is the planned bill
wire-up. ``bess_kwh`` was previously a dead column (written only as a
default by step1); reusing it for user-edited values likewise costs
nothing.

New columns:
  ev_kwh:
      EV battery capacity, kWh. NULL on existing rows; new rows get
      whatever the calibration UI persists (or NULL when the user
      sticks with the default 60 kWh — see ev_calibrated below).
  load_scale_factor:
      Persisted ±5% baseline scaling, defaults to 1.0. The fix-18
      recalculate path still reads scale_factor straight off the JS
      `state.scaleFactor`; Phase D will switch to reading this column
      as the source of truth.
  pv_calibrated / bess_calibrated / ev_calibrated:
      Research signal — True when the participant actively unchecked
      "I don't know" and confirmed a value, False (default) when they
      accepted the platform default. Pilot analysis can split users by
      whether they internalised their own situation vs. defaulted, an
      important covariate for the willingness measurements taken later
      in the journey.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c8f3e2a4b7d1'
down_revision: Union[str, Sequence[str], None] = 'b1c5e4a2f0d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('user_inputs', schema=None) as b:
        b.add_column(sa.Column('ev_kwh', sa.Float(), nullable=True))
        b.add_column(sa.Column(
            'load_scale_factor',
            sa.Float(),
            nullable=True,
            server_default='1.0',
        ))
        b.add_column(sa.Column(
            'pv_calibrated',
            sa.Boolean(),
            nullable=False,
            server_default='0',
        ))
        b.add_column(sa.Column(
            'bess_calibrated',
            sa.Boolean(),
            nullable=False,
            server_default='0',
        ))
        b.add_column(sa.Column(
            'ev_calibrated',
            sa.Boolean(),
            nullable=False,
            server_default='0',
        ))


def downgrade() -> None:
    with op.batch_alter_table('user_inputs', schema=None) as b:
        b.drop_column('ev_calibrated')
        b.drop_column('bess_calibrated')
        b.drop_column('pv_calibrated')
        b.drop_column('load_scale_factor')
        b.drop_column('ev_kwh')
