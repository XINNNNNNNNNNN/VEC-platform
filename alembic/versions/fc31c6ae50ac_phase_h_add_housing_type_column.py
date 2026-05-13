"""phase H add housing_type column

Revision ID: fc31c6ae50ac
Revises: 904b52105716
Create Date: 2026-05-13 11:45:02.787847

Phase H replaces the 2-way ownership_type (tenant / owner) with a
5-way housing_type matching the E.ON Sweden consumer-survey
categories, with apartments split between renting and BRF condo
owners so the SP experiment can distinguish the two groups (only
condo owners are eligible for VEC participation the way villa
owners are, but neither apartment sub-group pays effekttariff —
that fee applies only to housings with their own meter).

Categories:
  apt_renting      apartment, renting
  apt_condo        apartment, BRF condo owner
  townhouse_owner  townhouse owner
  villa_owner      house / villa owner
  other            fritidshus / annat

The new column is nullable. Existing 172 dogfood sessions stay NULL;
the engine falls back to the house archetype + effekttariff so the
pre-Phase-H "owner" default behaviour is preserved for them — those
rows are not pilot-grade and not used for analysis.

ownership_type is intentionally NOT dropped — kept as rollback
safety. mock.calculate_bill still accepts it as a fallback kwarg
and translates tenant -> apt_renting, owner -> villa_owner.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fc31c6ae50ac'
down_revision: Union[str, Sequence[str], None] = '904b52105716'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('user_inputs') as batch_op:
        batch_op.add_column(sa.Column('housing_type', sa.String(32), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('user_inputs') as batch_op:
        batch_op.drop_column('housing_type')
