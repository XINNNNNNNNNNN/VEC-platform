"""VEC Platform - FastAPI main server with Dash mounted via WSGI middleware."""

import json
import uuid
from pathlib import Path
from contextlib import asynccontextmanager
from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
from starlette.middleware.wsgi import WSGIMiddleware

from dash import html, dcc, no_update
import dash_bootstrap_components as dbc
import plotly.graph_objects as go

from vec_platform.config import SLOTS_PER_DAY
# Re-export the runtime singletons so existing imports such as
# `from vec_platform.main import get_db, calculation_engine` (used by
# vec_platform/api/*) keep working without churn in those modules.
from vec_platform.runtime import (
    engine,
    SessionLocal,
    calculation_engine,
    get_db,
    dash_app,
)
from vec_platform.pages._helpers import (
    _parse_session_id,
    make_progress,
    _slot_to_hour,
    _get_profile_at_step,
)


# Dash layout
dash_app.layout = html.Div([
    # Navigation bar
    dbc.Navbar(
        dbc.Container([
            dbc.NavbarBrand("VEC Platform", className="ms-2"),
            dbc.Nav([
                dbc.NavItem(dbc.NavLink("Home", href="/dash/")),
            ]),
        ]),
        color="dark",
        dark=True,
        className="mb-4",
    ),
    
    # Main content
    dbc.Container([
        # URL location for multi-page
        dcc.Location(id="url", refresh=False),
        
        # Progress indicator
        html.Div(id="progress-bar"),
        
        # Page content
        html.Div(id="page-content"),
    ]),
])


# URL routing callback
from dash.dependencies import Input, Output, State


@dash_app.callback(
    Output("page-content", "children"),
    Output("progress-bar", "children"),
    Input("url", "pathname"),
    State("url", "search"),
)
def display_page(pathname, search):
    """Route to the correct page based on URL."""
    session_id = _parse_session_id(search)

    if pathname in (None, "/dash/", "/dash", "/dash/step1"):
        return step1_layout(session_id), make_progress(1)
    elif pathname == "/dash/step2":
        return step2_layout(session_id), make_progress(2)
    elif pathname == "/dash/step4":
        return step4_layout(session_id), make_progress(4)
    elif pathname == "/dash/step6":
        return step6_layout(session_id), make_progress(6)
    elif pathname == "/dash/step7":
        return step7_layout(session_id), make_progress(7)
    elif pathname == "/dash/step8":
        return step8_layout(session_id), make_progress(8)
    else:
        return html.Div([
            html.H3("Page not found"),
            html.P(f"No page for: {pathname}"),
            dbc.Button("Go to Step 1", href="/dash/step1", color="primary"),
        ]), make_progress(1)


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


# ==================== Step 2 ====================
# Colors (consistent across steps) for each device in the stacked chart.
_DEVICE_COLORS = {
    "base_load": "#6c757d",
    "cooking_am": "#f39c12",
    "cooking_pm": "#e67e22",
    "water_heater": "#c0392b",
    "dishwasher": "#3498db",
    "washing_machine": "#2980b9",
    "ev_charger": "#27ae60",
}
_DEVICE_LABELS = {
    "base_load": "Base load (lighting, fridge, peaks)",
    "cooking_am": "Cooking — morning",
    "cooking_pm": "Cooking — evening",
    "water_heater": "Water heater",
    "dishwasher": "Dishwasher",
    "washing_machine": "Washing machine",
    "ev_charger": "EV charger",
}


def _load_curve_figure(devices: dict, pv_generation: list, net_load: list) -> go.Figure:
    """Stacked area chart of per-device loads, PV as negative area, net-load line."""
    hours = [_slot_to_hour(i) for i in range(SLOTS_PER_DAY)]
    fig = go.Figure()

    order = [d for d in _DEVICE_LABELS if d in devices]
    for name in order:
        fig.add_trace(go.Scatter(
            x=hours,
            y=devices[name],
            name=_DEVICE_LABELS[name],
            mode="lines",
            stackgroup="load",
            line=dict(width=0.5, color=_DEVICE_COLORS.get(name)),
            hovertemplate="%{y:.2f} kW<extra>%{fullData.name}</extra>",
        ))

    if any(v > 0 for v in pv_generation):
        fig.add_trace(go.Scatter(
            x=hours,
            y=[-v for v in pv_generation],
            name="PV generation",
            mode="lines",
            stackgroup="pv",
            line=dict(width=0.5, color="#f1c40f"),
            fillcolor="rgba(241, 196, 15, 0.5)",
            hovertemplate="%{y:.2f} kW<extra>PV generation</extra>",
        ))

    fig.add_trace(go.Scatter(
        x=hours,
        y=net_load,
        name="Net load",
        mode="lines",
        line=dict(color="black", width=2, dash="dot"),
        hovertemplate="%{y:.2f} kW<extra>Net load</extra>",
    ))

    fig.update_layout(
        height=420,
        margin=dict(l=50, r=20, t=30, b=40),
        xaxis=dict(
            title="Hour of day",
            tickmode="array",
            tickvals=list(range(0, 25, 3)),
            range=[0, 24],
        ),
        yaxis=dict(title="Power (kW)"),
        legend=dict(orientation="h", yanchor="bottom", y=-0.3),
        hovermode="x unified",
    )
    return fig


