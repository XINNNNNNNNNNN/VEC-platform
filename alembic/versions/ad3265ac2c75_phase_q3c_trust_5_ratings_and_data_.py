"""phase_q3c_trust_5_ratings_and_data_control_multiselect

Revision ID: ad3265ac2c75
Revises: 614f8c045cb6
Create Date: 2026-05-19 11:59:49.203465

Phase Q-3c: replace single-select trust + single-Likert transparency
with v3's 5-rating trust battery + multi-select data control.

Drops:
  survey_responses.q5_trust_source    (VARCHAR; single-select)
  survey_responses.q7_transparency_pref (VARCHAR; single-Likert)

Adds:
  survey_responses.trust_municipality INT nullable  (1=No trust .. 5=Complete trust)
  survey_responses.trust_coop         INT nullable
  survey_responses.trust_utility      INT nullable
  survey_responses.trust_private      INT nullable
  survey_responses.trust_grid         INT nullable
  survey_responses.data_control_prefs TEXT nullable  (JSON list of selected options)

Pre-Q-3c data in the dropped columns is intentionally discarded — the
new schema is semantically incompatible with the old (a single
'utility' answer cannot be split into 5 trust ratings; a single
'detailed' transparency answer cannot be mapped to the 6 data-control
options). Dogfood rows that pre-date Q-3c have NULL for the new
columns and the dropped columns are gone.

batch_alter_table is required for SQLite DROP COLUMN + ADD COLUMN —
env.py sets render_as_batch=True globally; wrapper is a no-op on PostgreSQL.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ad3265ac2c75'
down_revision: Union[str, Sequence[str], None] = '614f8c045cb6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('survey_responses', schema=None) as b:
        # Drop the two superseded columns.
        b.drop_column('q5_trust_source')
        b.drop_column('q7_transparency_pref')

        # Add the 5-rating trust battery.
        b.add_column(sa.Column('trust_municipality', sa.Integer(), nullable=True))
        b.add_column(sa.Column('trust_coop', sa.Integer(), nullable=True))
        b.add_column(sa.Column('trust_utility', sa.Integer(), nullable=True))
        b.add_column(sa.Column('trust_private', sa.Integer(), nullable=True))
        b.add_column(sa.Column('trust_grid', sa.Integer(), nullable=True))

        # Add the data-control multi-select (JSON list serialized to Text).
        b.add_column(sa.Column('data_control_prefs', sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('survey_responses', schema=None) as b:
        b.drop_column('data_control_prefs')
        b.drop_column('trust_grid')
        b.drop_column('trust_private')
        b.drop_column('trust_utility')
        b.drop_column('trust_coop')
        b.drop_column('trust_municipality')

        # Re-create the old columns empty (data NOT restored — Q-3c is
        # a destructive forward migration; downgrade only recovers
        # schema shape).
        b.add_column(sa.Column('q5_trust_source', sa.String(length=32), nullable=True))
        b.add_column(sa.Column('q7_transparency_pref', sa.String(length=16), nullable=True))
