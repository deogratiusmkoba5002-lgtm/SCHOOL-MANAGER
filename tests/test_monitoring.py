"""Phase 3: error monitoring. Uses a throwaway Flask app with deliberately failing routes (so no real
route has to be modified), plus one test against the real DrDemic app."""
import json
import logging
import re

import psycopg2
import pytest
from flask import Flask, abort, g

from core.db import get_db, to_dicts
from core.monitoring import init_monitoring, classify_severity
from tests.factories import make_school, make_admin

EVENT_ID = re.compile(r"^EVT-[0-9A-F]{10}$")


def _events():
    con = get_db(); cur = con.cursor()
    try:
        cur.execute("SELECT * FROM error_events ORDER BY id")
        return to_dicts(cur.fetchall(), cur)
    finally:
        cur.close(); con.close()


def _dump(row):
    return json.dumps(row, default=str)


@pytest.fixture
def mon(app):
    a = Flask("monitoring_test_app")
    a.config["TESTING"] = True
    init_monitoring(a)

    @a.route("/boom")
    def boom():
        raise RuntimeError("kaboom")

    @a.route("/db-down")
    def db_down():
        raise psycopg2.OperationalError("connection refused")

    @a.route("/bad-input")
    def bad_input():
        raise ValueError("invalid literal")

    @a.route("/ctx")
    def ctx():
        g.school_id = 7; g.username = "teacher1"; g.role = "teacher"
        raise RuntimeError("with context")

    @a.route("/secrets", methods=["POST"])
    def secrets_route():
        raise RuntimeError("login failed password=hunter2 Authorization: Bearer abc123token")

    @a.route("/item/<token>")
    def item(token):
        raise RuntimeError("item failed")

    @a.route("/forbidden")
    def forbidden():
        abort(403)

    @a.route("/unavailable")
    def unavailable():
        abort(503)

    return a.test_client()


def test_exception_is_captured_and_stored(mon):
    r = mon.get("/boom")
    assert r.status_code == 500
    rows = _events()
    assert len(rows) == 1
    e = rows[0]
    assert EVENT_ID.match(e["event_id"])
    assert (e["exception_type"], e["severity"], e["http_status"]) == ("RuntimeError", "ERROR", 500)
    assert (e["method"], e["path"], e["endpoint"], e["status"]) == ("GET", "/boom", "boom", "new")
    assert "kaboom" in e["message"] and "kaboom" in e["traceback"]


def test_user_gets_safe_response(mon):
    r = mon.get("/boom")
    body = r.get_json()
    assert body["ok"] is False and EVENT_ID.match(body["event_id"])
    assert body["event_id"] == _events()[0]["event_id"]
    assert "kaboom" not in r.get_data(as_text=True) and "Traceback" not in r.get_data(as_text=True)


def test_user_and_school_context_recorded(mon):
    mon.get("/ctx")
    e = _events()[0]
    assert (e["school_id"], e["username"], e["role"]) == (7, "teacher1", "teacher")


def test_expected_errors_are_not_recorded(mon):
    assert mon.get("/does-not-exist").status_code == 404
    assert mon.get("/forbidden").status_code == 403
    assert _events() == []
    assert mon.get("/unavailable").status_code == 503      # 5xx HTTP errors ARE recorded
    rows = _events()
    assert len(rows) == 1 and rows[0]["http_status"] == 503


@pytest.mark.parametrize("path,expected", [("/db-down", "CRITICAL"), ("/bad-input", "WARNING"), ("/boom", "ERROR")])
def test_severity_levels(mon, path, expected):
    mon.get(path)
    assert _events()[0]["severity"] == expected


def test_payment_endpoint_failures_are_critical():
    assert classify_severity(RuntimeError("x"), "access.api_access_pay") == "CRITICAL"
    assert classify_severity(RuntimeError("x"), "pdf.pdf_report") == "ERROR"


def test_sensitive_data_is_not_stored(mon):
    mon.post("/secrets?token=SECRET123&page=2",
             json={"username": "bob", "password": "pw-in-body"},
             headers={"Authorization": "Bearer abc123token", "Cookie": "session=cookieval999"})
    e = _events()[0]
    dump = _dump(e)
    for needle in ("hunter2", "abc123token", "SECRET123", "pw-in-body", "cookieval999"):
        assert needle not in dump, f"{needle} leaked into stored event"
    assert "[REDACTED]" in e["message"]
    assert e["context"]["query_params"] == ["page", "token"]          # names only
    assert e["context"]["json_fields"] == ["password", "username"]


def test_secret_in_url_path_is_not_stored(mon):
    mon.get("/item/TOPSECRETVALUE")
    e = _events()[0]
    assert e["path"] == "/item/<token>"
    assert "TOPSECRETVALUE" not in _dump(e)
    assert e["context"]["view_args"]["token"] == "[REDACTED]"


def test_storage_failure_does_not_crash_request(mon, monkeypatch, caplog):
    def broken_store(ev):
        raise RuntimeError("table missing")
    monkeypatch.setattr("core.monitoring._store_event", broken_store)
    with caplog.at_level(logging.ERROR, logger="drdemic.monitoring"):
        r = mon.get("/boom")
    body = r.get_json()
    assert r.status_code == 500 and EVENT_ID.match(body["event_id"])
    assert "monitoring storage failed" in caplog.text and body["event_id"] in caplog.text


def test_db_connection_failure_does_not_crash_request(mon, monkeypatch, caplog):
    def no_db(*a, **k):
        raise psycopg2.OperationalError("db down")
    monkeypatch.setattr("psycopg2.connect", no_db)
    with caplog.at_level(logging.ERROR, logger="drdemic.monitoring"):
        r = mon.get("/boom")
    assert r.status_code == 500 and r.get_json()["ok"] is False
    assert "monitoring storage failed" in caplog.text


def test_event_building_failure_does_not_crash_request(mon, monkeypatch):
    def broken_build(*a, **k):
        raise RuntimeError("builder bug")
    monkeypatch.setattr("core.monitoring._build_event", broken_build)
    r = mon.get("/boom")
    assert r.status_code == 500 and EVENT_ID.match(r.get_json()["event_id"])


def test_real_app_route_failure_is_monitored(client, login, monkeypatch):
    school = make_school(); admin = make_admin(school)
    headers = login(school, admin["username"])
    token = headers["Authorization"][len("Bearer "):]

    assert client.get("/api/classes").status_code == 401        # expected error: not recorded
    assert _events() == []

    def broken(*a, **k):
        raise psycopg2.OperationalError("db down")
    monkeypatch.setattr("routes.classes_routes.get_db", broken)
    r = client.get(f"/api/classes?token={token}")                # token in query string, as PDF links do
    assert r.status_code == 500 and EVENT_ID.match(r.get_json()["event_id"])

    rows = _events()
    assert len(rows) == 1
    e = rows[0]
    assert (e["severity"], e["blueprint"], e["operation"]) == ("CRITICAL", "classes", "Classes")
    assert (e["school_id"], e["username"], e["role"], e["path"]) == (school["id"], "admin", "admin", "/api/classes")
    assert token not in _dump(e)