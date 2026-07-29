"""
School Manager - Flask API Backend (v7 - Full Multi-Tenant)
"""
import hashlib, os, tempfile, secrets, json, re, io, base64, time, hmac, uuid
import requests
import psycopg2, psycopg2.extras
from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta


try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("WARNING: python-dotenv not installed — .env file will NOT be loaded. "
          "Run: pip install python-dotenv")

app = Flask(__name__)
CORS(app)

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
DATABASE_URL  = os.environ.get("DATABASE_URL", "")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "storage", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
IMPORT_EXPORT_FOLDER = os.path.join(BASE_DIR, "storage", "import_exports")
os.makedirs(IMPORT_EXPORT_FOLDER, exist_ok=True)
ALLOWED_LOGO_EXT = {"png","jpg","jpeg","gif","webp","svg"}
def _mime_for_ext(ext):
    return {"png":"image/png","jpg":"image/jpeg","jpeg":"image/jpeg",
            "gif":"image/gif","webp":"image/webp","svg":"image/svg+xml"}.get(ext, "application/octet-stream")
_FALLBACK_SUBJECTS = [
    "mathematics","physics","chemistry","biology","geography","history","civics",
    "english","literature","kiswahili","bible knowledge","book keeping","commerce",
    "business studies","historia ya tanzania na maadili",
]
_FALLBACK_ABBR = {
    "historia ya tanzania na maadili":"HTM","mathematics":"MATH","physics":"PHY",
    "chemistry":"CHEM","biology":"BIO","geography":"GEO","history":"HIST",
    "civics":"CIV","english":"ENG","literature":"LIT","kiswahili":"KIS",
    "bible knowledge":"BK","book keeping":"BKP","commerce":"COM","business studies":"BS",
}
_FALLBACK_GRADES = [
    {"min_score":80,"max_score":100,"grade":"A"},{"min_score":70,"max_score":79,"grade":"B"},
    {"min_score":60,"max_score":69,"grade":"C"},{"min_score":50,"max_score":59,"grade":"D"},
    {"min_score":0,"max_score":49,"grade":"F"},
]

# ── SUBSCRIPTIONS (Manual Mobile Money Verification) ───────────
SUBSCRIPTION_PLANS = {
    "free":     {"amount": 0,      "days": 36500,
                 "label": "Free — basic features, forever",
                 "features": ["Marks entry", "On-screen viewing"]},
    "standard": {"amount": 300000, "days": 182,
                 "label": "Standard — 300,000 TZS / 6 months",
                 "features": ["Everything in Free", "Analytics", "PDF downloads", "Announcements", "Results publishing"]},
    "premium":  {"amount": 500000, "days": 365,
                 "label": "Premium — 500,000 TZS / year",
                 "features": ["Everything in Standard", "Priority support"]},
}

def is_subscribed(school_id):
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT subscription_exempt, subscription_status, subscription_expires_at FROM schools WHERE id=%s", (school_id,))
    row = cur.fetchone(); cur.close(); con.close()
    if not row: return False
    exempt, status, expires_at = row
    if exempt: return True
    return bool(status == "active" and expires_at and expires_at > datetime.utcnow())

def _expire_stale_payment_requests(school_id=None):
    """Lazily flips any 'pending' request older than 48h to 'expired'. Called
    at the top of every read/write path that touches payment_requests, so the
    transition happens the moment anyone looks — no scheduler needed. Rows are
    never deleted; only their status changes, preserving the audit trail."""
    con = get_db(); cur = con.cursor()
    if school_id:
        cur.execute("""UPDATE payment_requests SET status='expired'
                       WHERE status='pending' AND school_id=%s
                       AND submitted_at < NOW() - INTERVAL '48 hours'""", (school_id,))
    else:
        cur.execute("""UPDATE payment_requests SET status='expired'
                       WHERE status='pending' AND submitted_at < NOW() - INTERVAL '48 hours'""")
    con.commit(); cur.close(); con.close()

def subscription_required(f):
    from functools import wraps
    @wraps(f)
    def wrapper(*args, **kwargs):
        sid = school_id_from_header()
        if not is_subscribed(sid):
            return jsonify({"ok": False, "error": "subscription_required",
                             "message": "This feature requires an active subscription."}), 402
        return f(*args, **kwargs)
    return wrapper

def _platform_payment_config():
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT business_name, payment_number, networks FROM platform_payment_config WHERE id=1")
    row = cur.fetchone(); cur.close(); con.close()
    if not row: return {"business_name": "", "payment_number": "", "networks": []}
    return {"business_name": row[0], "payment_number": row[1],
            "networks": row[2].split(",") if row[2] else []}




# ── DB ────────────────────────────────────────────────────────
def get_db():
    con = psycopg2.connect(DATABASE_URL)
    con.autocommit = False
    return con

def to_dict(row, cur):
    if row is None: return None
    return dict(zip([d[0] for d in cur.description], row))

def to_dicts(rows, cur):
    if not rows: return []
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in rows]

# ── PASSWORD ──────────────────────────────────────────────────
def hash_password(pw, iterations=260_000):
    salt = secrets.token_hex(16)
    dk   = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), iterations)
    return f"{iterations}:{salt}:{dk.hex()}"

def verify_password(pw, stored):
    try:
        parts = stored.split(":")
        if len(parts) == 3:
            iterations, salt, dk_hex = parts
            iterations = int(iterations)
        else:
            # Legacy hashes (created before iteration count was stored) always used 260,000.
            salt, dk_hex = parts
            iterations = 260_000
        dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), iterations)
        return dk.hex() == dk_hex
    except: return False

# ── SCHOOL_ID HELPERS ─────────────────────────────────────────
def school_id_from_header():
    sid = request.headers.get("X-School-ID")
    if not sid:
        # Browser navigation (<a href>, window.open) used for PDF downloads
        # can't set custom headers, so those links pass school_id as a
        # query parameter instead — fall back to that here.
        sid = request.args.get("school_id")
    if sid:
        try: return int(sid)
        except: pass
    return 1

_REG_CODE_RE = re.compile(r'^[A-Za-z0-9_-]{3,32}$')

def valid_reg_code(code):
    return bool(code) and bool(_REG_CODE_RE.match(code.strip()))

def get_school_id_by_reg_code(reg_code):
    """Resolve a school's registration code (case-insensitive) to its school_id.
    This is the single source of truth for which school a login belongs to —
    it replaces guessing based on username/password alone, which is what let
    a teacher with the same username+password in two different schools get
    logged into the wrong one."""
    if not reg_code: return None
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT id FROM schools WHERE LOWER(reg_code)=LOWER(%s)", (reg_code.strip(),))
    row = cur.fetchone(); cur.close(); con.close()
    return row[0] if row else None

def generate_unique_reg_code(base):
    """Auto-generate a unique reg_code from a school name, e.g. for schools
    that don't pick their own, or for backfilling pre-existing schools."""
    base = re.sub(r'[^A-Za-z0-9_-]', '', (base or "").strip().replace(" ", "_"))[:24] or "school"
    con = get_db(); cur = con.cursor()
    candidate = base; suffix = 0
    while True:
        cur.execute("SELECT 1 FROM schools WHERE LOWER(reg_code)=LOWER(%s)", (candidate,))
        if not cur.fetchone(): break
        suffix += 1
        candidate = f"{base}_{suffix}"
    cur.close(); con.close()
    return candidate

def get_config_val(school_id, key, default=""):
    try:
        con = get_db(); cur = con.cursor()
        cur.execute("SELECT value FROM school_config WHERE school_id=%s AND key=%s", (school_id, key))
        row = cur.fetchone(); cur.close(); con.close()
        return row[0] if row else default
    except: return default

def set_config_val(school_id, key, value):
    con = get_db(); cur = con.cursor()
    cur.execute("""INSERT INTO school_config(school_id,key,value) VALUES(%s,%s,%s)
                   ON CONFLICT(school_id,key) DO UPDATE SET value=EXCLUDED.value""",
                (school_id, key, value))
    con.commit(); cur.close(); con.close()

def get_school_name(school_id):
    return get_config_val(school_id, "school_name", "School Name")

def is_registration_complete(school_id):
    return get_config_val(school_id, "registration_complete", "0") == "1"

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

def get_grade_rules(school_id):
    try:
        con = get_db(); cur = con.cursor()
        cur.execute("SELECT min_score,max_score,grade FROM grade_config WHERE school_id=%s ORDER BY min_score DESC", (school_id,))
        rows = cur.fetchall(); cur.close(); con.close()
        if rows: return [{"min_score":r[0],"max_score":r[1],"grade":r[2]} for r in rows]
    except: pass
    return list(_FALLBACK_GRADES)

def get_grade(school_id, score):
    if score is None: return "-"
    for r in get_grade_rules(school_id):
        if score >= r["min_score"]: return r["grade"]
    return "F"

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

def calc_ca_avg(school_id, student_id, subject, term_id):
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT score FROM ca_scores WHERE school_id=%s AND student_id=%s AND subject=%s AND term_id=%s",
                (school_id, student_id, subject, term_id))
    rows = cur.fetchall(); cur.close(); con.close()
    if not rows: return None
    return sum(r[0] for r in rows) / len(rows)

def calc_final(school_id, student_id, subject, term_id):
    term = get_term_by_id(school_id, term_id)
    if not term: return None
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT score FROM exam_scores WHERE school_id=%s AND student_id=%s AND subject=%s AND term_id=%s",
                (school_id, student_id, subject, term_id))
    row = cur.fetchone(); cur.close(); con.close()
    if not row: return None
    ca_avg = calc_ca_avg(school_id, student_id, subject, term_id)
    if ca_avg is None: return None
    return (ca_avg/100)*term["ca_weight"] + (row[0]/100)*term["exam_weight"]

def calc_student_average(school_id, student_id, term_id):
    subjects = get_subjects(school_id)
    finals = [calc_final(school_id, student_id, s, term_id) for s in subjects]
    finals = [f for f in finals if f is not None]
    return sum(finals)/len(finals) if finals else 0

def _assign_positions(rows, key):
    rows.sort(key=lambda x: (x[key] is None, -(x[key] or 0)))
    for i, r in enumerate(rows):
        if i == 0: r["position"] = 1
        elif r[key] == rows[i-1][key]: r["position"] = rows[i-1]["position"]
        else: r["position"] = i+1

def get_ranking(school_id, students, term_id):
    rows = []
    for s in students:
        avg = calc_student_average(school_id, s["id"], term_id)
        rows.append({"id":s["id"],"name":s["name"],"average":round(avg,2),"grade":get_grade(school_id,avg)})
    _assign_positions(rows, "average")
    return rows

def get_positions(school_id, student_id, class_id, stream_id, term_id):
    all_class = get_students_in_scope(school_id, class_id)
    class_ranking = get_ranking(school_id, all_class, term_id)
    c_pos   = next((r["position"] for r in class_ranking if r["id"]==student_id), "-")
    c_total = len(class_ranking)
    s_pos, s_total = None, None
    if stream_id:
        stream_studs   = get_students_in_scope(school_id, class_id, stream_id)
        stream_ranking = get_ranking(school_id, stream_studs, term_id)
        s_pos   = next((r["position"] for r in stream_ranking if r["id"]==student_id), "-")
        s_total = len(stream_ranking)
    return c_pos, c_total, s_pos, s_total

def get_subject_position(school_id, student_id, subject, class_id, stream_id, term_id):
    scope = get_students_in_scope(school_id, class_id, stream_id)
    scores = []
    for s in scope:
        f = calc_final(school_id, s["id"], subject, term_id)
        if f is not None: scores.append({"id":s["id"],"score":f})
    _assign_positions(scores, "score")
    for s in scores:
        if s["id"] == student_id: return s["position"]
    return "-"

def teacher_can_access(school_id, username, subject, class_id, stream_id=None):
    con = get_db(); cur = con.cursor()
    cur.execute("""SELECT id FROM subject_assignments
                   WHERE school_id=%s AND username=%s AND subject=%s AND class_id=%s
                   AND (stream_id=%s OR stream_id IS NULL)""",
                (school_id, username, subject, class_id, stream_id))
    row = cur.fetchone(); cur.close(); con.close()
    return row is not None


# ── BULK SCORE FETCHING (performance) ───────────────────────────
# Report cards, their PDFs, and the parent portal used to compute every
# figure (CA average, final score, class position, stream position,
# subject position) with its own tiny query on its own fresh DB
# connection — repeated once per subject, and for positions, once per
# subject PER STUDENT in the class. For a class of 40 students and 15
# subjects that's thousands of round trips for a single report. These
# helpers fetch every CA/exam score for a whole class+term in exactly
# two queries; everything else (averages, finals, rankings) is then
# plain Python math with zero further DB access.

def get_term_scores_bulk(school_id, term_id, student_ids):
    """{student_id: {subject: {"ca": {ca_name: score}, "exam": score_or_None}}}"""
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
    cur.close(); con.close()
    data = {}
    for student_id, subject, ca_name, score in ca_rows:
        d = data.setdefault(student_id, {}).setdefault(subject, {"ca": {}, "exam": None})
        d["ca"][ca_name] = score
    for student_id, subject, score in exam_rows:
        d = data.setdefault(student_id, {}).setdefault(subject, {"ca": {}, "exam": None})
        d["exam"] = score
    return data

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
    """Rank by a single assessment's raw score (a CA name, or 'exam') rather than the weighted final."""
    scored = []
    for stid in student_ids:
        entry = scores_bulk.get(stid, {}).get(subject)
        if not entry: continue
        val = entry["exam"] if assess == "exam" else entry["ca"].get(assess)
        if val is not None: scored.append({"id": stid, "score": val})
    _assign_positions(scored, "score")
    return {r["id"]: r["position"] for r in scored}

