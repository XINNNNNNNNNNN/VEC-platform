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
