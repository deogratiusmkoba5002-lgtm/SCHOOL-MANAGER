"""Phase 8: multi-tenant isolation + role restrictions, driven only through the HTTP API.
Every test builds TWO schools (A and B) with identical shapes, then attacks B using A's tokens.
Tests marked xfail pin REAL bugs: they stay 'xfailed' until you fix the bug, then flip to XPASS
(delete the marker when that happens)."""
import pytest
from psycopg2.extras import Json

from tests.factories import (DEFAULT_PASSWORD, run, query, make_school, make_term, make_class, make_admin,
                             make_teacher, assign_teacher, make_student, make_marks)


# ── world builder ───────────────────────────────────────────────
def build(tag):
    school = make_school(f"{tag} School")
    term = make_term(school, label=f"{tag} Term")
    cls = make_class(school, f"{tag} Form 1")
    admin = make_admin(school)
    teacher = make_teacher(school, username=f"mr_{tag.lower()}")
    assign_teacher(school, teacher, "mathematics", cls)
    student = make_student(school, cls, name=f"{tag} Pupil", phone="0711000111")
    make_marks(school, term, student, "mathematics", ca={"CA1": 70, "CA2": 70}, exam=70)
    return {"school": school, "term": term, "cls": cls, "admin": admin, "teacher": teacher, "student": student}


class Two:
    """Two schools. Logins happen lazily (and once) because every login costs real DB round-trips."""
    def __init__(self, login):
        self._login, self._cache = login, {}
        self.A, self.B = build("A"), build("B")

    def h(self, side, role):
        key = (side, role)
        if key not in self._cache:
            w = self.A if side == "A" else self.B
            if role == "parent":
                u, p = w["student"]["parent_username"], w["student"]["parent_password"]
            else:
                u, p = w[role]["username"], DEFAULT_PASSWORD
            self._cache[key] = self._login(w["school"], u, p)
        return self._cache[key]


@pytest.fixture
def two(login):
    return Two(login)


def login_status(client, school, user, pw):
    return client.post("/api/login", json={"reg_code": school["reg_code"], "username": user,
                                           "password": pw}).status_code


def call(client, method, path, headers):
    return getattr(client, method)(path, headers=headers, json={})


# ═══ 1. READS: SCHOOL A NEVER SEES SCHOOL B ═════════════════════
def test_lists_never_contain_the_other_school(two, client):
    a = two.h("A", "admin")
    for path, mine in (("/api/students", "A Pupil"), ("/api/teachers", "mr_a"),
                       ("/api/classes", "A Form 1"), ("/api/terms", "A Term")):
        r = client.get(path, headers=a)
        text = r.get_data(as_text=True)
        assert r.status_code == 200 and mine in text, f"{path}: own data missing ({r.status_code})"
        for theirs in ("B Pupil", "B Form 1", "B Term", "mr_b"):
            assert theirs not in text, f"{path} leaked '{theirs}' from school B"


def test_foreign_ids_are_invisible_for_reads(two, client):
    a, B = two.h("A", "admin"), two.B
    sid = B["student"]["id"]
    assert client.get(f"/api/report/{sid}", headers=a).status_code == 404
    assert client.get(f"/api/pdf/report/{sid}", headers=a).status_code == 404
    assert client.get(f"/api/access/status?student_id={sid}", headers=a).status_code == 404
    assert client.get(f"/api/results/assessments?term_id={B['term']['id']}", headers=a).status_code == 404
    assert client.get(f"/api/tests?term_id={B['term']['id']}", headers=a).get_json() == []
    # B's student is "student no. 1" in B and A's is "no. 1" in A: the number resolves inside the caller's school
    r = client.get("/api/students/resolve_display_id?no=1", headers=a).get_json()
    assert r["id"] == two.A["student"]["id"] != sid


