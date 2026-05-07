"""VEC Platform - FastAPI main server with Dash mounted via WSGI middleware.

Layout-only entrypoint: imports the runtime singletons + each page module
(which registers its own callbacks), wires the Dash routing callback to
the page-level layouts, and exposes the FastAPI app object.
"""

import random
import uuid
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
from starlette.middleware.wsgi import WSGIMiddleware
from starlette.types import Scope


class NoCacheStaticFiles(StaticFiles):
    """StaticFiles subclass that disables HTTP caching.

    Phase 3.X-fix-5d: prevent browsers from serving stale JS/CSS during
    development and after platform updates. Without this, users who
    visited a previous version may keep running outdated client-side
    code indefinitely (this caused the fix-5c data-loss bug across
    multiple test sessions: server already had the fix-5c JS on disk,
    but participants' browsers kept replaying the pre-fix JS so all
    Step 3 device-shift POSTs were silently skipped).

    The triple no-store / no-cache / must-revalidate is belt-and-braces
    against various browser caching layers (HTTP cache, BFCache,
    intermediate proxies). Pragma + Expires=0 cover legacy HTTP/1.0.
    """

    async def get_response(self, path: str, scope: Scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

from dash import html, dcc
from dash.dependencies import Input, Output, State
import dash_bootstrap_components as dbc

# Re-export the runtime singletons so existing imports such as
# `from vec_platform.main import get_db, calculation_engine` (used by
# vec_platform/api/*) keep working without churn in those modules.
from vec_platform.runtime import (
    SessionLocal,
    calculation_engine,
    get_db,
    dash_app,
)
from vec_platform.pages._helpers import _parse_session_id, make_progress
# Importing each page module registers its Dash callbacks against
# runtime.dash_app. Order doesn't matter as long as they're imported before
# the first request (so before uvicorn finishes app construction).
# Phase 4-A: removed _step2 (mock baseline page deleted) and renumbered
# step4/6/7/8 → step3/5/6/7. Static respond/customize pages (Steps 3+5
# in the old numbering, Steps 2+4 in the new flow) are still served
# below by FastAPI at the historical /step3 and /step5 URLs (decision
# 1B preserves URLs for blast-radius control).
from vec_platform.pages import step0 as _step0
from vec_platform.pages import step1 as _step1
from vec_platform.pages import step3 as _step3
from vec_platform.pages import step5 as _step5
from vec_platform.pages import step6 as _step6
from vec_platform.pages import step7 as _step7
from vec_platform.pages import tenant_disclaimer as _tenant_disclaimer
from vec_platform.pages import info_calibration as _info_calibration


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
@dash_app.callback(
    Output("page-content", "children"),
    Output("progress-bar", "children"),
    Input("url", "pathname"),
    State("url", "search"),
)
def display_page(pathname, search):
    """Route to the correct page based on URL."""
    session_id = _parse_session_id(search)

    # Phase 4-A: 7-step flow. /dash/step2 (mock baseline page) deleted;
    # other Dash routes shifted down by one. The static customize page
    # (now flow Step 2) lives at /step3 and the respond page (now flow
    # Step 4) lives at /step5 — both URLs preserved per decision 1B.
    if pathname == "/dash/step0":
        return _step0.step0_layout(session_id), make_progress(0)
    elif pathname in (None, "/dash/", "/dash", "/dash/step1"):
        return _step1.step1_layout(session_id), make_progress(1)
    elif pathname == "/dash/tenant_disclaimer":
        # Intermediate page between Step 1 and the info-calibration arm;
        # we keep the progress bar showing Step 1 because the participant
        # hasn't generated a profile yet.
        return _tenant_disclaimer.tenant_disclaimer_layout(session_id), make_progress(1)
    elif pathname == "/dash/info_calibration":
        return _info_calibration.info_calibration_layout(session_id), make_progress(1)
    elif pathname == "/dash/step3":
        return _step3.step3_layout(session_id), make_progress(3)
    elif pathname == "/dash/step5":
        return _step5.step5_layout(session_id), make_progress(5)
    elif pathname == "/dash/step6":
        return _step6.step6_layout(session_id), make_progress(6)
    elif pathname == "/dash/step7":
        return _step7.step7_layout(session_id), make_progress(7)
    else:
        return html.Div([
            html.H3("Page not found"),
            html.P(f"No page for: {pathname}"),
            dbc.Button("Go to Step 1", href="/dash/step1", color="primary"),
        ]), make_progress(1)


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
    """Create a new session and redirect to Step 0.

    Each session is randomly assigned to one of three info-calibration
    arms (A/B/C) at creation time. The arm controls framing on the
    intermediate ``/dash/info_calibration`` page that sits between
    Step 1 and the (Phase 4-A renumbered) Step 2 customize page.
    """
    session_id = str(uuid.uuid4())
    arm = random.choice(["A", "B", "C"])

    db = SessionLocal()
    try:
        from vec_platform.models import Session
        session = Session(
            id=session_id,
            current_step=0,
            info_calibration_arm=arm,
        )
        db.add(session)
        db.commit()
    finally:
        db.close()

    return RedirectResponse(url=f"/dash/step0?session_id={session_id}")


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
    fastapi_app.mount("/static", NoCacheStaticFiles(directory=str(static_path)), name="static")


# Export for uvicorn: uvicorn vec_platform.main:app --reload
app = fastapi_app
__all__ = ["app", "get_db", "calculation_engine", "SessionLocal", "dash_app"]