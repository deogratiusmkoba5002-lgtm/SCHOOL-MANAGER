"""
School Manager – Flask API Backend (v3)
Run setup_admin.py FIRST, then run this.
Open http://localhost:5000
"""
import sqlite3, hashlib, os, tempfile, secrets
from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE  = os.path.join(BASE_DIR, "school.db")

allowed_subjects = [
    "mathematics","physics","chemistry","biology",
    "geography","history","civics","english",
    "literature","kiswahili","bible knowledge",
    "book keeping","commerce","business studies",
    "historia ya tanzania na maadili",
]
classes = ["form 1","form 2","form 3","form 4"]

# ── DB ──────────────────────────────────────────────────────
def get_db():
    con = sqlite3.connect(DB_FILE)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con

def qone(cur, sql, params=()):
    return cur.execute(sql, params).fetchone()

def qall(cur, sql, params=()):
    return cur.execute(sql, params).fetchall()

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
    row = qone(con.cursor(), "SELECT * FROM terms WHERE status='open' ORDER BY id DESC LIMIT 1")
    con.close()
    return dict(row) if row else None

def get_term_by_id(term_id):
    con = get_db()
    row = qone(con.cursor(), "SELECT * FROM terms WHERE id=?", (term_id,))
    con.close()
    return dict(row) if row else None

def term_weights(term_id):
    t = get_term_by_id(term_id)
    if not t:
        return 30, 70, 2
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
    rows = qall(con.cursor(),
        "SELECT score FROM ca_scores WHERE student_id=? AND subject=? AND term_id=?",
        (student_id, subject, term_id))
    con.close()
    if not rows: return None
    return sum(r["score"] for r in rows) / len(rows)

def calc_final(student_id, subject, term_id):
    ca_w, ex_w, _ = term_weights(term_id)
    con = get_db()
    exam = qone(con.cursor(),
        "SELECT score FROM exam_scores WHERE student_id=? AND subject=? AND term_id=?",
        (student_id, subject, term_id))
    con.close()
    if not exam: return None
    ca_avg = calc_ca_avg(student_id, subject, term_id)
    if ca_avg is None: return None
    return (ca_avg / 100) * ca_w + (exam["score"] / 100) * ex_w

def calc_student_average(student_id, term_id):
    finals = [calc_final(student_id, s, term_id) for s in allowed_subjects]
    finals = [f for f in finals if f is not None]
    return sum(finals)/len(finals) if finals else 0

def _assign_positions(rows, key):
    """Correct position assignment with proper tie handling."""
    sorted_rows = sorted(rows, key=lambda x: x[key], reverse=True)
    pos = 1
    for i, r in enumerate(sorted_rows):
        if i == 0:
            r["position"] = 1
        elif r[key] == sorted_rows[i-1][key]:
            r["position"] = sorted_rows[i-1]["position"]
        else:
            r["position"] = i + 1
        pos = r["position"]

def get_class_ranking(class_name, term_id):
    con = get_db()
    studs = qall(con.cursor(), "SELECT id,name FROM students WHERE class_name=?", (class_name,))
    con.close()
    rows = []
    for s in studs:
        avg = calc_student_average(s["id"], term_id)
        rows.append({"id":s["id"],"name":s["name"],"average":round(avg,2),"grade":get_grade(avg)})
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
    studs = qall(con.cursor(), "SELECT id FROM students WHERE class_name=?", (class_name,))
    con.close()
    scores = []
    for s in studs:
        f = calc_final(s["id"], subject, term_id)
        if f is not None:
            scores.append({"id":s["id"], "score":f})
    scores.sort(key=lambda x: x["score"], reverse=True)
    _assign_positions(scores, "score")
    for s in scores:
        if s["id"] == student_id:
            return s["position"]
    return "-"

def is_teacher_allowed(username, subject, class_name):
    con = get_db()
    row = qone(con.cursor(),
        "SELECT id FROM subject_assignments WHERE username=? AND subject=? AND class_name=?",
        (username, subject, class_name))
    con.close()
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
    row = qone(con.cursor(), "SELECT * FROM users WHERE username=?", (u,))
    con.close()
    if not row or not verify_password(p, row["password"]):
        return jsonify({"ok":False,"error":"Invalid username or password"}), 401
    return jsonify({"ok":True,"user":{
        "username":        row["username"],
        "role":            row["role"],
        "is_class_teacher":bool(row["is_class_teacher"]),
        "class_name":      row["class_name"] or "",
    }})

