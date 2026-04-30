"""Step 8 — final survey + submit callback.

v3.9 expansion (Phase 3.9):
  - Q1-Q4 (kept from v3 baseline)
  - Q5 trust source / Q6 fairness preference / Q7 transparency preference
  - Entry threshold slider + exit threshold radio
  - Final willingness Likert (3rd/last willingness measurement, round=3)
  - Expert-only block (3 questions, conditional on sessions.expertise)
  - Demographics block (age / gender / country)

Submitting upserts survey_responses, upserts a single exit_thresholds
row (carrying both entry and exit thresholds), and inserts a
willingness_measurements(round=3, scale_type='4point_accept') row.

Importing this module registers three Dash callbacks against
``dash_app``: slider display, Submit-enable gate, Submit handler.
"""

import json

from dash import html, dcc, no_update
from dash.dependencies import Input, Output, State
import dash_bootstrap_components as dbc

from vec_platform.runtime import dash_app, SessionLocal
from vec_platform.pages._helpers import _parse_session_id


# ==================== Step 8 ====================

# ----- existing (v3 baseline) -----

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


# ----- v3.9 new options -----

_Q5_OPTIONS = [
    {"label": "Government / municipality", "value": "government"},
    {"label": "My existing electricity supplier (e.g., E.ON, Vattenfall)",
     "value": "utility"},
    {"label": "Independent energy cooperative", "value": "coop"},
    {"label": "Tech company (e.g., Tibber, Greenely)", "value": "tech"},
    {"label": "I would not trust any of these", "value": "none"},
]

_Q6_OPTIONS = [
    {"label": "Equally — everyone gets the same share", "value": "equal"},
    {"label": "Proportional — those who contribute more get more",
     "value": "proportional"},
    {"label": "Need-based — those with lower incomes get more", "value": "needs"},
    {"label": "I'm not sure", "value": "unsure"},
]

_Q7_OPTIONS = [
    {"label": "Just my monthly bill", "value": "minimal"},
    {"label": "Plus a simple summary of my contribution", "value": "summary"},
    {"label": "Plus details on community-wide flows", "value": "detailed"},
    {"label": "Full transparency — all real-time data accessible", "value": "full"},
]

_EXIT_OPTIONS = [
    {"label": "Savings drop to 75% of my expectation — I'd consider leaving", "value": 0.75},
    {"label": "Drop to 50%", "value": 0.50},
    {"label": "Drop to 25%", "value": 0.25},
    {"label": "Drop to 0% (no savings at all)", "value": 0.0},
    {"label": "I would not leave even if savings were zero", "value": -1.0},
]

_FINAL_WILLINGNESS_OPTIONS = [
    {"label": "I would definitely join", "value": 4},
    {"label": "I would probably join", "value": 3},
    {"label": "I would probably not join", "value": 2},
    {"label": "I would definitely not join", "value": 1},
]

_EXPERT_Q1_OPTIONS = [
    {"label": "1 — Very unrealistic", "value": 1},
    {"label": "2 — Unrealistic", "value": 2},
    {"label": "3 — Neutral", "value": 3},
    {"label": "4 — Realistic", "value": 4},
    {"label": "5 — Very realistic", "value": 5},
]

_EXPERT_Q2_OPTIONS = [
    {"label": "Regulatory framework (Ei rules, billing settlement)",
     "value": "regulatory"},
    {"label": "Lack of consumer awareness", "value": "awareness"},
    {"label": "Technical infrastructure (smart meters, data exchange)",
     "value": "tech"},
    {"label": "Financial incentives are too weak", "value": "incentives"},
    {"label": "DSO/aggregator business models unclear", "value": "biz_model"},
]

_AGE_OPTIONS = [
    {"label": "18-29", "value": "18-29"},
    {"label": "30-39", "value": "30-39"},
    {"label": "40-49", "value": "40-49"},
    {"label": "50-59", "value": "50-59"},
    {"label": "60-69", "value": "60-69"},
    {"label": "70+",   "value": "70+"},
]