def _bill_card(bill) -> dbc.Card:
    """Monthly bill breakdown card (no-VEC scenario)."""

    def row(label: str, value: float, bold: bool = False) -> dbc.Row:
        cls = "fw-bold" if bold else ""
        return dbc.Row([
            dbc.Col(html.Span(label, className=cls), width=8),
            dbc.Col(html.Span(f"{value:,.0f} SEK", className=cls),
                    width=4, className="text-end"),
        ], className="mb-1")

    return dbc.Card([
        dbc.CardHeader(html.H5("Estimated Monthly Bill (no VEC)", className="mb-0")),
        dbc.CardBody([
            row("Electricity purchase", bill.energy_purchase),
            row("Grid fee", bill.grid_fee),
            row("Energy tax", bill.energy_tax),
            row("Feed-in income", -bill.feed_in_income),
            html.Hr(className="my-2"),
            row("Net cost", bill.net_cost, bold=True),
            html.Small(
                "Approximate, based on a typical daily profile × 30 days.",
                className="text-muted",
            ),
        ]),
    ])


def step2_layout(session_id: str | None):
    if not session_id:
        return html.Div([
            html.H2("Step 2: Your Electricity Profile"),
            dbc.Alert("No session found. Please start from Step 1.", color="warning"),
            dbc.Button("← Back to Step 1", href="/dash/step1", color="secondary"),
        ])

    from vec_platform.models import DailyProfile, BillBreakdown

    db = SessionLocal()
    try:
        profile = (
            db.query(DailyProfile)
            .filter(DailyProfile.session_id == session_id, DailyProfile.step == 2)
            .order_by(DailyProfile.id.desc())
            .first()
        )
        bill = (
            db.query(BillBreakdown)
            .filter(
                BillBreakdown.session_id == session_id,
                BillBreakdown.scenario == "no_vec",
            )
            .order_by(BillBreakdown.id.desc())
            .first()
        )
    finally:
        db.close()

    if profile is None or bill is None:
        return html.Div([
            html.H2("Step 2: Your Electricity Profile"),
            dbc.Alert(
                "No profile found for this session. Please complete Step 1 first.",
                color="warning",
            ),
            dbc.Button(
                "← Back to Step 1",
                href=f"/dash/step1?session_id={session_id}",
                color="secondary",
            ),
        ])

    devices = json.loads(profile.devices)
    pv_generation = json.loads(profile.pv_generation)
    net_load = json.loads(profile.net_load)
    figure = _load_curve_figure(devices, pv_generation, net_load)

    return html.Div([
        html.H2("Step 2: Your Electricity Profile"),
        html.P("A typical weekday for your household, based on what you told us."),

        dbc.Row([
            dbc.Col(
                dbc.Card([
                    dbc.CardHeader(html.H5("Daily load curve", className="mb-0")),
                    dbc.CardBody(dcc.Graph(figure=figure, config={"displayModeBar": False})),
                ]),
                md=8,
            ),
            dbc.Col(_bill_card(bill), md=4),
        ], className="mb-3"),

        dbc.Row([
            dbc.Col(
                dbc.Button(
                    "← Back",
                    href=f"/dash/step1?session_id={session_id}",
                    color="secondary",
                ),
                width="auto",
            ),
            dbc.Col(
                dbc.Button(
                    "Next → Customize devices",
                    href=f"/step3?session_id={session_id}",
                    external_link=True,
                    color="primary",
                ),
                width="auto",
            ),
        ], justify="between"),
    ])


# ==================== Step 4 ====================

def _get_or_create_shadow_prices(db, session_id: str):
    """Return the session's ShadowPrices row, creating it via the engine if absent."""
    from vec_platform.models import ShadowPrices

    row = (
        db.query(ShadowPrices)
        .filter(ShadowPrices.session_id == session_id)
        .first()
    )
    if row is None:
        row = calculation_engine.get_shadow_prices(session_id)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def _pick_bill(db, session_id: str, scenario: str):
    """Prefer the Step 3 (customized) bill; fall back to the Step 2 baseline."""
    from vec_platform.models import BillBreakdown

    q = db.query(BillBreakdown).filter(
        BillBreakdown.session_id == session_id,
        BillBreakdown.scenario == scenario,
    )
    bill = q.filter(BillBreakdown.step == 3).order_by(BillBreakdown.id.desc()).first()
    if bill is None:
        bill = q.order_by(BillBreakdown.id.desc()).first()
    return bill


