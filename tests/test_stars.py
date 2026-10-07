from services.stars import record_qualifying_parent
from tests.factories import run, query, make_school


def test_one_payment_qualifies_a_student_only_once():
    school = make_school()
    run("INSERT INTO star_cycles(school_id,cycle_number,status) VALUES(%s,1,'IN_PROGRESS')", (school["id"],))
    assert record_qualifying_parent(school["id"], 1, "REF-1")["ok"] is True
    run("UPDATE star_cycles SET status='COMPLETED' WHERE school_id=%s", (school["id"],))
    run("INSERT INTO star_cycles(school_id,cycle_number,status) VALUES(%s,2,'IN_PROGRESS')", (school["id"],))
    assert record_qualifying_parent(school["id"], 1, "REF-1")["ok"] is False   # same payment, new cycle
    assert record_qualifying_parent(school["id"], 1, "REF-2")["ok"] is True    # renewal = new payment
    assert query("SELECT COUNT(*) FROM star_qualifying_parents")[0][0] == 2