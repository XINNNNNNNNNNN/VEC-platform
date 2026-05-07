"""Step 7 — final survey + submit callback.

Phase 4-A: renumbered from Step 8 (8-step flow) to Step 7 (7-step flow).
File renamed step8.py → step7.py; identifiers, widget IDs, and UI
labels updated accordingly. Survey-question CSS class names that
identify *this page* use step7-* (e.g., step7-q5-trust-source).

Survey content:
  - Q1-Q4 (kept from v3 baseline)
  - Q5 trust source / Q6 fairness preference / Q7 transparency preference
  - Entry threshold slider + exit threshold radio
  - Final willingness Likert (3rd/last willingness measurement, round=3)
  - Expert-only block (3 questions; v3.X-fix-9 gates on
    sessions.vec_familiarity ∈ _EXPERT_FAMILIARITY_GATE — replaces the
    earlier sessions.expertise self-label gate)
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


# ==================== Step 7 ====================

# ----- existing (v3 baseline) -----

_Q1_OPTIONS = [
    {"label": "Very willing", "value": "very_willing"},
    {"label": "Somewhat willing", "value": "somewhat"},
    {"label": "I'd need more information", "value": "need_more_info"},
    {"label": "Unlikely", "value": "unlikely"},
    {"label": "Not willing", "value": "not_willing"},
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

# Phase 3.X-fix-9: expert block now gated by vec_familiarity (top 2 of
# the 5-pt scale: 'very_familiar' or 'have_participated'). Replaces the
# Phase 3.9 / fix-3.9 gate of `expertise == 'expert'`, which was a Step 1
# occupation self-label. Self-labelling has low validity and risks demand
# effect (people who tick "energy professional" may answer differently
# *because* of the label); a prior-knowledge proxy from Step 0's
# familiarity slider is methodologically cleaner.
#
# Backward compat: sessions.expertise + user_inputs.occupation columns
# (and the Step 1 occupation question) are intentionally preserved.
# Analyses can compare self-label vs. familiarity-gate definitions.
_EXPERT_FAMILIARITY_GATE = {"very_familiar", "have_participated"}


# v3.X-fix-7 / fix-8 — E.ON Q13 alignment + merged legacy Q2_reasons.
# The 9 values keep E.ON Q13 cross-reference (so the column directly
# compares to the E.ON survey); the visible labels were rewritten in
# fix-8 to the conversational Q2-style wording for pilot UX.
# Stored as a JSON-encoded list on survey_responses.drivers_top3.
_DRIVERS_OPTIONS = [
    {"label": "Save money on my bill",          "value": "savings"},
    {"label": "Environmental / climate impact", "value": "climate"},
    {"label": "Support my local community",     "value": "community"},
    {"label": "More control over my energy",    "value": "control"},
    {"label": "Looks simple / easy to use",     "value": "simplicity"},
    {"label": "Privacy of my data",             "value": "privacy"},
    {"label": "Transparent benefit sharing",    "value": "transparency"},
    {"label": "Helps the local grid",           "value": "grid_benefit"},
    {"label": "Other",                           "value": "other"},
]
_DRIVERS_MAX = 3


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
    """Three extra questions for the high-familiarity subset. Caller
    (step7_layout) decides whether to include via the
    _EXPERT_FAMILIARITY_GATE check.

    Phase 3.X-fix-10: removed the leading ``html.Hr()`` divider and the
    ``html.H3("Expert questions")`` group title. Users gated on
    vec_familiarity should not be told they're being singled out as
    experts — the three cards visually blend in with the rest of the
    survey. The question wording is left intact (it lives inside the
    cards and is part of the question content, not the framing).
    """
    return [
        _radio_card(
            "Based on your professional knowledge, how realistic is it "
            "that the savings shown in this study would actually be "
            "delivered to participants?",
            "step7-expert-q1-realism", _EXPERT_Q1_OPTIONS,
        ),
        _radio_card(
            "What do you think is the biggest barrier to widespread VEC "
            "adoption in Sweden?",
            "step7-expert-q2-barrier", _EXPERT_Q2_OPTIONS,
        ),
        dbc.Card(dbc.CardBody([
            html.H4(
                "How well does this stated-preference study capture "
                "real-world VEC participation behaviour?"
            ),
            dcc.Textarea(
                id="step7-expert-q3-comment",
                placeholder="Optional, max 200 characters",
                maxLength=200,
                style={"width": "100%", "height": 80},
            ),
        ]), className="mb-3"),
    ]


def _survey_form(session_id: str, is_expert: bool) -> html.Div:
    """Full survey form. Expert block visibility is decided by the caller
    (step7_layout) — v3.X-fix-9 derives ``is_expert`` from
    ``sessions.vec_familiarity ∈ _EXPERT_FAMILIARITY_GATE`` instead of
    the former ``sessions.expertise == 'expert'`` self-label."""

    expert = _expert_block() if is_expert else []

    return html.Div(id="step7-form", children=[
        # ----- Q1-Q3 baseline (v3.X-fix-8: original Q2 was merged into
        # drivers_top3 below, so this block is now Q1 / Q2 (concerns) /
        # Q3 (savings perception). The "top reasons" question lives in
        # the drivers_top3 card further down.) -----
        html.H5("Q1 · How likely are you to actually join a VEC like this?"),
        dbc.RadioItems(id="survey-q1", options=_Q1_OPTIONS, value=None, className="mb-4"),

        html.H5("Q2 · What would worry you the most? (pick up to 3)"),
        dbc.Checklist(id="survey-q3", options=_Q3_OPTIONS, value=[], className="mb-4"),

        html.H5("Q3 · Looking at the savings you saw in Step 5…"),
        dbc.RadioItems(id="survey-q4", options=_Q4_OPTIONS, value=None, className="mb-3"),

        # ----- Q5 / Q6 / Q7 (v3.9) -----
        html.Hr(),
        _radio_card(
            "If a VEC service were available where you live, who would "
            "you most trust to manage it?",
            "step7-q5-trust-source", _Q5_OPTIONS,
        ),
        _radio_card(
            "If everyone in the VEC contributes differently (some have "
            "solar, some don't), how should the savings be split?",
            "step7-q6-fairness", _Q6_OPTIONS,
        ),
        _radio_card(
            "How much information would you want about the VEC's operation?",
            "step7-q7-transparency", _Q7_OPTIONS,
        ),

        # ----- entry threshold slider -----
        dbc.Card(dbc.CardBody([
            html.H4(
                "Before joining, what minimum % of monthly bill savings "
                "would you require to consider joining a VEC at all?"
            ),
            dcc.Slider(
                id="step7-entry-threshold-pct",
                min=0, max=50, step=1, value=0,
                marks={p: f"{p}%" for p in (0, 10, 20, 30, 40, 50)},
                tooltip={"placement": "bottom", "always_visible": False},
            ),
            html.Div(
                "0%",
                id="step7-entry-threshold-display",
                className="text-center fs-4 fw-bold mt-2",
            ),
        ]), className="mb-3"),

        # ----- exit threshold -----
        _radio_card(
            "Imagine you joined a VEC and during the first months your "
            "actual savings turn out to be lower than what you originally "
            "expected. At what point would you consider leaving?",
            "step7-exit-threshold", _EXIT_OPTIONS,
        ),

        # ----- final willingness (3rd measurement) -----
        _radio_card(
            "All things considered, if you were offered the chance to "
            "join a VEC tomorrow, what would you do?",
            "step7-final-willingness", _FINAL_WILLINGNESS_OPTIONS,
        ),

        # ----- expert block (conditional) -----
        *expert,

        # ----- v3.X-fix-7 / fix-8: E.ON Q13 drivers top-3 (also serves
        # as the merged Q2_reasons question) -----
        html.Hr(),
        dbc.Card(dbc.CardBody([
            html.H4(
                f"What would be your top reasons to join a VEC like "
                f"this? (pick up to {_DRIVERS_MAX})"
            ),
            dcc.Checklist(
                id="step7-drivers-top3",
                options=_DRIVERS_OPTIONS,
                value=[],
                labelStyle={"display": "block", "padding": "0.2rem 0"},
            ),
            html.Div(id="step7-drivers-warn", className="text-warning small mt-1"),
        ]), className="mb-3"),

        # ----- demographics -----
        html.H3("A few questions about you", className="mt-4 mb-3"),
        dbc.Card(dbc.CardBody([
            html.H4("Age range"),
            dcc.RadioItems(
                id="step7-demo-age", options=_AGE_OPTIONS, value=None,
                labelStyle={"display": "inline-block", "marginRight": "1rem"},
            ),
            html.Hr(),
            html.H4("Gender"),
            dcc.RadioItems(
                id="step7-demo-gender", options=_GENDER_OPTIONS, value=None,
                labelStyle={"display": "inline-block", "marginRight": "1rem"},
            ),
            html.Hr(),
            html.H4("Country"),
            dcc.Dropdown(
                id="step7-demo-country", options=_COUNTRY_OPTIONS,
                value="SE", clearable=False,
            ),
        ]), className="mb-3"),

        # ----- error + buttons -----
        html.Div(id="survey-error", className="text-danger mb-2"),

        dbc.Row([
            dbc.Col(
                dbc.Button("Submit", id="btn-submit-survey",
                          color="primary", size="lg",
                          disabled=True),
                width="auto",
            ),
        ], justify="end"),
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


def step7_layout(session_id: str | None):
    if not session_id:
        return html.Div([
            html.H2("Step 7: Your decision"),
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
            html.H2("Step 7: Your decision"),
            dbc.Alert("Session not found.", color="warning"),
        ])

    # A row may exist with only the step3_* fields filled (Phase 4-A's
    # renamed step3 prices page) but no q1_willingness yet — those
    # participants still need to fill out the survey, so the thank-you
    # gate is "did the survey actually submit", i.e. q1_willingness is
    # non-NULL.
    if already is not None and already.q1_willingness:
        return html.Div([
            html.H2("Step 7: Your decision"),
            _thank_you_view(),
        ])

    # v3.X-fix-9: gate switched from expertise self-label to a
    # vec_familiarity threshold (top 2 of the 5-pt scale). expertise
    # remains readable on the session object for backward compat.
    is_expert = (session.vec_familiarity in _EXPERT_FAMILIARITY_GATE)

    return html.Div([
        html.H2("Step 7: Your decision"),
        html.P(
            "One last thing. After seeing how a VEC could change your bill, "
            "your daily schedule, and your footprint — how do you actually "
            "feel about joining?"
        ),
        html.Div(
            _survey_form(session_id, is_expert=is_expert),
            id="step7-content",
        ),
    ])


# ==================== callbacks ====================

@dash_app.callback(
    Output("step7-entry-threshold-display", "children"),
    Input("step7-entry-threshold-pct", "value"),
)
def update_step7_entry_threshold_display(pct):
    """Live "X%" label below the entry-threshold slider."""
    return f"{pct}%"


@dash_app.callback(
    Output("step7-drivers-warn", "children"),
    Input("step7-drivers-top3", "value"),
)
def warn_drivers_max(values):
    """v3.X-fix-7: warn when the user picks more than _DRIVERS_MAX
    options. The submit gate also enforces the cap (defensive)."""
    if values and len(values) > _DRIVERS_MAX:
        return f"Please select at most {_DRIVERS_MAX} options."
    return ""


@dash_app.callback(
    Output("btn-submit-survey", "disabled"),
    Input("survey-q1", "value"),
    Input("survey-q4", "value"),
    Input("step7-q5-trust-source", "value"),
    Input("step7-q6-fairness", "value"),
    Input("step7-q7-transparency", "value"),
    Input("step7-exit-threshold", "value"),
    Input("step7-final-willingness", "value"),
    Input("step7-demo-age", "value"),
    Input("step7-demo-gender", "value"),
    Input("step7-drivers-top3", "value"),
)
def toggle_step7_submit(q1, q4, q5, q6, q7, exit_t, final_w, age, gender, drivers):
    """Lock Submit until every required question has a value.

    Required: Q1, Q4, Q5, Q6, Q7, exit threshold, final willingness, age,
    gender. v3.X-fix-7 added drivers_top3 — must be 1.._DRIVERS_MAX picks.
    NOT required:
      - Q2/Q3 multi-select (empty list is acceptable, matches v3 baseline)
      - entry threshold slider (default 0% counts as answered)
      - country dropdown (default 'SE' counts as answered)
      - expert questions (optional even for experts — don't block them)
    """
    required = [q1, q4, q5, q6, q7, exit_t, final_w, age, gender]
    if any(v is None for v in required):
        return True
    n = len(drivers or [])
    if n < 1 or n > _DRIVERS_MAX:
        return True
    return False


@dash_app.callback(
    Output("step7-content", "children"),
    Output("survey-error", "children"),
    Input("btn-submit-survey", "n_clicks"),
    # Q1 + Q3 (concerns) + Q4 (savings perception) — baseline.
    # v3.X-fix-8: the legacy "Q2_reasons" multi-select was merged into
    # drivers_top3, so survey-q2 is no longer captured here. The
    # survey_responses.q2_reasons column survives as an escape hatch
    # for the legacy /api/survey endpoint.
    State("survey-q1", "value"),
    State("survey-q3", "value"),
    State("survey-q4", "value"),
    # v3.9 new states
    State("step7-q5-trust-source", "value"),
    State("step7-q6-fairness", "value"),
    State("step7-q7-transparency", "value"),
    State("step7-entry-threshold-pct", "value"),
    State("step7-exit-threshold", "value"),
    State("step7-final-willingness", "value"),
    State("step7-expert-q1-realism", "value"),
    State("step7-expert-q2-barrier", "value"),
    State("step7-expert-q3-comment", "value"),
    State("step7-demo-age", "value"),
    State("step7-demo-gender", "value"),
    State("step7-demo-country", "value"),
    State("step7-drivers-top3", "value"),
    State("url", "search"),
    prevent_initial_call=True,
)
def submit_survey(n_clicks, q1, q3, q4,
                  q5, q6, q7,
                  entry_pct, exit_t, final_w,
                  eq1, eq2, eq3,
                  age, gender, country,
                  drivers,
                  search):
    """v3.9: writes survey_responses (upsert) + exit_thresholds (upsert) +
    willingness_measurements(round=3) + flips sessions.completed=True.

    Expert states (eq1/eq2/eq3) come back as None when the expert block
    isn't rendered (suppress_callback_exceptions=True is set globally).

    v3.X-fix-7 added drivers_top3 (E.ON Q13). v3.X-fix-8 merged the
    legacy Q2_reasons question into drivers_top3 (same semantic — "top
    reasons to join"); q2_reasons column is kept on the table for the
    /api/survey escape hatch but is no longer written here.
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
    drivers_count = len(drivers or [])
    if drivers_count < 1 or drivers_count > _DRIVERS_MAX:
        return no_update, f"Please pick between 1 and {_DRIVERS_MAX} drivers."

    from vec_platform.models import (
        Session as SessionModel,
        ExitThreshold,
        WillingnessMeasurement,
    )
    from vec_platform.pages._survey_helpers import get_or_create_survey_row

    # Cap multi-selects at 3 so "top 3" is enforced in the data.
    q3_trim = (q3 or [])[:3]
    drivers_trim = (drivers or [])[:_DRIVERS_MAX]

    db = SessionLocal()
    try:
        session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
        if session is None:
            return no_update, "Session not found. Please start from Step 1."

        # 1) survey_responses — upsert all fields onto the per-session row.
        row = get_or_create_survey_row(db, session_id)
        row.q1_willingness = q1
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
        row.drivers_top3 = json.dumps(drivers_trim)  # v3.X-fix-7 / fix-8

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

        # 4) Mark the session complete. Phase 4-A: current_step=8 means
        # "past Step 7" in the new 7-step flow (matches the historical
        # "current_step=9 = past Step 8" semantics, just shifted).
        session.completed = True
        session.current_step = 8

        db.commit()
    finally:
        db.close()

    return _thank_you_view(), ""