def test_foreign_class_ids_return_nothing(two, client):
    a, cid = two.h("A", "admin"), two.B["cls"]["id"]
    for path in (f"/api/scoresheet?mode=terminal&class_id={cid}", f"/api/scoresheet?mode=exam&class_id={cid}",
                 f"/api/ranking/subject?subject=mathematics&class_id={cid}&assess=exam",
                 f"/api/analytics/overview?class_id={cid}",
                 f"/api/analytics/subject?subject=mathematics&class_id={cid}",
                 f"/api/pdf/terminal_sheet?class_id={cid}", f"/api/pdf/ca_sheet?class_id={cid}&ca_name=CA1",
                 f"/api/pdf/grade_sheet?mode=terminal&class_id={cid}"):
        r = client.get(path, headers=a)
        assert r.status_code < 500, f"{path} -> {r.status_code}"
        assert "B Pupil" not in r.get_data(as_text=True), f"{path} leaked school B's student"


# ═══ 2. WRITES: SCHOOL A CANNOT TOUCH SCHOOL B ══════════════════
def test_foreign_ids_cannot_be_modified(two, client):
    a, B = two.h("A", "admin"), two.B
    sid, tid = B["student"]["id"], B["term"]["id"]
    test_id = run("INSERT INTO term_tests(school_id,term_id,label,all_classes) VALUES(%s,%s,'Quiz',1) RETURNING id",
                  (B["school"]["id"], tid))

    assert client.patch(f"/api/students/{sid}", json={"name": "Hacked"}, headers=a).status_code == 404
    assert client.post(f"/api/students/{sid}/reset_parent_credentials", json={}, headers=a).status_code == 404
    assert client.patch(f"/api/terms/{tid}", json={"label": "Hacked"}, headers=a).status_code == 404
    assert client.post(f"/api/terms/{tid}/close", headers=a).status_code == 404
    assert client.post("/api/students/bulk_delete", json={"ids": [sid]}, headers=a).status_code == 404
    client.delete(f"/api/students/{sid}", headers=a)                     # status irrelevant; effect is what matters
    client.delete("/api/teachers/mr_b", headers=a)
    client.delete(f"/api/tests/{test_id}", headers=a)

    # a teacher of A aiming at B's class
    t = two.h("A", "teacher")
    r = client.post("/api/marks/exam", headers=t, json={"subject": "mathematics", "class_id": B["cls"]["id"],
                                                        "stream_id": None, "student_id": sid, "score": 1})
    assert r.status_code == 403

    assert query("SELECT name FROM students WHERE id=%s", (sid,)) == [("B Pupil",)]
    assert query("SELECT label,status FROM terms WHERE id=%s", (tid,)) == [("B Term", "open")]
    assert query("SELECT COUNT(*) FROM exam_scores WHERE school_id=%s", (B["school"]["id"],))[0][0] == 1
    assert query("SELECT COUNT(*) FROM ca_scores WHERE school_id=%s", (B["school"]["id"],))[0][0] == 2
    assert query("SELECT COUNT(*) FROM users WHERE school_id=%s AND username='mr_b'", (B["school"]["id"],))[0][0] == 1
    assert query("SELECT COUNT(*) FROM subject_assignments WHERE school_id=%s", (B["school"]["id"],))[0][0] == 1
    assert query("SELECT COUNT(*) FROM term_tests WHERE id=%s", (test_id,))[0][0] == 1
    assert login_status(client, B["school"], B["student"]["parent_username"], B["student"]["parent_password"]) == 200


def test_same_username_in_two_schools_stays_separate(two, client):
    A, B = two.A, two.B
    make_teacher(A["school"], username="shared", password="pw-for-A-1")
    make_teacher(B["school"], username="shared", password="pw-for-B-1")
    assert login_status(client, A["school"], "shared", "pw-for-B-1") == 401       # the code picks the school
    assert login_status(client, B["school"], "shared", "pw-for-A-1") == 401
    ha = two._login(A["school"], "shared", "pw-for-A-1")
    hb = two._login(B["school"], "shared", "pw-for-B-1")
    assert client.get("/api/config", headers=ha).get_json()["school_name"] == "A School"
    assert client.get("/api/config", headers=hb).get_json()["school_name"] == "B School"
    # A's admin fires A's "shared": B's "shared" must be untouched
    assert client.delete("/api/teachers/shared", headers=two.h("A", "admin")).status_code == 200
    assert client.get("/api/classes", headers=ha).status_code == 401
    assert client.get("/api/classes", headers=hb).status_code == 200


