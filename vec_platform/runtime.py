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

# Hotfix (state_3 500): turn on dev tools so callback exceptions
# surface as full Python tracebacks in the uvicorn terminal + an
# in-browser red banner, instead of being swallowed into a generic
# 500 Internal Server Error from the Flask error handler.
#
# dev_tools_silence_routes_logging=True keeps the per-request access
# log readable (otherwise Dash spams every poll/heartbeat). All
# other tools enabled.
#
# Production-deployment note: this also enables hot reload of
# component JS bundles in the browser, which is fine for dogfood +
# pilot but should be flagged before Render production deployment
# (Render production should run with debug=False).
dash_app.enable_dev_tools(
    debug=True,
    dev_tools_ui=True,
    dev_tools_props_check=False,  # noisy, not useful for callback errors
    dev_tools_serve_dev_bundles=False,
    dev_tools_hot_reload=False,
    dev_tools_silence_routes_logging=True,
    dev_tools_prune_errors=True,
)
