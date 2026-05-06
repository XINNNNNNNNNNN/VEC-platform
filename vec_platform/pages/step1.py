"""Step 1 — household profile form + submit callback (v3.0).

Five questions:
  Q1  ownership type        (tenant / owner)
  Q2  DER multi-select      (PV / BESS / EV)
  Q3  area                  (m²)
  Q4  people                (count)
  Q5  occupation            (energy professional / general public)

The legacy v2 questions (4-choice building_type, 3-choice heating) are gone.
MockEngine derives an internal building_type code from ownership + DER, so
the engine still drives the right base-load amplitude.

Importing this module registers the Dash callback against ``dash_app``.
"""

import uuid

from dash import html, no_update
from dash.dependencies import Input, Output, State
import dash_bootstrap_components as dbc

from vec_platform.runtime import dash_app, SessionLocal, calculation_engine
from vec_platform.pages._helpers import _parse_session_id
# Phase 3.X-fix-10: share the same vec_familiarity threshold step8 uses to
# gate the expert block, so the "are you in the high-familiarity subset?"
# decision lives in exactly one place. step1 hides Q5 (occupation) when
# the user is *below* the gate; step8 shows the expert block when the
# user is *at or above* the gate. Both must pivot on identical values.
from vec_platform.pages.step8 import _EXPERT_FAMILIARITY_GATE


# ==================== Step 1 ====================

_OWNERSHIP_OPTIONS = [
    {"label": "Tenant (rent)", "value": "tenant"},
    {"label": "Owner", "value": "owner"},
]

_DER_OPTIONS = [
    {"label": "Solar PV", "value": "pv"},
    {"label": "Battery storage (BESS)", "value": "bess"},
    {"label": "Electric vehicle (EV)", "value": "ev"},
]

_OCCUPATION_OPTIONS = [
    {
        "label": (
            "Energy-related researcher or professional "
            "(works/studies in energy industry, utilities, energy research, "
            "or energy policy)"
        ),
        "value": "energy_professional",
    },
    {"label": "Other (general public)", "value": "general_public"},
]


def step1_layout(session_id: str | None = None):
    session_note = (
        dbc.Alert(f"Session: {session_id}", color="light", className="py-2 small")
        if session_id else
        dbc.Alert("No active session — open the site from '/' to create one.",
                  color="warning", className="py-2 small")
    )

    # Phase 3.X-fix-10: Q5 (occupation / "energy professional?") is only
    # asked of participants whose Step 0 vec_familiarity is in the top 2
    # of the 5-pt scale. Users below the gate are extremely unlikely to
    # be energy professionals, so the question is information-redundant
    # for them — and hiding it removes a small surface for the demand
    # effect. The high-familiarity subset is still asked, preserving the
    # backward-compat comparison with the legacy expertise self-label.
    show_occupation = False
    if session_id:
        from vec_platform.models import Session as SessionModel
        db = SessionLocal()
        try:
            sess = db.query(SessionModel).filter(SessionModel.id == session_id).first()
            vec_fam = sess.vec_familiarity if sess else None
        finally:
            db.close()
        show_occupation = vec_fam in _EXPERT_FAMILIARITY_GATE

    occupation_block = []
    if show_occupation:
        occupation_block = [
            # Q5: Occupation (drives sessions.expertise; conditionally
            # rendered post fix-10).
            html.H5("Q5 · Which best describes your background?"),
            dbc.RadioItems(
                id="occupation",
                options=_OCCUPATION_OPTIONS,
                value=None,
                className="mb-3",
            ),
        ]

    return html.Div([
        html.H2("Step 1: Tell us about your home"),
        html.P("A few quick questions so we can build your typical electricity day."),

        session_note,

        dbc.Card([
            dbc.CardBody([
                # Q1: Ownership type
                html.H5("Q1 · Are you a tenant or an owner?"),
                dbc.RadioItems(
                    id="ownership-type",
                    options=_OWNERSHIP_OPTIONS,
                    value=None,
                    className="mb-4",
                ),

                # Q2: DER (multi-select, may be empty)
                html.H5("Q2 · Which of these do you have at home? "
                        "(select all that apply)"),
                dbc.Checklist(
                    id="der-options",
                    options=_DER_OPTIONS,
                    value=[],
                    className="mb-4",
                ),

                # Q3: Area
                html.H5("Q3 · Approximate floor area of your home (m²)"),
                dbc.Row([
                    dbc.Col(
                        dbc.Input(id="area", type="number", value=75, min=30, max=300),
                        width=4,
                    ),
                ], className="mb-4"),

                # Q4: People
                html.H5("Q4 · Number of people living in your home"),
                dbc.Row([
                    dbc.Col(
                        dbc.Input(id="people", type="number", value=2, min=1, max=6),
                        width=4,
                    ),
                ], className="mb-4"),

                *occupation_block,

                html.Hr(),
                html.Div(id="step1-error", className="text-danger mb-2"),
                dbc.Button("Next → Generate my profile", id="btn-next-step1",
                          color="primary", size="lg", className="mt-2"),
            ])
        ]),
    ])


