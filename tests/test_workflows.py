"""Phase 7: core workflow tests. Every test builds its own school; nothing touches your demo schools.
Tests marked xfail document REAL bugs in the app: they stay 'xfailed' until you fix the bug, then flip to XPASS."""
import hashlib
import hmac
import io
import json
from datetime import datetime, timedelta, timezone

import pytest

from services.stars import get_or_create_referral_token
from tests.factories import (DEFAULT_PASSWORD, DEFAULT_SUBJECTS, run, query, make_school, make_term,
                             make_class, make_stream, make_admin, make_teacher, assign_teacher,
                             make_student, make_marks)

SEVEN = [s for s, _ in DEFAULT_SUBJECTS]


# ── helpers ─────────────────────────────────────────────────────
def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def ok(resp, label, status=200):
    body = resp.get_json(silent=True)
    assert resp.status_code == status, f"[{label}] expected HTTP {status}, got {resp.status_code}: {body}"
    if isinstance(body, dict) and "ok" in body and status < 400:
        assert body["ok"] is True, f"[{label}] {body}"
    return body


def classroom(n_students=3, **term_kw):
    school = make_school(); term = make_term(school, **term_kw)
    cls = make_class(school); admin = make_admin(school)
    studs = [make_student(school, cls, name=f"Pupil {chr(65 + i)}", phone=f"07110000{i:02d}")
             for i in range(n_students)]
    return school, term, cls, admin, studs


def report(client, headers, student, term=None):
    q = f"?term_id={term['id']}" if term else ""
    return ok(client.get(f"/api/report/{student['id']}{q}", headers=headers), f"report {student['name']}")


def login_status(client, school, user, pw):
    return client.post("/api/login", json={"reg_code": school["reg_code"], "username": user,
                                           "password": pw}).status_code


def csv_file(header, rows, name="students.csv"):
    return (io.BytesIO((header + "\n" + "\n".join(rows) + "\n").encode()), name)


def do_import(client, headers, rows, header="name,class_name,stream_name,parent_phone", mapping=None, colmap=None):
    colmap = colmap or {"name": ["name"], "class": "class_name", "stream": "stream_name", "phone": "parent_phone"}
    data = {"file": csv_file(header, rows), "column_map": json.dumps(colmap), "mapping": json.dumps(mapping or {})}
    return client.post("/api/students/import", data=data, headers=headers)


def score_subjects(school, term, student, subjects, score):
    for subj in subjects:
        make_marks(school, term, student, subj, ca={"CA1": score, "CA2": score}, exam=score)


def grant_access(school, student, days=30):
    run("INSERT INTO student_access(school_id,student_id,plan,expires_at) VALUES(%s,%s,'6m',%s)",
        (school["id"], student["id"], _now() + timedelta(days=days)))


def sa_headers(client):
    r = client.post("/api/superadmin/login", json={"username": "test_superadmin", "password": "test_superadmin_pw"})
    return {"Authorization": "Bearer " + r.get_json()["token"]}


# ═══ 1. SCHOOL REGISTRATION ═════════════════════════════════════
def reg_form(**over):
    f = {"school_name": "Reg School", "admin_username": "head", "admin_password": "headpass1", "phone": "",
         "email": "", "admin_phone": "", "motto": "", "reg_code": "S5555", "agree_terms": "1", "ref_token": "",
         "classes": json.dumps([{"name": "Form 1", "streams": ["A"]}]),
         "subjects": json.dumps([{"name": "Mathematics", "abbreviation": "MATH"}]),
         "grades": json.dumps([{"min_score": 0, "max_score": 100, "grade": "A"}])}
    f.update(over)
    return f


@pytest.mark.parametrize("over,why", [
    ({"school_name": ""}, "no school name"), ({"agree_terms": "0"}, "terms not accepted"),
    ({"reg_code": "BAD"}, "invalid NECTA code"), ({"subjects": "[]"}, "no subjects"),
    ({"grades": "[]"}, "no grades"), ({"classes": "not json"}, "malformed JSON")])
def test_registration_rejects_bad_input(client, over, why):
    assert client.post("/api/register/school", data=reg_form(**over)).status_code == 400, why
    assert query("SELECT COUNT(*) FROM schools")[0][0] == 0, f"{why}: a school was created anyway"


