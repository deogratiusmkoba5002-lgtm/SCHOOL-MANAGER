"""Regression tests for bugs found in the review."""
import io
import json

from tests.factories import (run, query, make_school, make_term, make_class, make_admin, make_teacher,
                             make_student, make_marks)


def _access(school, student):
    run("INSERT INTO student_access(school_id,student_id,plan,expires_at) VALUES(%s,%s,'6m',NOW()+INTERVAL '30 days')",
        (school["id"], student["id"]))


def test_parent_cannot_see_report_until_exam_is_published(client, login):
    school = make_school(); term = make_term(school); cls = make_class(school); admin = make_admin(school)
    stu = make_student(school, cls)
    make_marks(school, term, stu, "mathematics", ca={"CA1": 60, "CA2": 60}, exam=70)
    _access(school, stu)
    p = login(school, stu["parent_username"], stu["parent_password"])
    a = login(school, admin["username"])
    assert client.get(f"/api/report/{stu['id']}", headers=p).status_code == 403
    assert client.get(f"/api/pdf/report/{stu['id']}", headers=p).status_code == 403
    assert query("SELECT COUNT(*) FROM star_qualifying_parents")[0][0] == 0
    client.post("/api/results/publish_assessments", headers=a,
                json={"term_id": term["id"], "assess_keys": ["exam"], "publish": True})
    assert client.get(f"/api/report/{stu['id']}", headers=p).status_code == 200
    r = client.get(f"/api/pdf/report/{stu['id']}", headers=p)
    data = r.get_data(); r.close()
    assert r.status_code == 200 and data.startswith(b"%PDF")


def test_class_can_be_renamed(client, login):
    school = make_school(); admin = make_admin(school); teacher = make_teacher(school)
    c1, _c2 = make_class(school, "Form 1"), make_class(school, "Form 2")
    a = login(school, admin["username"])
    url = f"/api/classes/{c1['id']}"
    assert client.patch(url, json={"class_name": "Form 1A"}, headers=a).status_code == 200
    assert query("SELECT class_name FROM classes WHERE id=%s", (c1["id"],)) == [("Form 1A",)]
    assert client.patch(url, json={"class_name": "Form 2"}, headers=a).status_code == 409
    assert client.patch(url, json={"class_name": "  "}, headers=a).status_code == 400
    assert client.patch(url, json={"class_name": "X"}, headers=login(school, teacher["username"])).status_code == 403
    other = make_school(); oc = make_class(other)
    assert client.patch(f"/api/classes/{oc['id']}", json={"class_name": "X"}, headers=a).status_code == 404


def test_test_marks_are_locked_when_the_term_is_closed(client, login):
    school = make_school(); term = make_term(school); cls = make_class(school); admin = make_admin(school)
    stu = make_student(school, cls)
    tid = run("INSERT INTO term_tests(school_id,term_id,label,all_classes) VALUES(%s,%s,'Quiz',1) RETURNING id",
              (school["id"], term["id"]))
    a = login(school, admin["username"])
    body = {"subject": "mathematics", "class_id": cls["id"], "stream_id": None,
            "student_id": stu["id"], "test_id": tid, "score": 55}
    assert client.post("/api/marks/test", json=body, headers=a).status_code == 200
    run("UPDATE terms SET status='closed' WHERE id=%s", (term["id"],))
    assert client.post("/api/marks/test", json={**body, "score": 99}, headers=a).status_code == 400
    assert query("SELECT score FROM test_scores") == [(55,)]


def test_reimport_of_students_without_phone_is_a_noop(client, login):
    school = make_school(); make_class(school, "Form 1"); admin = make_admin(school)
    a = login(school, admin["username"])
    colmap = json.dumps({"name": ["name"], "class": "class_name", "stream": "stream_name", "phone": "parent_phone"})

    def run_import():
        data = {"file": (io.BytesIO(b"name,class_name,stream_name,parent_phone\nNo Phone,Form 1,,\n"), "s.csv"),
                "column_map": colmap, "mapping": "{}"}
        return client.post("/api/students/import", data=data, headers=a).get_json()
    assert run_import()["inserted"] == 1
    again = run_import()
    assert (again["inserted"], again["duplicates"]) == (0, 1)
    assert query("SELECT COUNT(*) FROM students")[0][0] == 1


def test_report_pdf_works_for_names_with_a_slash(client, login):
    school = make_school(); term = make_term(school); cls = make_class(school); admin = make_admin(school)
    stu = make_student(school, cls, name="A/B Kid")
    make_marks(school, term, stu, "mathematics", ca={"CA1": 60, "CA2": 60}, exam=70)
    _access(school, stu)
    r = client.get(f"/api/pdf/report/{stu['id']}", headers=login(school, admin["username"]))
    data = r.get_data(); r.close()
    assert r.status_code == 200 and data.startswith(b"%PDF")