# ── TEACHERS ─────────────────────────────────────────────────
@app.route("/api/teachers", methods=["GET"])
def api_get_teachers():
    con = get_db()
    teachers = qall(con.cursor(),
        "SELECT username,is_class_teacher,class_name FROM users WHERE role='teacher'")
    result = []
    for t in teachers:
        assignments = qall(con.cursor(),
            "SELECT subject,class_name FROM subject_assignments WHERE username=?", (t["username"],))
        result.append({
            "username":         t["username"],
            "is_class_teacher": bool(t["is_class_teacher"]),
            "class_name":       t["class_name"] or "",
            "assignments":      [{"subject":a["subject"],"class_name":a["class_name"]} for a in assignments],
        })
    con.close()
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
    if qone(con.cursor(), "SELECT username FROM users WHERE username=?", (username,)):
        con.close()
        return jsonify({"ok":False,"error":"Username already exists"}), 409
    con.execute("INSERT INTO users(username,password,role) VALUES(?,?,?)",
                (username, hash_password(password), "teacher"))
    con.commit(); con.close()
    return jsonify({"ok":True})

@app.route("/api/teachers/<username>", methods=["DELETE"])
def api_delete_teacher(username):
    con = get_db()
    con.execute("DELETE FROM subject_assignments WHERE username=?", (username,))
    con.execute("DELETE FROM users WHERE username=? AND role='teacher'", (username,))
    con.commit(); con.close()
    return jsonify({"ok":True})

@app.route("/api/teachers/<username>/class_teacher", methods=["POST"])
def api_set_class_teacher(username):
    d     = request.json
    is_ct = bool(d.get("is_class_teacher", False))
    cls   = d.get("class_name","").lower().strip()
    if is_ct and cls not in classes:
        return jsonify({"ok":False,"error":"Invalid class"}), 400
    con = get_db()
    con.execute("UPDATE users SET is_class_teacher=?, class_name=? WHERE username=? AND role='teacher'",
                (1 if is_ct else 0, cls if is_ct else None, username))
    con.commit(); con.close()
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
    if not qone(con.cursor(),"SELECT username FROM users WHERE username=? AND role='teacher'",(username,)):
        con.close()
        return jsonify({"ok":False,"error":"Teacher not found"}), 404
    try:
        con.execute("INSERT INTO subject_assignments(username,subject,class_name) VALUES(?,?,?)",
                    (username, subject, cname))
        con.commit()
    except sqlite3.IntegrityError:
        con.close()
        return jsonify({"ok":False,"error":"Already assigned"}), 409
    con.close()
    return jsonify({"ok":True})

@app.route("/api/unassign_teacher", methods=["POST"])
def api_unassign_teacher():
    d = request.json
    username = d.get("username","")
    subject  = d.get("subject","").lower()
    cname    = d.get("class_name","").lower()
    con = get_db()
    con.execute("DELETE FROM subject_assignments WHERE username=? AND subject=? AND class_name=?",
                (username, subject, cname))
    con.commit(); con.close()
    return jsonify({"ok":True})

# ── STUDENTS ─────────────────────────────────────────────────
@app.route("/api/students", methods=["GET"])
def api_students():
    con = get_db()
    rows = qall(con.cursor(), "SELECT id,name,class_name FROM students ORDER BY class_name,name")
    con.close()
    return jsonify([dict(r) for r in rows])

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
    if qone(con.cursor(),
            "SELECT id FROM students WHERE LOWER(name)=LOWER(?) AND class_name=?", (name, cname)):
        con.close()
        return jsonify({"ok":False,"error":"Student already exists in this class"}), 409
    con.execute("INSERT INTO students(name,class_name) VALUES(?,?)", (name, cname))
    con.commit(); con.close()
    return jsonify({"ok":True})

@app.route("/api/students/<int:sid>", methods=["DELETE"])
def api_delete_student(sid):
    con = get_db()
    con.execute("DELETE FROM ca_scores   WHERE student_id=?", (sid,))
    con.execute("DELETE FROM exam_scores WHERE student_id=?", (sid,))
    con.execute("DELETE FROM remarks     WHERE student_id=?", (sid,))
    con.execute("DELETE FROM students    WHERE id=?",         (sid,))
    con.commit(); con.close()
    return jsonify({"ok":True})

# ── TERMS ────────────────────────────────────────────────────
@app.route("/api/terms", methods=["GET"])
def api_get_terms():
    con = get_db()
    rows = qall(con.cursor(), "SELECT * FROM terms ORDER BY id DESC")
    con.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/terms/active", methods=["GET"])
def api_active_term():
    t = get_active_term()
    if not t:
        return jsonify({"ok":False,"error":"No active term"})
    return jsonify({"ok":True,"term":t})