def get_class_report_data(school_id, term_id, class_id, stream_id, subjects, ca_weight, exam_weight):
    """
    One-shot computation of everything needed to render a report card /
    PDF / parent result for an entire class (and, if given, a stream
    within it) for one term — exactly 2 score queries total, regardless
    of class size or subject count.
    Returns (class_rows, class_rank_map, stream_rank_map, scores_bulk).
    class_rows: [{"id","name","stream_id","average","finals":{subject:final}}]
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


def _get_all_terms_ordered(school_id):
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM terms WHERE school_id=%s ORDER BY id ASC", (school_id,))
    rows = to_dicts(cur.fetchall(), cur); cur.close(); con.close()
    return rows

def _assessments_for_term(term):
    return [f"CA{i}" for i in range(1, term["ca_count"] + 1)] + ["exam"]

def get_all_students_in_school(school_id):
    con = get_db(); cur = con.cursor()
    cur.execute("""SELECT s.id,s.name,s.class_id,s.stream_id,c.class_name,st.stream_name
                   FROM students s JOIN classes c ON s.class_id=c.id
                   LEFT JOIN streams st ON s.stream_id=st.id
                   WHERE s.school_id=%s ORDER BY s.name""", (school_id,))
    rows = to_dicts(cur.fetchall(), cur); cur.close(); con.close()
    return rows

def _compute_overall_series(school_id, class_id, stream_id, subjects):
    """Chronological list of {"term_id","label","assess","values":{sid:avg},
    "avg":float,"ranks":{sid:pos},"student_count"} — one entry per CA/Exam
    across every term, using each student's average raw score across all
    subjects for that single assessment."""
    students = get_students_in_scope(school_id, class_id, stream_id) if class_id \
        else get_all_students_in_school(school_id)
    student_ids = [s["id"] for s in students]
    name_map = {s["id"]: s["name"] for s in students}
    if not student_ids: return [], name_map

    points = []
    for term in _get_all_terms_ordered(school_id):
        scores_bulk = get_term_scores_bulk(school_id, term["id"], student_ids)
        for assess in _assessments_for_term(term):
            values = {}
            for sid in student_ids:
                entry_map = scores_bulk.get(sid, {})
                vals = []
                for subj in subjects:
                    entry = entry_map.get(subj)
                    if not entry: continue
                    v = entry["exam"] if assess == "exam" else entry["ca"].get(assess)
                    if v is not None: vals.append(v)
                values[sid] = round(sum(vals) / len(vals), 2) if vals else None
            present = {sid: v for sid, v in values.items() if v is not None}
            if not present: continue
            ranked = [{"id": sid, "score": v} for sid, v in present.items()]
            _assign_positions(ranked, "score")
            ranks = {r["id"]: r["position"] for r in ranked}
            avg = round(sum(present.values()) / len(present), 2)
            label = f"{term['label']} {'Exam' if assess=='exam' else assess}"
            points.append({"term_id": term["id"], "assess": assess, "label": label,
                           "values": values, "avg": avg, "ranks": ranks,
                           "student_count": len(present)})
    return points, name_map

def _compute_subject_series(school_id, class_id, stream_id, subject):
    """Same shape as _compute_overall_series but for a single subject's raw
    CA/Exam marks — used for Subject Teacher analytics."""
    students = get_students_in_scope(school_id, class_id, stream_id)
    student_ids = [s["id"] for s in students]
    name_map = {s["id"]: s["name"] for s in students}
    if not student_ids: return [], name_map

    points = []
    for term in _get_all_terms_ordered(school_id):
        scores_bulk = get_term_scores_bulk(school_id, term["id"], student_ids)
        for assess in _assessments_for_term(term):
            values = {}
            for sid in student_ids:
                entry = scores_bulk.get(sid, {}).get(subject)
                if not entry: continue
                v = entry["exam"] if assess == "exam" else entry["ca"].get(assess)
                if v is not None: values[sid] = v
            if not values: continue
            ranked = [{"id": sid, "score": v} for sid, v in values.items()]
            _assign_positions(ranked, "score")
            ranks = {r["id"]: r["position"] for r in ranked}
            avg = round(sum(values.values()) / len(values), 2)
            label = f"{term['label']} {'Exam' if assess=='exam' else assess}"
            points.append({"term_id": term["id"], "assess": assess, "label": label,
                           "values": values, "avg": avg, "ranks": ranks,
                           "student_count": len(values)})
    return points, name_map

def _build_common_cards(points, name_map, school_id):
    """Shared card logic for both overall (admin/class-teacher) and
    subject-level (subject teacher) analytics. A student is only flagged as
    improved/declining/outstanding/at-risk when BOTH the mark and the
    position move together — this is the whole point of the spec: marks
    alone or position alone can mislead when exam difficulty varies."""
    if not points:
        return {"graph": [], "current_label": None, "average": None,
                "outstanding": [], "needs_support": [], "improved": [],
                "declining": [], "at_risk": []}

    graph = [{"label": p["label"], "value": p["avg"]} for p in points[-5:]]
    latest = points[-1]
    prev = points[-2] if len(points) >= 2 else None
    latest_vals, latest_ranks, latest_avg = latest["values"], latest["ranks"], latest["avg"]
    total = len(latest_ranks)

    outstanding, needs_support = [], []
    for sid, val in latest_vals.items():
        if val is None: continue
        pos = latest_ranks.get(sid)
        if pos is None: continue
        name = name_map.get(sid, "?")
        if pos <= 3 and val >= latest_avg + 5:
            outstanding.append({"id": sid, "name": name, "value": val, "position": pos})
        if total >= 3 and pos > total - 3 and val <= latest_avg - 5:
            needs_support.append({"id": sid, "name": name, "value": val, "position": pos})
    outstanding.sort(key=lambda r: r["position"])
    needs_support.sort(key=lambda r: -r["position"])

    improved, declining = [], []
    if prev:
        prev_vals, prev_ranks = prev["values"], prev["ranks"]
        for sid in set(latest_vals) & set(prev_vals):
            lv, pv = latest_vals[sid], prev_vals[sid]
            lp, pp = latest_ranks.get(sid), prev_ranks.get(sid)
            if None in (lv, pv, lp, pp): continue
            name = name_map.get(sid, "?")
            if lv > pv and lp < pp:
                improved.append({"id": sid, "name": name, "prev_value": pv, "current_value": lv,
                                 "prev_position": pp, "current_position": lp})
            elif lv < pv and lp > pp:
                declining.append({"id": sid, "name": name, "prev_value": pv, "current_value": lv,
                                  "prev_position": pp, "current_position": lp})

    at_risk = []
    grade_rules = get_grade_rules(school_id)
    lowest_rule = min(grade_rules, key=lambda r: r["min_score"]) if grade_rules else None
    if prev and lowest_rule:
        prev_vals = prev["values"]
        for sid in set(latest_vals) & set(prev_vals):
            lv, pv = latest_vals[sid], prev_vals[sid]
            if lv is None or pv is None: continue
            if lowest_rule["min_score"] <= lv <= lowest_rule["max_score"] and \
               lowest_rule["min_score"] <= pv <= lowest_rule["max_score"]:
                at_risk.append({"id": sid, "name": name_map.get(sid, "?"), "value": lv,
                                "reason": "Lowest grade in two consecutive examinations."})

    return {"graph": graph, "current_label": latest["label"], "average": round(latest_avg, 2),
            "outstanding": outstanding, "needs_support": needs_support,
            "improved": improved, "declining": declining, "at_risk": at_risk}

def _best_weakest_subject(school_id, class_id, stream_id, subjects, term_id, assess):
    students = get_students_in_scope(school_id, class_id, stream_id) if class_id \
        else get_all_students_in_school(school_id)
    ids = [s["id"] for s in students]
    if not ids: return None, None
    scores_bulk = get_term_scores_bulk(school_id, term_id, ids)
    subj_avgs = {}
    for subj in subjects:
        vals = []
        for sid in ids:
            entry = scores_bulk.get(sid, {}).get(subj)
            if not entry: continue
            v = entry["exam"] if assess == "exam" else entry["ca"].get(assess)
            if v is not None: vals.append(v)
        if vals: subj_avgs[subj] = round(sum(vals) / len(vals), 2)
    if not subj_avgs: return None, None
    best = max(subj_avgs.items(), key=lambda kv: kv[1])
    weak = min(subj_avgs.items(), key=lambda kv: kv[1])
    return {"subject": best[0], "average": best[1]}, {"subject": weak[0], "average": weak[1]}





# ── INIT DB ───────────────────────────────────────────────────
def init_db():
    con = get_db(); cur = con.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS schools (
        id            SERIAL PRIMARY KEY,
        school_name   TEXT NOT NULL,
        registered_at TIMESTAMP DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS users (
        id                   SERIAL,
        username             TEXT NOT NULL,
        password             TEXT NOT NULL,
        role                 TEXT NOT NULL DEFAULT 'teacher',
        school_id            INTEGER NOT NULL DEFAULT 1,
        is_class_teacher     INTEGER DEFAULT 0,
        class_id             INTEGER DEFAULT NULL,
        stream_id            INTEGER DEFAULT NULL,
        must_change_password INTEGER DEFAULT 0,
        student_id           INTEGER DEFAULT NULL,
        PRIMARY KEY(username, school_id)
    );
    CREATE TABLE IF NOT EXISTS classes (
        id         SERIAL PRIMARY KEY,
        school_id  INTEGER NOT NULL DEFAULT 1,
        class_name TEXT NOT NULL,
        UNIQUE(school_id, class_name)
    );
    CREATE TABLE IF NOT EXISTS streams (
        id          SERIAL PRIMARY KEY,
        school_id   INTEGER NOT NULL DEFAULT 1,
        class_id    INTEGER NOT NULL,
        stream_name TEXT NOT NULL,
        UNIQUE(class_id, stream_name)
    );
    CREATE TABLE IF NOT EXISTS students (
        id           SERIAL PRIMARY KEY,
        school_id    INTEGER NOT NULL DEFAULT 1,
        name         TEXT NOT NULL,
        class_id     INTEGER NOT NULL,
        stream_id    INTEGER DEFAULT NULL,
        phone_number TEXT DEFAULT NULL
    );
    CREATE TABLE IF NOT EXISTS subject_assignments (
        id        SERIAL PRIMARY KEY,
        school_id INTEGER NOT NULL DEFAULT 1,
        username  TEXT NOT NULL,
        subject   TEXT NOT NULL,
        class_id  INTEGER NOT NULL,
        stream_id INTEGER DEFAULT NULL,
        UNIQUE(school_id, username, subject, class_id, stream_id)
    );
    CREATE TABLE IF NOT EXISTS terms (
        id          SERIAL PRIMARY KEY,
        school_id   INTEGER NOT NULL DEFAULT 1,
        label       TEXT NOT NULL,
        ca_count    INTEGER NOT NULL DEFAULT 2,
        ca_weight   INTEGER NOT NULL DEFAULT 30,
        exam_weight INTEGER NOT NULL DEFAULT 70,
        status      TEXT NOT NULL DEFAULT 'open'
    );
    CREATE TABLE IF NOT EXISTS ca_scores (
        id         SERIAL PRIMARY KEY,
        school_id  INTEGER NOT NULL DEFAULT 1,
        student_id INTEGER NOT NULL,
        subject    TEXT NOT NULL,
        ca_name    TEXT NOT NULL,
        score      REAL NOT NULL,
        entered_by TEXT,
        term_id    INTEGER NOT NULL,
        UNIQUE(school_id, student_id, subject, ca_name, term_id)
    );
    CREATE TABLE IF NOT EXISTS exam_scores (
        id         SERIAL PRIMARY KEY,
        school_id  INTEGER NOT NULL DEFAULT 1,
        student_id INTEGER NOT NULL,
        subject    TEXT NOT NULL,
        score      REAL NOT NULL,
        entered_by TEXT,
        term_id    INTEGER NOT NULL,
        UNIQUE(school_id, student_id, subject, term_id)
    );
    CREATE TABLE IF NOT EXISTS remarks (
        school_id            INTEGER NOT NULL DEFAULT 1,
        student_id           INTEGER NOT NULL,
        term_id              INTEGER NOT NULL,
        class_teacher_remark TEXT DEFAULT '',
        head_remark          TEXT DEFAULT '',
        PRIMARY KEY(school_id, student_id, term_id)
    );
    CREATE TABLE IF NOT EXISTS school_config (
        school_id INTEGER NOT NULL DEFAULT 1,
        key       TEXT NOT NULL,
        value     TEXT NOT NULL DEFAULT '',
        PRIMARY KEY(school_id, key)
    );
    CREATE TABLE IF NOT EXISTS school_subjects (
        id           SERIAL PRIMARY KEY,
        school_id    INTEGER NOT NULL DEFAULT 1,
        name         TEXT NOT NULL,
        abbreviation TEXT NOT NULL,
        sort_order   INTEGER DEFAULT 0,
        UNIQUE(school_id, name)
    );
    CREATE TABLE IF NOT EXISTS grade_config (
        id         SERIAL PRIMARY KEY,
        school_id  INTEGER NOT NULL DEFAULT 1,
        min_score  REAL NOT NULL,
        max_score  REAL NOT NULL,
        grade      TEXT NOT NULL,
        sort_order INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS announcements (
        id             SERIAL PRIMARY KEY,
        school_id      INTEGER NOT NULL DEFAULT 1,
        title          TEXT NOT NULL,
        body           TEXT NOT NULL,
        target_classes TEXT NOT NULL DEFAULT 'all',
        posted_by      TEXT NOT NULL,
        posted_at      TIMESTAMP DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS announcement_reads (
        announcement_id INTEGER NOT NULL,
        student_id      INTEGER NOT NULL,
        read_at         TIMESTAMP DEFAULT NOW(),
        PRIMARY KEY(announcement_id, student_id)
    );
    CREATE TABLE IF NOT EXISTS results_published (
        school_id INTEGER NOT NULL DEFAULT 1,
        term_id   INTEGER NOT NULL,
        published INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY(school_id, term_id)
    );
    CREATE TABLE IF NOT EXISTS superadmins (
        username TEXT PRIMARY KEY,
        password TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS platform_announcements (
        id        SERIAL PRIMARY KEY,
        title     TEXT NOT NULL,
        body      TEXT NOT NULL,
        target    TEXT NOT NULL DEFAULT 'all',
        posted_at TIMESTAMP DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS platform_announcement_reads (
        announcement_id INTEGER NOT NULL,
        school_id       INTEGER NOT NULL,
        read_at         TIMESTAMP DEFAULT NOW(),
        PRIMARY KEY(announcement_id, school_id)
    );
    CREATE TABLE IF NOT EXISTS platform_payment_config (
        id             INTEGER PRIMARY KEY DEFAULT 1,
        business_name  TEXT NOT NULL DEFAULT 'DrDemic',
        payment_number TEXT NOT NULL DEFAULT '',
        networks       TEXT NOT NULL DEFAULT 'M-Pesa,Airtel Money,Mixx,HaloPesa',
        updated_at     TIMESTAMP DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS payment_requests (
        id              SERIAL PRIMARY KEY,
        school_id       INTEGER NOT NULL,
        plan            TEXT NOT NULL,
        claimed_amount  REAL NOT NULL,
        transaction_id  TEXT NOT NULL,
        phone_used      TEXT NOT NULL,
        payment_date    DATE NOT NULL,
        note            TEXT DEFAULT '',
        status          TEXT NOT NULL DEFAULT 'pending',
        submitted_by    TEXT,
        submitted_at    TIMESTAMP DEFAULT NOW(),
        decided_by      TEXT,
        decided_at      TIMESTAMP,
        decision_note   TEXT DEFAULT ''
    );
    """)
    

    # Migrations - add missing columns to existing tables
    migrations = [
        "ALTER TABLE schools ADD COLUMN IF NOT EXISTS registered_at TIMESTAMP DEFAULT NOW()",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS school_id INTEGER DEFAULT 1",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_class_teacher INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS class_id INTEGER DEFAULT NULL",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS stream_id INTEGER DEFAULT NULL",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS must_change_password INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS student_id INTEGER DEFAULT NULL",
        "ALTER TABLE classes ADD COLUMN IF NOT EXISTS school_id INTEGER DEFAULT 1",
        "ALTER TABLE streams ADD COLUMN IF NOT EXISTS school_id INTEGER DEFAULT 1",
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS school_id INTEGER DEFAULT 1",
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS stream_id INTEGER DEFAULT NULL",
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS phone_number TEXT DEFAULT NULL",
        "ALTER TABLE subject_assignments ADD COLUMN IF NOT EXISTS school_id INTEGER DEFAULT 1",
        "ALTER TABLE terms ADD COLUMN IF NOT EXISTS school_id INTEGER DEFAULT 1",
        "ALTER TABLE ca_scores ADD COLUMN IF NOT EXISTS school_id INTEGER DEFAULT 1",
        "ALTER TABLE exam_scores ADD COLUMN IF NOT EXISTS school_id INTEGER DEFAULT 1",
        "ALTER TABLE remarks ADD COLUMN IF NOT EXISTS school_id INTEGER DEFAULT 1",
        "ALTER TABLE school_config ADD COLUMN IF NOT EXISTS school_id INTEGER DEFAULT 1",
        "ALTER TABLE school_subjects ADD COLUMN IF NOT EXISTS school_id INTEGER DEFAULT 1",
        "ALTER TABLE grade_config ADD COLUMN IF NOT EXISTS school_id INTEGER DEFAULT 1",
        "ALTER TABLE announcements ADD COLUMN IF NOT EXISTS school_id INTEGER DEFAULT 1",
        "ALTER TABLE results_published ADD COLUMN IF NOT EXISTS school_id INTEGER DEFAULT 1",
        "ALTER TABLE schools ADD COLUMN IF NOT EXISTS subscription_exempt INTEGER DEFAULT 0",
        "ALTER TABLE schools ADD COLUMN IF NOT EXISTS subscription_status TEXT DEFAULT 'inactive'",
        "ALTER TABLE schools ADD COLUMN IF NOT EXISTS subscription_plan TEXT DEFAULT ''",
        "ALTER TABLE schools ADD COLUMN IF NOT EXISTS subscription_expires_at TIMESTAMP",
    ]
    for m in migrations:
        try: cur.execute(m)
        except Exception as e: print(f"Migration note: {e}")

    # Seed school_id=1 for all existing data
    try:
        cur.execute("INSERT INTO schools(id,school_name) VALUES(1,'Default School') ON CONFLICT DO NOTHING")
    except: pass

    seeds = [
        "UPDATE users SET school_id=1 WHERE school_id IS NULL",
        "UPDATE classes SET school_id=1 WHERE school_id IS NULL",
        "UPDATE streams SET school_id=1 WHERE school_id IS NULL",
        "UPDATE students SET school_id=1 WHERE school_id IS NULL",
        "UPDATE subject_assignments SET school_id=1 WHERE school_id IS NULL",
        "UPDATE terms SET school_id=1 WHERE school_id IS NULL",
        "UPDATE ca_scores SET school_id=1 WHERE school_id IS NULL",
        "UPDATE exam_scores SET school_id=1 WHERE school_id IS NULL",
        "UPDATE remarks SET school_id=1 WHERE school_id IS NULL",
        "UPDATE school_config SET school_id=1 WHERE school_id IS NULL",
        "UPDATE school_subjects SET school_id=1 WHERE school_id IS NULL",
        "UPDATE grade_config SET school_id=1 WHERE school_id IS NULL",
        "UPDATE announcements SET school_id=1 WHERE school_id IS NULL",
        "UPDATE results_published SET school_id=1 WHERE school_id IS NULL",
        "INSERT INTO school_config(school_id,key,value) VALUES(1,'school_name','School Name') ON CONFLICT DO NOTHING",
        "INSERT INTO school_config(school_id,key,value) VALUES(1,'registration_complete','0') ON CONFLICT DO NOTHING",
        "INSERT INTO school_config(school_id,key,value) VALUES(1,'phone','') ON CONFLICT DO NOTHING",
        "INSERT INTO school_config(school_id,key,value) VALUES(1,'email','') ON CONFLICT DO NOTHING",
        "INSERT INTO school_config(school_id,key,value) VALUES(1,'motto','') ON CONFLICT DO NOTHING",
        "INSERT INTO school_config(school_id,key,value) VALUES(1,'logo_path','') ON CONFLICT DO NOTHING",
        "INSERT INTO school_config(school_id,key,value) VALUES(1,'admin_phone','') ON CONFLICT DO NOTHING",
    ]
    for s in seeds:
        try: cur.execute(s)
        except Exception as e: print(f"Seed note: {e}")

    # Repair announcements from before the target-classes default-selection
    # fix — these were saved with an empty target_classes and were invisible
    # to every parent, regardless of what class they were meant for.
    try:
        cur.execute("UPDATE announcements SET target_classes='all' WHERE target_classes IS NULL OR TRIM(target_classes)=''")
    except Exception as e:
        print(f"announcement target_classes repair note: {e}")

# Subscription grandfathering — runs exactly once, on the very next deploy.
# Every school that exists at that moment (your demo schools included) gets
# exempt=1 forever. Any school registered after this point gets exempt=0
# by column default and must subscribe.
    try:
        cur.execute("CREATE TABLE IF NOT EXISTS _subscription_migration (id INTEGER PRIMARY KEY, applied INTEGER DEFAULT 0)")
        cur.execute("INSERT INTO _subscription_migration(id,applied) VALUES(1,0) ON CONFLICT(id) DO NOTHING")
        cur.execute("SELECT applied FROM _subscription_migration WHERE id=1")
        if cur.fetchone()[0] == 0:
            cur.execute("UPDATE schools SET subscription_exempt=1")
            cur.execute("UPDATE _subscription_migration SET applied=1 WHERE id=1")
            print("Subscription migration: grandfathered all existing schools.")
    except Exception as e:
        print(f"Subscription migration note: {e}")
    try:
        cur.execute("ALTER TABLE schools ADD COLUMN IF NOT EXISTS reg_code TEXT")
        cur.execute("SELECT id FROM schools WHERE reg_code IS NULL OR reg_code=''")
        for (missing_id,) in cur.fetchall():
            cur.execute("UPDATE schools SET reg_code=%s WHERE id=%s", (f"school-{missing_id}", missing_id))
        cur.execute("SELECT 1 FROM pg_indexes WHERE indexname='idx_schools_reg_code_ci'")
        if not cur.fetchone():
            cur.execute("CREATE UNIQUE INDEX idx_schools_reg_code_ci ON schools (LOWER(reg_code))")
    except Exception as e:
        print(f"reg_code migration note: {e}")

    try:
        cur.execute("INSERT INTO platform_payment_config(id) VALUES(1) ON CONFLICT DO NOTHING")
        # Partial unique index: blocks reuse of a transaction ID that's currently
        # pending or already funded an approval, but frees it up again if a
        # request is rejected or cancelled — so a school that mistyped some
        # OTHER field can resubmit with the same (real) transaction ID.
        cur.execute("SELECT 1 FROM pg_indexes WHERE indexname='idx_payment_requests_txn_ci'")
        if not cur.fetchone():
            cur.execute("""CREATE UNIQUE INDEX idx_payment_requests_txn_ci
                           ON payment_requests (LOWER(transaction_id))
                           WHERE status IN ('pending','approved')""")
    except Exception as e:
        print(f"payment_requests migration note: {e}")

    # Superadmin from env
    sa_user = os.environ.get("SUPERADMIN_USERNAME","")
    

    # Superadmin from env
    sa_user = os.environ.get("SUPERADMIN_USERNAME","")
    sa_pass = os.environ.get("SUPERADMIN_PASSWORD","")
    if sa_user and sa_pass:
        try:
            cur.execute("SELECT username FROM superadmins WHERE username=%s", (sa_user,))
            if not cur.fetchone():
                cur.execute("INSERT INTO superadmins(username,password) VALUES(%s,%s)",
                            (sa_user, hash_password(sa_pass)))
                print(f"Superadmin '{sa_user}' created.")
        except Exception as e: print(f"Superadmin note: {e}")

    # Migration safety net: older deployments may have a `users` table created
    # before PRIMARY KEY(username, school_id) was added. Several routes rely on
    # ON CONFLICT(username, school_id), which requires a real unique constraint
    # on exactly that pair — without it, every such insert fails with
    # "no unique or exclusion constraint matching the ON CONFLICT specification".
    try:
        cur.execute("""
            SELECT 1 FROM pg_constraint
            WHERE conrelid = 'users'::regclass
              AND contype IN ('p','u')
              AND conkey = (
                  SELECT array_agg(attnum ORDER BY attnum)
                  FROM pg_attribute
                  WHERE attrelid = 'users'::regclass
                    AND attname IN ('username','school_id')
              )
        """)
        if not cur.fetchone():
            cur.execute("ALTER TABLE users ADD CONSTRAINT users_username_school_id_key UNIQUE (username, school_id)")
            print("Migration: added missing UNIQUE(username, school_id) constraint on users.")
    except Exception as e:
        print(f"Users unique-constraint check note: {e}")

    # Performance: these columns are filtered/joined on every students/marks/import
    # request. Without indexes, schools with thousands of students (e.g. bulk Excel
    # imports) see full table scans on every lookup — this gets slower as the school grows.
    try:
        cur.execute("CREATE INDEX IF NOT EXISTS idx_students_school ON students(school_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_students_school_phone ON students(school_id, phone_number)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_students_class ON students(class_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_students_stream ON students(stream_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_classes_school ON classes(school_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_streams_class ON streams(class_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_users_school_role ON users(school_id, role)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_exam_scores_student ON exam_scores(school_id, student_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ca_scores_student ON ca_scores(school_id, student_id)")
    except Exception as e:
        print(f"Index creation note: {e}")

    con.commit(); cur.close(); con.close()
    print("DB ready (multi-tenant).")

    try:
            cur.execute("INSERT INTO platform_payment_config(id) VALUES(1) ON CONFLICT DO NOTHING")
            # Partial unique index: blocks reuse of a transaction ID that's currently
            # pending or already funded an approval, but frees it up again if a
            # request is rejected or cancelled — so a school that mistyped some
            # OTHER field can resubmit with the same (real) transaction ID.
            cur.execute("SELECT 1 FROM pg_indexes WHERE indexname='idx_payment_requests_txn_ci'")
            if not cur.fetchone():
                cur.execute("""CREATE UNIQUE INDEX idx_payment_requests_txn_ci
                               ON payment_requests (LOWER(transaction_id))
                               WHERE status IN ('pending','approved')""")
    except Exception as e:
        print(f"payment_requests migration note: {e}")