def test_school_selection_cannot_be_spoofed(two, client):
    a, b_id = two.h("A", "admin"), two.B["school"]["id"]
    spoofed = {**a, "X-School-ID": str(b_id)}
    names = [c["class_name"] for c in client.get("/api/classes", headers=spoofed).get_json()]
    assert names == ["A Form 1"]
    text = client.get(f"/api/students?school_id={b_id}", headers=a).get_data(as_text=True)
    assert "A Pupil" in text and "B Pupil" not in text


# ═══ 3. TOKENS ══════════════════════════════════════════════════
def test_bad_tokens_are_rejected(two, client, monkeypatch):
    a, t = two.h("A", "admin"), two.h("A", "teacher")
    token = a["Authorization"].split(" ", 1)[1]
    flipped = token[:-2] + ("BB" if token[-2:] == "AA" else "AA")
    assert client.get("/api/classes", headers={"Authorization": "Bearer " + flipped}).status_code == 401
    assert client.get("/api/classes", headers={"Authorization": "Bearer "}).status_code == 401
    assert client.get("/api/classes", headers={"Authorization": token}).status_code == 401      # missing "Bearer"

    # a deleted account's token dies immediately
    assert client.get("/api/classes", headers=t).status_code == 200
    assert client.delete("/api/teachers/mr_a", headers=a).status_code == 200
    assert client.get("/api/classes", headers=t).status_code == 401

    monkeypatch.setattr("core.auth.SESSION_MAX_AGE", -1)                                        # everything is expired
    r = client.get("/api/classes", headers=a)
    assert r.status_code == 401 and "expired" in r.get_json()["error"].lower()


# ═══ 4. ROLE MATRIX ═════════════════════════════════════════════
ADMIN_ONLY = [
    ("post", "/api/students/bulk_delete"), ("delete", "/api/students/1"), ("patch", "/api/students/1"),
    ("post", "/api/students/1/reset_parent_credentials"), ("post", "/api/teachers"), ("delete", "/api/teachers/x"),
    ("post", "/api/teachers/x/class_teacher"), ("post", "/api/assign_teacher"), ("post", "/api/unassign_teacher"),
    ("post", "/api/classes"), ("delete", "/api/classes/1"), ("post", "/api/classes/1/streams"),
    ("delete", "/api/streams/1"), ("post", "/api/terms"), ("patch", "/api/terms/1"), ("post", "/api/terms/1/close"),
    ("post", "/api/tests"), ("delete", "/api/tests/1"), ("post", "/api/subjects"), ("post", "/api/grades"),
    ("post", "/api/config/grading_system"), ("post", "/api/config/school_info"), ("post", "/api/config/school_name"),
    ("get", "/api/config/reg_code"), ("post", "/api/config/reg_code"), ("post", "/api/config/logo"),
    ("post", "/api/config/onboarding_complete"), ("post", "/api/announcements"), ("delete", "/api/announcements/1"),
    ("post", "/api/results/toggle"), ("post", "/api/results/publish_assessments"),
    ("get", "/api/subscription/status"), ("post", "/api/subscription/select_free"),
    ("post", "/api/subscription/request"), ("get", "/api/stars/dashboard"), ("get", "/api/stars/history"),
    ("post", "/api/stars/withdraw"), ("post", "/api/stars/payout_account"),
    ("get", "/api/students/import/template"), ("post", "/api/students/import"),
    ("post", "/api/students/import/preview"), ("post", "/api/students/import/columns"),
    ("get", "/api/analytics/dashboard_classes"),
]
STAFF_ONLY = [
    ("post", "/api/students"), ("post", "/api/marks/ca"), ("post", "/api/marks/exam"), ("post", "/api/marks/test"),
    ("get", "/api/scoresheet"), ("get", "/api/ranking/subject"), ("get", "/api/pdf/ca_sheet"),
    ("get", "/api/pdf/grade_sheet"), ("get", "/api/pdf/terminal_sheet"),
]
PARENT_ONLY = [("get", "/api/parent/results?student_id=1")]
NOT_FOR_TEACHERS = [("post", "/api/access/pay"), ("post", "/api/access/check/1")]


