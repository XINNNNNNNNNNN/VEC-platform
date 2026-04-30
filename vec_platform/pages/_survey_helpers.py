"""Upsert helper for the survey_responses table.

Each session has at most one row in survey_responses. Different page
callbacks fill different subsets of the row's columns at different points
in the journey:

  Step 4 submit  → step4_q1_shift_intent + step4_q2_control_pref
  Step 8 submit  → q1_willingness, q2_reasons, q3_concerns, q4_savings_perception

Whoever runs first creates the row; later writers update it. This module
exists so both callbacks share the same get-or-create code path and don't
race-INSERT two rows for the same session.
"""

from vec_platform.models import SurveyResponse


def get_or_create_survey_row(db, session_id: str) -> SurveyResponse:
    """Return the existing survey_responses row for ``session_id``, or
    stage a new empty one (caller commits).

    Caller is responsible for setting the relevant fields and calling
    ``db.commit()``. The new row is added to the session via ``db.add``
    but NOT flushed/committed here, so the caller can fill fields and
    commit atomically.
    """
    row = (
        db.query(SurveyResponse)
        .filter(SurveyResponse.session_id == session_id)
        .first()
    )
    if row is None:
        row = SurveyResponse(session_id=session_id)
        db.add(row)
    return row
