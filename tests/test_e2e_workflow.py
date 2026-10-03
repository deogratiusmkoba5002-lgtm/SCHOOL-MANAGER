"""End-to-end workflows, driven only through the public HTTP API (plus a mocked mobile-money provider).
Failure messages are labelled [step] so you can see which workflow broke."""
import io
import json

import pytest

import config
from tests.factories import (run, query, make_school, make_term, make_class, make_admin, make_teacher,
                             assign_teacher, make_student, make_marks)

SUBJECTS = [("mathematics", "MATH"), ("english", "ENG"), ("kiswahili", "KIS"), ("biology", "BIO"),
            ("chemistry", "CHEM"), ("physics", "PHY"), ("geography", "GEO")]
GRADES = [(80, 100, "A"), (70, 79, "B"), (60, 69, "C"), (50, 59, "D"), (0, 49, "F")]
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
AMOUNT = config.PARENT_PLANS["6m"]["amount"]


# ── helpers ─────────────────────────────────────────────────────
def _json(resp, label, status=200):
    body = resp.get_json(silent=True)
    assert resp.status_code == status, f"[{label}] expected HTTP {status}, got {resp.status_code}: {body}"
    if isinstance(body, dict) and "ok" in body and status < 400:
        assert body["ok"] is True, f"[{label}] {body}"
    return body


def _bytes(resp, label, mimetype, status=200):
    data = resp.get_data(); resp.close()          # close so Windows releases the temp file
    assert resp.status_code == status, f"[{label}] HTTP {resp.status_code}: {data[:200]}"
    assert resp.mimetype == mimetype, f"[{label}] got {resp.mimetype}"
    return data


def _csv_file(rows, header="name,class_name,stream_name,parent_phone"):
    return (io.BytesIO((header + "\n" + "\n".join(rows) + "\n").encode()), "students.csv")


class FakeSnippe:
    """Stands in for the mobile-money provider. Each payment gets its own reference and state."""
    def __init__(self):
        self.n = 0
        self.remote = {}

    def __call__(self, method, path, **kw):
        if method == "POST":
            self.n += 1
            ref = f"REF-{self.n}"
            self.remote[ref] = {"status": "pending", "value": kw["json"]["details"]["amount"]}
            return {"reference": ref}
        r = self.remote[path.rsplit("/", 1)[-1]]
        return {"status": r["status"], "amount": {"value": r["value"], "currency": "TZS"},
                "completed_at": "2026-10-02T10:00:00", "channel": {"provider": "test-mobile-money"}}

    def settle(self, ref, status="completed", value=None):
        self.remote[ref]["status"] = status
        if value is not None:
            self.remote[ref]["value"] = value


@pytest.fixture
def snippe(monkeypatch):
    fake = FakeSnippe()
    monkeypatch.setattr("services.access.SNIPPE_API_KEY", "test-key")
    monkeypatch.setattr("services.access._snippe_call", fake)
    return fake


