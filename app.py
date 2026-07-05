"""
School Manager - Flask API Backend (v7 - Full Multi-Tenant)
"""
import hashlib, os, tempfile, secrets, json
import psycopg2, psycopg2.extras
from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename

app = Flask(__name__)
CORS(app)

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
DATABASE_URL  = os.environ.get("DATABASE_URL", "")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "storage", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
ALLOWED_LOGO_EXT = {"png","jpg","jpeg","gif","webp","svg"}

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

# ── SCHOOL_ID HELPERS ─────────────────────────────────────────
def school_id_from_header():
    sid = request.headers.get("X-School-ID")
    if sid:
        try: return int(sid)
        except: pass
    return 1

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

    con.commit(); cur.close(); con.close()
    print("DB ready (multi-tenant).")


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
    if not school_name: return jsonify({"ok":False,"error":"School name required"}), 400
    if not admin_user or not admin_pass: return jsonify({"ok":False,"error":"Admin username and password required"}), 400
    logo_path = ""
    if "logo" in request.files:
        f = request.files["logo"]
        if f and f.filename:
            ext = f.filename.rsplit(".",1)[-1].lower() if "." in f.filename else ""
            if ext not in ALLOWED_LOGO_EXT: return jsonify({"ok":False,"error":"Logo must be an image"}), 400
            logos_dir = os.path.join(UPLOAD_FOLDER, "logos")
            os.makedirs(logos_dir, exist_ok=True)
            fname = secure_filename(f"school_logo_{secrets.token_hex(6)}.{ext}")
            f.save(os.path.join(logos_dir, fname))
            logo_path = f"storage/uploads/logos/{fname}"
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
        cur.execute("INSERT INTO schools(school_name) VALUES(%s) RETURNING id", (school_name,))
        school_id = cur.fetchone()[0]
        cur.execute("INSERT INTO users(username,password,role,school_id) VALUES(%s,%s,'admin',%s)",
                    (admin_user, hash_password(admin_pass), school_id))
        cfg = {"school_name":school_name,"phone":phone,"email":email,"admin_phone":admin_phone,
               "motto":motto,"logo_path":logo_path,"registration_complete":"1"}
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
    d = request.json
    u, p = d.get("username","").strip(), d.get("password","")
    hint_sid = request.headers.get("X-School-ID")
    if not u or not p: return jsonify({"ok":False,"error":"Enter username and password"}), 400
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM users WHERE username=%s", (u,))
    rows = cur.fetchall(); cols = [x[0] for x in cur.description]
    cur.close(); con.close()
    if not rows: return jsonify({"ok":False,"error":"Invalid username or password"}), 401
    user = None
    if hint_sid:
        try: hint_sid = int(hint_sid)
        except: hint_sid = None
    for row in rows:
        r = dict(zip(cols, row))
        if hint_sid and r["school_id"] != hint_sid: continue
        if verify_password(p, r["password"]): user = r; break
    if not user:
        for row in rows:
            r = dict(zip(cols, row))
            if verify_password(p, r["password"]): user = r; break
    if not user: return jsonify({"ok":False,"error":"Invalid username or password"}), 401
    school_id = user["school_id"]
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
    school_id = request.args.get("school_id",1,type=int)
    keys = ["school_name","phone","email","admin_phone","motto","logo_path","registration_complete"]
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT key,value FROM school_config WHERE school_id=%s AND key=ANY(%s)", (school_id, keys))
    rows = cur.fetchall(); cur.close(); con.close()
    return jsonify({r[0]:r[1] for r in rows})

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
    cur.execute("INSERT INTO students(school_id,name,class_id,stream_id,phone_number) VALUES(%s,%s,%s,%s,%s) RETURNING id",
                (sid,name,class_id,stream_id,phone))
    student_id = cur.fetchone()[0]; con.commit(); cur.close(); con.close()
    username, temp_pw = _gen_parent_creds(sid, name, phone, student_id)
    con = get_db(); cur = con.cursor()
    cur.execute("INSERT INTO users(username,password,role,school_id,must_change_password,student_id) VALUES(%s,%s,'parent',%s,1,%s) ON CONFLICT(username,school_id) DO NOTHING",
                (username, hash_password(temp_pw), sid, student_id))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok":True,"parent_username":username,"temp_password":temp_pw})