def test_role_matrix(two, client):
    matrix = {"parent": ADMIN_ONLY + STAFF_ONLY,
              "teacher": ADMIN_ONLY + PARENT_ONLY + NOT_FOR_TEACHERS,
              "admin": PARENT_ONLY}
    wrong = []
    for role, endpoints in matrix.items():
        h = two.h("A", role)
        for method, path in endpoints:
            r = call(client, method, path, h)
            if r.status_code != 403:
                wrong.append(f"{role} {method.upper()} {path} -> {r.status_code} (expected 403)")
    assert not wrong, "role restrictions broken:\n  " + "\n  ".join(wrong)


# ═══ 5. PARENT ISOLATION ════════════════════════════════════════
def test_parent_cannot_reach_another_childs_data(two, client):
    A, B = two.A, two.B
    pa = two.h("A", "parent")
    sib = make_student(A["school"], A["cls"], name="A Sibling", phone="0711000222")
    mine = A["student"]["id"]
    for other in (sib["id"], B["student"]["id"]):
        assert client.get(f"/api/report/{other}", headers=pa).status_code == 403, other
        assert client.get(f"/api/pdf/report/{other}", headers=pa).status_code == 403, other
        assert client.get(f"/api/parent/results?student_id={other}&term_id={A['term']['id']}&assess=exam",
                          headers=pa).status_code == 403, other
        assert client.get(f"/api/announcements?student_id={other}", headers=pa).status_code == 403, other
        assert client.post("/api/announcements/1/read", json={"student_id": other}, headers=pa).status_code == 403
        # the access endpoints pin a parent to their own child no matter what is asked for
        assert client.get(f"/api/access/status?student_id={other}", headers=pa).get_json()["student_id"] == mine

    def pay(school, student):
        return run("""INSERT INTO student_payments(school_id,student_id,plan,duration_days,amount,status,initiated_role)
                      VALUES(%s,%s,'6m',182,500,'pending','parent') RETURNING id""", (school["id"], student["id"]))
    assert client.post(f"/api/access/check/{pay(A['school'], sib)}", json={}, headers=pa).status_code == 403
    assert client.post(f"/api/access/check/{pay(B['school'], B['student'])}", json={}, headers=pa).status_code == 404


def test_credential_downloads_are_school_scoped(two, client):
    token = "tok" * 8
    creds = [{"row": 2, "name": "X", "class_name": "A Form 1", "stream_name": "", "parent_phone": "0711000000",
              "username": "x", "password": "1234"}]
    run("INSERT INTO import_credential_batches(school_id,token,data) VALUES(%s,%s,%s)",
        (two.A["school"]["id"], token, Json(creds)))
    url = f"/api/students/import/credentials/{token}"
    assert client.get(url, headers=two.h("B", "admin")).status_code == 404       # another school's admin
    assert client.get(url, headers=two.h("A", "teacher")).status_code == 403
    r = client.get(url, headers=two.h("A", "admin"))
    data = r.get_data(); r.close()
    assert r.status_code == 200 and data[:2] == b"PK"


