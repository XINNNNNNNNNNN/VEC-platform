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
willingness_measurements(round=3, scale_type='5point_likely') row.
(Phase Q-2b standardized the anchor and expanded 4-point → 5-point.)

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

# Phase Q-3c: S7-Q4 upgraded from single-select trust source to 5
# independent 5-Likert ratings. The 5 targets cover the realistic
# range of VEC organizers in Sweden (Ei policy reference: Ellevio,
# E.ON; cooperative model: andelsförening; private tech: Tibber/
# Greenely; grid operator: Svenska Kraftnät). Each rating is 1=No
# trust .. 5=Complete trust. Persisted to 5 separate Integer columns
# on survey_responses; SEM latent trust analysis fits a 1-factor
# model across the 5 indicators.
_TRUST_TARGETS = [
    ("municipality", "The local municipality"),
    ("coop", "A community cooperative"),
    ("utility", "Your current electricity utility"),
    ("private", "A private tech platform (e.g., a startup)"),
    ("grid", "The national grid operator"),
]
_TRUST_LIKERT_OPTIONS = [
    {"label": "1", "value": 1},
    {"label": "2", "value": 2},
    {"label": "3", "value": 3},
    {"label": "4", "value": 4},
    {"label": "5", "value": 5},
]

_Q6_OPTIONS = [
    {"label": "Equally — everyone gets the same share", "value": "equal"},
    {"label": "Proportional — those who contribute more get more",
     "value": "proportional"},
    {"label": "Need-based — those with lower incomes get more", "value": "needs"},
    {"label": "I'm not sure", "value": "unsure"},
]

# Phase Q-3c: S7-Q6 reshaped from single-Likert transparency to
# multi-select data sovereignty. The 6 options cover the realistic
# set of data operations a VEC member might want (GDPR rights +
# pragmatic queries). Persisted as JSON list on
# survey_responses.data_control_prefs. The trailing "no_detailed"
# option provides a clean opt-out for participants who don't care
# about granular control — selecting it together with other options
# is ambiguous but accepted (analytics filter for "no_detailed" only
# as the singleton "I don't care" group).
_DATA_CONTROL_OPTIONS = [
    {"label": "See my own household's usage anytime", "value": "own_usage"},
    {"label": "See aggregated community data", "value": "agg_community"},
    {"label": "See others (anonymized)", "value": "anon_others"},
    {"label": "Decide what data is shared", "value": "decide_share"},
    {"label": "Delete data anytime", "value": "delete_anytime"},
    {"label": "I don't need detailed control", "value": "no_detailed"},
]

_EXIT_OPTIONS = [
    {"label": "Savings drop to 75% of my expectation — I'd consider leaving", "value": 0.75},
    {"label": "Drop to 50%", "value": 0.50},
    {"label": "Drop to 25%", "value": 0.25},
    {"label": "Drop to 0% (no savings at all)", "value": 0.0},
    {"label": "I would not leave even if savings were zero", "value": -1.0},
]

# Phase Q-2b: standardized 5-point 'how likely' anchor. Replaces the
# Phase 3.9 4-point reversed-order set ({4:definitely join, 3:probably
# join, 2:probably not, 1:definitely not}). Three changes:
#   1. Range expands 1..4 → 1..5 (adds 'Undecided' midpoint).
#   2. Value semantics flip: 1 is now LEAST likely (was 'definitely not'
#      = 1 already, so 1 stays the lowest endpoint), 5 is now MOST
#      likely (was 'definitely join' = 4).
#   3. scale_type at write-time changes from '4point_accept' to
#      '5point_likely' so analysis can distinguish historical dogfood
#      rows (which were written under the 4-point scheme) from
#      pilot-era rows under the new uniform scheme.
# Anchors are identical to IC-Q1 (info_calibration.py) and S5-Q3
# (step5.py) — the three rounds are now directly paired in analysis.
_FINAL_WILLINGNESS_OPTIONS = [
    {"label": "1 — Very unlikely",      "value": 1},
    {"label": "2 — Somewhat unlikely",  "value": 2},
    {"label": "3 — Undecided",          "value": 3},
    {"label": "4 — Somewhat likely",    "value": 4},
    {"label": "5 — Very likely",        "value": 5},
]

