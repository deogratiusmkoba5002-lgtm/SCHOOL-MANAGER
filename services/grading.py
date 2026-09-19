"""
Grading & division business logic: grade lookups, NECTA grade/division
tables, and division/points computation. Pure logic + DB reads — no Flask
request/response handling.
"""
from core.db import get_db
from config import _FALLBACK_GRADES


def get_grade_rules(school_id):
    try:
        con = get_db(); cur = con.cursor()
        cur.execute("SELECT min_score,max_score,grade,points FROM grade_config WHERE school_id=%s ORDER BY min_score DESC", (school_id,))
        rows = cur.fetchall(); cur.close(); con.close()
        if rows:
            # Grades saved before "points" existed (or left blank by the admin) get a
            # sensible default assigned automatically: best grade = 1 point, next = 2,
            # etc. (same convention NECTA uses) — so division/points never silently
            # fail just because a school never typed points in.
            return [{"min_score":r[0],"max_score":r[1],"grade":r[2],
                     "points": r[3] if r[3] is not None else (i+1)} for i,r in enumerate(rows)]
    except: pass
    return list(_FALLBACK_GRADES)


def get_grade(school_id, score):
    if score is None: return "-"
    for r in get_grade_rules(school_id):
        if score >= r["min_score"]: return r["grade"]
    return "F"


def get_school_grading_settings(school_id):
    con=get_db(); cur=con.cursor()
    cur.execute("SELECT grading_system, division_source FROM schools WHERE id=%s",(school_id,))
    row=cur.fetchone(); cur.close(); con.close()
    if not row: return {"grading_system":"o_level","division_source":"school"}
    return {"grading_system":row[0] or "o_level","division_source":row[1] or "school"}


def get_necta_grades(level):
    con=get_db(); cur=con.cursor()
    cur.execute("SELECT min_score,max_score,grade,points FROM necta_grades WHERE level=%s ORDER BY min_score DESC",(level,))
    rows=cur.fetchall(); cur.close(); con.close()
    return [{"min_score":r[0],"max_score":r[1],"grade":r[2],"points":r[3]} for r in rows]


def get_necta_divisions(level):
    con=get_db(); cur=con.cursor()
    cur.execute("SELECT min_points,max_points,division FROM necta_divisions WHERE level=%s ORDER BY min_points",(level,))
    rows=cur.fetchall(); cur.close(); con.close()
    return [{"min_points":r[0],"max_points":r[1],"division":r[2]} for r in rows]


def get_grade_points_rules(school_id):
    settings = get_school_grading_settings(school_id)
    if settings["division_source"]=="necta":
        return get_necta_grades(settings["grading_system"])
    return get_grade_rules(school_id)  # now includes 'points' if admin set them


def grade_and_points_for_score(rules, score):
    if score is None: return "-", None
    for r in sorted(rules, key=lambda r:-r["min_score"]):
        if score >= r["min_score"]:
            return r["grade"], r.get("points")
    return "F", None


def get_principal_subjects(school_id):
    con=get_db(); cur=con.cursor()
    cur.execute("SELECT name FROM school_subjects WHERE school_id=%s AND is_principal=1 ORDER BY sort_order",(school_id,))
    rows=cur.fetchall(); cur.close(); con.close()
    return [r[0] for r in rows]


def get_noncredit_subjects(school_id):
    con=get_db(); cur=con.cursor()
    cur.execute("SELECT name FROM school_subjects WHERE school_id=%s AND is_noncredit=1",(school_id,))
    rows=cur.fetchall(); cur.close(); con.close()
    return [r[0] for r in rows]


def compute_division_from_finals(school_id, finals, grading_system=None, division_source=None, noncredit_override=None):
    """finals: {subject: final_score_or_None}. Returns (total_points, division_label).
    grading_system/division_source/noncredit_override let a caller (e.g. a one-off
    grade score sheet) compute division under different settings than what's saved
    in Config, without touching the school's saved settings.

    A-level uses only the student's BEST 3 credited subjects (matches how the
    NECTA division bands are scaled). O-level uses the best 7. If a student
    doesn't have enough credited subjects with marks, "INC" (incomplete) is
    returned instead of silently showing blank. If the grade configuration
    itself is missing points for a matched grade, "ERR" is returned instead
    of silently showing blank, so the admin knows to check Grading System."""
    settings = get_school_grading_settings(school_id)
    level = grading_system or settings["grading_system"]
    div_source = division_source or settings["division_source"]
    rules = get_necta_grades(level) if div_source=="necta" else get_grade_rules(school_id)
    noncredit = set(noncredit_override) if noncredit_override is not None else set(get_noncredit_subjects(school_id))

    if level == "a_level":
        use_subjects = get_principal_subjects(school_id)
        if not use_subjects:
            use_subjects = list(finals.keys())  # fallback if admin hasn't set principals yet
        min_required = 3
    else:
        use_subjects = list(finals.keys())
        min_required = 5

    use_subjects = [s for s in use_subjects if s not in noncredit]

    scored_pairs = []
    grade_config_error = False
    for s in use_subjects:
        score = finals.get(s)
        if score is None: continue
        _, points = grade_and_points_for_score(rules, score)
        if points is None:
            grade_config_error = True
            continue
        scored_pairs.append((s, points))

    if grade_config_error:
        return "ERR", "ERR"
    if len(scored_pairs) < min_required:
        return "INC", "INC"

    scored_pairs.sort(key=lambda x: x[1])
    best_n = scored_pairs[:3] if level == "a_level" else scored_pairs[:7]
    total = sum(p for _, p in best_n)

    for d in get_necta_divisions(level):
        if d["min_points"] <= total <= d["max_points"]:
            return total, d["division"]
    return total, "0"