# ═══ 6. SUPERADMIN ══════════════════════════════════════════════
def test_superadmin_endpoints_reject_everyone_else(two, client):
    sid = two.A["school"]["id"]
    endpoints = [
        ("get", "/api/superadmin/schools"), ("get", "/api/superadmin/schools/pending"),
        ("post", f"/api/superadmin/schools/{sid}/approve"), ("post", f"/api/superadmin/schools/{sid}/reject"),
        ("get", "/api/superadmin/announce"), ("post", "/api/superadmin/announce"),
        ("delete", "/api/superadmin/announce/1"), ("get", "/api/superadmin/payment_requests"),
        ("post", "/api/superadmin/payment_requests/1/approve"), ("post", "/api/superadmin/payment_requests/1/reject"),
        ("get", "/api/superadmin/payment_config"), ("post", "/api/superadmin/payment_config"),
        ("get", "/api/superadmin/star_withdrawals"), ("post", "/api/superadmin/star_withdrawals/1/approve"),
        ("post", "/api/superadmin/star_withdrawals/1/reject"),
    ]
    callers = {"school admin": two.h("A", "admin"), "teacher": two.h("A", "teacher"),
               "parent": two.h("A", "parent"), "nobody": {}}
    wrong = [f"{who} {m.upper()} {p} -> {call(client, m, p, h).status_code}"
             for who, h in callers.items() for m, p in endpoints
             if call(client, m, p, h).status_code != 401]
    assert not wrong, "superadmin routes reachable without superadmin auth:\n  " + "\n  ".join(wrong)
    assert query("SELECT verification_status FROM schools WHERE id=%s", (sid,)) == [("approved",)]

    sa = client.post("/api/superadmin/login", json={"username": "test_superadmin", "password": "test_superadmin_pw"})
    h = {"Authorization": "Bearer " + sa.get_json()["token"]}
    ids = {s["id"] for s in client.get("/api/superadmin/schools", headers=h).get_json()["schools"]}
    assert ids == {two.A["school"]["id"], two.B["school"]["id"]}


# ═══ 7. TEACHER / CLASS-TEACHER SCOPE ═══════════════════════════
def test_remark_permissions(two, client):
    A = two.A
    student = A["student"]["id"]
    other = make_class(A["school"], "A Other")
    make_teacher(A["school"], username="ct_other", class_teacher_of=other)
    make_teacher(A["school"], username="ct_own", class_teacher_of=A["cls"])
    body = lambda **kw: {"is_class_teacher": True, "student_id": student, "remark": "note", **kw}

    assert client.post("/api/remarks", json=body(), headers=two.h("A", "teacher")).status_code == 403      # lying about being CT
    assert client.post("/api/remarks", json=body(), headers=two.h("A", "parent")).status_code == 403
    assert client.post("/api/remarks", json=body(), headers=two._login(A["school"], "ct_other")).status_code == 403
    assert query("SELECT COUNT(*) FROM remarks")[0][0] == 0

    assert client.post("/api/remarks", json=body(remark="class note"), headers=two._login(A["school"], "ct_own")).status_code == 200
    r = client.post("/api/remarks", json=body(is_class_teacher=False, remark="head note"), headers=two.h("A", "admin"))
    assert r.status_code == 200
    assert query("SELECT class_teacher_remark, head_remark FROM remarks WHERE student_id=%s", (student,)) == \
        [("class note", "head note")]
    foreign = client.post("/api/remarks", json=body(student_id=two.B["student"]["id"]), headers=two.h("A", "admin"))
    assert foreign.status_code == 404


def test_teacher_analytics_scope_is_server_enforced(two, client):
    A = two.A
    other = make_class(A["school"], "A Other")
    kid = make_student(A["school"], other, name="Hidden Kid", phone="0711000444")
    make_marks(A["school"], A["term"], kid, "mathematics", ca={"CA1": 20, "CA2": 20}, exam=20)
    plain = two.h("A", "teacher")
    assert client.get("/api/analytics/overview", headers=plain).status_code == 403            # not a class teacher
    r = client.get(f"/api/analytics/subject?subject=physics&class_id={A['cls']['id']}", headers=plain)
    assert r.status_code == 403                                                                # not assigned to physics

    make_teacher(A["school"], username="ct_a", class_teacher_of=A["cls"])
    ct = two._login(A["school"], "ct_a")
    d = client.get(f"/api/analytics/overview?class_id={other['id']}", headers=ct).get_json()
    assert d["ok"] and d["average"] == 70      # own class (all 70s); the other class (all 20s) was requested but ignored


