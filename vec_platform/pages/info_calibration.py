"""info-calibration page — concept illustration + between-subjects framing.

Phase P-1 redesign. The page now has three sections in a fixed order:

  1. 4-panel concept illustration (line-art SVGs). All arms see the same
     four panels; this is the FIRST mechanism reveal in the journey
     (Welcome page is deliberately abstract per Phase O-fix-12).
  2. Arm-specific saving info (the between-subjects manipulation).
     Arm A — optimistic anchor ("15–20%").
     Arm B — realistic anchor ("3–7%").
     Arm C — control: explicit "varies / limited data" copy, no number.
  3. 5-point 'how likely' Likert. Phase Q-2b standardized this anchor
     across all three willingness measurement rounds (IC-Q1 / S5-Q3 /
     S7-Q1) so the rounds are directly paired in analysis. Persisted
     with scale_type='5point_likely' (was '5point_interest' in P-1,
     '7point_interest' before that).

Arm assignment is set at session creation in ``main.root`` and is read
from ``sessions.info_calibration_arm`` here — Phase P-1 does NOT touch
the randomization.

The submit-time DB write uses ``upsert_willingness`` so a participant
who navigates back and changes their answer overwrites the round=1 row
instead of accumulating duplicates.

Importing this module registers three Dash callbacks against
``dash_app``.
"""

from dash import html, dcc, no_update
from dash.dependencies import Input, Output, State
import dash_bootstrap_components as dbc

from vec_platform.runtime import dash_app, SessionLocal
from vec_platform.pages._helpers import _parse_session_id


# ==================== arm content ====================

def _arm_content(arm: str):
    """Return ``(title, body_paragraph)`` for an arm.

    Phase P-1 copy: shorter and more uniform than the pre-fix-1 prose.
    Arms A/B share the title 'What participants typically save' so the
    only visible variation is the number range; Arm C uses a neutral
    'About savings' title with no anchor figure.
    """
    if arm == "A":
        return (
            "What participants typically save",
            "Recent studies suggest households save around 15–20 % off "
            "their monthly electricity bill by joining a VEC.",
        )
    if arm == "B":
        return (
            "What participants typically save",
            "Recent studies suggest households save around 3–7 % off "
            "their monthly electricity bill by joining a VEC.",
        )
    # 'C' (control) and any unexpected value.
    return (
        "About savings",
        "Actual savings vary significantly by household and community "
        "composition. Limited public data is available.",
    )


# Phase Q-2b: standardized 'how likely' anchor — the same 5-point
# scale is used by IC-Q1 (this file), S5-Q3 (step5.py), and S7-Q1
# (step7.py) so the three willingness measurements are directly
# paired for the cross-round analysis. scale_type tag changed from
# the Phase P-1 '5point_interest' to '5point_likely'; historical
# dogfood rows keep the old tag and are filtered by scale_type
# in analysis.
_LIKERT_OPTIONS = [
    {"label": "1 — Very unlikely",      "value": 1},
    {"label": "2 — Somewhat unlikely",  "value": 2},
    {"label": "3 — Undecided",          "value": 3},
    {"label": "4 — Somewhat likely",    "value": 4},
    {"label": "5 — Very likely",        "value": 5},
]
_LIKERT_SCALE_TYPE = "5point_likely"


# Phase P-1: shared className constants — the visual rule for the
# disabled-look Next button cannot drift between the next-visual and
# submit callbacks.
_CLS_BTN_ENABLED = "mt-4"
_CLS_BTN_DISABLED = "mt-4 disabled-look"


# ==================== panel helpers ====================

# The 4-panel grid. Captions live next to the icon URL so adding /
# reordering panels is a single-edit operation. SVG URLs are resolved
# via dash_app.get_asset_url so the Dash mount prefix (/dash/) is
# applied automatically; hard-coding "/assets/..." would 404 because
# Dash actually serves them at /dash/assets/.
_PANEL_SPECS = [
    ("vec-panel-1.svg", "Households in the same area"),
    # Phase P-2: Panel 2 caption now mentions BESS (battery sharing) and
    # the timing dimension ("at the right times") — the prior copy
    # ("Some produce energy, others don't") lost the storage-shifts-in-
    # time insight that distinguishes a VEC from a pure-PV cooperative.
    ("vec-panel-2.svg",
     "Some have solar panels and batteries — they can share excess "
     "energy at the right times"),
    # Phase P-2: Panel 3 caption surfaces the dual-benefit price band
    # (internal price sits between feed-in and retail) — without this,
    # participants don't see WHY both parties might want to participate.
    ("vec-panel-3.svg",
     "Energy moves between them via the public grid — buyers pay "
     "less than retail, sellers earn more than feed-in"),
    ("vec-panel-4.svg",
     "A portion of the energy is settled internally — your contract "
     "and meter stay the same"),
]


def _build_panel(svg_filename, caption_text):
    return html.Div([
        html.Div(
            html.Img(
                src=dash_app.get_asset_url(svg_filename),
                alt=caption_text,
            ),
            className="vec-panel-icon",
        ),
        html.P(caption_text, className="vec-panel-caption"),
    ], className="vec-panel")


# ==================== layout ====================

