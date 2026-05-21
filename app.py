"""
School Manager – Flask API Backend (v4 – PostgreSQL)
Tables are created automatically on first run.
Set DATABASE_URL environment variable before running.
"""
import hashlib, os, tempfile, secrets
import psycopg2
import psycopg2.extras
from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATABASE_URL = os.environ.get("DATABASE_URL", "")

allowed_subjects = [
    "mathematics","physics","chemistry","biology",
    "geography","history","civics","english",
    "literature","kiswahili","bible knowledge",
    "book keeping","commerce","business studies",
    "historia ya tanzania na maadili",
]
classes = ["form 1","form 2","form 3","form 4"]

# ── DB ───────────────────────────────────────────────────────
def get_db():
    con = psycopg2.connect(DATABASE_URL)
    con.autocommit = False
    return con

def qone(cur, sql, params=()):
    cur.execute(sql, params)
    return cur.fetchone()

def qall(cur, sql, params=()):
    cur.execute(sql, params)
    return cur.fetchall()

def row_to_dict(row, cur):
    """Convert a psycopg2 row to a dict using cursor description."""
    if row is None:
        return None
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))

def rows_to_dicts(rows, cur):
    if not rows:
        return []
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in rows]

# ── AUTO-CREATE TABLES ───────────────────────────────────────
def init_db():
    con = get_db()
    cur = con.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        username         TEXT PRIMARY KEY,
        password         TEXT NOT NULL,
        role             TEXT NOT NULL CHECK(role IN ('admin','teacher')),
        is_class_teacher INTEGER DEFAULT 0,
        class_name       TEXT DEFAULT NULL
    );

    CREATE TABLE IF NOT EXISTS students (
        id         SERIAL PRIMARY KEY,
        name       TEXT NOT NULL,
        class_name TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS subject_assignments (
        id         SERIAL PRIMARY KEY,
        username   TEXT NOT NULL REFERENCES users(username),
        subject    TEXT NOT NULL,
        class_name TEXT NOT NULL,
        UNIQUE(username, subject, class_name)
    );

    CREATE TABLE IF NOT EXISTS terms (
        id          SERIAL PRIMARY KEY,
        label       TEXT NOT NULL,
        ca_count    INTEGER NOT NULL DEFAULT 2,
        ca_weight   INTEGER NOT NULL DEFAULT 30,
        exam_weight INTEGER NOT NULL DEFAULT 70,
        status      TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','closed'))
    );

    CREATE TABLE IF NOT EXISTS ca_scores (
        id         SERIAL PRIMARY KEY,
        student_id INTEGER NOT NULL REFERENCES students(id),
        subject    TEXT NOT NULL,
        class_name TEXT NOT NULL,
        ca_name    TEXT NOT NULL,
        score      REAL NOT NULL,
        entered_by TEXT,
        term_id    INTEGER NOT NULL REFERENCES terms(id),
        UNIQUE(student_id, subject, ca_name, term_id)
    );

    CREATE TABLE IF NOT EXISTS exam_scores (
        id         SERIAL PRIMARY KEY,
        student_id INTEGER NOT NULL REFERENCES students(id),
        subject    TEXT NOT NULL,
        class_name TEXT NOT NULL,
        score      REAL NOT NULL,
        entered_by TEXT,
        term_id    INTEGER NOT NULL REFERENCES terms(id),
        UNIQUE(student_id, subject, term_id)
    );

    CREATE TABLE IF NOT EXISTS remarks (
        student_id           INTEGER NOT NULL REFERENCES students(id),
        term_id              INTEGER NOT NULL REFERENCES terms(id),
        class_teacher_remark TEXT DEFAULT '',
        head_remark          TEXT DEFAULT '',
        PRIMARY KEY(student_id, term_id)
    );
    """)
    con.commit()
    cur.close()
    con.close()
    print("✓ Database tables ready.")

# ── PASSWORD ─────────────────────────────────────────────────
def hash_password(pw):
    salt = secrets.token_hex(16)
    dk   = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 260_000)
    return f"{salt}:{dk.hex()}"

def verify_password(pw, stored):
    try:
        salt, dk_hex = stored.split(":")
        dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 260_000)
        return dk.hex() == dk_hex
    except Exception:
        return False

# ── TERM HELPERS ─────────────────────────────────────────────
def get_active_term():
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT * FROM terms WHERE status='open' ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    result = row_to_dict(row, cur) if row else None
    cur.close(); con.close()
    return result

def get_term_by_id(term_id):
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT * FROM terms WHERE id=%s", (term_id,))
    row = cur.fetchone()
    result = row_to_dict(row, cur) if row else None
    cur.close(); con.close()
    return result

def term_weights(term_id):
    t = get_term_by_id(term_id)
    if not t: return 30, 70, 2
    return t["ca_weight"], t["exam_weight"], t["ca_count"]

# ── GRADE / SCORE ────────────────────────────────────────────
def get_grade(score):
    if score >= 80: return "A"
    if score >= 70: return "B"
    if score >= 60: return "C"
    if score >= 50: return "D"
    return "F"

def calc_ca_avg(student_id, subject, term_id):
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT score FROM ca_scores WHERE student_id=%s AND subject=%s AND term_id=%s",
                (student_id, subject, term_id))
    rows = cur.fetchall()
    cur.close(); con.close()
    if not rows: return None
    return sum(r[0] for r in rows) / len(rows)

def calc_final(student_id, subject, term_id):
    ca_w, ex_w, _ = term_weights(term_id)
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT score FROM exam_scores WHERE student_id=%s AND subject=%s AND term_id=%s",
                (student_id, subject, term_id))
    row = cur.fetchone()
    cur.close(); con.close()
    if not row: return None
    ca_avg = calc_ca_avg(student_id, subject, term_id)
    if ca_avg is None: return None
    return (ca_avg / 100) * ca_w + (row[0] / 100) * ex_w

def calc_student_average(student_id, term_id):
    finals = [calc_final(student_id, s, term_id) for s in allowed_subjects]
    finals = [f for f in finals if f is not None]
    return sum(finals)/len(finals) if finals else 0

def _assign_positions(rows, key):
    sorted_rows = sorted(rows, key=lambda x: x[key], reverse=True)
    for i, r in enumerate(sorted_rows):
        if i == 0:
            r["position"] = 1
        elif r[key] == sorted_rows[i-1][key]:
            r["position"] = sorted_rows[i-1]["position"]
        else:
            r["position"] = i + 1

def get_class_ranking(class_name, term_id):
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT id,name FROM students WHERE class_name=%s", (class_name,))
    studs = cur.fetchall()
    cur.close(); con.close()
    rows = []
    for s in studs:
        avg = calc_student_average(s[0], term_id)
        rows.append({"id":s[0],"name":s[1],"average":round(avg,2),"grade":get_grade(avg)})
    rows.sort(key=lambda x: x["average"], reverse=True)
    _assign_positions(rows, "average")
    return rows

def get_overall_position(class_name, student_id, term_id):
    ranking = get_class_ranking(class_name, term_id)
    total   = len(ranking)
    for r in ranking:
        if r["id"] == student_id:
            return r["position"], total
    return "-", total

def get_subject_position(student_id, subject, class_name, term_id):
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT id FROM students WHERE class_name=%s", (class_name,))
    studs = cur.fetchall()
    cur.close(); con.close()
    scores = []
    for s in studs:
        f = calc_final(s[0], subject, term_id)
        if f is not None:
            scores.append({"id":s[0], "score":f})
    scores.sort(key=lambda x: x["score"], reverse=True)
    _assign_positions(scores, "score")
    for s in scores:
        if s["id"] == student_id:
            return s["position"]
    return "-"

def is_teacher_allowed(username, subject, class_name):
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT id FROM subject_assignments WHERE username=%s AND subject=%s AND class_name=%s",
                (username, subject, class_name))
    row = cur.fetchone()
    cur.close(); con.close()
    return row is not None

# ── AUTH ─────────────────────────────────────────────────────
@app.route("/api/login", methods=["POST"])
def api_login():
    d = request.json
    u = d.get("username","").strip()
    p = d.get("password","")
    if not u or not p:
        return jsonify({"ok":False,"error":"Enter username and password"}), 400
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT * FROM users WHERE username=%s", (u,))
    row = cur.fetchone()
    user = row_to_dict(row, cur) if row else None
    cur.close(); con.close()
    if not user or not verify_password(p, user["password"]):
        return jsonify({"ok":False,"error":"Invalid username or password"}), 401
    return jsonify({"ok":True,"user":{
        "username":        user["username"],
        "role":            user["role"],
        "is_class_teacher":bool(user["is_class_teacher"]),
        "class_name":      user["class_name"] or "",
    }})

# ── ADMIN SETUP VIA ENV ──────────────────────────────────────
@app.route("/api/setup_admin", methods=["POST"])
def api_setup_admin():
    """One-time admin creation. Only works if no admin exists yet."""
    d = request.json
    secret   = d.get("secret","")
    username = d.get("username","").strip()
    password = d.get("password","")
    env_secret = os.environ.get("ADMIN_SETUP_SECRET","")
    if not env_secret or secret != env_secret:
        return jsonify({"ok":False,"error":"Invalid setup secret"}), 403
    if not username or not password:
        return jsonify({"ok":False,"error":"Username and password required"}), 400
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT username FROM users WHERE role='admin'")
    if cur.fetchone():
        cur.close(); con.close()
        return jsonify({"ok":False,"error":"Admin already exists"}), 409
    cur.execute("INSERT INTO users(username,password,role) VALUES(%s,%s,%s)",
                (username, hash_password(password), "admin"))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok":True})

# ── TEACHERS ─────────────────────────────────────────────────
@app.route("/api/teachers", methods=["GET"])
def api_get_teachers():
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT username,is_class_teacher,class_name FROM users WHERE role='teacher'")
    teachers = rows_to_dicts(cur.fetchall(), cur)
    result = []
    for t in teachers:
        cur.execute("SELECT subject,class_name FROM subject_assignments WHERE username=%s", (t["username"],))
        assignments = rows_to_dicts(cur.fetchall(), cur)
        result.append({
            "username":         t["username"],
            "is_class_teacher": bool(t["is_class_teacher"]),
            "class_name":       t["class_name"] or "",
            "assignments":      assignments,
        })
    cur.close(); con.close()
    return jsonify(result)

@app.route("/api/teachers", methods=["POST"])
def api_create_teacher():
    d = request.json
    username = d.get("username","").strip()
    password = d.get("password","").strip()
    if not username or not password:
        return jsonify({"ok":False,"error":"Username and password required"}), 400
    if len(password) < 4:
        return jsonify({"ok":False,"error":"Password must be at least 4 characters"}), 400
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT username FROM users WHERE username=%s", (username,))
    if cur.fetchone():
        cur.close(); con.close()
        return jsonify({"ok":False,"error":"Username already exists"}), 409
    cur.execute("INSERT INTO users(username,password,role) VALUES(%s,%s,%s)",
                (username, hash_password(password), "teacher"))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok":True})

@app.route("/api/teachers/<username>", methods=["DELETE"])
def api_delete_teacher(username):
    con = get_db()
    cur = con.cursor()
    cur.execute("DELETE FROM subject_assignments WHERE username=%s", (username,))
    cur.execute("DELETE FROM users WHERE username=%s AND role='teacher'", (username,))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok":True})

@app.route("/api/teachers/<username>/class_teacher", methods=["POST"])
def api_set_class_teacher(username):
    d     = request.json
    is_ct = bool(d.get("is_class_teacher", False))
    cls   = d.get("class_name","").lower().strip()
    if is_ct and cls not in classes:
        return jsonify({"ok":False,"error":"Invalid class"}), 400
    con = get_db()
    cur = con.cursor()
    cur.execute("UPDATE users SET is_class_teacher=%s, class_name=%s WHERE username=%s AND role='teacher'",
                (1 if is_ct else 0, cls if is_ct else None, username))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok":True})

# ── SUBJECT ASSIGNMENTS ──────────────────────────────────────
@app.route("/api/assign_teacher", methods=["POST"])
def api_assign_teacher():
    d        = request.json
    username = d.get("username","")
    subject  = d.get("subject","").lower().strip()
    cname    = d.get("class_name","").lower().strip()
    if subject not in allowed_subjects:
        return jsonify({"ok":False,"error":"Invalid subject"}), 400
    if cname not in classes:
        return jsonify({"ok":False,"error":"Invalid class"}), 400
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT username FROM users WHERE username=%s AND role='teacher'", (username,))
    if not cur.fetchone():
        cur.close(); con.close()
        return jsonify({"ok":False,"error":"Teacher not found"}), 404
    try:
        cur.execute("INSERT INTO subject_assignments(username,subject,class_name) VALUES(%s,%s,%s)",
                    (username, subject, cname))
        con.commit()
    except psycopg2.errors.UniqueViolation:
        con.rollback()
        cur.close(); con.close()
        return jsonify({"ok":False,"error":"Already assigned"}), 409
    cur.close(); con.close()
    return jsonify({"ok":True})

@app.route("/api/unassign_teacher", methods=["POST"])
def api_unassign_teacher():
    d = request.json
    username = d.get("username","")
    subject  = d.get("subject","").lower()
    cname    = d.get("class_name","").lower()
    con = get_db()
    cur = con.cursor()
    cur.execute("DELETE FROM subject_assignments WHERE username=%s AND subject=%s AND class_name=%s",
                (username, subject, cname))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok":True})

# ── STUDENTS ─────────────────────────────────────────────────
@app.route("/api/students", methods=["GET"])
def api_students():
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT id,name,class_name FROM students ORDER BY class_name,name")
    rows = rows_to_dicts(cur.fetchall(), cur)
    cur.close(); con.close()
    return jsonify(rows)

@app.route("/api/students", methods=["POST"])
def api_add_student():
    d     = request.json
    name  = d.get("name","").strip()
    cname = d.get("class_name","").lower().strip()
    if not name:
        return jsonify({"ok":False,"error":"Name required"}), 400
    if cname not in classes:
        return jsonify({"ok":False,"error":"Invalid class"}), 400
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT id FROM students WHERE LOWER(name)=LOWER(%s) AND class_name=%s", (name, cname))
    if cur.fetchone():
        cur.close(); con.close()
        return jsonify({"ok":False,"error":"Student already exists in this class"}), 409
    cur.execute("INSERT INTO students(name,class_name) VALUES(%s,%s)", (name, cname))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok":True})

@app.route("/api/students/<int:sid>", methods=["DELETE"])
def api_delete_student(sid):
    con = get_db()
    cur = con.cursor()
    cur.execute("DELETE FROM ca_scores   WHERE student_id=%s", (sid,))
    cur.execute("DELETE FROM exam_scores WHERE student_id=%s", (sid,))
    cur.execute("DELETE FROM remarks     WHERE student_id=%s", (sid,))
    cur.execute("DELETE FROM students    WHERE id=%s",         (sid,))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok":True})

# ── TERMS ────────────────────────────────────────────────────
@app.route("/api/terms", methods=["GET"])
def api_get_terms():
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT * FROM terms ORDER BY id DESC")
    rows = rows_to_dicts(cur.fetchall(), cur)
    cur.close(); con.close()
    return jsonify(rows)

@app.route("/api/terms/active", methods=["GET"])
def api_active_term():
    t = get_active_term()
    if not t:
        return jsonify({"ok":False,"error":"No active term"})
    return jsonify({"ok":True,"term":t})

@app.route("/api/terms", methods=["POST"])
def api_create_term():
    d         = request.json
    label     = d.get("label","").strip()
    ca_count  = int(d.get("ca_count", 2))
    ca_weight = int(d.get("ca_weight", 30))
    ex_weight = int(d.get("exam_weight", 70))
    if not label:
        return jsonify({"ok":False,"error":"Term label required"}), 400
    if ca_count < 1 or ca_count > 10:
        return jsonify({"ok":False,"error":"CA count must be 1–10"}), 400
    if ca_weight + ex_weight != 100:
        return jsonify({"ok":False,"error":"CA weight + Exam weight must equal 100"}), 400
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT id FROM terms WHERE status='open'")
    if cur.fetchone():
        cur.close(); con.close()
        return jsonify({"ok":False,"error":"Close the current term before opening a new one"}), 409
    cur.execute("INSERT INTO terms(label,ca_count,ca_weight,exam_weight,status) VALUES(%s,%s,%s,%s,'open')",
                (label, ca_count, ca_weight, ex_weight))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok":True})

@app.route("/api/terms/<int:term_id>/close", methods=["POST"])
def api_close_term(term_id):
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT * FROM terms WHERE id=%s", (term_id,))
    term = row_to_dict(cur.fetchone(), cur) if cur.rowcount else None
    cur.execute("SELECT status FROM terms WHERE id=%s", (term_id,))
    row = cur.fetchone()
    if not row:
        cur.close(); con.close()
        return jsonify({"ok":False,"error":"Term not found"}), 404
    if row[0] == "closed":
        cur.close(); con.close()
        return jsonify({"ok":False,"error":"Already closed"}), 400
    cur.execute("UPDATE terms SET status='closed' WHERE id=%s", (term_id,))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok":True})

# ── MARKS – CA ───────────────────────────────────────────────
@app.route("/api/marks/ca", methods=["POST"])
def api_enter_ca():
    d          = request.json
    username   = d.get("username","")
    subject    = d.get("subject","").lower().strip()
    class_name = d.get("class_name","").lower().strip()
    student_id = int(d.get("student_id"))
    ca_name    = d.get("ca_name","")
    score      = float(d.get("score"))

    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT role FROM users WHERE username=%s", (username,))
    user = cur.fetchone()
    if not user or user[0] != "teacher":
        cur.close(); con.close()
        return jsonify({"ok":False,"error":"Only teachers can enter marks"}), 403
    cur.close(); con.close()

    if not is_teacher_allowed(username, subject, class_name):
        return jsonify({"ok":False,"error":"Access denied – not your assignment"}), 403
    if not (0 <= score <= 100):
        return jsonify({"ok":False,"error":"Score must be 0–100"}), 400

    term = get_active_term()
    if not term:
        return jsonify({"ok":False,"error":"No active term. Ask admin to open a term first."}), 400
    term_id  = term["id"]
    ca_count = term["ca_count"]

    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT id FROM students WHERE id=%s AND class_name=%s", (student_id, class_name))
    if not cur.fetchone():
        cur.close(); con.close()
        return jsonify({"ok":False,"error":"Student not found in that class"}), 404

    cur.execute("SELECT ca_name FROM ca_scores WHERE student_id=%s AND subject=%s AND term_id=%s",
                (student_id, subject, term_id))
    existing = [r[0] for r in cur.fetchall()]
    if ca_name not in existing and len(existing) >= ca_count:
        cur.close(); con.close()
        return jsonify({"ok":False,"error":f"CA limit ({ca_count}) reached for this term"}), 400

    cur.execute("""
        INSERT INTO ca_scores(student_id,subject,class_name,ca_name,score,entered_by,term_id)
        VALUES(%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT(student_id,subject,ca_name,term_id)
        DO UPDATE SET score=EXCLUDED.score, entered_by=EXCLUDED.entered_by
    """, (student_id, subject, class_name, ca_name, score, username, term_id))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok":True})

# ── MARKS – EXAM ─────────────────────────────────────────────
@app.route("/api/marks/exam", methods=["POST"])
def api_enter_exam():
    d          = request.json
    username   = d.get("username","")
    subject    = d.get("subject","").lower().strip()
    class_name = d.get("class_name","").lower().strip()
    student_id = int(d.get("student_id"))
    score      = float(d.get("score"))

    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT role FROM users WHERE username=%s", (username,))
    user = cur.fetchone()
    if not user or user[0] != "teacher":
        cur.close(); con.close()
        return jsonify({"ok":False,"error":"Only teachers can enter marks"}), 403
    cur.close(); con.close()

    if not is_teacher_allowed(username, subject, class_name):
        return jsonify({"ok":False,"error":"Access denied – not your assignment"}), 403
    if not (0 <= score <= 100):
        return jsonify({"ok":False,"error":"Score must be 0–100"}), 400

    term = get_active_term()
    if not term:
        return jsonify({"ok":False,"error":"No active term. Ask admin to open a term first."}), 400
    term_id = term["id"]

    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT id FROM students WHERE id=%s AND class_name=%s", (student_id, class_name))
    if not cur.fetchone():
        cur.close(); con.close()
        return jsonify({"ok":False,"error":"Student not found in that class"}), 404
    cur.execute("""
        INSERT INTO exam_scores(student_id,subject,class_name,score,entered_by,term_id)
        VALUES(%s,%s,%s,%s,%s,%s)
        ON CONFLICT(student_id,subject,term_id)
        DO UPDATE SET score=EXCLUDED.score, entered_by=EXCLUDED.entered_by
    """, (student_id, subject, class_name, score, username, term_id))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok":True})

# ── REPORT CARD ──────────────────────────────────────────────
@app.route("/api/report/<int:sid>", methods=["GET"])
def api_report(sid):
    term_id = request.args.get("term_id")
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT * FROM students WHERE id=%s", (sid,))
    row = cur.fetchone()
    student = row_to_dict(row, cur) if row else None
    cur.close(); con.close()
    if not student:
        return jsonify({"ok":False,"error":"Student not found"}), 404

    term = get_term_by_id(int(term_id)) if term_id else get_active_term()
    if not term:
        return jsonify({"ok":False,"error":"No term available"}), 400

    term_id    = term["id"]
    ca_count   = term["ca_count"]
    class_name = student["class_name"]
    pos, total = get_overall_position(class_name, sid, term_id)
    avg        = calc_student_average(sid, term_id)

    rows = []
    for subject in allowed_subjects:
        con = get_db()
        cur = con.cursor()
        cur.execute("SELECT ca_name,score FROM ca_scores WHERE student_id=%s AND subject=%s AND term_id=%s",
                    (sid, subject, term_id))
        ca_rows = cur.fetchall()
        cur.execute("SELECT score FROM exam_scores WHERE student_id=%s AND subject=%s AND term_id=%s",
                    (sid, subject, term_id))
        exam_row = cur.fetchone()
        cur.close(); con.close()

        ca_map    = {r[0]: r[1] for r in ca_rows}
        ca_scores = {f"CA{i}": ca_map.get(f"CA{i}") for i in range(1, ca_count+1)}
        exam_val  = exam_row[0] if exam_row else None
        final_val = calc_final(sid, subject, term_id)
        subj_pos  = get_subject_position(sid, subject, class_name, term_id) if final_val is not None else "-"
        rows.append({
            "subject":  subject,
            "ca":       ca_scores,
            "exam":     exam_val,
            "final":    round(final_val,1) if final_val is not None else None,
            "grade":    get_grade(final_val) if final_val is not None else "-",
            "position": subj_pos,
        })

    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT * FROM remarks WHERE student_id=%s AND term_id=%s", (sid, term_id))
    remark_row = cur.fetchone()
    remark = row_to_dict(remark_row, cur) if remark_row else None
    cur.close(); con.close()

    return jsonify({
        "ok":True,
        "student":             student,
        "term":                term,
        "rows":                rows,
        "average":             round(avg,2),
        "grade":               get_grade(avg),
        "position":            pos,
        "total_students":      total,
        "class_teacher_remark":remark["class_teacher_remark"] if remark else "",
        "head_remark":         remark["head_remark"] if remark else "",
        "ca_count":            ca_count,
        "ca_weight":           term["ca_weight"],
        "exam_weight":         term["exam_weight"],
    })

# ── REMARKS ──────────────────────────────────────────────────
@app.route("/api/remarks", methods=["POST"])
def api_remarks():
    d        = request.json
    username = d.get("username","")
    role     = d.get("role","")
    is_ct    = d.get("is_class_teacher", False)
    sid      = int(d.get("student_id"))
    remark   = d.get("remark","").strip()

    term = get_active_term()
    if not term:
        return jsonify({"ok":False,"error":"No active term"}), 400
    term_id = term["id"]

    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT class_name FROM students WHERE id=%s", (sid,))
    student = cur.fetchone()
    if not student:
        cur.close(); con.close()
        return jsonify({"ok":False,"error":"Student not found"}), 404

    if role == "admin":
        field = "head_remark"
    elif role == "teacher" and is_ct:
        cur.execute("SELECT class_name FROM users WHERE username=%s AND is_class_teacher=1", (username,))
        u = cur.fetchone()
        if not u or u[0] != student[0]:
            cur.close(); con.close()
            return jsonify({"ok":False,"error":"Not your class"}), 403
        field = "class_teacher_remark"
    else:
        cur.close(); con.close()
        return jsonify({"ok":False,"error":"Not allowed"}), 403

    cur.execute(f"""
        INSERT INTO remarks(student_id, term_id, {field}) VALUES(%s,%s,%s)
        ON CONFLICT(student_id, term_id) DO UPDATE SET {field}=EXCLUDED.{field}
    """, (sid, term_id, remark))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok":True})

# ── RANKINGS ─────────────────────────────────────────────────
@app.route("/api/ranking/subject", methods=["GET"])
def api_subject_ranking():
    subject    = request.args.get("subject","").lower()
    class_name = request.args.get("class_name","").lower()
    assess     = request.args.get("assess","exam")
    term_id    = request.args.get("term_id")

    if not term_id:
        term = get_active_term()
        if not term: return jsonify([])
        term_id = term["id"]
    else:
        term_id = int(term_id)

    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT id,name FROM students WHERE class_name=%s", (class_name,))
    studs = cur.fetchall()
    cur.close(); con.close()

    rows = []
    for s in studs:
        score = None
        con = get_db()
        cur = con.cursor()
        if assess == "exam":
            cur.execute("SELECT score FROM exam_scores WHERE student_id=%s AND subject=%s AND term_id=%s",
                        (s[0], subject, term_id))
            r = cur.fetchone()
            score = r[0] if r else None
        else:
            cur.execute("SELECT score FROM ca_scores WHERE student_id=%s AND subject=%s AND ca_name=%s AND term_id=%s",
                        (s[0], subject, assess, term_id))
            r = cur.fetchone()
            score = r[0] if r else None
        cur.close(); con.close()
        if score is not None:
            rows.append({"id":s[0],"name":s[1],"score":round(score,2),"grade":get_grade(score)})

    rows.sort(key=lambda x: x["score"], reverse=True)
    _assign_positions(rows, "score")
    return jsonify(rows)

# ── SCORE SHEETS ─────────────────────────────────────────────
@app.route("/api/scoresheet", methods=["GET"])
def api_scoresheet():
    mode       = request.args.get("mode","ca")
    class_name = request.args.get("class_name","").lower()
    ca_name    = request.args.get("ca_name","CA1")
    term_id    = request.args.get("term_id")

    if not term_id:
        term = get_active_term()
        if not term: return jsonify({"subjects":[],"results":[]})
        term_id = term["id"]
    else:
        term_id = int(term_id)

    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT id,name FROM students WHERE class_name=%s ORDER BY name", (class_name,))
    studs = cur.fetchall()
    cur.close(); con.close()

    results = []
    for s in studs:
        row = {"id":s[0],"name":s[1],"scores":{},"total":0,"count":0}
        for subject in allowed_subjects:
            score = None
            con = get_db()
            cur = con.cursor()
            if mode == "ca":
                cur.execute("SELECT score FROM ca_scores WHERE student_id=%s AND subject=%s AND ca_name=%s AND term_id=%s",
                            (s[0], subject, ca_name, term_id))
                r = cur.fetchone()
                score = r[0] if r else None
            elif mode == "exam":
                cur.execute("SELECT score FROM exam_scores WHERE student_id=%s AND subject=%s AND term_id=%s",
                            (s[0], subject, term_id))
                r = cur.fetchone()
                score = r[0] if r else None
            elif mode == "terminal":
                cur.close(); con.close()
                f = calc_final(s[0], subject, term_id)
                score = round(f,1) if f is not None else None
                con = None
            if con:
                cur.close(); con.close()
            row["scores"][subject] = score
            if score is not None:
                row["total"] += score; row["count"] += 1
        row["average"] = round(row["total"]/row["count"],2) if row["count"] else 0
        row["grade"]   = get_grade(row["average"])
        results.append(row)

    results.sort(key=lambda x: x["average"], reverse=True)
    _assign_positions(results, "average")
    return jsonify({"subjects": allowed_subjects, "results": results})

# ── CONFIG ───────────────────────────────────────────────────
@app.route("/api/config", methods=["GET"])
def api_config():
    term = get_active_term()
    return jsonify({
        "allowed_subjects": allowed_subjects,
        "classes":          classes,
        "active_term":      term,
        "ca_count":         term["ca_count"] if term else 2,
    })

# ── PDF ──────────────────────────────────────────────────────
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm

def _blue_sheet_pdf(filename, subtitle, class_students, subjects, get_score_fn, term=None):
    H_BG  = colors.HexColor("#1A6FA8")
    S_BG  = colors.HexColor("#5BA4CF")
    ODD   = colors.HexColor("#E8F4FC")
    EVEN  = colors.white
    RED   = colors.HexColor("#C0392B")
    WHITE = colors.white
    doc = SimpleDocTemplate(filename, pagesize=landscape(A4),
                            rightMargin=1.2*cm, leftMargin=1.2*cm,
                            topMargin=1.2*cm, bottomMargin=1.2*cm)
    styles = getSampleStyleSheet()
    story  = []
    t_s = ParagraphStyle("T",parent=styles["Title"],fontSize=14,textColor=H_BG,spaceAfter=2)
    s_s = ParagraphStyle("S",parent=styles["Normal"],fontSize=8,alignment=1,spaceAfter=6)
    term_label = term["label"] if term else ""
    story += [Paragraph("SCHOOL NAME",t_s),
              Paragraph(f"{subtitle}  {'| '+term_label if term_label else ''}",s_s),
              Spacer(1,0.3*cm)]

    results = []
    for s in class_students:
        row = {"name":s["name"],"scores":{},"total":0,"count":0}
        for subj in subjects:
            sc = get_score_fn(s["id"], subj)
            row["scores"][subj] = sc
            if sc is not None: row["total"] += sc; row["count"] += 1
        row["average"] = row["total"]/row["count"] if row["count"] else 0
        row["grade"]   = get_grade(row["average"])
        results.append(row)

    results.sort(key=lambda x: x["average"], reverse=True)
    _assign_positions(results, "average")

    hdr = ["#","Student"]+[s[:5].title() for s in subjects]+["Total","Avg","Pos","Grd"]
    tdata = [hdr]
    fail_cells = []
    for ri,r in enumerate(results,1):
        row = [str(r["position"]), r["name"]]
        for ci,subj in enumerate(subjects):
            sc = r["scores"][subj]
            if sc is not None:
                if sc < 50: fail_cells.append((ri,ci+2))
                row.append(f"{sc:.1f}")
            else: row.append("-")
        row += [f"{r['total']:.1f}" if r["count"] else "-",
                f"{r['average']:.1f}" if r["count"] else "-",
                str(r["position"]), r["grade"] if r["count"] else "-"]
        tdata.append(row)

    n  = len(subjects)
    cw = [0.7*cm,3.4*cm]+[1.25*cm]*n+[1.5*cm,1.3*cm,0.9*cm,1.0*cm]
    tbl = Table(tdata, colWidths=cw, repeatRows=1)
    ts = [
        ("BACKGROUND",(0,0),(-1,0),H_BG),("TEXTCOLOR",(0,0),(-1,0),WHITE),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,0),6.5),
        ("ALIGN",(0,0),(-1,0),"CENTER"),
        ("FONTNAME",(0,1),(-1,-1),"Helvetica"),("FONTSIZE",(0,1),(-1,-1),7),
        ("ALIGN",(0,1),(-1,-1),"CENTER"),("ALIGN",(1,1),(1,-1),"LEFT"),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[ODD,EVEN]),
        ("GRID",(0,0),(-1,-1),0.4,colors.HexColor("#A0C4E0")),
        ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3),
        ("BACKGROUND",(-4,0),(-1,0),S_BG),("FONTNAME",(-4,1),(-1,-1),"Helvetica-Bold"),
    ]
    for (ri,ci) in fail_cells: ts.append(("TEXTCOLOR",(ci,ri),(ci,ri),RED))
    tbl.setStyle(TableStyle(ts))
    story.append(tbl)
    story.append(Spacer(1,0.3*cm))
    ft = ParagraphStyle("F",parent=styles["Normal"],fontSize=6.5,textColor=colors.grey,alignment=2)
    story.append(Paragraph(f"Generated  |  {len(class_students)} students  |  {term_label}",ft))
    doc.build(story)


@app.route("/api/pdf/report/<int:sid>", methods=["GET"])
def pdf_report(sid):
    term_id = request.args.get("term_id")
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT * FROM students WHERE id=%s", (sid,))
    row = cur.fetchone()
    student = row_to_dict(row, cur) if row else None
    cur.close(); con.close()
    if not student: return jsonify({"error":"Not found"}), 404

    term = get_term_by_id(int(term_id)) if term_id else get_active_term()
    if not term: return jsonify({"error":"No term available"}), 400

    term_id   = term["id"]
    ca_count  = term["ca_count"]
    ca_weight = term["ca_weight"]
    ex_weight = term["exam_weight"]
    class_name = student["class_name"]
    pos, total = get_overall_position(class_name, sid, term_id)
    avg        = calc_student_average(sid, term_id)

    safe  = student["name"].replace(" ","_")
    fname = os.path.join(tempfile.gettempdir(), f"ReportCard_{safe}_{term_id}.pdf")
    doc   = SimpleDocTemplate(fname, pagesize=A4,
                              rightMargin=1.5*cm, leftMargin=1.5*cm,
                              topMargin=1.5*cm, bottomMargin=1.5*cm)
    styles = getSampleStyleSheet()
    story  = []
    H_BG  = colors.HexColor("#1A6FA8")
    ODD   = colors.HexColor("#E8F4FC")
    WHITE = colors.white
    RED   = colors.HexColor("#C0392B")

    t_s = ParagraphStyle("T",parent=styles["Title"],fontSize=16,textColor=H_BG,spaceAfter=2)
    s_s = ParagraphStyle("S",parent=styles["Normal"],fontSize=9,alignment=1,spaceAfter=4)
    story += [Paragraph("SCHOOL NAME",t_s), Paragraph("STUDENT REPORT CARD",s_s), Spacer(1,0.3*cm)]

    info = [
        ["Name:",     student["name"],      "Class:",    student["class_name"].title()],
        ["Term:",     term["label"],         "Weights:",  f"CA {ca_weight}% | Exam {ex_weight}%"],
        ["Position:", f"{pos}/{total}",      "Grade:",    get_grade(avg)],
    ]
    it = Table(info, colWidths=[3*cm,6*cm,3*cm,5*cm])
    it.setStyle(TableStyle([
        ("FONTNAME",(0,0),(-1,-1),"Helvetica"),
        ("FONTNAME",(0,0),(0,-1),"Helvetica-Bold"),
        ("FONTNAME",(2,0),(2,-1),"Helvetica-Bold"),
        ("FONTSIZE",(0,0),(-1,-1),9),
        ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3),
    ]))
    story += [it, Spacer(1,0.4*cm)]

    hdr = ["Subject"]+[f"CA{i}" for i in range(1,ca_count+1)]+["Exam","Final","Pos","Grd","Remark","Sign"]
    tdata = [hdr]
    tot, cnt = 0, 0
    fail_rows = []
    for subject in allowed_subjects:
        con = get_db()
        cur = con.cursor()
        cur.execute("SELECT ca_name,score FROM ca_scores WHERE student_id=%s AND subject=%s AND term_id=%s",
                    (sid, subject, term_id))
        ca_rows = cur.fetchall()
        cur.execute("SELECT score FROM exam_scores WHERE student_id=%s AND subject=%s AND term_id=%s",
                    (sid, subject, term_id))
        exam_row = cur.fetchone()
        cur.close(); con.close()

        ca_map = {r[0]:r[1] for r in ca_rows}
        row = [subject.title()]
        for i in range(1, ca_count+1):
            v = ca_map.get(f"CA{i}")
            row.append(f"{v:.1f}" if v is not None else "-")
        exam_v = exam_row[0] if exam_row else None
        row.append(f"{exam_v:.1f}" if exam_v is not None else "-")
        final_v = calc_final(sid, subject, term_id)
        if final_v is not None: tot += final_v; cnt += 1
        row.append(f"{final_v:.1f}" if final_v is not None else "-")
        row.append(str(get_subject_position(sid,subject,class_name,term_id)) if final_v is not None else "-")
        row.append(get_grade(final_v) if final_v is not None else "-")
        row += ["",""]
        if final_v is not None and final_v < 50: fail_rows.append(len(tdata))
        tdata.append(row)

    ca_w = 1.1*cm
    cw   = [4.0*cm]+[ca_w]*ca_count+[1.4*cm,1.4*cm,1.0*cm,1.1*cm,2.4*cm,1.6*cm]
    mt   = Table(tdata, colWidths=cw, repeatRows=1)
    mts  = [
        ("BACKGROUND",(0,0),(-1,0),H_BG),("TEXTCOLOR",(0,0),(-1,0),WHITE),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),7.5),
        ("ALIGN",(0,0),(-1,-1),"CENTER"),("ALIGN",(0,1),(0,-1),"LEFT"),
        ("GRID",(0,0),(-1,-1),0.4,colors.HexColor("#A0C4E0")),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[ODD,WHITE]),
        ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3),
    ]
    for ri in fail_rows: mts.append(("TEXTCOLOR",(0,ri),(-1,ri),RED))
    mt.setStyle(TableStyle(mts))
    story += [mt, Spacer(1,0.4*cm)]

    comp_avg = tot/cnt if cnt else 0
    sm = Table([["AVERAGE",f"{comp_avg:.2f}","GRADE",get_grade(comp_avg),"POSITION",f"{pos}/{total}"]],
               colWidths=[3*cm,3*cm,2*cm,2*cm,3*cm,4*cm])
    sm.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1),H_BG),("TEXTCOLOR",(0,0),(-1,-1),WHITE),
        ("FONTNAME",(0,0),(-1,-1),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),9),
        ("ALIGN",(0,0),(-1,-1),"CENTER"),
        ("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5),
    ]))
    story += [sm, Spacer(1,0.4*cm)]

    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT * FROM remarks WHERE student_id=%s AND term_id=%s", (sid, term_id))
    remark_row = cur.fetchone()
    rmk = row_to_dict(remark_row, cur) if remark_row else None
    cur.close(); con.close()

    rm_data = [
        ["Class Teacher Remark:", rmk["class_teacher_remark"] if rmk else "________________________"],
        ["Head of School Remark:", rmk["head_remark"] if rmk else "________________________"],
    ]
    rmt = Table(rm_data, colWidths=[5*cm,12*cm])
    rmt.setStyle(TableStyle([
        ("FONTNAME",(0,0),(0,-1),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),8),
        ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),
        ("LINEBELOW",(1,0),(1,-1),0.5,colors.grey),
    ]))
    story += [rmt, Spacer(1,0.4*cm)]
    sig = Table([["Class Teacher Sign: _______________","Head Sign: _______________","Date: _______________"]],
                colWidths=[6*cm,6*cm,5*cm])
    sig.setStyle(TableStyle([("FONTSIZE",(0,0),(-1,-1),7.5),("FONTNAME",(0,0),(-1,-1),"Helvetica")]))
    story.append(sig)
    doc.build(story)
    return send_file(fname, as_attachment=True,
                     download_name=f"ReportCard_{student['name'].replace(' ','_')}_{term['label'].replace(' ','_')}.pdf",
                     mimetype="application/pdf")


@app.route("/api/pdf/ca_sheet", methods=["GET"])
def pdf_ca_sheet():
    class_name = request.args.get("class_name","").lower()
    ca_name    = request.args.get("ca_name","CA1")
    term_id    = request.args.get("term_id")
    term = get_term_by_id(int(term_id)) if term_id else get_active_term()
    if not term: return jsonify({"error":"No term"}), 400
    tid   = term["id"]
    fname = os.path.join(tempfile.gettempdir(), f"CA_{class_name.replace(' ','')}_{ca_name}_{tid}.pdf")
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT id,name FROM students WHERE class_name=%s ORDER BY name", (class_name,))
    cs = [{"id":r[0],"name":r[1]} for r in cur.fetchall()]
    cur.close(); con.close()
    if not cs: return jsonify({"error":"No students"}), 404
    def get_score(sid, subj):
        con = get_db(); cur = con.cursor()
        cur.execute("SELECT score FROM ca_scores WHERE student_id=%s AND subject=%s AND ca_name=%s AND term_id=%s",
                    (sid, subj, ca_name, tid))
        r = cur.fetchone(); cur.close(); con.close()
        return r[0] if r else None
    _blue_sheet_pdf(fname, f"{ca_name.upper()} SCORE SHEET  |  {class_name.title()}",
                    cs, allowed_subjects, get_score, term)
    return send_file(fname, as_attachment=True,
                     download_name=os.path.basename(fname), mimetype="application/pdf")


@app.route("/api/pdf/terminal_sheet", methods=["GET"])
def pdf_terminal_sheet():
    class_name = request.args.get("class_name","").lower()
    term_id    = request.args.get("term_id")
    term = get_term_by_id(int(term_id)) if term_id else get_active_term()
    if not term: return jsonify({"error":"No term"}), 400
    tid   = term["id"]
    fname = os.path.join(tempfile.gettempdir(), f"Terminal_{class_name.replace(' ','')}_{tid}.pdf")
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT id,name FROM students WHERE class_name=%s ORDER BY name", (class_name,))
    cs = [{"id":r[0],"name":r[1]} for r in cur.fetchall()]
    cur.close(); con.close()
    if not cs: return jsonify({"error":"No students"}), 404
    def get_score(sid, subj):
        f = calc_final(sid, subj, tid)
        return round(f,1) if f is not None else None
    _blue_sheet_pdf(fname,
                    f"TERMINAL SCORE SHEET  |  {class_name.title()}  (CA {term['ca_weight']}% + Exam {term['exam_weight']}%)",
                    cs, allowed_subjects, get_score, term)
    return send_file(fname, as_attachment=True,
                     download_name=os.path.basename(fname), mimetype="application/pdf")

# ── SERVE FRONTEND ───────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")

@app.route("/setup")
def setup_page():
    return send_from_directory(BASE_DIR, "setup.html")

# ── STARTUP ──────────────────────────────────────────────────
with app.app_context():
    try:
        init_db()
    except Exception as e:
        print(f"DB init warning: {e}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
