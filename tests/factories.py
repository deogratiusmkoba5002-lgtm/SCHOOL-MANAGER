"""
Plain functions that insert realistic DrDemic rows directly via SQL.
They return dicts so tests can chain them:
    school -> term -> class -> stream -> admin/teacher -> student (+parent login) -> marks

Performance note:
Each high-level factory uses one database connection/transaction instead
of opening and closing a connection for every individual SQL statement.
"""

import itertools

from core.db import get_db
from core.security import hash_password_fast
from services.students import gen_parent_creds

DEFAULT_PASSWORD = "pass1234"
_n = itertools.count(1)

DEFAULT_SUBJECTS = [
    ("mathematics", "MATH"),
    ("english", "ENG"),
    ("kiswahili", "KIS"),
    ("biology", "BIO"),
    ("chemistry", "CHEM"),
    ("physics", "PHY"),
    ("geography", "GEO"),
]

DEFAULT_GRADES = [
    (80, 100, "A", 1),
    (70, 79, "B", 2),
    (60, 69, "C", 3),
    (50, 59, "D", 4),
    (0, 49, "F", 5),
]


def run(sql, params=()):
    """Execute and commit one standalone SQL statement."""
    con = get_db()
    cur = con.cursor()
    try:
        cur.execute(sql, params)
        out = cur.fetchone()[0] if cur.description else None
        con.commit()
        return out
    except Exception:
        con.rollback()
        raise
    finally:
        cur.close()
        con.close()


def query(sql, params=()):
    """Execute a SELECT and return all rows."""
    con = get_db()
    cur = con.cursor()
    try:
        cur.execute(sql, params)
        return cur.fetchall()
    finally:
        cur.close()
        con.close()





def make_term(
    school,
    label="Term 1",
    ca_count=2,
    ca_weight=30,
    exam_weight=70,
    status="open",
):
    tid = run(
        """INSERT INTO terms(
               school_id,label,ca_count,ca_weight,exam_weight,status
           )
           VALUES(%s,%s,%s,%s,%s,%s)
           RETURNING id""",
        (
            school["id"],
            label,
            ca_count,
            ca_weight,
            exam_weight,
            status,
        ),
    )

    return {
        "id": tid,
        "label": label,
        "ca_count": ca_count,
        "ca_weight": ca_weight,
        "exam_weight": exam_weight,
    }


def make_class(school, name="Form 1"):
    cid = run(
        "INSERT INTO classes(school_id,class_name) VALUES(%s,%s) RETURNING id",
        (school["id"], name),
    )
    return {"id": cid, "name": name}


def make_stream(school, class_, name="A"):
    stid = run(
        """INSERT INTO streams(
               school_id,class_id,stream_name
           )
           VALUES(%s,%s,%s)
           RETURNING id""",
        (school["id"], class_["id"], name),
    )
    return {
        "id": stid,
        "name": name,
        "class_id": class_["id"],
    }


def _make_user(school, username, role, password=DEFAULT_PASSWORD, **extra):
    cols = ["username", "password", "role", "school_id"] + list(extra.keys())
    vals = [
        username,
        hash_password_fast(password),
        role,
        school["id"],
    ] + list(extra.values())

    run(
        f"INSERT INTO users({','.join(cols)}) "
        f"VALUES({','.join(['%s'] * len(vals))})",
        vals,
    )

    return {
        "username": username,
        "password": password,
        "role": role,
        "school_id": school["id"],
    }


def make_admin(school, username="admin", password=DEFAULT_PASSWORD):
    return _make_user(school, username, "admin", password)


def make_teacher(
    school,
    username=None,
    password=DEFAULT_PASSWORD,
    class_teacher_of=None,
    stream=None,
):
    username = username or f"teacher{next(_n)}"

    extra = {}

    if class_teacher_of:
        extra = {
            "is_class_teacher": 1,
            "class_id": class_teacher_of["id"],
            "stream_id": stream["id"] if stream else None,
        }

    return _make_user(
        school,
        username,
        "teacher",
        password,
        **extra,
    )


def assign_teacher(school, teacher, subject, class_, stream=None):
    run(
        """INSERT INTO subject_assignments(
               school_id,username,subject,class_id,stream_id
           )
           VALUES(%s,%s,%s,%s,%s)""",
        (
            school["id"],
            teacher["username"],
            subject,
            class_["id"],
            stream["id"] if stream else None,
        ),
    )


