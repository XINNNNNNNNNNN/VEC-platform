"""Step 6 — three-way bill comparison + disappointment & consider Likerts.

Pulls per-scenario bills (preferring the right ``step``) plus Step 2/3/5
profiles, builds three summary cards, a breakdown table and a three-line
net-load chart. Phase 3.7 added two follow-up questions at the bottom:

  Q6-1 disappointment vs expectation — 5-point Likert, persisted on
       survey_responses.step6_expectation_vs_reality
  Q6-2 would-you-consider Likert — 5-point, persisted as
       willingness_measurements(round=2, scale_type='5point_consider')
       to keep all three willingness measurements (info_calibration /
       Step 6 / Step 8) in one uniform table

Importing this module registers two Dash callbacks against ``dash_app``.
"""

import json

from dash import html, dcc, no_update
from dash.dependencies import Input, Output, State
import dash_bootstrap_components as dbc
import plotly.graph_objects as go

from vec_platform.config import SLOTS_PER_DAY
from vec_platform.runtime import SessionLocal, dash_app
from vec_platform.pages._helpers import (
    _slot_to_hour,
    _get_profile_at_step,
    _parse_session_id,
)


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


def _load_prior_step6(db, session_id: str) -> dict | None:
    """v3.X-fix-6a: rehydrate the two Likerts when the user revisits via
    Back. Q6-1 lives on survey_responses.step6_expectation_vs_reality;
    Q6-2 is willingness_measurements(round=2). Either may be present
    without the other depending on whether prior submissions partially
    succeeded; we just surface whatever we have.
    """
    from vec_platform.models import SurveyResponse, WillingnessMeasurement
    sr = (
        db.query(SurveyResponse)
        .filter(SurveyResponse.session_id == session_id)
        .first()
    )
    wm = (
        db.query(WillingnessMeasurement)
        .filter(
            WillingnessMeasurement.session_id == session_id,
            WillingnessMeasurement.round == 2,
        )
        .order_by(WillingnessMeasurement.id.desc())
        .first()
    )
    if sr is None and wm is None:
        return None
    return {
        "expectation_vs_reality": sr.step6_expectation_vs_reality if sr else None,
        "consider":               wm.value if wm else None,
    }


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
        # v3.X-fix-6a: piggyback prior-Likerts lookup on the same db block.
        prior = _load_prior_step6(db, session_id)
    finally:
        db.close()
    expect_default   = prior["expectation_vs_reality"] if prior else None
    consider_default = prior["consider"]               if prior else None

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

        # ----- v3.7: disappointment + consider Likerts -----
        html.Hr(),
        dbc.Card([
            dbc.CardBody([
                html.H4(
                    "Looking at how much the three options would actually save "
                    "you, how does this compare to what you expected before "
                    "seeing your own profile?"
                ),
                dcc.RadioItems(
                    id="step6-expectation-vs-reality",
                    options=[
                        {"label": "1 — Much less than I expected",  "value": 1},
                        {"label": "2 — Less than I expected",       "value": 2},
                        {"label": "3 — About what I expected",      "value": 3},
                        {"label": "4 — More than I expected",       "value": 4},
                        {"label": "5 — Much more than I expected",  "value": 5},
                    ],
                    value=expect_default,
                    labelStyle={"display": "block", "padding": "0.3rem 0"},
                ),
            ]),
        ], className="mb-3"),

        dbc.Card([
            dbc.CardBody([
                html.H4(
                    "Now that you've seen the comparison, would you consider "
                    "joining a VEC?"
                ),
                dcc.RadioItems(
                    id="step6-consider-willingness",
                    options=[
                        {"label": "1 — Definitely not",   "value": 1},
                        {"label": "2 — Probably not",     "value": 2},
                        {"label": "3 — Maybe",            "value": 3},
                        {"label": "4 — Probably yes",     "value": 4},
                        {"label": "5 — Definitely yes",   "value": 5},
                    ],
                    value=consider_default,
                    labelStyle={"display": "block", "padding": "0.3rem 0"},
                ),
                html.Div(id="step6-error", className="text-danger small mt-2"),
            ]),
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
                    id="step6-next-btn",
                    color="primary",
                    disabled=True,
                ),
                width="auto",
            ),
        ], justify="between"),

        # /dash/step7 lives within the Dash mount, so this could in
        # principle ride on the root url Location's pathname. We keep a
        # dedicated refresh=True Location for symmetry with Step 4 (whose
        # downstream /step5 is outside the Dash mount and DOES need the
        # full reload). Either works for /dash/step7.
        dcc.Location(id="step6-redirect", refresh=True),
    ])


# ==================== callbacks ====================

@dash_app.callback(
    Output("step6-next-btn", "disabled"),
    Input("step6-expectation-vs-reality", "value"),
    Input("step6-consider-willingness", "value"),
)
def toggle_step6_next(q1, q2):
    """Lock Next until both Likert questions are answered."""
    return q1 is None or q2 is None


@dash_app.callback(
    Output("step6-redirect", "href"),
    Output("step6-error", "children"),
    Input("step6-next-btn", "n_clicks"),
    State("step6-expectation-vs-reality", "value"),
    State("step6-consider-willingness", "value"),
    State("url", "search"),
    prevent_initial_call=True,
)
def submit_step6(n_clicks, q1, q2, search):
    """Persist Q6-1 onto survey_responses + Q6-2 as round-2 willingness, nav to Step 7."""
    if not n_clicks:
        return no_update, no_update

    session_id = _parse_session_id(search)
    if not session_id:
        return no_update, "Session id missing — please start from '/'."
    if q1 is None or q2 is None:
        return no_update, "Please answer both questions."

    from vec_platform.models import (
        Session as SessionModel,
        WillingnessMeasurement,
    )
    from vec_platform.pages._survey_helpers import get_or_create_survey_row

    db = SessionLocal()
    try:
        sess = db.query(SessionModel).filter(SessionModel.id == session_id).first()
        if sess is None:
            return no_update, "Session not found."

        # Q6-1: upsert disappointment Likert onto the per-session survey row.
        row = get_or_create_survey_row(db, session_id)
        row.step6_expectation_vs_reality = int(q1)

        # Q6-2: Phase 3.2b's willingness_measurements table holds three
        # measurements per session (info_calibration / Step 6 / Step 8).
        # Defensive idempotency: skip the insert if a round=2 row already
        # exists for this session, so a double-click doesn't double-insert.
        existing = (
            db.query(WillingnessMeasurement)
            .filter(
                WillingnessMeasurement.session_id == session_id,
                WillingnessMeasurement.round == 2,
            )
            .first()
        )
        if existing is None:
            db.add(WillingnessMeasurement(
                session_id=session_id,
                round=2,
                scale_type="5point_consider",
                value=int(q2),
            ))

        if sess.current_step is None or sess.current_step < 7:
            sess.current_step = 7
        db.commit()
    finally:
        db.close()

    return f"/dash/step7?session_id={session_id}", ""
