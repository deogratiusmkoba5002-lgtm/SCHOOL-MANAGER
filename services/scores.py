"""
Term, student-scope and score logic: subject/term/student lookups, bulk score
fetching, final-mark and average computation, and ranking. No Flask
request/response handling.
"""
from core.db import get_db, to_dict, to_dicts
from config import _FALLBACK_SUBJECTS, _FALLBACK_ABBR


# ── SUBJECTS ──────────────────────────────────────────────────
def get_subjects(school_id):
    try:
        con = get_db(); cur = con.cursor()
        cur.execute("SELECT name FROM school_subjects WHERE school_id=%s ORDER BY sort_order,name", (school_id,))
        rows = cur.fetchall(); cur.close(); con.close()
        if rows: return [r[0] for r in rows]
    except: pass
    return list(_FALLBACK_SUBJECTS)

def get_subject_map(school_id):
    try:
        con = get_db(); cur = con.cursor()
        cur.execute("SELECT name,abbreviation FROM school_subjects WHERE school_id=%s ORDER BY sort_order,name", (school_id,))
        rows = cur.fetchall(); cur.close(); con.close()
        if rows: return {r[0]:r[1] for r in rows}
    except: pass
    return dict(_FALLBACK_ABBR)


# ── TERMS ─────────────────────────────────────────────────────
def get_active_term(school_id):
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM terms WHERE school_id=%s AND status='open' ORDER BY id DESC LIMIT 1", (school_id,))
    row = cur.fetchone(); r = to_dict(row, cur) if row else None
    cur.close(); con.close(); return r

def get_term_by_id(school_id, tid):
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM terms WHERE id=%s AND school_id=%s", (tid, school_id))
    row = cur.fetchone(); r = to_dict(row, cur) if row else None
    cur.close(); con.close(); return r

def _get_all_terms_ordered(school_id):
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM terms WHERE school_id=%s ORDER BY id ASC", (school_id,))
    rows = to_dicts(cur.fetchall(), cur); cur.close(); con.close()
    return rows


# ── STUDENTS ──────────────────────────────────────────────────
def get_students_in_scope(school_id, class_id, stream_id=None):
    con = get_db(); cur = con.cursor()
    if stream_id:
        cur.execute("""SELECT s.id,s.name,s.class_id,s.stream_id,c.class_name,st.stream_name
                       FROM students s JOIN classes c ON s.class_id=c.id
                       LEFT JOIN streams st ON s.stream_id=st.id
                       WHERE s.school_id=%s AND s.class_id=%s AND s.stream_id=%s ORDER BY s.name""",
                    (school_id, class_id, stream_id))
    else:
        cur.execute("""SELECT s.id,s.name,s.class_id,s.stream_id,c.class_name,st.stream_name
                       FROM students s JOIN classes c ON s.class_id=c.id
                       LEFT JOIN streams st ON s.stream_id=st.id
                       WHERE s.school_id=%s AND s.class_id=%s ORDER BY s.name""",
                    (school_id, class_id))
    rows = to_dicts(cur.fetchall(), cur); cur.close(); con.close()
    return rows

def get_all_students_in_school(school_id):
    con = get_db(); cur = con.cursor()
    cur.execute("""SELECT s.id,s.name,s.class_id,s.stream_id,c.class_name,st.stream_name
                   FROM students s JOIN classes c ON s.class_id=c.id
                   LEFT JOIN streams st ON s.stream_id=st.id
                   WHERE s.school_id=%s ORDER BY s.name""", (school_id,))
    rows = to_dicts(cur.fetchall(), cur); cur.close(); con.close()
    return rows


# ── TESTS ─────────────────────────────────────────────────────
def get_term_tests(school_id, term_id, class_id=None):
    """Returns tests for a term. If class_id is given, only tests that apply
    to that class (all_classes=1, or explicitly listed in test_classes) are
    returned — this is what scopes a test to teachers/students in the
    participating classes only. If class_id is None, every test in the term
    is returned (used for admin management and term-wide publishing)."""
    con=get_db(); cur=con.cursor()
    cur.execute("SELECT id,label,all_classes FROM term_tests WHERE school_id=%s AND term_id=%s ORDER BY id",(school_id,term_id))
    rows=cur.fetchall()
    result=[]
    for tid,label,all_classes in rows:
        if class_id is not None and not all_classes:
            cur.execute("SELECT 1 FROM test_classes WHERE test_id=%s AND class_id=%s",(tid,class_id))
            if not cur.fetchone(): continue
        result.append({"id":tid,"label":label,"all_classes":bool(all_classes)})
    cur.close(); con.close()
    return result

def get_test_class_ids(test_id):
    con=get_db(); cur=con.cursor()
    cur.execute("SELECT class_id FROM test_classes WHERE test_id=%s",(test_id,))
    rows=[r[0] for r in cur.fetchall()]
    cur.close(); con.close()
    return rows


# ── RANKING ───────────────────────────────────────────────────
def _assign_positions(rows, key):
    rows.sort(key=lambda x: (x[key] is None, -(x[key] or 0)))
    for i, r in enumerate(rows):
        if i == 0: r["position"] = 1
        elif r[key] == rows[i-1][key]: r["position"] = rows[i-1]["position"]
        else: r["position"] = i+1