def test_registration_rejects_non_image_logo(client):
    data = reg_form(); data["logo"] = (io.BytesIO(b"MZ"), "evil.exe")
    assert client.post("/api/register/school", data=data).status_code == 400
    assert query("SELECT COUNT(*) FROM schools")[0][0] == 0


def test_registration_builds_a_usable_school(client, login):
    sid = ok(client.post("/api/register/school", data=reg_form()), "register")["school_id"]
    admin = login({"reg_code": "S5555"}, "head", "headpass1")
    subs = ok(client.get("/api/subjects", headers=admin), "subjects")
    assert [(s["name"], s["abbreviation"]) for s in subs] == [("mathematics", "MATH")]   # lower-cased on save
    classes = ok(client.get("/api/classes", headers=admin), "classes")
    assert [(c["class_name"], [s["stream_name"] for s in c["streams"]]) for c in classes] == [("Form 1", ["A"])]
    assert ok(client.get("/api/config", headers=admin), "config")["verification_status"] == "pending"
    assert query("SELECT school_id FROM users WHERE username='head'") == [(sid,)]


def test_registration_with_referral_link_records_relationship_but_no_reward(client):
    referrer = make_school()
    token = get_or_create_referral_token(referrer["id"])
    sid = ok(client.post("/api/register/school", data=reg_form(ref_token=token, reg_code="S6666")), "register")["school_id"]
    assert query("SELECT referring_school_id, referred_school_id FROM star_referral_relationships") == [(referrer["id"], sid)]
    assert query("SELECT COUNT(*) FROM star_transactions")[0][0] == 0      # reward only after first completed cycle


# ═══ 2. SCHOOL CONFIGURATION ════════════════════════════════════
def test_subjects_and_grades_are_admin_only_and_roundtrip(client, login):
    school = make_school(); admin = make_admin(school); teacher = make_teacher(school)
    a, t = login(school, admin["username"]), login(school, teacher["username"])
    subs = [{"name": "Physics", "abbreviation": "phy"}, {"name": "Chemistry", "abbreviation": "CHEM"}]
    assert client.post("/api/subjects", json={"subjects": subs}, headers=t).status_code == 403
    ok(client.post("/api/subjects", json={"subjects": subs}, headers=a), "save subjects")
    cfg = ok(client.get("/api/config", headers=a), "config")
    assert cfg["allowed_subjects"] == ["physics", "chemistry"] and cfg["subject_abbr"]["physics"] == "PHY"

    grades = [{"min_score": 50, "max_score": 100, "grade": "P"}, {"min_score": 0, "max_score": 49, "grade": "F"}]
    assert client.post("/api/grades", json={"grades": grades}, headers=t).status_code == 403
    ok(client.post("/api/grades", json={"grades": grades}, headers=a), "save grades")
    rules = ok(client.get("/api/grades", headers=a), "grades")
    assert [(r["grade"], r["points"]) for r in rules] == [("P", 1), ("F", 2)]       # missing points default to 1,2,...


def test_grading_system_settings(client, login):
    school = make_school(); admin = make_admin(school); a = login(school, admin["username"])
    url = "/api/config/grading_system"
    assert client.post(url, json={"grading_system": "z", "division_source": "school"}, headers=a).status_code == 400
    assert client.post(url, json={"grading_system": "o_level", "division_source": "z"}, headers=a).status_code == 400
    ok(client.post(url, json={"grading_system": "a_level", "division_source": "necta",
                              "principal_subjects": ["mathematics", "physics"],
                              "non_credit_subjects": ["geography"]}, headers=a), "save grading system")
    gs = ok(client.get(url, headers=a), "read grading system")
    assert (gs["grading_system"], gs["division_source"]) == ("a_level", "necta")
    assert set(gs["principal_subjects"]) == {"mathematics", "physics"} and gs["non_credit_subjects"] == ["geography"]


def test_registration_code_change(client, login):
    s1 = make_school(); s2 = make_school(); admin = make_admin(s1)
    a = login(s1, admin["username"])
    assert client.post("/api/config/reg_code", json={"reg_code": "x"}, headers=a).status_code == 400
    assert client.post("/api/config/reg_code", json={"reg_code": s2["reg_code"].lower()}, headers=a).status_code == 409
    ok(client.post("/api/config/reg_code", json={"reg_code": "My_School_9"}, headers=a), "change code")
    assert login_status(client, s1, "admin", DEFAULT_PASSWORD) == 401                 # old code is dead
    login({"reg_code": "my_school_9"}, "admin")                                        # new one is case-insensitive


