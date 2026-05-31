"""
School Manager – Flask API Backend (v5 – Dynamic Classes + Streams)
"""
import hashlib, os, tempfile, secrets
import psycopg2, psycopg2.extras
from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
DATABASE_URL = os.environ.get("DATABASE_URL", "")

allowed_subjects = [
    "mathematics","physics","chemistry","biology",
    "geography","history","civics","english",
    "literature","kiswahili","bible knowledge",
    "book keeping","commerce","business studies",
    "historia ya tanzania na maadili",
]

SUBJECT_ABBR = {
    "historia ya tanzania na maadili":"HTM",
    "mathematics":"MATH","physics":"PHY","chemistry":"CHEM",
    "biology":"BIO","geography":"GEO","history":"HIST",
    "civics":"CIV","english":"ENG","literature":"LIT",
    "kiswahili":"KIS","bible knowledge":"BK",
    "book keeping":"BKP","commerce":"COM","business studies":"BS",
}
def abbr(s): return SUBJECT_ABBR.get(s.lower(), s[:5].upper())

# ── DB ────────────────────────────────────────────────────────
def get_db():
    con = psycopg2.connect(DATABASE_URL)
    con.autocommit = False
    return con

def qone(cur, sql, params=()):
    cur.execute(sql, params); return cur.fetchone()

def qall(cur, sql, params=()):
    cur.execute(sql, params); return cur.fetchall()

def to_dict(row, cur):
    if row is None: return None
    return dict(zip([d[0] for d in cur.description], row))

def to_dicts(rows, cur):
    if not rows: return []
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in rows]

