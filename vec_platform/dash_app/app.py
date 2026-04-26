"""Dash app initialization and multi-page setup."""

from dash import Dash, html
from dash.dependencies import Input, Output, State
import dash_bootstrap_components as dbc

# Create Dash app
def create_dash_app(server):
    """Create and configure Dash app with multi-page support."""
    
    dash_app = Dash(
        __name__,
        server=server,
        url_base_pathname="/dash/",
        suppress_callback_exceptions=True,
        external_stylesheets=[dbc.themes.BOOTSTRAP],
    )
    
    # Navigation component
    nav_bar = html.Div([
        dbc.Navbar(
            [
                html.A(
                    dbc.Row([
                        dbc.Col(html.B("VEC Platform")),
                    ]),
                    href="/dash/",
                    className="navbar-brand",
                ),
                dbc.NavbarToggler(id="navbar-toggler"),
                dbc.Collapse(
                    dbc.Nav([
                        dbc.NavItem(dbc.NavLink("Step 1: Role", href="/dash/step1")),
                        dbc.NavItem(dbc.NavLink("Step 2: Profile", href="/dash/step2")),
                        dbc.NavItem(dbc.NavLink("Step 3: Customize", href="/dash/step3")),
                        dbc.NavItem(dbc.NavLink("Step 4: Prices", href="/dash/step4")),
                        dbc.NavItem(dbc.NavLink("Step 5: Respond", href="/dash/step5")),
                        dbc.NavItem(dbc.NavLink("Step 6: Compare", href="/dash/step6")),
                        dbc.NavItem(dbc.NavLink("Step 7: Impacts", href="/dash/step7")),
                        dbc.NavItem(dbc.NavLink("Step 8: Survey", href="/dash/step8")),
                    ], className="ml-auto"),
                    id="navbar-collapse",
                    navbar=True,
                ),
            ],
            color="dark",
            dark=True,
        ),
    ], className="mb-4")
    
    # Main layout
    dash_app.layout = html.Div([
        nav_bar,
        html.Div(id="page-content"),
    ])
    
    return dash_app


# Page registry
PAGES = {}


def register_page(path, layout_func):
    """Register a page with its layout function."""
    PAGES[path] = layout_func