def _shadow_price_figure(retail, internal_buy, internal_sell, feed_in) -> go.Figure:
    """Three-line chart of retail / internal buy / internal sell prices."""
    hours = [_slot_to_hour(i) for i in range(SLOTS_PER_DAY)]
    fig = go.Figure()

    # Shade the PV-surplus window (10:00-14:00) where internal-buy goes cheap.
    fig.add_vrect(
        x0=10, x1=14,
        fillcolor="rgba(46, 204, 113, 0.12)",
        line_width=0,
        annotation_text="Community PV surplus",
        annotation_position="top left",
        annotation=dict(font=dict(size=11, color="#27ae60")),
    )

    fig.add_trace(go.Scatter(
        x=hours, y=retail,
        name="Retail price (grid)",
        mode="lines",
        line=dict(color="#6c757d", width=2, dash="dash"),
        hovertemplate="%{y:.2f} SEK/kWh<extra>Retail</extra>",
    ))
    fig.add_trace(go.Scatter(
        x=hours, y=internal_buy,
        name="VEC internal buy",
        mode="lines",
        line=dict(color="#3498db", width=2.5),
        hovertemplate="%{y:.2f} SEK/kWh<extra>VEC buy</extra>",
    ))
    fig.add_trace(go.Scatter(
        x=hours, y=internal_sell,
        name="VEC internal sell",
        mode="lines",
        line=dict(color="#27ae60", width=2.5),
        hovertemplate="%{y:.2f} SEK/kWh<extra>VEC sell</extra>",
    ))
    fig.add_trace(go.Scatter(
        x=hours, y=feed_in,
        name="Feed-in (outside VEC)",
        mode="lines",
        line=dict(color="#e67e22", width=1.5, dash="dot"),
        hovertemplate="%{y:.2f} SEK/kWh<extra>Feed-in</extra>",
    ))

    fig.update_layout(
        height=380,
        margin=dict(l=50, r=20, t=40, b=40),
        xaxis=dict(
            title="Hour of day",
            tickmode="array",
            tickvals=list(range(0, 25, 3)),
            range=[0, 24],
        ),
        yaxis=dict(title="Price (SEK / kWh)"),
        legend=dict(orientation="h", yanchor="bottom", y=-0.3),
        hovermode="x unified",
    )
    return fig


def _pv_window_callout(retail: list, internal_buy: list) -> str:
    """Build a human sentence describing the midday VEC discount."""
    # Slots 40..55 = 10:00-14:00
    window = range(40, 56)
    avg_buy = sum(internal_buy[i] for i in window) / len(window)
    avg_retail = sum(retail[i] for i in window) / len(window)
    pct = (1 - avg_buy / avg_retail) * 100 if avg_retail else 0
    return (
        f"10:00–14:00 · community PV surplus → VEC internal buy "
        f"≈ {avg_buy:.2f} SEK/kWh vs. market {avg_retail:.2f} SEK/kWh "
        f"(~{pct:.0f}% off if you consume in this window)."
    )


def _savings_card(bill_no_vec, bill_vec) -> dbc.Card:
    """Side-by-side monthly-cost comparison with a highlighted savings delta."""
    savings = bill_no_vec.net_cost - bill_vec.net_cost
    pct = (savings / bill_no_vec.net_cost * 100) if bill_no_vec.net_cost else 0

    def cost_block(title: str, value: float, muted: bool = False) -> dbc.Col:
        color = "text-muted" if muted else ""
        return dbc.Col([
            html.Div(title, className=f"small {color}"),
            html.Div(
                f"{value:,.0f} SEK",
                className=f"h4 mb-0 {color}",
            ),
            html.Div("per month", className="small text-muted"),
        ], width=6)

    return dbc.Card([
        dbc.CardHeader(html.H5("If you don't change anything", className="mb-0")),
        dbc.CardBody([
            dbc.Row([
                cost_block("Without VEC", bill_no_vec.net_cost, muted=True),
                cost_block("With VEC (same schedule)", bill_vec.net_cost),
            ], className="mb-3"),
            html.Div([
                html.Span(
                    f"Save {savings:,.0f} SEK / month",
                    className="badge bg-success fs-6 me-2",
                ),
                html.Span(f"({pct:.1f}% less)", className="text-muted"),
            ]),
            html.Small(
                "VEC membership already discounts your energy cost even if you "
                "don't shift when you use power. In Step 5 you'll see how much "
                "more you can save by shifting flexible loads into the cheap "
                "midday window.",
                className="d-block text-muted mt-2",
            ),
        ]),
    ])


def _about_vec_card() -> dbc.Card:
    return dbc.Card([
        dbc.CardHeader(html.H5("What is a Virtual Energy Community?", className="mb-0")),
        dbc.CardBody([
            html.P(
                "A VEC is a group of neighbouring homes and businesses that share "
                "rooftop solar and battery capacity through a virtual marketplace. "
                "When the community produces more power than it consumes, members "
                "who buy at that moment pay a discounted internal price — and "
                "members who export earn more than the grid's feed-in rate."
            ),
            html.Ul([
                html.Li([html.B("Retail price"), " — what you pay to your grid "
                         "supplier (flat rate in this demo)."]),
                html.Li([html.B("VEC internal buy"), " — what VEC members pay "
                         "when buying electricity from the community pool."]),
                html.Li([html.B("VEC internal sell"), " — what VEC members earn "
                         "when selling their surplus inside the community."]),
            ], className="mb-2"),
            html.Small(
                "These are \"shadow prices\" — they are negotiated inside the "
                "community each day based on supply and demand forecasts.",
                className="text-muted",
            ),
        ]),
    ])