def _gen_parent_creds(school_id, student_name, phone_number, student_id):
    phone_clean = phone_number.strip(); last4 = phone_clean[-4:]
    username_base = student_name.strip().lower().replace(" ","_")
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT id FROM students WHERE school_id=%s AND phone_number=%s AND id!=%s ORDER BY id",
                (school_id,phone_clean,student_id))
    siblings = cur.fetchall()
    cur.execute("SELECT username FROM users WHERE school_id=%s AND role='parent' AND username LIKE %s",
                (school_id,username_base+"%"))
    existing = [r[0] for r in cur.fetchall()]; cur.close(); con.close()
    if siblings:
        con = get_db(); cur = con.cursor()
        cur.execute("SELECT id FROM students WHERE school_id=%s AND phone_number=%s ORDER BY id",(school_id,phone_clean))
        all_same=[r[0] for r in cur.fetchall()]; cur.close(); con.close()
        try: idx=all_same.index(student_id)+1
        except ValueError: idx=len(all_same)+1
        temp_pw=f"{last4}-{idx}"
    else: temp_pw=last4
    final_user=username_base; counter=2
    while final_user in existing: final_user=f"{username_base}_{counter}"; counter+=1
    return final_user, temp_pw

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
    tid=term["id"]; ca_count=term["ca_count"]
    class_id=student["class_id"]; stream_id=student["stream_id"]
    c_pos,c_total,s_pos,s_total = get_positions(sid,student_id,class_id,stream_id,tid)
    avg = calc_student_average(sid,student_id,tid)
    rows = []
    for subject in subjects:
        con = get_db(); cur = con.cursor()
        cur.execute("SELECT ca_name,score FROM ca_scores WHERE school_id=%s AND student_id=%s AND subject=%s AND term_id=%s",
                    (sid,student_id,subject,tid))
        ca_rows = cur.fetchall()
        cur.execute("SELECT score FROM exam_scores WHERE school_id=%s AND student_id=%s AND subject=%s AND term_id=%s",
                    (sid,student_id,subject,tid))
        exam_row = cur.fetchone(); cur.close(); con.close()
        ca_map   = {r[0]:r[1] for r in ca_rows}
        ca_scores= {f"CA{i}": ca_map.get(f"CA{i}") for i in range(1,ca_count+1)}
        exam_val = exam_row[0] if exam_row else None
        final_val= calc_final(sid,student_id,subject,tid)
        subj_pos = get_subject_position(sid,student_id,subject,class_id,stream_id,tid) if final_val is not None else "-"
        rows.append({"subject":subject,"ca":ca_scores,"exam":exam_val,
                     "final":round(final_val,1) if final_val is not None else None,
                     "grade":get_grade(sid,final_val) if final_val is not None else "-","position":subj_pos})
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM remarks WHERE school_id=%s AND student_id=%s AND term_id=%s",(sid,student_id,tid))
    rmk_row = cur.fetchone(); rmk = to_dict(rmk_row,cur) if rmk_row else None
    cur.close(); con.close()
    return jsonify({"ok":True,"student":student,"term":term,"rows":rows,
                    "average":round(avg,2),"grade":get_grade(sid,avg),
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
    studs=get_students_in_scope(sid,class_id,stream_id); rows=[]
    for s in studs:
        con=get_db(); cur=con.cursor()
        if assess=="exam":
            cur.execute("SELECT score FROM exam_scores WHERE school_id=%s AND student_id=%s AND subject=%s AND term_id=%s",
                        (sid,s["id"],subject,term_id))
        else:
            cur.execute("SELECT score FROM ca_scores WHERE school_id=%s AND student_id=%s AND subject=%s AND ca_name=%s AND term_id=%s",
                        (sid,s["id"],subject,assess,term_id))
        row=cur.fetchone(); cur.close(); con.close()
        if row: rows.append({"id":s["id"],"name":s["name"],"score":round(row[0],2),"grade":get_grade(sid,row[0])})
    _assign_positions(rows,"score"); return jsonify(rows)

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
    studs=get_students_in_scope(sid,class_id,stream_id); results=[]
    for s in studs:
        row={"id":s["id"],"name":s["name"],"stream_name":s.get("stream_name"),"scores":{},"total":0,"count":0}
        for subject in subjects:
            score=None
            con=get_db(); cur=con.cursor()
            if mode=="ca":
                cur.execute("SELECT score FROM ca_scores WHERE school_id=%s AND student_id=%s AND subject=%s AND ca_name=%s AND term_id=%s",
                            (sid,s["id"],subject,ca_name,term_id))
                r=cur.fetchone(); score=r[0] if r else None
            elif mode=="exam":
                cur.execute("SELECT score FROM exam_scores WHERE school_id=%s AND student_id=%s AND subject=%s AND term_id=%s",
                            (sid,s["id"],subject,term_id))
                r=cur.fetchone(); score=r[0] if r else None
            cur.close(); con.close()
            if mode=="terminal": f=calc_final(sid,s["id"],subject,term_id); score=round(f,1) if f is not None else None
            row["scores"][subject]=score
            if score is not None: row["total"]+=score; row["count"]+=1
        row["average"]=round(row["total"]/row["count"],2) if row["count"] else 0
        row["grade"]=get_grade(sid,row["average"]); results.append(row)
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
def api_post_announcement():
    sid=school_id_from_header(); d=request.json
    title=d.get("title","").strip(); body=d.get("body","").strip()
    posted_by=d.get("posted_by",""); target_classes=d.get("target_classes","all").strip()
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
    ca_count=term["ca_count"]; class_id=student["class_id"]; stream_id=student["stream_id"]
    results=[]
    for subject in subjects:
        con=get_db(); cur=con.cursor()
        cur.execute("SELECT ca_name,score FROM ca_scores WHERE school_id=%s AND student_id=%s AND subject=%s AND term_id=%s",
                    (sid,stid,subject,term_id))
        ca_rows=cur.fetchall()
        cur.execute("SELECT score FROM exam_scores WHERE school_id=%s AND student_id=%s AND subject=%s AND term_id=%s",
                    (sid,stid,subject,term_id))
        exam_row=cur.fetchone(); cur.close(); con.close()
        ca_map={r[0]:r[1] for r in ca_rows}
        ca_scores={f"CA{i}": ca_map.get(f"CA{i}") for i in range(1,ca_count+1)}
        exam_val=exam_row[0] if exam_row else None
        if assess:
            score=exam_val if assess=="exam" else ca_map.get(assess)
            if score is None: continue
            scope=get_students_in_scope(sid,class_id,stream_id)
            scores_list=[]
            con=get_db(); cur=con.cursor()
            for st in scope:
                if assess=="exam":
                    cur.execute("SELECT score FROM exam_scores WHERE school_id=%s AND student_id=%s AND subject=%s AND term_id=%s",
                                (sid,st["id"],subject,term_id))
                else:
                    cur.execute("SELECT score FROM ca_scores WHERE school_id=%s AND student_id=%s AND subject=%s AND ca_name=%s AND term_id=%s",
                                (sid,st["id"],subject,assess,term_id))
                r2=cur.fetchone()
                if r2: scores_list.append({"id":st["id"],"score":r2[0]})
            cur.close(); con.close()
            _assign_positions(scores_list,"score")
            pos=next((x["position"] for x in scores_list if x["id"]==stid),"-")
            results.append({"subject":subject,"ca":ca_scores,"exam":exam_val,"score":score,
                            "grade":get_grade(sid,score),"position":pos})
        else:
            if not ca_map and exam_val is None: continue
            final_val=calc_final(sid,stid,subject,term_id)
            subj_pos=get_subject_position(sid,stid,subject,class_id,stream_id,term_id) if final_val is not None else "-"
            results.append({"subject":subject,"ca":ca_scores,"exam":exam_val,
                            "final":round(final_val,1) if final_val is not None else None,
                            "grade":get_grade(sid,final_val) if final_val is not None else "-","position":subj_pos})
    c_pos,c_total,s_pos,s_total=get_positions(sid,stid,class_id,stream_id,term_id)
    if assess and results:
        scores_only=[r["score"] for r in results if r.get("score") is not None]
        avg=round(sum(scores_only)/len(scores_only),2) if scores_only else 0
    else: avg=round(calc_student_average(sid,stid,term_id),2)
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
                   WHERE pa.target='all' OR pa.target LIKE %s
                   ORDER BY pa.posted_at DESC""",(sid,f"%{sid}%"))
    rows=to_dicts(cur.fetchall(),cur); cur.close(); con.close(); return jsonify(rows)

@app.route("/api/platform_announcements/<int:aid>/read", methods=["POST"])
def api_platform_announcement_read(aid):
    sid=school_id_from_header()
    con=get_db(); cur=con.cursor()
    cur.execute("INSERT INTO platform_announcement_reads(announcement_id,school_id) VALUES(%s,%s) ON CONFLICT DO NOTHING",(aid,sid))
    con.commit(); cur.close(); con.close(); return jsonify({"ok":True})


# ── PDF ────────────────────────────────────────────────────────
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm

def _get_logo_element(school_id, max_h=2*cm):
    path = get_config_val(school_id,"logo_path","")
    if not path: return None
    full = os.path.join(BASE_DIR, path)
    if os.path.exists(full):
        try:
            img=Image(full); img.drawHeight=max_h; img.drawWidth=max_h; return img
        except: pass
    return None

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

def _blue_sheet_pdf(school_id,filename,subtitle,students,subjects,get_score_fn,term=None):
    subj_map=get_subject_map(school_id)
    H_BG=colors.HexColor("#1A6FA8"); S_BG=colors.HexColor("#5BA4CF")
    ODD=colors.HexColor("#E8F4FC"); EVEN=colors.white
    RED=colors.HexColor("#C0392B"); WHITE=colors.white
    doc=SimpleDocTemplate(filename,pagesize=landscape(A4),rightMargin=1.2*cm,leftMargin=1.2*cm,topMargin=1.2*cm,bottomMargin=1.2*cm)
    styles=getSampleStyleSheet(); story=[]
    tl=term["label"] if term else ""
    story+=_school_header_story(school_id,styles,subtitle,tl)
    results=[]
    for s in students:
        row={"name":s["name"],"stream":s.get("stream_name") or "","scores":{},"total":0,"count":0}
        for subj in subjects:
            sc=get_score_fn(s["id"],subj); row["scores"][subj]=sc
            if sc is not None: row["total"]+=sc; row["count"]+=1
        row["average"]=row["total"]/row["count"] if row["count"] else 0
        row["grade"]=get_grade(school_id,row["average"]); results.append(row)
    _assign_positions(results,"average")
    has_streams=any(r["stream"] for r in results)
    hdr=["#","Student"]
    if has_streams: hdr.append("Stream")
    hdr+=[subj_map.get(s,s[:4].upper()) for s in subjects]+["Total","Avg","Pos","Grd"]
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
              str(r["position"]),r["grade"] if r["count"] else "-"]
        tdata.append(row)
    sc_w=1.2*cm; extra=0.8*cm if has_streams else 0
    cw=[0.7*cm,3.0*cm]+([extra] if has_streams else [])+[sc_w]*len(subjects)+[1.5*cm,1.3*cm,0.9*cm,1.0*cm]
    tbl=Table(tdata,colWidths=cw,repeatRows=1)
    ts=[("BACKGROUND",(0,0),(-1,0),H_BG),("TEXTCOLOR",(0,0),(-1,0),WHITE),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,0),6.5),
        ("ALIGN",(0,0),(-1,0),"CENTER"),("FONTNAME",(0,1),(-1,-1),"Helvetica"),
        ("FONTSIZE",(0,1),(-1,-1),7),("ALIGN",(0,1),(-1,-1),"CENTER"),("ALIGN",(1,1),(1,-1),"LEFT"),
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
    c_pos,c_total,s_pos,s_total=get_positions(school_id,sid,class_id,stream_id,tid)
    safe=student["name"].replace(" ","_")
    fname=os.path.join(tempfile.gettempdir(),f"RC_{school_id}_{safe}_{tid}.pdf")
    doc=SimpleDocTemplate(fname,pagesize=A4,rightMargin=1.5*cm,leftMargin=1.5*cm,topMargin=1.5*cm,bottomMargin=1.5*cm)
    styles=getSampleStyleSheet(); story=[]
    H_BG=colors.HexColor("#1A6FA8"); ODD=colors.HexColor("#E8F4FC"); WHITE=colors.white; RED=colors.HexColor("#C0392B")
    story+=_school_header_story(school_id,styles,"STUDENT REPORT CARD")
    stream_label=f"{student['class_name']} {student['stream_name']}" if student.get("stream_name") else student["class_name"]
    avg=calc_student_average(school_id,sid,tid)
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
        con=get_db(); cur=con.cursor()
        cur.execute("SELECT ca_name,score FROM ca_scores WHERE school_id=%s AND student_id=%s AND subject=%s AND term_id=%s",
                    (school_id,sid,subject,tid))
        ca_rows=cur.fetchall()
        cur.execute("SELECT score FROM exam_scores WHERE school_id=%s AND student_id=%s AND subject=%s AND term_id=%s",
                    (school_id,sid,subject,tid))
        exam_row=cur.fetchone(); cur.close(); con.close()
        ca_map={r[0]:r[1] for r in ca_rows}
        row_data=[subject.title()]+[f"{ca_map.get(f'CA{i}'):.1f}" if ca_map.get(f"CA{i}") is not None else "-" for i in range(1,ca_count+1)]
        exam_v=exam_row[0] if exam_row else None
        row_data.append(f"{exam_v:.1f}" if exam_v is not None else "-")
        final_v=calc_final(school_id,sid,subject,tid)
        if final_v is not None: tot+=final_v; cnt+=1
        row_data.append(f"{final_v:.1f}" if final_v is not None else "-")
        row_data.append(str(get_subject_position(school_id,sid,subject,class_id,stream_id,tid)) if final_v is not None else "-")
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
    def get_score(stid,subj):
        con=get_db(); cur=con.cursor()
        cur.execute("SELECT score FROM ca_scores WHERE school_id=%s AND student_id=%s AND subject=%s AND ca_name=%s AND term_id=%s",
                    (school_id,stid,subj,ca_name,tid))
        r=cur.fetchone(); cur.close(); con.close(); return r[0] if r else None
    _blue_sheet_pdf(school_id,fname,f"{ca_name.upper()} SCORE SHEET",studs,subjects,get_score,term)
    return send_file(fname,as_attachment=True,download_name=os.path.basename(fname),mimetype="application/pdf")

@app.route("/api/pdf/terminal_sheet", methods=["GET"])
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
    def get_score(stid,subj):
        f=calc_final(school_id,stid,subj,tid); return round(f,1) if f is not None else None
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
            result.append({"id":sid,"school_name":s["school_name"],"registered_at":s.get("cast") or "—",
                           "student_count":sc,"teacher_count":tc,"active_term":at,"payment_status":"pending"})
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

# ── STATIC ─────────────────────────────────────────────────────
_STATIC_FILES=["shared.css","shared.js","page-dashboard.js","page-students.js",
               "page-teachers.js","page-reports.js","page-parent.js","page-config.js"]

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
            row_dict = dict(zip(headers, [str(v).strip() if v is not None else "" for v in row]))
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
    """Try multiple possible column name spellings."""
    for c in candidates:
        if c in row and row[c]: return row[c].strip()
    return ""

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
        rows = [
    r for r in rows
    if any(str(v).strip() for v in r.values() if v is not None)
]
    except ValueError as e:
        return jsonify({"ok":False,"error":str(e)}), 400
    if not rows:
        return jsonify({"ok":False,"error":"File is empty or has no data rows"}), 400
    cmap = _build_class_map(school_id)
    preview = []; warnings = []
    for i, row in enumerate(rows[:10]):
        name         = _normalize_col(row,"name","student name","full name","jina","student")
        class_name   = _normalize_col(row,"class_name","class","darasa","form","grade")
        stream_name  = _normalize_col(row,"stream_name","stream","mkondo","section","division")
        parent_phone = _normalize_col(row,"parent_phone","phone","parent phone","phone number","simu","contact","guardian phone")
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

@app.route("/api/students/import", methods=["POST"])
def api_import_students():
    """Full import: parse, validate, bulk insert."""
    school_id = school_id_from_header()
    if "file" not in request.files:
        return jsonify({"ok":False,"error":"No file uploaded"}), 400
    f = request.files["file"]
    try:
        rows = _parse_import_file(f.stream, f.filename)
    except ValueError as e:
        return jsonify({"ok":False,"error":str(e)}), 400
    if not rows:
        return jsonify({"ok":False,"error":"File is empty"}), 400
    cmap     = _build_class_map(school_id)
    inserted = 0; skipped = []; errors = []
    con = get_db(); cur = con.cursor()
    for i, row in enumerate(rows):
        row_num      = i + 2
        name         = _normalize_col(row,"name","student name","full name","jina","student")
        class_name   = _normalize_col(row,"class_name","class","darasa","form","grade")
        stream_name  = _normalize_col(row,"stream_name","stream","mkondo","section","division")
        parent_phone = _normalize_col(row,"parent_phone","phone","parent phone","phone number","simu","contact","guardian phone")
        if not name or not class_name or not parent_phone:
            skipped.append({"row":row_num,"reason":"Missing required field","data":str(row)})
            continue
        ckey = class_name.strip().lower()
        if ckey not in cmap:
            skipped.append({"row":row_num,"reason":f"Class '{class_name}' not found. Check spelling.","data":name})
            continue
        class_id  = cmap[ckey]["_id"]
        stream_id = None
        if stream_name:
            skey = stream_name.strip().lower()
            if skey in cmap[ckey]["_streams"]:
                class_id, stream_id = cmap[ckey]["_streams"][skey]
            else:
                skipped.append({"row":row_num,"reason":f"Stream '{stream_name}' not found in class '{class_name}'","data":name})
                continue
        try:
            cur.execute("INSERT INTO students(school_id,name,class_id,stream_id,phone_number) VALUES(%s,%s,%s,%s,%s) RETURNING id",
                        (school_id, name, class_id, stream_id, parent_phone))
            student_id   = cur.fetchone()[0]
            username_base= name.strip().lower().replace(" ","_")
            last4        = parent_phone.strip()[-4:]
            # Check for same phone (siblings)
            cur.execute("SELECT id FROM students WHERE school_id=%s AND phone_number=%s AND id!=%s ORDER BY id",
                        (school_id, parent_phone, student_id))
            siblings = cur.fetchall()
            if siblings:
                cur.execute("SELECT id FROM students WHERE school_id=%s AND phone_number=%s ORDER BY id",(school_id,parent_phone))
                all_s=[r[0] for r in cur.fetchall()]
                try: idx=all_s.index(student_id)+1
                except ValueError: idx=len(all_s)+1
                temp_pw=f"{last4}-{idx}"
            else: temp_pw=last4
            cur.execute("SELECT username FROM users WHERE school_id=%s AND role='parent' AND username LIKE %s",
                        (school_id, username_base+"%"))
            existing=[r[0] for r in cur.fetchall()]
            final_user=username_base; counter=2
            while final_user in existing: final_user=f"{username_base}_{counter}"; counter+=1
            cur.execute("INSERT INTO users(username,password,role,school_id,must_change_password,student_id) VALUES(%s,%s,'parent',%s,1,%s) ON CONFLICT(username,school_id) DO NOTHING",
                        (final_user,hash_password(temp_pw),school_id,student_id))
            inserted += 1
        except Exception as e:
            errors.append({"row":row_num,"error":str(e),"data":name})
    con.commit(); cur.close(); con.close()
    return jsonify({"ok":True,"inserted":inserted,"skipped":len(skipped),"errors":len(errors),
                    "skipped_details":skipped[:20],"error_details":errors[:20]})


with app.app_context():
    init_db()

if __name__=="__main__":
    app.run(debug=False,host="0.0.0.0",port=int(os.environ.get("PORT",5000)))
