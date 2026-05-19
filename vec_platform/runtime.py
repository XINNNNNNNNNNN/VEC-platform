"""Shared runtime singletons used by main.py and pages/*.

Holding the SQLAlchemy engine, session factory, calculation engine and the
Dash app instance in their own module avoids circular imports between
main.py and the page modules (each page registers callbacks against
``dash_app`` and reads/writes via ``SessionLocal``).

main.py re-imports these symbols so the existing ``from vec_platform.main
import get_db, calculation_engine`` paths in vec_platform/api/* keep
working without any change there.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from dash import Dash
import dash_bootstrap_components as dbc

from vec_platform.config import DATABASE_URL, DEBUG
from vec_platform.engine import MockEngine

# ==================== Database ====================
# Schema is managed by Alembic — run `alembic upgrade head` before starting
# the app on a fresh database.
engine = create_engine(DATABASE_URL, echo=DEBUG)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """FastAPI dependency: yield a SQLAlchemy session, close it after."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Global calculation engine
calculation_engine = MockEngine()


# ==================== Dash App ====================
dash_app = Dash(
    __name__,
    requests_pathname_prefix="/dash/",
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    suppress_callback_exceptions=True,
)

# Hotfix v3 (2026-05-19): Hotfix v1's dash_app.enable_dev_tools(
# debug=True, ...) call broke HTTP serving — every route returned a
# blank page. Dash's debug mode expects to drive its own Flask dev
# server via dash_app.run(); calling enable_dev_tools at import time
# under a FastAPI/Starlette WSGI mount subverts the dispatch path.
#
# Disabled until we have a safe way to surface tracebacks under the
# Starlette wrapper (likely: a custom Starlette error middleware
# that catches WSGI exceptions and logs them, instead of relying on
# Dash dev tools).
#
# When debugging a callback 500 in the meantime, the workflow is:
#   1. Replicate the failing callback by importing it directly:
#      `python -c "from vec_platform.pages.step0 import welcome_state3_submit; import traceback
#                   try: r = welcome_state3_submit(1, '?session_id=...')
#                   except: traceback.print_exc()"`
#   2. If the in-process call succeeds but the HTTP request 500s,
#      the bug is in Dash's callback registration / Output conflict
#      (check allow_duplicate=True coverage, prevent_initial_call).
#
# dash_app.enable_dev_tools(
#     debug=True,
#     dev_tools_ui=True,
#     dev_tools_props_check=False,
#     dev_tools_serve_dev_bundles=False,
#     dev_tools_hot_reload=False,
#     dev_tools_silence_routes_logging=True,
#     dev_tools_prune_errors=True,
# )
