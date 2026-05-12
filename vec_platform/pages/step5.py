"""Step 5 — three-way bill comparison + disappointment & consider Likerts.

Phase 4-A: renumbered from Step 6 (8-step flow) to Step 5 (7-step flow).
File renamed step6.py → step5.py; identifiers, DB column names, and UI
labels updated accordingly. Data step values in daily_profiles /
device_shifts are preserved (decision 2a), so internal step= filters
still query 2/3/5 unchanged.

Pulls per-scenario bills (preferring the right ``step``) plus
baseline / customized / responded profiles, builds three summary cards,
a breakdown table and a three-line net-load chart. Two follow-up
questions at the bottom:

  Q1 disappointment vs expectation — 5-point Likert, persisted on
     survey_responses.step5_expectation_vs_reality
  Q2 would-you-consider Likert — 5-point, persisted as
     willingness_measurements(round=2, scale_type='5point_consider')
     to keep all three willingness measurements (info_calibration /
     Step 5 / Step 7) in one uniform table

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


# ==================== Step 5 ====================

def _pick_scenario_bill(db, session_id: str, scenario: str, preferred_step: int):
    """Find the right bill for each scenario, falling back sensibly.

    Phase K-2 F1: for the step=2 baseline scenario, the bill is
    regenerated on the fly from the current ``user_inputs`` row rather
    than read from the frozen ``bill_breakdowns`` snapshot written at
    Step 1 submit. Without this, a participant who calibrated PV
    capacity (Phase C) on the customize page would still see the
    pre-calibration default-PV baseline on the Step 5 compare page —
    making the "without VEC" anchor inconsistent with everything else
    on the page.

    step=3 (customize) and step=5 (responded) keep reading the
    DB-persisted snapshot, since those are correctly written by
    /api/recalculate at submit time with current user_input state.
    """
    from vec_platform.models import BillBreakdown, UserInput, DailyProfile
    from vec_platform.runtime import calculation_engine
    import json as _json

    if preferred_step == 2:
        ui = (
            db.query(UserInput)
            .filter(UserInput.session_id == session_id)
            .order_by(UserInput.id.desc())
            .first()
        )
        if ui is not None:
            # Regenerate baseline profile from current user_input,
            # then apply load_scale_factor before computing the bill
            # so the same scaling the user sees on the customize page
            # is reflected here too.
            fresh = calculation_engine.generate_profile(ui)
            scale = float(ui.load_scale_factor or 1.0)
            rigid = [v * scale for v in _json.loads(fresh.rigid_load)]
            flex = _json.loads(fresh.flexible_load)
            pv = _json.loads(fresh.pv_generation)
            net = [rigid[i] + flex[i] - pv[i] for i in range(len(rigid))]
            profile_view = DailyProfile(
                session_id=session_id,
                step=2,
                rigid_load=_json.dumps(rigid),
                flexible_load=_json.dumps(flex),
                pv_generation=_json.dumps(pv),
                net_load=_json.dumps(net),
                devices=fresh.devices,
            )
            # Phase N F6: pass ui.area_m2 so lazy regen matches the
            # cascade-rewritten DB row and frontend live preview.
            return calculation_engine.calculate_bill(
                profile_view, scenario, area_m2=ui.area_m2,
            )

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


# Phase 4-A: data step values preserved — preferred_step still uses
# 2/3/5 (baseline / customized / responded) regardless of UI flow
# renumbering.
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
    """Three-line comparison chart. Trace names use the data-step labels
    (baseline=step 2, customized=step 3, responded=step 5) which match
    the scenario semantics regardless of UI flow renumbering."""
    hours = [_slot_to_hour(i) for i in range(SLOTS_PER_DAY)]
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=hours, y=net_baseline,
        name="Baseline",
        mode="lines",
        line=dict(color="#adb5bd", width=1.5, dash="dash"),
        hovertemplate="%{y:.2f} kW<extra>Baseline</extra>",
    ))
    fig.add_trace(go.Scatter(
        x=hours, y=net_customized,
        name="Customized (Step 2)",
        mode="lines",
        line=dict(color="#3498db", width=2),
        hovertemplate="%{y:.2f} kW<extra>Customized</extra>",
    ))
    fig.add_trace(go.Scatter(
        x=hours, y=net_responsive,
        name="After responding (Step 4)",
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


def step5_layout(session_id: str | None):
    if not session_id:
        return html.Div([
            html.H2("Step 5: Your savings breakdown"),
            dbc.Alert("No session found. Please start from Step 1.", color="warning"),
        ])

    db = SessionLocal()
    try:
        bills = {
            s: _pick_scenario_bill(db, session_id, s, _SCENARIO_META[s]["preferred_step"])
            for s in ("no_vec", "vec_no_adjust", "vec_adjusted")
        }
        # Phase 4-A: data step values preserved (decision 2a) so the
        # query keys 2/3/5 still match baseline/customized/responded.
        p2 = _get_profile_at_step(db, session_id, 2)
        p3 = _get_profile_at_step(db, session_id, 3) or p2
        p5 = _get_profile_at_step(db, session_id, 5) or p3
    finally:
        db.close()

    if any(b is None for b in bills.values()) or p2 is None:
        return html.Div([
            html.H2("Step 5: Your savings breakdown"),
            dbc.Alert(
                "Missing bill or profile data — please complete Step 1–4 first.",
                color="warning",
            ),
        ])

    baseline_net = bills["no_vec"].net_cost

    net_baseline = json.loads(p2.net_load)
    net_customized = json.loads(p3.net_load)
    net_responsive = json.loads(p5.net_load)

    return html.Div([
        html.H2("Step 5: Your savings breakdown"),
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

        # ----- disappointment + consider Likerts -----
        html.Hr(),
        dbc.Card([
            dbc.CardBody([
                html.H4(
                    "Looking at how much the three options would actually save "
                    "you, how does this compare to what you expected before "
                    "seeing your own profile?"
                ),
                dcc.RadioItems(
                    id="step5-expectation-vs-reality",
                    options=[
                        {"label": "1 — Much less than I expected",  "value": 1},
                        {"label": "2 — Less than I expected",       "value": 2},
                        {"label": "3 — About what I expected",      "value": 3},
                        {"label": "4 — More than I expected",       "value": 4},
                        {"label": "5 — Much more than I expected",  "value": 5},
                    ],
                    value=None,
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
                    id="step5-consider-willingness",
                    options=[
                        {"label": "1 — Definitely not",   "value": 1},
                        {"label": "2 — Probably not",     "value": 2},
                        {"label": "3 — Maybe",            "value": 3},
                        {"label": "4 — Probably yes",     "value": 4},
                        {"label": "5 — Definitely yes",   "value": 5},
                    ],
                    value=None,
                    labelStyle={"display": "block", "padding": "0.3rem 0"},
                ),
                html.Div(id="step5-error", className="text-danger small mt-2"),
            ]),
        ], className="mb-3"),

        dbc.Row([
            dbc.Col(
                dbc.Button(
                    "Next → Broader impacts",
                    id="step5-next-btn",
                    color="primary",
                    disabled=True,
                ),
                width="auto",
            ),
        ], justify="end"),

        # /dash/step6 lives within the Dash mount; the dedicated
        # refresh=True Location keeps symmetry with Step 3 (whose
        # downstream /step5 is outside the Dash mount and DOES need the
        # full reload). Either approach works for /dash/step6.
        dcc.Location(id="step5-redirect", refresh=True),
    ])


# ==================== callbacks ====================

@dash_app.callback(
    Output("step5-next-btn", "disabled"),
    Input("step5-expectation-vs-reality", "value"),
    Input("step5-consider-willingness", "value"),
)
def toggle_step5_next(q1, q2):
    """Lock Next until both Likert questions are answered."""
    return q1 is None or q2 is None


@dash_app.callback(
    Output("step5-redirect", "href"),
    Output("step5-error", "children"),
    Input("step5-next-btn", "n_clicks"),
    State("step5-expectation-vs-reality", "value"),
    State("step5-consider-willingness", "value"),
    State("url", "search"),
    prevent_initial_call=True,
)
def submit_step5(n_clicks, q1, q2, search):
    """Persist Q1 onto survey_responses + Q2 as round-2 willingness, nav to Step 6."""
    if not n_clicks:
        return no_update, no_update

    session_id = _parse_session_id(search)
    if not session_id:
        return no_update, "Session id missing — please start from '/'."
    if q1 is None or q2 is None:
        return no_update, "Please answer both questions."

    from vec_platform.models import Session as SessionModel
    from vec_platform.pages._survey_helpers import get_or_create_survey_row
    from vec_platform.pages._upsert_helpers import upsert_willingness

    db = SessionLocal()
    try:
        sess = db.query(SessionModel).filter(SessionModel.id == session_id).first()
        if sess is None:
            return no_update, "Session not found."

        # Q1: upsert disappointment Likert onto the per-session survey row.
        row = get_or_create_survey_row(db, session_id)
        row.step5_expectation_vs_reality = int(q1)

        # Q2: willingness_measurements table holds three measurements
        # per session (info_calibration / Step 5 / Step 7). Phase E:
        # switched from defensive-idempotency (which silently dropped
        # the new value on resubmit) to an explicit upsert that records
        # the participant's latest answer.
        upsert_willingness(
            db, session_id,
            round_=2,
            scale_type="5point_consider",
            value=q2,
        )

        # Phase 4-A: advance to current_step=6 (next page is impacts,
        # which is "Step 6" in the new 7-step flow).
        if sess.current_step is None or sess.current_step < 6:
            sess.current_step = 6
        db.commit()
    finally:
        db.close()

    return f"/dash/step6?session_id={session_id}", ""