# ── INIT DB ───────────────────────────────────────────────────
def init_db():
    con = get_db(); cur = con.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        username              TEXT PRIMARY KEY,
        password              TEXT NOT NULL,
        role                  TEXT NOT NULL CHECK(role IN ('admin','teacher','parent')),
        is_class_teacher      INTEGER DEFAULT 0,
        class_id              INTEGER DEFAULT NULL,
        stream_id             INTEGER DEFAULT NULL,
        must_change_password  INTEGER DEFAULT 0,
        student_id            INTEGER DEFAULT NULL
    );

    CREATE TABLE IF NOT EXISTS classes (
        id         SERIAL PRIMARY KEY,
        class_name TEXT NOT NULL UNIQUE
    );

    CREATE TABLE IF NOT EXISTS streams (
        id          SERIAL PRIMARY KEY,
        class_id    INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
        stream_name TEXT NOT NULL,
        UNIQUE(class_id, stream_name)
    );

    CREATE TABLE IF NOT EXISTS students (
        id        SERIAL PRIMARY KEY,
        name      TEXT NOT NULL,
        class_id  INTEGER NOT NULL REFERENCES classes(id),
        stream_id    INTEGER DEFAULT NULL REFERENCES streams(id),
        phone_number TEXT DEFAULT NULL
    );

    CREATE TABLE IF NOT EXISTS subject_assignments (
        id        SERIAL PRIMARY KEY,
        username  TEXT NOT NULL REFERENCES users(username),
        subject   TEXT NOT NULL,
        class_id  INTEGER NOT NULL REFERENCES classes(id),
        stream_id INTEGER DEFAULT NULL REFERENCES streams(id),
        UNIQUE(username, subject, class_id, stream_id)
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

    CREATE TABLE IF NOT EXISTS school_config (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );

    INSERT INTO school_config(key,value) VALUES('school_name','School Name')
    ON CONFLICT(key) DO NOTHING;

    CREATE TABLE IF NOT EXISTS announcements (id SERIAL PRIMARY KEY, title TEXT NOT NULL, body TEXT NOT NULL, target_classes TEXT NOT NULL DEFAULT 'all', posted_by TEXT NOT NULL, posted_at TIMESTAMP DEFAULT NOW());

    CREATE TABLE IF NOT EXISTS announcement_reads (announcement_id INTEGER NOT NULL, student_id INTEGER NOT NULL, read_at TIMESTAMP DEFAULT NOW(), PRIMARY KEY(announcement_id,student_id));

    CREATE TABLE IF NOT EXISTS results_published (term_id INTEGER NOT NULL, published INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(term_id));
    """)
    # ── Migrate existing tables — add columns if missing ──
    migrations = [
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS class_id INTEGER DEFAULT NULL",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS stream_id INTEGER DEFAULT NULL",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS must_change_password INTEGER DEFAULT 0",
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS stream_id INTEGER DEFAULT NULL",
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS phone_number TEXT DEFAULT NULL",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS student_id INTEGER DEFAULT NULL",
        "ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check",
        "ALTER TABLE users ADD CONSTRAINT users_role_check CHECK(role IN ('admin','teacher','parent'))",
    ]
    for m in migrations:
        try:
            cur.execute(m)
        except Exception as e:
            print(f"Migration note: {e}")
    con.commit(); cur.close(); con.close()
    print("✓ Database ready.")

# ── PASSWORD ──────────────────────────────────────────────────
def hash_password(pw):
    salt = secrets.token_hex(16)
    dk   = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 260_000)
    return f"{salt}:{dk.hex()}"

def verify_password(pw, stored):
    try:
        salt, dk_hex = stored.split(":")
        dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 260_000)
        return dk.hex() == dk_hex
    except: return False

# ── SCHOOL CONFIG ─────────────────────────────────────────────
def get_school_name():
    try:
        con = get_db(); cur = con.cursor()
        cur.execute("SELECT value FROM school_config WHERE key='school_name'")
        row = cur.fetchone(); cur.close(); con.close()
        return row[0] if row else "School Name"
    except: return "School Name"

# ── TERM HELPERS ──────────────────────────────────────────────
def get_active_term():
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM terms WHERE status='open' ORDER BY id DESC LIMIT 1")
    row = cur.fetchone(); r = to_dict(row, cur) if row else None
    cur.close(); con.close(); return r

def get_term_by_id(tid):
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM terms WHERE id=%s", (tid,))
    row = cur.fetchone(); r = to_dict(row, cur) if row else None
    cur.close(); con.close(); return r

# ── CLASS / STREAM HELPERS ────────────────────────────────────
def get_class_by_id(cid):
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM classes WHERE id=%s", (cid,))
    row = cur.fetchone(); r = to_dict(row, cur) if row else None
    cur.close(); con.close(); return r

def get_stream_by_id(sid):
    if not sid: return None
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM streams WHERE id=%s", (sid,))
    row = cur.fetchone(); r = to_dict(row, cur) if row else None
    cur.close(); con.close(); return r

def get_streams_for_class(class_id):
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM streams WHERE class_id=%s ORDER BY stream_name", (class_id,))
    rows = to_dicts(cur.fetchall(), cur); cur.close(); con.close()
    return rows

def class_has_streams(class_id):
    return len(get_streams_for_class(class_id)) > 0

def get_students_in_scope(class_id, stream_id=None):
    """
    Get students. stream_id=None means ALL students in class.
    stream_id=specific means only that stream.
    """
    con = get_db(); cur = con.cursor()
    if stream_id:
        cur.execute("""
            SELECT s.id, s.name, s.class_id, s.stream_id,
                   c.class_name, st.stream_name
            FROM students s
            JOIN classes c ON s.class_id=c.id
            LEFT JOIN streams st ON s.stream_id=st.id
            WHERE s.class_id=%s AND s.stream_id=%s
            ORDER BY s.name
        """, (class_id, stream_id))
    else:
        cur.execute("""
            SELECT s.id, s.name, s.class_id, s.stream_id,
                   c.class_name, st.stream_name
            FROM students s
            JOIN classes c ON s.class_id=c.id
            LEFT JOIN streams st ON s.stream_id=st.id
            WHERE s.class_id=%s
            ORDER BY s.name
        """, (class_id,))
    rows = to_dicts(cur.fetchall(), cur); cur.close(); con.close()
    return rows

# ── GRADE / SCORE ─────────────────────────────────────────────
def get_grade(score):
    if score >= 80: return "A"
    if score >= 70: return "B"
    if score >= 60: return "C"
    if score >= 50: return "D"
    return "F"

def calc_ca_avg(student_id, subject, term_id):
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT score FROM ca_scores WHERE student_id=%s AND subject=%s AND term_id=%s",
                (student_id, subject, term_id))
    rows = cur.fetchall(); cur.close(); con.close()
    if not rows: return None
    return sum(r[0] for r in rows) / len(rows)

def calc_final(student_id, subject, term_id):
    term = get_term_by_id(term_id)
    if not term: return None
    ca_w, ex_w = term["ca_weight"], term["exam_weight"]
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT score FROM exam_scores WHERE student_id=%s AND subject=%s AND term_id=%s",
                (student_id, subject, term_id))
    row = cur.fetchone(); cur.close(); con.close()
    if not row: return None
    ca_avg = calc_ca_avg(student_id, subject, term_id)
    if ca_avg is None: return None
    return (ca_avg/100)*ca_w + (row[0]/100)*ex_w

def calc_student_average(student_id, term_id):
    finals = [calc_final(student_id, s, term_id) for s in allowed_subjects]
    finals = [f for f in finals if f is not None]
    return sum(finals)/len(finals) if finals else 0

def _assign_positions(rows, key):
    rows.sort(key=lambda x: x[key], reverse=True)
    for i, r in enumerate(rows):
        if i == 0: r["position"] = 1
        elif r[key] == rows[i-1][key]: r["position"] = rows[i-1]["position"]
        else: r["position"] = i+1

def get_ranking(students, term_id):
    """Build ranking rows for a list of student dicts."""
    rows = []
    for s in students:
        avg = calc_student_average(s["id"], term_id)
        rows.append({"id":s["id"],"name":s["name"],
                     "average":round(avg,2),"grade":get_grade(avg)})
    _assign_positions(rows, "average")
    return rows

def get_positions(student_id, class_id, stream_id, term_id):
    """
    Returns (class_position, class_total, stream_position, stream_total)
    stream_position/total are None if no streams or student has no stream.
    """
    all_class = get_students_in_scope(class_id)
    class_ranking = get_ranking(all_class, term_id)
    c_pos   = next((r["position"] for r in class_ranking if r["id"]==student_id), "-")
    c_total = len(class_ranking)

    s_pos, s_total = None, None
    if stream_id:
        stream_studs   = get_students_in_scope(class_id, stream_id)
        stream_ranking = get_ranking(stream_studs, term_id)
        s_pos   = next((r["position"] for r in stream_ranking if r["id"]==student_id), "-")
        s_total = len(stream_ranking)

    return c_pos, c_total, s_pos, s_total

def get_subject_position(student_id, subject, class_id, stream_id, term_id):
    """Position in a subject — within stream if given, else whole class."""
    scope = get_students_in_scope(class_id, stream_id)
    scores = []
    for s in scope:
        f = calc_final(s["id"], subject, term_id)
        if f is not None:
            scores.append({"id":s["id"],"score":f})
    _assign_positions(scores, "score")
    for s in scores:
        if s["id"] == student_id: return s["position"]
    return "-"

# ── PERMISSION CHECK ──────────────────────────────────────────
def teacher_can_access(username, subject, class_id, stream_id=None):
    """
    Teacher is allowed if they have an assignment matching:
    - exact subject + class_id + stream_id, OR
    - subject + class_id + stream_id=NULL (overall / all streams)
    """
    con = get_db(); cur = con.cursor()
    cur.execute("""
        SELECT id FROM subject_assignments
        WHERE username=%s AND subject=%s AND class_id=%s
          AND (stream_id=%s OR stream_id IS NULL)
    """, (username, subject, class_id, stream_id))
    row = cur.fetchone(); cur.close(); con.close()
    return row is not None

# ── AUTH ──────────────────────────────────────────────────────
@app.route("/api/login", methods=["POST"])
def api_login():
    d = request.json
    u, p = d.get("username","").strip(), d.get("password","")
    if not u or not p:
        return jsonify({"ok":False,"error":"Enter username and password"}), 400
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM users WHERE username=%s", (u,))
    row = cur.fetchone(); user = to_dict(row, cur) if row else None
    cur.close(); con.close()
    if not user or not verify_password(p, user["password"]):
        return jsonify({"ok":False,"error":"Invalid username or password"}), 401
    return jsonify({"ok":True,"user":{
        "username":             user["username"],
        "role":                 user["role"],
        "is_class_teacher":     bool(user["is_class_teacher"]),
        "class_id":             user["class_id"],
        "stream_id":            user["stream_id"],
        "must_change_password": bool(user["must_change_password"]),
        "student_id":           user["student_id"],
    }})

@app.route("/api/setup_admin", methods=["POST"])
def api_setup_admin():
    d = request.json
    secret   = d.get("secret","")
    username = d.get("username","").strip()
    password = d.get("password","")
    if not os.environ.get("ADMIN_SETUP_SECRET") or secret != os.environ.get("ADMIN_SETUP_SECRET"):
        return jsonify({"ok":False,"error":"Invalid setup secret"}), 403
    if not username or not password:
        return jsonify({"ok":False,"error":"Username and password required"}), 400
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT username FROM users WHERE role='admin'")
    if cur.fetchone():
        cur.close(); con.close()
        return jsonify({"ok":False,"error":"Admin already exists"}), 409
    cur.execute("INSERT INTO users(username,password,role) VALUES(%s,%s,'admin')",
                (username, hash_password(password)))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok":True})

# ── PARENT ACCOUNT HELPERS ───────────────────────────────────
def generate_parent_credentials(student_name, phone_number, student_id):
    phone_clean   = phone_number.strip()
    last4         = phone_clean[-4:]
    username_base = student_name.strip().lower().replace(" ", "_")
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT id FROM students WHERE phone_number=%s AND id!=%s ORDER BY id",
                (phone_clean, student_id))
    siblings = cur.fetchall()
    cur.execute("SELECT username FROM users WHERE role='parent' AND username LIKE %s",
                (username_base + "%",))
    existing_usernames = [r[0] for r in cur.fetchall()]
    cur.close(); con.close()
    if siblings:
        con = get_db(); cur = con.cursor()
        cur.execute("SELECT id FROM students WHERE phone_number=%s ORDER BY id", (phone_clean,))
        all_same = [r[0] for r in cur.fetchall()]
        cur.close(); con.close()
        try: idx = all_same.index(student_id) + 1
        except ValueError: idx = len(all_same) + 1
        temp_password = f"{last4}-{idx}"
    else:
        temp_password = last4
    final_username = username_base
    counter = 2
    while final_username in existing_usernames:
        final_username = f"{username_base}_{counter}"; counter += 1
    return final_username, temp_password

@app.route("/api/change_password", methods=["POST"])
def api_change_password():
    d = request.json
    username = d.get("username","").strip()
    old_pw   = d.get("old_password","")
    new_pw   = d.get("new_password","").strip()
    if len(new_pw) < 6:
        return jsonify({"ok":False,"error":"New password must be at least 6 characters"}), 400
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT password FROM users WHERE username=%s", (username,))
    row = cur.fetchone()
    if not row or not verify_password(old_pw, row[0]):
        cur.close(); con.close()
        return jsonify({"ok":False,"error":"Current password is incorrect"}), 401
    cur.execute("UPDATE users SET password=%s, must_change_password=0 WHERE username=%s",
                (hash_password(new_pw), username))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok":True})

# ── CLASSES ───────────────────────────────────────────────────
@app.route("/api/classes", methods=["GET"])
def api_get_classes():
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM classes ORDER BY class_name")
    classes = to_dicts(cur.fetchall(), cur)
    result = []
    for c in classes:
        cur.execute("SELECT * FROM streams WHERE class_id=%s ORDER BY stream_name", (c["id"],))
        streams = to_dicts(cur.fetchall(), cur)
        result.append({**c, "streams": streams})
    cur.close(); con.close()
    return jsonify(result)

@app.route("/api/classes", methods=["POST"])
def api_add_class():
    name = request.json.get("class_name","").strip()
    if not name:
        return jsonify({"ok":False,"error":"Class name required"}), 400
    con = get_db(); cur = con.cursor()
    try:
        cur.execute("INSERT INTO classes(class_name) VALUES(%s) RETURNING id", (name,))
        new_id = cur.fetchone()[0]
        con.commit()
    except psycopg2.errors.UniqueViolation:
        con.rollback(); cur.close(); con.close()
        return jsonify({"ok":False,"error":"Class already exists"}), 409
    cur.close(); con.close()
    return jsonify({"ok":True,"id":new_id})

@app.route("/api/classes/<int:cid>", methods=["DELETE"])
def api_delete_class(cid):
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM students WHERE class_id=%s", (cid,))
    if cur.fetchone()[0] > 0:
        cur.close(); con.close()
        return jsonify({"ok":False,"error":"Cannot delete — students are assigned to this class"}), 409
    cur.execute("DELETE FROM streams WHERE class_id=%s", (cid,))
    cur.execute("DELETE FROM classes WHERE id=%s", (cid,))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok":True})

# ── STREAMS ───────────────────────────────────────────────────
@app.route("/api/classes/<int:cid>/streams", methods=["POST"])
def api_add_stream(cid):
    name = request.json.get("stream_name","").strip()
    if not name:
        return jsonify({"ok":False,"error":"Stream name required"}), 400
    con = get_db(); cur = con.cursor()
    try:
        cur.execute("INSERT INTO streams(class_id,stream_name) VALUES(%s,%s) RETURNING id",
                    (cid, name))
        new_id = cur.fetchone()[0]
        con.commit()
    except psycopg2.errors.UniqueViolation:
        con.rollback(); cur.close(); con.close()
        return jsonify({"ok":False,"error":"Stream already exists in this class"}), 409
    cur.close(); con.close()
    return jsonify({"ok":True,"id":new_id})

@app.route("/api/streams/<int:sid>", methods=["DELETE"])
def api_delete_stream(sid):
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM students WHERE stream_id=%s", (sid,))
    if cur.fetchone()[0] > 0:
        cur.close(); con.close()
        return jsonify({"ok":False,"error":"Cannot delete — students are assigned to this stream"}), 409
    cur.execute("DELETE FROM streams WHERE id=%s", (sid,))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok":True})

# ── STUDENTS ──────────────────────────────────────────────────
@app.route("/api/students", methods=["GET"])
def api_students():
    con = get_db(); cur = con.cursor()
    cur.execute("""
        SELECT s.id, s.name, s.class_id, s.stream_id,
               c.class_name, st.stream_name
        FROM students s
        JOIN classes c ON s.class_id=c.id
        LEFT JOIN streams st ON s.stream_id=st.id
        ORDER BY c.class_name, st.stream_name, s.name
    """)
    rows = to_dicts(cur.fetchall(), cur); cur.close(); con.close()
    return jsonify(rows)

@app.route("/api/students", methods=["POST"])
def api_add_student():
    d         = request.json
    name      = d.get("name","").strip()
    class_id  = d.get("class_id")
    stream_id = d.get("stream_id") or None
    if not name or not class_id:
        return jsonify({"ok":False,"error":"Name and class required"}), 400
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT id FROM classes WHERE id=%s", (class_id,))
    if not cur.fetchone():
        cur.close(); con.close()
        return jsonify({"ok":False,"error":"Invalid class"}), 400
    if stream_id:
        cur.execute("SELECT id FROM streams WHERE id=%s AND class_id=%s", (stream_id, class_id))
        if not cur.fetchone():
            cur.close(); con.close()
            return jsonify({"ok":False,"error":"Stream does not belong to this class"}), 400
    cur.execute("SELECT id FROM students WHERE LOWER(name)=LOWER(%s) AND class_id=%s AND (stream_id=%s OR (stream_id IS NULL AND %s IS NULL))",
                (name, class_id, stream_id, stream_id))
    if cur.fetchone():
        cur.close(); con.close()
        return jsonify({"ok":False,"error":"Student already exists in this class/stream"}), 409
    phone_number = request.json.get("phone_number","").strip()
    if not phone_number or len(phone_number) < 4:
        return jsonify({"ok":False,"error":"Parent phone number required (min 4 digits)"}), 400
    cur.execute("INSERT INTO students(name,class_id,stream_id,phone_number) VALUES(%s,%s,%s,%s) RETURNING id",
                (name, class_id, stream_id, phone_number))
    student_id = cur.fetchone()[0]
    con.commit(); cur.close(); con.close()
    username, temp_pw = generate_parent_credentials(name, phone_number, student_id)
    con = get_db(); cur = con.cursor()
    cur.execute("INSERT INTO users(username,password,role,must_change_password,student_id) VALUES(%s,%s,'parent',1,%s)",
                (username, hash_password(temp_pw), student_id))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok":True,"parent_username":username,"temp_password":temp_pw})

@app.route("/api/students/<int:sid>", methods=["DELETE"])
def api_delete_student(sid):
    con = get_db(); cur = con.cursor()
    cur.execute("DELETE FROM ca_scores   WHERE student_id=%s", (sid,))
    cur.execute("DELETE FROM exam_scores WHERE student_id=%s", (sid,))
    cur.execute("DELETE FROM remarks     WHERE student_id=%s", (sid,))
    cur.execute("DELETE FROM students    WHERE id=%s",         (sid,))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok":True})

# ── TEACHERS ──────────────────────────────────────────────────
@app.route("/api/teachers", methods=["GET"])
def api_get_teachers():
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT username,is_class_teacher,class_id,stream_id,must_change_password FROM users WHERE role='teacher'")
    teachers = to_dicts(cur.fetchall(), cur)
    result = []
    for t in teachers:
        cur.execute("""
            SELECT sa.id, sa.subject, sa.class_id, sa.stream_id,
                   c.class_name, st.stream_name
            FROM subject_assignments sa
            JOIN classes c ON sa.class_id=c.id
            LEFT JOIN streams st ON sa.stream_id=st.id
            WHERE sa.username=%s
        """, (t["username"],))
        assignments = to_dicts(cur.fetchall(), cur)
        ct_class  = get_class_by_id(t["class_id"])  if t["class_id"]  else None
        ct_stream = get_stream_by_id(t["stream_id"]) if t["stream_id"] else None
        result.append({
            "username":             t["username"],
            "is_class_teacher":     bool(t["is_class_teacher"]),
            "class_id":             t["class_id"],
            "stream_id":            t["stream_id"],
            "class_name":           ct_class["class_name"]   if ct_class  else "",
            "stream_name":          ct_stream["stream_name"] if ct_stream else "",
            "must_change_password": bool(t["must_change_password"]),
            "assignments":          assignments,
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
    con = get_db(); cur = con.cursor()
    if qone(cur,"SELECT username FROM users WHERE username=%s",(username,)):
        cur.close(); con.close()
        return jsonify({"ok":False,"error":"Username already exists"}), 409
    cur.execute("INSERT INTO users(username,password,role,must_change_password) VALUES(%s,%s,'teacher',1)",
                (username, hash_password(password)))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok":True})

@app.route("/api/teachers/<username>", methods=["DELETE"])
def api_delete_teacher(username):
    con = get_db(); cur = con.cursor()
    cur.execute("DELETE FROM subject_assignments WHERE username=%s", (username,))
    cur.execute("DELETE FROM users WHERE username=%s AND role='teacher'", (username,))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok":True})

@app.route("/api/teachers/<username>/class_teacher", methods=["POST"])
def api_set_class_teacher(username):
    d        = request.json
    is_ct    = bool(d.get("is_class_teacher", False))
    class_id = d.get("class_id") or None
    stream_id= d.get("stream_id") or None
    if is_ct and not class_id:
        return jsonify({"ok":False,"error":"Class required for class teacher"}), 400
    con = get_db(); cur = con.cursor()
    cur.execute("UPDATE users SET is_class_teacher=%s, class_id=%s, stream_id=%s WHERE username=%s AND role='teacher'",
                (1 if is_ct else 0, class_id if is_ct else None, stream_id if is_ct else None, username))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok":True})

# ── SUBJECT ASSIGNMENTS ───────────────────────────────────────
@app.route("/api/assign_teacher", methods=["POST"])
def api_assign_teacher():
    d         = request.json
    username  = d.get("username","")
    subject   = d.get("subject","").lower().strip()
    class_id  = d.get("class_id")
    stream_id = d.get("stream_id") or None   # None = overall (all streams)

    if subject not in allowed_subjects:
        return jsonify({"ok":False,"error":"Invalid subject"}), 400
    con = get_db(); cur = con.cursor()
    if not qone(cur,"SELECT id FROM classes WHERE id=%s",(class_id,)):
        cur.close(); con.close()
        return jsonify({"ok":False,"error":"Invalid class"}), 400
    if not qone(cur,"SELECT username FROM users WHERE username=%s AND role='teacher'",(username,)):
        cur.close(); con.close()
        return jsonify({"ok":False,"error":"Teacher not found"}), 404
    try:
        cur.execute("INSERT INTO subject_assignments(username,subject,class_id,stream_id) VALUES(%s,%s,%s,%s)",
                    (username, subject, class_id, stream_id))
        con.commit()
    except psycopg2.errors.UniqueViolation:
        con.rollback(); cur.close(); con.close()
        return jsonify({"ok":False,"error":"Already assigned"}), 409
    cur.close(); con.close()
    return jsonify({"ok":True})

@app.route("/api/unassign_teacher", methods=["POST"])
def api_unassign_teacher():
    d         = request.json
    username  = d.get("username","")
    subject   = d.get("subject","").lower()
    class_id  = d.get("class_id")
    stream_id = d.get("stream_id") or None
    con = get_db(); cur = con.cursor()
    if stream_id:
        cur.execute("DELETE FROM subject_assignments WHERE username=%s AND subject=%s AND class_id=%s AND stream_id=%s",
                    (username, subject, class_id, stream_id))
    else:
        cur.execute("DELETE FROM subject_assignments WHERE username=%s AND subject=%s AND class_id=%s AND stream_id IS NULL",
                    (username, subject, class_id))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok":True})

# ── TERMS ──────────────────────────────────────────────────────
@app.route("/api/terms", methods=["GET"])
def api_get_terms():
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM terms ORDER BY id DESC")
    rows = to_dicts(cur.fetchall(), cur); cur.close(); con.close()
    return jsonify(rows)

@app.route("/api/terms/active", methods=["GET"])
def api_active_term():
    t = get_active_term()
    return jsonify({"ok": bool(t), "term": t})

@app.route("/api/terms", methods=["POST"])
def api_create_term():
    d         = request.json
    label     = d.get("label","").strip()
    ca_count  = int(d.get("ca_count",2))
    ca_weight = int(d.get("ca_weight",30))
    ex_weight = int(d.get("exam_weight",70))
    if not label: return jsonify({"ok":False,"error":"Term label required"}), 400
    if ca_weight + ex_weight != 100: return jsonify({"ok":False,"error":"Weights must sum to 100"}), 400
    con = get_db(); cur = con.cursor()
    if qone(cur,"SELECT id FROM terms WHERE status='open'",None if False else ()):
        cur.close(); con.close()
        return jsonify({"ok":False,"error":"Close the current term first"}), 409
    cur.execute("INSERT INTO terms(label,ca_count,ca_weight,exam_weight,status) VALUES(%s,%s,%s,%s,'open')",
                (label, ca_count, ca_weight, ex_weight))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok":True})

@app.route("/api/terms/<int:tid>/close", methods=["POST"])
def api_close_term(tid):
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT status FROM terms WHERE id=%s", (tid,))
    row = cur.fetchone()
    if not row: cur.close(); con.close(); return jsonify({"ok":False,"error":"Not found"}), 404
    if row[0]=="closed": cur.close(); con.close(); return jsonify({"ok":False,"error":"Already closed"}), 400
    cur.execute("UPDATE terms SET status='closed' WHERE id=%s", (tid,))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok":True})

# ── MARKS – CA ────────────────────────────────────────────────
@app.route("/api/marks/ca", methods=["POST"])
def api_enter_ca():
    d          = request.json
    username   = d.get("username","")
    subject    = d.get("subject","").lower().strip()
    class_id   = int(d.get("class_id"))
    stream_id  = d.get("stream_id") or None
    student_id = int(d.get("student_id"))
    ca_name    = d.get("ca_name","")
    score      = float(d.get("score"))

    con = get_db(); cur = con.cursor()
    cur.execute("SELECT role FROM users WHERE username=%s", (username,))
    u = cur.fetchone(); cur.close(); con.close()
    if not u or u[0]!="teacher":
        return jsonify({"ok":False,"error":"Only teachers can enter marks"}), 403
    if not teacher_can_access(username, subject, class_id, stream_id):
        return jsonify({"ok":False,"error":"Access denied – not your assignment"}), 403
    if not (0 <= score <= 100):
        return jsonify({"ok":False,"error":"Score must be 0–100"}), 400

    term = get_active_term()
    if not term: return jsonify({"ok":False,"error":"No active term"}), 400
    term_id  = term["id"]
    ca_count = term["ca_count"]

    con = get_db(); cur = con.cursor()
    cur.execute("SELECT id FROM students WHERE id=%s AND class_id=%s", (student_id, class_id))
    if not cur.fetchone():
        cur.close(); con.close()
        return jsonify({"ok":False,"error":"Student not found in this class"}), 404
    cur.execute("SELECT ca_name FROM ca_scores WHERE student_id=%s AND subject=%s AND term_id=%s",
                (student_id, subject, term_id))
    existing = [r[0] for r in cur.fetchall()]
    if ca_name not in existing and len(existing) >= ca_count:
        cur.close(); con.close()
        return jsonify({"ok":False,"error":f"CA limit ({ca_count}) reached"}), 400
    cur.execute("""
        INSERT INTO ca_scores(student_id,subject,ca_name,score,entered_by,term_id)
        VALUES(%s,%s,%s,%s,%s,%s)
        ON CONFLICT(student_id,subject,ca_name,term_id)
        DO UPDATE SET score=EXCLUDED.score, entered_by=EXCLUDED.entered_by
    """, (student_id, subject, ca_name, score, username, term_id))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok":True})

# ── MARKS – EXAM ──────────────────────────────────────────────
@app.route("/api/marks/exam", methods=["POST"])
def api_enter_exam():
    d          = request.json
    username   = d.get("username","")
    subject    = d.get("subject","").lower().strip()
    class_id   = int(d.get("class_id"))
    stream_id  = d.get("stream_id") or None
    student_id = int(d.get("student_id"))
    score      = float(d.get("score"))

    con = get_db(); cur = con.cursor()
    cur.execute("SELECT role FROM users WHERE username=%s", (username,))
    u = cur.fetchone(); cur.close(); con.close()
    if not u or u[0]!="teacher":
        return jsonify({"ok":False,"error":"Only teachers can enter marks"}), 403
    if not teacher_can_access(username, subject, class_id, stream_id):
        return jsonify({"ok":False,"error":"Access denied – not your assignment"}), 403
    if not (0 <= score <= 100):
        return jsonify({"ok":False,"error":"Score must be 0–100"}), 400

    term = get_active_term()
    if not term: return jsonify({"ok":False,"error":"No active term"}), 400
    term_id = term["id"]

    con = get_db(); cur = con.cursor()
    cur.execute("SELECT id FROM students WHERE id=%s AND class_id=%s", (student_id, class_id))
    if not cur.fetchone():
        cur.close(); con.close()
        return jsonify({"ok":False,"error":"Student not found in this class"}), 404
    cur.execute("""
        INSERT INTO exam_scores(student_id,subject,score,entered_by,term_id)
        VALUES(%s,%s,%s,%s,%s)
        ON CONFLICT(student_id,subject,term_id)
        DO UPDATE SET score=EXCLUDED.score, entered_by=EXCLUDED.entered_by
    """, (student_id, subject, score, username, term_id))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok":True})

# ── REPORT CARD ───────────────────────────────────────────────
@app.route("/api/report/<int:sid>", methods=["GET"])
def api_report(sid):
    term_id = request.args.get("term_id")
    con = get_db(); cur = con.cursor()
    cur.execute("""
        SELECT s.id, s.name, s.class_id, s.stream_id,
               c.class_name, st.stream_name
        FROM students s
        JOIN classes c ON s.class_id=c.id
        LEFT JOIN streams st ON s.stream_id=st.id
        WHERE s.id=%s
    """, (sid,))
    row = cur.fetchone(); student = to_dict(row, cur) if row else None
    cur.close(); con.close()
    if not student: return jsonify({"ok":False,"error":"Student not found"}), 404

    term = get_term_by_id(int(term_id)) if term_id else get_active_term()
    if not term: return jsonify({"ok":False,"error":"No term available"}), 400

    tid        = term["id"]
    ca_count   = term["ca_count"]
    class_id   = student["class_id"]
    stream_id  = student["stream_id"]

    c_pos, c_total, s_pos, s_total = get_positions(sid, class_id, stream_id, tid)
    avg = calc_student_average(sid, tid)

    rows = []
    for subject in allowed_subjects:
        con = get_db(); cur = con.cursor()
        cur.execute("SELECT ca_name,score FROM ca_scores WHERE student_id=%s AND subject=%s AND term_id=%s",
                    (sid, subject, tid))
        ca_rows = cur.fetchall()
        cur.execute("SELECT score FROM exam_scores WHERE student_id=%s AND subject=%s AND term_id=%s",
                    (sid, subject, tid))
        exam_row = cur.fetchone(); cur.close(); con.close()
        ca_map    = {r[0]:r[1] for r in ca_rows}
        ca_scores = {f"CA{i}": ca_map.get(f"CA{i}") for i in range(1, ca_count+1)}
        exam_val  = exam_row[0] if exam_row else None
        final_val = calc_final(sid, subject, tid)
        subj_pos  = get_subject_position(sid, subject, class_id, stream_id, tid) if final_val is not None else "-"
        rows.append({
            "subject":  subject,
            "ca":       ca_scores,
            "exam":     exam_val,
            "final":    round(final_val,1) if final_val is not None else None,
            "grade":    get_grade(final_val) if final_val is not None else "-",
            "position": subj_pos,
        })

    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM remarks WHERE student_id=%s AND term_id=%s", (sid, tid))
    remark_row = cur.fetchone(); rmk = to_dict(remark_row, cur) if remark_row else None
    cur.close(); con.close()

    return jsonify({
        "ok":True,
        "student":             student,
        "term":                term,
        "rows":                rows,
        "average":             round(avg,2),
        "grade":               get_grade(avg),
        "class_position":      c_pos,
        "class_total":         c_total,
        "stream_position":     s_pos,
        "stream_total":        s_total,
        "class_teacher_remark":rmk["class_teacher_remark"] if rmk else "",
        "head_remark":         rmk["head_remark"] if rmk else "",
        "ca_count":            ca_count,
        "ca_weight":           term["ca_weight"],
        "exam_weight":         term["exam_weight"],
    })

# ── REMARKS ───────────────────────────────────────────────────
@app.route("/api/remarks", methods=["POST"])
def api_remarks():
    d        = request.json
    username = d.get("username","")
    role     = d.get("role","")
    is_ct    = d.get("is_class_teacher", False)
    sid      = int(d.get("student_id"))
    remark   = d.get("remark","").strip()
    term = get_active_term()
    if not term: return jsonify({"ok":False,"error":"No active term"}), 400
    tid = term["id"]
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT class_id, stream_id FROM students WHERE id=%s", (sid,))
    student = cur.fetchone()
    if not student: cur.close(); con.close(); return jsonify({"ok":False,"error":"Student not found"}), 404
    if role == "admin":
        field = "head_remark"
    elif role == "teacher" and is_ct:
        cur.execute("SELECT class_id, stream_id FROM users WHERE username=%s AND is_class_teacher=1", (username,))
        u = cur.fetchone()
        if not u or u[0] != student[0]:
            cur.close(); con.close()
            return jsonify({"ok":False,"error":"Not your class"}), 403
        field = "class_teacher_remark"
    else:
        cur.close(); con.close()
        return jsonify({"ok":False,"error":"Not allowed"}), 403
    cur.execute(f"""
        INSERT INTO remarks(student_id,term_id,{field}) VALUES(%s,%s,%s)
        ON CONFLICT(student_id,term_id) DO UPDATE SET {field}=EXCLUDED.{field}
    """, (sid, tid, remark))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok":True})

# ── RANKINGS ──────────────────────────────────────────────────
@app.route("/api/ranking/subject", methods=["GET"])
def api_subject_ranking():
    subject   = request.args.get("subject","").lower()
    class_id  = request.args.get("class_id")
    stream_id = request.args.get("stream_id") or None
    assess    = request.args.get("assess","exam")
    term_id   = request.args.get("term_id")
    if not term_id:
        term = get_active_term()
        if not term: return jsonify([])
        term_id = term["id"]
    else: term_id = int(term_id)
    if stream_id: stream_id = int(stream_id)
    if class_id:  class_id  = int(class_id)
    studs = get_students_in_scope(class_id, stream_id)
    rows = []
    for s in studs:
        con = get_db(); cur = con.cursor()
        if assess == "exam":
            cur.execute("SELECT score FROM exam_scores WHERE student_id=%s AND subject=%s AND term_id=%s",
                        (s["id"], subject, term_id))
        else:
            cur.execute("SELECT score FROM ca_scores WHERE student_id=%s AND subject=%s AND ca_name=%s AND term_id=%s",
                        (s["id"], subject, assess, term_id))
        row = cur.fetchone(); cur.close(); con.close()
        if row: rows.append({"id":s["id"],"name":s["name"],"score":round(row[0],2),"grade":get_grade(row[0])})
    _assign_positions(rows, "score")
    return jsonify(rows)

# ── SCORE SHEETS ──────────────────────────────────────────────
@app.route("/api/scoresheet", methods=["GET"])
def api_scoresheet():
    mode      = request.args.get("mode","ca")
    class_id  = request.args.get("class_id")
    stream_id = request.args.get("stream_id") or None
    ca_name   = request.args.get("ca_name","CA1")
    term_id   = request.args.get("term_id")
    if not term_id:
        term = get_active_term()
        if not term: return jsonify({"subjects":[],"results":[]})
        term_id = term["id"]
    else: term_id = int(term_id)
    if class_id:  class_id  = int(class_id)
    if stream_id: stream_id = int(stream_id)
    studs = get_students_in_scope(class_id, stream_id)
    results = []
    for s in studs:
        row = {"id":s["id"],"name":s["name"],"stream_name":s.get("stream_name"),"scores":{},"total":0,"count":0}
        for subject in allowed_subjects:
            score = None
            con = get_db(); cur = con.cursor()
            if mode == "ca":
                cur.execute("SELECT score FROM ca_scores WHERE student_id=%s AND subject=%s AND ca_name=%s AND term_id=%s",
                            (s["id"], subject, ca_name, term_id))
                r = cur.fetchone(); score = r[0] if r else None
            elif mode == "exam":
                cur.execute("SELECT score FROM exam_scores WHERE student_id=%s AND subject=%s AND term_id=%s",
                            (s["id"], subject, term_id))
                r = cur.fetchone(); score = r[0] if r else None
            cur.close(); con.close()
            if mode == "terminal":
                f = calc_final(s["id"], subject, term_id)
                score = round(f,1) if f is not None else None
            row["scores"][subject] = score
            if score is not None: row["total"] += score; row["count"] += 1
        row["average"] = round(row["total"]/row["count"],2) if row["count"] else 0
        row["grade"]   = get_grade(row["average"])
        results.append(row)
    _assign_positions(results, "average")
    return jsonify({"subjects": allowed_subjects, "results": results})

# ── CONFIG ─────────────────────────────────────────────────────
@app.route("/api/config", methods=["GET"])
def api_config():
    term = get_active_term()
    return jsonify({
        "allowed_subjects": allowed_subjects,
        "active_term":      term,
        "ca_count":         term["ca_count"] if term else 2,
        "school_name":      get_school_name(),
    })

@app.route("/api/config/school_name", methods=["POST"])
def api_set_school_name():
    name = request.json.get("school_name","").strip()
    if not name: return jsonify({"ok":False,"error":"Name cannot be empty"}), 400
    con = get_db(); cur = con.cursor()
    cur.execute("INSERT INTO school_config(key,value) VALUES('school_name',%s) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value", (name,))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok":True})

# ── PDF ────────────────────────────────────────────────────────
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm

def _blue_sheet_pdf(filename, subtitle, students, subjects, get_score_fn, term=None):
    H_BG=colors.HexColor("#1A6FA8"); S_BG=colors.HexColor("#5BA4CF")
    ODD=colors.HexColor("#E8F4FC"); EVEN=colors.white
    RED=colors.HexColor("#C0392B"); WHITE=colors.white
    doc = SimpleDocTemplate(filename, pagesize=landscape(A4),
                            rightMargin=1.2*cm, leftMargin=1.2*cm,
                            topMargin=1.2*cm, bottomMargin=1.2*cm)
    styles = getSampleStyleSheet(); story = []
    t_s = ParagraphStyle("T",parent=styles["Title"],fontSize=14,textColor=H_BG,spaceAfter=2)
    s_s = ParagraphStyle("S",parent=styles["Normal"],fontSize=8,alignment=1,spaceAfter=6)
    tl  = term["label"] if term else ""
    story += [Paragraph(get_school_name(),t_s), Paragraph(f"{subtitle} | {tl}",s_s), Spacer(1,0.3*cm)]
    results = []
    for s in students:
        row={"name":s["name"],"stream":s.get("stream_name") or "","scores":{},"total":0,"count":0}
        for subj in subjects:
            sc = get_score_fn(s["id"], subj)
            row["scores"][subj]=sc
            if sc is not None: row["total"]+=sc; row["count"]+=1
        row["average"]=row["total"]/row["count"] if row["count"] else 0
        row["grade"]=get_grade(row["average"])
        results.append(row)
    _assign_positions(results,"average")
    # detect if stream column needed
    has_streams = any(r["stream"] for r in results)
    hdr = ["#","Student"]
    if has_streams: hdr.append("Stream")
    hdr += [abbr(s) for s in subjects] + ["Total","Avg","Pos","Grd"]
    tdata=[hdr]; fail_cells=[]
    for ri,r in enumerate(results,1):
        row=[str(r["position"]),r["name"]]
        if has_streams: row.append(r["stream"] or "—")
        for ci,subj in enumerate(subjects):
            sc=r["scores"][subj]
            if sc is not None:
                if sc<50: fail_cells.append((ri,ci+(3 if has_streams else 2)))
                row.append(f"{sc:.1f}")
            else: row.append("-")
        row+=[f"{r['total']:.1f}" if r["count"] else "-",
              f"{r['average']:.1f}" if r["count"] else "-",
              str(r["position"]), r["grade"] if r["count"] else "-"]
        tdata.append(row)
    sc_w=1.2*cm; extra=0.8*cm if has_streams else 0
    cw=[0.7*cm,3.0*cm]+([extra] if has_streams else [])+[sc_w]*len(subjects)+[1.5*cm,1.3*cm,0.9*cm,1.0*cm]
    tbl=Table(tdata,colWidths=cw,repeatRows=1)
    ts=[("BACKGROUND",(0,0),(-1,0),H_BG),("TEXTCOLOR",(0,0),(-1,0),WHITE),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,0),6.5),
        ("ALIGN",(0,0),(-1,0),"CENTER"),
        ("FONTNAME",(0,1),(-1,-1),"Helvetica"),("FONTSIZE",(0,1),(-1,-1),7),
        ("ALIGN",(0,1),(-1,-1),"CENTER"),("ALIGN",(1,1),(1,-1),"LEFT"),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[ODD,EVEN]),
        ("GRID",(0,0),(-1,-1),0.4,colors.HexColor("#A0C4E0")),
        ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3),
        ("BACKGROUND",(-4,0),(-1,0),S_BG),("FONTNAME",(-4,1),(-1,-1),"Helvetica-Bold")]
    for (ri,ci) in fail_cells: ts.append(("TEXTCOLOR",(ci,ri),(ci,ri),RED))
    tbl.setStyle(TableStyle(ts)); story.append(tbl)
    story.append(Spacer(1,0.3*cm))
    ft=ParagraphStyle("F",parent=styles["Normal"],fontSize=6.5,textColor=colors.grey,alignment=2)
    story.append(Paragraph(f"Generated | {len(students)} students | {tl}",ft))
    doc.build(story)

@app.route("/api/pdf/report/<int:sid>", methods=["GET"])
def pdf_report(sid):
    term_id = request.args.get("term_id")
    con = get_db(); cur = con.cursor()
    cur.execute("""SELECT s.id,s.name,s.class_id,s.stream_id,c.class_name,st.stream_name
                   FROM students s JOIN classes c ON s.class_id=c.id
                   LEFT JOIN streams st ON s.stream_id=st.id WHERE s.id=%s""", (sid,))
    row = cur.fetchone(); student = to_dict(row,cur) if row else None
    cur.close(); con.close()
    if not student: return jsonify({"error":"Not found"}), 404
    term = get_term_by_id(int(term_id)) if term_id else get_active_term()
    if not term: return jsonify({"error":"No term"}), 400
    tid=term["id"]; ca_count=term["ca_count"]; ca_w=term["ca_weight"]; ex_w=term["exam_weight"]
    class_id=student["class_id"]; stream_id=student["stream_id"]
    c_pos,c_total,s_pos,s_total = get_positions(sid,class_id,stream_id,tid)
    avg = calc_student_average(sid,tid)
    safe=student["name"].replace(" ","_")
    fname=os.path.join(tempfile.gettempdir(),f"RC_{safe}_{tid}.pdf")
    doc=SimpleDocTemplate(fname,pagesize=A4,rightMargin=1.5*cm,leftMargin=1.5*cm,topMargin=1.5*cm,bottomMargin=1.5*cm)
    styles=getSampleStyleSheet(); story=[]
    H_BG=colors.HexColor("#1A6FA8"); ODD=colors.HexColor("#E8F4FC")
    WHITE=colors.white; RED=colors.HexColor("#C0392B")
    t_s=ParagraphStyle("T",parent=styles["Title"],fontSize=16,textColor=H_BG,spaceAfter=2)
    s_s=ParagraphStyle("S",parent=styles["Normal"],fontSize=9,alignment=1,spaceAfter=4)
    story+=[Paragraph(get_school_name(),t_s),Paragraph("STUDENT REPORT CARD",s_s),Spacer(1,0.3*cm)]
    stream_label = f"{student['class_name']} {student['stream_name']}" if student.get("stream_name") else student["class_name"]
    info=[["Name:",student["name"],"Class:",stream_label],
          ["Term:",term["label"],"Weights:",f"CA {ca_w}% | Exam {ex_w}%"],
          ["Class Position:",f"{c_pos}/{c_total}","Grade:",get_grade(avg)]]
    if s_pos is not None:
        info.append(["Stream Position:",f"{s_pos}/{s_total}","",""])
    it=Table(info,colWidths=[3*cm,6*cm,3*cm,5*cm])
    it.setStyle(TableStyle([("FONTNAME",(0,0),(-1,-1),"Helvetica"),
        ("FONTNAME",(0,0),(0,-1),"Helvetica-Bold"),("FONTNAME",(2,0),(2,-1),"Helvetica-Bold"),
        ("FONTSIZE",(0,0),(-1,-1),9),("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3)]))
    story+=[it,Spacer(1,0.4*cm)]
    hdr=["Subject"]+[f"CA{i}" for i in range(1,ca_count+1)]+["Exam","Final","Pos","Grd","Remark","Sign"]
    tdata=[hdr]; tot,cnt=0,0; fail_rows=[]
    for subject in allowed_subjects:
        con=get_db(); cur=con.cursor()
        cur.execute("SELECT ca_name,score FROM ca_scores WHERE student_id=%s AND subject=%s AND term_id=%s",(sid,subject,tid))
        ca_rows=cur.fetchall()
        cur.execute("SELECT score FROM exam_scores WHERE student_id=%s AND subject=%s AND term_id=%s",(sid,subject,tid))
        exam_row=cur.fetchone(); cur.close(); con.close()
        ca_map={r[0]:r[1] for r in ca_rows}
        row=[subject.title()]
        for i in range(1,ca_count+1):
            v=ca_map.get(f"CA{i}"); row.append(f"{v:.1f}" if v is not None else "-")
        exam_v=exam_row[0] if exam_row else None
        row.append(f"{exam_v:.1f}" if exam_v is not None else "-")
        final_v=calc_final(sid,subject,tid)
        if final_v is not None: tot+=final_v; cnt+=1
        row.append(f"{final_v:.1f}" if final_v is not None else "-")
        row.append(str(get_subject_position(sid,subject,class_id,stream_id,tid)) if final_v is not None else "-")
        row.append(get_grade(final_v) if final_v is not None else "-")
        row+=["",""]
        if final_v is not None and final_v<50: fail_rows.append(len(tdata))
        tdata.append(row)
    ca_cw=1.1*cm; cw=[4.0*cm]+[ca_cw]*ca_count+[1.4*cm,1.4*cm,1.0*cm,1.1*cm,2.4*cm,1.6*cm]
    mt=Table(tdata,colWidths=cw,repeatRows=1)
    mts=[("BACKGROUND",(0,0),(-1,0),H_BG),("TEXTCOLOR",(0,0),(-1,0),WHITE),
         ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),7.5),
         ("ALIGN",(0,0),(-1,-1),"CENTER"),("ALIGN",(0,1),(0,-1),"LEFT"),
         ("GRID",(0,0),(-1,-1),0.4,colors.HexColor("#A0C4E0")),
         ("ROWBACKGROUNDS",(0,1),(-1,-1),[ODD,WHITE]),
         ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3)]
    for ri in fail_rows: mts.append(("TEXTCOLOR",(0,ri),(-1,ri),RED))
    mt.setStyle(TableStyle(mts)); story+=[mt,Spacer(1,0.4*cm)]
    comp_avg=tot/cnt if cnt else 0
    # Summary band
    summary_data=[["AVERAGE",f"{comp_avg:.2f}","GRADE",get_grade(comp_avg),"CLASS POS",f"{c_pos}/{c_total}"]]
    summary_cols=[3*cm,3*cm,2*cm,2*cm,3*cm,4*cm]
    if s_pos is not None:
        summary_data[0]+=["STREAM POS",f"{s_pos}/{s_total}"]
        summary_cols+=[3*cm,3*cm]
    sm=Table(summary_data,colWidths=summary_cols)
    sm.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),H_BG),("TEXTCOLOR",(0,0),(-1,-1),WHITE),
        ("FONTNAME",(0,0),(-1,-1),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),9),
        ("ALIGN",(0,0),(-1,-1),"CENTER"),("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5)]))
    story+=[sm,Spacer(1,0.4*cm)]
    con=get_db(); cur=con.cursor()
    cur.execute("SELECT * FROM remarks WHERE student_id=%s AND term_id=%s",(sid,tid))
    rmk_row=cur.fetchone(); rmk=to_dict(rmk_row,cur) if rmk_row else None; cur.close(); con.close()
    rm_data=[["Class Teacher Remark:",rmk["class_teacher_remark"] if rmk else "________________________"],
             ["Head of School Remark:",rmk["head_remark"] if rmk else "________________________"]]
    rmt=Table(rm_data,colWidths=[5*cm,12*cm])
    rmt.setStyle(TableStyle([("FONTNAME",(0,0),(0,-1),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),8),
        ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),
        ("LINEBELOW",(1,0),(1,-1),0.5,colors.grey)]))
    story+=[rmt,Spacer(1,0.4*cm)]
    sig=Table([["Class Teacher Sign: _______________","Head Sign: _______________","Date: _______________"]],colWidths=[6*cm,6*cm,5*cm])
    sig.setStyle(TableStyle([("FONTSIZE",(0,0),(-1,-1),7.5),("FONTNAME",(0,0),(-1,-1),"Helvetica")]))
    story.append(sig); doc.build(story)
    return send_file(fname,as_attachment=True,
                     download_name=f"RC_{student['name'].replace(' ','_')}_{term['label'].replace(' ','_')}.pdf",
                     mimetype="application/pdf")

@app.route("/api/pdf/ca_sheet", methods=["GET"])
def pdf_ca_sheet():
    class_id  = request.args.get("class_id")
    stream_id = request.args.get("stream_id") or None
    ca_name   = request.args.get("ca_name","CA1")
    term_id   = request.args.get("term_id")
    term = get_term_by_id(int(term_id)) if term_id else get_active_term()
    if not term: return jsonify({"error":"No term"}), 400
    tid=term["id"]; class_id=int(class_id) if class_id else None
    if stream_id: stream_id=int(stream_id)
    studs=get_students_in_scope(class_id,stream_id)
    if not studs: return jsonify({"error":"No students"}), 404
    fname=os.path.join(tempfile.gettempdir(),f"CA_{class_id}_{stream_id}_{ca_name}_{tid}.pdf")
    def get_score(sid,subj):
        con=get_db(); cur=con.cursor()
        cur.execute("SELECT score FROM ca_scores WHERE student_id=%s AND subject=%s AND ca_name=%s AND term_id=%s",(sid,subj,ca_name,tid))
        r=cur.fetchone(); cur.close(); con.close(); return r[0] if r else None
    _blue_sheet_pdf(fname,f"{ca_name.upper()} SCORE SHEET",studs,allowed_subjects,get_score,term)
    return send_file(fname,as_attachment=True,download_name=os.path.basename(fname),mimetype="application/pdf")

@app.route("/api/pdf/terminal_sheet", methods=["GET"])
def pdf_terminal_sheet():
    class_id  = request.args.get("class_id")
    stream_id = request.args.get("stream_id") or None
    term_id   = request.args.get("term_id")
    term = get_term_by_id(int(term_id)) if term_id else get_active_term()
    if not term: return jsonify({"error":"No term"}), 400
    tid=term["id"]; class_id=int(class_id) if class_id else None
    if stream_id: stream_id=int(stream_id)
    studs=get_students_in_scope(class_id,stream_id)
    if not studs: return jsonify({"error":"No students"}), 404
    fname=os.path.join(tempfile.gettempdir(),f"Terminal_{class_id}_{stream_id}_{tid}.pdf")
    def get_score(sid,subj):
        f=calc_final(sid,subj,tid); return round(f,1) if f is not None else None
    _blue_sheet_pdf(fname,f"TERMINAL SCORE SHEET (CA {term['ca_weight']}% + Exam {term['exam_weight']}%)",
                    studs,allowed_subjects,get_score,term)
    return send_file(fname,as_attachment=True,download_name=os.path.basename(fname),mimetype="application/pdf")

# ── ONE-TIME RESET ENDPOINT (remove after use) ──────────────
@app.route("/api/reset_db", methods=["POST"])
def api_reset_db():
    secret = request.json.get("secret","")
    if secret != os.environ.get("ADMIN_SETUP_SECRET",""):
        return jsonify({"ok":False,"error":"Invalid secret"}), 403
    con = get_db(); cur = con.cursor()
    drops = [
        "DROP TABLE IF EXISTS remarks CASCADE",
        "DROP TABLE IF EXISTS exam_scores CASCADE",
        "DROP TABLE IF EXISTS ca_scores CASCADE",
        "DROP TABLE IF EXISTS subject_assignments CASCADE",
        "DROP TABLE IF EXISTS students CASCADE",
        "DROP TABLE IF EXISTS streams CASCADE",
        "DROP TABLE IF EXISTS classes CASCADE",
        "DROP TABLE IF EXISTS terms CASCADE",
        "DROP TABLE IF EXISTS school_config CASCADE",
        "DROP TABLE IF EXISTS users CASCADE",
    ]
    for d in drops:
        cur.execute(d)
    con.commit(); cur.close(); con.close()
    init_db()
    return jsonify({"ok":True,"message":"Database reset. Go to /setup to create admin."})

# ── SERVE FRONTEND ────────────────────────────────────────────
@app.route("/")
def index(): return send_from_directory(BASE_DIR,"index.html")

@app.route("/setup")
def setup_page(): return send_from_directory(BASE_DIR,"setup.html")

# ── STARTUP ────────────────────────────────────────────────────
with app.app_context():
    try: init_db()
    except Exception as e: print(f"DB init warning: {e}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT",5000))
    app.run(host="0.0.0.0",port=port,debug=False)


# ── ANNOUNCEMENTS ─────────────────────────────────────────────
@app.route("/api/announcements", methods=["GET"])
def api_get_announcements():
    student_id = request.args.get("student_id")
    con = get_db(); cur = con.cursor()
    if student_id:
        sid = int(student_id)
        cur.execute("SELECT class_id FROM students WHERE id=%s", (sid,))
        row = cur.fetchone()
        if not row: cur.close(); con.close(); return jsonify([])
        cur.execute("SELECT class_name FROM classes WHERE id=%s", (row[0],))
        cls_row = cur.fetchone(); class_name = cls_row[0] if cls_row else ""
        cur.execute("""
            SELECT a.id, a.title, a.body, a.target_classes,
                   a.posted_by, a.posted_at::text,
                   CASE WHEN ar.student_id IS NOT NULL THEN 1 ELSE 0 END as is_read
            FROM announcements a
            LEFT JOIN announcement_reads ar
                ON ar.announcement_id=a.id AND ar.student_id=%s
            WHERE a.target_classes='all' OR a.target_classes LIKE %s
            ORDER BY a.posted_at DESC
        """, (sid, f"%{class_name}%"))
    else:
        cur.execute("SELECT id,title,body,target_classes,posted_by,posted_at::text,0 as is_read FROM announcements ORDER BY posted_at DESC")
    rows = to_dicts(cur.fetchall(), cur); cur.close(); con.close()
    return jsonify(rows)

@app.route("/api/announcements", methods=["POST"])
def api_post_announcement():
    d              = request.json
    title          = d.get("title","").strip()
    body           = d.get("body","").strip()
    posted_by      = d.get("posted_by","")
    target_classes = d.get("target_classes","all").strip()
    if not title or not body:
        return jsonify({"ok":False,"error":"Title and body required"}), 400
    con = get_db(); cur = con.cursor()
    cur.execute("INSERT INTO announcements(title,body,target_classes,posted_by) VALUES(%s,%s,%s,%s) RETURNING id",
                (title, body, target_classes, posted_by))
    new_id = cur.fetchone()[0]
    con.commit(); cur.close(); con.close()
    return jsonify({"ok":True,"id":new_id})

@app.route("/api/announcements/<int:aid>", methods=["DELETE"])
def api_delete_announcement(aid):
    con = get_db(); cur = con.cursor()
    cur.execute("DELETE FROM announcements WHERE id=%s", (aid,))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok":True})

@app.route("/api/announcements/<int:aid>/read", methods=["POST"])
def api_mark_read(aid):
    student_id = request.json.get("student_id")
    if not student_id: return jsonify({"ok":False,"error":"student_id required"}), 400
    con = get_db(); cur = con.cursor()
    cur.execute("INSERT INTO announcement_reads(announcement_id,student_id) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                (aid, int(student_id)))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok":True})

# ── RESULTS PUBLISHING ────────────────────────────────────────
@app.route("/api/results/status", methods=["GET"])
def api_results_status():
    term_id = request.args.get("term_id")
    if not term_id:
        term = get_active_term()
        if not term: return jsonify({"published":False,"term":None,"term_id":None})
        term_id = term["id"]
    else:
        term_id = int(term_id)
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT published FROM results_published WHERE term_id=%s", (term_id,))
    row = cur.fetchone(); cur.close(); con.close()
    published = bool(row[0]) if row else False
    return jsonify({"published":published,"term":get_term_by_id(term_id),"term_id":term_id})

@app.route("/api/results/toggle", methods=["POST"])
def api_toggle_results():
    d       = request.json
    term_id = d.get("term_id")
    publish = bool(d.get("publish", True))
    if not term_id: return jsonify({"ok":False,"error":"term_id required"}), 400
    term_id = int(term_id)
    term = get_term_by_id(term_id)
    if not term: return jsonify({"ok":False,"error":"Term not found"}), 404
    if term["status"] == "closed" and publish:
        return jsonify({"ok":False,"error":"Cannot re-publish results of a closed term"}), 400
    con = get_db(); cur = con.cursor()
    cur.execute("INSERT INTO results_published(term_id,published) VALUES(%s,%s) ON CONFLICT(term_id) DO UPDATE SET published=EXCLUDED.published",
                (term_id, 1 if publish else 0))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok":True,"published":publish})

# ── PARENT RESULTS ────────────────────────────────────────────
@app.route("/api/parent/results", methods=["GET"])
def api_parent_results():
    student_id = request.args.get("student_id")
    term_id    = request.args.get("term_id")
    if not student_id: return jsonify({"ok":False,"error":"student_id required"}), 400
    if not term_id:
        term = get_active_term()
        if not term: return jsonify({"ok":False,"error":"No active term"}), 400
        term_id = term["id"]
    else:
        term_id = int(term_id)
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT published FROM results_published WHERE term_id=%s", (term_id,))
    row = cur.fetchone(); cur.close(); con.close()
    if not row or not row[0]:
        return jsonify({"ok":False,"error":"Results not yet published for this term"}), 403
    sid  = int(student_id)
    term = get_term_by_id(term_id)
    con = get_db(); cur = con.cursor()
    cur.execute("""SELECT s.id,s.name,s.class_id,s.stream_id,c.class_name,st.stream_name
                   FROM students s JOIN classes c ON s.class_id=c.id
                   LEFT JOIN streams st ON s.stream_id=st.id WHERE s.id=%s""", (sid,))
    row = cur.fetchone(); student = to_dict(row,cur) if row else None
    cur.close(); con.close()
    if not student: return jsonify({"ok":False,"error":"Student not found"}), 404
    ca_count  = term["ca_count"]
    class_id  = student["class_id"]
    stream_id = student["stream_id"]
    results = []
    for subject in allowed_subjects:
        con = get_db(); cur = con.cursor()
        cur.execute("SELECT ca_name,score FROM ca_scores WHERE student_id=%s AND subject=%s AND term_id=%s",
                    (sid, subject, term_id))
        ca_rows = cur.fetchall()
        cur.execute("SELECT score FROM exam_scores WHERE student_id=%s AND subject=%s AND term_id=%s",
                    (sid, subject, term_id))
        exam_row = cur.fetchone(); cur.close(); con.close()
        ca_map = {r[0]:r[1] for r in ca_rows}
        if not ca_map and not exam_row: continue
        ca_scores = {f"CA{i}": ca_map.get(f"CA{i}") for i in range(1, ca_count+1)}
        exam_val  = exam_row[0] if exam_row else None
        final_val = calc_final(sid, subject, term_id)
        subj_pos  = get_subject_position(sid,subject,class_id,stream_id,term_id) if final_val is not None else "-"
        results.append({
            "subject":subject,"ca":ca_scores,"exam":exam_val,
            "final":round(final_val,1) if final_val is not None else None,
            "grade":get_grade(final_val) if final_val is not None else "-",
            "position":subj_pos,
        })
    c_pos,c_total,s_pos,s_total = get_positions(sid,class_id,stream_id,term_id)
    avg = calc_student_average(sid,term_id)
    return jsonify({
        "ok":True,"student":student,"term":term,"results":results,
        "ca_count":ca_count,"average":round(avg,2),"grade":get_grade(avg),
        "class_position":c_pos,"class_total":c_total,
        "stream_position":s_pos,"stream_total":s_total,
    })

@app.route("/api/parent/terms", methods=["GET"])
def api_parent_terms():
    con = get_db(); cur = con.cursor()
    cur.execute("""SELECT t.id,t.label,t.ca_count,t.ca_weight,t.exam_weight,t.status
                   FROM terms t JOIN results_published rp ON rp.term_id=t.id
                   WHERE rp.published=1 ORDER BY t.id DESC""")
    rows = to_dicts(cur.fetchall(),cur); cur.close(); con.close()
    return jsonify(rows)