_GENDER_OPTIONS = [
    {"label": "Male",   "value": "male"},
    {"label": "Female", "value": "female"},
    {"label": "Other",  "value": "other"},
    {"label": "Prefer not to say", "value": "no_answer"},
]

_COUNTRY_OPTIONS = [
    {"label": "Sweden", "value": "SE"},
    {"label": "Other",  "value": "OTHER"},
]


# ----- form layout -----

_BLOCK_RADIO_STYLE = {"display": "block", "padding": "0.3rem 0"}


def _radio_card(question: str, radio_id: str, options: list) -> dbc.Card:
    """Compact wrapper used for the v3.9 single-radio question cards."""
    return dbc.Card(dbc.CardBody([
        html.H4(question),
        dcc.RadioItems(
            id=radio_id, options=options, value=None,
            labelStyle=_BLOCK_RADIO_STYLE,
        ),
    ]), className="mb-3")


def _expert_block() -> list:
    """Three expert-only questions. Caller decides whether to include."""
    return [
        html.Hr(),
        html.H3("Expert questions", className="mt-4 mb-3"),
        _radio_card(
            "Based on your professional knowledge, how realistic is it "
            "that the savings shown in this study would actually be "
            "delivered to participants?",
            "step8-expert-q1-realism", _EXPERT_Q1_OPTIONS,
        ),
        _radio_card(
            "What do you think is the biggest barrier to widespread VEC "
            "adoption in Sweden?",
            "step8-expert-q2-barrier", _EXPERT_Q2_OPTIONS,
        ),
        dbc.Card(dbc.CardBody([
            html.H4(
                "How well does this stated-preference study capture "
                "real-world VEC participation behaviour?"
            ),
            dcc.Textarea(
                id="step8-expert-q3-comment",
                placeholder="Optional, max 200 characters",
                maxLength=200,
                style={"width": "100%", "height": 80},
            ),
        ]), className="mb-3"),
    ]


