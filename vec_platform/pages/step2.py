"""Step 2 — daily load curve + monthly bill card.

Pure layout module: no Dash callbacks, just a function the routing
callback in main.py calls with the current session_id.

(Phase 3.3 added a second prior-expectation slider + confidence Likert at
the bottom of this page; Phase 3.3.1 reverted that — those measurements
now live at the end of Step 3, after the participant has finished
adjusting their schedule and seen the live bill update.)
"""

import json

from dash import html, dcc
import dash_bootstrap_components as dbc
import plotly.graph_objects as go

from vec_platform.config import SLOTS_PER_DAY
from vec_platform.runtime import SessionLocal
from vec_platform.pages._helpers import _slot_to_hour


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
