"""v3_drop_fairness_likert

Revision ID: 556a3c5004ba
Revises: ca05978e8fdb
Create Date: 2026-05-06 16:10:57.650648

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '556a3c5004ba'
down_revision: Union[str, Sequence[str], None] = 'ca05978e8fdb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Phase 3.X-fix-8: drop survey_responses.fairness_likert.

    fix-7 added this column for E.ON Q11 alignment (1..7 Likert about
    preferential treatment) on Step 7. After review the question was
    judged to overlap conceptually with Phase 3.9's q6_fairness_pref
    (also a "fairness" framing, just on a different axis — savings
    distribution preference) and to lack a clean rationale for living on
    Step 7 specifically. Decision: drop, keep q6_fairness_pref as the
    canonical fairness measure.

    survey_responses.q2_reasons is intentionally NOT dropped here — it
    stays as an escape hatch for the legacy /api/survey endpoint, even
    though Step 8 layout no longer writes to it (fix-8 merges Q2 into
    drivers_top3).
    """
    with op.batch_alter_table('survey_responses', schema=None) as b:
        b.drop_column('fairness_likert')


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('survey_responses', schema=None) as b:
        b.add_column(sa.Column('fairness_likert', sa.Integer(), nullable=True))
