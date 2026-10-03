"""Phase 5: grouping + alerting. Uses throwaway Flask apps with deliberately failing routes."""
import logging

import psycopg2
import pytest
from flask import Flask, g, request

import core.monitoring as monitoring
from core.db import get_db, to_dicts
from core.monitoring import init_monitoring
from tests.factories import run, make_school


def _rows(sql, params=()):
    con = get_db(); cur = con.cursor()
    try:
        cur.execute(sql, params)
        return to_dicts(cur.fetchall(), cur)
    finally:
        cur.close(); con.close()


def _groups(): return _rows("SELECT * FROM error_groups ORDER BY id")
def _events(): return _rows("SELECT * FROM error_events ORDER BY id")
def _alerts(): return _rows("SELECT * FROM error_alerts ORDER BY id")


def _connect():
    raise psycopg2.OperationalError("connection refused")


@pytest.fixture
def mon(app):
    a = Flask("grouping_test_app")
    a.config["TESTING"] = True
    init_monitoring(a)

    @a.route("/boom")
    def boom():
        if request.args.get("s"):
            g.school_id = int(request.args["s"])
        raise RuntimeError(f"user {request.args.get('n', '0')} failed")

    @a.route("/boom-b")
    def boom_b():
        raise RuntimeError("same type, different endpoint")

    @a.route("/mixed")
    def mixed():
        if request.args.get("k") == "value":
            raise ValueError("bad")
        raise RuntimeError("bad")

    @a.route("/db-a")
    def db_a():
        _connect()

    @a.route("/db-b")
    def db_b():
        _connect()

    return a.test_client()


@pytest.fixture
def alerts(monkeypatch):
    """Turns alerts on and captures dispatched payloads instead of sending anything."""
    monkeypatch.setenv("ALERT_EMAIL_TO", "ops@example.com")
    monkeypatch.setenv("ALERT_EMAIL_API_KEY", "test-key")
    for k in ("ALERT_MIN_SEVERITY", "ALERT_THROTTLE_MINUTES", "ALERT_MAX_PER_HOUR"):
        monkeypatch.delenv(k, raising=False)
    sent = []
    monkeypatch.setattr(monitoring, "_dispatch_alert", lambda p: sent.append(p))
    return sent


def _payload(**over):
    p = {"alert_id": 1, "group_id": 1, "severity": "CRITICAL", "event_id": "EVT-ABCDEF1234",
         "operation": "PDF generation", "school_id": 3, "school_name": "Test School", "method": "GET",
         "path": "/api/pdf/report/<int:sid>", "endpoint": "pdf.pdf_report", "exception_type": "RuntimeError",
         "message": "boom", "occurrences": 4, "suppressed": 0, "first_seen": "2026-10-01 10:00:00 UTC",
         "last_seen": "2026-10-01 11:00:00 UTC", "reopened": False, "new_group": False}
    p.update(over)
    return p


# ── GROUPING ────────────────────────────────────────────────────
def test_repeated_error_is_one_group(mon):
    for _ in range(5):
        assert mon.get("/boom").status_code == 500
    gs = _groups(); evs = _events()
    assert len(gs) == 1 and len(evs) == 5
    grp = gs[0]
    assert (grp["occurrence_count"], grp["status"], grp["severity"]) == (5, "new", "ERROR")
    assert grp["first_seen"] <= grp["last_seen"]
    assert grp["last_event_id"] == evs[-1]["event_id"]
    assert {e["fingerprint"] for e in evs} == {grp["fingerprint"]}


def test_message_and_school_variation_does_not_split_group(mon):
    mon.get("/boom?n=1&s=1"); mon.get("/boom?n=2&s=2"); mon.get("/boom?n=3")
    gs = _groups()
    assert len(gs) == 1 and gs[0]["occurrence_count"] == 3
    assert gs[0]["last_school_id"] is None


def test_unrelated_errors_are_not_grouped(mon):
    for path in ("/boom", "/boom-b", "/mixed?k=value", "/mixed"):
        mon.get(path)
    gs = _groups()
    assert len(gs) == 4 and all(g_["occurrence_count"] == 1 for g_ in gs)


def test_db_outage_across_endpoints_is_one_group(mon):
    for path in ("/db-a", "/db-b", "/db-a"):
        mon.get(path)
    gs = _groups()
    assert len(gs) == 1 and gs[0]["occurrence_count"] == 3 and gs[0]["severity"] == "CRITICAL"


def test_resolved_group_reopens_ignored_stays_ignored(mon):
    mon.get("/boom")
    run("UPDATE error_groups SET status='resolved'")
    mon.get("/boom")
    assert (_groups()[0]["status"], _groups()[0]["occurrence_count"]) == ("new", 2)
    run("UPDATE error_groups SET status='ignored'")
    mon.get("/boom")
    assert (_groups()[0]["status"], _groups()[0]["occurrence_count"]) == ("ignored", 3)


def test_event_storage_is_capped_but_count_is_not(mon, monkeypatch):
    monkeypatch.setattr(monitoring, "MAX_EVENTS_PER_GROUP", 3)
    for _ in range(6):
        mon.get("/boom")
    grp = _groups()[0]; evs = _events()
    assert grp["occurrence_count"] == 6 and len(evs) == 3
    assert grp["last_event_id"] == evs[-1]["event_id"]