def step4_layout(session_id: str | None):
    if not session_id:
        return html.Div([
            html.H2("Step 4: Tomorrow's community energy prices"),
            dbc.Alert("No session found. Please start from Step 1.", color="warning"),
            dbc.Button("← Back to Step 1", href="/dash/step1", color="secondary"),
        ])

    db = SessionLocal()
    try:
        shadow = _get_or_create_shadow_prices(db, session_id)
        bill_no_vec = _pick_bill(db, session_id, "no_vec")
        bill_vec = _pick_bill(db, session_id, "vec_no_adjust")
    finally:
        db.close()

    if bill_no_vec is None or bill_vec is None:
        return html.Div([
            html.H2("Step 4: Tomorrow's community energy prices"),
            dbc.Alert(
                "No bill found. Please complete Step 1–3 first.",
                color="warning",
            ),
            dbc.Button(
                "← Back to Step 3",
                href=f"/step3?session_id={session_id}",
                external_link=True,
                color="secondary",
            ),
        ])

    retail = json.loads(shadow.retail_price)
    internal_buy = json.loads(shadow.internal_buy)
    internal_sell = json.loads(shadow.internal_sell)
    feed_in = json.loads(shadow.feed_in_price)

    return html.Div([
        html.H2("Step 4: Tomorrow's community energy prices"),
        html.P(
            "Every day the VEC publishes internal prices that reflect how much "
            "solar and battery capacity the community expects to have. Here are "
            "tomorrow's prices for your community."
        ),

        dbc.Alert(
            _pv_window_callout(retail, internal_buy),
            color="success",
            className="py-2",
        ),

        dbc.Card([
            dbc.CardHeader(html.H5("Price curves over 24 hours", className="mb-0")),
            dbc.CardBody(dcc.Graph(
                figure=_shadow_price_figure(retail, internal_buy, internal_sell, feed_in),
                config={"displayModeBar": False},
            )),
        ], className="mb-3"),

        dbc.Row([
            dbc.Col(_savings_card(bill_no_vec, bill_vec), md=6),
            dbc.Col(_about_vec_card(), md=6),
        ], className="mb-3"),

        dbc.Row([
            dbc.Col(
                dbc.Button(
                    "← Back to Step 3",
                    href=f"/step3?session_id={session_id}",
                    external_link=True,
                    color="secondary",
                ),
                width="auto",
            ),
            dbc.Col(
                dbc.Button(
                    "Next → Respond to prices",
                    href=f"/step5?session_id={session_id}",
                    external_link=True,
                    color="primary",
                ),
                width="auto",
            ),
        ], justify="between"),
    ])


# ==================== Step 6 ====================

def _pick_scenario_bill(db, session_id: str, scenario: str, preferred_step: int):
    """Find the right bill for each scenario, falling back sensibly."""
    from vec_platform.models import BillBreakdown

    q = db.query(BillBreakdown).filter(
        BillBreakdown.session_id == session_id,
        BillBreakdown.scenario == scenario,
    )
    bill = (
        q.filter(BillBreakdown.step == preferred_step)
        .order_by(BillBreakdown.id.desc())
        .first()
    )
    if bill is None:
        bill = q.order_by(BillBreakdown.step.desc(), BillBreakdown.id.desc()).first()
    return bill


_SCENARIO_META = {
    "no_vec": {
        "title": "Without VEC",
        "subtitle": "Your original schedule, no community",
        "color": "secondary",
        "accent": "#6c757d",
        "preferred_step": 2,
    },
    "vec_no_adjust": {
        "title": "VEC · same schedule",
        "subtitle": "You joined, but didn't shift loads",
        "color": "info",
        "accent": "#3498db",
        "preferred_step": 3,
    },
    "vec_adjusted": {
        "title": "VEC · after responding",
        "subtitle": "You joined and shifted loads into cheap hours",
        "color": "success",
        "accent": "#27ae60",
        "preferred_step": 5,
    },
}


def _bill_summary_card(scenario: str, bill, baseline_net: float) -> dbc.Card:
    meta = _SCENARIO_META[scenario]
    saving = baseline_net - bill.net_cost
    pct = (saving / baseline_net * 100) if baseline_net else 0

    if scenario == "no_vec":
        badge = html.Span("baseline", className="badge bg-secondary")
    elif saving > 0:
        badge = html.Span(
            f"−{saving:,.0f} SEK / month  ({pct:.1f}% off)",
            className="badge bg-success fs-6",
        )
    else:
        badge = html.Span(
            f"+{-saving:,.0f} SEK / month",
            className="badge bg-danger fs-6",
        )

    return dbc.Card(
        [
            dbc.CardHeader(
                html.Div([
                    html.Strong(meta["title"]),
                    html.Div(meta["subtitle"], className="small text-muted"),
                ]),
                style={"borderTop": f"4px solid {meta['accent']}"},
            ),
            dbc.CardBody([
                html.Div(f"{bill.net_cost:,.0f} SEK", className="h3 mb-0"),
                html.Div("per month", className="small text-muted mb-2"),
                badge,
            ]),
        ],
        className="h-100",
    )


def _breakdown_row(label: str, values: list[float], fmt_sign: bool = False) -> html.Tr:
    def cell(v: float) -> html.Td:
        sign = "+" if (fmt_sign and v > 0) else ("−" if (fmt_sign and v < 0) else "")
        txt = f"{sign}{abs(v):,.0f} SEK" if fmt_sign else f"{v:,.0f} SEK"
        return html.Td(txt, className="text-end")

    return html.Tr([html.Td(label)] + [cell(v) for v in values])


