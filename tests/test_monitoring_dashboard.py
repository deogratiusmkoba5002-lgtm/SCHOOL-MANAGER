"""Phase 4: Superadmin monitoring API. Authorization is tested first and hardest."""
import itertools
from datetime import datetime, timedelta, timezone

import psycopg2
import pytest
from psycopg2.extras import Json

from tests.factories import run, query, make_school, make_admin, make_teacher, make_class, make_student

BASE = "/api/superadmin/monitoring"
_seq = itertools.count(1)
FAKE_ID = "EVT-0000000001"

ENDPOINTS = [("get", f"{BASE}/summary"), ("get", f"{BASE}/events"), ("get", f"{BASE}/filters"),
             ("get", f"{BASE}/events/{FAKE_ID}"), ("post", f"{BASE}/events/{FAKE_ID}")]


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def add_event(severity="ERROR", status="new", hours_ago=1, operation="PDF generation",
              endpoint="pdf.pdf_report", school_id=None, message="boom"):
    event_id = f"EVT-{next(_seq):010X}"
    run("""INSERT INTO error_events(event_id,severity,status,created_at,exception_type,message,http_status,
                                    method,path,endpoint,operation,school_id,username,role,traceback,context)
           VALUES(%s,%s,%s,%s,'RuntimeError',%s,500,'GET','/api/x',%s,%s,%s,'bob','admin',
                  'Traceback (most recent call last): boom',%s)""",
        (event_id, severity, status, _utcnow() - timedelta(hours=hours_ago), message, endpoint,
         operation, school_id, Json({"query_params": ["page"]})))
    return event_id


def _ids(resp):
    return [e["event_id"] for e in resp.get_json()["events"]]


@pytest.fixture(scope="module")
def sa(app):
    c = app.test_client()
    r = c.post("/api/superadmin/login", json={"username": "test_superadmin", "password": "test_superadmin_pw"})
    assert r.status_code == 200, r.get_json()
    return {"Authorization": "Bearer " + r.get_json()["token"]}


def _call(client, method, path, headers=None):
    kw = {"headers": headers or {}}
    if method == "post":
        kw["json"] = {"status": "resolved"}
    return getattr(client, method)(path, **kw)


# ── AUTHORIZATION ───────────────────────────────────────────────
@pytest.mark.parametrize("method,path", ENDPOINTS)
def test_endpoints_reject_missing_token(client, method, path):
    r = _call(client, method, path)
    assert r.status_code == 401 and r.get_json()["ok"] is False


def test_non_superadmin_tokens_are_rejected(client, login, sa):
    school = make_school(); cls = make_class(school)
    admin = make_admin(school); teacher = make_teacher(school); student = make_student(school, cls)
    eid = add_event()
    tampered = sa["Authorization"][:-1] + ("A" if sa["Authorization"][-1] != "A" else "B")
    attackers = {
        "school admin": login(school, admin["username"]),
        "teacher": login(school, teacher["username"]),
        "parent": login(school, student["parent_username"], student["parent_password"]),
        "garbage": {"Authorization": "Bearer not-a-real-token"},
        "tampered superadmin": {"Authorization": tampered},
    }
    for who, headers in attackers.items():
        for method, path in ENDPOINTS:
            r = _call(client, method, path, headers)
            assert r.status_code == 401, f"{who} got {r.status_code} on {method} {path}"
        r = client.post(f"{BASE}/events/{eid}", json={"status": "resolved"}, headers=headers)
        assert r.status_code == 401
    assert query("SELECT status FROM error_events WHERE event_id=%s", (eid,))[0][0] == "new"
    # and a superadmin token is not accepted by the normal school API
    assert client.get("/api/classes", headers=sa).status_code == 401


# ── SUMMARY ─────────────────────────────────────────────────────
def test_summary_empty(client, sa):
    d = client.get(f"{BASE}/summary", headers=sa).get_json()
    assert d["ok"] and d["total_recent"] == 0 and d["unresolved_total"] == 0
    assert d["health"] == "healthy" and d["last_event_at"] is None


def test_summary_counts_and_health(client, sa):
    err = add_event("ERROR", "new", hours_ago=1)
    crit = add_event("CRITICAL", "new", hours_ago=2)
    add_event("CRITICAL", "resolved", hours_ago=3)
    add_event("WARNING", "new", hours_ago=48)          # outside the 24h window
    add_event("INFO", "ignored", hours_ago=1)
    d = client.get(f"{BASE}/summary", headers=sa).get_json()
    assert d["total_recent"] == 4 and d["critical_recent"] == 2
    assert d["unresolved_total"] == 3 and d["unresolved_critical"] == 1
    assert d["health"] == "critical" and d["last_event_at"].endswith("Z")

    client.post(f"{BASE}/events/{crit}", json={"status": "resolved"}, headers=sa)
    assert client.get(f"{BASE}/summary", headers=sa).get_json()["health"] == "warning"
    client.post(f"{BASE}/events/{err}", json={"status": "ignored"}, headers=sa)
    assert client.get(f"{BASE}/summary", headers=sa).get_json()["health"] == "healthy"


