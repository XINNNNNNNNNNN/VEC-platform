"""Step 0 — welcome, consent, and the first prior-expectation guess.

v3 entry point. The FastAPI ``/`` route creates the session row (with a
random info_calibration_arm assigned) and redirects here. We collect:
  * informed consent (a single mandatory checkbox);
  * the participant's first guess at the % savings they'd get from a VEC,
    written to the ``prior_expectations`` table with measurement_round=1.

Once both are done we hand off to Step 1.

Importing this module registers three Dash callbacks against ``dash_app``.
"""

from dash import html, dcc, no_update
from dash.dependencies import Input, Output, State
import dash_bootstrap_components as dbc

from vec_platform.runtime import dash_app, SessionLocal
from vec_platform.pages._helpers import _parse_session_id


# ==================== Step 0 ====================

_VEC_INTRO_MD = (
    "**Virtual Energy Community (VEC):** A group of households in the same "
    "area that pool their electricity to reduce bills together. Solar PV "
    "owners can sell their surplus to neighbours at a better price than the "
    "grid; everyone in the community can buy at a discount during certain "
    "hours. You stay with your existing electricity contract and meter — the "
    "savings come from how the community settles the energy internally."
)

_CONSENT_OPTIONS = [
    {
        "label": ("I understand and agree to participate in this study "
                  "(anonymous, ~25 minutes)."),
        "value": "agreed",
    },
]

# v3.X-fix-7 — E.ON Q9 alignment. Asked before the prior-expectation
# slider so the answer is a true baseline (no anchoring from any
# numbers shown later in the flow).
_VEC_FAMILIARITY_OPTIONS = [
    {"label": "Never heard of it",                              "value": "never_heard"},
    {"label": "Heard of it, but don't really understand it",    "value": "heard_no_understand"},
    {"label": "Somewhat familiar",                              "value": "somewhat_familiar"},
    {"label": "Very familiar",                                  "value": "very_familiar"},
    {"label": "Have participated in a similar initiative",      "value": "have_participated"},
]

_SLIDER_MARKS = {p: f"{p}%" for p in (0, 10, 20, 30, 40, 50)}


def step0_layout(session_id: str | None = None):
    session_note = (
        dbc.Alert(f"Session: {session_id}", color="light", className="py-2 small")
        if session_id else
        dbc.Alert(
            "No active session — open the site from '/' to create one.",
            color="warning", className="py-2 small",
        )
    )

    return html.Div([
        html.H2("Welcome"),
        html.P(
            "We're studying how households would interact with a virtual "
            "energy community. Before we show you any numbers, we'd like "
            "your gut feeling about how much you might save."
        ),

        session_note,

        # VEC intro
        dbc.Card([
            dbc.CardBody(dcc.Markdown(_VEC_INTRO_MD)),
        ], className="mb-3"),

        # Consent
        dbc.Card([
            dbc.CardBody([
                html.H5("Consent"),
                dbc.Checklist(
                    id="step0-consent",
                    options=_CONSENT_OPTIONS,
                    value=[],
                ),
            ]),
        ], className="mb-3"),

        # v3.X-fix-7 — E.ON Q9 baseline familiarity (must precede the
        # expectation slider so it captures pre-exposure knowledge).
        dbc.Card([
            dbc.CardBody([
                html.H5("Before we start: how familiar are you with this concept?"),
                html.P(
                    "Virtual energy sharing means electricity is shared via the "
                    "existing grid through agreements between buyers and sellers, "
                    "not through new cables. The electricity is transported as "
                    "usual in the grid and the benefits are shared between "
                    "participants.",
                    className="text-muted small",
                ),
                dcc.RadioItems(
                    id="step0-vec-familiarity",
                    options=_VEC_FAMILIARITY_OPTIONS,
                    value=None,
                    labelStyle={"display": "block", "padding": "0.2rem 0"},
                ),
            ]),
        ], className="mb-3"),

        # First expectation
        dbc.Card([
            dbc.CardBody([
                html.H5(
                    "Before seeing any data, what % of your monthly "
                    "electricity bill do you expect to save by joining "
                    "a VEC?"
                ),
                dcc.Slider(
                    id="step0-expectation-pct",
                    min=0, max=50, step=1, value=0,
                    marks=_SLIDER_MARKS,
                    tooltip={"placement": "bottom", "always_visible": False},
                ),
                html.Div(
                    "0%",
                    id="step0-expectation-display",
                    className="text-center fs-4 fw-bold mt-3",
                ),
            ]),
        ], className="mb-3"),

        html.Hr(),
        html.Div(id="step0-error", className="text-danger mb-2"),
        dbc.Button(
            "Next",
            id="step0-next-btn",
            color="primary",
            size="lg",
            disabled=True,
            className="mt-2",
        ),
    ])


