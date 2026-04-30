"""Step 2 — daily load curve + monthly bill card + second prior expectation.

Layout shows the participant's profile/bill (unchanged from v2) and then
asks two new questions: their second guess at the % savings and how
confident they are about it. Submitting writes one row to
``prior_expectations`` (measurement_round=2) and navigates to the static
Step 3 drag page.

Importing this module registers three Dash callbacks against ``dash_app``.
"""

import json

from dash import html, dcc, no_update
from dash.dependencies import Input, Output, State
import dash_bootstrap_components as dbc
import plotly.graph_objects as go

from vec_platform.config import SLOTS_PER_DAY
from vec_platform.runtime import SessionLocal, dash_app
from vec_platform.pages._helpers import _slot_to_hour, _parse_session_id


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

        # ----- v3.3: second prior-expectation guess -----
        html.Hr(),
        dbc.Card([
            dbc.CardBody([
                html.H4(
                    "Now that you've seen your own profile and bill, what % "
                    "of your monthly bill do you expect to save by joining "
                    "a VEC?"
                ),
                # Default 0% — deliberately NOT pre-filled with the Step 0
                # value so we don't anchor the second guess.
                dcc.Slider(
                    id="step2-expectation-pct",
                    min=0, max=50, step=1, value=0,
                    marks={p: f"{p}%" for p in (0, 10, 20, 30, 40, 50)},
                    tooltip={"placement": "bottom", "always_visible": False},
                ),
                html.Div(
                    "0%",
                    id="step2-expectation-display",
                    className="text-center fs-4 fw-bold mt-3",
                ),
            ]),
        ], className="mb-3"),

        # ----- v3.3: confidence Likert -----
        html.Hr(),
        dbc.Card([
            dbc.CardBody([
                html.H4("How confident are you about this estimate?"),
                dcc.RadioItems(
                    id="step2-confidence",
                    options=[
                        {"label": "1 — Not at all confident", "value": 1},
                        {"label": "2 — Slightly confident", "value": 2},
                        {"label": "3 — Moderately confident", "value": 3},
                        {"label": "4 — Quite confident", "value": 4},
                        {"label": "5 — Very confident", "value": 5},
                    ],
                    value=None,
                    labelStyle={"display": "block"},
                ),
                html.Div(id="step2-error", className="text-danger small mt-2"),
            ]),
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
                    id="step2-next-btn",
                    color="primary",
                    disabled=True,
                ),
                width="auto",
            ),
        ], justify="between"),

        # Hidden redirect: the global url Location has refresh=False
        # (SPA-style). /step3 is a FastAPI-served HTML page outside the
        # Dash mount, so we need a refresh=True Location to force a full
        # browser navigation when submit_step2 fires.
        dcc.Location(id="step2-redirect", refresh=True),
    ])


# ==================== callbacks ====================

@dash_app.callback(
    Output("step2-expectation-display", "children"),
    Input("step2-expectation-pct", "value"),
)
def update_step2_expectation_display(pct):
    """Live "X%" label under the slider."""
    return f"{pct}%"


@dash_app.callback(
    Output("step2-next-btn", "disabled"),
    Input("step2-confidence", "value"),
)
def toggle_step2_next(v):
    """Lock Next until the participant picks a confidence level."""
    return v is None


@dash_app.callback(
    Output("step2-redirect", "href"),
    Output("step2-error", "children"),
    Input("step2-next-btn", "n_clicks"),
    State("step2-expectation-pct", "value"),
    State("step2-confidence", "value"),
    State("url", "search"),
    prevent_initial_call=True,
)
def submit_step2(n_clicks, pct, confidence, search):
    """Persist the round-2 prior-expectation row, then full-nav to /step3."""
    if not n_clicks:
        return no_update, no_update

    session_id = _parse_session_id(search)
    if not session_id:
        return no_update, "Session id missing — please start from '/'."
    if confidence is None:
        return no_update, "Please answer both questions."

    from vec_platform.models import (
        Session as SessionModel,
        PriorExpectation,
    )

    db = SessionLocal()
    try:
        sess = db.query(SessionModel).filter(SessionModel.id == session_id).first()
        if sess is None:
            return no_update, "Session not found."
        db.add(PriorExpectation(
            session_id=session_id,
            measurement_round=2,
            pct=float(pct),
            confidence=int(confidence),
        ))
        if sess.current_step is None or sess.current_step < 3:
            sess.current_step = 3
        db.commit()
    finally:
        db.close()

    return f"/step3?session_id={session_id}", ""