# ═══ 3. TERMS ═══════════════════════════════════════════════════
def test_term_lifecycle(client, login):
    school = make_school(); admin = make_admin(school); cls = make_class(school)
    student = make_student(school, cls)
    a = login(school, admin["username"])
    ok(client.post("/api/terms", json={"label": "T1", "ca_count": 3, "ca_weight": 40, "exam_weight": 60}, headers=a), "open")
    assert client.get("/api/terms/active", headers=a).get_json()["term"]["label"] == "T1"
    tid = client.get("/api/terms/active", headers=a).get_json()["term"]["id"]

    assert client.patch(f"/api/terms/{tid}", json={"ca_count": 0}, headers=a).status_code == 400
    assert client.patch(f"/api/terms/{tid}", json={"ca_weight": 50, "exam_weight": 40}, headers=a).status_code == 400
    ok(client.patch(f"/api/terms/{tid}", json={"label": "T1 fixed", "ca_count": 4, "ca_weight": 50,
                                               "exam_weight": 50}, headers=a), "edit open term")
    t = ok(client.get("/api/terms", headers=a), "list")[0]
    assert (t["label"], t["ca_count"], t["ca_weight"], t["exam_weight"]) == ("T1 fixed", 4, 50, 50)

    ok(client.post(f"/api/terms/{tid}/close", headers=a), "close")
    assert client.post(f"/api/terms/{tid}/close", headers=a).status_code == 400          # already closed
    assert client.patch(f"/api/terms/{tid}", json={"label": "nope"}, headers=a).status_code == 400   # locked
    assert client.get("/api/terms/active", headers=a).get_json()["term"] is None
    r = client.post("/api/marks/exam", headers=a, json={"subject": "mathematics", "class_id": cls["id"],
                                                        "student_id": student["id"], "score": 50})
    assert r.status_code == 400 and "No active term" in r.get_json()["error"]            # marks locked with the term
    ok(client.post("/api/terms", json={"label": "T2", "ca_count": 2, "ca_weight": 30, "exam_weight": 70}, headers=a),
       "next term can open")


# ═══ 4. TEACHERS ════════════════════════════════════════════════
def test_teacher_management(client, login):
    school, term, cls, admin, _ = classroom(0)
    stream = make_stream(school, cls, "A")
    a = login(school, admin["username"])
    mk = {"username": "mr_x", "password": "temp123"}
    ok(client.post("/api/teachers", json=mk, headers=a), "create")
    assert client.post("/api/teachers", json=mk, headers=a).status_code == 409
    assert client.post("/api/teachers", json={"username": "mr_y", "password": ""}, headers=a).status_code == 400
    teachers = ok(client.get("/api/teachers", headers=a), "list")
    assert [t["username"] for t in teachers] == ["mr_x"] and teachers[0]["must_change_password"] == 1

    for subj, sid in (("Mathematics", None), ("Physics", stream["id"])):
        ok(client.post("/api/assign_teacher", headers=a, json={"username": "mr_x", "subject": subj,
                                                               "class_id": cls["id"], "stream_id": sid}), f"assign {subj}")
    got = ok(client.get("/api/teachers", headers=a), "list")[0]["assignments"]
    assert {(x["subject"], x["stream_name"]) for x in got} == {("mathematics", None), ("physics", "A")}
    ok(client.post("/api/unassign_teacher", headers=a, json={"username": "mr_x", "subject": "mathematics",
                                                             "class_id": cls["id"], "stream_id": None}), "unassign")
    got = ok(client.get("/api/teachers", headers=a), "list")[0]["assignments"]
    assert [(x["subject"], x["stream_name"]) for x in got] == [("physics", "A")]

    ct = f"/api/teachers/mr_x/class_teacher"
    assert client.post(ct, json={"is_class_teacher": True}, headers=a).status_code == 400    # class required
    ok(client.post(ct, json={"is_class_teacher": True, "class_id": cls["id"], "stream_id": None}, headers=a), "set CT")
    row = ok(client.get("/api/teachers", headers=a), "list")[0]
    assert row["is_class_teacher"] and row["class_name"] == "Form 1"

    t_h = login(school, "mr_x", "temp123")
    assert client.post("/api/teachers", json={"username": "evil", "password": "x12345"}, headers=t_h).status_code == 403
    ok(client.delete("/api/teachers/mr_x", headers=a), "delete")
    assert query("SELECT COUNT(*) FROM subject_assignments")[0][0] == 0
    assert ok(client.get("/api/teachers", headers=a), "list") == []


