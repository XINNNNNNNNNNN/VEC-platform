"""Idempotent upsert helpers for the measurement tables.

Phase E: previously, several Submit callbacks did an unconditional
``db.add(...)`` and others used a "skip if already exists" defensive
guard — both shapes break if the participant presses Back and
resubmits the same step:

* Unconditional ``db.add`` (step0 round=1, info_calibration round=1,
  step1 UserInput/DailyProfile/BillBreakdown) → duplicate rows pile
  up; analysis has to pick a winner.
* Defensive idempotency (step5 round=2, step7 round=3, device_shift
  round=2, device_shift step4_q1/q2) → no dup, but the *new* value
  is silently dropped.

This module provides the third shape — a true upsert — modelled on
``_survey_helpers.get_or_create_survey_row``: query first, ``db.add``
the row if missing, then set fields and return the ORM instance.
SQLAlchemy's dirty tracking handles INSERT vs UPDATE at commit time.

Schema-level UNIQUE constraints on (session_id, measurement_round)
and (session_id, round) belong in a future migration (pilot-prep
cleanup). The helper makes the application layer idempotent today.
"""

from typing import Optional

from vec_platform.models import PriorExpectation, WillingnessMeasurement


def upsert_prior_expectation(
    db,
    session_id: str,
    measurement_round: int,
    pct: float,
    confidence: Optional[int] = None,
) -> PriorExpectation:
    """Insert or update the (session_id, measurement_round) row.

    ``confidence`` is only set when explicitly provided so the caller
    can leave the column NULL for round=1 (which has no confidence
    Likert) without clobbering an existing value on resubmit.
    """
    row = (
        db.query(PriorExpectation)
        .filter(
            PriorExpectation.session_id == session_id,
            PriorExpectation.measurement_round == measurement_round,
        )
        .first()
    )
    if row is None:
        row = PriorExpectation(
            session_id=session_id,
            measurement_round=measurement_round,
        )
        db.add(row)
    row.pct = float(pct)
    if confidence is not None:
        row.confidence = int(confidence)
    return row


def upsert_willingness(
    db,
    session_id: str,
    round_: int,
    scale_type: str,
    value: int,
) -> WillingnessMeasurement:
    """Insert or update the (session_id, round) row.

    ``round_`` is suffixed to avoid shadowing the Python builtin in
    the helper signature; the SQLAlchemy column is named ``round``.
    """
    row = (
        db.query(WillingnessMeasurement)
        .filter(
            WillingnessMeasurement.session_id == session_id,
            WillingnessMeasurement.round == round_,
        )
        .first()
    )
    if row is None:
        row = WillingnessMeasurement(
            session_id=session_id,
            round=round_,
            scale_type=scale_type,
        )
        db.add(row)
    # Update both fields each time so a session that somehow recorded
    # the wrong scale_type (e.g., from a model migration) is healed.
    row.scale_type = scale_type
    row.value = int(value)
    return row
