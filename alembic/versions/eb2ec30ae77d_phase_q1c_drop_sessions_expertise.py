"""phase_q1c_drop_sessions_expertise

Revision ID: eb2ec30ae77d
Revises: 2ab1adab2450
Create Date: 2026-05-18 16:30:19.791886

Phase Q-1c: drop ``sessions.expertise`` column.

VEC questionnaire v3 abandons the expertise self-label as a UI-time
gating variable. Phase Q-1b removed the Step 7 expert block that
previously consumed this signal; this migration removes the underlying
column entirely. RQ7 (expert vs lay) analysis is now fully post-hoc,
computed as composite_expertise_z = z(occupation self-report) +
z(quiz_score) — no persisted "expert" flag needed.

The Step 1 occupation question itself is kept (the column
``user_inputs.occupation`` and its Yes/No values are preserved); the
question is now shown to all participants regardless of vec_familiarity.
What goes away is the derived ``sessions.expertise`` column written by
submit_step1's old branching logic.

Schema note: sessions.expertise was declared NOT NULL with
server_default='general'. The downgrade re-adds it with the same
nullability and default, so a downgrade on a populated DB will
backfill 'general' for every existing row via the batch table rewrite.
This is acceptable because:
1. The "real" expertise value was already lost when the column was
   dropped; we can't recover it.
2. Downgrade is only used in dev rollback scenarios where the DB is
   typically wiped anyway.

batch_alter_table is required: SQLite cannot ALTER TABLE DROP COLUMN
natively; the wrapper rebuilds the table. env.py sets
render_as_batch=True globally; the wrapper is a no-op on PostgreSQL.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'eb2ec30ae77d'
down_revision: Union[str, Sequence[str], None] = '2ab1adab2450'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('sessions', schema=None) as b:
        b.drop_column('expertise')


def downgrade() -> None:
    with op.batch_alter_table('sessions', schema=None) as b:
        b.add_column(sa.Column(
            'expertise',
            sa.String(length=16),
            server_default='general',
            nullable=False,
        ))
