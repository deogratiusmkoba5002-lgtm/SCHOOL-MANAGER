from services.stars import record_qualifying_parent, record_referral_relationship
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

def _n(school_id, typ):
    return query("SELECT COUNT(*) FROM star_transactions WHERE school_id=%s AND type=%s",
                 (school_id, typ))[0][0]


def test_only_first_ten_parents_earn_stars_referrer_gets_one():
    referrer = make_school(); referred = make_school()
    assert record_referral_relationship(referrer["id"], referred["id"])
    run("INSERT INTO star_cycles(school_id,cycle_number,status) VALUES(%s,1,'IN_PROGRESS')", (referred["id"],))
    for i in range(1, 31):
        record_qualifying_parent(referred["id"], i, f"REF-{i}")
    assert _n(referred["id"], "CYCLE_REWARD") == 1
    assert _n(referrer["id"], "REFERRAL_REWARD") == 1
    assert _n(referred["id"], "REFERRAL_REWARD") == 0
    assert _n(referrer["id"], "CYCLE_REWARD") == 0
    assert query("SELECT COUNT(*) FROM star_transactions")[0][0] == 2   # nothing for parents 11-30