def _breakdown_table(bills: dict) -> dbc.Table:
    order = ["no_vec", "vec_no_adjust", "vec_adjusted"]
    header = html.Thead(html.Tr([
        html.Th("Line item"),
        *[html.Th(_SCENARIO_META[s]["title"], className="text-end") for s in order],
    ]))

    def col(key: str):
        return [getattr(bills[s], key) for s in order]

    # Discounts/income reduce the bill, so show them with a − sign for clarity.
    def col_negated(key: str):
        return [-getattr(bills[s], key) for s in order]

    rows = [
        _breakdown_row("Electricity purchase", col("energy_purchase")),
        _breakdown_row("Grid fee", col("grid_fee")),
        _breakdown_row("Energy tax", col("energy_tax")),
        _breakdown_row("PV self-consumption (value)", col_negated("pv_self_consumption"), fmt_sign=True),
        _breakdown_row("VEC discount", col_negated("vec_discount"), fmt_sign=True),
        _breakdown_row("Feed-in income", col_negated("feed_in_income"), fmt_sign=True),
    ]
    total = html.Tr(
        [html.Td(html.B("Net monthly cost"))]
        + [html.Td(html.B(f"{getattr(bills[s], 'net_cost'):,.0f} SEK"),
                   className="text-end") for s in order],
        className="table-active",
    )

    return dbc.Table(
        [header, html.Tbody(rows + [total])],
        bordered=True,
        hover=True,
        responsive=True,
        size="sm",
    )


def _compare_figure(net_baseline: list, net_customized: list, net_responsive: list) -> go.Figure:
    hours = [_slot_to_hour(i) for i in range(SLOTS_PER_DAY)]
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=hours, y=net_baseline,
        name="Step 2 — baseline",
        mode="lines",
        line=dict(color="#adb5bd", width=1.5, dash="dash"),
        hovertemplate="%{y:.2f} kW<extra>Baseline</extra>",
    ))
    fig.add_trace(go.Scatter(
        x=hours, y=net_customized,
        name="Step 3 — customized",
        mode="lines",
        line=dict(color="#3498db", width=2),
        hovertemplate="%{y:.2f} kW<extra>Customized</extra>",
    ))
    fig.add_trace(go.Scatter(
        x=hours, y=net_responsive,
        name="Step 5 — after responding",
        mode="lines",
        line=dict(color="#27ae60", width=2.5),
        hovertemplate="%{y:.2f} kW<extra>Responded</extra>",
    ))
    fig.update_layout(
        height=360,
        margin=dict(l=50, r=20, t=20, b=40),
        xaxis=dict(title="Hour of day", tickmode="array",
                   tickvals=list(range(0, 25, 3)), range=[0, 24]),
        yaxis=dict(title="Net load (kW)"),
        legend=dict(orientation="h", yanchor="bottom", y=-0.35),
        hovermode="x unified",
    )
    return fig


def step6_layout(session_id: str | None):
    if not session_id:
        return html.Div([
            html.H2("Step 6: Your savings breakdown"),
            dbc.Alert("No session found. Please start from Step 1.", color="warning"),
        ])

    db = SessionLocal()
    try:
        bills = {
            s: _pick_scenario_bill(db, session_id, s, _SCENARIO_META[s]["preferred_step"])
            for s in ("no_vec", "vec_no_adjust", "vec_adjusted")
        }
        p2 = _get_profile_at_step(db, session_id, 2)
        p3 = _get_profile_at_step(db, session_id, 3) or p2
        p5 = _get_profile_at_step(db, session_id, 5) or p3
    finally:
        db.close()

    if any(b is None for b in bills.values()) or p2 is None:
        return html.Div([
            html.H2("Step 6: Your savings breakdown"),
            dbc.Alert(
                "Missing bill or profile data — please complete Step 1–5 first.",
                color="warning",
            ),
            dbc.Button(
                "← Back to Step 5",
                href=f"/step5?session_id={session_id}",
                external_link=True,
                color="secondary",
            ),
        ])

    baseline_net = bills["no_vec"].net_cost

    net_baseline = json.loads(p2.net_load)
    net_customized = json.loads(p3.net_load)
    net_responsive = json.loads(p5.net_load)

    return html.Div([
        html.H2("Step 6: Your savings breakdown"),
        html.P(
            "Three ways to pay for electricity next month — starting from your "
            "original schedule, then joining VEC without changing habits, and "
            "finally shifting loads into the community's cheap hours."
        ),

        dbc.Row([
            dbc.Col(_bill_summary_card("no_vec", bills["no_vec"], baseline_net), md=4),
            dbc.Col(_bill_summary_card("vec_no_adjust", bills["vec_no_adjust"], baseline_net), md=4),
            dbc.Col(_bill_summary_card("vec_adjusted", bills["vec_adjusted"], baseline_net), md=4),
        ], className="g-3 mb-4"),

        dbc.Card([
            dbc.CardHeader(html.H5("Detailed monthly breakdown", className="mb-0")),
            dbc.CardBody(_breakdown_table(bills)),
        ], className="mb-3"),

        dbc.Card([
            dbc.CardHeader(html.H5("Net load across the day", className="mb-0")),
            dbc.CardBody(dcc.Graph(
                figure=_compare_figure(net_baseline, net_customized, net_responsive),
                config={"displayModeBar": False},
            )),
        ], className="mb-3"),

        dbc.Row([
            dbc.Col(
                dbc.Button(
                    "← Back to Step 5",
                    href=f"/step5?session_id={session_id}",
                    external_link=True,
                    color="secondary",
                ),
                width="auto",
            ),
            dbc.Col(
                dbc.Button(
                    "Next → Broader impacts",
                    href=f"/dash/step7?session_id={session_id}",
                    color="primary",
                ),
                width="auto",
            ),
        ], justify="between"),
    ])