def info_calibration_layout(session_id: str | None = None):
    """Render the concept illustration + arm-specific framing + interest Likert."""
    if not session_id:
        return html.Div([
            html.H2("Information"),
            dbc.Alert(
                "No active session — please start from '/'.",
                color="warning",
            ),
        ])

    from vec_platform.models import Session as SessionModel

    db = SessionLocal()
    try:
        sess = (
            db.query(SessionModel)
            .filter(SessionModel.id == session_id)
            .first()
        )
        arm = sess.info_calibration_arm if sess else "C"
    finally:
        db.close()

    arm_title, arm_body = _arm_content(arm)

    return html.Div([
        html.H2("A quick introduction to Virtual Energy Communities"),
        html.P(
            "Before we continue, here's how a VEC works at a high level.",
            className="text-muted mb-4",
        ),

        # 4-panel illustration. All arms see the same four panels —
        # the concept reveal is held constant; the between-subjects
        # manipulation is only the arm-specific saving block below.
        html.Div(
            [_build_panel(fname, caption) for fname, caption in _PANEL_SPECS],
            className="vec-panels-grid",
        ),

        # Arm-specific saving info. The arm-info-block class styles it
        # with a yellow left-border to distinguish it from the neutral
        # panels (without using "savings"-leading visual language in
        # the panels themselves).
        html.Div([
            html.H4(arm_title),
            html.P(arm_body),
        ], className="arm-info-block"),

        # Interest question.
        html.Div([
            html.Label(
                "IC-Q1 · Based on what you've read, how likely are you "
                "to join a VEC?",
                className="form-label fw-bold mb-3 mt-3",
            ),
            dcc.RadioItems(
                id="info-cal-likert",
                options=_LIKERT_OPTIONS,
                value=None,
                labelStyle={"display": "block", "padding": "0.2rem 0"},
            ),
            html.Div(id="info-cal-hint", className="step1-hint-text"),
        ], className="mb-4"),

        # Phase O-fix-10 disabled-look Next button — gray until the
        # Likert is picked, click-through preserved so an empty-form
        # click surfaces an inline hint rather than feeling dead.
        dbc.Button(
            "Next",
            id="info-cal-next-btn",
            color="primary",
            size="lg",
            className=_CLS_BTN_DISABLED,
            n_clicks=0,
        ),

        # Cross-mount navigation Location. The /step3 customize page is
        # served by FastAPI (outside the Dash mount), so we need a
        # refresh=True Location to trigger a full browser reload — the
        # root url Location is refresh=False for in-Dash navigation.
        dcc.Location(id="info-cal-redirect", refresh=True),
    ])


# ==================== callbacks ====================

@dash_app.callback(
    Output("info-cal-next-btn", "className"),
    Input("info-cal-likert", "value"),
)
def info_cal_next_visual(likert_value):
    """Phase P-1 / Phase O-fix-10 disabled-look toggle. Next button
    leaves disabled-look only when the participant has picked a
    Likert value (never via the HTML disabled attribute, which would
    block click-through to the submit callback's hint path)."""
    if likert_value is None:
        return _CLS_BTN_DISABLED
    return _CLS_BTN_ENABLED


# Hint-clear callback — wipes the inline hint as soon as the user
# picks a Likert option, mirroring the Phase O-fix-10 step1.py pattern.
# allow_duplicate=True is required because submit_info_cal also writes
# this Output (Dash >= 2.9 accepts the dup when prevent_initial_call=True).
@dash_app.callback(
    Output("info-cal-hint", "children", allow_duplicate=True),
    Input("info-cal-likert", "value"),
    prevent_initial_call=True,
)
def _info_cal_clear_hint(_value):
    return ""


@dash_app.callback(
    Output("info-cal-hint", "children"),
    Output("info-cal-redirect", "href"),
    Input("info-cal-next-btn", "n_clicks"),
    State("info-cal-likert", "value"),
    State("url", "search"),
    prevent_initial_call=True,
)
def submit_info_cal(n_clicks, likert_value, search):
    """Validate, persist round=1 willingness, hand off to /step3.

    Phase Q-2b: scale_type='5point_likely' (was '5point_interest' in
    P-1, '7point_interest' before that).
    Phase 4-A: destination /step3 (the static customize page) is
    outside the Dash mount, so the refresh=True info-cal-redirect
    Location is required to trigger a full browser navigation.
    """
    # Phase O-fix-13 defensive guard: prevent_initial_call=True should
    # already block n_clicks=0 firing, but a no-op early return is
    # cheap insurance against any Dash edge case.
    if not n_clicks:
        return no_update, no_update

    session_id = _parse_session_id(search)
    if not session_id:
        return "⚠ Session id missing — please start from '/'.", no_update
    if likert_value is None:
        return "⚠ Please select an option.", no_update

    from vec_platform.models import Session as SessionModel
    from vec_platform.pages._upsert_helpers import upsert_willingness

    db = SessionLocal()
    try:
        sess = (
            db.query(SessionModel)
            .filter(SessionModel.id == session_id)
            .first()
        )
        if sess is None:
            return "⚠ Session not found.", no_update
        # Phase E pattern: upsert so a Back-and-resubmit overwrites
        # the round=1 row in place rather than producing duplicates.
        upsert_willingness(
            db, session_id,
            round_=1,
            scale_type=_LIKERT_SCALE_TYPE,
            value=likert_value,
        )
        if sess.current_step is None or sess.current_step < 2:
            sess.current_step = 2
        db.commit()
    finally:
        db.close()

    return "", f"/step3?session_id={session_id}"
