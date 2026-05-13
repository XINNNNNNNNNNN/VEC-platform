"""phase H+1 split housing into building and ownership

Revision ID: 831c8b336b5e
Revises: fc31c6ae50ac
Create Date: 2026-05-13 12:08:57.169007

Phase H rolled the 2-way ownership_type into a single 5-way
housing_type. That collapsed onto a single radio missed renting of
townhouse / house / other entirely — 3-5 % of Swedish households
(roughly 150k people) had no honest option and had to pick "Other".

Phase H+1 splits housing back into two independent dimensions
mirroring how the E.ON Sweden survey actually asks:

  building_type ∈ {apartment, townhouse, house, other}   (4-way Q)
  is_owner      ∈ {True, False}                          (1 Y/N Q)

→ 4 × 2 = 8 real combinations, full coverage. Effekttariff still
applies only to housings with their own meter, but now correctly
gated on both conditions:

  is_owner AND building_type ∈ config.EFFEKTTARIFF_BUILDINGS

The Phase H housing_type column stays in place for one cycle as
rollback safety. mock.calculate_bill accepts the legacy kwarg and
translates: apt_renting -> (apartment, False); apt_condo ->
(apartment, True); townhouse_owner -> (townhouse, True);
villa_owner -> (house, True); other -> (other, True).

NULL legacy behaviour change vs Phase H: rows with no building_type
+ no is_owner default to the house archetype but NO effekttariff
(is_owner=None is not True). Phase H assumed those rows were owner
and added effekt; Phase H+1 errs the safer way — those 172 rows are
not pilot-grade and are not used for analysis, but the more honest
default is "we don't know whether they own".
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '831c8b336b5e'
down_revision: Union[str, Sequence[str], None] = 'fc31c6ae50ac'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('user_inputs') as batch_op:
        batch_op.add_column(sa.Column('building_type', sa.String(32), nullable=True))
        batch_op.add_column(sa.Column('is_owner', sa.Boolean, nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('user_inputs') as batch_op:
        batch_op.drop_column('is_owner')
        batch_op.drop_column('building_type')