@pytest.mark.xfail(strict=False, reason="BUG: UNIQUE(school,user,subject,class,stream_id) never fires when stream_id "
                                        "is NULL (Postgres treats NULLs as distinct), so whole-class assignments duplicate")
def test_duplicate_whole_class_assignment_is_rejected(client, login):
    school, term, cls, admin, _ = classroom(0)
    teacher = make_teacher(school); a = login(school, admin["username"])
    body = {"username": teacher["username"], "subject": "mathematics", "class_id": cls["id"], "stream_id": None}
    ok(client.post("/api/assign_teacher", json=body, headers=a), "first assignment")
    assert client.post("/api/assign_teacher", json=body, headers=a).status_code == 409


# ═══ 5. STUDENTS ════════════════════════════════════════════════
def test_student_add_edit_reset_delete(client, login):
    school, term, cls, admin, _ = classroom(0)
    a = login(school, admin["username"])
    r = ok(client.post("/api/students", headers=a, json={"name": "Neema Peter", "class_id": cls["id"],
                                                         "phone_number": "0755123456"}), "add")
    assert (r["parent_username"], r["temp_password"]) == ("neema_peter", "3456")
    old_token = login(school, "neema_peter", "3456")
    sid = ok(client.get("/api/students", headers=a), "list")[0]["id"]

    r = ok(client.patch(f"/api/students/{sid}", headers=a,
                        json={"name": "Neema Peter Jr", "phone_number": "0755999999"}), "edit name+phone")
    assert (r["new_username"], r["new_password"]) == ("neema_peter_jr", "9999")
    assert login_status(client, school, "neema_peter", "3456") == 401                  # old credentials die
    assert client.get("/api/access/status", headers=old_token).status_code == 401      # ...and so does the old session
    assert login_status(client, school, "neema_peter_jr", "9999") == 200

    r = ok(client.post(f"/api/students/{sid}/reset_parent_credentials", json={}, headers=a), "reset")
    assert (r["username"], r["temp_password"]) == ("neema_peter_jr", "9999")

    ok(client.delete(f"/api/students/{sid}", headers=a), "delete")
    assert login_status(client, school, "neema_peter_jr", "9999") == 401
    assert query("SELECT COUNT(*) FROM students")[0][0] == 0


def test_same_name_students_get_a_warning_not_a_crash(client, login):
    school, term, cls, admin, _ = classroom(0)
    a = login(school, admin["username"])
    r1 = ok(client.post("/api/students", headers=a, json={"name": "Twin Name", "class_id": cls["id"],
                                                          "phone_number": "0711110001"}), "first twin")
    r2 = ok(client.post("/api/students", headers=a, json={"name": "Twin Name", "class_id": cls["id"],
                                                          "phone_number": "0711110002"}), "second twin")
    assert r1["parent_username"] == "twin_name"
    assert r2["parent_username"] is None and "already taken" in r2["warning"]       # student saved, no login created
    assert query("SELECT COUNT(*) FROM students")[0][0] == 2


def test_cannot_add_student_to_another_schools_class(client, login):
    school, term, cls, admin, _ = classroom(0)
    foreign_class = make_class(make_school())
    a = login(school, admin["username"])
    r = client.post("/api/students", headers=a, json={"name": "Sneaky", "class_id": foreign_class["id"],
                                                      "phone_number": "0711110001"})
    assert r.status_code == 400 and query("SELECT COUNT(*) FROM students")[0][0] == 0


def test_bulk_delete_only_touches_own_school(client, login):
    school, term, cls, admin, studs = classroom(3)
    other = make_school(); foreign = make_student(other, make_class(other))
    for s in studs:
        make_marks(school, term, s, "mathematics", exam=50)
    a = login(school, admin["username"])
    r = ok(client.post("/api/students/bulk_delete", headers=a,
                       json={"ids": [studs[0]["id"], studs[1]["id"], foreign["id"]]}), "bulk delete")
    assert r["deleted"] == 2
    assert query("SELECT COUNT(*) FROM exam_scores WHERE school_id=%s", (school["id"],))[0][0] == 1
    assert query("SELECT COUNT(*) FROM students WHERE id=%s", (foreign["id"],))[0][0] == 1
    assert login_status(client, school, studs[0]["parent_username"], studs[0]["parent_password"]) == 401
    assert login_status(client, school, studs[2]["parent_username"], studs[2]["parent_password"]) == 200