# ── BULK SCORE FETCHING & COMPUTATION ─────────────────────────
def get_term_scores_bulk(school_id, term_id, student_ids):
    if not student_ids: return {}
    con = get_db(); cur = con.cursor()
    cur.execute("""SELECT student_id, subject, ca_name, score FROM ca_scores
                   WHERE school_id=%s AND term_id=%s AND student_id=ANY(%s)""",
                (school_id, term_id, student_ids))
    ca_rows = cur.fetchall()
    cur.execute("""SELECT student_id, subject, score FROM exam_scores
                   WHERE school_id=%s AND term_id=%s AND student_id=ANY(%s)""",
                (school_id, term_id, student_ids))
    exam_rows = cur.fetchall()
    cur.execute("""SELECT student_id, subject, test_id, score FROM test_scores
                   WHERE school_id=%s AND term_id=%s AND student_id=ANY(%s)""",
                (school_id, term_id, student_ids))
    test_rows = cur.fetchall()
    cur.close(); con.close()
    data = {}
    for student_id, subject, ca_name, score in ca_rows:
        d = data.setdefault(student_id, {}).setdefault(subject, {"ca": {}, "exam": None, "tests": {}})
        d["ca"][ca_name] = score
    for student_id, subject, score in exam_rows:
        d = data.setdefault(student_id, {}).setdefault(subject, {"ca": {}, "exam": None, "tests": {}})
        d["exam"] = score
    for student_id, subject, test_id, score in test_rows:
        d = data.setdefault(student_id, {}).setdefault(subject, {"ca": {}, "exam": None, "tests": {}})
        d["tests"][test_id] = score
    return data

def _score_for_assess(entry, assess):
    if not entry: return None
    if assess == "exam": return entry.get("exam")
    if isinstance(assess,str) and assess.startswith("test:"):
        try: tid = int(assess.split(":",1)[1])
        except ValueError: return None
        return (entry.get("tests") or {}).get(tid)
    return (entry.get("ca") or {}).get(assess)

def _active_subjects_in_scores(subjects, scores_bulk):
    """Returns the subset of `subjects` for which at least one student in
    scores_bulk has any recorded score (CA, exam, or test) — used to drop
    subject columns/rows a class doesn't actually take."""
    active = set()
    for student_data in scores_bulk.values():
        active.update(student_data.keys())
    return [s for s in subjects if s in active]

def _final_from_entry(entry, ca_weight, exam_weight):
    if not entry: return None
    ca_vals = list(entry["ca"].values())
    if not ca_vals or entry["exam"] is None: return None
    ca_avg = sum(ca_vals) / len(ca_vals)
    return (ca_avg/100)*ca_weight + (entry["exam"]/100)*exam_weight

def compute_student_finals(scores_bulk, student_id, subjects, ca_weight, exam_weight):
    student_data = scores_bulk.get(student_id, {})
    return {subj: _final_from_entry(student_data.get(subj), ca_weight, exam_weight) for subj in subjects}

def compute_average_from_finals(finals):
    vals = [v for v in finals.values() if v is not None]
    return sum(vals)/len(vals) if vals else 0

def get_subject_rank_map(class_rows, subject):
    """class_rows: [{"id":..., "finals":{subject:final_or_None}}, ...] -> {student_id: position}"""
    scored = [{"id": r["id"], "score": r["finals"].get(subject)} for r in class_rows if r["finals"].get(subject) is not None]
    _assign_positions(scored, "score")
    return {r["id"]: r["position"] for r in scored}

def get_subject_assess_rank_map(scores_bulk, student_ids, subject, assess):
    """Rank by a single assessment's raw score (a CA name, 'exam', or 'test:ID')
    rather than the weighted final."""
    scored = []
    for stid in student_ids:
        entry = scores_bulk.get(stid, {}).get(subject)
        if not entry: continue
        val = _score_for_assess(entry, assess)
        if val is not None: scored.append({"id": stid, "score": val})
    _assign_positions(scored, "score")
    return {r["id"]: r["position"] for r in scored}

def get_class_report_data(school_id, term_id, class_id, stream_id, subjects, ca_weight, exam_weight):
    """
    One-shot computation of everything needed to render a report card /
    PDF / parent result for an entire class (and, if given, a stream
    within it) for one term — exactly 3 score queries total, regardless
    of class size or subject count.
    Returns (class_rows, class_rank_map, stream_rank_map, scores_bulk).
    """
    class_students = get_students_in_scope(school_id, class_id)
    ids = [s["id"] for s in class_students]
    scores_bulk = get_term_scores_bulk(school_id, term_id, ids)
    class_rows = []
    for s in class_students:
        finals = compute_student_finals(scores_bulk, s["id"], subjects, ca_weight, exam_weight)
        avg = compute_average_from_finals(finals)
        class_rows.append({"id": s["id"], "name": s["name"], "stream_id": s.get("stream_id"),
                           "average": round(avg, 2), "finals": finals})
    _assign_positions(class_rows, "average")
    class_rank_map = {r["id"]: r for r in class_rows}
    stream_rank_map = None
    if stream_id:
        stream_rows = [dict(r) for r in class_rows if r["stream_id"] == stream_id]
        _assign_positions(stream_rows, "average")
        stream_rank_map = {r["id"]: r for r in stream_rows}
    return class_rows, class_rank_map, stream_rank_map, scores_bulk