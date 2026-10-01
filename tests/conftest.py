"""
Test foundation. IMPORTANT: environment is configured at import time, BEFORE
`app` is imported, because config.py / core/db.py read env vars once at import.
"""
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env.test")
except ImportError:
    pass

DEFAULT_PASSWORD = "pass1234"
# Tables seeded by init_db() that tests rely on and must survive cleanup.
KEEP_TABLES = {"necta_grades", "necta_divisions", "platform_payment_config",
               "superadmins", "_subscription_migration"}


def _configure_environment():
    url = os.environ.get("TEST_DATABASE_URL", "").strip()
    if not url:
        pytest.exit("TEST_DATABASE_URL is not set. Put it in .env.test "
                    "(see Phase 2 instructions). Refusing to run.", returncode=2)
    parsed = urlparse(url)
    dbname = (parsed.path or "").lstrip("/")
    if not dbname.endswith("_test"):
        pytest.exit(f"Refusing to run: test database name must end with '_test' (got '{dbname}').", returncode=2)
    if parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
        pytest.exit(f"Refusing to run: test database host must be local (got '{parsed.hostname}').", returncode=2)

    os.environ["DATABASE_URL"] = url            # overrides anything from .env
    os.environ["SECRET_KEY"] = "test-secret-key-not-for-production"
    os.environ["SNIPPE_API_KEY"] = ""
    os.environ["SNIPPE_WEBHOOK_SECRET"] = ""
    os.environ["PUBLIC_BASE_URL"] = ""
    os.environ["SCHOOL_SUBSCRIPTION_ENFORCED"] = "0"
    os.environ["SUPERADMIN_USERNAME"] = "test_superadmin"
    os.environ["SUPERADMIN_PASSWORD"] = "test_superadmin_pw"
    return url


TEST_DATABASE_URL = _configure_environment()


@pytest.fixture(scope="session")
def app():
    import app as app_module          # runs init_db() against the TEST database
    app_module.app.config.update(TESTING=True)
    return app_module.app


def _reset_database():
    from core.db import get_db
    con = get_db(); cur = con.cursor()
    try:
        cur.execute("SELECT current_database()")
        name = cur.fetchone()[0]
        if not name.endswith("_test"):
            raise RuntimeError(f"SAFETY STOP: connected to '{name}', not a test database")
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")
        tables = [r[0] for r in cur.fetchall() if r[0] not in KEEP_TABLES]
        if tables:
            cur.execute("TRUNCATE " + ", ".join(f'"{t}"' for t in tables) + " RESTART IDENTITY CASCADE")
        con.commit()
    except Exception:
        con.rollback(); raise
    finally:
        cur.close(); con.close()


@pytest.fixture(autouse=True)
def clean_db(app):
    """Every test starts with empty tables (data is left in place afterwards so you can inspect it)."""
    _reset_database()


@pytest.fixture
def reset_db():
    return _reset_database


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    def _blocked(*a, **k):
        raise RuntimeError("Network access is blocked in tests. Mock it explicitly.")
    monkeypatch.setattr("requests.sessions.Session.request", _blocked)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def login(client):
    """login(school, username, password=DEFAULT_PASSWORD) -> {'Authorization': 'Bearer ...'}"""
    def _login(school, username, password=DEFAULT_PASSWORD):
        r = client.post("/api/login", json={"reg_code": school["reg_code"],
                                            "username": username, "password": password})
        body = r.get_json()
        assert r.status_code == 200 and body and body.get("ok"), f"login failed: {r.status_code} {body}"
        return {"Authorization": f"Bearer {body['token']}"}
    return _login