# ═══ SECURITY  GUARDS ═════════════════════════════
def test_parent_cannot_list_students(two, client):
    assert client.get("/api/students", headers=two.h("A", "parent")).status_code == 403


def test_parent_cannot_list_teachers(two, client):
    assert client.get("/api/teachers", headers=two.h("A", "parent")).status_code == 403


def test_marks_cannot_target_students_outside_the_class(two, client):
    A = two.A
    outsider = make_student(A["school"], make_class(A["school"], "A Form 2"), name="A Outsider", phone="0711000333")
    for who in ("teacher", "admin"):
        for sid in (outsider["id"], two.B["student"]["id"]):
            r = client.post("/api/marks/exam", headers=two.h("A", who),
                            json={"subject": "mathematics", "class_id": A["cls"]["id"], "stream_id": None,
                                  "student_id": sid, "score": 1})
            assert r.status_code in (400, 403, 404), f"{who} wrote a mark for student {sid}: HTTP {r.status_code}"


def test_admin_cannot_unscope_another_schools_test(two, client):
    B = two.B
    tid = run("INSERT INTO term_tests(school_id,term_id,label,all_classes) VALUES(%s,%s,'Quiz',0) RETURNING id",
              (B["school"]["id"], B["term"]["id"]))
    run("INSERT INTO test_classes(test_id,class_id) VALUES(%s,%s)", (tid, B["cls"]["id"]))
    client.delete(f"/api/tests/{tid}", headers=two.h("A", "admin"))
    assert query("SELECT COUNT(*) FROM test_classes WHERE test_id=%s", (tid,))[0][0] == 1


def test_deleting_a_foreign_student_id_keeps_their_read_receipts(two, client):
    B = two.B
    ann = run("INSERT INTO announcements(school_id,title,body,target_classes,posted_by) "
              "VALUES(%s,'t','b','all','admin') RETURNING id", (B["school"]["id"],))
    run("INSERT INTO announcement_reads(announcement_id,student_id) VALUES(%s,%s)", (ann, B["student"]["id"]))
    client.delete(f"/api/students/{B['student']['id']}", headers=two.h("A", "admin"))
    assert query("SELECT COUNT(*) FROM announcement_reads WHERE student_id=%s", (B["student"]["id"],))[0][0] == 1


def test_cannot_add_stream_to_another_schools_class(two, client):
    cid = two.B["cls"]["id"]
    r = client.post(f"/api/classes/{cid}/streams", json={"stream_name": "Z"}, headers=two.h("A", "admin"))
    assert r.status_code in (400, 404)
    assert query("SELECT COUNT(*) FROM streams WHERE class_id=%s", (cid,))[0][0] == 0


def test_idempotency_key_does_not_cross_schools(two, client):
    run("""INSERT INTO star_transactions(school_id,type,stars,amount,reference_type,description,status)
           VALUES(%s,'CYCLE_REWARD',3,30000,'star_cycle','seed','AVAILABLE')""", (two.A["school"]["id"],))
    a, b = two.h("A", "admin"), two.h("B", "admin")
    assert client.post("/api/stars/payout_account", json={"account_identifier": "0712345678"}, headers=a).status_code == 200
    r = client.post("/api/stars/withdraw", json={"stars": 2, "idempotency_key": "shared-key-123"}, headers=a)
    assert r.status_code == 200 and r.get_json()["stars"] == 2
    leak = client.post("/api/stars/withdraw", json={"stars": 1, "idempotency_key": "shared-key-123"}, headers=b).get_json()
    assert not leak.get("already_existed"), f"school B was handed school A's withdrawal: {leak}"