@app.route("/api/terms", methods=["POST"])
def api_create_term():
    """Admin creates a new open term. Only one can be open at a time."""
    d = request.json
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
    # Only one open term allowed
    existing_open = qone(con.cursor(), "SELECT id FROM terms WHERE status='open'")
    if existing_open:
        con.close()
        return jsonify({"ok":False,"error":"Close the current term before opening a new one"}), 409

    con.execute("""
        INSERT INTO terms(label, ca_count, ca_weight, exam_weight, status)
        VALUES(?,?,?,?,'open')
    """, (label, ca_count, ca_weight, ex_weight))
    con.commit(); con.close()
    return jsonify({"ok":True})

@app.route("/api/terms/<int:term_id>/close", methods=["POST"])
def api_close_term(term_id):
    """Admin closes a term — all marks become read-only."""
    con = get_db()
    term = qone(con.cursor(), "SELECT * FROM terms WHERE id=?", (term_id,))
    if not term:
        con.close()
        return jsonify({"ok":False,"error":"Term not found"}), 404
    if term["status"] == "closed":
        con.close()
        return jsonify({"ok":False,"error":"Term is already closed"}), 400
    con.execute("UPDATE terms SET status='closed' WHERE id=?", (term_id,))
    con.commit(); con.close()
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

    # role check
    con = get_db()
    user = qone(con.cursor(), "SELECT role FROM users WHERE username=?", (username,))
    con.close()
    if not user or user["role"] != "teacher":
        return jsonify({"ok":False,"error":"Only teachers can enter marks"}), 403
    if not is_teacher_allowed(username, subject, class_name):
        return jsonify({"ok":False,"error":"Access denied – not your assignment"}), 403
    if not (0 <= score <= 100):
        return jsonify({"ok":False,"error":"Score must be 0–100"}), 400

    # active term check
    term = get_active_term()
    if not term:
        return jsonify({"ok":False,"error":"No active term. Ask admin to open a term first."}), 400
    term_id = term["id"]
    ca_count = term["ca_count"]

    con = get_db()
    if not qone(con.cursor(),"SELECT id FROM students WHERE id=? AND class_name=?",(student_id,class_name)):
        con.close()
        return jsonify({"ok":False,"error":"Student not found in that class"}), 404

    existing = qall(con.cursor(),
        "SELECT ca_name FROM ca_scores WHERE student_id=? AND subject=? AND term_id=?",
        (student_id, subject, term_id))
    ca_names = [r["ca_name"] for r in existing]
    if ca_name not in ca_names and len(ca_names) >= ca_count:
        con.close()
        return jsonify({"ok":False,"error":f"CA limit ({ca_count}) reached for this term"}), 400

    con.execute("""
        INSERT INTO ca_scores(student_id,subject,class_name,ca_name,score,entered_by,term_id)
        VALUES(?,?,?,?,?,?,?)
        ON CONFLICT(student_id,subject,ca_name,term_id)
        DO UPDATE SET score=excluded.score, entered_by=excluded.entered_by
    """, (student_id, subject, class_name, ca_name, score, username, term_id))
    con.commit(); con.close()
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
    user = qone(con.cursor(), "SELECT role FROM users WHERE username=?", (username,))
    con.close()
    if not user or user["role"] != "teacher":
        return jsonify({"ok":False,"error":"Only teachers can enter marks"}), 403
    if not is_teacher_allowed(username, subject, class_name):
        return jsonify({"ok":False,"error":"Access denied – not your assignment"}), 403
    if not (0 <= score <= 100):
        return jsonify({"ok":False,"error":"Score must be 0–100"}), 400

    term = get_active_term()
    if not term:
        return jsonify({"ok":False,"error":"No active term. Ask admin to open a term first."}), 400
    term_id = term["id"]

    con = get_db()
    if not qone(con.cursor(),"SELECT id FROM students WHERE id=? AND class_name=?",(student_id,class_name)):
        con.close()
        return jsonify({"ok":False,"error":"Student not found in that class"}), 404
    con.execute("""
        INSERT INTO exam_scores(student_id,subject,class_name,score,entered_by,term_id)
        VALUES(?,?,?,?,?,?)
        ON CONFLICT(student_id,subject,term_id)
        DO UPDATE SET score=excluded.score, entered_by=excluded.entered_by
    """, (student_id, subject, class_name, score, username, term_id))
    con.commit(); con.close()
    return jsonify({"ok":True})

