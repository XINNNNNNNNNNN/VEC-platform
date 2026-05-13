"""Phase O building type 4 way E.ON aligned

Revision ID: fea15d1b9cf2
Revises: 904b52105716
Create Date: 2026-05-13 12:39:24.173155

Phase O simplifies the Step 1 housing question. The Swedish 2026
effekttariff mandate was cancelled 2026-03-13 and Ellevio /
Mälarenergi / Göteborg Energi have all withdrawn or paused their
roll-outs; E.ON's winter-only model from 2026-09-01 has no public
formula yet. With effekttariff removed from the mock engine, the
2-way ownership_type (tenant / owner) loses its only billing-
differentiating role and is replaced by a 4-way ``building_type``
that mirrors the E.ON Sweden consumer survey 2025 categories:

  apartment   Lägenhet
  townhouse   Radhus
  house       Villa / hus
  other       Fritidshus / annat

Engine archetype map is now 2-class: apartment vs house. The
townhouse / house / other building types all share the house
archetype calibration (Phase N-fix-4).

Schema changes:
  - Add user_inputs.building_type VARCHAR(32) nullable.
  - Relax user_inputs.ownership_type from NOT NULL to nullable.
    The column is retained as deprecated for one-cycle rollback
    safety; Phase O code paths neither read nor write it. SQLite
    cannot ALTER COLUMN nullability in place, so this uses
    op.batch_alter_table() which recreates the table.

Pre-pilot dogfood DB (172 sessions) was wiped 2026-05-13 to ensure
clean pilot data, so there are no rows to migrate.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fea15d1b9cf2'
down_revision: Union[str, Sequence[str], None] = '904b52105716'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('user_inputs') as batch_op:
        batch_op.add_column(
            sa.Column('building_type', sa.String(32), nullable=True)
        )
        batch_op.alter_column(
            'ownership_type',
            existing_type=sa.String(16),
            nullable=True,
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('user_inputs') as batch_op:
        batch_op.alter_column(
            'ownership_type',
            existing_type=sa.String(16),
            nullable=False,
        )
        batch_op.drop_column('building_type')
