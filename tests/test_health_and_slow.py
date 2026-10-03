"""Phase 6: /health and slow-request detection."""
import time

import psycopg2
import pytest
from flask import Flask, g, request

from core.db import get_db, to_dicts
from core.monitoring import init_monitoring
from routes.health_routes import health_bp
from tests.factories import make_school, make_admin


def _rows(sql):
    con = get_db(); cur = con.cursor()
    try:
        cur.execute(sql)
        return to_dicts(cur.fetchall(), cur)
    finally:
        cur.close(); con.close()


def _events(): return _rows("SELECT * FROM error_events ORDER BY id")
def _groups(): return _rows("SELECT * FROM error_groups ORDER BY id")


# ── HEALTH ──────────────────────────────────────────────────────
def test_health_ok_without_auth(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.get_json() == {"status": "ok", "db": "ok"}
    assert r.headers["Cache-Control"] == "no-store"


def test_health_leaks_nothing(client):
    body = client.get("/health").get_data(as_text=True).lower()
    for needle in ("postgres", "localhost", "_test", "password", "traceback"):
        assert needle not in body


def test_health_reports_db_outage_safely_and_records_no_event(client, monkeypatch):
    def no_db(*a, **k):
        raise psycopg2.OperationalError("password authentication failed for user bob at 10.0.0.5")
    with monkeypatch.context() as m:
        m.setattr("psycopg2.connect", no_db)
        r = client.get("/health")
    assert r.status_code == 503 and r.get_json() == {"status": "degraded", "db": "unreachable"}
    body = r.get_data(as_text=True).lower()
    assert "bob" not in body and "10.0.0.5" not in body and "password" not in body
    assert _events() == []


# ── SLOW REQUESTS ───────────────────────────────────────────────
@pytest.fixture
def slow(app, monkeypatch):
    monkeypatch.setenv("SLOW_REQUEST_SECONDS", "0.2")
    a = Flask("slow_test_app")
    a.config["TESTING"] = True
    init_monitoring(a)
    a.register_blueprint(health_bp)

    @a.route("/slow")
    def slow_route():
        if request.args.get("s"):
            g.school_id = int(request.args["s"])
        time.sleep(0.3)
        return "ok"

    @a.route("/fast")
    def fast_route():
        return "ok"

    @a.route("/slow-boom")
    def slow_boom():
        time.sleep(0.3)
        raise RuntimeError("slow and broken")

    return a.test_client()


def test_slow_request_is_recorded(slow):
    school = make_school("Slow School")
    r = slow.get(f"/slow?s={school['id']}")
    assert r.status_code == 200 and r.get_data(as_text=True) == "ok"      # user is unaffected
    rows = _events()
    assert len(rows) == 1
    e = rows[0]
    assert (e["severity"], e["kind"], e["school_id"], e["endpoint"]) == ("WARNING", "event", school["id"], "slow_route")
    assert e["message"].startswith("Slow request: ") and "threshold 0.2s" in e["message"]
    assert e["traceback"] is None and e["exception_type"] is None


def test_fast_request_is_not_recorded(slow):
    assert slow.get("/fast").status_code == 200
    assert _events() == []


def test_threshold_zero_disables_detection(slow, monkeypatch):
    monkeypatch.setenv("SLOW_REQUEST_SECONDS", "0")
    slow.get("/slow")
    assert _events() == []


def test_repeated_slow_requests_form_one_group(slow):
    for _ in range(3):
        slow.get("/slow")
    gs = _groups()
    assert len(gs) == 1 and gs[0]["occurrence_count"] == 3 and gs[0]["severity"] == "WARNING"


def test_slow_failure_is_one_exception_event_not_two(slow):
    assert slow.get("/slow-boom").status_code == 500
    rows = _events()
    assert len(rows) == 1 and rows[0]["exception_type"] == "RuntimeError"


def test_health_is_never_reported_as_slow(slow, monkeypatch):
    monkeypatch.setenv("SLOW_REQUEST_SECONDS", "0.000001")
    assert slow.get("/health").status_code == 200
    assert _events() == []


def test_slow_check_failure_never_breaks_the_response(slow, monkeypatch):
    def broken(*a, **k):
        raise RuntimeError("monitor bug")
    monkeypatch.setattr("core.monitoring.record_event", broken)
    r = slow.get("/slow")
    assert r.status_code == 200 and r.get_data(as_text=True) == "ok"


def test_real_app_slow_request_has_operation_and_context(client, login, monkeypatch):
    school = make_school(); admin = make_admin(school)
    headers = login(school, admin["username"])
    monkeypatch.setenv("SLOW_REQUEST_SECONDS", "0.000001")      # everything counts as slow
    assert client.get("/api/classes", headers=headers).status_code == 200
    rows = _events()
    assert len(rows) == 1
    e = rows[0]
    assert (e["severity"], e["operation"], e["school_id"], e["username"], e["role"], e["path"]) == \
        ("WARNING", "Classes", school["id"], "admin", "admin", "/api/classes")