# ══════════════════════════════════════════════════════════════
# API ROUTES
# ══════════════════════════════════════════════════════════════

# ── SCHOOL REGISTRATION ───────────────────────────────────────
@app.route("/api/register/school", methods=["POST"])
def api_register_school():
    data         = request.form
    school_name  = data.get("school_name","").strip()
    admin_user   = data.get("admin_username","").strip()
    admin_pass   = data.get("admin_password","").strip()
    phone        = data.get("phone","").strip()
    email        = data.get("email","").strip()
    admin_phone  = data.get("admin_phone","").strip()
    motto        = data.get("motto","").strip()
    reg_code     = data.get("reg_code","").strip()
    if not school_name: return jsonify({"ok":False,"error":"School name required"}), 400
    if not admin_user or not admin_pass: return jsonify({"ok":False,"error":"Admin username and password required"}), 400
    if reg_code:
        if not valid_reg_code(reg_code):
            return jsonify({"ok":False,"error":"Registration code must be 3-32 characters: letters, numbers, underscore or hyphen only"}), 400
        if get_school_id_by_reg_code(reg_code):
            return jsonify({"ok":False,"error":f"Registration code '{reg_code}' is already taken by another school. Please choose a different one."}), 409
    else:
        reg_code = generate_unique_reg_code(school_name)
    logo_b64 = ""; logo_mime = ""
    if "logo" in request.files:
        f = request.files["logo"]
        if f and f.filename:
            ext = f.filename.rsplit(".",1)[-1].lower() if "." in f.filename else ""
            if ext not in ALLOWED_LOGO_EXT: return jsonify({"ok":False,"error":"Logo must be an image"}), 400
            raw = f.read()
            if len(raw) > 2*1024*1024:
                return jsonify({"ok":False,"error":"Logo must be smaller than 2MB"}), 400
            logo_mime = _mime_for_ext(ext)
            logo_b64  = base64.b64encode(raw).decode("ascii")
    try:
        classes_data  = json.loads(data.get("classes","[]"))
        subjects_data = json.loads(data.get("subjects","[]"))
        grades_data   = json.loads(data.get("grades","[]"))
    except Exception as e:
        return jsonify({"ok":False,"error":f"Invalid JSON: {e}"}), 400
    if not subjects_data: return jsonify({"ok":False,"error":"At least one subject required"}), 400
    if not grades_data:   return jsonify({"ok":False,"error":"At least one grade rule required"}), 400
    con = get_db(); cur = con.cursor()
    try:
        cur.execute("INSERT INTO schools(school_name,reg_code) VALUES(%s,%s) RETURNING id", (school_name, reg_code))
        school_id = cur.fetchone()[0]
        cur.execute("INSERT INTO users(username,password,role,school_id) VALUES(%s,%s,'admin',%s)",
                    (admin_user, hash_password(admin_pass), school_id))
        logo_path = f"api/logo/{school_id}" if logo_b64 else ""
        cfg = {"school_name":school_name,"phone":phone,"email":email,"admin_phone":admin_phone,
               "motto":motto,"logo_path":logo_path,"registration_complete":"1"}
        if logo_b64:
            cfg["logo_data"] = logo_b64
            cfg["logo_mime"] = logo_mime
        for k,v in cfg.items():
            cur.execute("INSERT INTO school_config(school_id,key,value) VALUES(%s,%s,%s) ON CONFLICT(school_id,key) DO UPDATE SET value=EXCLUDED.value",
                        (school_id, k, v))
        for i,s in enumerate(subjects_data):
            name = s.get("name","").strip().lower(); ab = s.get("abbreviation","").strip().upper()
            if name:
                cur.execute("INSERT INTO school_subjects(school_id,name,abbreviation,sort_order) VALUES(%s,%s,%s,%s) ON CONFLICT(school_id,name) DO UPDATE SET abbreviation=EXCLUDED.abbreviation",
                            (school_id, name, ab, i))
        for i,g in enumerate(grades_data):
            cur.execute("INSERT INTO grade_config(school_id,min_score,max_score,grade,sort_order) VALUES(%s,%s,%s,%s,%s)",
                        (school_id, float(g["min_score"]), float(g["max_score"]), str(g["grade"]).strip(), i))
        for cls in classes_data:
            cname = cls.get("name","").strip()
            if not cname: continue
            cur.execute("INSERT INTO classes(school_id,class_name) VALUES(%s,%s) ON CONFLICT(school_id,class_name) DO NOTHING RETURNING id",
                        (school_id, cname))
            row = cur.fetchone()
            if not row:
                cur.execute("SELECT id FROM classes WHERE school_id=%s AND class_name=%s", (school_id, cname))
                row = cur.fetchone()
            cid = row[0]
            for sname in cls.get("streams",[]):
                sname = sname.strip()
                if sname:
                    cur.execute("INSERT INTO streams(school_id,class_id,stream_name) VALUES(%s,%s,%s) ON CONFLICT(class_id,stream_name) DO NOTHING",
                                (school_id, cid, sname))
        con.commit()
    except Exception as e:
        con.rollback(); cur.close(); con.close()
        return jsonify({"ok":False,"error":str(e)}), 500
    cur.close(); con.close()
    return jsonify({"ok":True,"school_id":school_id})

# ── AUTH ──────────────────────────────────────────────────────
@app.route("/api/login", methods=["POST"])
def api_login():
    d = request.json or {}
    reg_code = (d.get("reg_code") or "").strip()
    u, p = d.get("username","").strip(), d.get("password","")
    if not reg_code: return jsonify({"ok":False,"error":"Enter your school's registration code"}), 400
    if not u or not p: return jsonify({"ok":False,"error":"Enter username and password"}), 400
    school_id = get_school_id_by_reg_code(reg_code)
    if not school_id:
        return jsonify({"ok":False,"error":"School registration code not recognized"}), 401
    # The registration code pins the school unambiguously, so this lookup is
    # always scoped to exactly one school — a username/password that matches
    # a *different* school can never authenticate here, by construction.
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM users WHERE username=%s AND school_id=%s", (u, school_id))
    row = cur.fetchone(); cols = [x[0] for x in cur.description] if cur.description else []
    cur.close(); con.close()
    if not row: return jsonify({"ok":False,"error":"Invalid registration code, username or password"}), 401
    user = dict(zip(cols, row))
    if not verify_password(p, user["password"]):
        return jsonify({"ok":False,"error":"Invalid registration code, username or password"}), 401
    return jsonify({"ok":True,"user":{
        "username":             user["username"],
        "role":                 user["role"],
        "school_id":            school_id,
        "is_class_teacher":     bool(user.get("is_class_teacher",0)),
        "class_id":             user.get("class_id"),
        "stream_id":            user.get("stream_id"),
        "must_change_password": bool(user.get("must_change_password",0)),
        "student_id":           user.get("student_id"),
    },"registration_complete": is_registration_complete(school_id)})

@app.route("/api/school/info", methods=["GET"])
def api_school_info():
    reg_code = request.args.get("reg_code")
    if reg_code:
        school_id = get_school_id_by_reg_code(reg_code)
        if not school_id: return jsonify({})
    else:
        school_id = request.args.get("school_id",1,type=int)
    keys = ["school_name","phone","email","admin_phone","motto","logo_path","registration_complete"]
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT key,value FROM school_config WHERE school_id=%s AND key=ANY(%s)", (school_id, keys))
    rows = cur.fetchall(); cur.close(); con.close()
    return jsonify({r[0]:r[1] for r in rows})

@app.route("/api/find_reg_code", methods=["POST"])
def api_find_reg_code():
    """Recovery helper for people who don't know their school's registration
    code (e.g. right after this feature was deployed). Given a correct
    username+password, find which school it belongs to — but only answers
    when the match is unambiguous. If the same username+password happens to
    be valid in more than one school, this refuses to guess, which is exactly
    the ambiguity the registration-code login was built to eliminate."""
    d = request.json or {}
    u, p = d.get("username","").strip(), d.get("password","")
    if not u or not p:
        return jsonify({"ok":False,"error":"Enter your username and password"}), 400
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM users WHERE username=%s", (u,))
    rows = cur.fetchall(); cols = [x[0] for x in cur.description] if cur.description else []
    cur.close(); con.close()
    matches = [dict(zip(cols,row)) for row in rows if verify_password(p, dict(zip(cols,row))["password"])]
    if not matches:
        return jsonify({"ok":False,"error":"Invalid username or password"}), 401
    if len(matches) > 1:
        return jsonify({"ok":False,"error":"This username and password exist in more than one school. Please ask your school admin for your registration code."}), 409
    school_id = matches[0]["school_id"]
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT reg_code, school_name FROM schools WHERE id=%s", (school_id,))
    row = cur.fetchone(); cur.close(); con.close()
    if not row: return jsonify({"ok":False,"error":"School not found"}), 404
    return jsonify({"ok":True,"reg_code":row[0],"school_name":row[1]})

@app.route("/api/setup_admin", methods=["POST"])
def api_setup_admin():
    d = request.json
    secret = d.get("secret",""); username = d.get("username","").strip(); password = d.get("password","")
    if not os.environ.get("ADMIN_SETUP_SECRET") or secret != os.environ.get("ADMIN_SETUP_SECRET"):
        return jsonify({"ok":False,"error":"Invalid setup secret"}), 403
    if not username or not password: return jsonify({"ok":False,"error":"Username and password required"}), 400
    con = get_db(); cur = con.cursor()
    cur.execute("INSERT INTO schools(id,school_name) VALUES(1,'Default School') ON CONFLICT DO NOTHING")
    cur.execute("SELECT username FROM users WHERE role='admin' AND school_id=1")
    if cur.fetchone():
        cur.close(); con.close()
        return jsonify({"ok":False,"error":"Admin already exists"}), 409
    cur.execute("INSERT INTO users(username,password,role,school_id) VALUES(%s,%s,'admin',1)",
                (username, hash_password(password)))
    for k,v in [("school_name","School Name"),("registration_complete","0"),("phone",""),
                 ("email",""),("motto",""),("logo_path",""),("admin_phone","")]:
        cur.execute("INSERT INTO school_config(school_id,key,value) VALUES(1,%s,%s) ON CONFLICT DO NOTHING",(k,v))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok":True,"school_id":1})

@app.route("/api/change_password", methods=["POST"])
def api_change_password():
    d = request.json
    username  = d.get("username","").strip()
    school_id = d.get("school_id") or school_id_from_header()
    old_pw    = d.get("old_password","")
    new_pw    = d.get("new_password","").strip()
    if len(new_pw) < 6: return jsonify({"ok":False,"error":"Password must be at least 6 characters"}), 400
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT password FROM users WHERE username=%s AND school_id=%s", (username, school_id))
    row = cur.fetchone()
    if not row or not verify_password(old_pw, row[0]):
        cur.close(); con.close(); return jsonify({"ok":False,"error":"Current password is incorrect"}), 401
    cur.execute("UPDATE users SET password=%s,must_change_password=0 WHERE username=%s AND school_id=%s",
                (hash_password(new_pw), username, school_id))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok":True})

@app.route("/uploads/logos/<filename>")
def serve_logo(filename):
    return send_from_directory(os.path.join(UPLOAD_FOLDER,"logos"), filename)


# ── SUBJECTS / GRADES ─────────────────────────────────────────
@app.route("/api/subjects", methods=["GET"])
def api_get_subjects():
    sid = school_id_from_header()
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT id,name,abbreviation,sort_order FROM school_subjects WHERE school_id=%s ORDER BY sort_order,name",(sid,))
    rows = to_dicts(cur.fetchall(), cur); cur.close(); con.close()
    if rows: return jsonify(rows)
    return jsonify([{"id":i,"name":n,"abbreviation":_FALLBACK_ABBR.get(n,n[:4].upper()),"sort_order":i} for i,n in enumerate(_FALLBACK_SUBJECTS)])

@app.route("/api/subjects", methods=["POST"])
def api_save_subjects():
    sid = school_id_from_header(); subjects = request.json.get("subjects",[])
    con = get_db(); cur = con.cursor()
    cur.execute("DELETE FROM school_subjects WHERE school_id=%s",(sid,))
    for i,s in enumerate(subjects):
        name=s.get("name","").strip().lower(); ab=s.get("abbreviation","").strip().upper()
        if name:
            cur.execute("INSERT INTO school_subjects(school_id,name,abbreviation,sort_order) VALUES(%s,%s,%s,%s)",(sid,name,ab,i))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok":True})

@app.route("/api/grades", methods=["GET"])
def api_get_grades():
    return jsonify(get_grade_rules(school_id_from_header()))

@app.route("/api/grades", methods=["POST"])
def api_save_grades():
    sid = school_id_from_header(); grades = request.json.get("grades",[])
    con = get_db(); cur = con.cursor()
    cur.execute("DELETE FROM grade_config WHERE school_id=%s",(sid,))
    for i,g in enumerate(grades):
        cur.execute("INSERT INTO grade_config(school_id,min_score,max_score,grade,sort_order) VALUES(%s,%s,%s,%s,%s)",
                    (sid,float(g["min_score"]),float(g["max_score"]),str(g["grade"]).strip(),i))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok":True})

# ── CLASSES ───────────────────────────────────────────────────
@app.route("/api/classes", methods=["GET"])
def api_get_classes():
    sid = school_id_from_header()
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM classes WHERE school_id=%s ORDER BY class_name",(sid,))
    classes = to_dicts(cur.fetchall(), cur); result = []
    for c in classes:
        cur.execute("SELECT * FROM streams WHERE school_id=%s AND class_id=%s ORDER BY stream_name",(sid,c["id"]))
        result.append({**c,"streams":to_dicts(cur.fetchall(),cur)})
    cur.close(); con.close(); return jsonify(result)

@app.route("/api/classes", methods=["POST"])
def api_add_class():
    sid = school_id_from_header(); name = request.json.get("class_name","").strip()
    if not name: return jsonify({"ok":False,"error":"Class name required"}),400
    con = get_db(); cur = con.cursor()
    try:
        cur.execute("INSERT INTO classes(school_id,class_name) VALUES(%s,%s) RETURNING id",(sid,name))
        new_id = cur.fetchone()[0]; con.commit()
    except psycopg2.errors.UniqueViolation:
        con.rollback(); cur.close(); con.close(); return jsonify({"ok":False,"error":"Class already exists"}),409
    cur.close(); con.close(); return jsonify({"ok":True,"id":new_id})

@app.route("/api/classes/<int:cid>", methods=["DELETE"])
def api_delete_class(cid):
    sid = school_id_from_header()
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM students WHERE school_id=%s AND class_id=%s",(sid,cid))
    if cur.fetchone()[0]>0:
        cur.close(); con.close(); return jsonify({"ok":False,"error":"Students exist in this class"}),409
    cur.execute("DELETE FROM streams WHERE school_id=%s AND class_id=%s",(sid,cid))
    cur.execute("DELETE FROM classes WHERE id=%s AND school_id=%s",(cid,sid))
    con.commit(); cur.close(); con.close(); return jsonify({"ok":True})

@app.route("/api/classes/<int:cid>/streams", methods=["POST"])
def api_add_stream(cid):
    sid = school_id_from_header(); name = request.json.get("stream_name","").strip()
    if not name: return jsonify({"ok":False,"error":"Stream name required"}),400
    con = get_db(); cur = con.cursor()
    try:
        cur.execute("INSERT INTO streams(school_id,class_id,stream_name) VALUES(%s,%s,%s) RETURNING id",(sid,cid,name))
        new_id = cur.fetchone()[0]; con.commit()
    except psycopg2.errors.UniqueViolation:
        con.rollback(); cur.close(); con.close(); return jsonify({"ok":False,"error":"Stream already exists"}),409
    cur.close(); con.close(); return jsonify({"ok":True,"id":new_id})

@app.route("/api/streams/<int:stream_id>", methods=["DELETE"])
def api_delete_stream(stream_id):
    sid = school_id_from_header()
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM students WHERE school_id=%s AND stream_id=%s",(sid,stream_id))
    if cur.fetchone()[0]>0:
        cur.close(); con.close(); return jsonify({"ok":False,"error":"Students exist in this stream"}),409
    cur.execute("DELETE FROM streams WHERE id=%s AND school_id=%s",(stream_id,sid))
    con.commit(); cur.close(); con.close(); return jsonify({"ok":True})

# ── STUDENTS ──────────────────────────────────────────────────
@app.route("/api/students", methods=["GET"])
def api_students():
    sid = school_id_from_header()
    con = get_db(); cur = con.cursor()
    cur.execute("""SELECT s.id,s.name,s.class_id,s.stream_id,c.class_name,st.stream_name
                   FROM students s JOIN classes c ON s.class_id=c.id
                   LEFT JOIN streams st ON s.stream_id=st.id
                   WHERE s.school_id=%s ORDER BY c.class_name,st.stream_name,s.name""",(sid,))
    rows = to_dicts(cur.fetchall(),cur); cur.close(); con.close(); return jsonify(rows)

