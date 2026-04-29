"""Step 8 — final survey + submit callback.

Importing this module registers the Dash callback against ``dash_app``.
On submit the callback writes a SurveyResponse row, marks the session
completed, and replaces the form with the thank-you view.
"""

import json

from dash import html, no_update
from dash.dependencies import Input, Output, State
import dash_bootstrap_components as dbc

from vec_platform.runtime import dash_app, SessionLocal
from vec_platform.pages._helpers import _parse_session_id


# ==================== Step 8 ====================

_Q1_OPTIONS = [
    {"label": "Very willing", "value": "very_willing"},
    {"label": "Somewhat willing", "value": "somewhat"},
    {"label": "I'd need more information", "value": "need_more_info"},
    {"label": "Unlikely", "value": "unlikely"},
    {"label": "Not willing", "value": "not_willing"},
]

_Q2_OPTIONS = [
    {"label": "Save money on my bill", "value": "savings"},
    {"label": "Environmental benefit", "value": "environment"},
    {"label": "Support my local community", "value": "community"},
    {"label": "More control over my energy", "value": "control"},
    {"label": "Looks easy / convenient", "value": "convenience"},
    {"label": "Other", "value": "other"},
]

_Q3_OPTIONS = [
    {"label": "Privacy of my usage data", "value": "privacy"},
    {"label": "Seems too complex to use", "value": "complexity"},
    {"label": "Savings look too small", "value": "insufficient_savings"},
    {"label": "Losing control of my appliances", "value": "loss_of_control"},
    {"label": "Don't trust the operator", "value": "distrust"},
    {"label": "Other", "value": "other"},
]

_Q4_OPTIONS = [
    {"label": "Yes, attractive savings", "value": "attractive"},
    {"label": "Somewhat interesting", "value": "somewhat"},
    {"label": "Not enough to bother", "value": "not_enough"},
    {"label": "Unsure", "value": "unsure"},
]


def _survey_form(session_id: str) -> html.Div:
    return html.Div(id="step8-form", children=[
        html.H5("Q1 · How likely are you to actually join a VEC like this?"),
        dbc.RadioItems(id="survey-q1", options=_Q1_OPTIONS, value=None, className="mb-4"),

        html.H5("Q2 · What would be your top reasons to join? (pick up to 3)"),
        dbc.Checklist(id="survey-q2", options=_Q2_OPTIONS, value=[], className="mb-4"),

        html.H5("Q3 · What would worry you the most? (pick up to 3)"),
        dbc.Checklist(id="survey-q3", options=_Q3_OPTIONS, value=[], className="mb-4"),

        html.H5("Q4 · Looking at the savings you saw in Step 6…"),
        dbc.RadioItems(id="survey-q4", options=_Q4_OPTIONS, value=None, className="mb-3"),

        html.Div(id="survey-error", className="text-danger mb-2"),

        dbc.Row([
            dbc.Col(
                dbc.Button(
                    "← Back to Step 7",
                    href=f"/dash/step7?session_id={session_id}",
                    color="secondary",
                ),
                width="auto",
            ),
            dbc.Col(
                dbc.Button("Submit", id="btn-submit-survey",
                          color="primary", size="lg"),
                width="auto",
            ),
        ], justify="between"),
    ])


def _thank_you_view() -> html.Div:
    return html.Div([
        dbc.Alert(
            [
                html.H3("Thank you for participating! 🎉", className="mb-3"),
                html.P(
                    "Your answers have been recorded. Researchers at KTH and "
                    "E.ON will use responses like yours to design real "
                    "virtual energy communities in Sweden."
                ),
                html.P(
                    "You can safely close this tab, or start again with a "
                    "new session:",
                    className="mb-2",
                ),
                dbc.Button("Start over", href="/", color="primary",
                           external_link=True),
            ],
            color="success",
        ),
    ])


def step8_layout(session_id: str | None):
    if not session_id:
        return html.Div([
            html.H2("Step 8: Your decision"),
            dbc.Alert("No session found. Please start from Step 1.", color="warning"),
        ])

    from vec_platform.models import Session as SessionModel, SurveyResponse

    db = SessionLocal()
    try:
        session = (
            db.query(SessionModel)
            .filter(SessionModel.id == session_id)
            .first()
        )
        already = (
            db.query(SurveyResponse)
            .filter(SurveyResponse.session_id == session_id)
            .first()
        )
    finally:
        db.close()

    if session is None:
        return html.Div([
            html.H2("Step 8: Your decision"),
            dbc.Alert("Session not found.", color="warning"),
        ])

    if already is not None:
        return html.Div([
            html.H2("Step 8: Your decision"),
            _thank_you_view(),
        ])

    return html.Div([
        html.H2("Step 8: Your decision"),
        html.P(
            "One last thing. After seeing how a VEC could change your bill, "
            "your daily schedule, and your footprint — how do you actually "
            "feel about joining?"
        ),
        html.Div(_survey_form(session_id), id="step8-content"),
    ])


@dash_app.callback(
    Output("step8-content", "children"),
    Output("survey-error", "children"),
    Input("btn-submit-survey", "n_clicks"),
    State("survey-q1", "value"),
    State("survey-q2", "value"),
    State("survey-q3", "value"),
    State("survey-q4", "value"),
    State("url", "search"),
    prevent_initial_call=True,
)
def submit_survey(n_clicks, q1, q2, q3, q4, search):
    if not n_clicks:
        return no_update, no_update

    if not q1 or not q4:
        return no_update, "Please answer Q1 and Q4 before submitting."

    session_id = _parse_session_id(search)
    if not session_id:
        return no_update, "Session id missing from URL. Please start from Step 1."

    from vec_platform.models import (
        Session as SessionModel,
        SurveyResponse,
    )

    # Cap multi-selects at 3 so "top 3" is enforced in the data.
    q2_trim = (q2 or [])[:3]
    q3_trim = (q3 or [])[:3]

    db = SessionLocal()
    try:
        session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
        if session is None:
            return no_update, "Session not found. Please start from Step 1."

        # Idempotency: don't insert twice if the user clicks Submit rapidly.
        existing = (
            db.query(SurveyResponse)
            .filter(SurveyResponse.session_id == session_id)
            .first()
        )
        if existing is None:
            db.add(SurveyResponse(
                session_id=session_id,
                q1_willingness=q1,
                q2_reasons=json.dumps(q2_trim),
                q3_concerns=json.dumps(q3_trim),
                q4_savings_perception=q4,
            ))

        session.completed = True
        session.current_step = 8
        db.commit()
    finally:
        db.close()

    return _thank_you_view(), ""
