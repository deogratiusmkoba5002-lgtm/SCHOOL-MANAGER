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
    os.environ["ALERT_EMAIL_TO"] = ""
    os.environ["ALERT_EMAIL_API_KEY"] = ""
    os.environ["ALERT_SMTP_HOST"] = ""
    os.environ["SLOW_REQUEST_SECONDS"] = "0"
    return url


TEST_DATABASE_URL = _configure_environment()


@pytest.fixture(scope="session")
def app():
    import app as app_module          # runs init_db() against the TEST database
    app_module.app.config.update(TESTING=True)
    return app_module.app


_RESETTABLE = None   # the table list is fixed for the whole session


def _reset_database():
    global _RESETTABLE
    from core.db import get_db
    con = get_db(); cur = con.cursor()
    try:
        cur.execute("SELECT current_database()")
        name = cur.fetchone()[0]
        if not name.endswith("_test"):
            raise RuntimeError(f"SAFETY STOP: connected to '{name}', not a test database")
        if _RESETTABLE is None:
            cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")
            _RESETTABLE = [r[0] for r in cur.fetchall() if r[0] not in KEEP_TABLES]
        if _RESETTABLE:
            cur.execute(" UNION ALL ".join(
                f"SELECT '{t}' WHERE EXISTS (SELECT 1 FROM \"{t}\")" for t in _RESETTABLE))
            dirty = [r[0] for r in cur.fetchall()]
            if dirty:
                cur.execute("TRUNCATE " + ", ".join(f'"{t}"' for t in dirty) + " RESTART IDENTITY CASCADE")
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

# ══ Phase 9: auto-markers + "what broke" summary ═════════════════
from collections import defaultdict

_AREA_BY_FILE = {
    "test_foundation.py": "foundation",
    "test_health_and_slow.py": "monitoring",
    "test_workflows.py": "workflows",
    "test_e2e_workflow.py": "workflows",
    "test_security.py": "security",
}
_AREAS = ["foundation", "monitoring", "workflows", "security"]
_COLS = ["passed", "failed", "error", "xfailed", "XPASS", "skipped"]
_RESULTS = defaultdict(lambda: defaultdict(int))
_BROKEN = []


def _area_of(nodeid):
    fname = nodeid.split("::")[0].replace("\\", "/").rsplit("/", 1)[-1]
    if fname in _AREA_BY_FILE:
        return _AREA_BY_FILE[fname]
    if fname.startswith("test_monitoring"):
        return "monitoring"
    return "other"


def pytest_collection_modifyitems(items):
    """Every test gets its area marker from its file name, so `pytest -m security` just works."""
    for item in items:
        area = _area_of(item.nodeid)
        if area in _AREAS:
            item.add_marker(getattr(pytest.mark, area))


def pytest_runtest_logreport(report):
    area = _area_of(report.nodeid)
    if report.when == "call":
        if hasattr(report, "wasxfail"):
            outcome = "xfailed" if report.skipped else "XPASS"
        else:
            outcome = report.outcome
    elif report.outcome == "failed":
        outcome = "error"                      # setup/teardown blew up
    elif report.outcome == "skipped" and report.when == "setup":
        outcome = "skipped"
    else:
        return
    _RESULTS[area][outcome] += 1
    if outcome in ("failed", "error"):
        _BROKEN.append((area, report.nodeid.split("::", 1)[-1]))


def pytest_terminal_summary(terminalreporter):
    if not _RESULTS:
        return
    tr = terminalreporter
    tr.section("DrDemic regression summary")
    tr.write_line(f"{'AREA':<13}" + "".join(f"{c:>9}" for c in _COLS))
    for area in _AREAS + ["other"]:
        if area in _RESULTS:
            tr.write_line(f"{area:<13}" + "".join(f"{_RESULTS[area][c]:>9}" for c in _COLS))
    tr.write_line("")
    if _BROKEN:
        tr.write_line("VERDICT: BROKEN. What failed:", red=True, bold=True)
        for area, name in _BROKEN:
            tr.write_line(f"  [{area}] {name}", red=True)
    else:
        tr.write_line("VERDICT: ALL CLEAR", green=True, bold=True)
    stale = sum(r["XPASS"] for r in _RESULTS.values())
    if stale:
        tr.write_line(f"NOTE: {stale} XPASS = a known bug got fixed; delete that test's xfail marker.", yellow=True)