def make_student(school, class_, stream=None, name=None, phone="0712345678"):
    """Creates the student AND its parent login using the app's own gen_parent_creds()."""
    name = name or f"Student {next(_n)}"

    con = get_db()
    cur = con.cursor()

    try:
        cur.execute(
            """INSERT INTO students(
                   school_id,name,class_id,stream_id,
                   phone_number,school_student_no
               )
               VALUES(
                   %s,%s,%s,%s,%s,
                   (
                       SELECT COALESCE(MAX(school_student_no),0)+1
                       FROM students
                       WHERE school_id=%s
                   )
               )
               RETURNING id""",
            (
                school["id"],
                name,
                class_["id"],
                stream["id"] if stream else None,
                phone,
                school["id"],
            ),
        )

        stid = cur.fetchone()[0]

        username, pw = gen_parent_creds(
            school["id"],
            name,
            phone,
            stid,
        )

        cur.execute(
            """INSERT INTO users(
                   username,password,role,school_id,
                   must_change_password,student_id
               )
               VALUES(%s,%s,'parent',%s,1,%s)""",
            (
                username,
                hash_password_fast(pw),
                school["id"],
                stid,
            ),
        )

        con.commit()

        return {
            "id": stid,
            "name": name,
            "class_id": class_["id"],
            "school_id": school["id"],
            "parent_username": username,
            "parent_password": pw,
        }

    except Exception:
        con.rollback()
        raise

    finally:
        cur.close()
        con.close()

def make_school(name=None, reg_code=None, with_defaults=True, grading_system="o_level"):
    n = next(_n)
    name = name or f"Test School {n}"
    reg_code = reg_code or f"T{1000 + n}"
    con = get_db(); cur = con.cursor()
    try:
        cur.execute("""INSERT INTO schools(school_name, reg_code, necta_code, verification_status,
                                           subscription_exempt, grading_system, division_source)
                       VALUES(%s,%s,%s,'approved',1,%s,'school') RETURNING id""",
                    (name, reg_code, reg_code, grading_system))
        sid = cur.fetchone()[0]
        cfg = {"school_name": name, "registration_complete": "1", "onboarding_complete": "1",
               "phone": "", "email": "", "motto": "", "logo_path": "", "admin_phone": ""}
        cur.executemany("INSERT INTO school_config(school_id,key,value) VALUES(%s,%s,%s)",
                        [(sid, k, v) for k, v in cfg.items()])
        if with_defaults:
            cur.executemany("INSERT INTO school_subjects(school_id,name,abbreviation,sort_order) VALUES(%s,%s,%s,%s)",
                            [(sid, subj, ab, i) for i, (subj, ab) in enumerate(DEFAULT_SUBJECTS)])
            cur.executemany("""INSERT INTO grade_config(school_id,min_score,max_score,grade,points,sort_order)
                               VALUES(%s,%s,%s,%s,%s,%s)""",
                            [(sid, lo, hi, g, p, i) for i, (lo, hi, g, p) in enumerate(DEFAULT_GRADES)])
        con.commit()
    except Exception:
        con.rollback(); raise
    finally:
        cur.close(); con.close()
    return {"id": sid, "name": name, "reg_code": reg_code}


def make_marks(school, term, student, subject, ca=None, exam=None):
    """ca: {"CA1": 60, "CA2": 80}; exam: number. One connection for all rows."""
    con = get_db(); cur = con.cursor()
    try:
        for ca_name, score in (ca or {}).items():
            cur.execute("""INSERT INTO ca_scores(school_id,student_id,subject,ca_name,score,entered_by,term_id)
                           VALUES(%s,%s,%s,%s,%s,'factory',%s)""",
                        (school["id"], student["id"], subject, ca_name, score, term["id"]))
        if exam is not None:
            cur.execute("""INSERT INTO exam_scores(school_id,student_id,subject,score,entered_by,term_id)
                           VALUES(%s,%s,%s,%s,'factory',%s)""",
                        (school["id"], student["id"], subject, exam, term["id"]))
        con.commit()
    except Exception:
        con.rollback(); raise
    finally:
        cur.close(); con.close()