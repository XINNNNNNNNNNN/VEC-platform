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
# Importing each page module registers its Dash callbacks against
# runtime.dash_app. Order doesn't matter as long as they're imported before
# the first request (so before uvicorn finishes app construction).
from vec_platform.pages import step1 as _step1
from vec_platform.pages import step2 as _step2
from vec_platform.pages import step4 as _step4


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
        return _step1.step1_layout(session_id), make_progress(1)
    elif pathname == "/dash/step2":
        return _step2.step2_layout(session_id), make_progress(2)
    elif pathname == "/dash/step4":
        return _step4.step4_layout(session_id), make_progress(4)
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