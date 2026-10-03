"""Phase 5: group endpoints used by the Superadmin dashboard."""
import itertools
from datetime import datetime, timedelta, timezone

import psycopg2
import pytest
from psycopg2.extras import Json

from tests.factories import run, query, make_school, make_admin, make_teacher, make_class, make_student

BASE = "/api/superadmin/monitoring"
_seq = itertools.count(1)
ENDPOINTS = [("get", f"{BASE}/groups/summary"), ("get", f"{BASE}/groups"),
             ("get", f"{BASE}/groups/1"), ("post", f"{BASE}/groups/1")]


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def add_group(severity="ERROR", status="new", hours_ago=1, operation="PDF generation", endpoint="pdf.pdf_report",
              count=1, school_id=None, message="boom"):
    n = next(_seq)
    fp, event_id = f"fp{n:030d}", f"EVT-{n:010X}"
    last_seen = _utcnow() - timedelta(hours=hours_ago)
    run("""INSERT INTO error_events(event_id,severity,created_at,exception_type,message,http_status,method,path,
                                    endpoint,operation,school_id,username,role,traceback,context,fingerprint)
           VALUES(%s,%s,%s,'RuntimeError',%s,500,'GET','/api/x',%s,%s,%s,'bob','admin',
                  'Traceback (most recent call last): boom',%s,%s)""",
        (event_id, severity, last_seen, message, endpoint, operation, school_id, Json({"query_params": ["page"]}), fp))
    return run("""INSERT INTO error_groups(fingerprint,severity,exception_type,endpoint,operation,sample_message,
                                           occurrence_count,first_seen,last_seen,last_event_id,last_school_id,status)
                  VALUES(%s,%s,'RuntimeError',%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
               (fp, severity, endpoint, operation, message, count, last_seen - timedelta(days=1), last_seen,
                event_id, school_id, status))


def _ids(resp):
    return [g["id"] for g in resp.get_json()["groups"]]


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


@pytest.mark.parametrize("method,path", ENDPOINTS)
def test_group_endpoints_reject_missing_token(client, method, path):
    r = _call(client, method, path)
    assert r.status_code == 401 and r.get_json()["ok"] is False


def test_group_endpoints_reject_non_superadmins(client, login):
    school = make_school(); cls = make_class(school)
    admin = make_admin(school); teacher = make_teacher(school); student = make_student(school, cls)
    gid = add_group()
    attackers = {
        "school admin": login(school, admin["username"]),
        "teacher": login(school, teacher["username"]),
        "parent": login(school, student["parent_username"], student["parent_password"]),
        "garbage": {"Authorization": "Bearer nope"},
    }
    for who, headers in attackers.items():
        for method, path in ENDPOINTS:
            assert _call(client, method, path, headers).status_code == 401, f"{who} {method} {path}"
        r = client.post(f"{BASE}/groups/{gid}", json={"status": "resolved"}, headers=headers)
        assert r.status_code == 401
    assert query("SELECT status FROM error_groups WHERE id=%s", (gid,))[0][0] == "new"


def test_groups_summary(client, sa):
    d = client.get(f"{BASE}/groups/summary", headers=sa).get_json()
    assert d["active_recent"] == 0 and d["health"] == "healthy" and d["alerts_enabled"] is False

    a = add_group("CRITICAL", "new", 1)
    b = add_group("ERROR", "new", 2)
    add_group("CRITICAL", "resolved", 3)
    add_group("WARNING", "new", 48)
    add_group("INFO", "ignored", 1)
    d = client.get(f"{BASE}/groups/summary", headers=sa).get_json()
    assert (d["active_recent"], d["critical_recent"]) == (3, 2)
    assert (d["unresolved_total"], d["unresolved_critical"]) == (3, 1) and d["health"] == "critical"

    client.post(f"{BASE}/groups/{a}", json={"status": "resolved"}, headers=sa)
    assert client.get(f"{BASE}/groups/summary", headers=sa).get_json()["health"] == "warning"
    client.post(f"{BASE}/groups/{b}", json={"status": "ignored"}, headers=sa)
    assert client.get(f"{BASE}/groups/summary", headers=sa).get_json()["health"] == "healthy"


def test_group_list_filters_sort_pagination(client, sa):
    school = make_school("Alpha School")
    g1 = add_group("ERROR", "new", 1, "PDF generation", count=5, school_id=school["id"])
    g2 = add_group("CRITICAL", "new", 2, "Parent payment", count=50)
    g3 = add_group("WARNING", "investigating", 3, "Student import", count=2)
    g4 = add_group("ERROR", "resolved", 24 * 10, "PDF generation", count=1)
    get = lambda **q: client.get(f"{BASE}/groups", query_string=q, headers=sa)

    r = get()
    assert _ids(r) == [g1, g2, g3, g4] and r.get_json()["total"] == 4
    row = r.get_json()["groups"][0]
    assert row["occurrence_count"] == 5 and row["school_name"] == "Alpha School"
    assert _ids(get(sort="occurrences")) == [g2, g1, g3, g4]
    assert _ids(get(sort="severity")) == [g2, g1, g4, g3]
    assert _ids(get(severity="critical")) == [g2]
    assert _ids(get(status="investigating")) == [g3]
    assert _ids(get(school_id=school["id"])) == [g1]
    assert _ids(get(operation="PDF generation")) == [g1, g4]
    assert _ids(get(q="student")) == [g3]
    assert _ids(get(q="generation")) == [g1, g4]                  # matches operation text
    assert _ids(get(q="pdf_report")) == [g1, g2, g3, g4]          # matches endpoint text
    five_days_ago = (_utcnow() - timedelta(days=5)).strftime("%Y-%m-%d")
    assert _ids(get(date_to=five_days_ago)) == [g4] and _ids(get(date_from=five_days_ago)) == [g1, g2, g3]
    assert _ids(get(limit=2)) == [g1, g2] and _ids(get(limit=2, offset=2)) == [g3, g4]
    for bad in ({"severity": "NOPE"}, {"status": "NOPE"}, {"sort": "nope"}, {"date_from": "x"}, {"limit": "x"}):
        assert get(**bad).status_code == 400, bad


def test_group_detail(client, sa):
    school = make_school("Delta School")
    gid = add_group(school_id=school["id"], count=7)
    d = client.get(f"{BASE}/groups/{gid}", headers=sa).get_json()
    assert d["ok"] and d["group"]["occurrence_count"] == 7 and d["group"]["school_name"] == "Delta School"
    assert d["latest"]["traceback"].startswith("Traceback") and d["latest"]["context"] == {"query_params": ["page"]}
    assert len(d["occurrences"]) == 1 and d["severity_color"]
    assert client.get(f"{BASE}/groups/999999", headers=sa).status_code == 404


def test_group_update(client, sa):
    gid = add_group(); url = f"{BASE}/groups/{gid}"
    detail = lambda: client.get(url, headers=sa).get_json()["group"]
    assert client.post(url, json={"status": "investigating", "admin_notes": "On it"}, headers=sa).status_code == 200
    assert (detail()["status"], detail()["admin_notes"]) == ("investigating", "On it")
    assert client.post(url, json={"status": "bogus"}, headers=sa).status_code == 400
    assert client.post(url, json={}, headers=sa).status_code == 400
    assert client.post(url, json={"admin_notes": "x" * 5001}, headers=sa).status_code == 400
    assert detail()["status"] == "investigating"
    assert client.post(f"{BASE}/groups/999999", json={"status": "resolved"}, headers=sa).status_code == 404


def test_real_failures_are_grouped_on_dashboard(client, login, sa, monkeypatch):
    school = make_school("Beta School"); admin = make_admin(school)
    headers = login(school, admin["username"])

    def broken(*a, **k):
        raise psycopg2.OperationalError("db down")
    monkeypatch.setattr("routes.classes_routes.get_db", broken)
    for _ in range(2):
        assert client.get("/api/classes", headers=headers).status_code == 500

    groups = client.get(f"{BASE}/groups", headers=sa).get_json()["groups"]
    assert len(groups) == 1
    g = groups[0]
    assert (g["severity"], g["operation"], g["school_name"], g["occurrence_count"]) == ("CRITICAL", "Classes", "Beta School", 2)
    d = client.get(f"{BASE}/groups/{g['id']}", headers=sa).get_json()
    assert "OperationalError" in d["latest"]["traceback"] and len(d["occurrences"]) == 2