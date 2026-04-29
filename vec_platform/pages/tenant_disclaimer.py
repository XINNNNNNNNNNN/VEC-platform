"""Tenant disclaimer — a static between-page shown only to renters.

Tenants in Sweden often have electricity bundled into rent, so the rest of
the study (which assumes the participant directly owns the electricity
contract) doesn't map cleanly to their reality. This page is a brief
hypothetical-framing notice; renters tap Continue and proceed to the
info-calibration page like everyone else.

No data is written here — it's purely a routing waypoint.

Importing this module registers one Dash callback against ``dash_app``.
"""

from dash import html, dcc, no_update
from dash.dependencies import Input, Output, State
import dash_bootstrap_components as dbc

from vec_platform.runtime import dash_app
from vec_platform.pages._helpers import _parse_session_id


_DISCLAIMER_MD = """
**For tenants: a hypothetical exercise**

The rest of this study assumes that you (as a tenant) could freely choose
to join a Virtual Energy Community and would directly receive any savings
on your electricity bill. In reality, tenants in Sweden often have
electricity bundled into rent, or limited control over their utility
contract — so the scenarios you'll see may not directly apply to your
current situation.

We ask you to imagine yourself in a position where you do have direct
control over your electricity bill, just for the purposes of this study.
Please answer all questions from that imagined perspective.
"""


def tenant_disclaimer_layout(session_id: str | None = None):
    return html.Div([
        html.H2("A note for tenants"),

        dbc.Card([
            dbc.CardBody(dcc.Markdown(_DISCLAIMER_MD)),
        ], className="mb-3"),

        dbc.Button(
            "Continue",
            id="tenant-disclaimer-continue",
            color="primary",
            size="lg",
        ),
    ])


@dash_app.callback(
    Output("url", "pathname", allow_duplicate=True),
    Output("url", "search", allow_duplicate=True),
    Input("tenant-disclaimer-continue", "n_clicks"),
    State("url", "search"),
    prevent_initial_call=True,
)
def submit_tenant_disclaimer(n_clicks, search):
    """No-op DB write — just route the tenant to the info-calibration page."""
    if not n_clicks:
        return no_update, no_update
    session_id = _parse_session_id(search)
    if not session_id:
        return no_update, no_update
    return "/dash/info_calibration", f"?session_id={session_id}"
