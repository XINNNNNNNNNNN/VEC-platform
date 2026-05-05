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


def _load_prior_step1(db, session_id: str) -> dict | None:
    """v3.X-fix-6a: rehydrate the form when the user revisits Step 1 via
    Back. Returns ``None`` for fresh sessions so the layout falls back to
    its first-time defaults (area=75, people=2, everything else empty).

    submit_step1 currently inserts a new UserInput row each time rather
    than upserting, so we order by id desc and pick the latest row — the
    user's most recent answers win on revisit. (Cleaning up the duplicate-
    insert is a separate concern; here we just need to surface the right
    one in the form.)
    """
    from vec_platform.models import UserInput
    ui = (
        db.query(UserInput)
        .filter(UserInput.session_id == session_id)
        .order_by(UserInput.id.desc())
        .first()
    )
    if ui is None:
        return None
    der = []
    if ui.has_pv:   der.append("pv")
    if ui.has_bess: der.append("bess")
    if ui.has_ev:   der.append("ev")
    return {
        "ownership_type": ui.ownership_type,
        "der_options":    der,
        "area_m2":        ui.area_m2,
        "people":         ui.people,
        "occupation":     ui.occupation,
    }


def step1_layout(session_id: str | None = None):
    session_note = (
        dbc.Alert(f"Session: {session_id}", color="light", className="py-2 small")
        if session_id else
        dbc.Alert("No active session — open the site from '/' to create one.",
                  color="warning", className="py-2 small")
    )

    # v3.X-fix-6a: hydrate from any previous Step 1 submission. pv_kwp /
    # bess_kwh aren't surfaced in the form (submit_step1 derives defaults
    # from has_pv / has_bess) so we don't restore those.
    prior = None
    if session_id:
        db = SessionLocal()
        try:
            prior = _load_prior_step1(db, session_id)
        finally:
            db.close()
    pv_owner_default = prior["ownership_type"] if prior else None
    der_default      = prior["der_options"]    if prior else []
    area_default     = int(prior["area_m2"])   if prior else 75
    people_default   = prior["people"]         if prior else 2
    occ_default      = prior["occupation"]     if prior else None

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
                    value=pv_owner_default,
                    className="mb-4",
                ),

                # Q2: DER (multi-select, may be empty)
                html.H5("Q2 · Which of these do you have at home? "
                        "(select all that apply)"),
                dbc.Checklist(
                    id="der-options",
                    options=_DER_OPTIONS,
                    value=der_default,
                    className="mb-4",
                ),

                # Q3: Area
                html.H5("Q3 · Approximate floor area of your home (m²)"),
                dbc.Row([
                    dbc.Col(
                        dbc.Input(id="area", type="number", value=area_default, min=30, max=300),
                        width=4,
                    ),
                ], className="mb-4"),

                # Q4: People
                html.H5("Q4 · Number of people living in your home"),
                dbc.Row([
                    dbc.Col(
                        dbc.Input(id="people", type="number", value=people_default, min=1, max=6),
                        width=4,
                    ),
                ], className="mb-4"),

                # Q5: Occupation (drives sessions.expertise)
                html.H5("Q5 · Which best describes your background?"),
                dbc.RadioItems(
                    id="occupation",
                    options=_OCCUPATION_OPTIONS,
                    value=occ_default,
                    className="mb-3",
                ),

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

    if (not ownership_type or area is None or people is None or not occupation):
        return no_update, no_update, "Please answer all questions before continuing."

    from vec_platform.models import Session as SessionModel, UserInput

    session_id = _parse_session_id(search)
    der = der_options or []
    has_pv = "pv" in der
    has_bess = "bess" in der
    has_ev = "ev" in der
    expertise = "expert" if occupation == "energy_professional" else "general"

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

        # v3: drives Step 8's expert-only follow-ups.
        session.expertise = expertise
        session.current_step = 2
        # session.role kept for backward-compat but no longer written here —
        # building_type is gone, and nothing in the codebase reads .role.

        user_input = UserInput(
            session_id=session_id,
            ownership_type=ownership_type,
            occupation=occupation,
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