# ==================== Step 7 ====================

_CO2_FACTOR_KG_PER_KWH = 0.045  # Nordic electricity mix
_TREE_CO2_KG_PER_YEAR = 21.0   # rough, but commonly cited


def _compute_impacts(db, session_id: str):
    """Session-specific impact numbers derived from Step 2 vs Step 5 net-loads.

    Returns deterministic figures so refreshing the tab doesn't jiggle them.
    """
    p2 = _get_profile_at_step(db, session_id, 2)
    p3 = _get_profile_at_step(db, session_id, 3) or p2
    p5 = _get_profile_at_step(db, session_id, 5) or p3
    if p2 is None:
        return None

    def totals(net):
        imported = sum(max(0.0, x) for x in net) * 0.25
        exported = sum(max(0.0, -x) for x in net) * 0.25
        return imported, exported, max(net)

    imp2, exp2, peak2 = totals(json.loads(p2.net_load))
    imp5, exp5, peak5 = totals(json.loads(p5.net_load))

    import_saved_monthly_kwh = (imp2 - imp5) * 30
    export_diff_monthly_kwh = (exp5 - exp2) * 30
    co2_saved_kg_month = import_saved_monthly_kwh * _CO2_FACTOR_KG_PER_KWH
    co2_saved_kg_year = co2_saved_kg_month * 12
    trees_per_year = co2_saved_kg_year / _TREE_CO2_KG_PER_YEAR
    peak_reduction_pct = (peak2 - peak5) / peak2 * 100 if peak2 else 0

    return {
        "import_baseline_monthly_kwh": imp2 * 30,
        "import_responsive_monthly_kwh": imp5 * 30,
        "import_saved_monthly_kwh": import_saved_monthly_kwh,
        "export_diff_monthly_kwh": export_diff_monthly_kwh,
        "co2_saved_kg_month": co2_saved_kg_month,
        "co2_saved_kg_year": co2_saved_kg_year,
        "trees_per_year": trees_per_year,
        "peak_baseline_kw": peak2,
        "peak_responsive_kw": peak5,
        "peak_reduction_pct": peak_reduction_pct,
    }


def _policy_tab(impacts: dict) -> html.Div:
    return html.Div([
        html.H5("Policy headwinds — and how VEC cushions them", className="mt-2"),
        html.P([
            "From 2026 the Swedish ",
            html.I("skattereduktion"),
            " tax credit for small-scale producers is being phased out and a "
            "capacity-based grid tariff (",
            html.I("effekttariff"), ") is rolling out. Both make individual ",
            "prosumer economics worse — but a community changes the math.",
        ]),
        dbc.Row([
            dbc.Col(dbc.Card([
                dbc.CardHeader(html.Strong("No tax credit for export")),
                dbc.CardBody([
                    html.P(
                        "Outside a VEC, exported solar earns only the grid's "
                        "feed-in rate (~0.50 SEK/kWh). Inside the VEC, the "
                        "internal-sell price is ~1.05 SEK/kWh — more than 2× "
                        "the outside rate during community deficit hours."
                    ),
                    html.Small(
                        "Source of the policy change: Riksdag budget 2024/25.",
                        className="text-muted",
                    ),
                ]),
            ]), md=6),
            dbc.Col(dbc.Card([
                dbc.CardHeader(html.Strong("Effekttariff (capacity charges)")),
                dbc.CardBody([
                    html.P(
                        "Grid operators increasingly bill on peak kW, not just "
                        "total kWh. Without coordination, an EV plugged in at "
                        "6 pm hits the daily peak; with VEC load-shifting, "
                        "peaks are shaved."
                    ),
                    html.Div([
                        html.Span(
                            f"Your peak: {impacts['peak_baseline_kw']:.1f} kW "
                            f"→ {impacts['peak_responsive_kw']:.1f} kW",
                            className="me-2",
                        ),
                        html.Span(
                            f"({impacts['peak_reduction_pct']:.0f}% lower)",
                            className="badge bg-success",
                        ) if impacts['peak_reduction_pct'] > 0 else html.Span(
                            "No change in peak yet",
                            className="badge bg-secondary",
                        ),
                    ]),
                ]),
            ]), md=6),
        ], className="g-3"),
    ])