@app.route("/api/students", methods=["POST"])
def api_add_student():
    sid = school_id_from_header(); d = request.json
    name=d.get("name","").strip(); class_id=d.get("class_id"); stream_id=d.get("stream_id") or None
    phone=d.get("phone_number","").strip()
    if not name or not class_id: return jsonify({"ok":False,"error":"Name and class required"}),400
    if not phone or len(phone)<4: return jsonify({"ok":False,"error":"Parent phone required"}),400
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT id FROM classes WHERE id=%s AND school_id=%s",(class_id,sid))
    if not cur.fetchone(): cur.close(); con.close(); return jsonify({"ok":False,"error":"Invalid class"}),400
    cur.execute("SELECT id FROM students WHERE school_id=%s AND LOWER(TRIM(name))=%s AND class_id=%s "
                "AND COALESCE(stream_id,0)=%s AND phone_number=%s",
                (sid, name.lower(), class_id, stream_id or 0, phone))
    if cur.fetchone():
        cur.close(); con.close()
        return jsonify({"ok":False,"error":"A student with this name, class, stream and phone already exists"}),409
    cur.execute("INSERT INTO students(school_id,name,class_id,stream_id,phone_number) VALUES(%s,%s,%s,%s,%s) RETURNING id",
                (sid,name,class_id,stream_id,phone))
    student_id = cur.fetchone()[0]; con.commit(); cur.close(); con.close()
    username, temp_pw = _gen_parent_creds(sid, name, phone, student_id)
    con = get_db(); cur = con.cursor()
    cur.execute("INSERT INTO users(username,password,role,school_id,must_change_password,student_id) VALUES(%s,%s,'parent',%s,1,%s) ON CONFLICT(username,school_id) DO NOTHING",
                (username, hash_password(temp_pw), sid, student_id))
    created = cur.rowcount > 0
    con.commit(); cur.close(); con.close()
    if created:
        return jsonify({"ok":True,"parent_username":username,"temp_password":temp_pw})
    return jsonify({"ok":True,"parent_username":None,"temp_password":None,
                    "warning":f"Student added, but username '{username}' is already taken by another parent account "
                              f"(same name as an existing student). No new login was created — that student will "
                              f"need a different name on file, or share the existing '{username}' login."})

def _gen_parent_creds(school_id, student_name, phone_number, student_id):
    username = student_name.strip().lower().replace(" ","_")
    temp_pw  = phone_number.strip()[-4:]
    
    return username, temp_pw

@app.route("/api/students/bulk_delete", methods=["POST"])
def api_bulk_delete_students():
    sid = school_id_from_header(); ids = request.json.get("ids", [])
    try: ids = [int(i) for i in ids]
    except (TypeError, ValueError): return jsonify({"ok":False,"error":"Invalid student IDs"}),400
    if not ids: return jsonify({"ok":False,"error":"No students selected"}),400
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT id FROM students WHERE school_id=%s AND id=ANY(%s)",(sid,ids))
    valid_ids = [r[0] for r in cur.fetchall()]
    if not valid_ids: cur.close(); con.close(); return jsonify({"ok":False,"error":"No matching students found"}),404
    cur.execute("DELETE FROM announcement_reads WHERE student_id=ANY(%s)",(valid_ids,))
    cur.execute("DELETE FROM remarks WHERE school_id=%s AND student_id=ANY(%s)",(sid,valid_ids))
    cur.execute("DELETE FROM ca_scores WHERE school_id=%s AND student_id=ANY(%s)",(sid,valid_ids))
    cur.execute("DELETE FROM exam_scores WHERE school_id=%s AND student_id=ANY(%s)",(sid,valid_ids))
    cur.execute("DELETE FROM users WHERE school_id=%s AND student_id=ANY(%s) AND role='parent'",(sid,valid_ids))
    cur.execute("DELETE FROM students WHERE school_id=%s AND id=ANY(%s)",(sid,valid_ids))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok":True,"deleted":len(valid_ids)})

@app.route("/api/students/<int:student_id>", methods=["DELETE"])
def api_delete_student(student_id):
    sid = school_id_from_header()
    con = get_db(); cur = con.cursor()
    cur.execute("DELETE FROM announcement_reads WHERE student_id=%s",(student_id,))
    cur.execute("DELETE FROM remarks WHERE school_id=%s AND student_id=%s",(sid,student_id))
    cur.execute("DELETE FROM ca_scores WHERE school_id=%s AND student_id=%s",(sid,student_id))
    cur.execute("DELETE FROM exam_scores WHERE school_id=%s AND student_id=%s",(sid,student_id))
    cur.execute("DELETE FROM users WHERE school_id=%s AND student_id=%s AND role='parent'",(sid,student_id))
    cur.execute("DELETE FROM students WHERE id=%s AND school_id=%s",(student_id,sid))
    con.commit(); cur.close(); con.close(); return jsonify({"ok":True})


# ── TEACHERS ──────────────────────────────────────────────────
@app.route("/api/teachers", methods=["GET"])
def api_get_teachers():
    sid = school_id_from_header()
    con = get_db(); cur = con.cursor()
    cur.execute("""SELECT u.username,u.is_class_teacher,u.class_id,u.stream_id,u.must_change_password,
                          c.class_name,st.stream_name
                   FROM users u
                   LEFT JOIN classes c ON u.class_id=c.id AND c.school_id=%s
                   LEFT JOIN streams st ON u.stream_id=st.id
                   WHERE u.role='teacher' AND u.school_id=%s ORDER BY u.username""",(sid,sid))
    teachers = to_dicts(cur.fetchall(),cur); result=[]
    for t in teachers:
        cur.execute("""SELECT sa.subject,sa.class_id,sa.stream_id,c.class_name,st.stream_name
                       FROM subject_assignments sa JOIN classes c ON sa.class_id=c.id
                       LEFT JOIN streams st ON sa.stream_id=st.id
                       WHERE sa.school_id=%s AND sa.username=%s""",(sid,t["username"]))
        result.append({**t,"assignments":to_dicts(cur.fetchall(),cur)})
    cur.close(); con.close(); return jsonify(result)

@app.route("/api/teachers", methods=["POST"])
def api_create_teacher():
    sid = school_id_from_header(); d = request.json
    username=d.get("username","").strip(); password=d.get("password","")
    if not username or not password: return jsonify({"ok":False,"error":"Username and password required"}),400
    con = get_db(); cur = con.cursor()
    try:
        cur.execute("INSERT INTO users(username,password,role,school_id,must_change_password) VALUES(%s,%s,'teacher',%s,1)",
                    (username,hash_password(password),sid))
        con.commit()
    except psycopg2.errors.UniqueViolation:
        con.rollback(); cur.close(); con.close()
        return jsonify({"ok":False,"error":"Username already exists"}),409
    cur.close(); con.close(); return jsonify({"ok":True})

@app.route("/api/teachers/<username>", methods=["DELETE"])
def api_delete_teacher(username):
    sid = school_id_from_header()
    con = get_db(); cur = con.cursor()
    cur.execute("DELETE FROM subject_assignments WHERE school_id=%s AND username=%s",(sid,username))
    cur.execute("DELETE FROM users WHERE username=%s AND role='teacher' AND school_id=%s",(username,sid))
    con.commit(); cur.close(); con.close(); return jsonify({"ok":True})

@app.route("/api/teachers/<username>/class_teacher", methods=["POST"])
def api_set_class_teacher(username):
    sid = school_id_from_header(); d = request.json
    is_ct=bool(d.get("is_class_teacher",False)); class_id=d.get("class_id") or None; stream_id=d.get("stream_id") or None
    if is_ct and not class_id: return jsonify({"ok":False,"error":"Class required"}),400
    con = get_db(); cur = con.cursor()
    cur.execute("UPDATE users SET is_class_teacher=%s,class_id=%s,stream_id=%s WHERE username=%s AND school_id=%s AND role='teacher'",
                (1 if is_ct else 0, class_id if is_ct else None, stream_id if is_ct else None, username, sid))
    con.commit(); cur.close(); con.close(); return jsonify({"ok":True})

@app.route("/api/assign_teacher", methods=["POST"])
def api_assign_teacher():
    sid = school_id_from_header(); d = request.json
    username=d.get("username",""); subject=d.get("subject","").lower().strip()
    class_id=d.get("class_id"); stream_id=d.get("stream_id") or None
    con = get_db(); cur = con.cursor()
    try:
        cur.execute("INSERT INTO subject_assignments(school_id,username,subject,class_id,stream_id) VALUES(%s,%s,%s,%s,%s)",
                    (sid,username,subject,class_id,stream_id))
        con.commit()
    except psycopg2.errors.UniqueViolation:
        con.rollback(); cur.close(); con.close(); return jsonify({"ok":False,"error":"Already assigned"}),409
    cur.close(); con.close(); return jsonify({"ok":True})

@app.route("/api/unassign_teacher", methods=["POST"])
def api_unassign_teacher():
    sid = school_id_from_header(); d = request.json
    username=d.get("username",""); subject=d.get("subject","").lower()
    class_id=d.get("class_id"); stream_id=d.get("stream_id") or None
    con = get_db(); cur = con.cursor()
    if stream_id:
        cur.execute("DELETE FROM subject_assignments WHERE school_id=%s AND username=%s AND subject=%s AND class_id=%s AND stream_id=%s",
                    (sid,username,subject,class_id,stream_id))
    else:
        cur.execute("DELETE FROM subject_assignments WHERE school_id=%s AND username=%s AND subject=%s AND class_id=%s AND stream_id IS NULL",
                    (sid,username,subject,class_id))
    con.commit(); cur.close(); con.close(); return jsonify({"ok":True})

# ── TERMS ──────────────────────────────────────────────────────
@app.route("/api/terms", methods=["GET"])
def api_get_terms():
    sid = school_id_from_header()
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM terms WHERE school_id=%s ORDER BY id DESC",(sid,))
    rows = to_dicts(cur.fetchall(),cur); cur.close(); con.close(); return jsonify(rows)

@app.route("/api/terms/active", methods=["GET"])
def api_active_term():
    sid = school_id_from_header(); t = get_active_term(sid)
    return jsonify({"ok":bool(t),"term":t})

@app.route("/api/terms", methods=["POST"])
def api_create_term():
    sid = school_id_from_header(); d = request.json
    label=d.get("label","").strip(); ca_count=int(d.get("ca_count",2))
    ca_weight=int(d.get("ca_weight",30)); ex_weight=int(d.get("exam_weight",70))
    if not label: return jsonify({"ok":False,"error":"Term label required"}),400
    if ca_weight+ex_weight!=100: return jsonify({"ok":False,"error":"Weights must sum to 100"}),400
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT id FROM terms WHERE school_id=%s AND status='open'",(sid,))
    if cur.fetchone(): cur.close(); con.close(); return jsonify({"ok":False,"error":"Close current term first"}),409
    cur.execute("INSERT INTO terms(school_id,label,ca_count,ca_weight,exam_weight,status) VALUES(%s,%s,%s,%s,%s,'open')",
                (sid,label,ca_count,ca_weight,ex_weight))
    con.commit(); cur.close(); con.close(); return jsonify({"ok":True})

@app.route("/api/terms/<int:tid>", methods=["PATCH"])
def api_update_term(tid):
    sid = school_id_from_header(); d = request.json or {}
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT status FROM terms WHERE id=%s AND school_id=%s",(tid,sid))
    row = cur.fetchone()
    if not row:
        cur.close(); con.close(); return jsonify({"ok":False,"error":"Term not found"}),404
    if row[0]=="closed":
        cur.close(); con.close(); return jsonify({"ok":False,"error":"Closed terms are locked and can't be edited"}),400

    fields=[]; vals=[]
    if d.get("label") is not None:
        label=d.get("label","").strip()
        if not label:
            cur.close(); con.close(); return jsonify({"ok":False,"error":"Term label required"}),400
        fields.append("label=%s"); vals.append(label)
    if d.get("ca_count") is not None:
        try: ca_count=int(d.get("ca_count"))
        except (TypeError,ValueError):
            cur.close(); con.close(); return jsonify({"ok":False,"error":"Invalid CA count"}),400
        if ca_count<1:
            cur.close(); con.close(); return jsonify({"ok":False,"error":"Number of CAs must be at least 1"}),400
        fields.append("ca_count=%s"); vals.append(ca_count)
    if d.get("ca_weight") is not None and d.get("exam_weight") is not None:
        try:
            ca_weight=int(d.get("ca_weight")); exam_weight=int(d.get("exam_weight"))
        except (TypeError,ValueError):
            cur.close(); con.close(); return jsonify({"ok":False,"error":"Invalid weights"}),400
        if ca_weight+exam_weight!=100:
            cur.close(); con.close(); return jsonify({"ok":False,"error":"Weights must sum to 100"}),400
        fields.append("ca_weight=%s"); vals.append(ca_weight)
        fields.append("exam_weight=%s"); vals.append(exam_weight)
    if not fields:
        cur.close(); con.close(); return jsonify({"ok":False,"error":"Nothing to update"}),400

    vals += [tid, sid]
    cur.execute(f"UPDATE terms SET {','.join(fields)} WHERE id=%s AND school_id=%s", vals)
    con.commit(); cur.close(); con.close()
    return jsonify({"ok":True})

@app.route("/api/terms/<int:tid>/close", methods=["POST"])
def api_close_term(tid):
    sid = school_id_from_header()
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT status FROM terms WHERE id=%s AND school_id=%s",(tid,sid))
    row = cur.fetchone()
    if not row: cur.close(); con.close(); return jsonify({"ok":False,"error":"Not found"}),404
    if row[0]=="closed": cur.close(); con.close(); return jsonify({"ok":False,"error":"Already closed"}),400
    cur.execute("UPDATE terms SET status='closed' WHERE id=%s AND school_id=%s",(tid,sid))
    con.commit(); cur.close(); con.close(); return jsonify({"ok":True})

# ── MARKS ─────────────────────────────────────────────────────
@app.route("/api/marks/ca", methods=["POST"])
def api_enter_ca():
    sid = school_id_from_header(); d = request.json
    username=d.get("username",""); subject=d.get("subject","").lower().strip()
    class_id=int(d.get("class_id")); stream_id=d.get("stream_id") or None
    student_id=int(d.get("student_id")); ca_name=d.get("ca_name",""); score=float(d.get("score"))
    if not (0<=score<=100): return jsonify({"ok":False,"error":"Score must be 0-100"}),400
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT role FROM users WHERE username=%s AND school_id=%s",(username,sid))
    u = cur.fetchone(); cur.close(); con.close()
    if not u: return jsonify({"ok":False,"error":"User not found"}),403
    if u[0]=="teacher" and not teacher_can_access(sid,username,subject,class_id,stream_id):
        return jsonify({"ok":False,"error":"Access denied"}),403
    term = get_active_term(sid)
    if not term: return jsonify({"ok":False,"error":"No active term"}),400
    con = get_db(); cur = con.cursor()
    cur.execute("""INSERT INTO ca_scores(school_id,student_id,subject,ca_name,score,entered_by,term_id)
                   VALUES(%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT(school_id,student_id,subject,ca_name,term_id)
                   DO UPDATE SET score=EXCLUDED.score,entered_by=EXCLUDED.entered_by""",
                (sid,student_id,subject,ca_name,score,username,term["id"]))
    con.commit(); cur.close(); con.close(); return jsonify({"ok":True})

@app.route("/api/marks/exam", methods=["POST"])
def api_enter_exam():
    sid = school_id_from_header(); d = request.json
    username=d.get("username",""); subject=d.get("subject","").lower().strip()
    class_id=int(d.get("class_id")); stream_id=d.get("stream_id") or None
    student_id=int(d.get("student_id")); score=float(d.get("score"))
    if not (0<=score<=100): return jsonify({"ok":False,"error":"Score must be 0-100"}),400
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT role FROM users WHERE username=%s AND school_id=%s",(username,sid))
    u = cur.fetchone(); cur.close(); con.close()
    if not u: return jsonify({"ok":False,"error":"User not found"}),403
    if u[0]=="teacher" and not teacher_can_access(sid,username,subject,class_id,stream_id):
        return jsonify({"ok":False,"error":"Access denied"}),403
    term = get_active_term(sid)
    if not term: return jsonify({"ok":False,"error":"No active term"}),400
    con = get_db(); cur = con.cursor()
    cur.execute("""INSERT INTO exam_scores(school_id,student_id,subject,score,entered_by,term_id)
                   VALUES(%s,%s,%s,%s,%s,%s)
                   ON CONFLICT(school_id,student_id,subject,term_id)
                   DO UPDATE SET score=EXCLUDED.score,entered_by=EXCLUDED.entered_by""",
                (sid,student_id,subject,score,username,term["id"]))
    con.commit(); cur.close(); con.close(); return jsonify({"ok":True})


# ── CONFIG ─────────────────────────────────────────────────────
@app.route("/api/config", methods=["GET"])
def api_config():
    sid = school_id_from_header(); term = get_active_term(sid)
    subjects = get_subjects(sid); subj_map = get_subject_map(sid)
    info = {k: get_config_val(sid,k,"") for k in ["school_name","phone","email","admin_phone","motto","logo_path"]}
    return jsonify({"allowed_subjects":subjects,"subject_abbr":subj_map,"active_term":term,
                    "ca_count":term["ca_count"] if term else 2,"school_name":info.get("school_name","School Name"),
                    "school_info":info,"grade_rules":get_grade_rules(sid)})

@app.route("/api/config/school_name", methods=["POST"])
def api_set_school_name():
    sid = school_id_from_header(); name = request.json.get("school_name","").strip()
    if not name: return jsonify({"ok":False,"error":"Name cannot be empty"}),400
    set_config_val(sid,"school_name",name); return jsonify({"ok":True})

@app.route("/api/config/reg_code", methods=["GET"])
def api_get_reg_code():
    sid = school_id_from_header()
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT reg_code FROM schools WHERE id=%s", (sid,))
    row = cur.fetchone(); cur.close(); con.close()
    return jsonify({"reg_code": row[0] if row else ""})

@app.route("/api/config/reg_code", methods=["POST"])
def api_set_reg_code():
    sid = school_id_from_header()
    new_code = ((request.json or {}).get("reg_code") or "").strip()
    if not valid_reg_code(new_code):
        return jsonify({"ok":False,"error":"Registration code must be 3-32 characters: letters, numbers, underscore or hyphen only"}), 400
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT id FROM schools WHERE LOWER(reg_code)=LOWER(%s) AND id!=%s", (new_code, sid))
    if cur.fetchone():
        cur.close(); con.close()
        return jsonify({"ok":False,"error":"That registration code is already taken by another school. Please choose a different one."}), 409
    cur.execute("UPDATE schools SET reg_code=%s WHERE id=%s", (new_code, sid))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok":True,"reg_code":new_code})

@app.route("/api/config/school_info", methods=["POST"])
def api_set_school_info():
    sid = school_id_from_header(); d = request.json
    for key in ["school_name","phone","email","admin_phone","motto"]:
        val = d.get(key)
        if val is not None: set_config_val(sid, key, val.strip())
    return jsonify({"ok":True})

