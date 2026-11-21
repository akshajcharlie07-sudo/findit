"""Central configuration for FindIt."""
import os
from datetime import timedelta

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
ON_VERCEL = bool(os.environ.get("VERCEL"))


class Config:
    # IMPORTANT: set SECRET_KEY as an environment variable in production.
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me-in-production")

    # Database. Vercel's filesystem is read-only except /tmp (which is temporary).
    DATABASE = os.environ.get("FINDIT_DB") or (
        "/tmp/findit.db" if ON_VERCEL else os.path.join(BASE_DIR, "database", "findit.db")
    )
    SEED_DEMO_DATA = os.environ.get("SEED_DEMO_DATA", "1") == "1"

    # Uploads (images are validated, re-encoded and stored in the database).
    # Vercel limits request bodies to ~4.5 MB, so we cap at 4 MB.
    MAX_CONTENT_LENGTH = 4 * 1024 * 1024
    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}

    # Sessions / cookies
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = ON_VERCEL or os.environ.get("FLASK_ENV") == "production"

    # CSRF (Flask-WTF)
    WTF_CSRF_TIME_LIMIT = 3600

    ITEMS_PER_PAGE = 9
