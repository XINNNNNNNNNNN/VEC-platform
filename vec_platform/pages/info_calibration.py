"""Info-calibration page — between-subjects framing of expected savings.

Each session is randomly assigned to one of three arms at creation time
(see ``main.root``). The page text varies by arm; everyone answers the
same 7-point Likert about how interested they would be in joining a VEC.
The Likert response lands in ``willingness_measurements`` with round=1.

Importing this module registers two Dash callbacks against ``dash_app``.
"""

from dash import html, dcc, no_update
from dash.dependencies import Input, Output, State
import dash_bootstrap_components as dbc

from vec_platform.runtime import dash_app, SessionLocal
from vec_platform.pages._helpers import _parse_session_id


# ==================== arm content ====================

def _arm_content(arm: str):
    """Return ``(title, body_markdown, likert_question_text)`` for an arm.

    A — optimistic framing (15-20% savings cited)
    B — realistic framing (3-7% savings cited)
    C — control: no anchor figure, generic prompt
    """
    if arm == "A":
        title = "What participants typically save"
        body = (
            "Recent studies of Virtual Energy Communities suggest that, "
            "**under favourable conditions**, households can save around "
            "**15–20% off their monthly electricity bill** by joining a "
            "VEC. Communities with a good mix of solar generation and "
            "complementary demand patterns tend to see the largest "
            "benefits."
        )
        likert_q = (
            "Based on what you've just read, how interested would you "
            "be in joining a VEC?"
        )
    elif arm == "B":
        title = "What participants typically save"
        body = (
            "Recent studies of Virtual Energy Communities suggest that, "
            "**on average**, households save around **3–7% off their "
            "monthly electricity bill** by joining a VEC. Actual savings "
            "depend heavily on the household's electricity use patterns "
            "and on the mix of participants in the community."
        )
        likert_q = (
            "Based on what you've just read, how interested would you "
            "be in joining a VEC?"
        )
    else:  # 'C' (control) — also any unexpected value
        title = "Continue to the next part"
        body = (
            "You'll now see what your own electricity profile and bill "
            "would look like."
        )
        likert_q = (
            "Based on your understanding of VECs so far, how interested "
            "would you be in joining one?"
        )
    return title, body, likert_q


_LIKERT_OPTIONS = [
    {"label": "1 — Not at all interested", "value": 1},
    {"label": "2", "value": 2},
    {"label": "3", "value": 3},
    {"label": "4 — Neutral", "value": 4},
    {"label": "5", "value": 5},
    {"label": "6", "value": 6},
    {"label": "7 — Extremely interested", "value": 7},
]


# ==================== layout ====================

def _load_prior_info_cal(db, session_id: str) -> dict | None:
    """v3.X-fix-6a: rehydrate the Likert when the user revisits this page
    via Back. Returns None for fresh sessions.

    submit_info_cal writes one round=1 row per session — no upsert — so
    a re-submit would double-insert. We just read the most recent row
    here; idempotency on submit is a separate concern.
    """
    from vec_platform.models import WillingnessMeasurement
    wm = (
        db.query(WillingnessMeasurement)
        .filter(
            WillingnessMeasurement.session_id == session_id,
            WillingnessMeasurement.round == 1,
        )
        .order_by(WillingnessMeasurement.id.desc())
        .first()
    )
    return {"value": wm.value} if wm else None


def info_calibration_layout(session_id: str | None = None):
    """Render the page with text matching this session's assigned arm."""
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
        sess = db.query(SessionModel).filter(SessionModel.id == session_id).first()
        arm = sess.info_calibration_arm if sess else "C"
        # v3.X-fix-6a: piggyback the prior-Likert lookup on the same db
        # session that's already open for the arm read.
        prior = _load_prior_info_cal(db, session_id)
    finally:
        db.close()
    likert_default = prior["value"] if prior else None

    title, body, likert_q = _arm_content(arm)

    return html.Div([
        html.H2(title),

        dbc.Card([
            dbc.CardBody(dcc.Markdown(body)),
        ], className="mb-3"),

        dbc.Card([
            dbc.CardBody([
                html.H5(likert_q, className="mb-3"),
                dcc.RadioItems(
                    id="info-cal-likert",
                    options=_LIKERT_OPTIONS,
                    value=likert_default,
                    labelStyle={"display": "block"},
                ),
            ]),
        ], className="mb-3"),

        html.Div(id="info-cal-error", className="text-danger mb-2"),
        dbc.Button(
            "Next",
            id="info-cal-next-btn",
            color="primary",
            size="lg",
            disabled=True,
        ),
    ])


# ==================== callbacks ====================

@dash_app.callback(
    Output("info-cal-next-btn", "disabled"),
    Input("info-cal-likert", "value"),
)
def toggle_info_cal_next(v):
    """Lock Next until the participant picks a Likert value."""
    return v is None


@dash_app.callback(
    Output("url", "pathname", allow_duplicate=True),
    Output("url", "search", allow_duplicate=True),
    Output("info-cal-error", "children"),
    Input("info-cal-next-btn", "n_clicks"),
    State("info-cal-likert", "value"),
    State("url", "search"),
    prevent_initial_call=True,
)
def submit_info_cal(n_clicks, likert_value, search):
    """Persist the round-1 willingness measurement and hand off to Step 2."""
    if not n_clicks:
        return no_update, no_update, no_update

    session_id = _parse_session_id(search)
    if not session_id:
        return no_update, no_update, "Session id missing — please start from '/'."
    if likert_value is None:
        return no_update, no_update, "Please select an option."

    from vec_platform.models import (
        Session as SessionModel,
        WillingnessMeasurement,
    )

    db = SessionLocal()
    try:
        sess = db.query(SessionModel).filter(SessionModel.id == session_id).first()
        if sess is None:
            return no_update, no_update, "Session not found."
        db.add(WillingnessMeasurement(
            session_id=session_id,
            round=1,
            scale_type="7point_interest",
            value=int(likert_value),
        ))
        # info_calibration sits between Step 1 and Step 2; the participant
        # is now moving on to Step 2.
        if sess.current_step is None or sess.current_step < 2:
            sess.current_step = 2
        db.commit()
    finally:
        db.close()

    return "/dash/step2", f"?session_id={session_id}", ""
