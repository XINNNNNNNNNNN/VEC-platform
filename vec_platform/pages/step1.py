"""Step 1 — building profile form + submit callback.

Importing this module registers the Dash callback against ``dash_app``.
"""

import uuid

from dash import html, no_update
from dash.dependencies import Input, Output, State
import dash_bootstrap_components as dbc

from vec_platform.runtime import dash_app, SessionLocal, calculation_engine
from vec_platform.pages._helpers import _parse_session_id


# ==================== Step 1 ====================
def step1_layout(session_id: str | None = None):
    session_note = (
        dbc.Alert(f"Session: {session_id}", color="light", className="py-2 small")
        if session_id else
        dbc.Alert("No active session — open the site from '/' to create one.",
                  color="warning", className="py-2 small")
    )

    return html.Div([
        html.H2("Step 1: Tell us about your building"),
        html.P("Select your role and provide basic information."),

        session_note,

        dbc.Card([
            dbc.CardBody([
                # Role selection
                html.H5("Building Type"),
                dbc.RadioItems(
                    id="building-type",
                    options=[
                        {"label": "Apartment (Lägenhet)", "value": "apartment"},
                        {"label": "Villa / Radhus (no DER)", "value": "villa_noder"},
                        {"label": "Villa with Solar PV", "value": "villa_pv"},
                        {"label": "Villa with Solar PV + Battery", "value": "villa_pvbess"},
                    ],
                    value="apartment",
                    className="mb-3",
                ),

                # Basic info
                html.H5("Basic Information", className="mt-3"),
                dbc.Row([
                    dbc.Col([
                        dbc.Label("Area (m²)"),
                        dbc.Input(id="area", type="number", value=75, min=30, max=300),
                    ], width=4),
                    dbc.Col([
                        dbc.Label("Number of people"),
                        dbc.Input(id="people", type="number", value=2, min=1, max=6),
                    ], width=4),
                    dbc.Col([
                        dbc.Label("Heating"),
                        dbc.Select(
                            id="heating",
                            options=[
                                {"label": "District heating", "value": "district"},
                                {"label": "Electric heating", "value": "electric"},
                                {"label": "Heat pump", "value": "heatpump"},
                            ],
                            value="district",
                        ),
                    ], width=4),
                ], className="mb-3"),

                # EV
                dbc.Checkbox(id="has-ev", label="I have an electric vehicle (EV)", value=False),

                html.Hr(),
                html.Div(id="step1-error", className="text-danger mb-2"),
                dbc.Button("Next → Generate my profile", id="btn-next-step1",
                          color="primary", size="lg", className="mt-2"),
            ])
        ]),
    ])


# ==================== Step 1 submit callback ====================
# Default PV/BESS sizing when user picks a DER variant.
# 5 kWp × 0.6 shape-factor ≈ 3 kW noon peak (matches dev spec).
_DEFAULT_PV_KWP = 5.0
_DEFAULT_BESS_KWH = 10.0
_SCENARIOS = ("no_vec", "vec_no_adjust", "vec_adjusted")


@dash_app.callback(
    Output("url", "pathname"),
    Output("url", "search"),
    Output("step1-error", "children"),
    Input("btn-next-step1", "n_clicks"),
    State("building-type", "value"),
    State("area", "value"),
    State("people", "value"),
    State("heating", "value"),
    State("has-ev", "value"),
    State("url", "search"),
    prevent_initial_call=True,
)
def submit_step1(n_clicks, building_type, area, people, heating, has_ev, search):
    if not n_clicks:
        return no_update, no_update, no_update

    if not building_type or area is None or people is None or not heating:
        return no_update, no_update, "Please fill in all fields."

    from vec_platform.models import Session as SessionModel, UserInput

    session_id = _parse_session_id(search)
    has_pv = "pv" in building_type
    has_bess = "bess" in building_type

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

        session.role = building_type
        session.current_step = 2

        user_input = UserInput(
            session_id=session_id,
            building_type=building_type,
            area_m2=float(area),
            people=int(people),
            heating=heating,
            has_ev=bool(has_ev),
            has_pv=has_pv,
            pv_kwp=_DEFAULT_PV_KWP if has_pv else None,
            has_bess=has_bess,
            bess_kwh=_DEFAULT_BESS_KWH if has_bess else None,
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
