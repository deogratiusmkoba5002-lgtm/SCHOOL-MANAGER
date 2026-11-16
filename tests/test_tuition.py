"""DrDemic Tuition: course subjects, applications, instalments, catalog isolation."""
import pytest

from tests.factories import query


class FakeSnippe:
    def __init__(self):
        self.n, self.remote = 0, {}

    def __call__(self, method, path, **kw):
        if method == "POST":
            self.n += 1
            ref = f"TREF-{self.n}"
            self.remote[ref] = {"status": "pending", "value": kw["json"]["details"]["amount"]}
            return {"reference": ref}
        r = self.remote[path.rsplit("/", 1)[-1]]
        return {"status": r["status"], "amount": {"value": r["value"], "currency": "TZS"},
                "completed_at": "2026-10-02T10:00:00", "channel": {"provider": "test"}}

    def settle(self, ref):
        self.remote[ref]["status"] = "completed"


@pytest.fixture
def snippe(monkeypatch):
    fake = FakeSnippe()
    monkeypatch.setattr("services.access.SNIPPE_API_KEY", "test-key")
    monkeypatch.setattr("services.access._snippe_call", fake)
    return fake


def signup(client, username, role="student"):
    r = client.post("/api/tuition/auth/signup", json={
        "username": username, "password": "secret12", "confirm_password": "secret12",
        "full_name": f"{username} Full", "role": role, "agree_terms": True, "phone": "0712345678"})
    assert r.status_code == 200, r.get_json()
    return {"Authorization": "Bearer " + r.get_json()["token"]}


def make_program(client, teacher, **over):
    body = {"name": "Pre-Form Five", "fee": 10000, "advance": 2000, "installments": 3,
            "subjects": ["Physics", "Chemistry", "Mathematics"], **over}
    r = client.post("/api/tuition/programs", json=body, headers=teacher)
    assert r.status_code == 200, r.get_json()
    pid = r.get_json()["id"]
    prog = client.get(f"/api/tuition/programs/{pid}", headers=teacher).get_json()["program"]
    return pid, prog["join_token"]


def apply(client, student, token, subjects):
    return client.post(f"/api/tuition/p/{token}/apply", headers=student,
                       json={"full_name": "Asha Juma", "phone": "0711111111", "subjects": subjects})


# ── course subjects ─────────────────────────────────────────────
def test_subjects_are_cleaned_and_deduplicated(client):
    t = signup(client, "teach1", "teacher")
    pid, token = make_program(client, t, subjects=["Physics", " physics ", "Chem, Bio", "", "Maths"])
    assert client.get(f"/api/tuition/programs/{pid}", headers=t).get_json()["program"]["subjects"] == \
        ["Physics", "Chem Bio", "Maths"]
    assert client.get(f"/api/tuition/p/{token}").get_json()["subjects"] == ["Physics", "Chem Bio", "Maths"]


def test_saving_the_timetable_keeps_subjects_and_subjects_can_be_replaced(client):
    t = signup(client, "teach1", "teacher")
    pid, _ = make_program(client, t)
    get = lambda: client.get(f"/api/tuition/programs/{pid}", headers=t).get_json()["program"]
    assert client.post(f"/api/tuition/programs/{pid}", json={"timetable": "Mon 4pm"}, headers=t).status_code == 200
    assert get()["subjects"] == ["Physics", "Chemistry", "Mathematics"] and get()["timetable"] == "Mon 4pm"
    client.post(f"/api/tuition/programs/{pid}", json={"subjects": ["Biology"]}, headers=t)
    assert get()["subjects"] == ["Biology"]


def test_application_only_accepts_the_teachers_subjects(client):
    t, s = signup(client, "teach1", "teacher"), signup(client, "stud1")
    pid, token = make_program(client, t)
    assert apply(client, s, token, ["Biology"]).status_code == 400          # not offered
    assert apply(client, s, token, []).status_code == 400                    # at least one
    assert apply(client, s, token, "Physics").status_code == 200             # string form also works
    assert apply(client, s, token, ["physics", "MATHEMATICS", "physics"]).status_code == 200
    assert query("SELECT subjects FROM tuition_applications") == [("Physics, Mathematics",)]   # canonical names


def test_course_without_a_subject_list_still_takes_free_text(client):
    t, s = signup(client, "teach1", "teacher"), signup(client, "stud1")
    _, token = make_program(client, t, subjects=[])
    assert apply(client, s, token, "Anything I like").status_code == 200
    assert query("SELECT subjects FROM tuition_applications") == [("Anything I like",)]


def test_only_the_owner_sees_a_course(client):
    t1, t2, s = signup(client, "teach1", "teacher"), signup(client, "teach2", "teacher"), signup(client, "stud1")
    pid, _ = make_program(client, t1)
    assert client.get(f"/api/tuition/programs/{pid}", headers=t2).status_code == 404
    assert client.get(f"/api/tuition/programs/{pid}", headers=s).status_code == 404       # not applied
    assert client.post(f"/api/tuition/programs/{pid}", json={"name": "Hacked"}, headers=t2).status_code == 404


# ── instalments ─────────────────────────────────────────────────
def test_instalment_rules_registration_and_no_double_pending(client, snippe):
    t, s = signup(client, "teach1", "teacher"), signup(client, "stud1")
    pid, token = make_program(client, t)                                     # fee 10000, advance 2000, 3 instalments
    topic = client.post("/api/tuition/courses", json={"name": "Mechanics", "program_id": pid}, headers=t).get_json()["id"]
    assert apply(client, s, token, ["Physics"]).status_code == 200
    pay = lambda amount: client.post(f"/api/tuition/programs/{pid}/pay", json={"amount": amount, "phone": "0712345678"}, headers=s)
    check = lambda p: client.post(f"/api/tuition/program_pay/check/{p['payment_id']}", json={}, headers=s).get_json()["status"]

    assert pay(1000).status_code == 400                                      # below the advance
    first = pay(2000).get_json(); assert first["ok"]
    dup = pay(2000)
    assert dup.status_code == 400 and "waiting" in dup.get_json()["error"]   # no second pending payment
    assert check(first) == "pending"
    snippe.settle(first["reference"])
    assert check(first) == "completed"
    assert query("SELECT status FROM tuition_applications") == [("registered",)]
    assert query("SELECT course_id FROM tuition_enrollments") == [(topic,)]  # enrolled in every topic

    second = pay(2000).get_json(); snippe.settle(second["reference"]); assert check(second) == "completed"
    assert pay(2000).status_code == 400                                      # last instalment must clear the balance (6000)
    last = pay(6000).get_json(); snippe.settle(last["reference"]); assert check(last) == "completed"
    assert pay(500).status_code == 400                                       # fully paid


# ── isolation ───────────────────────────────────────────────────
def test_program_topics_cannot_be_joined_through_the_catalog(client):
    t, s = signup(client, "teach1", "teacher"), signup(client, "stud1")
    pid, _ = make_program(client, t)
    topic = client.post("/api/tuition/courses", json={"name": "Mechanics", "program_id": pid}, headers=t).get_json()["id"]
    assert client.post(f"/api/tuition/catalog/course/{topic}/join", json={}, headers=s).status_code == 404
    assert client.get(f"/api/tuition/catalog/course/{topic}", headers=s).status_code == 404
    assert query("SELECT COUNT(*) FROM tuition_enrollments")[0][0] == 0