# ═══ 6. STUDENT IMPORT ══════════════════════════════════════════
def test_import_unmatched_class_is_skipped_until_mapped(client, login):
    school, term, cls, admin, _ = classroom(0)
    a = login(school, admin["username"])
    rows = ["Kili Ally,Form 9,,0711000001"]
    r = ok(do_import(client, a, rows), "import without mapping")
    assert (r["inserted"], r["skipped"]) == (0, 1) and "not found" in r["skipped_details"][0]["reason"]
    r = ok(do_import(client, a, rows, mapping={"classes": {"Form 9": "Form 1"}}), "import with mapping")
    assert r["inserted"] == 1
    assert query("SELECT class_id FROM students WHERE school_id=%s", (school["id"],)) == [(cls["id"],)]


def test_import_without_phone_is_flagged_not_dropped(client, login):
    school, term, cls, admin, _ = classroom(0)
    a = login(school, admin["username"])
    r = ok(do_import(client, a, ["No Phone,Form 1,,"]), "import")
    assert r["inserted"] == 1 and len(r["flagged_details"]) == 1 and r["credentials_file"] is None
    assert "Missing parent phone" in query("SELECT flag_reason FROM students WHERE name='No Phone'")[0][0]
    assert query("SELECT COUNT(*) FROM users WHERE role='parent'")[0][0] == 0


def test_import_duplicate_rows_in_one_file(client, login):
    school, term, cls, admin, _ = classroom(0)
    a = login(school, admin["username"])
    r = ok(do_import(client, a, ["Dup One,Form 1,,0711000009"] * 2), "import")
    assert (r["inserted"], r["duplicates"]) == (1, 1)


def test_import_first_name_surname_headers(client, login):
    school, term, cls, admin, _ = classroom(0)
    a = login(school, admin["username"])
    header = "First Name,Surname,Class,Phone"; rows = ["John,Mkapa,Form 1,0722000001"]
    cols = ok(client.post("/api/students/import/columns", data={"file": csv_file(header, rows)}, headers=a), "columns")
    assert cols["suggested"]["name"] == ["First Name", "Surname"]
    r = ok(do_import(client, a, rows, header=header, colmap=cols["suggested"]), "import")
    assert (r["inserted"], r["credentials_count"]) == (1, 1)
    assert query("SELECT name FROM students")[0][0] == "John Mkapa"


def test_import_rejects_bad_files_and_non_admins(client, login):
    school, term, cls, admin, _ = classroom(0)
    teacher = make_teacher(school)
    a, t = login(school, admin["username"]), login(school, teacher["username"])
    r = client.post("/api/students/import/columns", headers=a, data={"file": (io.BytesIO(b"x"), "students.txt")})
    assert r.status_code == 400 and "Unsupported" in r.get_json()["error"]
    r = client.post("/api/students/import/columns", headers=a, data={"file": csv_file("name,class_name", [])})
    assert r.status_code == 400
    r = client.post("/api/students/import/columns", headers=t, data={"file": csv_file("name,class_name", ["a,b"])})
    assert r.status_code == 403


# ═══ 7. MARKS ENTRY ═════════════════════════════════════════════
def test_marks_entry_rules(client, login):
    school, term, cls, admin, studs = classroom(1)
    form2 = make_class(school, "Form 2")
    teacher = make_teacher(school); assign_teacher(school, teacher, "mathematics", cls)
    t = login(school, teacher["username"])
    p = login(school, studs[0]["parent_username"], studs[0]["parent_password"])
    body = lambda **kw: {"subject": "mathematics", "class_id": cls["id"], "stream_id": None,
                         "student_id": studs[0]["id"], **kw}

    ok(client.post("/api/marks/ca", json=body(ca_name="CA1", score=50), headers=t), "first entry")
    ok(client.post("/api/marks/ca", json=body(ca_name="CA1", score=60), headers=t), "correction")
    assert query("SELECT score FROM ca_scores") == [(60,)]                         # upsert, not a second row
    for bad in (-1, 100.5, 101):
        assert client.post("/api/marks/ca", json=body(ca_name="CA1", score=bad), headers=t).status_code == 400, bad
    for edge in (0, 100):
        ok(client.post("/api/marks/exam", json=body(score=edge), headers=t), f"exam {edge}")
    assert query("SELECT score FROM exam_scores") == [(100,)]

    assert client.post("/api/marks/ca", json=body(ca_name="CA1", score=50, subject="english"), headers=t).status_code == 403
    assert client.post("/api/marks/ca", json=body(ca_name="CA1", score=50, class_id=form2["id"]), headers=t).status_code == 403
    assert client.post("/api/marks/ca", json=body(ca_name="CA1", score=50), headers=p).status_code == 403   # parents can't mark