# ── REPORT CARD ───────────────────────────────────────────────
@app.route("/api/report/<int:student_id>", methods=["GET"])
def api_report(student_id):
    sid = school_id_from_header(); subjects = get_subjects(sid)
    term_id = request.args.get("term_id")
    con = get_db(); cur = con.cursor()
    cur.execute("""SELECT s.id,s.name,s.class_id,s.stream_id,c.class_name,st.stream_name
                   FROM students s JOIN classes c ON s.class_id=c.id
                   LEFT JOIN streams st ON s.stream_id=st.id
                   WHERE s.id=%s AND s.school_id=%s""",(student_id,sid))
    row = cur.fetchone(); student = to_dict(row,cur) if row else None
    cur.close(); con.close()
    if not student: return jsonify({"ok":False,"error":"Student not found"}),404
    term = get_term_by_id(sid,int(term_id)) if term_id else get_active_term(sid)
    if not term: return jsonify({"ok":False,"error":"No term available"}),400
    tid=term["id"]; ca_count=term["ca_count"]; ca_w=term["ca_weight"]; ex_w=term["exam_weight"]
    class_id=student["class_id"]; stream_id=student["stream_id"]

    class_rows, class_rank_map, stream_rank_map, scores_bulk = get_class_report_data(
        sid, tid, class_id, stream_id, subjects, ca_w, ex_w)
    subject_rank_maps = {subj: get_subject_rank_map(class_rows, subj) for subj in subjects}

    c_entry = class_rank_map.get(student_id)
    c_pos   = c_entry["position"] if c_entry else "-"
    c_total = len(class_rows)
    s_pos = s_total = None
    if stream_id and stream_rank_map is not None:
        s_entry = stream_rank_map.get(student_id)
        s_pos   = s_entry["position"] if s_entry else "-"
        s_total = len(stream_rank_map)

    student_finals = c_entry["finals"] if c_entry else compute_student_finals(scores_bulk, student_id, subjects, ca_w, ex_w)
    avg = c_entry["average"] if c_entry else round(compute_average_from_finals(student_finals), 2)
    student_scores = scores_bulk.get(student_id, {})

    rows = []
    for subject in subjects:
        entry     = student_scores.get(subject, {})
        ca_map    = entry.get("ca", {})
        ca_scores = {f"CA{i}": ca_map.get(f"CA{i}") for i in range(1,ca_count+1)}
        exam_val  = entry.get("exam")
        final_val = student_finals.get(subject)
        subj_pos  = subject_rank_maps[subject].get(student_id, "-") if final_val is not None else "-"
        rows.append({"subject":subject,"ca":ca_scores,"exam":exam_val,
                     "final":round(final_val,1) if final_val is not None else None,
                     "grade":get_grade(sid,final_val) if final_val is not None else "-","position":subj_pos})
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM remarks WHERE school_id=%s AND student_id=%s AND term_id=%s",(sid,student_id,tid))
    rmk_row = cur.fetchone(); rmk = to_dict(rmk_row,cur) if rmk_row else None
    cur.close(); con.close()
    return jsonify({"ok":True,"student":student,"term":term,"rows":rows,
                    "average":avg,"grade":get_grade(sid,avg),
                    "class_position":c_pos,"class_total":c_total,
                    "stream_position":s_pos,"stream_total":s_total,
                    "class_teacher_remark":rmk["class_teacher_remark"] if rmk else "",
                    "head_remark":rmk["head_remark"] if rmk else "",
                    "ca_count":ca_count,"ca_weight":term["ca_weight"],"exam_weight":term["exam_weight"]})

# ── REMARKS ───────────────────────────────────────────────────
@app.route("/api/remarks", methods=["POST"])
def api_remarks():
    sid = school_id_from_header(); d = request.json
    username=d.get("username",""); role=d.get("role",""); is_ct=d.get("is_class_teacher",False)
    student_id=int(d.get("student_id")); remark=d.get("remark","").strip()
    term = get_active_term(sid)
    if not term: return jsonify({"ok":False,"error":"No active term"}),400
    tid=term["id"]
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT class_id FROM students WHERE id=%s AND school_id=%s",(student_id,sid))
    student = cur.fetchone()
    if not student: cur.close(); con.close(); return jsonify({"ok":False,"error":"Student not found"}),404
    if role=="admin": field="head_remark"
    elif role=="teacher" and is_ct:
        cur.execute("SELECT class_id FROM users WHERE username=%s AND school_id=%s AND is_class_teacher=1",(username,sid))
        u = cur.fetchone()
        if not u or u[0]!=student[0]:
            cur.close(); con.close(); return jsonify({"ok":False,"error":"Not your class"}),403
        field="class_teacher_remark"
    else:
        cur.close(); con.close(); return jsonify({"ok":False,"error":"Not allowed"}),403
    cur.execute(f"""INSERT INTO remarks(school_id,student_id,term_id,{field}) VALUES(%s,%s,%s,%s)
                    ON CONFLICT(school_id,student_id,term_id) DO UPDATE SET {field}=EXCLUDED.{field}""",
                (sid,student_id,tid,remark))
    con.commit(); cur.close(); con.close(); return jsonify({"ok":True})

# ── RANKINGS ──────────────────────────────────────────────────
@app.route("/api/ranking/subject", methods=["GET"])
def api_subject_ranking():
    sid=school_id_from_header(); subject=request.args.get("subject","").lower()
    class_id=request.args.get("class_id"); stream_id=request.args.get("stream_id") or None
    assess=request.args.get("assess","exam"); term_id=request.args.get("term_id")
    if not term_id:
        term=get_active_term(sid)
        if not term: return jsonify([])
        term_id=term["id"]
    else: term_id=int(term_id)
    if stream_id: stream_id=int(stream_id)
    if class_id:  class_id=int(class_id)
    studs=get_students_in_scope(sid,class_id,stream_id)
    if not studs: return jsonify([])
    student_ids=[s["id"] for s in studs]
    con=get_db(); cur=con.cursor()
    if assess=="exam":
        cur.execute("SELECT student_id,score FROM exam_scores WHERE school_id=%s AND student_id=ANY(%s) AND subject=%s AND term_id=%s",
                    (sid,student_ids,subject,term_id))
    else:
        cur.execute("SELECT student_id,score FROM ca_scores WHERE school_id=%s AND student_id=ANY(%s) AND subject=%s AND ca_name=%s AND term_id=%s",
                    (sid,student_ids,subject,assess,term_id))
    score_map=dict(cur.fetchall()); cur.close(); con.close()
    name_map={s["id"]:s["name"] for s in studs}
    rows=[{"id":stid,"name":name_map[stid],"score":round(sc,2),"grade":get_grade(sid,sc)}
          for stid,sc in score_map.items()]
    _assign_positions(rows,"score"); return jsonify(rows)



# ── ANALYTICS ROUTES ───────────────────────────────────────────
@app.route("/api/analytics/overview", methods=["GET"])
@subscription_required
def api_analytics_overview():
    sid = school_id_from_header()
    username  = request.args.get("username", "")
    role      = request.args.get("role", "")
    class_id  = request.args.get("class_id") or None
    stream_id = request.args.get("stream_id") or None
    class_id  = int(class_id) if class_id else None
    stream_id = int(stream_id) if stream_id else None

    # A class teacher can only ever see their own class/stream — enforced
    # server-side regardless of what the request asked for, since this is
    # the same trust boundary marks entry already relies on.
    if role == "teacher":
        con = get_db(); cur = con.cursor()
        cur.execute("SELECT is_class_teacher,class_id,stream_id FROM users WHERE username=%s AND school_id=%s",
                    (username, sid))
        row = cur.fetchone(); cur.close(); con.close()
        if not row or not row[0]:
            return jsonify({"ok": False, "error": "Not a class teacher"}), 403
        if row[1] is None:
            return jsonify({"ok": False, "error": "No class assigned"}), 403
        class_id, stream_id = row[1], row[2]

    subjects = get_subjects(sid)
    points, name_map = _compute_overall_series(sid, class_id, stream_id, subjects)
    result = _build_common_cards(points, name_map, sid)
    if points:
        best_subj, weak_subj = _best_weakest_subject(
            sid, class_id, stream_id, subjects, points[-1]["term_id"], points[-1]["assess"])
        result["best_subject"] = best_subj
        result["weakest_subject"] = weak_subj
    else:
        result["best_subject"] = None
        result["weakest_subject"] = None
    return jsonify({"ok": True, **result})

@app.route("/api/analytics/subject", methods=["GET"])
@subscription_required
def api_analytics_subject():
    sid       = school_id_from_header()
    username  = request.args.get("username", "")
    role      = request.args.get("role", "")
    subject   = request.args.get("subject", "").lower().strip()
    class_id  = request.args.get("class_id")
    stream_id = request.args.get("stream_id") or None
    if not subject or not class_id:
        return jsonify({"ok": False, "error": "subject and class_id required"}), 400
    class_id  = int(class_id)
    stream_id = int(stream_id) if stream_id else None
    if role == "teacher" and not teacher_can_access(sid, username, subject, class_id, stream_id):
        return jsonify({"ok": False, "error": "Access denied"}), 403

    points, name_map = _compute_subject_series(sid, class_id, stream_id, subject)
    result = _build_common_cards(points, name_map, sid)
    return jsonify({"ok": True, **result})

@app.route("/api/analytics/dashboard_classes", methods=["GET"])
@subscription_required
def api_analytics_dashboard_classes():
    sid = school_id_from_header()
    subjects = get_subjects(sid)
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT id,class_name FROM classes WHERE school_id=%s ORDER BY class_name", (sid,))
    classes = to_dicts(cur.fetchall(), cur); cur.close(); con.close()
    results = []
    for c in classes:
        points, _ = _compute_overall_series(sid, c["id"], None, subjects)
        if points:
            results.append({"class_id": c["id"], "class_name": c["class_name"], "average": points[-1]["avg"]})
    if not results:
        return jsonify({"ok": True, "best": None, "weakest": None})
    best = max(results, key=lambda r: r["average"])
    weakest = min(results, key=lambda r: r["average"])
    return jsonify({"ok": True, "best": best, "weakest": weakest})

# ── SCORE SHEETS ──────────────────────────────────────────────
@app.route("/api/scoresheet", methods=["GET"])
def api_scoresheet():
    sid=school_id_from_header(); subjects=get_subjects(sid)
    mode=request.args.get("mode","ca"); class_id=request.args.get("class_id")
    stream_id=request.args.get("stream_id") or None; ca_name=request.args.get("ca_name","CA1")
    term_id=request.args.get("term_id")
    if not term_id:
        term=get_active_term(sid)
        if not term: return jsonify({"subjects":[],"results":[]})
        term_id=term["id"]
    else: term_id=int(term_id)
    if class_id:  class_id=int(class_id)
    if stream_id: stream_id=int(stream_id)

    studs=get_students_in_scope(sid,class_id,stream_id)
    if not studs:
        return jsonify({"subjects":subjects,"results":[]})
    student_ids=[s["id"] for s in studs]

    # Batch-fetch all needed scores in a handful of queries (one DB connection),
    # instead of opening a new connection per student per subject.
    con=get_db(); cur=con.cursor()
    ca_scores={}; exam_scores={}; ca_avgs={}; term=None
    if mode=="ca":
        cur.execute("""SELECT student_id,subject,score FROM ca_scores
                       WHERE school_id=%s AND term_id=%s AND ca_name=%s AND student_id=ANY(%s)""",
                    (sid,term_id,ca_name,student_ids))
        for student_id,subject,score in cur.fetchall(): ca_scores[(student_id,subject)]=score
    elif mode=="exam":
        cur.execute("""SELECT student_id,subject,score FROM exam_scores
                       WHERE school_id=%s AND term_id=%s AND student_id=ANY(%s)""",
                    (sid,term_id,student_ids))
        for student_id,subject,score in cur.fetchall(): exam_scores[(student_id,subject)]=score
    elif mode=="terminal":
        term=get_term_by_id(sid,term_id)
        if not term:
            cur.close(); con.close()
            return jsonify({"subjects":subjects,"results":[]})
        cur.execute("""SELECT student_id,subject,score FROM exam_scores
                       WHERE school_id=%s AND term_id=%s AND student_id=ANY(%s)""",
                    (sid,term_id,student_ids))
        for student_id,subject,score in cur.fetchall(): exam_scores[(student_id,subject)]=score
        cur.execute("""SELECT student_id,subject,AVG(score) FROM ca_scores
                       WHERE school_id=%s AND term_id=%s AND student_id=ANY(%s)
                       GROUP BY student_id,subject""",
                    (sid,term_id,student_ids))
        for student_id,subject,avg_score in cur.fetchall(): ca_avgs[(student_id,subject)]=float(avg_score)
    cur.close(); con.close()

    grade_rules=get_grade_rules(sid)  # fetched once, not per row
    def grade_for(score):
        if score is None: return "-"
        for r in grade_rules:
            if score>=r["min_score"]: return r["grade"]
        return "F"

    results=[]
    for s in studs:
        row={"id":s["id"],"name":s["name"],"stream_name":s.get("stream_name"),"scores":{},"total":0,"count":0}
        for subject in subjects:
            score=None
            if mode=="ca":
                score=ca_scores.get((s["id"],subject))
            elif mode=="exam":
                score=exam_scores.get((s["id"],subject))
            elif mode=="terminal":
                exam=exam_scores.get((s["id"],subject)); ca_avg=ca_avgs.get((s["id"],subject))
                if exam is not None and ca_avg is not None:
                    score=round((ca_avg/100)*term["ca_weight"] + (exam/100)*term["exam_weight"],1)
            row["scores"][subject]=score
            if score is not None: row["total"]+=score; row["count"]+=1
        row["average"]=round(row["total"]/row["count"],2) if row["count"] else 0
        row["grade"]=grade_for(row["average"]); results.append(row)
    _assign_positions(results,"average")
    return jsonify({"subjects":subjects,"results":results})


# ── ANNOUNCEMENTS ─────────────────────────────────────────────
@app.route("/api/announcements", methods=["GET"])
def api_get_announcements():
    sid=school_id_from_header(); student_id=request.args.get("student_id")
    con=get_db(); cur=con.cursor()
    if student_id:
        stid=int(student_id)
        cur.execute("SELECT class_id FROM students WHERE id=%s AND school_id=%s",(stid,sid))
        row=cur.fetchone()
        if not row: cur.close(); con.close(); return jsonify([])
        cur.execute("SELECT class_name FROM classes WHERE id=%s AND school_id=%s",(row[0],sid))
        cls_row=cur.fetchone(); class_name=cls_row[0] if cls_row else ""
        cur.execute("""SELECT a.id,a.title,a.body,a.target_classes,a.posted_by,CAST(a.posted_at AS TEXT),
                              CASE WHEN ar.student_id IS NOT NULL THEN 1 ELSE 0 END as is_read
                       FROM announcements a
                       LEFT JOIN announcement_reads ar ON ar.announcement_id=a.id AND ar.student_id=%s
                       WHERE a.school_id=%s AND (a.target_classes='all' OR a.target_classes LIKE %s)
                       ORDER BY a.posted_at DESC""",(stid,sid,f"%{class_name}%"))
    else:
        cur.execute("SELECT id,title,body,target_classes,posted_by,CAST(posted_at AS TEXT),0 as is_read FROM announcements WHERE school_id=%s ORDER BY posted_at DESC",(sid,))
    rows=to_dicts(cur.fetchall(),cur); cur.close(); con.close(); return jsonify(rows)

@app.route("/api/announcements", methods=["POST"])
@subscription_required
def api_post_announcement():
    sid=school_id_from_header(); d=request.json
    title=d.get("title","").strip(); body=d.get("body","").strip()
    posted_by=d.get("posted_by",""); target_classes=(d.get("target_classes") or "all").strip() or "all"
    if not title or not body: return jsonify({"ok":False,"error":"Title and body required"}),400
    con=get_db(); cur=con.cursor()
    cur.execute("INSERT INTO announcements(school_id,title,body,target_classes,posted_by) VALUES(%s,%s,%s,%s,%s) RETURNING id",
                (sid,title,body,target_classes,posted_by))
    new_id=cur.fetchone()[0]; con.commit(); cur.close(); con.close()
    return jsonify({"ok":True,"id":new_id})

@app.route("/api/announcements/<int:aid>", methods=["DELETE"])
def api_delete_announcement(aid):
    sid=school_id_from_header()
    con=get_db(); cur=con.cursor()
    cur.execute("DELETE FROM announcements WHERE id=%s AND school_id=%s",(aid,sid))
    con.commit(); cur.close(); con.close(); return jsonify({"ok":True})

@app.route("/api/announcements/<int:aid>/read", methods=["POST"])
def api_mark_announcement_read(aid):
    student_id=request.json.get("student_id")
    if not student_id: return jsonify({"ok":False,"error":"student_id required"}),400
    con=get_db(); cur=con.cursor()
    cur.execute("INSERT INTO announcement_reads(announcement_id,student_id) VALUES(%s,%s) ON CONFLICT DO NOTHING",(aid,int(student_id)))
    con.commit(); cur.close(); con.close(); return jsonify({"ok":True})

# ── RESULTS PUBLISHING ────────────────────────────────────────
@app.route("/api/results/status", methods=["GET"])
def api_results_status():
    sid=school_id_from_header(); term_id=request.args.get("term_id")
    if not term_id:
        term=get_active_term(sid)
        if not term: return jsonify({"published":False,"term":None,"term_id":None})
        term_id=term["id"]
    else: term_id=int(term_id)
    con=get_db(); cur=con.cursor()
    cur.execute("SELECT published FROM results_published WHERE school_id=%s AND term_id=%s",(sid,term_id))
    row=cur.fetchone(); cur.close(); con.close()
    return jsonify({"published":bool(row[0]) if row else False,"term":get_term_by_id(sid,term_id),"term_id":term_id})

@app.route("/api/results/toggle", methods=["POST"])
def api_toggle_results():
    sid=school_id_from_header(); d=request.json
    term_id=d.get("term_id"); publish=bool(d.get("publish",True))
    if publish and not is_subscribed(sid):
        return jsonify({"ok": False, "error": "subscription_required",
                        "message": "Publishing results requires an active subscription."}), 402
    if not term_id: return jsonify({"ok":False,"error":"term_id required"}),400
    con=get_db(); cur=con.cursor()
    cur.execute("""INSERT INTO results_published(school_id,term_id,published) VALUES(%s,%s,%s)
                   ON CONFLICT(school_id,term_id) DO UPDATE SET published=EXCLUDED.published""",
                (sid,int(term_id),1 if publish else 0))
    con.commit(); cur.close(); con.close(); return jsonify({"ok":True,"published":publish})

# ── PARENT PORTAL ─────────────────────────────────────────────
@app.route("/api/parent/terms", methods=["GET"])
def api_parent_terms():
    sid=school_id_from_header()
    con=get_db(); cur=con.cursor()
    cur.execute("""SELECT t.id,t.label,t.ca_count,t.ca_weight,t.exam_weight,t.status
                   FROM terms t JOIN results_published rp ON rp.term_id=t.id AND rp.school_id=t.school_id
                   WHERE t.school_id=%s AND rp.published=1 ORDER BY t.id ASC""",(sid,))
    rows=to_dicts(cur.fetchall(),cur); cur.close(); con.close(); return jsonify(rows)

