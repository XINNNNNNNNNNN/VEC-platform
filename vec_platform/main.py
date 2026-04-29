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
from vec_platform.pages import step6 as _step6
from vec_platform.pages import step7 as _step7


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
        return _step6.step6_layout(session_id), make_progress(6)
    elif pathname == "/dash/step7":
        return _step7.step7_layout(session_id), make_progress(7)
    elif pathname == "/dash/step8":
        return step8_layout(session_id), make_progress(8)
    else:
        return html.Div([
            html.H3("Page not found"),
            html.P(f"No page for: {pathname}"),
            dbc.Button("Go to Step 1", href="/dash/step1", color="primary"),
        ]), make_progress(1)


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