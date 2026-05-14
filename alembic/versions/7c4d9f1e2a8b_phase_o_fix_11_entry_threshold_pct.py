"""phase_o_fix_11_entry_threshold_pct

Revision ID: 7c4d9f1e2a8b
Revises: fea15d1b9cf2
Create Date: 2026-05-14 14:30:00.000000

Phase O-fix-11: ``user_inputs`` gains ``entry_threshold_pct`` AND
relaxes ``area_m2`` / ``people`` to nullable.

New column — entry_threshold_pct
--------------------------------
The Welcome page splits into two states (consent / onboarding). The
new threshold question — "how much saving would you need before
considering joining such a community?" — has a different semantic
from the existing ``prior_expectations.pct`` round=1 row, which is
the participant's *expected* savings. Keeping the two semantically-
distinct values in separate columns lets Layer 1 analysis compare
expectation vs. threshold cleanly without overloading
prior_expectations.pct or losing the round1-vs-round2 expectation-gap
signal (round=2 stays "expected savings"). Range 0.0 — 50.0, NULL on
pre-existing rows.

Nullability relaxation — area_m2, people
----------------------------------------
Welcome state-2 submit inserts a fresh ``user_inputs`` row keyed on
session_id so it can stash ``entry_threshold_pct`` before the
participant reaches Step 1. The previous schema declared
``area_m2`` / ``people`` NOT NULL — Step 1 always wrote them when
the row was created — but the Welcome→Step 1 transient row would
trigger an IntegrityError on INSERT. Relaxing both columns to
nullable lets the upsert pattern work in either direction; Step 1
still always writes a non-NULL value, so analytics-side completeness
is unchanged.

batch_alter_table is required for SQLite (it rewrites the table to
change NULL constraints; raw ALTER COLUMN is not supported).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7c4d9f1e2a8b'
down_revision: Union[str, Sequence[str], None] = 'fea15d1b9cf2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('user_inputs', schema=None) as b:
        b.add_column(sa.Column('entry_threshold_pct', sa.Float(), nullable=True))
        b.alter_column('area_m2', existing_type=sa.Float(), nullable=True)
        b.alter_column('people', existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    with op.batch_alter_table('user_inputs', schema=None) as b:
        # Downgrade can only succeed if no rows have NULL area_m2 or
        # people — the only way to re-introduce the NOT NULL constraint
        # without rewriting data. The Welcome→Step1 transient rows would
        # block downgrade until Step 1 has been completed for every
        # session; that's acceptable since downgrade is only used in
        # dev rollback scenarios where we'd wipe the pilot DB anyway.
        b.alter_column('people', existing_type=sa.Integer(), nullable=False)
        b.alter_column('area_m2', existing_type=sa.Float(), nullable=False)
        b.drop_column('entry_threshold_pct')