@app.route("/api/parent/results", methods=["GET"])
def api_parent_results():
    sid=school_id_from_header(); subjects=get_subjects(sid)
    student_id=request.args.get("student_id"); term_id=request.args.get("term_id"); assess=request.args.get("assess")
    if not student_id: return jsonify({"ok":False,"error":"student_id required"}),400
    if not term_id:
        term=get_active_term(sid)
        if not term: return jsonify({"ok":False,"error":"No active term"}),400
        term_id=term["id"]
    else: term_id=int(term_id)
    con=get_db(); cur=con.cursor()
    cur.execute("SELECT published FROM results_published WHERE school_id=%s AND term_id=%s",(sid,term_id))
    row=cur.fetchone(); cur.close(); con.close()
    if not row or not row[0]: return jsonify({"ok":False,"error":"Results not yet published"}),403
    stid=int(student_id); term=get_term_by_id(sid,term_id)
    con=get_db(); cur=con.cursor()
    cur.execute("""SELECT s.id,s.name,s.class_id,s.stream_id,c.class_name,st.stream_name
                   FROM students s JOIN classes c ON s.class_id=c.id LEFT JOIN streams st ON s.stream_id=st.id
                   WHERE s.id=%s AND s.school_id=%s""",(stid,sid))
    row=cur.fetchone(); student=to_dict(row,cur) if row else None; cur.close(); con.close()
    if not student: return jsonify({"ok":False,"error":"Student not found"}),404
    ca_count=term["ca_count"]; ca_w=term["ca_weight"]; ex_w=term["exam_weight"]
    class_id=student["class_id"]; stream_id=student["stream_id"]

    class_rows, class_rank_map, stream_rank_map, scores_bulk = get_class_report_data(
        sid, term_id, class_id, stream_id, subjects, ca_w, ex_w)
    class_ids = [r["id"] for r in class_rows]
    student_scores = scores_bulk.get(stid, {})

    results=[]
    if assess:
        assess_rank_maps={}
        for subject in subjects:
            entry=student_scores.get(subject,{})
            ca_map=entry.get("ca",{})
            ca_scores={f"CA{i}": ca_map.get(f"CA{i}") for i in range(1,ca_count+1)}
            exam_val=entry.get("exam")
            score=exam_val if assess=="exam" else ca_map.get(assess)
            if score is None: continue
            if subject not in assess_rank_maps:
                assess_rank_maps[subject]=get_subject_assess_rank_map(scores_bulk,class_ids,subject,assess)
            pos=assess_rank_maps[subject].get(stid,"-")
            results.append({"subject":subject,"ca":ca_scores,"exam":exam_val,"score":score,
                            "grade":get_grade(sid,score),"position":pos})
    else:
        subject_rank_maps={subj: get_subject_rank_map(class_rows, subj) for subj in subjects}
        student_finals = class_rank_map.get(stid,{}).get("finals") or compute_student_finals(scores_bulk,stid,subjects,ca_w,ex_w)
        for subject in subjects:
            entry=student_scores.get(subject,{})
            ca_map=entry.get("ca",{})
            ca_scores={f"CA{i}": ca_map.get(f"CA{i}") for i in range(1,ca_count+1)}
            exam_val=entry.get("exam")
            if not ca_map and exam_val is None: continue
            final_val=student_finals.get(subject)
            subj_pos=subject_rank_maps[subject].get(stid,"-") if final_val is not None else "-"
            results.append({"subject":subject,"ca":ca_scores,"exam":exam_val,
                            "final":round(final_val,1) if final_val is not None else None,
                            "grade":get_grade(sid,final_val) if final_val is not None else "-","position":subj_pos})

    if assess:
        # Rank by THIS assessment's own average across subjects, not the term's
        # weighted final. Finals are only computable once both CA and exam marks
        # exist, so before the exam is entered every student's final average is
        # 0 — that ties the whole class and everyone was showing up as "1st".
        stream_id_map = {r["id"]: r.get("stream_id") for r in class_rows}
        assess_scores=[]
        for cid in class_ids:
            student_data = scores_bulk.get(cid, {})
            vals=[]
            for subject in subjects:
                entry = student_data.get(subject, {})
                v = entry.get("exam") if assess=="exam" else (entry.get("ca") or {}).get(assess)
                if v is not None: vals.append(v)
            if vals: assess_scores.append({"id":cid,"score":sum(vals)/len(vals)})
        _assign_positions(assess_scores,"score")
        assess_pos_map={r["id"]:r["position"] for r in assess_scores}
        c_pos = assess_pos_map.get(stid,"-")
        c_total = len(assess_scores)
        s_pos=s_total=None
        if stream_id:
            stream_scores=[dict(r) for r in assess_scores if stream_id_map.get(r["id"])==stream_id]
            _assign_positions(stream_scores,"score")
            stream_pos_map={r["id"]:r["position"] for r in stream_scores}
            s_pos = stream_pos_map.get(stid,"-")
            s_total = len(stream_scores)
        if results:
            scores_only=[r["score"] for r in results if r.get("score") is not None]
            avg=round(sum(scores_only)/len(scores_only),2) if scores_only else 0
        else:
            avg = 0
    else:
        c_entry=class_rank_map.get(stid)
        c_pos=c_entry["position"] if c_entry else "-"
        c_total=len(class_rows)
        s_pos=s_total=None
        if stream_id and stream_rank_map is not None:
            s_entry=stream_rank_map.get(stid)
            s_pos=s_entry["position"] if s_entry else "-"
            s_total=len(stream_rank_map)
        avg = c_entry["average"] if c_entry else round(compute_average_from_finals(compute_student_finals(scores_bulk,stid,subjects,ca_w,ex_w)),2)
    return jsonify({"ok":True,"student":student,"term":term,"results":results,"ca_count":ca_count,
                    "average":avg,"grade":get_grade(sid,avg),
                    "class_position":c_pos,"class_total":c_total,
                    "stream_position":s_pos,"stream_total":s_total,"assess":assess})

# ── PLATFORM ANNOUNCEMENTS (school-side) ──────────────────────
@app.route("/api/platform_announcements", methods=["GET"])
def api_platform_announcements():
    sid=school_id_from_header()
    con=get_db(); cur=con.cursor()
    cur.execute("""SELECT pa.id,pa.title,pa.body,CAST(pa.posted_at AS TEXT) as posted_at,
                          CASE WHEN par.school_id IS NOT NULL THEN 1 ELSE 0 END AS is_read
                   FROM platform_announcements pa
                   LEFT JOIN platform_announcement_reads par ON par.announcement_id=pa.id AND par.school_id=%s
                   WHERE pa.target='all' OR pa.target=%s
                   ORDER BY pa.posted_at DESC""",(sid,str(sid)))
    rows=to_dicts(cur.fetchall(),cur); cur.close(); con.close(); return jsonify(rows)

@app.route("/api/platform_announcements/<int:aid>/read", methods=["POST"])
def api_platform_announcement_read(aid):
    sid=school_id_from_header()
    con=get_db(); cur=con.cursor()
    cur.execute("INSERT INTO platform_announcement_reads(announcement_id,school_id) VALUES(%s,%s) ON CONFLICT DO NOTHING",(aid,sid))
    con.commit(); cur.close(); con.close(); return jsonify({"ok":True})

@app.route("/api/subscription/status", methods=["GET"])
def api_subscription_status():
    sid = school_id_from_header()
    _expire_stale_payment_requests(sid)
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT subscription_exempt, subscription_status, subscription_plan, subscription_expires_at FROM schools WHERE id=%s", (sid,))
    row = cur.fetchone()
    if not row:
        cur.close(); con.close(); return jsonify({"ok": False}), 404
    exempt, status, plan, expires_at = row

    cur.execute("""SELECT id, plan, claimed_amount, transaction_id, phone_used,
                          CAST(payment_date AS TEXT), note, status, CAST(submitted_at AS TEXT), decision_note
                   FROM payment_requests WHERE school_id=%s ORDER BY id DESC LIMIT 1""", (sid,))
    req_row = cur.fetchone(); cur.close(); con.close()

    pending_request = None
    last_decision = None
    if req_row:
        (rid, rplan, ramount, rtxn, rphone, rdate, rnote, rstatus, rsubmitted, rdecision_note) = req_row
        if rstatus == "pending":
            pending_request = {"id": rid, "plan": rplan, "claimed_amount": ramount,
                                "transaction_id": rtxn, "phone_used": rphone,
                                "payment_date": rdate, "note": rnote, "submitted_at": rsubmitted}
        elif rstatus == "expired":
            last_decision = {"status": "expired",
                              "note": "This payment request expired because it was not verified within 48 hours. "
                                      "If you already paid, contact support. Otherwise, submit a new payment request."}
        elif rstatus == "rejected":
            last_decision = {"status": "rejected", "note": rdecision_note}

    return jsonify({"ok": True, "active": is_subscribed(sid), "exempt": bool(exempt),
                     "plan": plan, "status": status,
                     "expires_at": expires_at.isoformat() if expires_at else None,
                     "plans": SUBSCRIPTION_PLANS,
                     "payment_info": _platform_payment_config(),
                     "pending_request": pending_request,
                     "last_decision": last_decision})
@app.route("/api/subscription/select_free", methods=["POST"])
def api_select_free_plan():
    sid = school_id_from_header()
    con = get_db(); cur = con.cursor()
    cur.execute("""UPDATE schools SET subscription_status='active', subscription_plan='free',
                   subscription_expires_at=%s WHERE id=%s""",
                (datetime.utcnow() + timedelta(days=SUBSCRIPTION_PLANS["free"]["days"]), sid))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok": True})

@app.route("/api/subscription/request", methods=["POST"])
def api_submit_payment_request():
    sid = school_id_from_header()
    _expire_stale_payment_requests(sid)
    d = request.json or {}
    plan = d.get("plan", "")
    if plan not in SUBSCRIPTION_PLANS or plan == "free":
        return jsonify({"ok": False, "error": "Invalid plan"}), 400
    txn_id  = (d.get("transaction_id") or "").strip()
    phone   = (d.get("phone_used") or "").strip()
    pay_date= (d.get("payment_date") or "").strip()
    note    = (d.get("note") or "").strip()
    try:
        amount = float(d.get("claimed_amount"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Amount paid is required"}), 400
    if not txn_id:   return jsonify({"ok": False, "error": "Transaction ID is required"}), 400
    if not phone:    return jsonify({"ok": False, "error": "Phone number used is required"}), 400
    if amount <= 0:  return jsonify({"ok": False, "error": "Amount paid must be greater than zero"}), 400
    if not pay_date: return jsonify({"ok": False, "error": "Payment date is required"}), 400

    con = get_db(); cur = con.cursor()

    # Abuse guard: counts every submission attempt (any status) in the last
    # 24h, so rapid cancel-and-resubmit cycling still counts against the cap.
    cur.execute("SELECT COUNT(*) FROM payment_requests WHERE school_id=%s AND submitted_at > NOW() - INTERVAL '24 hours'", (sid,))
    if cur.fetchone()[0] >= 5:
        cur.close(); con.close()
        return jsonify({"ok": False, "error": "Too many verification requests. Please contact support if you continue experiencing problems."}), 429

    cur.execute("SELECT id FROM payment_requests WHERE school_id=%s AND status='pending'", (sid,))
    if cur.fetchone():
        cur.close(); con.close()
        return jsonify({"ok": False, "error": "You already have a payment request pending verification. Cancel it below before submitting a new one."}), 409
    try:
        cur.execute("""INSERT INTO payment_requests(school_id,plan,claimed_amount,transaction_id,phone_used,payment_date,note,status,submitted_by)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,'pending',%s) RETURNING id""",
                    (sid, plan, amount, txn_id, phone, pay_date, note, d.get("username", "")))
        new_id = cur.fetchone()[0]
        cur.execute("UPDATE schools SET subscription_status='pending' WHERE id=%s", (sid,))
        con.commit()
    except psycopg2.errors.UniqueViolation:
        con.rollback(); cur.close(); con.close()
        return jsonify({"ok": False, "error": "This transaction ID has already been submitted. If you believe this is an error, contact support."}), 409
    cur.close(); con.close()
    return jsonify({"ok": True, "id": new_id})

@app.route("/api/subscription/request/cancel", methods=["POST"])
def api_cancel_payment_request():
    sid = school_id_from_header()
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT id FROM payment_requests WHERE school_id=%s AND status='pending' ORDER BY id DESC LIMIT 1", (sid,))
    row = cur.fetchone()
    if not row:
        cur.close(); con.close(); return jsonify({"ok": False, "error": "No pending request to cancel"}), 404
    cur.execute("UPDATE payment_requests SET status='cancelled', decided_at=NOW() WHERE id=%s", (row[0],))
    cur.execute("UPDATE schools SET subscription_status='inactive' WHERE id=%s AND subscription_status='pending'", (sid,))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok": True})

# ── PDF ────────────────────────────────────────────────────────
from reportlab.lib.pagesizes import A4, A3, landscape
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm

def _get_logo_element(school_id, max_h=2*cm):
    logo_data = get_config_val(school_id, "logo_data", "")
    if logo_data:
        try:
            raw = base64.b64decode(logo_data)
            img = Image(io.BytesIO(raw)); img.drawHeight=max_h; img.drawWidth=max_h; return img
        except: pass
    # Fallback for any older logo still sitting on disk (e.g. one committed to Git)
    path = get_config_val(school_id,"logo_path","")
    if path and not path.startswith("api/logo/"):
        full = os.path.join(BASE_DIR, path)
        if os.path.exists(full):
            try:
                img=Image(full); img.drawHeight=max_h; img.drawWidth=max_h; return img
            except: pass
    return None

def _esc(s):
    return str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

def _school_header_story(school_id, styles, title_text, subtitle_text=""):
    story=[]; H_BG=colors.HexColor("#1A6FA8")
    t_s=ParagraphStyle("T",parent=styles["Title"],fontSize=16,textColor=H_BG,spaceAfter=2,alignment=1)
    s_s=ParagraphStyle("S",parent=styles["Normal"],fontSize=9,alignment=1,spaceAfter=4)
    motto=get_config_val(school_id,"motto",""); sname=get_school_name(school_id)
    logo=_get_logo_element(school_id,1.8*cm)
    if logo:
        name_para=Paragraph(f"<b>{sname}</b>",t_s)
        sub_para=Paragraph(motto,s_s) if motto else None
        inner=[[logo,[name_para]+([sub_para] if sub_para else [])]]
        tbl=Table(inner,colWidths=[2.2*cm,None])
        tbl.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"MIDDLE"),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),6)]))
        story.append(tbl)
    else:
        story.append(Paragraph(sname,t_s))
        if motto: story.append(Paragraph(f'<i>"{motto}"</i>',s_s))
    if title_text: story.append(Paragraph(title_text,s_s))
    if subtitle_text: story.append(Paragraph(subtitle_text,s_s))
    story.append(Spacer(1,0.3*cm)); return story

def _blue_sheet_pdf(school_id,filename,subtitle,students,subjects,get_score_fn,term=None,class_label=""):
    subj_map=get_subject_map(school_id)
    H_BG=colors.HexColor("#1A6FA8"); S_BG=colors.HexColor("#5BA4CF")
    ODD=colors.HexColor("#E8F4FC"); EVEN=colors.white
    RED=colors.HexColor("#C0392B"); WHITE=colors.white
    page_size = landscape(A3) if len(subjects) > 10 else landscape(A4)
    doc=SimpleDocTemplate(filename,pagesize=page_size,rightMargin=1.2*cm,leftMargin=1.2*cm,topMargin=1.2*cm,bottomMargin=1.2*cm)
    styles=getSampleStyleSheet(); story=[]
    tl=term["label"] if term else ""
    title_text = f"{subtitle} — {class_label}" if class_label else subtitle
    story+=_school_header_story(school_id,styles,title_text,tl)
    results=[]
    for s in students:
        row={"name":s["name"],"scores":{},"total":0,"count":0}
        for subj in subjects:
            sc=get_score_fn(s["id"],subj); row["scores"][subj]=sc
            if sc is not None: row["total"]+=sc; row["count"]+=1
        row["average"]=row["total"]/row["count"] if row["count"] else 0
        row["grade"]=get_grade(school_id,row["average"]); results.append(row)
    _assign_positions(results,"average")
    name_style = ParagraphStyle("NameCell", parent=styles["Normal"], fontSize=7.5, leading=8.5)
    hdr=["#","Student"]+[subj_map.get(s,s[:4].upper()) for s in subjects]+["Total","Avg","Pos","Grd"]
    tdata=[hdr]; fail_cells=[]
    for ri,r in enumerate(results,1):
        row=[str(ri),Paragraph(_esc(r["name"]),name_style)]
        for ci,subj in enumerate(subjects):
            sc=r["scores"][subj]
            if sc is not None:
                if sc<50: fail_cells.append((ri,ci+2))
                row.append(f"{sc:.1f}")
            else: row.append("-")
        row+=[f"{r['total']:.1f}" if r["count"] else "-",
              f"{r['average']:.1f}" if r["count"] else "-",
              str(r["position"]),r["grade"] if r["count"] else "-"]
        tdata.append(row)
    sc_w=1.2*cm
    cw=[0.8*cm,6.2*cm]+[sc_w]*len(subjects)+[1.5*cm,1.3*cm,0.9*cm,1.0*cm]
    tbl=Table(tdata,colWidths=cw,repeatRows=1)
    ts=[("BACKGROUND",(0,0),(-1,0),H_BG),("TEXTCOLOR",(0,0),(-1,0),WHITE),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,0),6.5),
        ("ALIGN",(0,0),(-1,0),"CENTER"),("FONTNAME",(0,1),(-1,-1),"Helvetica"),
        ("FONTSIZE",(0,1),(-1,-1),7),("ALIGN",(0,1),(-1,-1),"CENTER"),("ALIGN",(1,1),(1,-1),"LEFT"),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[ODD,EVEN]),("GRID",(0,0),(-1,-1),0.4,colors.HexColor("#A0C4E0")),
        ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3),
        ("BACKGROUND",(-4,0),(-1,0),S_BG),("FONTNAME",(-4,1),(-1,-1),"Helvetica-Bold")]
    for (ri,ci) in fail_cells: ts.append(("TEXTCOLOR",(ci,ri),(ci,ri),RED))
    tbl.setStyle(TableStyle(ts)); story.append(tbl)
    story.append(Spacer(1,0.3*cm))
    ft=ParagraphStyle("F",parent=styles["Normal"],fontSize=6.5,textColor=colors.grey,alignment=2)
    story.append(Paragraph(f"Generated | {len(students)} students | {tl}",ft))
    doc.build(story)