# ── 1. THE WHOLE SCHOOL LIFECYCLE ───────────────────────────────
@pytest.mark.e2e
def test_school_lifecycle_end_to_end(client, login, snippe):
    # ── register ────────────────────────────────────────────────
    form = {"school_name": "Acme Secondary", "admin_username": "head", "admin_password": "headpass1",
            "phone": "", "email": "", "admin_phone": "", "motto": "Learn", "reg_code": "S4321",
            "agree_terms": "1", "ref_token": "",
            "classes": json.dumps([{"name": "Form 1", "streams": ["A", "B"]}, {"name": "Form 2", "streams": []}]),
            "subjects": json.dumps([{"name": n, "abbreviation": a} for n, a in SUBJECTS]),
            "grades": json.dumps([{"min_score": lo, "max_score": hi, "grade": g} for lo, hi, g in GRADES])}
    assert client.post("/api/register/school", data=dict(form, agree_terms="0")).status_code == 400
    assert client.post("/api/register/school", data=dict(form, reg_code="BAD")).status_code == 400
    school_id = _json(client.post("/api/register/school", data=form), "register school")["school_id"]
    assert client.post("/api/register/school", data=form).status_code == 409        # duplicate code

    school = {"reg_code": "S4321"}
    admin = login(school, "head", "headpass1")
    cfg = _json(client.get("/api/config", headers=admin), "school config")
    assert cfg["school_name"] == "Acme Secondary" and cfg["verification_status"] == "pending"
    assert cfg["allowed_subjects"] == [n for n, _ in SUBJECTS] and len(cfg["grade_rules"]) == 5
    assert cfg["onboarding_complete"] is False

    # ── superadmin verifies the school ──────────────────────────
    sa = client.post("/api/superadmin/login", json={"username": "test_superadmin", "password": "test_superadmin_pw"}).get_json()
    sa_h = {"Authorization": "Bearer " + sa["token"]}
    pending = _json(client.get("/api/superadmin/schools/pending", headers=sa_h), "pending schools")
    assert [s["id"] for s in pending["schools"]] == [school_id]
    _json(client.post(f"/api/superadmin/schools/{school_id}/approve", headers=sa_h), "approve school")
    cfg = _json(client.get("/api/config", headers=admin), "config after approval")
    assert cfg["verification_status"] == "approved" and cfg["just_approved"] is True

    # ── classes and term ────────────────────────────────────────
    classes = _json(client.get("/api/classes", headers=admin), "list classes")
    form1 = next(c for c in classes if c["class_name"] == "Form 1")
    form2 = next(c for c in classes if c["class_name"] == "Form 2")
    stream = {s["stream_name"]: s["id"] for s in form1["streams"]}
    assert set(stream) == {"A", "B"} and form2["streams"] == []
    f1 = form1["id"]

    term_body = {"label": "Term 1 2026", "ca_count": 2, "ca_weight": 30, "exam_weight": 70}
    assert client.post("/api/terms", json=dict(term_body, ca_weight=40), headers=admin).status_code == 400
    _json(client.post("/api/terms", json=term_body, headers=admin), "open term")
    assert client.post("/api/terms", json=term_body, headers=admin).status_code == 409   # one open term at a time
    term_id = _json(client.get("/api/terms/active", headers=admin), "active term")["term"]["id"]

    # ── teacher ─────────────────────────────────────────────────
    _json(client.post("/api/teachers", json={"username": "mr_hassan", "password": "teachpass1"}, headers=admin), "create teacher")
    assert client.post("/api/teachers", json={"username": "mr_hassan", "password": "x12345"}, headers=admin).status_code == 409
    _json(client.post("/api/assign_teacher", json={"username": "mr_hassan", "subject": "Mathematics",
                                                   "class_id": f1, "stream_id": None}, headers=admin), "assign subject")
    _json(client.post("/api/teachers/mr_hassan/class_teacher",
                      json={"is_class_teacher": True, "class_id": f1, "stream_id": None}, headers=admin), "set class teacher")
    teacher = _json(client.get("/api/teachers", headers=admin), "list teachers")[0]
    assert teacher["is_class_teacher"] and teacher["class_name"] == "Form 1"
    assert [(a["subject"], a["class_name"]) for a in teacher["assignments"]] == [("mathematics", "Form 1")]

    t_h = login(school, "mr_hassan", "teachpass1")
    _json(client.post("/api/change_password", json={"old_password": "teachpass1", "new_password": "newpass12"},
                      headers=t_h), "teacher changes password")
    assert client.get("/api/classes", headers=t_h).status_code == 401                   # old session is invalidated
    assert client.post("/api/login", json={"reg_code": "S4321", "username": "mr_hassan",
                                           "password": "teachpass1"}).status_code == 401
    t_h = login(school, "mr_hassan", "newpass12")

    # ── students: manual add ────────────────────────────────────
    people = {}
    for name, stream_name, phone in [("Asha Juma", "A", "0711110001"), ("Baraka Mussa", "A", "0711110002"),
                                     ("Neema Peter", "B", "0711110003")]:
        body = _json(client.post("/api/students", json={"name": name, "class_id": f1, "stream_id": stream[stream_name],
                                                        "phone_number": phone}, headers=admin), f"add student {name}")
        people[name] = {"stream_id": stream[stream_name], "user": body["parent_username"], "pw": body["temp_password"]}
    assert (people["Asha Juma"]["user"], people["Asha Juma"]["pw"]) == ("asha_juma", "0001")
    assert client.post("/api/students", json={"name": "Asha Juma", "class_id": f1, "stream_id": stream["A"],
                                              "phone_number": "0711110001"}, headers=admin).status_code == 409
    assert client.post("/api/students", json={"name": "No Phone", "class_id": f1}, headers=admin).status_code == 400
    listing = _json(client.get("/api/students", headers=admin), "list students")
    ids = {r["name"]: r["id"] for r in listing}
    assert sorted(r["display_id"] for r in listing) == [f"{school_id:05d}/000{i}" for i in (1, 2, 3)]
    assert _json(client.get("/api/students/resolve_display_id?no=1", headers=admin), "resolve id")["id"] == ids["Asha Juma"]

    # ── students: CSV import into Form 2 ────────────────────────
    rows = ["Salma Ali,Form 2,,0722220001", "Omari Said,form two,,0722220002"]   # note the loose class spelling
    cols = _json(client.post("/api/students/import/columns", data={"file": _csv_file(rows)}, headers=admin), "import: columns")
    assert cols["headers"] == ["name", "class_name", "stream_name", "parent_phone"] and cols["total_rows"] == 2
    colmap = json.dumps(cols["suggested"])
    prev = _json(client.post("/api/students/import/preview", data={"file": _csv_file(rows), "column_map": colmap},
                             headers=admin), "import: preview")
    assert prev["total_rows"] == 2 and prev["unmatched_classes"] == [] and all(not p["issues"] for p in prev["preview"])
    imp_data = lambda: {"file": _csv_file(rows), "column_map": colmap, "mapping": "{}"}
    imp = _json(client.post("/api/students/import", data=imp_data(), headers=admin), "import: run")
    assert (imp["inserted"], imp["skipped"], imp["errors"], imp["credentials_count"]) == (2, 0, 0, 2)
    xlsx = _bytes(client.get(imp["credentials_file"], headers=admin), "import: credentials download", XLSX)
    assert xlsx[:2] == b"PK"
    again = _json(client.post("/api/students/import", data=imp_data(), headers=admin), "import: re-run")
    assert (again["inserted"], again["duplicates"]) == (0, 2)                            # safe to click twice
    login(school, "salma_ali", "0001")                                                    # imported parent can sign in
    assert len(_json(client.get("/api/students", headers=admin), "list students after import")) == 5

    # ── a weekly test, scoped to Form 1 only ────────────────────
    test_id = _json(client.post("/api/tests", json={"term_id": term_id, "label": "Weekly Test 1", "class_ids": [f1]},
                                headers=admin), "create test")["id"]
    assert [t["label"] for t in client.get(f"/api/tests?term_id={term_id}&class_id={f1}", headers=admin).get_json()] == ["Weekly Test 1"]
    assert client.get(f"/api/tests?term_id={term_id}&class_id={form2['id']}", headers=admin).get_json() == []

    # ── marks entered by the teacher (maths) ────────────────────
    def mark(kind, student, subject="mathematics", **extra):
        return client.post(f"/api/marks/{kind}", headers=t_h, json={
            "subject": subject, "class_id": f1, "stream_id": people[student]["stream_id"],
            "student_id": ids[student], **extra})

    scores = {"Asha Juma": ({"CA1": 80, "CA2": 90}, 70), "Baraka Mussa": ({"CA1": 60, "CA2": 60}, 60),
              "Neema Peter": ({"CA1": 40, "CA2": 50}, 30)}
    _json(mark("ca", "Asha Juma", ca_name="CA1", score=70), "marks: first CA1 entry (corrected below)")
    for name, (cas, exam) in scores.items():
        for ca_name, sc in cas.items():
            _json(mark("ca", name, ca_name=ca_name, score=sc), f"marks: {name} {ca_name}")
        _json(mark("exam", name, score=exam), f"marks: {name} exam")
    _json(mark("test", "Asha Juma", test_id=test_id, score=55), "marks: weekly test")
    assert mark("ca", "Asha Juma", ca_name="CA1", score=101).status_code == 400          # out of range
    assert mark("ca", "Asha Juma", subject="english", ca_name="CA1", score=50).status_code == 403   # not assigned

    # the other four subjects arrive via the factory (keeps this test fast)
    for name, (cas, exam) in scores.items():
        for subject in ("english", "kiswahili", "biology", "chemistry", "physics", "geography"):
            make_marks({"id": school_id}, {"id": term_id}, {"id": ids[name]}, subject, ca=cas, exam=exam)

    # ── remarks ─────────────────────────────────────────────────
    _json(client.post("/api/remarks", json={"is_class_teacher": True, "student_id": ids["Asha Juma"],
                                            "remark": "Excellent work"}, headers=t_h), "class teacher remark")
    _json(client.post("/api/remarks", json={"is_class_teacher": False, "student_id": ids["Asha Juma"],
                                            "remark": "Keep it up"}, headers=admin), "head remark")

    # ── report cards ────────────────────────────────────────────
    rep = _json(client.get(f"/api/report/{ids['Asha Juma']}", headers=admin), "report card: Asha")
    assert rep["average"] == pytest.approx(74.5) and rep["grade"] == "B" and len(rep["rows"]) == 7
    assert (rep["class_position"], rep["class_total"], rep["stream_position"], rep["stream_total"]) == (1, 3, 1, 2)
    assert (rep["division"], rep["division_points"]) == ("I", 14)
    maths = next(r for r in rep["rows"] if r["subject"] == "mathematics")
    assert maths["ca"] == {"CA1": 80, "CA2": 90} and maths["exam"] == 70            # CA1 correction took effect
    assert (maths["final"], maths["grade"], maths["position"]) == (pytest.approx(74.5), "B", 1)
    assert (rep["class_teacher_remark"], rep["head_remark"]) == ("Excellent work", "Keep it up")   # weekly test did not change the final

    bar = _json(client.get(f"/api/report/{ids['Baraka Mussa']}", headers=admin), "report card: Baraka")
    assert (bar["grade"], bar["class_position"], bar["stream_position"], bar["division"], bar["division_points"]) == ("C", 2, 2, "II", 21)
    nee = _json(client.get(f"/api/report/{ids['Neema Peter']}", headers=admin), "report card: Neema")
    assert (nee["grade"], nee["class_position"], nee["stream_position"], nee["stream_total"], nee["division"],
            nee["division_points"]) == ("F", 3, 1, 1, "0", 35)

    # ── score sheets ────────────────────────────────────────────
    ts = _json(client.get(f"/api/scoresheet?mode=terminal&class_id={f1}", headers=admin), "score sheet: terminal")
    assert [(r["name"], r["position"], r["grade"]) for r in ts["results"]] == \
        [("Asha Juma", 1, "B"), ("Baraka Mussa", 2, "C"), ("Neema Peter", 3, "F")]
    assert [r["average"] for r in ts["results"]] == [pytest.approx(74.5), pytest.approx(60.0), pytest.approx(34.5)]
    assert len(ts["subjects"]) == 7
    ca1 = _json(client.get(f"/api/scoresheet?mode=ca&ca_name=CA1&class_id={f1}", headers=admin), "score sheet: CA1")
    assert next(r for r in ca1["results"] if r["name"] == "Asha Juma")["scores"]["mathematics"] == 80
    gs = _json(client.get(f"/api/scoresheet?mode=terminal&sheet_type=grade&class_id={f1}", headers=admin), "score sheet: grades")
    assert [(r["name"], r["points"], r["division"]) for r in gs["results"]] == \
        [("Asha Juma", 14, "I"), ("Baraka Mussa", 21, "II"), ("Neema Peter", 35, "0")]

    for path, label in [(f"/api/pdf/terminal_sheet?class_id={f1}", "PDF: terminal sheet"),
                        (f"/api/pdf/ca_sheet?class_id={f1}&ca_name=CA1", "PDF: CA sheet"),
                        (f"/api/pdf/grade_sheet?mode=terminal&class_id={f1}", "PDF: grade sheet")]:
        assert _bytes(client.get(path, headers=admin), label, "application/pdf").startswith(b"%PDF")
    locked = client.get(f"/api/pdf/report/{ids['Asha Juma']}", headers=admin)            # needs parent access first
    assert locked.status_code == 402 and locked.get_json()["code"] == "parent_access_required"

    # ── publishing ──────────────────────────────────────────────
    avail = _json(client.get(f"/api/results/assessments?term_id={term_id}", headers=admin), "publish: list")
    assert [a["assess_key"] for a in avail["assessments"]] == ["CA1", "CA2", "exam", f"test:{test_id}"]
    assert not any(a["published"] for a in avail["assessments"])
    _json(client.post("/api/results/publish_assessments", json={"term_id": term_id, "assess_keys": ["CA1", "CA2", "exam"],
                                                                "publish": True}, headers=admin), "publish: CA1, CA2, exam")
    avail = _json(client.get(f"/api/results/assessments?term_id={term_id}", headers=admin), "publish: list after")
    assert {a["assess_key"] for a in avail["assessments"] if a["published"]} == {"CA1", "CA2", "exam"}

    # ── parent: locked until they pay ───────────────────────────
    asha = ids["Asha Juma"]
    p_h = login(school, "asha_juma", "0001")
    r = client.get(f"/api/report/{asha}?term_id={term_id}", headers=p_h)
    assert r.status_code == 402 and r.get_json()["code"] == "parent_access_required"
    assert client.get("/api/parent/terms", headers=p_h).get_json() == []
    assert client.get(f"/api/parent/results?student_id={asha}&term_id={term_id}&assess=exam", headers=p_h).status_code == 402
    st = _json(client.get("/api/access/status", headers=p_h), "parent access status")
    assert st["active"] is False and [p["key"] for p in st["plans"]] == ["6m", "12m"]

    # ── parent pays ─────────────────────────────────────────────
    pay = _json(client.post("/api/access/pay", json={"plan": "6m", "phone": "0712345678"}, headers=p_h), "parent starts payment")
    assert pay["amount"] == AMOUNT
    check = f"/api/access/check/{pay['payment_id']}"
    res = _json(client.post(check, json={}, headers=p_h), "payment still pending")
    assert res["status"] == "pending" and res["access"]["active"] is False
    snippe.settle(pay["reference"])
    res = _json(client.post(check, json={}, headers=p_h), "payment completes")
    assert res["status"] == "completed" and res["access"]["active"] is True and res["access"]["plan"] == "6m"
    expiry = res["access"]["expires_at"]
    assert _json(client.post(check, json={}, headers=p_h), "payment re-checked")["access"]["expires_at"] == expiry

    # ── parent views everything ─────────────────────────────────
    terms = client.get("/api/parent/terms", headers=p_h).get_json()
    assert [t["id"] for t in terms] == [term_id]
    exam = _json(client.get(f"/api/parent/results?student_id={asha}&term_id={term_id}&assess=exam", headers=p_h), "parent: exam results")
    assert exam["average"] == pytest.approx(70.0) and exam["grade"] == "B"
    assert (exam["class_position"], exam["class_total"]) == (1, 3)
    assert len(exam["results"]) == 7 and all(r["score"] == 70 for r in exam["results"])
    assert client.get(f"/api/parent/results?student_id={asha}&term_id={term_id}&assess=test:{test_id}", headers=p_h).status_code == 403   # unpublished
    assert client.get(f"/api/parent/results?student_id={ids['Baraka Mussa']}&term_id={term_id}&assess=exam", headers=p_h).status_code == 403   # not their child
    prc = _json(client.get(f"/api/report/{asha}?term_id={term_id}", headers=p_h), "parent: report card")
    assert prc["average"] == pytest.approx(74.5) and prc["access"]["active"] is True
    assert _bytes(client.get(f"/api/pdf/report/{asha}?term_id={term_id}", headers=p_h), "parent: report PDF",
                  "application/pdf").startswith(b"%PDF")
    assert _bytes(client.get(f"/api/pdf/report/{asha}?term_id={term_id}", headers=admin), "admin: report PDF after access",
                  "application/pdf").startswith(b"%PDF")

    other = login(school, "baraka_mussa", "0002")                                         # access is per student
    assert client.get(f"/api/report/{ids['Baraka Mussa']}?term_id={term_id}", headers=other).status_code == 402

    # ── star system + superadmin visibility ─────────────────────
    stars = _json(client.get("/api/stars/dashboard", headers=admin), "star dashboard")
    assert stars["cycle_progress"]["qualifying_parent_count"] == 1
    row = next(s for s in _json(client.get("/api/superadmin/schools", headers=sa_h), "superadmin schools")["schools"]
               if s["id"] == school_id)
    assert (row["student_count"], row["teacher_count"]) == (5, 1)

    # the whole workflow must not have produced a single server error
    assert query("SELECT event_id, endpoint, exception_type FROM error_events") == [], "server errors were recorded"