# ── LIST + FILTERS ──────────────────────────────────────────────
def test_list_filters_ordering_and_pagination(client, sa):
    school = make_school("Alpha School")
    a = add_event("ERROR", "new", 1, school_id=school["id"], operation="PDF generation")
    b = add_event("CRITICAL", "new", 2, operation="Parent payment", endpoint="access.api_access_pay")
    c = add_event("WARNING", "investigating", 3, operation="Student import")
    old = add_event("ERROR", "resolved", hours_ago=24 * 10, operation="PDF generation")
    get = lambda **q: client.get(f"{BASE}/events", query_string=q, headers=sa)

    r = get()
    assert _ids(r) == [a, b, c, old] and r.get_json()["total"] == 4          # newest first
    assert _ids(get(severity="critical")) == [b]
    assert _ids(get(status="investigating")) == [c]
    r = get(school_id=school["id"])
    assert _ids(r) == [a] and r.get_json()["events"][0]["school_name"] == "Alpha School"
    assert _ids(get(operation="PDF generation")) == [a, old]
    five_days_ago = (_utcnow() - timedelta(days=5)).strftime("%Y-%m-%d")
    assert _ids(get(date_to=five_days_ago)) == [old]
    assert _ids(get(date_from=five_days_ago)) == [a, b, c]
    assert _ids(get(limit=2, offset=0)) == [a, b]
    r = get(limit=2, offset=2)
    assert _ids(r) == [c, old] and r.get_json()["total"] == 4

    for bad in ({"severity": "NOPE"}, {"status": "NOPE"}, {"date_from": "yesterday"},
                {"school_id": "abc"}, {"limit": "x"}):
        assert get(**bad).status_code == 400, bad


def test_filters_endpoint_lists_what_exists(client, sa):
    school = make_school("Gamma School")
    add_event(operation="Student import", school_id=school["id"])
    add_event(operation="PDF generation")
    d = client.get(f"{BASE}/filters", headers=sa).get_json()
    assert d["operations"] == ["PDF generation", "Student import"]
    assert d["schools"] == [{"id": school["id"], "name": "Gamma School"}]


# ── DETAIL + UPDATE ─────────────────────────────────────────────
def test_event_detail(client, sa):
    school = make_school("Delta School")
    eid = add_event(school_id=school["id"])
    ev = client.get(f"{BASE}/events/{eid}", headers=sa).get_json()["event"]
    assert ev["event_id"] == eid and ev["status"] == "new" and ev["admin_notes"] == ""
    assert ev["traceback"].startswith("Traceback") and ev["context"] == {"query_params": ["page"]}
    assert ev["school_name"] == "Delta School" and ev["severity_color"]
    assert client.get(f"{BASE}/events/EVT-FFFFFFFFFF", headers=sa).status_code == 404
    assert client.get(f"{BASE}/events/nope", headers=sa).status_code == 404


def test_update_status_and_notes(client, sa):
    eid = add_event(); url = f"{BASE}/events/{eid}"
    detail = lambda: client.get(url, headers=sa).get_json()["event"]

    r = client.post(url, json={"status": "investigating", "admin_notes": "Looking into it"}, headers=sa)
    assert r.status_code == 200 and r.get_json()["ok"]
    assert (detail()["status"], detail()["admin_notes"]) == ("investigating", "Looking into it")

    client.post(url, json={"admin_notes": "only notes"}, headers=sa)
    assert (detail()["status"], detail()["admin_notes"]) == ("investigating", "only notes")

    assert client.post(url, json={"status": "bogus"}, headers=sa).status_code == 400
    assert client.post(url, json={}, headers=sa).status_code == 400
    assert client.post(url, json={"admin_notes": "x" * 5001}, headers=sa).status_code == 400
    assert detail()["status"] == "investigating"                      # rejected updates changed nothing
    assert client.post(f"{BASE}/events/EVT-FFFFFFFFFF", json={"status": "resolved"}, headers=sa).status_code == 404


# ── END TO END ──────────────────────────────────────────────────
def test_real_failure_appears_on_dashboard(client, login, sa, monkeypatch):
    school = make_school("Beta School"); admin = make_admin(school)
    headers = login(school, admin["username"])

    def broken(*a, **k):
        raise psycopg2.OperationalError("db down")
    monkeypatch.setattr("routes.classes_routes.get_db", broken)
    assert client.get("/api/classes", headers=headers).status_code == 500

    events = client.get(f"{BASE}/events", headers=sa).get_json()["events"]
    assert len(events) == 1
    e = events[0]
    assert (e["severity"], e["operation"], e["school_name"], e["status"]) == ("CRITICAL", "Classes", "Beta School", "new")
    detail = client.get(f"{BASE}/events/{e['event_id']}", headers=sa).get_json()["event"]
    assert "OperationalError" in detail["traceback"]