@app.route("/api/pdf/report/<int:sid>", methods=["GET"])
@subscription_required
def pdf_report(sid):
    school_id=school_id_from_header(); subjects=get_subjects(school_id); subj_map=get_subject_map(school_id)
    term_id=request.args.get("term_id")
    con=get_db(); cur=con.cursor()
    cur.execute("""SELECT s.id,s.name,s.class_id,s.stream_id,c.class_name,st.stream_name
                   FROM students s JOIN classes c ON s.class_id=c.id LEFT JOIN streams st ON s.stream_id=st.id
                   WHERE s.id=%s AND s.school_id=%s""",(sid,school_id))
    row=cur.fetchone(); student=to_dict(row,cur) if row else None; cur.close(); con.close()
    if not student: return jsonify({"error":"Not found"}),404
    term=get_term_by_id(school_id,int(term_id)) if term_id else get_active_term(school_id)
    if not term: return jsonify({"error":"No term"}),400
    tid=term["id"]; ca_count=term["ca_count"]; ca_w=term["ca_weight"]; ex_w=term["exam_weight"]
    class_id=student["class_id"]; stream_id=student["stream_id"]

    class_rows, class_rank_map, stream_rank_map, scores_bulk = get_class_report_data(
        school_id, tid, class_id, stream_id, subjects, ca_w, ex_w)
    subject_rank_maps = {subj: get_subject_rank_map(class_rows, subj) for subj in subjects}
    c_entry=class_rank_map.get(sid)
    c_pos=c_entry["position"] if c_entry else "-"
    c_total=len(class_rows)
    s_pos=s_total=None
    if stream_id and stream_rank_map is not None:
        s_entry=stream_rank_map.get(sid)
        s_pos=s_entry["position"] if s_entry else "-"
        s_total=len(stream_rank_map)
    student_finals = c_entry["finals"] if c_entry else compute_student_finals(scores_bulk, sid, subjects, ca_w, ex_w)
    avg = c_entry["average"] if c_entry else compute_average_from_finals(student_finals)
    student_scores = scores_bulk.get(sid, {})

    safe=student["name"].replace(" ","_")
    fname=os.path.join(tempfile.gettempdir(),f"RC_{school_id}_{safe}_{tid}.pdf")
    # Many CA columns get cramped in portrait — switch to landscape automatically.
    page_size = landscape(A4) if ca_count > 4 else A4
    doc=SimpleDocTemplate(fname,pagesize=page_size,rightMargin=1.5*cm,leftMargin=1.5*cm,topMargin=1.5*cm,bottomMargin=1.5*cm)
    styles=getSampleStyleSheet(); story=[]
    H_BG=colors.HexColor("#1A6FA8"); ODD=colors.HexColor("#E8F4FC"); WHITE=colors.white; RED=colors.HexColor("#C0392B")
    story+=_school_header_story(school_id,styles,"STUDENT REPORT CARD")
    stream_label=f"{student['class_name']} {student['stream_name']}" if student.get("stream_name") else student["class_name"]
    info=[[" Name:",student["name"],"Class:",stream_label],
          ["Term:",term["label"],"Weights:",f"CA {ca_w}% | Exam {ex_w}%"],
          ["Class Position:",f"{c_pos}/{c_total}","Grade:",get_grade(school_id,avg)]]
    if s_pos is not None: info.append(["Stream Position:",f"{s_pos}/{s_total}","",""])
    it=Table(info,colWidths=[3*cm,6*cm,3*cm,5*cm])
    it.setStyle(TableStyle([("FONTNAME",(0,0),(-1,-1),"Helvetica"),("FONTNAME",(0,0),(0,-1),"Helvetica-Bold"),
        ("FONTNAME",(2,0),(2,-1),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),9),
        ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3)]))
    story+=[it,Spacer(1,0.4*cm)]
    hdr=["Subject"]+[f"CA{i}" for i in range(1,ca_count+1)]+["Exam","Final","Pos","Grd","Remark","Sign"]
    tdata=[hdr]; tot,cnt=0,0; fail_rows=[]
    for subject in subjects:
        entry=student_scores.get(subject,{})
        ca_map=entry.get("ca",{})
        row_data=[subject.title()]+[f"{ca_map.get(f'CA{i}'):.1f}" if ca_map.get(f"CA{i}") is not None else "-" for i in range(1,ca_count+1)]
        exam_v=entry.get("exam")
        row_data.append(f"{exam_v:.1f}" if exam_v is not None else "-")
        final_v=student_finals.get(subject)
        if final_v is not None: tot+=final_v; cnt+=1
        row_data.append(f"{final_v:.1f}" if final_v is not None else "-")
        row_data.append(str(subject_rank_maps[subject].get(sid,"-")) if final_v is not None else "-")
        row_data.append(get_grade(school_id,final_v) if final_v is not None else "-")
        row_data+=["",""]
        if final_v is not None and final_v<50: fail_rows.append(len(tdata))
        tdata.append(row_data)
    ca_cw=1.1*cm; cw=[4.0*cm]+[ca_cw]*ca_count+[1.4*cm,1.4*cm,1.0*cm,1.1*cm,2.4*cm,1.6*cm]
    mt=Table(tdata,colWidths=cw,repeatRows=1)
    mts=[("BACKGROUND",(0,0),(-1,0),H_BG),("TEXTCOLOR",(0,0),(-1,0),WHITE),
         ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),7.5),
         ("ALIGN",(0,0),(-1,-1),"CENTER"),("ALIGN",(0,1),(0,-1),"LEFT"),
         ("GRID",(0,0),(-1,-1),0.4,colors.HexColor("#A0C4E0")),("ROWBACKGROUNDS",(0,1),(-1,-1),[ODD,WHITE]),
         ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3)]
    for ri in fail_rows: mts.append(("TEXTCOLOR",(0,ri),(-1,ri),RED))
    mt.setStyle(TableStyle(mts)); story+=[mt,Spacer(1,0.4*cm)]
    comp_avg=tot/cnt if cnt else 0
    summary_data=[["AVERAGE",f"{comp_avg:.2f}","GRADE",get_grade(school_id,comp_avg),"CLASS POS",f"{c_pos}/{c_total}"]]
    summary_cols=[3*cm,3*cm,2*cm,2*cm,3*cm,4*cm]
    if s_pos is not None: summary_data[0]+=["STREAM POS",f"{s_pos}/{s_total}"]; summary_cols+=[3*cm,3*cm]
    sm=Table(summary_data,colWidths=summary_cols)
    sm.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),H_BG),("TEXTCOLOR",(0,0),(-1,-1),WHITE),
        ("FONTNAME",(0,0),(-1,-1),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),9),
        ("ALIGN",(0,0),(-1,-1),"CENTER"),("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5)]))
    story+=[sm,Spacer(1,0.4*cm)]
    con=get_db(); cur=con.cursor()
    cur.execute("SELECT * FROM remarks WHERE school_id=%s AND student_id=%s AND term_id=%s",(school_id,sid,tid))
    rmk_row=cur.fetchone(); rmk=to_dict(rmk_row,cur) if rmk_row else None; cur.close(); con.close()
    rm_data=[["Class Teacher Remark:",rmk["class_teacher_remark"] if rmk else "________________________"],
             ["Head of School Remark:",rmk["head_remark"] if rmk else "________________________"]]
    rmt=Table(rm_data,colWidths=[5*cm,12*cm])
    rmt.setStyle(TableStyle([("FONTNAME",(0,0),(0,-1),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),8),
        ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),("LINEBELOW",(1,0),(1,-1),0.5,colors.grey)]))
    story+=[rmt,Spacer(1,0.4*cm)]
    sig=Table([["Class Teacher Sign: _______________","Head Sign: _______________","Date: _______________"]],colWidths=[6*cm,6*cm,5*cm])
    sig.setStyle(TableStyle([("FONTSIZE",(0,0),(-1,-1),7.5),("FONTNAME",(0,0),(-1,-1),"Helvetica")]))
    story.append(sig); doc.build(story)
    return send_file(fname,as_attachment=True,
                     download_name=f"RC_{student['name'].replace(' ','_')}_{term['label'].replace(' ','_')}.pdf",
                     mimetype="application/pdf")

@app.route("/api/pdf/ca_sheet", methods=["GET"])
@subscription_required
def pdf_ca_sheet():
    school_id=school_id_from_header(); subjects=get_subjects(school_id)
    class_id=request.args.get("class_id"); stream_id=request.args.get("stream_id") or None
    ca_name=request.args.get("ca_name","CA1"); term_id=request.args.get("term_id")
    term=get_term_by_id(school_id,int(term_id)) if term_id else get_active_term(school_id)
    if not term: return jsonify({"error":"No term"}),400
    tid=term["id"]; class_id=int(class_id) if class_id else None
    if stream_id: stream_id=int(stream_id)
    studs=get_students_in_scope(school_id,class_id,stream_id)
    if not studs: return jsonify({"error":"No students"}),404
    fname=os.path.join(tempfile.gettempdir(),f"CA_{school_id}_{class_id}_{ca_name}_{tid}.pdf")
    scores_bulk=get_term_scores_bulk(school_id,tid,[s["id"] for s in studs])
    def get_score(stid,subj):
        entry=scores_bulk.get(stid,{}).get(subj)
        return entry["ca"].get(ca_name) if entry else None
    class_label = studs[0]["class_name"] + (f" {studs[0]['stream_name']}" if stream_id and studs[0].get("stream_name") else "")
    _blue_sheet_pdf(school_id,fname,f"{ca_name.upper()} SCORE SHEET",studs,subjects,get_score,term,class_label=class_label)
    return send_file(fname,as_attachment=True,download_name=os.path.basename(fname),mimetype="application/pdf")

@app.route("/api/pdf/terminal_sheet", methods=["GET"])
@subscription_required
def pdf_terminal_sheet():
    school_id=school_id_from_header(); subjects=get_subjects(school_id)
    class_id=request.args.get("class_id"); stream_id=request.args.get("stream_id") or None; term_id=request.args.get("term_id")
    term=get_term_by_id(school_id,int(term_id)) if term_id else get_active_term(school_id)
    if not term: return jsonify({"error":"No term"}),400
    tid=term["id"]; class_id=int(class_id) if class_id else None
    if stream_id: stream_id=int(stream_id)
    studs=get_students_in_scope(school_id,class_id,stream_id)
    if not studs: return jsonify({"error":"No students"}),404
    fname=os.path.join(tempfile.gettempdir(),f"Terminal_{school_id}_{class_id}_{tid}.pdf")
    scores_bulk=get_term_scores_bulk(school_id,tid,[s["id"] for s in studs])
    ca_w=term["ca_weight"]; ex_w=term["exam_weight"]
    def get_score(stid,subj):
        f=_final_from_entry(scores_bulk.get(stid,{}).get(subj),ca_w,ex_w)
        return round(f,1) if f is not None else None
    class_label = studs[0]["class_name"] + (f" {studs[0]['stream_name']}" if stream_id and studs[0].get("stream_name") else "")
    _blue_sheet_pdf(school_id,fname,f"TERMINAL SCORE SHEET (CA {term['ca_weight']}% + Exam {term['exam_weight']}%)",studs,subjects,get_score,term)
    return send_file(fname,as_attachment=True,download_name=os.path.basename(fname),mimetype="application/pdf")


# ══════════════════════════════════════════════════════════════
# SUPERADMIN ROUTES
# ══════════════════════════════════════════════════════════════
_SA_SESSIONS = {}

def _sa_token():
    auth=request.headers.get("Authorization","")
    if auth.startswith("Bearer "): return auth[7:].strip()
    return None

def _require_superadmin():
    token=_sa_token()
    if not token or token not in _SA_SESSIONS:
        return None,(jsonify({"ok":False,"error":"Superadmin authentication required"}),401)
    return _SA_SESSIONS[token],None

@app.route("/api/superadmin/login", methods=["POST"])
def api_superadmin_login():
    d=request.json; u=d.get("username","").strip(); p=d.get("password","")
    if not u or not p: return jsonify({"ok":False,"error":"Username and password required"}),400
    con=get_db(); cur=con.cursor()
    cur.execute("SELECT password FROM superadmins WHERE username=%s",(u,))
    row=cur.fetchone(); cur.close(); con.close()
    if not row or not verify_password(p,row[0]): return jsonify({"ok":False,"error":"Invalid credentials"}),401
    token=secrets.token_hex(32); _SA_SESSIONS[token]=u
    return jsonify({"ok":True,"token":token,"username":u})

@app.route("/api/superadmin/logout", methods=["POST"])
def api_superadmin_logout():
    token=_sa_token()
    if token and token in _SA_SESSIONS: del _SA_SESSIONS[token]
    return jsonify({"ok":True})

@app.route("/api/superadmin/schools", methods=["GET"])
def api_superadmin_schools():
    sa,err=_require_superadmin()
    if err: return err
    try:
        con=get_db(); cur=con.cursor()
        cur.execute("SELECT id,school_name,CAST(registered_at AS TEXT) FROM schools ORDER BY id")
        schools_raw=to_dicts(cur.fetchall(),cur); result=[]
        for s in schools_raw:
            sid=s["id"]
            cur.execute("SELECT COUNT(*) FROM students WHERE school_id=%s",(sid,)); sc=cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM users WHERE school_id=%s AND role='teacher'",(sid,)); tc=cur.fetchone()[0]
            cur.execute("SELECT label FROM terms WHERE school_id=%s AND status='open' ORDER BY id DESC LIMIT 1",(sid,))
            r=cur.fetchone(); at=r[0] if r else "—"
            cur.execute("SELECT subscription_exempt, subscription_status, subscription_plan, subscription_expires_at FROM schools WHERE id=%s",(sid,))
            sub_row = cur.fetchone()
            exempt, sub_status, sub_plan, sub_expires = sub_row if sub_row else (0,"inactive","",None)
            payment_status = "demo" if exempt else (sub_status or "inactive")
            result.append({"id":sid,"school_name":s["school_name"],"registered_at":s.get("cast") or "—",
                           "student_count":sc,"teacher_count":tc,"active_term":at,
                           "payment_status":payment_status,
                           "subscription_plan": sub_plan or "—",
                           "subscription_expires_at": sub_expires.isoformat() if sub_expires else None})
        cur.close(); con.close()
        return jsonify({"ok":True,"schools":result})
    except Exception as e: return jsonify({"ok":False,"error":str(e)}),500

@app.route("/api/superadmin/announce", methods=["GET"])
def api_superadmin_announce_list():
    sa,err=_require_superadmin()
    if err: return err
    try:
        con=get_db(); cur=con.cursor()
        cur.execute("SELECT id,title,body,target,CAST(posted_at AS TEXT) as posted_at FROM platform_announcements ORDER BY posted_at DESC")
        rows=to_dicts(cur.fetchall(),cur); cur.close(); con.close()
        return jsonify({"ok":True,"announcements":rows})
    except Exception as e: return jsonify({"ok":False,"error":str(e)}),500

@app.route("/api/superadmin/announce", methods=["POST"])
def api_superadmin_announce():
    sa,err=_require_superadmin()
    if err: return err
    d=request.json; title=d.get("title","").strip(); body=d.get("body","").strip(); target=d.get("target","all").strip()
    if not title or not body: return jsonify({"ok":False,"error":"Title and body required"}),400
    try:
        con=get_db(); cur=con.cursor()
        cur.execute("INSERT INTO platform_announcements(title,body,target) VALUES(%s,%s,%s) RETURNING id",(title,body,target))
        new_id=cur.fetchone()[0]; con.commit(); cur.close(); con.close()
        return jsonify({"ok":True,"id":new_id})
    except Exception as e: return jsonify({"ok":False,"error":str(e)}),500

@app.route("/api/superadmin/announce/<int:aid>", methods=["DELETE"])
def api_superadmin_announce_delete(aid):
    sa,err=_require_superadmin()
    if err: return err
    try:
        con=get_db(); cur=con.cursor()
        cur.execute("DELETE FROM platform_announcements WHERE id=%s",(aid,))
        con.commit(); cur.close(); con.close()
        return jsonify({"ok":True})
    except Exception as e: return jsonify({"ok":False,"error":str(e)}),500

@app.route("/api/reset_db", methods=["POST"])
def api_reset_db():
    secret=request.json.get("secret","")
    if secret!=os.environ.get("ADMIN_SETUP_SECRET",""): return jsonify({"ok":False,"error":"Invalid secret"}),403
    con=get_db(); cur=con.cursor()
    for t in ["remarks","exam_scores","ca_scores","subject_assignments","students","streams","classes",
              "terms","grade_config","school_subjects","school_config","announcements","announcement_reads",
              "results_published","users","schools"]:
        cur.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    con.commit(); cur.close(); con.close(); init_db()
    return jsonify({"ok":True,"message":"Database reset."})

@app.route("/api/superadmin/payment_requests", methods=["GET"])
def api_sa_payment_requests():
    sa, err = _require_superadmin()
    if err: return err
    _expire_stale_payment_requests()
    status = request.args.get("status", "pending")
    con = get_db(); cur = con.cursor()
    q = """SELECT pr.id, pr.school_id, s.school_name, pr.plan, pr.claimed_amount, pr.transaction_id,
                  pr.phone_used, CAST(pr.payment_date AS TEXT), pr.note, pr.status,
                  pr.submitted_by, CAST(pr.submitted_at AS TEXT),
                  pr.decided_by, CAST(pr.decided_at AS TEXT), pr.decision_note
           FROM payment_requests pr JOIN schools s ON s.id = pr.school_id"""
    params = ()
    if status != "all":
        q += " WHERE pr.status=%s"; params = (status,)
    q += " ORDER BY pr.submitted_at ASC"
    cur.execute(q, params)
    rows = to_dicts(cur.fetchall(), cur); cur.close(); con.close()
    return jsonify({"ok": True, "requests": rows})

@app.route("/api/superadmin/payment_requests/<int:rid>/approve", methods=["POST"])
def api_sa_approve_payment(rid):
    sa, err = _require_superadmin()
    if err: return err
    note = (request.json or {}).get("note", "")
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT school_id, plan, status FROM payment_requests WHERE id=%s", (rid,))
    row = cur.fetchone()
    if not row: cur.close(); con.close(); return jsonify({"ok": False, "error": "Not found"}), 404
    school_id, plan, status = row
    if status not in ("pending", "expired"):
        cur.close(); con.close(); return jsonify({"ok": False, "error": "This request was already decided"}), 409
    if plan not in SUBSCRIPTION_PLANS:
        cur.close(); con.close(); return jsonify({"ok": False, "error": "Unknown plan on this request"}), 400
    days = SUBSCRIPTION_PLANS[plan]["days"]
    cur.execute("SELECT subscription_expires_at FROM schools WHERE id=%s", (school_id,))
    exp_row = cur.fetchone()
    base = exp_row[0] if exp_row and exp_row[0] and exp_row[0] > datetime.utcnow() else datetime.utcnow()
    cur.execute("""UPDATE schools SET subscription_status='active', subscription_plan=%s,
                   subscription_expires_at=%s WHERE id=%s""",
                (plan, base + timedelta(days=days), school_id))
    cur.execute("""UPDATE payment_requests SET status='approved', decided_by=%s, decided_at=NOW(), decision_note=%s
                   WHERE id=%s""", (sa, note, rid))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok": True})

@app.route("/api/superadmin/payment_requests/<int:rid>/reject", methods=["POST"])
def api_sa_reject_payment(rid):
    sa, err = _require_superadmin()
    if err: return err
    note = (request.json or {}).get("note", "").strip()
    if not note: return jsonify({"ok": False, "error": "A rejection reason is required"}), 400
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT school_id, status FROM payment_requests WHERE id=%s", (rid,))
    row = cur.fetchone()
    if not row: cur.close(); con.close(); return jsonify({"ok": False, "error": "Not found"}), 404
    school_id, status = row
    if status not in ("pending", "expired"):
        cur.close(); con.close(); return jsonify({"ok": False, "error": "This request was already decided"}), 409
    cur.execute("UPDATE payment_requests SET status='rejected', decided_by=%s, decided_at=NOW(), decision_note=%s WHERE id=%s",
                (sa, note, rid))
    cur.execute("UPDATE schools SET subscription_status='inactive' WHERE id=%s AND subscription_status='pending'", (school_id,))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok": True})

@app.route("/api/superadmin/payment_config", methods=["GET"])
def api_sa_get_payment_config():
    sa, err = _require_superadmin()
    if err: return err
    return jsonify({"ok": True, **_platform_payment_config()})

@app.route("/api/superadmin/payment_config", methods=["POST"])
def api_sa_set_payment_config():
    sa, err = _require_superadmin()
    if err: return err
    d = request.json or {}
    business_name = (d.get("business_name") or "").strip()
    payment_number = (d.get("payment_number") or "").strip()
    networks = d.get("networks") or []
    if not business_name or not payment_number:
        return jsonify({"ok": False, "error": "Business name and payment number required"}), 400
    con = get_db(); cur = con.cursor()
    cur.execute("""UPDATE platform_payment_config SET business_name=%s, payment_number=%s, networks=%s, updated_at=NOW() WHERE id=1""",
                (business_name, payment_number, ",".join(networks)))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok": True})