# ── REPORT CARD ──────────────────────────────────────────────
@app.route("/api/report/<int:sid>", methods=["GET"])
def api_report(sid):
    term_id = request.args.get("term_id")
    con = get_db()
    student = qone(con.cursor(), "SELECT * FROM students WHERE id=?", (sid,))
    con.close()
    if not student:
        return jsonify({"ok":False,"error":"Student not found"}), 404

    # Use specified term or active term
    if term_id:
        term = get_term_by_id(int(term_id))
    else:
        term = get_active_term()
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
        ca_rows  = qall(con.cursor(),
            "SELECT ca_name,score FROM ca_scores WHERE student_id=? AND subject=? AND term_id=?",
            (sid, subject, term_id))
        exam_row = qone(con.cursor(),
            "SELECT score FROM exam_scores WHERE student_id=? AND subject=? AND term_id=?",
            (sid, subject, term_id))
        con.close()
        ca_map    = {r["ca_name"]:r["score"] for r in ca_rows}
        ca_scores = {f"CA{i}": ca_map.get(f"CA{i}") for i in range(1, ca_count+1)}
        exam_val  = exam_row["score"] if exam_row else None
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
    remark = qone(con.cursor(),
        "SELECT * FROM remarks WHERE student_id=? AND term_id=?", (sid, term_id))
    con.close()
    return jsonify({
        "ok":True,
        "student":             {"id":student["id"],"name":student["name"],"class_name":student["class_name"]},
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
    student = qone(con.cursor(), "SELECT class_name FROM students WHERE id=?", (sid,))
    if not student:
        con.close()
        return jsonify({"ok":False,"error":"Student not found"}), 404

    if role == "admin":
        field = "head_remark"
    elif role == "teacher" and is_ct:
        user = qone(con.cursor(),
            "SELECT class_name FROM users WHERE username=? AND is_class_teacher=1", (username,))
        if not user or user["class_name"] != student["class_name"]:
            con.close()
            return jsonify({"ok":False,"error":"Not your class"}), 403
        field = "class_teacher_remark"
    else:
        con.close()
        return jsonify({"ok":False,"error":"Not allowed"}), 403

    con.execute(f"""
        INSERT INTO remarks(student_id, term_id, {field}) VALUES(?,?,?)
        ON CONFLICT(student_id, term_id) DO UPDATE SET {field}=excluded.{field}
    """, (sid, term_id, remark))
    con.commit(); con.close()
    return jsonify({"ok":True})

# ── RANKINGS ─────────────────────────────────────────────────
@app.route("/api/ranking/subject", methods=["GET"])
def api_subject_ranking():
    """
    Rank students by a specific assessment (CA1, CA2, ... or exam)
    in a subject and class for a given term.
    """
    subject    = request.args.get("subject","").lower()
    class_name = request.args.get("class_name","").lower()
    assess     = request.args.get("assess","exam")   # CA1 / CA2 / exam
    term_id    = request.args.get("term_id")

    if not term_id:
        term = get_active_term()
        if not term:
            return jsonify([])
        term_id = term["id"]
    else:
        term_id = int(term_id)

    con = get_db()
    studs = qall(con.cursor(),"SELECT id,name FROM students WHERE class_name=?",(class_name,))
    con.close()

    rows = []
    for s in studs:
        score = None
        if assess == "exam":
            con = get_db()
            r = qone(con.cursor(),
                "SELECT score FROM exam_scores WHERE student_id=? AND subject=? AND term_id=?",
                (s["id"], subject, term_id))
            con.close()
            score = r["score"] if r else None
        else:
            con = get_db()
            r = qone(con.cursor(),
                "SELECT score FROM ca_scores WHERE student_id=? AND subject=? AND ca_name=? AND term_id=?",
                (s["id"], subject, assess, term_id))
            con.close()
            score = r["score"] if r else None

        if score is not None:
            rows.append({"id":s["id"],"name":s["name"],"score":round(score,2),"grade":get_grade(score)})

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
    studs = qall(con.cursor(),
        "SELECT id,name FROM students WHERE class_name=? ORDER BY name", (class_name,))
    con.close()

    results = []
    for s in studs:
        row = {"id":s["id"],"name":s["name"],"scores":{},"total":0,"count":0}
        for subject in allowed_subjects:
            score = None
            if mode == "ca":
                con = get_db()
                r = qone(con.cursor(),
                    "SELECT score FROM ca_scores WHERE student_id=? AND subject=? AND ca_name=? AND term_id=?",
                    (s["id"], subject, ca_name, term_id))
                con.close()
                score = r["score"] if r else None
            elif mode == "exam":
                con = get_db()
                r = qone(con.cursor(),
                    "SELECT score FROM exam_scores WHERE student_id=? AND subject=? AND term_id=?",
                    (s["id"], subject, term_id))
                con.close()
                score = r["score"] if r else None
            elif mode == "terminal":
                f = calc_final(s["id"], subject, term_id)
                score = round(f,1) if f is not None else None
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
    story += [Paragraph("SCHOOL NAME", t_s),
              Paragraph(f"{subtitle}  {'| '+term_label if term_label else ''}", s_s),
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
                str(r["position"]),
                r["grade"] if r["count"] else "-"]
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
    student = qone(con.cursor(),"SELECT * FROM students WHERE id=?",(sid,))
    con.close()
    if not student: return jsonify({"error":"Not found"}),404

    term = get_term_by_id(int(term_id)) if term_id else get_active_term()
    if not term: return jsonify({"error":"No term available"}),400

    term_id    = term["id"]
    ca_count   = term["ca_count"]
    ca_weight  = term["ca_weight"]
    ex_weight  = term["exam_weight"]
    class_name = student["class_name"]
    pos, total = get_overall_position(class_name, sid, term_id)
    avg        = calc_student_average(sid, term_id)

    safe  = student["name"].replace(" ","_")
    fname = os.path.join(tempfile.gettempdir(), f"ReportCard_{safe}_{term_id}.pdf")

    doc = SimpleDocTemplate(fname, pagesize=A4,
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
        ca_rows  = qall(con.cursor(),
            "SELECT ca_name,score FROM ca_scores WHERE student_id=? AND subject=? AND term_id=?",
            (sid, subject, term_id))
        exam_row = qone(con.cursor(),
            "SELECT score FROM exam_scores WHERE student_id=? AND subject=? AND term_id=?",
            (sid, subject, term_id))
        con.close()
        ca_map = {r["ca_name"]:r["score"] for r in ca_rows}
        row = [subject.title()]
        for i in range(1, ca_count+1):
            v = ca_map.get(f"CA{i}")
            row.append(f"{v:.1f}" if v is not None else "-")
        exam_v = exam_row["score"] if exam_row else None
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
    rmk = qone(con.cursor(),"SELECT * FROM remarks WHERE student_id=? AND term_id=?",(sid,term_id))
    con.close()
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
    if not term: return jsonify({"error":"No term"}),400
    tid   = term["id"]
    fname = os.path.join(tempfile.gettempdir(), f"CA_{class_name.replace(' ','')}_{ca_name}_{tid}.pdf")
    con = get_db()
    cs = qall(con.cursor(),"SELECT id,name FROM students WHERE class_name=? ORDER BY name",(class_name,))
    con.close()
    if not cs: return jsonify({"error":"No students"}),404
    def get_score(sid, subj):
        con = get_db()
        r = qone(con.cursor(),
            "SELECT score FROM ca_scores WHERE student_id=? AND subject=? AND ca_name=? AND term_id=?",
            (sid,subj,ca_name,tid))
        con.close()
        return r["score"] if r else None
    _blue_sheet_pdf(fname, f"{ca_name.upper()} SCORE SHEET  |  {class_name.title()}",
                    [dict(r) for r in cs], allowed_subjects, get_score, term)
    return send_file(fname, as_attachment=True,
                     download_name=os.path.basename(fname), mimetype="application/pdf")


@app.route("/api/pdf/terminal_sheet", methods=["GET"])
def pdf_terminal_sheet():
    class_name = request.args.get("class_name","").lower()
    term_id    = request.args.get("term_id")
    term = get_term_by_id(int(term_id)) if term_id else get_active_term()
    if not term: return jsonify({"error":"No term"}),400
    tid   = term["id"]
    fname = os.path.join(tempfile.gettempdir(), f"Terminal_{class_name.replace(' ','')}_{tid}.pdf")
    con = get_db()
    cs = qall(con.cursor(),"SELECT id,name FROM students WHERE class_name=? ORDER BY name",(class_name,))
    con.close()
    if not cs: return jsonify({"error":"No students"}),404
    def get_score(sid, subj):
        f = calc_final(sid, subj, tid)
        return round(f,1) if f is not None else None
    _blue_sheet_pdf(fname,
                    f"TERMINAL SCORE SHEET  |  {class_name.title()}  (CA {term['ca_weight']}% + Exam {term['exam_weight']}%)",
                    [dict(r) for r in cs], allowed_subjects, get_score, term)
    return send_file(fname, as_attachment=True,
                     download_name=os.path.basename(fname), mimetype="application/pdf")

# ── SERVE FRONTEND ───────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")

if __name__ == "__main__":
    if not os.path.exists(DB_FILE):
        print("\n⚠  Database not found. Run:  python setup_admin.py  first.\n")
    else:
        print("\n🎓  School Manager running at  http://localhost:5000\n")
        app.run(debug=True, port=5000)