def test_stream_scoped_teacher_cannot_mark_other_stream(client, login):
    school, term, cls, admin, _ = classroom(0)
    sa_, sb = make_stream(school, cls, "A"), make_stream(school, cls, "B")
    student = make_student(school, cls, stream=sa_, name="Pupil A", phone="0711000000")
    teacher = make_teacher(school); assign_teacher(school, teacher, "mathematics", cls, sa_)
    t = login(school, teacher["username"])
    body = lambda stream: {"subject": "mathematics", "class_id": cls["id"], "stream_id": stream["id"],
                           "student_id": student["id"], "score": 70}
    ok(client.post("/api/marks/exam", json=body(sa_), headers=t), "own stream")
    assert client.post("/api/marks/exam", json=body(sb), headers=t).status_code == 403


def test_test_scores_respect_class_scope(client, login):
    school, term, cls, admin, studs = classroom(1)
    form2 = make_class(school, "Form 2"); other_kid = make_student(school, form2, name="Other Kid")
    a = login(school, admin["username"])
    tid = ok(client.post("/api/tests", headers=a, json={"term_id": term["id"], "label": "Quiz",
                                                        "class_ids": [cls["id"]]}), "create test")["id"]
    mark = lambda c, s: client.post("/api/marks/test", headers=a, json={"subject": "mathematics", "class_id": c["id"],
                                                                        "stream_id": None, "student_id": s["id"],
                                                                        "test_id": tid, "score": 55})
    ok(mark(cls, studs[0]), "participating class")
    assert mark(form2, other_kid).status_code == 403


def test_garbage_input_is_a_400_not_a_500(client, login):
    school, term, cls, admin, studs = classroom(1)
    a = login(school, admin["username"])
    good = {"subject": "mathematics", "class_id": cls["id"], "stream_id": None,
            "student_id": studs[0]["id"], "score": 50}
    for kind, extra in (("exam", {}), ("ca", {"ca_name": "CA1"})):
        for field, junk in (("score", "abc"), ("score", None), ("score", "nan"), ("score", "inf"),
                            ("student_id", "x"), ("class_id", None), ("stream_id", "abc")):
            r = client.post(f"/api/marks/{kind}", headers=a, json={**good, **extra, field: junk})
            assert r.status_code == 400, f"/marks/{kind} with {field}={junk!r} -> HTTP {r.status_code}"
    r = client.post("/api/marks/exam", headers=a, data="not json", content_type="application/json")
    assert r.status_code == 400
    assert query("SELECT COUNT(*) FROM error_events")[0][0] == 0      # user error, not a monitoring incident


def test_ca_endpoint_rejects_fake_ca_names(client, login):
    school, term, cls, admin, studs = classroom(1)
    a = login(school, admin["username"])
    for name in ("test:5", "junk", "CA99"):
        r = client.post("/api/marks/ca", headers=a, json={"subject": "mathematics", "class_id": cls["id"],
                                                          "student_id": studs[0]["id"], "ca_name": name, "score": 50})
        assert r.status_code == 400, name


# ═══ 8. RESULT CALCULATION ══════════════════════════════════════
def test_final_marks_use_the_terms_weights(client, login):
    school, term, cls, admin, studs = classroom(1, ca_weight=50, exam_weight=50)
    make_marks(school, term, studs[0], "mathematics", ca={"CA1": 80, "CA2": 90}, exam=70)
    row = report(client, login(school, admin["username"]), studs[0])["rows"][0]
    assert row["final"] == pytest.approx(77.5)                    # CA avg 85 * 50% + exam 70 * 50%


def test_tied_students_share_a_position(client, login):
    school, term, cls, admin, studs = classroom(3)
    for s, score in zip(studs, (90, 90, 50)):
        make_marks(school, term, s, "mathematics", ca={"CA1": score, "CA2": score}, exam=score)
    a = login(school, admin["username"])
    reps = [report(client, a, s) for s in studs]
    assert [r["class_position"] for r in reps] == [1, 1, 3]
    assert [r["rows"][0]["position"] for r in reps] == [1, 1, 3]