def test_grouping_failure_keeps_event_and_response(mon, monkeypatch, caplog):
    def broken(*a, **k):
        raise RuntimeError("grouping bug")
    monkeypatch.setattr(monitoring, "_group_step", broken)
    with caplog.at_level(logging.ERROR, logger="drdemic.monitoring"):
        r = mon.get("/boom")
    assert r.status_code == 500 and r.get_json()["ok"] is False
    assert len(_events()) == 1 and _events()[0]["fingerprint"] and _groups() == []
    assert "grouping failed" in caplog.text


# ── ALERTING ────────────────────────────────────────────────────
def test_alert_disabled_by_default_does_not_consume_throttle(mon, monkeypatch):
    sent = []
    monkeypatch.setattr(monitoring, "_dispatch_alert", lambda p: sent.append(p))
    for _ in range(3):
        mon.get("/db-a")
    assert sent == [] and _alerts() == []
    assert _groups()[0]["last_alert_at"] is None      # enabling alerts later still works


def test_critical_alert_once_then_throttled(mon, alerts):
    for _ in range(5):
        mon.get("/db-a")
    assert len(alerts) == 1
    p = alerts[0]
    assert (p["severity"], p["occurrences"], p["new_group"], p["exception_type"]) == ("CRITICAL", 1, True, "OperationalError")
    grp = _groups()[0]
    assert grp["suppressed_since_alert"] == 4 and grp["last_alert_at"] is not None
    assert len(_alerts()) == 1


def test_alert_resumes_after_window_with_suppressed_count(mon, alerts):
    for _ in range(5):
        mon.get("/db-a")
    run("UPDATE error_groups SET last_alert_at = last_alert_at - INTERVAL '2 hours'")
    mon.get("/db-a")
    assert len(alerts) == 2
    assert (alerts[1]["suppressed"], alerts[1]["occurrences"], alerts[1]["new_group"]) == (4, 6, False)
    assert _groups()[0]["suppressed_since_alert"] == 0


def test_only_serious_events_alert(mon, alerts, monkeypatch):
    mon.get("/boom")                                   # ERROR, default threshold is CRITICAL
    assert alerts == []
    monkeypatch.setenv("ALERT_MIN_SEVERITY", "ERROR")
    mon.get("/mixed?k=value")                          # WARNING: still below threshold
    assert alerts == []
    mon.get("/boom-b")                                 # ERROR: now qualifies
    assert len(alerts) == 1 and alerts[0]["severity"] == "ERROR"


def test_ignored_group_never_alerts(mon, alerts):
    mon.get("/db-a")
    run("UPDATE error_groups SET status='ignored', last_alert_at = last_alert_at - INTERVAL '2 hours'")
    mon.get("/db-a")
    assert len(alerts) == 1


def test_reopened_group_alerts_despite_throttle(mon, alerts):
    mon.get("/db-a")
    run("UPDATE error_groups SET status='resolved'")   # last alert was seconds ago
    mon.get("/db-a")
    assert len(alerts) == 2 and alerts[1]["reopened"] is True
    assert _groups()[0]["status"] == "new"


def test_global_alert_cap(mon, alerts, monkeypatch):
    monkeypatch.setattr(monitoring, "classify_severity", lambda exc, endpoint=None: "CRITICAL")
    monkeypatch.setenv("ALERT_MAX_PER_HOUR", "2")
    for path in ("/boom", "/boom-b", "/mixed?k=value", "/mixed"):
        mon.get(path)
    assert len(alerts) == 2 and len(_alerts()) == 2
    unalerted = [g_ for g_ in _groups() if g_["last_alert_at"] is None]
    assert len(unalerted) == 2 and all(g_["suppressed_since_alert"] == 1 for g_ in unalerted)


def test_alert_email_format_and_no_secrets(mon, alerts, monkeypatch):
    monkeypatch.setattr(monitoring, "classify_severity", lambda exc, endpoint=None: "CRITICAL")
    school = make_school("Format School")
    mon.get("/boom", query_string={"s": school["id"], "n": "password=hunter2"})
    p = alerts[0]
    text = monitoring._format_alert(p)
    assert text.startswith("CRITICAL DRDEMIC ERROR")
    for expected in (f"Event ID: {p['event_id']}", f"School: Format School (#{school['id']})",
                     "Occurrences: 1", "Endpoint: GET boom"):
        assert expected in text, expected
    assert "hunter2" not in text and "Traceback" not in text
    assert monitoring._alert_subject(p).startswith("[DrDemic CRITICAL]")


def test_resend_delivery_payload(alerts, monkeypatch):
    calls = []

    class Resp:
        status_code = 200
    monkeypatch.setattr(monitoring.requests, "post", lambda url, **kw: calls.append((url, kw)) or Resp())
    monitoring._deliver_alert(_payload())
    url, kw = calls[0]
    assert url == "https://api.resend.com/emails"
    assert kw["headers"]["Authorization"] == "Bearer test-key"
    assert kw["json"]["to"] == ["ops@example.com"] and kw["json"]["subject"].startswith("[DrDemic CRITICAL]")
    assert "DRDEMIC ERROR" in kw["json"]["text"]

    Resp.status_code = 500
    with pytest.raises(RuntimeError):
        monitoring._deliver_alert(_payload())


def test_delivery_failure_is_contained(mon, alerts, monkeypatch):
    mon.get("/db-a")
    p = alerts[0]

    def down(_p):
        raise RuntimeError("smtp down")
    monkeypatch.setattr(monitoring, "_deliver_alert", down)
    monitoring._run_delivery(p)                        # must not raise
    row = _alerts()[0]
    assert row["delivered"] is False and "smtp down" in row["error"]

    monkeypatch.setattr(monitoring, "_deliver_alert", lambda _p: None)
    monitoring._run_delivery(p)
    assert _alerts()[0]["delivered"] is True