# ==================== Step 1 submit callback ====================
# Default sizing for derived DER properties — keeps the v2 MockEngine
# behaviour (5 kWp PV ≈ 3 kW noon peak, 10 kWh battery).
_DEFAULT_PV_KWP = 5.0
_DEFAULT_BESS_KWH = 10.0
_SCENARIOS = ("no_vec", "vec_no_adjust", "vec_adjusted")


@dash_app.callback(
    Output("url", "pathname"),
    Output("url", "search"),
    Output("step1-error", "children"),
    Input("btn-next-step1", "n_clicks"),
    State("ownership-type", "value"),
    State("der-options", "value"),
    State("area", "value"),
    State("people", "value"),
    State("occupation", "value"),
    State("url", "search"),
    prevent_initial_call=True,
)
def submit_step1(n_clicks, ownership_type, der_options, area, people,
                 occupation, search):
    if not n_clicks:
        return no_update, no_update, no_update

    from vec_platform.models import Session as SessionModel, UserInput

    # Phase 3.X-fix-10: occupation is only required when the Q5 widget is
    # actually rendered. The widget is conditionally rendered on a
    # vec_familiarity threshold; for users below the gate the State ref
    # comes back as None (suppress_callback_exceptions=True), and that's
    # a legitimate "not asked" — not a missing answer.
    session_id = _parse_session_id(search)
    occupation_required = False
    if session_id:
        _db = SessionLocal()
        try:
            _sess = _db.query(SessionModel).filter(SessionModel.id == session_id).first()
            occupation_required = (
                _sess is not None
                and _sess.vec_familiarity in _EXPERT_FAMILIARITY_GATE
            )
        finally:
            _db.close()

    missing_required = (
        not ownership_type
        or area is None
        or people is None
        or (occupation_required and not occupation)
    )
    if missing_required:
        return no_update, no_update, "Please answer all questions before continuing."

    der = der_options or []
    has_pv = "pv" in der
    has_bess = "bess" in der
    has_ev = "ev" in der
    # fix-10: derive expertise only when occupation was actually asked.
    # When the question was hidden (low vec_familiarity), expertise stays
    # NULL on the session row to mirror the "not asked" data semantics.
    if occupation == "energy_professional":
        expertise = "expert"
    elif occupation == "general_public":
        expertise = "general"
    else:
        expertise = None  # widget hidden or never answered

    db = SessionLocal()
    try:
        if session_id:
            session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
        else:
            session = None

        if session is None:
            session_id = str(uuid.uuid4())
            session = SessionModel(id=session_id, current_step=1)
            db.add(session)
            db.flush()

        # v3: drives Step 8's expert-only follow-ups (fix-9 actually moved
        # that gate to vec_familiarity; expertise stays for backward-
        # compat analysis).
        if expertise is not None:
            session.expertise = expertise
        # else: leave existing value (None for fresh sessions; whatever
        # was there for a re-submit). Don't overwrite with None.
        session.current_step = 2

        user_input = UserInput(
            session_id=session_id,
            ownership_type=ownership_type,
            occupation=occupation,  # may be None when Q5 was hidden (fix-10)
            area_m2=float(area),
            people=int(people),
            has_pv=has_pv,
            pv_kwp=_DEFAULT_PV_KWP if has_pv else None,
            has_bess=has_bess,
            bess_kwh=_DEFAULT_BESS_KWH if has_bess else None,
            has_ev=has_ev,
        )
        db.add(user_input)
        db.flush()

        profile = calculation_engine.generate_profile(user_input)
        db.add(profile)
        db.flush()

        for scenario in _SCENARIOS:
            db.add(calculation_engine.calculate_bill(profile, scenario))

        db.commit()
    finally:
        db.close()

    # v3.2b: route through the tenant disclaimer (renters only) or
    # straight to the info-calibration page (owners). Both pages
    # eventually hand off to /dash/step2.
    if ownership_type == "tenant":
        next_path = "/dash/tenant_disclaimer"
    else:
        next_path = "/dash/info_calibration"
    return next_path, f"?session_id={session_id}", ""
