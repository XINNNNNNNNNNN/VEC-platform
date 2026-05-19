"""Upsert helper for the survey_responses table.

Each session has at most one row in survey_responses. Different page
callbacks fill different subsets of the row's columns at different points
in the journey (Phase 4-A renumbering applied):

  Step 3 submit  → step3_q1_shift_intent + step3_q2_control_pref
  Step 5 submit  → step5_disconfirmation_emotion (Phase Q-3a)
  Step 6 submit  → step6_broader_impacts_shift
  Step 7 submit  → q1_willingness, q3_concerns, q4_savings_perception, +
                   q5_trust_source, q6_fairness_pref, q7_transparency_pref,
                   demographics, drivers_top3, expert_*

Whoever runs first creates the row; later writers update it. This module
exists so the callbacks share the same get-or-create code path and don't
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