# ── 2. PAYMENT EDGE CASES ───────────────────────────────────────
def test_payment_requires_server_configuration(client, login):
    school = make_school(); cls = make_class(school)
    student = make_student(school, cls)
    h = login(school, student["parent_username"], student["parent_password"])
    r = client.post("/api/access/pay", json={"plan": "6m", "phone": "0712345678"}, headers=h)
    assert r.status_code == 400 and "not configured" in r.get_json()["error"]


def test_parent_payment_edge_cases(client, login, snippe):
    school = make_school(); term = make_term(school); cls = make_class(school)
    admin = make_admin(school); teacher = make_teacher(school)
    assign_teacher(school, teacher, "mathematics", cls)
    s1 = make_student(school, cls, name="Paying Parent", phone="0712340001")
    s2 = make_student(school, cls, name="Admin Funded", phone="0712340002")
    for st in (s1, s2):
        make_marks(school, term, st, "mathematics", ca={"CA1": 70, "CA2": 70}, exam=70)
    run("INSERT INTO published_assessments(school_id,term_id,assess_key,published) VALUES(%s,%s,'exam',1)",
        (school["id"], term["id"]))
    admin_h = login(school, admin["username"])
    p1 = login(school, s1["parent_username"], s1["parent_password"])

    pay = lambda headers, **extra: client.post("/api/access/pay", headers=headers,
                                               json={"plan": "6m", "phone": "0712345678", **extra})
    check = lambda headers, pid: _json(client.post(f"/api/access/check/{pid}", json={}, headers=headers), "check payment")
    status = lambda headers: _json(client.get("/api/access/status", headers=headers), "access status")

    # input validation never reaches the provider
    assert client.post("/api/access/pay", json={"plan": "1y", "phone": "0712345678"}, headers=p1).status_code == 400
    assert client.post("/api/access/pay", json={"plan": "6m", "phone": "123"}, headers=p1).status_code == 400
    assert snippe.n == 0

    # provider reports a smaller amount than the plan costs -> no access
    a = _json(pay(p1), "payment 1")
    snippe.settle(a["reference"], "completed", value=AMOUNT - 1)
    res = check(p1, a["payment_id"])
    assert res["status"] == "amount_mismatch" and res["access"]["active"] is False

    # a proper payment grants ~6 months
    b = _json(pay(p1), "payment 2"); snippe.settle(b["reference"])
    res = check(p1, b["payment_id"])
    assert res["status"] == "completed" and res["access"]["active"] is True and 181 <= res["access"]["days_left"] <= 183
    first_expiry = res["access"]["expires_at"]

    # buying again extends from the current expiry
    c = _json(pay(p1), "payment 3"); snippe.settle(c["reference"])
    res = check(p1, c["payment_id"])
    assert 363 <= res["access"]["days_left"] <= 366 and res["access"]["expires_at"] > first_expiry
    second_expiry = res["access"]["expires_at"]

    # a failed payment changes nothing
    d = _json(pay(p1), "payment 4"); snippe.settle(d["reference"], "failed")
    res = check(p1, d["payment_id"])
    assert res["status"] == "failed" and res["access"]["expires_at"] == second_expiry

    # the webhook grants access without the browser polling
    e = _json(pay(p1), "payment 5"); snippe.settle(e["reference"])
    hook = client.post("/api/access/webhook", json={"type": "payment.completed", "data": {"reference": e["reference"]}})
    assert hook.status_code == 200 and status(p1)["days_left"] >= 540
    expiry_after_hook = status(p1)["expires_at"]
    assert client.post("/api/access/webhook", json={"type": "payment.completed", "data": {"reference": "NOPE"}}).status_code == 200
    assert client.post("/api/access/webhook", data="not json", content_type="application/json").status_code == 400
    assert status(p1)["expires_at"] == expiry_after_hook

    # five attempts per hour per student
    r = pay(p1)
    assert r.status_code == 400 and "Too many" in r.get_json()["error"]

    # Star rule: a parent who paid counts, access funded by the admin never does
    _json(client.get(f"/api/parent/results?student_id={s1['id']}&term_id={term['id']}&assess=exam", headers=p1), "parent 1 views results")
    assert query("SELECT student_id FROM star_qualifying_parents") == [(s1["id"],)]

    f = _json(pay(admin_h, student_id=s2["id"], phone="0799999999"), "admin pays for student 2")
    snippe.settle(f["reference"])
    assert check(admin_h, f["payment_id"])["access"]["active"] is True
    p2 = login(school, s2["parent_username"], s2["parent_password"])
    _json(client.get(f"/api/parent/results?student_id={s2['id']}&term_id={term['id']}&assess=exam", headers=p2), "parent 2 views results")
    assert query("SELECT student_id FROM star_qualifying_parents") == [(s1["id"],)]

    # another school cannot look at this school's payment
    outsider_school = make_school(); outsider_cls = make_class(outsider_school)
    outsider = make_student(outsider_school, outsider_cls)
    o_h = login(outsider_school, outsider["parent_username"], outsider["parent_password"])
    assert client.post(f"/api/access/check/{b['payment_id']}", json={}, headers=o_h).status_code == 404