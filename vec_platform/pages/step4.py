"""Step 4 — tomorrow's VEC shadow prices + savings card.

Pure layout module: lazily creates the ShadowPrices row on first visit,
then reads no_vec / vec_no_adjust bills to drive a side-by-side savings
card.
"""

import json

from dash import html, dcc
import dash_bootstrap_components as dbc
import plotly.graph_objects as go

from vec_platform.config import SLOTS_PER_DAY
from vec_platform.runtime import SessionLocal, calculation_engine
from vec_platform.pages._helpers import _slot_to_hour


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