# ----- callbacks (registered against runtime.dash_app on import) -----

@dash_app.callback(
    Output("step0-expectation-display", "children"),
    Input("step0-expectation-pct", "value"),
)
def update_expectation_display(pct):
    """Live-render the slider value below the slider."""
    return f"{pct}%"


@dash_app.callback(
    Output("step0-next-btn", "disabled"),
    Input("step0-consent", "value"),
    Input("step0-vec-familiarity", "value"),
)
def toggle_next_button(consent_values, vec_familiarity):
    """Lock Next until both the consent checkbox is ticked AND the
    familiarity radio (v3.X-fix-7) has been answered."""
    if "agreed" not in (consent_values or []):
        return True
    if vec_familiarity is None:
        return True
    return False


@dash_app.callback(
    # Phase 3.X-fix-12: declare allow_duplicate so the four callbacks
    # that drive the root <Location id="url"> (step0/step1/info_cal/
    # tenant_disclaimer) coexist cleanly. Without this, Dash's strict
    # duplicate-Output detection silently dropped the step1 dispatch
    # when its State("occupation", "value") referenced a hidden widget
    # (fix-10 conditional render), leaving Next "stuck" for participants
    # below the familiarity gate. info_calibration / tenant_disclaimer
    # already used this pattern.
    Output("url", "pathname", allow_duplicate=True),
    Output("url", "search", allow_duplicate=True),
    Output("step0-error", "children"),
    Input("step0-next-btn", "n_clicks"),
    State("step0-expectation-pct", "value"),
    State("step0-vec-familiarity", "value"),
    State("url", "search"),
    prevent_initial_call=True,
)
def submit_step0(n_clicks, pct, vec_familiarity, search):
    """Persist the first prior-expectation row, stamp sessions.vec_familiarity
    (v3.X-fix-7), and hand off to Step 1.

    Outputs to the existing root-level ``dcc.Location id='url'`` rather
    than a Step-0-private one — same pattern as ``submit_step1``.
    """
    if not n_clicks:
        return no_update, no_update, no_update

    session_id = _parse_session_id(search)
    if not session_id:
        return no_update, no_update, "Session id missing — please start from '/'."

    # v3.X-fix-7: defensive validation. The Next button is gated until
    # vec_familiarity is set, but a synthetic click could bypass it.
    if vec_familiarity is None:
        return no_update, no_update, "Please answer the familiarity question."

    from vec_platform.models import (
        Session as SessionModel,
        PriorExpectation,
    )

    db = SessionLocal()
    try:
        sess = db.query(SessionModel).filter(SessionModel.id == session_id).first()
        if sess is None:
            return no_update, no_update, "Session not found — please start from '/'."

        sess.vec_familiarity = vec_familiarity
        db.add(PriorExpectation(
            session_id=session_id,
            measurement_round=1,
            pct=float(pct),
        ))
        # Advance the bookkeeping cursor to Step 1 (the user is moving off
        # Step 0). Idempotent: don't go backwards if it's already further.
        if sess.current_step is None or sess.current_step < 1:
            sess.current_step = 1
        db.commit()
    finally:
        db.close()

    return "/dash/step1", f"?session_id={session_id}", ""