def test_missing_exam_means_no_final_and_last_place(client, login):
    school, term, cls, admin, studs = classroom(2)
    make_marks(school, term, studs[0], "mathematics", ca={"CA1": 70, "CA2": 70}, exam=None)
    make_marks(school, term, studs[1], "mathematics", ca={"CA1": 60, "CA2": 60}, exam=60)
    a = login(school, admin["username"])
    row = report(client, a, studs[0])["rows"][0]
    assert (row["final"], row["grade"], row["position"]) == (None, "-", "-")
    assert report(client, a, studs[1])["class_position"] == 1


def test_report_for_student_with_no_marks_does_not_crash(client, login):
    school, term, cls, admin, studs = classroom(1)
    rep = report(client, login(school, admin["username"]), studs[0])
    assert rep["rows"] == [] and rep["division"] == "INC"


def test_division_needs_enough_subjects(client, login):
    school, term, cls, admin, studs = classroom(1)
    score_subjects(school, term, studs[0], SEVEN[:3], 90)
    rep = report(client, login(school, admin["username"]), studs[0])
    assert (rep["division"], rep["division_points"]) == ("INC", "INC")


def test_division_with_seven_subjects(client, login):
    school, term, cls, admin, studs = classroom(2)
    score_subjects(school, term, studs[0], SEVEN, 90)       # seven A's  -> 7 points
    score_subjects(school, term, studs[1], SEVEN, 30)       # seven F's  -> 35 points
    a = login(school, admin["username"])
    top, bottom = report(client, a, studs[0]), report(client, a, studs[1])
    assert (top["division"], top["division_points"]) == ("I", 7)
    assert (bottom["division"], bottom["division_points"]) == ("0", 35)


def test_olevel_division_requires_seven_subjects(client, login):
    school, term, cls, admin, studs = classroom(2)
    score_subjects(school, term, studs[0], SEVEN[:6], 95)     # six A's: not enough subjects
    score_subjects(school, term, studs[1], SEVEN, 95)         # seven A's: 7 points
    a = login(school, admin["username"])
    six, seven = report(client, a, studs[0]), report(client, a, studs[1])
    assert (six["division"], six["division_points"]) == ("INC", "INC")
    assert (seven["division"], seven["division_points"]) == ("I", 7)


def test_grade_sheet_alevel_and_noncredit_override(client, login):
    school, term, cls, admin, studs = classroom(1)
    for subj in ("mathematics", "physics", "chemistry"):
        make_marks(school, term, studs[0], subj, exam=85)
    a = login(school, admin["username"])
    base = (f"/api/scoresheet?mode=exam&sheet_type=grade&class_id={cls['id']}"
            f"&grading_system=a_level&division_source=necta")
    r = ok(client.get(base, headers=a), "A-level sheet")["results"][0]
    assert (r["points"], r["division"]) == (3, "I")
    r = ok(client.get(base + "&noncredit=mathematics", headers=a), "with non-credit")["results"][0]
    assert (r["points"], r["division"]) == ("INC", "INC")          # only 2 credited subjects left


# ═══ 9. PDFs ════════════════════════════════════════════════════
def test_report_pdf_with_many_cas_uses_the_landscape_branch(client, login):
    school, term, cls, admin, studs = classroom(1, ca_count=6)
    make_marks(school, term, studs[0], "mathematics", ca={f"CA{i}": 60 + i for i in range(1, 7)}, exam=70)
    grant_access(school, studs[0])
    r = client.get(f"/api/pdf/report/{studs[0]['id']}", headers=login(school, admin["username"]))
    data = r.get_data(); r.close()
    assert r.status_code == 200 and data.startswith(b"%PDF")


# ═══ 10. PARENT ACCESS + ANNOUNCEMENTS ══════════════════════════
def test_parent_access_expiry_gates_the_report(client, login):
    school, term, cls, admin, studs = classroom(2)
    p = login(school, studs[0]["parent_username"], studs[0]["parent_password"])
    url = f"/api/report/{studs[0]['id']}"
    r = client.get(url, headers=p)
    assert r.status_code == 402 and r.get_json()["code"] == "parent_access_required"

    grant_access(school, studs[0], days=-1)                                              # expired yesterday
    assert client.get(url, headers=p).status_code == 402
    st = ok(client.get("/api/access/status", headers=p), "status")
    assert st["active"] is False and st["expires_at"]

    run("UPDATE student_access SET expires_at=%s WHERE student_id=%s", (_now() + timedelta(days=30), studs[0]["id"]))
    assert ok(client.get(url, headers=p), "report after renewal")["access"]["active"] is True
    assert client.get(f"/api/report/{studs[1]['id']}", headers=p).status_code == 403    # never a sibling's report