# ── STATIC ─────────────────────────────────────────────────────
_STATIC_FILES=["shared.css","shared.js","page-dashboard.js","page-students.js",
               "page-teachers.js","page-reports.js","page-parent.js","page-config.js",
               "page-analytics.js"]

@app.route("/")
def index(): return send_from_directory(BASE_DIR,"index.html")

@app.route("/setup")
def setup_page(): return send_from_directory(BASE_DIR,"setup.html")

@app.route("/register")
def register_page(): return send_from_directory(BASE_DIR,"register.html")

@app.route("/superadmin")
def superadmin_page(): return send_from_directory(BASE_DIR,"superadmin.html")

@app.route("/storage/uploads/logos/<filename>")
def serve_logo_static(filename):
    return send_from_directory(os.path.join(UPLOAD_FOLDER,"logos"),filename)

@app.route("/api/config/logo", methods=["POST"])
def api_upload_logo():
    school_id = school_id_from_header()
    if "logo" not in request.files:
        return jsonify({"ok":False,"error":"No logo file uploaded"}), 400
    f = request.files["logo"]
    if not f or not f.filename:
        return jsonify({"ok":False,"error":"No logo file uploaded"}), 400
    ext = f.filename.rsplit(".",1)[-1].lower() if "." in f.filename else ""
    if ext not in ALLOWED_LOGO_EXT:
        return jsonify({"ok":False,"error":"Logo must be an image (png, jpg, jpeg, gif, webp, svg)"}), 400
    raw = f.read()
    if len(raw) > 2*1024*1024:
        return jsonify({"ok":False,"error":"Logo must be smaller than 2MB"}), 400
    logo_mime = _mime_for_ext(ext)
    logo_b64  = base64.b64encode(raw).decode("ascii")
    set_config_val(school_id, "logo_data", logo_b64)
    set_config_val(school_id, "logo_mime", logo_mime)
    logo_path = f"api/logo/{school_id}"
    set_config_val(school_id, "logo_path", logo_path)
    return jsonify({"ok":True,"logo_path":logo_path})

@app.route("/api/logo/<int:school_id>")
def serve_logo_db(school_id):
    data = get_config_val(school_id, "logo_data", "")
    mime = get_config_val(school_id, "logo_mime", "image/png")
    if not data:
        return ("Not found", 404)
    try:
        raw = base64.b64decode(data)
    except Exception:
        return ("Not found", 404)
    return send_file(io.BytesIO(raw), mimetype=mime)

@app.route("/<path:filename>")
def serve_static(filename):
    if filename in _STATIC_FILES: return send_from_directory(BASE_DIR,filename)
    return ("Not found",404)


# ── STUDENT IMPORT (Excel/CSV) ─────────────────────────────────

import csv, io
try:
    import openpyxl
    OPENPYXL_AVAILABLE = True
except ImportError:
    OPENPYXL_AVAILABLE = False

def hash_password_fast(pw):
    """Fast hash for temporary/bulk import passwords.
    These are throwaway — users must change on first login anyway.
    260,000 iterations x 4000 students = death. 100 iterations = fine.
    Iteration count is stored in the hash itself, so verify_password()
    still checks it correctly regardless of how it was hashed."""
    return hash_password(pw, iterations=100)

def _parse_import_file(file_obj, filename):
    """Parse uploaded Excel or CSV. Returns list of raw row dicts."""
    ext = filename.rsplit(".",1)[-1].lower() if "." in filename else ""
    rows = []
    if ext in ("xlsx","xls"):
        if not OPENPYXL_AVAILABLE:
            raise ValueError("openpyxl not installed. Add it to requirements.txt")
        wb = openpyxl.load_workbook(file_obj, read_only=True, data_only=True)
        ws = wb.active
        headers = None
        for row in ws.iter_rows(values_only=True):
            # Skip fully empty rows
            if all(v is None for v in row): continue
            if headers is None:
                headers = [str(h).strip().lower() if h else "" for h in row]
                continue
            values = [str(v).strip() if v is not None else "" for v in row]
            row_dict = dict(zip(headers, values))
            # Skip completely empty rows
            if all(v == "" for v in values): continue
            rows.append(row_dict)
        wb.close()
    elif ext == "csv":
        text = file_obj.read().decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            rows.append({k.strip().lower(): str(v).strip() for k,v in row.items()})
    else:
        raise ValueError("Unsupported file type. Use .xlsx or .csv")
    return rows

def _normalize_col(row, *candidates):
    """Try multiple possible column name spellings — strip, lowercase, ignore spaces/underscores."""
    def clean(s): return s.strip().lower().replace(" ","").replace("_","").replace("-","")
    cleaned_row = {clean(k): v for k,v in row.items()}
    for c in candidates:
        key = clean(c)
        if key in cleaned_row and cleaned_row[key]:
            return str(cleaned_row[key]).strip()
    return ""

def _col_by_position(row, index):
    """Fallback: grab column by position index regardless of header name."""
    vals = list(row.values())
    if index < len(vals) and vals[index]:
        return str(vals[index]).strip()
    return ""

def _extract_fields(row):
    """
    Try named columns first. If name or class is still missing,
    fall back to positional: col0=name, col1=class, col2=stream, col3=phone.
    No conditions on format, length, or capitalization.
    """
    name         = _normalize_col(row,"name","student name","full name","jina","student","students","jina la mwanafunzi","mwanafunzi")
    class_name   = _normalize_col(row,"class_name","class","darasa","form","grade","class name","level","form name")
    stream_name  = _normalize_col(row,"stream_name","stream","mkondo","section","division","stream name","class stream")
    parent_phone = _normalize_col(row,"parent_phone","phone","parent phone","phone number","simu","contact","guardian phone","nambari","tel","telephone","mobile","simu ya mzazi","mzazi")
    # If name or class still missing — go positional, user probably has no headers or weird headers
    if not name:        name         = _col_by_position(row, 0)
    if not class_name:  class_name   = _col_by_position(row, 1)
    if not stream_name: stream_name  = _col_by_position(row, 2)
    if not parent_phone:parent_phone = _col_by_position(row, 3)
    return name, class_name, stream_name, parent_phone

def _build_class_map(school_id):
    """Return {class_name_lower: {stream_name_lower: (class_id, stream_id)}}"""
    con = get_db(); cur = con.cursor()
    cur.execute("""SELECT c.id,c.class_name,s.id,s.stream_name
                   FROM classes c LEFT JOIN streams s ON s.class_id=c.id AND s.school_id=c.school_id
                   WHERE c.school_id=%s""", (school_id,))
    rows = cur.fetchall(); cur.close(); con.close()
    cmap = {}
    for (cid, cname, sid, sname) in rows:
        ckey = cname.strip().lower()
        if ckey not in cmap: cmap[ckey] = {"_id": cid, "_streams": {}}
        if sname:
            skey = sname.strip().lower()
            cmap[ckey]["_streams"][skey] = (cid, sid)
    return cmap

@app.route("/api/students/import/template", methods=["GET"])
def api_import_template():
    """Download a pre-filled Excel template."""
    school_id = school_id_from_header()
    if not OPENPYXL_AVAILABLE:
        # Fallback: return CSV template
        csv_content = "name,class_name,stream_name,parent_phone\nJuma Hassan,Form 1,A,0712345678\nFatuma Ally,Form 1,B,0754987654\n"
        return send_file(io.BytesIO(csv_content.encode()), as_attachment=True,
                        download_name="student_import_template.csv", mimetype="text/csv")
    wb = openpyxl.Workbook()
    ws = wb.active; ws.title = "Students"
    # Header row
    headers = ["name","class_name","stream_name","parent_phone"]
    header_labels = ["Student Full Name *","Class Name *","Stream Name (if any)","Parent Phone Number *"]
    from openpyxl.styles import Font, PatternFill, Alignment
    header_fill = PatternFill("solid", fgColor="1A6FA8")
    for col, (h, label) in enumerate(zip(headers, header_labels), 1):
        cell = ws.cell(row=1, column=col, value=label)
        cell.font = Font(bold=True, color="FFFFFF", size=11)
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")
    # Column widths
    ws.column_dimensions["A"].width = 28
    ws.column_dimensions["B"].width = 16
    ws.column_dimensions["C"].width = 18
    ws.column_dimensions["D"].width = 20
    # Pull existing classes for reference
    cmap = _build_class_map(school_id)
    # Example rows
    examples = []
    for ckey, cval in list(cmap.items())[:3]:
        cname = ckey.title()
        if cval["_streams"]:
            for skey in list(cval["_streams"].keys())[:2]:
                examples.append([f"Example Student", cname, skey.title(), "07XXXXXXXXX"])
        else:
            examples.append(["Example Student", cname, "", "07XXXXXXXXX"])
    if not examples:
        examples = [
            ["Juma Hassan","Form 1","A","0712345678"],
            ["Fatuma Ally","Form 1","B","0754987654"],
            ["Emmanuel Peter","Form 2","","0622123456"],
        ]
    from openpyxl.styles import Font as F2
    for ri, row in enumerate(examples, 2):
        for ci, val in enumerate(row, 1):
            cell = ws.cell(row=ri, column=ci, value=val)
            cell.font = F2(color="888888", italic=True)
    # Instructions sheet
    ws2 = wb.create_sheet("Instructions")
    instructions = [
        ("STUDENT IMPORT INSTRUCTIONS",""),
        ("",""),
        ("Column","What to put"),
        ("name","Full name of the student (e.g. Juma Hassan Ally)"),
        ("class_name","Must match exactly a class in your school (e.g. Form 1, Form 2)"),
        ("stream_name","Stream if your class has streams (e.g. A, B, Science, Arts). Leave blank if no streams."),
        ("parent_phone","Parent or guardian phone number (e.g. 0712345678)"),
        ("",""),
        ("IMPORTANT",""),
        ("• Delete the example rows before importing",""),
        ("• class_name must exactly match your school classes",""),
        ("• stream_name must exactly match your stream names",""),
        ("• Do not change the column headers",""),
        ("• Save as .xlsx or .csv before uploading",""),
    ]
    from openpyxl.styles import Font as F3
    for ri, (a,b) in enumerate(instructions, 1):
        ws2.cell(row=ri, column=1, value=a)
        ws2.cell(row=ri, column=2, value=b)
        if ri == 1:
            ws2.cell(row=ri, column=1).font = F3(bold=True, size=13, color="1A6FA8")
        if ri == 3:
            ws2.cell(row=ri, column=1).font = F3(bold=True)
            ws2.cell(row=ri, column=2).font = F3(bold=True)
    ws2.column_dimensions["A"].width = 40
    ws2.column_dimensions["B"].width = 50
    # Classes reference
    if cmap:
        ws3 = wb.create_sheet("Your Classes")
        ws3.cell(row=1,column=1,value="Class Name").font = F3(bold=True)
        ws3.cell(row=1,column=2,value="Streams").font = F3(bold=True)
        for ri,(ckey,cval) in enumerate(cmap.items(),2):
            ws3.cell(row=ri,column=1,value=ckey.title())
            streams = ", ".join(s.title() for s in cval["_streams"].keys())
            ws3.cell(row=ri,column=2,value=streams or "(no streams)")
        ws3.column_dimensions["A"].width = 20
        ws3.column_dimensions["B"].width = 30
    buf = io.BytesIO(); wb.save(buf); buf.seek(0)
    return send_file(buf, as_attachment=True,
                    download_name="student_import_template.xlsx",
                    mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

@app.route("/api/students/import/preview", methods=["POST"])
def api_import_preview():
    """Parse file, return first 10 rows for preview without inserting."""
    school_id = school_id_from_header()
    if "file" not in request.files:
        return jsonify({"ok":False,"error":"No file uploaded"}), 400
    f = request.files["file"]
    try:
        rows = _parse_import_file(f.stream, f.filename)
    except ValueError as e:
        return jsonify({"ok":False,"error":str(e)}), 400
    if not rows:
        return jsonify({"ok":False,"error":"File is empty or has no data rows"}), 400
    cmap = _build_class_map(school_id)
    preview = []; warnings = []
    for i, row in enumerate(rows[:10]):
        name, class_name, stream_name, parent_phone = _extract_fields(row)
        errs = []
        if not name:        errs.append("Missing name")
        if not class_name:  errs.append("Missing class")
        if not parent_phone:errs.append("Missing phone")
        ckey = class_name.lower()
        if class_name and ckey not in cmap: errs.append(f"Class '{class_name}' not found")
        preview.append({"row":i+2,"name":name,"class_name":class_name,"stream_name":stream_name,
                        "parent_phone":parent_phone,"errors":errs})
    return jsonify({"ok":True,"total_rows":len(rows),"preview":preview,
                    "columns_detected":list(rows[0].keys()) if rows else []})

def _write_credentials_xlsx(rows, path):
    """Write a workbook of parent username/one-time-password pairs for a completed import."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Parent Login Credentials"

    headers = ["Row", "Student Name", "Class", "Stream", "Parent Phone", "Username", "Temporary Password"]
    ws.append(headers)
    header_fill = PatternFill(start_color="1A6FA8", end_color="1A6FA8", fill_type="solid")
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = header_fill

    for r in rows:
        ws.append([
            r["row"], r["name"], r["class_name"], r["stream_name"] or "-",
            r["parent_phone"], r["username"], r["password"],
        ])

    widths = [6, 26, 14, 12, 16, 22, 20]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = w

    note_row = ws.max_row + 2
    ws.cell(row=note_row, column=1,
            value="Note: this is a one-time password. Parents must change it after first login.").font = \
        Font(italic=True, color="888888")

    wb.save(path)


@app.route("/api/students/import/credentials/<path:filename>")
def download_import_credentials(filename):
    """Serve a previously generated parent-credentials workbook for download."""
    filename = secure_filename(filename)
    path = os.path.join(IMPORT_EXPORT_FOLDER, filename)
    if not os.path.isfile(path):
        return jsonify({"ok": False, "error": "File not found or expired"}), 404
    return send_file(path, as_attachment=True,
                      download_name="parent_login_credentials.xlsx",
                      mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.route("/api/students/import", methods=["POST"])
def api_import_students():
    """Full import: parse, validate, bulk insert."""
    school_id = school_id_from_header()
    if "file" not in request.files:
        return jsonify({"ok":False,"error":"No file uploaded"}), 400
    f = request.files["file"]
    import traceback
    try:
        rows = _parse_import_file(f.stream, f.filename)
    except ValueError as e:
        return jsonify({"ok":False,"error":str(e)}),400
    except Exception as e:
        return jsonify({"ok":False,"error":"Parse failed: "+str(e)+" | "+traceback.format_exc()}), 500

    if not rows:
        return jsonify({"ok":False,"error":"File is empty"}), 400
    cmap     = _build_class_map(school_id)
    inserted = 0; skipped = []; errors = []; credentials = []; duplicates = 0
    con = get_db(); cur = con.cursor()

    # Snapshot of existing students for duplicate detection (name+class+stream+phone).
    # Also grows as we insert, so repeated rows within the same file are caught too —
    # and re-running an import on the same file becomes a safe no-op instead of creating dupes.
    cur.execute("SELECT LOWER(TRIM(name)), class_id, COALESCE(stream_id,0), phone_number "
                "FROM students WHERE school_id=%s", (school_id,))
    existing_students = set(cur.fetchall())

    for i, row in enumerate(rows):
        row_num      = i + 2
        name, class_name, stream_name, parent_phone = _extract_fields(row)
        if not name or not class_name or not parent_phone:
            skipped.append({"row":row_num,"reason":f"Missing: {'name' if not name else ''} {'class' if not class_name else ''} {'phone' if not parent_phone else ''}".strip(),"data":str(list(row.values())[:4])})
            continue
        ckey = class_name.strip().lower()
        if ckey not in cmap:
            skipped.append({"row":row_num,"reason":f"Class '{class_name}' not found — check spelling matches exactly","data":name})
            continue
        class_id  = cmap[ckey]["_id"]
        stream_id = None
        if stream_name:
            skey = stream_name.strip().lower()
            if skey in cmap[ckey]["_streams"]:
                class_id, stream_id = cmap[ckey]["_streams"][skey]
            else:
                skipped.append({"row":row_num,"reason":f"Stream '{stream_name}' not found in '{class_name}'","data":name})
                continue
        dup_key = (name.strip().lower(), class_id, stream_id or 0, parent_phone.strip())
        if dup_key in existing_students:
            skipped.append({"row":row_num,"reason":"Duplicate — same name, class, stream & phone already exist","data":name})
            duplicates += 1
            continue
        try:
            # Use savepoint so one failure doesn't abort the whole transaction
            cur.execute("SAVEPOINT sp_student")
            cur.execute("INSERT INTO students(school_id,name,class_id,stream_id,phone_number) VALUES(%s,%s,%s,%s,%s) RETURNING id",
                        (school_id, name, class_id, stream_id, parent_phone.strip()))
            student_id   = cur.fetchone()[0]
            username_base= name.strip().lower().replace(" ","_")
            temp_pw = parent_phone.strip()[-4:]
            
            cur.execute("INSERT INTO users(username,password,role,school_id,must_change_password,student_id) VALUES(%s,%s,'parent',%s,1,%s) ON CONFLICT(username,school_id) DO NOTHING",
                        (username_base,hash_password_fast(temp_pw),school_id,student_id))
            login_created = cur.rowcount > 0
            cur.execute("RELEASE SAVEPOINT sp_student")
            inserted += 1
            existing_students.add(dup_key)
            if login_created:
                credentials.append({"row":row_num,"name":name,"class_name":class_name,"stream_name":stream_name,
                                    "parent_phone":parent_phone.strip(),"username":username_base,"password":temp_pw})
            else:
                # Student record was created, but another student already has this exact
                # username (same name). Report it honestly instead of listing a login
                # that doesn't actually exist.
                skipped.append({"row":row_num,
                                "reason":f"Student added, but login username '{username_base}' is already taken "
                                         f"by another student with the same name — no new login created",
                                "data":name})
            # Commit every 200 students to avoid giant transactions
            if inserted % 200 == 0:
                con.commit()
        except Exception as e:
            cur.execute("ROLLBACK TO SAVEPOINT sp_student")
            errors.append({"row":row_num,"error":str(e),"data":name})
    con.commit(); cur.close(); con.close()

    credentials_file = None
    if credentials:
        fname = f"import_creds_{school_id}_{secrets.token_hex(8)}.xlsx"
        _write_credentials_xlsx(credentials, os.path.join(IMPORT_EXPORT_FOLDER, fname))
        credentials_file = f"/api/students/import/credentials/{fname}"

    return jsonify({"ok":True,"inserted":inserted,"skipped":len(skipped),"errors":len(errors),"duplicates":duplicates,
                    "skipped_details":skipped[:20],"error_details":errors[:20],
                    "credentials_file":credentials_file,"credentials_count":len(credentials)})


with app.app_context():
    init_db()

if __name__=="__main__":
    app.run(debug=False,host="0.0.0.0",port=int(os.environ.get("PORT",5000)))