def _grid_tab(impacts: dict) -> html.Div:
    # Imagine a community of 100 homes with a shared transformer.
    COMMUNITY_SIZE = 100
    transformer_capacity_kw = 400  # illustrative

    baseline_community_peak = impacts["peak_baseline_kw"] * COMMUNITY_SIZE * 0.6
    responsive_community_peak = impacts["peak_responsive_kw"] * COMMUNITY_SIZE * 0.6
    baseline_load_pct = baseline_community_peak / transformer_capacity_kw * 100
    responsive_load_pct = responsive_community_peak / transformer_capacity_kw * 100

    bar_fig = go.Figure()
    bar_fig.add_trace(go.Bar(
        x=["Baseline", "After VEC"],
        y=[baseline_community_peak, responsive_community_peak],
        marker=dict(color=["#adb5bd", "#27ae60"]),
        text=[f"{baseline_community_peak:.0f} kW", f"{responsive_community_peak:.0f} kW"],
        textposition="auto",
    ))
    bar_fig.add_hline(
        y=transformer_capacity_kw, line_dash="dot", line_color="#e74c3c",
        annotation_text=f"Transformer rating {transformer_capacity_kw} kW",
        annotation_position="top right",
    )
    bar_fig.update_layout(
        height=300,
        showlegend=False,
        margin=dict(l=40, r=20, t=20, b=30),
        yaxis=dict(title="Aggregated community peak (kW)"),
    )

    return html.Div([
        html.H5("Grid impact at the community level", className="mt-2"),
        html.P(
            "Imagine 100 households just like yours sharing one neighbourhood "
            "transformer. Small individual shifts add up to something the grid "
            "operator can measure."
        ),
        dbc.Row([
            dbc.Col(dcc.Graph(figure=bar_fig, config={"displayModeBar": False}), md=7),
            dbc.Col(dbc.Card([
                dbc.CardHeader(html.Strong("Transformer utilisation")),
                dbc.CardBody([
                    html.Div(f"{baseline_load_pct:.0f}% → {responsive_load_pct:.0f}%",
                             className="h3 mb-0"),
                    html.Div("at peak hour", className="small text-muted mb-2"),
                    html.P(
                        "Lower utilisation means less stress on grid "
                        "infrastructure and postponed reinforcement "
                        "investment — benefits ultimately shared across all "
                        "customers on the network.",
                        className="small mb-0",
                    ),
                ]),
            ]), md=5),
        ], className="g-3"),
    ])


def _environment_tab(impacts: dict) -> html.Div:
    month_kg = impacts["co2_saved_kg_month"]
    year_kg = impacts["co2_saved_kg_year"]
    trees = impacts["trees_per_year"]
    import_saved = impacts["import_saved_monthly_kwh"]

    def metric(label: str, value: str, sub: str = "") -> dbc.Col:
        return dbc.Col(dbc.Card(dbc.CardBody([
            html.Div(label, className="small text-muted"),
            html.Div(value, className="h3 mb-0"),
            html.Div(sub, className="small text-muted") if sub else None,
        ])), md=4)

    return html.Div([
        html.H5("Environmental impact", className="mt-2"),
        html.P(
            "Every kWh you pull from the grid has an emissions footprint — "
            "about 45 g of CO₂ on the Nordic mix. Shifting your load to "
            "midday keeps more locally-produced solar power inside the "
            "community and lowers the grid-import intensity."
        ),
        dbc.Row([
            metric("Grid imports avoided",
                   f"{import_saved:,.0f} kWh / month",
                   "vs. your baseline schedule"),
            metric("CO₂ avoided",
                   f"{month_kg:,.1f} kg / month",
                   f"≈ {year_kg:,.0f} kg per year"),
            metric("Equivalent to",
                   f"{trees:,.1f} trees 🌱",
                   "planted for one year"),
        ], className="g-3 mb-3"),
        dbc.Alert(
            [
                html.Strong("Why this matters. "),
                "These numbers are for your household alone. A 100-home VEC "
                "adds up to roughly ",
                html.Span(f"{year_kg * 100:,.0f} kg CO₂ per year", className="fw-bold"),
                " — the sort of figure a municipality can put in its climate plan.",
            ],
            color="success",
            className="small mb-0",
        ),
    ])


def step7_layout(session_id: str | None):
    if not session_id:
        return html.Div([
            html.H2("Step 7: Broader impacts"),
            dbc.Alert("No session found. Please start from Step 1.", color="warning"),
        ])

    db = SessionLocal()
    try:
        impacts = _compute_impacts(db, session_id)
    finally:
        db.close()

    if impacts is None:
        return html.Div([
            html.H2("Step 7: Broader impacts"),
            dbc.Alert(
                "No profile data. Please complete Step 1–5 first.",
                color="warning",
            ),
        ])

    tabs = dbc.Tabs(
        [
            dbc.Tab(_policy_tab(impacts), label="Policy", tab_id="policy"),
            dbc.Tab(_grid_tab(impacts), label="Grid", tab_id="grid"),
            dbc.Tab(_environment_tab(impacts), label="Environment",
                    tab_id="environment"),
        ],
        active_tab="policy",
        className="mb-3",
    )

    return html.Div([
        html.H2("Step 7: Broader impacts"),
        html.P(
            "VEC isn't only about your monthly bill. Your decisions also "
            "ripple out into policy, the local grid, and the environment. "
            "Flip through the tabs below."
        ),
        tabs,
        dbc.Row([
            dbc.Col(
                dbc.Button(
                    "← Back to Step 6",
                    href=f"/dash/step6?session_id={session_id}",
                    color="secondary",
                ),
                width="auto",
            ),
            dbc.Col(
                dbc.Button(
                    "Next → Final survey",
                    href=f"/dash/step8?session_id={session_id}",
                    color="primary",
                ),
                width="auto",
            ),
        ], justify="between"),
    ])


# ==================== Step 8 ====================

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


