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


def step1_layout(session_id: str | None = None):
    session_note = (
        dbc.Alert(f"Session: {session_id}", color="light", className="py-2 small")
        if session_id else
        dbc.Alert("No active session — open the site from '/' to create one.",
                  color="warning", className="py-2 small")
    )

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

                # Q5: Occupation (drives sessions.expertise)
                html.H5("Q5 · Which best describes your background?"),
                dbc.RadioItems(
                    id="occupation",
                    options=_OCCUPATION_OPTIONS,
                    value=None,
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

    return "/dash/step2", f"?session_id={session_id}", ""