def _survey_form(session_id: str, is_expert: bool) -> html.Div:
    """Full survey form. Expert block is conditional on sessions.expertise."""

    expert = _expert_block() if is_expert else []

    return html.Div(id="step8-form", children=[
        # ----- Q1-Q4 (existing v3 baseline) -----
        html.H5("Q1 · How likely are you to actually join a VEC like this?"),
        dbc.RadioItems(id="survey-q1", options=_Q1_OPTIONS, value=None, className="mb-4"),

        html.H5("Q2 · What would be your top reasons to join? (pick up to 3)"),
        dbc.Checklist(id="survey-q2", options=_Q2_OPTIONS, value=[], className="mb-4"),

        html.H5("Q3 · What would worry you the most? (pick up to 3)"),
        dbc.Checklist(id="survey-q3", options=_Q3_OPTIONS, value=[], className="mb-4"),

        html.H5("Q4 · Looking at the savings you saw in Step 6…"),
        dbc.RadioItems(id="survey-q4", options=_Q4_OPTIONS, value=None, className="mb-3"),

        # ----- Q5 / Q6 / Q7 (v3.9) -----
        html.Hr(),
        _radio_card(
            "If a VEC service were available where you live, who would "
            "you most trust to manage it?",
            "step8-q5-trust-source", _Q5_OPTIONS,
        ),
        _radio_card(
            "If everyone in the VEC contributes differently (some have "
            "solar, some don't), how should the savings be split?",
            "step8-q6-fairness", _Q6_OPTIONS,
        ),
        _radio_card(
            "How much information would you want about the VEC's operation?",
            "step8-q7-transparency", _Q7_OPTIONS,
        ),

        # ----- entry threshold slider -----
        dbc.Card(dbc.CardBody([
            html.H4(
                "Before joining, what minimum % of monthly bill savings "
                "would you require to consider joining a VEC at all?"
            ),
            dcc.Slider(
                id="step8-entry-threshold-pct",
                min=0, max=50, step=1, value=0,
                marks={p: f"{p}%" for p in (0, 10, 20, 30, 40, 50)},
                tooltip={"placement": "bottom", "always_visible": False},
            ),
            html.Div(
                "0%",
                id="step8-entry-threshold-display",
                className="text-center fs-4 fw-bold mt-2",
            ),
        ]), className="mb-3"),

        # ----- exit threshold -----
        _radio_card(
            "Imagine you joined a VEC and during the first months your "
            "actual savings turn out to be lower than what you originally "
            "expected. At what point would you consider leaving?",
            "step8-exit-threshold", _EXIT_OPTIONS,
        ),

        # ----- final willingness (3rd measurement) -----
        _radio_card(
            "All things considered, if you were offered the chance to "
            "join a VEC tomorrow, what would you do?",
            "step8-final-willingness", _FINAL_WILLINGNESS_OPTIONS,
        ),

        # ----- expert block (conditional) -----
        *expert,

        # ----- demographics -----
        html.Hr(),
        html.H3("A few questions about you", className="mt-4 mb-3"),
        dbc.Card(dbc.CardBody([
            html.H4("Age range"),
            dcc.RadioItems(
                id="step8-demo-age", options=_AGE_OPTIONS, value=None,
                labelStyle={"display": "inline-block", "marginRight": "1rem"},
            ),
            html.Hr(),
            html.H4("Gender"),
            dcc.RadioItems(
                id="step8-demo-gender", options=_GENDER_OPTIONS, value=None,
                labelStyle={"display": "inline-block", "marginRight": "1rem"},
            ),
            html.Hr(),
            html.H4("Country"),
            dcc.Dropdown(
                id="step8-demo-country", options=_COUNTRY_OPTIONS,
                value="SE", clearable=False,
            ),
        ]), className="mb-3"),

        # ----- error + buttons -----
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
                          color="primary", size="lg",
                          disabled=True),
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

    # A row may exist with only the step4_* fields filled (Phase 3.5) but
    # no q1_willingness yet — those participants still need to fill out
    # the survey, so the thank-you gate is "did the survey actually
    # submit", i.e. q1_willingness is non-NULL.
    if already is not None and already.q1_willingness:
        return html.Div([
            html.H2("Step 8: Your decision"),
            _thank_you_view(),
        ])

    is_expert = (session.expertise == "expert")

    return html.Div([
        html.H2("Step 8: Your decision"),
        html.P(
            "One last thing. After seeing how a VEC could change your bill, "
            "your daily schedule, and your footprint — how do you actually "
            "feel about joining?"
        ),
        html.Div(
            _survey_form(session_id, is_expert=is_expert),
            id="step8-content",
        ),
    ])


# ==================== callbacks ====================

@dash_app.callback(
    Output("step8-entry-threshold-display", "children"),
    Input("step8-entry-threshold-pct", "value"),
)
def update_step8_entry_threshold_display(pct):
    """Live "X%" label below the entry-threshold slider."""
    return f"{pct}%"


@dash_app.callback(
    Output("btn-submit-survey", "disabled"),
    Input("survey-q1", "value"),
    Input("survey-q4", "value"),
    Input("step8-q5-trust-source", "value"),
    Input("step8-q6-fairness", "value"),
    Input("step8-q7-transparency", "value"),
    Input("step8-exit-threshold", "value"),
    Input("step8-final-willingness", "value"),
    Input("step8-demo-age", "value"),
    Input("step8-demo-gender", "value"),
)
def toggle_step8_submit(q1, q4, q5, q6, q7, exit_t, final_w, age, gender):
    """Lock Submit until every required question has a value.

    Required: Q1, Q4, Q5, Q6, Q7, exit threshold, final willingness, age,
    gender. NOT required:
      - Q2/Q3 multi-select (empty list is acceptable, matches v3 baseline)
      - entry threshold slider (default 0% counts as answered)
      - country dropdown (default 'SE' counts as answered)
      - expert questions (optional even for experts — don't block them)
    """
    required = [q1, q4, q5, q6, q7, exit_t, final_w, age, gender]
    return any(v is None for v in required)


@dash_app.callback(
    Output("step8-content", "children"),
    Output("survey-error", "children"),
    Input("btn-submit-survey", "n_clicks"),
    # Q1-Q4 — existing baseline
    State("survey-q1", "value"),
    State("survey-q2", "value"),
    State("survey-q3", "value"),
    State("survey-q4", "value"),
    # v3.9 new states
    State("step8-q5-trust-source", "value"),
    State("step8-q6-fairness", "value"),
    State("step8-q7-transparency", "value"),
    State("step8-entry-threshold-pct", "value"),
    State("step8-exit-threshold", "value"),
    State("step8-final-willingness", "value"),
    State("step8-expert-q1-realism", "value"),
    State("step8-expert-q2-barrier", "value"),
    State("step8-expert-q3-comment", "value"),
    State("step8-demo-age", "value"),
    State("step8-demo-gender", "value"),
    State("step8-demo-country", "value"),
    State("url", "search"),
    prevent_initial_call=True,
)
def submit_survey(n_clicks, q1, q2, q3, q4,
                  q5, q6, q7,
                  entry_pct, exit_t, final_w,
                  eq1, eq2, eq3,
                  age, gender, country,
                  search):
    """v3.9: writes survey_responses (upsert) + exit_thresholds (upsert) +
    willingness_measurements(round=3) + flips sessions.completed=True.

    Expert states (eq1/eq2/eq3) come back as None when the expert block
    isn't rendered (suppress_callback_exceptions=True is set globally).
    """
    if not n_clicks:
        return no_update, no_update

    session_id = _parse_session_id(search)
    if not session_id:
        return no_update, "Session id missing from URL. Please start from Step 1."

    # Defensive validation — toggle keeps Submit disabled until these
    # are filled, but synthetic clicks could bypass the UI gate.
    required = [q1, q4, q5, q6, q7, exit_t, final_w, age, gender]
    if any(v is None for v in required):
        return no_update, "Please answer all required questions."

    from vec_platform.models import (
        Session as SessionModel,
        ExitThreshold,
        WillingnessMeasurement,
    )
    from vec_platform.pages._survey_helpers import get_or_create_survey_row

    # Cap multi-selects at 3 so "top 3" is enforced in the data.
    q2_trim = (q2 or [])[:3]
    q3_trim = (q3 or [])[:3]

    db = SessionLocal()
    try:
        session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
        if session is None:
            return no_update, "Session not found. Please start from Step 1."

        # 1) survey_responses — upsert all fields onto the per-session row.
        row = get_or_create_survey_row(db, session_id)
        row.q1_willingness = q1
        row.q2_reasons = json.dumps(q2_trim)
        row.q3_concerns = json.dumps(q3_trim)
        row.q4_savings_perception = q4
        row.q5_trust_source = q5
        row.q6_fairness_pref = q6
        row.q7_transparency_pref = q7
        row.expert_q1_realism = eq1  # None for non-experts, schema is nullable
        row.expert_q2_barrier = eq2
        row.expert_q3_comment = (eq3 or None) or None  # treat empty string as None
        row.demo_age_range = age
        row.demo_gender = gender
        row.demo_country = country or "SE"

        # 2) exit_thresholds — single row per session (upsert pattern).
        et = (
            db.query(ExitThreshold)
            .filter(ExitThreshold.session_id == session_id)
            .first()
        )
        if et is None:
            et = ExitThreshold(session_id=session_id)
            db.add(et)
        et.threshold_ratio = float(exit_t)
        et.entry_threshold_pct = float(entry_pct)

        # 3) willingness_measurements round=3. Defensive idempotency:
        # don't double-insert if a re-submit somehow fires.
        existing = (
            db.query(WillingnessMeasurement)
            .filter(
                WillingnessMeasurement.session_id == session_id,
                WillingnessMeasurement.round == 3,
            )
            .first()
        )
        if existing is None:
            db.add(WillingnessMeasurement(
                session_id=session_id,
                round=3,
                scale_type="4point_accept",
                value=int(final_w),
            ))

        # 4) Mark the session complete. current_step=9 means "past Step 8";
        # progress bar tops out at 8 anyway.
        session.completed = True
        session.current_step = 9

        db.commit()
    finally:
        db.close()

    return _thank_you_view(), ""