def test_announcement_targeting_and_read_receipts(client, login):
    school = make_school(); admin = make_admin(school)
    c1, c2 = make_class(school, "Form 1"), make_class(school, "Form 2")
    s1, s2 = make_student(school, c1, name="Kid One"), make_student(school, c2, name="Kid Two")
    a = login(school, admin["username"])
    for title, target in (("Trip", "Form 1"), ("All", "all")):
        ok(client.post("/api/announcements", headers=a, json={"title": title, "body": "text", "target_classes": target,
                                                              "posted_by": "admin"}), f"post {title}")
    p1 = login(school, s1["parent_username"], s1["parent_password"])
    p2 = login(school, s2["parent_username"], s2["parent_password"])
    titles = lambda h, s: {x["title"] for x in ok(client.get(f"/api/announcements?student_id={s['id']}", headers=h), "list")}
    assert titles(p1, s1) == {"Trip", "All"} and titles(p2, s2) == {"All"}

    listing = ok(client.get(f"/api/announcements?student_id={s1['id']}", headers=p1), "list")
    trip_id = next(x["id"] for x in listing if x["title"] == "Trip")
    ok(client.post(f"/api/announcements/{trip_id}/read", json={"student_id": s1["id"]}, headers=p1), "mark read")
    flags = {x["title"]: x["is_read"] for x in ok(client.get(f"/api/announcements?student_id={s1['id']}", headers=p1), "list")}
    assert flags == {"Trip": 1, "All": 0}
    assert client.post(f"/api/announcements/{trip_id}/read", json={"student_id": s2["id"]}, headers=p1).status_code == 403
    assert client.get(f"/api/announcements?student_id={s2['id']}", headers=p1).status_code == 403


# ═══ 11. PAYMENTS ═══════════════════════════════════════════════
def test_webhook_signature_is_enforced_when_a_secret_is_set(client, monkeypatch):
    monkeypatch.setattr("services.access.SNIPPE_WEBHOOK_SECRET", "whsec")
    raw = json.dumps({"type": "payment.completed", "data": {"reference": "NOPE"}}).encode()
    ts = "1700000000"
    sig = hmac.new(b"whsec", ts.encode() + b"." + raw, hashlib.sha256).hexdigest()
    good = {"X-Webhook-Timestamp": ts, "X-Webhook-Signature": sig}
    post = lambda h: client.post("/api/access/webhook", data=raw, content_type="application/json", headers=h)
    assert post({}).status_code == 400
    assert post({**good, "X-Webhook-Signature": "0" * 64}).status_code == 400
    assert post(good).status_code == 200


def test_school_subscription_request_flow(client, login):
    school = make_school(); admin = make_admin(school); teacher = make_teacher(school)
    a, t, sa = login(school, admin["username"]), login(school, teacher["username"]), sa_headers(client)
    req = {"plan": "standard", "transaction_id": "ABC123", "phone_used": "0712345678",
           "claimed_amount": 300000, "payment_date": "2026-10-01", "note": ""}
    post = lambda h, **over: client.post("/api/subscription/request", json={**req, **over}, headers=h)

    assert post(t).status_code == 403                                                   # admins only
    ok(post(a), "submit")
    assert post(a, transaction_id="OTHER1").status_code == 409                          # one pending at a time
    ok(client.post("/api/subscription/request/cancel", json={}, headers=a), "cancel")
    rid = ok(post(a, transaction_id="abc123"), "resubmit (id freed by cancel, case-insensitive)")["id"]

    ok(client.post(f"/api/superadmin/payment_requests/{rid}/approve", json={}, headers=sa), "approve")
    status, plan, expires = query("SELECT subscription_status, subscription_plan, subscription_expires_at "
                                  "FROM schools WHERE id=%s", (school["id"],))[0]
    assert (status, plan) == ("active", "standard") and 181 <= (expires - _now()).days <= 182
    assert post(a, transaction_id="ABC123").status_code == 409                          # an approved txn id can't be reused