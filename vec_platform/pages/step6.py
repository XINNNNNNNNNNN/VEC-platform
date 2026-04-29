"""Step 6 — three-way bill comparison.

Pure layout module. Pulls per-scenario bills (preferring the right
``step``) plus Step 2/3/5 profiles, builds three summary cards, a
breakdown table and a three-line net-load chart.
"""

import json

from dash import html, dcc
import dash_bootstrap_components as dbc
import plotly.graph_objects as go

from vec_platform.config import SLOTS_PER_DAY
from vec_platform.runtime import SessionLocal
from vec_platform.pages._helpers import _slot_to_hour, _get_profile_at_step


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
