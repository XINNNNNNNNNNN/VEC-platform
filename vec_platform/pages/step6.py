"""Step 6 — broader impacts (Policy / Grid / Environment tabs).

Phase 4-A: renumbered from Step 7 (8-step flow) to Step 6 (7-step flow).
File renamed step7.py → step6.py; identifiers, DB column names, and UI
labels updated accordingly. Data step values in daily_profiles are
preserved (decision 2a), so the impact computation still queries
step=2/3/5 unchanged.

Session-specific numbers are derived from baseline vs responded
net-loads in ``_compute_impacts``. A single 5-point Likert below the
tabs ("has this changed your view about joining a VEC?") is persisted
as survey_responses.step6_broader_impacts_shift via the upsert helper.

Importing this module registers two Dash callbacks against ``dash_app``.
"""

import json

from dash import html, dcc, no_update
from dash.dependencies import Input, Output, State
import dash_bootstrap_components as dbc
import plotly.graph_objects as go

from vec_platform.runtime import SessionLocal, dash_app
from vec_platform.pages._helpers import _get_profile_at_step, _parse_session_id


# ==================== Step 6 ====================

_CO2_FACTOR_KG_PER_KWH = 0.045  # Nordic electricity mix
_TREE_CO2_KG_PER_YEAR = 21.0   # rough, but commonly cited


def _compute_impacts(db, session_id: str):
    """Session-specific impact numbers derived from baseline (data
    step=2) vs responded (data step=5) net-loads.

    Returns deterministic figures so refreshing the tab doesn't jiggle
    them. Phase 4-A: data step values preserved (decision 2a) — the
    queries still use 2/3/5 even though UI flow positions changed.
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


def step6_layout(session_id: str | None):
    if not session_id:
        return html.Div([
            html.H2("Step 6: Broader impacts"),
            dbc.Alert("No session found. Please start from Step 1.", color="warning"),
        ])

    db = SessionLocal()
    try:
        impacts = _compute_impacts(db, session_id)
    finally:
        db.close()

    if impacts is None:
        return html.Div([
            html.H2("Step 6: Broader impacts"),
            dbc.Alert(
                "No profile data. Please complete Step 1–4 first.",
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
        html.H2("Step 6: Broader impacts"),
        html.P(
            "VEC isn't only about your monthly bill. Your decisions also "
            "ripple out into policy, the local grid, and the environment. "
            "Flip through the tabs below."
        ),
        tabs,

        # ----- broader-impacts Likert -----
        # (v3.X-fix-7 added an E.ON Q11 fairness Likert above this block;
        # v3.X-fix-8 removed it — the question overlapped conceptually
        # with q6_fairness_pref on the final survey.)
        html.Hr(),
        dbc.Card([
            dbc.CardBody([
                html.H4(
                    "Now that you've seen how VECs affect policy, the grid, "
                    "and the environment, has this changed your view about "
                    "joining one?"
                ),
                dcc.RadioItems(
                    id="step6-broader-impacts-shift",
                    options=[
                        {"label": "1 — It made me much less interested",   "value": 1},
                        {"label": "2 — It made me a bit less interested",  "value": 2},
                        {"label": "3 — No change",                          "value": 3},
                        {"label": "4 — It made me a bit more interested",  "value": 4},
                        {"label": "5 — It made me much more interested",   "value": 5},
                    ],
                    value=None,
                    labelStyle={"display": "block", "padding": "0.3rem 0"},
                ),
                html.Div(id="step6-error", className="text-danger small mt-2"),
            ]),
        ], className="mb-3"),

        dbc.Row([
            dbc.Col(
                dbc.Button(
                    "Next → Final survey",
                    id="step6-next-btn",
                    color="primary",
                    disabled=True,
                ),
                width="auto",
            ),
        ], justify="end"),

        # /dash/step7 lives within the Dash mount; refresh=True is kept
        # for symmetry with the Step 3/5 redirect Locations.
        dcc.Location(id="step6-redirect", refresh=True),
    ])


# ==================== callbacks ====================

@dash_app.callback(
    Output("step6-next-btn", "disabled"),
    Input("step6-broader-impacts-shift", "value"),
)
def toggle_step6_next(v):
    """Lock Next until the Likert is picked.

    (v3.X-fix-7 briefly added a fairness Likert co-gate; fix-8 reverted
    that — only the broader-impacts shift Likert remains.)
    """
    return v is None


@dash_app.callback(
    Output("step6-redirect", "href"),
    Output("step6-error", "children"),
    Input("step6-next-btn", "n_clicks"),
    State("step6-broader-impacts-shift", "value"),
    State("url", "search"),
    prevent_initial_call=True,
)
def submit_step6(n_clicks, q, search):
    """Upsert Q (broader-impacts shift) onto survey_responses, then nav
    to /dash/step7."""
    if not n_clicks:
        return no_update, no_update

    session_id = _parse_session_id(search)
    if not session_id:
        return no_update, "Session id missing — please start from '/'."
    if q is None:
        return no_update, "Please select an option."

    from vec_platform.models import Session as SessionModel
    from vec_platform.pages._survey_helpers import get_or_create_survey_row

    db = SessionLocal()
    try:
        sess = db.query(SessionModel).filter(SessionModel.id == session_id).first()
        if sess is None:
            return no_update, "Session not found."

        row = get_or_create_survey_row(db, session_id)
        row.step6_broader_impacts_shift = int(q)

        # Phase 4-A: advance to current_step=7 (final survey is "Step 7"
        # in the new 7-step flow).
        if sess.current_step is None or sess.current_step < 7:
            sess.current_step = 7
        db.commit()
    finally:
        db.close()

    return f"/dash/step7?session_id={session_id}", ""