def _survey_form(session_id: str) -> html.Div:
    return html.Div(id="step8-form", children=[
        html.H5("Q1 · How likely are you to actually join a VEC like this?"),
        dbc.RadioItems(id="survey-q1", options=_Q1_OPTIONS, value=None, className="mb-4"),

        html.H5("Q2 · What would be your top reasons to join? (pick up to 3)"),
        dbc.Checklist(id="survey-q2", options=_Q2_OPTIONS, value=[], className="mb-4"),

        html.H5("Q3 · What would worry you the most? (pick up to 3)"),
        dbc.Checklist(id="survey-q3", options=_Q3_OPTIONS, value=[], className="mb-4"),

        html.H5("Q4 · Looking at the savings you saw in Step 6…"),
        dbc.RadioItems(id="survey-q4", options=_Q4_OPTIONS, value=None, className="mb-3"),

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
                          color="primary", size="lg"),
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

    if already is not None:
        return html.Div([
            html.H2("Step 8: Your decision"),
            _thank_you_view(),
        ])

    return html.Div([
        html.H2("Step 8: Your decision"),
        html.P(
            "One last thing. After seeing how a VEC could change your bill, "
            "your daily schedule, and your footprint — how do you actually "
            "feel about joining?"
        ),
        html.Div(_survey_form(session_id), id="step8-content"),
    ])


@dash_app.callback(
    Output("step8-content", "children"),
    Output("survey-error", "children"),
    Input("btn-submit-survey", "n_clicks"),
    State("survey-q1", "value"),
    State("survey-q2", "value"),
    State("survey-q3", "value"),
    State("survey-q4", "value"),
    State("url", "search"),
    prevent_initial_call=True,
)
def submit_survey(n_clicks, q1, q2, q3, q4, search):
    if not n_clicks:
        return no_update, no_update

    if not q1 or not q4:
        return no_update, "Please answer Q1 and Q4 before submitting."

    session_id = _parse_session_id(search)
    if not session_id:
        return no_update, "Session id missing from URL. Please start from Step 1."

    from vec_platform.models import (
        Session as SessionModel,
        SurveyResponse,
    )

    # Cap multi-selects at 3 so "top 3" is enforced in the data.
    q2_trim = (q2 or [])[:3]
    q3_trim = (q3 or [])[:3]

    db = SessionLocal()
    try:
        session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
        if session is None:
            return no_update, "Session not found. Please start from Step 1."

        # Idempotency: don't insert twice if the user clicks Submit rapidly.
        existing = (
            db.query(SurveyResponse)
            .filter(SurveyResponse.session_id == session_id)
            .first()
        )
        if existing is None:
            db.add(SurveyResponse(
                session_id=session_id,
                q1_willingness=q1,
                q2_reasons=json.dumps(q2_trim),
                q3_concerns=json.dumps(q3_trim),
                q4_savings_perception=q4,
            ))

        session.completed = True
        session.current_step = 8
        db.commit()
    finally:
        db.close()

    return _thank_you_view(), ""


# ==================== FastAPI App ====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("VEC Platform starting up...")
    yield
    print("VEC Platform shutting down...")

fastapi_app = FastAPI(
    title="VEC Platform API",
    description="API for VEC Stated-Preference Platform",
    version="0.1.0",
    lifespan=lifespan,
)

# Root redirect
@fastapi_app.get("/")
async def root():
    """Redirect to Step 1 with a new session."""
    session_id = str(uuid.uuid4())
    
    db = SessionLocal()
    try:
        from vec_platform.models import Session
        session = Session(id=session_id, current_step=1)
        db.add(session)
        db.commit()
    finally:
        db.close()
    
    return RedirectResponse(url=f"/dash/step1?session_id={session_id}")


# Health check
@fastapi_app.get("/health")
async def health():
    return {"status": "ok", "engine": "mock"}


# Step 3 is a static HTML/JS page served by FastAPI (not Dash).
# The JS reads session_id from the URL query string (?session_id=...).
@fastapi_app.get("/step3")
async def step3_page(session_id: str | None = None):
    html_file = static_path / "step3_customize.html"
    if not html_file.exists():
        raise HTTPException(status_code=404, detail="Step 3 page not found")
    return FileResponse(str(html_file))


# Step 5 — also a static HTML/JS page, responds to shadow prices.
@fastapi_app.get("/step5")
async def step5_page(session_id: str | None = None):
    html_file = static_path / "step5_respond.html"
    if not html_file.exists():
        raise HTTPException(status_code=404, detail="Step 5 page not found")
    return FileResponse(str(html_file))


# API routes
from vec_platform.api import session, profile, bill, shadow_price, device_shift, survey

fastapi_app.include_router(session.router, prefix="/api", tags=["session"])
fastapi_app.include_router(profile.router, prefix="/api", tags=["profile"])
fastapi_app.include_router(bill.router, prefix="/api", tags=["bill"])
fastapi_app.include_router(shadow_price.router, prefix="/api", tags=["shadow_price"])
fastapi_app.include_router(device_shift.router, prefix="/api", tags=["device_shift"])
fastapi_app.include_router(survey.router, prefix="/api", tags=["survey"])


# Mount Dash as WSGI middleware under /dash/
fastapi_app.mount("/dash", WSGIMiddleware(dash_app.server))

# Mount static files
static_path = Path(__file__).parent / "static"
if static_path.exists():
    fastapi_app.mount("/static", StaticFiles(directory=str(static_path)), name="static")


# Export for uvicorn: uvicorn vec_platform.main:app --reload
app = fastapi_app
__all__ = ["app", "get_db", "calculation_engine", "SessionLocal", "dash_app"]