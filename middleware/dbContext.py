"""Ensures the scoped SQLAlchemy session is removed at the end of every
request so connections are returned to the pool cleanly."""
from database.dbConnection import SessionLocal


def register_db_teardown(app):
    @app.teardown_appcontext
    def remove_session(_exception=None):
        SessionLocal.remove()