# Phase Q-2d: S7-Q8 Final Decision Confidence. Pair with S0-Q3
# (Welcome state_2) for ΔConfidence analysis. Anchor labels match
# S0-Q3 by design — Q-2a's _DECISION_CONFIDENCE_OPTIONS in step0.py
# uses the same five labels. We duplicate them here rather than
# cross-import because each page file stays self-contained, and the
# label set is short + stable.
_S7_Q8_OPTIONS = [
    {"label": "1 — Very unsure", "value": 1},
    {"label": "2 — Somewhat unsure", "value": 2},
    {"label": "3 — Moderately sure", "value": 3},
    {"label": "4 — Quite sure", "value": 4},
    {"label": "5 — Very sure", "value": 5},
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


def _survey_form(session_id: str) -> html.Div:
    """Full survey form. All participants see the same questions —
    Q-1b removed the v3.X-fix-9 expert block (3 questions on realism
    / barrier / free-text comment); Q-1c removed the
    _EXPERT_FAMILIARITY_GATE constant and the corresponding
    occupation-question gating in step1.py. RQ7 expert-vs-lay analysis
    is now fully post-hoc, using composite_expertise_z =
    z(vec_familiarity) + z(occupation) computed from existing
    items. (Phase Q-1d-revised cancelled the originally-planned quiz
    component; expertise is now defined from these two self-report
    signals only.)"""

    return html.Div(id="step7-form", children=[
        # ----- Q1-Q3 baseline (v3.X-fix-8: original Q2 was merged into
        # drivers_top3 below, so this block is now Q1 / Q2 (concerns) /
        # Q3 (savings perception). The "top reasons" question lives in
        # the drivers_top3 card further down.) -----
        html.H5("S7-Q1 · After everything you've seen, how likely are "
                "you to actually join a VEC like this?"),
        dbc.RadioItems(id="survey-q1", options=_Q1_OPTIONS, value=None, className="mb-4"),

        html.H5("S7-Q2 · What would worry you the most? (pick up to 3)"),
        dbc.Checklist(id="survey-q3", options=_Q3_OPTIONS, value=[], className="mb-4"),

        html.H5("S7-Q3 · Looking at the savings you saw in Step 5…"),
        dbc.RadioItems(id="survey-q4", options=_Q4_OPTIONS, value=None, className="mb-3"),

        # ----- Q5 / Q6 / Q7 (v3.9) -----
        html.Hr(),
        # ----- S7-Q4 5-rating trust battery (Phase Q-3c) -----
        dbc.Card(dbc.CardBody([
            html.H4(
                "S7-Q4 · How much would you trust each of the "
                "following to manage a VEC in your area? Rate each "
                "1-5 (1=No trust, 5=Complete trust)."
            ),
            *[
                html.Div([
                    html.Label(label, className="form-label fw-bold mb-1 mt-2"),
                    dcc.RadioItems(
                        id=f"step7-trust-{key}",
                        options=_TRUST_LIKERT_OPTIONS,
                        value=None,
                        inline=True,
                        labelStyle={"padding": "0.2rem 0.8rem 0.2rem 0"},
                    ),
                ], className="mb-2")
                for key, label in _TRUST_TARGETS
            ],
        ]), className="mb-3"),
        _radio_card(
            "S7-Q5 · If everyone in the VEC contributes differently (some have "
            "solar, some don't), how should the savings be split?",
            "step7-q6-fairness", _Q6_OPTIONS,
        ),
        # ----- S7-Q6 data control multi-select (Phase Q-3c) -----
        dbc.Card(dbc.CardBody([
            html.H4(
                "S7-Q6 · Which of these would you want to be ABLE to "
                "do? (select all that apply)"
            ),
            dbc.Checklist(
                id="step7-q6-data-control",
                options=_DATA_CONTROL_OPTIONS,
                value=[],
                labelStyle={"display": "block", "padding": "0.3rem 0"},
            ),
        ]), className="mb-3"),

        # ----- S7-Q7 entry threshold slider (Phase Q-2c) -----
        # Hidden-until-drag pattern mirrors S0-Q2 on Welcome state_2:
        # the display Div starts empty and the touched Store stays
        # False until the participant interacts with the slider. The
        # Submit-gate callback below treats a False touched flag the
        # same as a missing required answer, so a default-0 slider
        # cannot accidentally be submitted as "I'd join with no
        # savings" — which would alias with the lowest legitimate
        # answer (0 % threshold means "I'd join even with no savings").
        dbc.Card(dbc.CardBody([
            html.H4(
                "S7-Q7 · After everything you've seen, what minimum "
                "monthly saving (as % of your electricity bill) would "
                "you require to join a VEC?"
            ),
            dcc.Slider(
                id="step7-entry-threshold-pct",
                min=0, max=50, step=1, value=0,
                marks={p: f"{p}%" for p in (0, 10, 20, 30, 40, 50)},
                tooltip={"placement": "bottom", "always_visible": False},
            ),
            html.Div(
                "",
                id="step7-entry-threshold-display",
                className="text-center fs-4 fw-bold mt-2",
            ),
            html.Small(
                "↓ Move the slider to set your threshold",
                id="step7-entry-threshold-placeholder",
                className="text-muted d-block text-center fs-6",
            ),
            # Touched flag: False at session start, flips True on first
            # slider input. Lifecycle is the same as the Welcome
            # state_2 threshold store — never goes back to False.
            dcc.Store(id="step7-entry-threshold-touched-store", data=False),
        ]), className="mb-3"),

        # ----- S7-Q8 Final Decision Confidence (Phase Q-2d) -----
        # Mirror of S0-Q3 on Welcome state_2. Same 5-Likert anchor;
        # different question stem (this one explicitly fights social
        # desirability with the "not just what sounds reasonable"
        # clause). Pairs with user_inputs.entry_threshold_decision_confidence
        # via session_id for ΔConfidence = S7-Q8 - S0-Q3.
        dbc.Card(dbc.CardBody([
            html.H4(
                "S7-Q8 · How sure are you that the % threshold you "
                "just gave is the level you would actually require — "
                "not just what sounds reasonable?"
            ),
            dcc.RadioItems(
                id="step7-q8-entry-confidence",
                options=_S7_Q8_OPTIONS,
                value=None,
                labelStyle={"display": "block", "padding": "0.3rem 0"},
            ),
        ]), className="mb-3"),

        # ----- exit threshold -----
        _radio_card(
            "S7-Q9 · Imagine you joined a VEC and during the first months your "
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

        # ----- v3.X-fix-7 / fix-8: E.ON Q13 drivers top-3 (also serves
        # as the merged Q2_reasons question) -----
        html.Hr(),
        dbc.Card(dbc.CardBody([
            html.H4(
                f"S7-Q12 · What would be your top reasons to join a VEC like "
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
        html.H3("S7-Q13 · A few questions about you", className="mt-4 mb-3"),
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

    return html.Div([
        html.H2("Step 7: Your decision"),
        html.P(
            "One last thing. After seeing how a VEC could change your bill, "
            "your daily schedule, and your footprint — how do you actually "
            "feel about joining?"
        ),
        html.Div(
            _survey_form(session_id),
            id="step7-content",
        ),
    ])


# ==================== callbacks ====================

@dash_app.callback(
    Output("step7-entry-threshold-display", "children"),
    Output("step7-entry-threshold-touched-store", "data"),
    Output("step7-entry-threshold-placeholder", "style"),
    Input("step7-entry-threshold-pct", "value"),
    prevent_initial_call=True,
)
def update_step7_entry_threshold_display(pct):
    """Phase Q-2c hidden-until-drag for S7-Q7. prevent_initial_call=True
    is what makes the display start blank — the callback doesn't fire
    on initial layout render. After the first slider interaction the
    display fills, the touched store flips to True, and the placeholder
    text is hidden via inline style override."""
    return f"{pct}%", True, {"display": "none"}


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
    Input("step7-trust-municipality", "value"),
    Input("step7-trust-coop", "value"),
    Input("step7-trust-utility", "value"),
    Input("step7-trust-private", "value"),
    Input("step7-trust-grid", "value"),
    Input("step7-q6-fairness", "value"),
    Input("step7-q6-data-control", "value"),
    Input("step7-entry-threshold-touched-store", "data"),
    Input("step7-q8-entry-confidence", "value"),
    Input("step7-exit-threshold", "value"),
    Input("step7-final-willingness", "value"),
    Input("step7-demo-age", "value"),
    Input("step7-demo-gender", "value"),
    Input("step7-drivers-top3", "value"),
)
def toggle_step7_submit(q1, q4,
                       t_muni, t_coop, t_util, t_priv, t_grid,
                       q6_fair, data_control,
                       entry_touched, q8_conf,
                       exit_t, final_w, age, gender, drivers):
    """Lock Submit until every required question has a value.

    Required: Q1, Q4, Q5, Q6, Q7, S7-Q7 entry threshold (must be
    *touched*, not just present), exit threshold, final willingness,
    age, gender. drivers_top3 must be 1.._DRIVERS_MAX picks.

    Phase Q-2c: S7-Q7 was previously "default 0 counts as answered"
    — but a default 0 means "I'd join even with no savings", which
    is a legitimate answer the participant might actually want to
    give. Conflating these two with the slider's HTML default
    polluted the data. Switching to a touched-flag gate makes the
    answer space unambiguous: every persisted entry_threshold_pct
    is a deliberate user input.

    NOT required:
      - Q2/Q3 multi-select (empty list is acceptable, matches v3 baseline)
      - country dropdown (default 'SE' counts as answered)
    """
    # Phase Q-3c: 5 trust ratings + data_control multi-select replace
    # the old q5/q7 single answers. All 5 trust ratings required
    # (SEM latent trust orientation needs the full battery); data
    # control multi-select requires at least 1 pick (otherwise the
    # answer is indistinguishable from "didn't read the question").
    required = [q1, q4, q6_fair, exit_t, final_w, age, gender,
                t_muni, t_coop, t_util, t_priv, t_grid]
    if any(v is None for v in required):
        return True
    if not entry_touched:
        return True
    if q8_conf is None:
        return True
    if not data_control:
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
    # Phase Q-3c — 5 trust ratings replace q5_trust_source.
    State("step7-trust-municipality", "value"),
    State("step7-trust-coop", "value"),
    State("step7-trust-utility", "value"),
    State("step7-trust-private", "value"),
    State("step7-trust-grid", "value"),
    State("step7-q6-fairness", "value"),
    # Phase Q-3c — data_control multi-select replaces q7_transparency_pref.
    State("step7-q6-data-control", "value"),
    State("step7-entry-threshold-pct", "value"),
    State("step7-entry-threshold-touched-store", "data"),
    State("step7-q8-entry-confidence", "value"),
    State("step7-exit-threshold", "value"),
    State("step7-final-willingness", "value"),
    State("step7-demo-age", "value"),
    State("step7-demo-gender", "value"),
    State("step7-demo-country", "value"),
    State("step7-drivers-top3", "value"),
    State("url", "search"),
    prevent_initial_call=True,
)
def submit_survey(n_clicks, q1, q3, q4,
                  t_muni, t_coop, t_util, t_priv, t_grid,
                  q6_fair, data_control,
                  entry_pct, entry_touched, q8_conf, exit_t, final_w,
                  age, gender, country,
                  drivers,
                  search):
    """v3.9: writes survey_responses (upsert) + exit_thresholds (upsert) +
    willingness_measurements(round=3) + flips sessions.completed=True.

    Phase Q-1b: expert block (eq1/eq2/eq3) removed — all participants
    answer the same questions.

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
    # Phase Q-3c: full validation including 5 trust ratings + data control.
    required = [q1, q4, q6_fair, exit_t, final_w, age, gender,
                t_muni, t_coop, t_util, t_priv, t_grid]
    if any(v is None for v in required):
        return no_update, "Please answer all required questions."
    if not entry_touched:
        return no_update, "Please move the entry-threshold slider to set your minimum saving requirement."
    if q8_conf is None:
        return no_update, "Please answer S7-Q8 — how sure you are about the threshold you just set."
    if not data_control:
        return no_update, "Please select at least one data-control option for S7-Q6."
    drivers_count = len(drivers or [])
    if drivers_count < 1 or drivers_count > _DRIVERS_MAX:
        return no_update, f"Please pick between 1 and {_DRIVERS_MAX} drivers."

    from vec_platform.models import (
        Session as SessionModel,
        ExitThreshold,
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
        # Phase Q-3c: 5 trust ratings replace q5_trust_source; data
        # control multi-select replaces q7_transparency_pref. Both
        # are persisted on the same survey_responses row.
        row.trust_municipality = int(t_muni)
        row.trust_coop = int(t_coop)
        row.trust_utility = int(t_util)
        row.trust_private = int(t_priv)
        row.trust_grid = int(t_grid)
        row.q6_fairness_pref = q6_fair
        # data_control_prefs stored as JSON list (same pattern as
        # q3_concerns / drivers_top3).
        row.data_control_prefs = json.dumps(list(data_control or []))
        row.demo_age_range = age
        row.demo_gender = gender
        row.demo_country = country or "SE"
        row.drivers_top3 = json.dumps(drivers_trim)  # v3.X-fix-7 / fix-8

        # 2) exit_thresholds — single row per session (upsert pattern).
        # Phase Q-2d: write entry_threshold_decision_confidence on the
        # same row that already carries entry_threshold_pct (S7-Q7) and
        # threshold_ratio (S7-Q9). Single-row design keeps the per-
        # session threshold/confidence triplet atomic for analysis.
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
        et.entry_threshold_decision_confidence = int(q8_conf)

        # 3) willingness_measurements round=3. Phase E: switched from
        # defensive-idempotency to an explicit upsert so a participant
        # who edits the survey after submitting (or whose double-click
        # races) sees their latest final-acceptance Likert recorded
        # instead of the first one being kept and the new one dropped.
        # Phase Q-2b: scale_type standardized to '5point_likely' and
        # value range expanded 1..4 → 1..5 to match the new ascending
        # 5-point anchor (see _FINAL_WILLINGNESS_OPTIONS).
        from vec_platform.pages._upsert_helpers import upsert_willingness
        upsert_willingness(
            db, session_id,
            round_=3,
            scale_type="5point_likely",
            value=final_w,
        )

        # 4) Mark the session complete. Phase 4-A: current_step=8 means
        # "past Step 7" in the new 7-step flow (matches the historical
        # "current_step=9 = past Step 8" semantics, just shifted).
        session.completed = True
        session.current_step = 8

        db.commit()
    finally:
        db.close()

    return _thank_you_view(), ""
