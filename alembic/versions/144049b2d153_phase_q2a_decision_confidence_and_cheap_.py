"""phase_q2a_decision_confidence_and_cheap_talk

Revision ID: 144049b2d153
Revises: 4e7cf7554469
Create Date: 2026-05-18 22:35:21.034387

Phase Q-2a: add two columns for the Welcome-page v3 additions.

1. user_inputs.entry_threshold_decision_confidence
   Integer, nullable. Holds the S0-Q3 Decision Confidence 1-5 Likert
   captured immediately after the S0-Q2 entry threshold slider.
   Pairs with S7-Q8 (final decision confidence) for the
   pre/post-information confidence change analysis.
   Nullable because:
   - existing rows (pre-Q-2a sessions) have no answer
   - the column is also nullable on transient rows that haven't reached
     the Welcome state_2 yet

2. sessions.cheap_talk_acknowledged
   Boolean, NOT NULL, server_default=false. Holds the S0-NOTE
   acknowledgement: True after the participant clicks
   "I understand — continue" on the cheap-talk preface (state_3).
   NOT NULL because every active session must reach state_3 to
   navigate to /dash/step1; defaults to False at session creation
   and is flipped to True by the state_3 submit handler.
   Server default ensures existing rows (pre-Q-2a) get False
   without raising integrity errors during the batch table rewrite.

batch_alter_table is required because SQLite cannot ALTER TABLE ADD
COLUMN with constraints natively for certain change patterns. env.py
sets render_as_batch=True globally; the wrapper is a no-op on PostgreSQL.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '144049b2d153'
down_revision: Union[str, Sequence[str], None] = '4e7cf7554469'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('user_inputs', schema=None) as b:
        b.add_column(sa.Column(
            'entry_threshold_decision_confidence',
            sa.Integer(),
            nullable=True,
        ))

    with op.batch_alter_table('sessions', schema=None) as b:
        b.add_column(sa.Column(
            'cheap_talk_acknowledged',
            sa.Boolean(),
            server_default=sa.text('0'),
            nullable=False,
        ))


def downgrade() -> None:
    with op.batch_alter_table('sessions', schema=None) as b:
        b.drop_column('cheap_talk_acknowledged')

    with op.batch_alter_table('user_inputs', schema=None) as b:
        b.drop_column('entry_threshold_decision_confidence')
