"""Phase 2: proves the test environment itself is safe and working."""
import pytest

import config
from tests.factories import (make_school, make_term, make_class, make_stream, make_admin,
                             make_teacher, assign_teacher, make_student, make_marks, query)


def _count(table):
    return query(f"SELECT COUNT(*) FROM {table}")[0][0]


def test_runs_against_test_database():
    db = query("SELECT current_database()")[0][0]
    assert db.endswith("_test")
    assert config.DATABASE_URL.endswith(db)


def test_app_starts_in_test_mode(app, client):
    assert app.config["TESTING"] is True
    r = client.get("/api/school/info?reg_code=does-not-exist")
    assert r.status_code == 200 and r.get_json() == {}


def test_school_can_be_created():
    from core.school import get_school_id_by_reg_code, is_registration_complete
    school = make_school()
    assert get_school_id_by_reg_code(school["reg_code"]) == school["id"]
    assert is_registration_complete(school["id"])
    assert _count("school_subjects") == 7 and _count("grade_config") == 5


def test_db_starts_empty_each_test():
    # The previous test created a school; cleanup must have removed it.
    assert _count("schools") == 0 and _count("users") == 0


def test_cleanup_helper_empties_tables(reset_db):
    school = make_school(); make_admin(school)
    assert _count("schools") == 1 and _count("users") == 1
    reset_db()
    assert _count("schools") == 0 and _count("users") == 0
    assert _count("necta_grades") > 0          # seeded reference data must survive


def test_factory_graph_and_scoring():
    from services.scores import get_term_scores_bulk, _final_from_entry
    school = make_school(); term = make_term(school)
    cls = make_class(school); stream = make_stream(school, cls)
    teacher = make_teacher(school, class_teacher_of=cls, stream=stream)
    assign_teacher(school, teacher, "mathematics", cls, stream)
    student = make_student(school, cls, stream)
    make_marks(school, term, student, "mathematics", ca={"CA1": 60, "CA2": 80}, exam=90)

    bulk = get_term_scores_bulk(school["id"], term["id"], [student["id"]])
    entry = bulk[student["id"]]["mathematics"]
    assert entry["ca"] == {"CA1": 60, "CA2": 80} and entry["exam"] == 90
    # CA avg 70 -> 70% of 30 = 21 ; exam 90 -> 90% of 70 = 63
    assert _final_from_entry(entry, 30, 70) == pytest.approx(84.0)


def test_login_and_school_scoping(client, login):
    school = make_school(); cls = make_class(school)
    other = make_school(); make_class(other, "Other School Class")
    admin = make_admin(school); student = make_student(school, cls)

    assert client.get("/api/classes").status_code == 401        # no token

    h = login(school, admin["username"])
    names = [c["class_name"] for c in client.get("/api/classes", headers=h).get_json()]
    assert names == ["Form 1"]                                   # only own school's class

    ph = login(school, student["parent_username"], student["parent_password"])
    r = client.get("/api/access/status", headers=ph)
    assert r.status_code == 200 and r.get_json()["student_id"] == student["id"]


def test_network_is_blocked():
    import requests
    assert config.SNIPPE_API_KEY == ""
    with pytest.raises(RuntimeError):
        requests.get("http://example.com")