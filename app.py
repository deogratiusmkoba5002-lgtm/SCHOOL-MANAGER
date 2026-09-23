"""
School Manager - Flask API Backend (v7 - Full Multi-Tenant)
"""
import hashlib, os, tempfile, secrets, json, re, io, base64, time, hmac, uuid
import requests
import psycopg2, psycopg2.extras
from flask import Flask, request, jsonify, send_file, send_from_directory, g
from flask_cors import CORS
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
from config import (
    BASE_DIR, DATABASE_URL, UPLOAD_FOLDER, IMPORT_EXPORT_FOLDER,
    ALLOWED_LOGO_EXT, _mime_for_ext,
    _FALLBACK_SUBJECTS, _FALLBACK_ABBR, _FALLBACK_GRADES,
    SUBSCRIPTION_PLANS, SECRET_KEY, SESSION_MAX_AGE, SA_SESSION_MAX_AGE,
)
from core.db import get_db, to_dict, to_dicts
from core.security import hash_password, verify_password, hash_password_fast
from core.school import (
    school_id_from_header, valid_reg_code, format_student_display_id,
    get_school_id_by_reg_code, generate_unique_reg_code,
    get_config_val, set_config_val, get_school_name, is_registration_complete,
)

from services.grading import (
    get_grade_rules, get_grade, get_school_grading_settings, get_necta_grades,
    get_necta_divisions, get_grade_points_rules, grade_and_points_for_score,
    get_principal_subjects, get_noncredit_subjects, compute_division_from_finals,
)

from services.scores import (
    get_subjects, get_subject_map, get_active_term, get_term_by_id,
    _get_all_terms_ordered, get_students_in_scope, get_all_students_in_school,
    get_term_tests, get_test_class_ids, _assign_positions,
    get_term_scores_bulk, _score_for_assess, _active_subjects_in_scores,
    _final_from_entry, compute_student_finals, compute_average_from_finals,
    get_subject_rank_map, get_subject_assess_rank_map, get_class_report_data,
)

from services.analytics import (
    _compute_overall_series, _compute_subject_series,
    _build_common_cards, _best_weakest_subject,
)

from services.subscriptions import (
    is_subscribed, _expire_stale_payment_requests,
    subscription_required, _platform_payment_config,
)

from services.students_import import (
    OPENPYXL_AVAILABLE, openpyxl,
    _parse_import_file, _normalize_col, _col_by_position, _extract_fields,
    _build_class_map, _normalize_class_key, _resolve_class_stream,
    _write_credentials_xlsx,
)


try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("WARNING: python-dotenv not installed — .env file will NOT be loaded. "
          "Run: pip install python-dotenv")

app = Flask(__name__)
CORS(app)

from routes.auth_routes import auth_bp
from routes.registration_routes import registration_bp
from routes.classes_routes import classes_bp
from routes.teachers_routes import teachers_bp
from routes.terms_routes import terms_bp
from routes.static_routes import static_bp

app.register_blueprint(auth_bp)
app.register_blueprint(registration_bp)
app.register_blueprint(classes_bp)
app.register_blueprint(teachers_bp)
app.register_blueprint(terms_bp)
app.register_blueprint(static_bp)

from core.auth import (
    issue_token, require_auth, require_role,
    LOGIN_MAX_ATTEMPTS, LOGIN_WINDOW_MINUTES,
    _login_attempts_count, _record_login_attempt,
    _sa_token, _require_superadmin, _sa_serializer,
)

def teacher_can_access(school_id, username, subject, class_id, stream_id=None):
    con = get_db(); cur = con.cursor()
    cur.execute("""SELECT id FROM subject_assignments
                   WHERE school_id=%s AND username=%s AND subject=%s AND class_id=%s
                   AND (stream_id=%s OR stream_id IS NULL)""",
                (school_id, username, subject, class_id, stream_id))
    row = cur.fetchone(); cur.close(); con.close()
    return row is not None



@app.route("/api/marks/test", methods=["POST"])
@require_auth
@require_role("admin","teacher")
def api_enter_test():
    sid = g.school_id; d = request.json
    username = g.username
    subject=d.get("subject","").lower().strip()
    class_id=int(d.get("class_id")); stream_id=d.get("stream_id") or None
    student_id=int(d.get("student_id")); test_id=int(d.get("test_id")); score=float(d.get("score"))
    if not (0<=score<=100): return jsonify({"ok":False,"error":"Score must be 0-100"}),400
    if g.role=="teacher" and not teacher_can_access(sid,username,subject,class_id,stream_id):
        return jsonify({"ok":False,"error":"Access denied"}),403
    con=get_db(); cur=con.cursor()
    cur.execute("SELECT term_id, all_classes FROM term_tests WHERE id=%s AND school_id=%s",(test_id,sid))
    row=cur.fetchone()
    if not row: cur.close(); con.close(); return jsonify({"ok":False,"error":"Test not found"}),404
    term_id, all_classes = row
    if not all_classes:
        cur.execute("SELECT 1 FROM test_classes WHERE test_id=%s AND class_id=%s",(test_id,class_id))
        if not cur.fetchone():
            cur.close(); con.close()
            return jsonify({"ok":False,"error":"This class is not part of this test"}),403
    cur.execute("""INSERT INTO test_scores(school_id,student_id,subject,test_id,score,entered_by,term_id)
                   VALUES(%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT(school_id,student_id,subject,test_id,term_id)
                   DO UPDATE SET score=EXCLUDED.score,entered_by=EXCLUDED.entered_by""",
                (sid,student_id,subject,test_id,score,username,term_id))
    con.commit(); cur.close(); con.close(); return jsonify({"ok":True})


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
    CREATE TABLE IF NOT EXISTS necta_grades (
    id SERIAL PRIMARY KEY,
    level TEXT NOT NULL,
    min_score REAL NOT NULL,
    max_score REAL NOT NULL,
    grade TEXT NOT NULL,
    points INTEGER NOT NULL,
    sort_order INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS necta_divisions (
        id SERIAL PRIMARY KEY,
        level TEXT NOT NULL,
        min_points INTEGER NOT NULL,
        max_points INTEGER NOT NULL,
        division TEXT NOT NULL,
        sort_order INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS term_tests (
        id         SERIAL PRIMARY KEY,
        school_id  INTEGER NOT NULL,
        term_id    INTEGER NOT NULL,
        label      TEXT NOT NULL,
        all_classes INTEGER NOT NULL DEFAULT 1,
        created_at TIMESTAMP DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS test_classes (
        test_id  INTEGER NOT NULL,
        class_id INTEGER NOT NULL,
        PRIMARY KEY(test_id, class_id)
    );
    CREATE TABLE IF NOT EXISTS test_scores (
        id         SERIAL PRIMARY KEY,
        school_id  INTEGER NOT NULL,
        student_id INTEGER NOT NULL,
        subject    TEXT NOT NULL,
        test_id    INTEGER NOT NULL,
        score      REAL NOT NULL,
        entered_by TEXT,
        term_id    INTEGER NOT NULL,
        UNIQUE(school_id, student_id, subject, test_id, term_id)
    );
    CREATE TABLE IF NOT EXISTS published_assessments (
        school_id  INTEGER NOT NULL,
        term_id    INTEGER NOT NULL,
        assess_key TEXT NOT NULL,
        published  INTEGER DEFAULT 0,
        PRIMARY KEY(school_id, term_id, assess_key)
    );
    CREATE TABLE IF NOT EXISTS login_attempts (
        id          SERIAL PRIMARY KEY,
        identifier  TEXT NOT NULL,
        attempted_at TIMESTAMP DEFAULT NOW() 
    );
    CREATE TABLE IF NOT EXISTS import_credential_batches (
        id         SERIAL PRIMARY KEY,
        school_id  INTEGER NOT NULL,
        token      TEXT NOT NULL UNIQUE,
        data       JSONB NOT NULL,
        created_at TIMESTAMP DEFAULT NOW()
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
        "ALTER TABLE schools ADD COLUMN IF NOT EXISTS grading_system TEXT DEFAULT 'o_level'",
        "ALTER TABLE schools ADD COLUMN IF NOT EXISTS division_source TEXT DEFAULT 'school'",
        "ALTER TABLE school_subjects ADD COLUMN IF NOT EXISTS is_principal INTEGER DEFAULT 0",
        "ALTER TABLE grade_config ADD COLUMN IF NOT EXISTS points INTEGER",
        "ALTER TABLE school_subjects ADD COLUMN IF NOT EXISTS is_noncredit INTEGER DEFAULT 0",
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS school_student_no INTEGER",
        "ALTER TABLE term_tests ADD COLUMN IF NOT EXISTS all_classes INTEGER NOT NULL DEFAULT 1",
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS flag_reason TEXT DEFAULT NULL",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS token_version INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS token_version INTEGER DEFAULT 0",
        "ALTER TABLE schools ADD COLUMN IF NOT EXISTS terms_accepted_at TIMESTAMP",
        "ALTER TABLE schools ADD COLUMN IF NOT EXISTS terms_accepted_by TEXT",
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
        cur.execute("SELECT COUNT(*) FROM necta_grades")
        if cur.fetchone()[0] == 0:
            o_level = [(80,100,'A',1),(70,79,'B',2),(60,69,'C',3),(50,59,'D',4),(0,49,'F',5)]
            a_level = [(80,100,'A',1),(70,79,'B',2),(60,69,'C',3),(50,59,'D',4),
                    (40,49,'E',5),(35,39,'S',6),(0,34,'F',7)]
            for i,(lo,hi,g,p) in enumerate(o_level):
                cur.execute("INSERT INTO necta_grades(level,min_score,max_score,grade,points,sort_order) VALUES('o_level',%s,%s,%s,%s,%s)",(lo,hi,g,p,i))
            for i,(lo,hi,g,p) in enumerate(a_level):
                cur.execute("INSERT INTO necta_grades(level,min_score,max_score,grade,points,sort_order) VALUES('a_level',%s,%s,%s,%s,%s)",(lo,hi,g,p,i))
            o_div = [(7,17,'I'),(18,21,'II'),(22,25,'III'),(26,33,'IV'),(34,50,'0')]
            a_div = [(3,9,'I'),(10,12,'II'),(13,17,'III'),(18,19,'IV'),(20,21,'0')]
            for i,(lo,hi,d) in enumerate(o_div):
                cur.execute("INSERT INTO necta_divisions(level,min_points,max_points,division,sort_order) VALUES('o_level',%s,%s,%s,%s)",(lo,hi,d,i))
            for i,(lo,hi,d) in enumerate(a_div):
                cur.execute("INSERT INTO necta_divisions(level,min_points,max_points,division,sort_order) VALUES('a_level',%s,%s,%s,%s)",(lo,hi,d,i))
    except Exception as e:
        print(f"necta seed note: {e}")
    try:
        cur.execute("""UPDATE students s
                       SET school_student_no = sub.rn
                       FROM (SELECT id, ROW_NUMBER() OVER (PARTITION BY school_id ORDER BY id) AS rn
                             FROM students WHERE school_student_no IS NULL) sub
                       WHERE s.id = sub.id""")
    except Exception as e:
        print(f"school_student_no backfill note: {e}")
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
        cur.execute("CREATE INDEX IF NOT EXISTS idx_login_attempts_identifier ON login_attempts(identifier, attempted_at)")
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
# ════════════════════════════════════════════════════════════

# ── SUBJECTS / GRADES ─────────────────────────────────────────
@app.route("/api/subjects", methods=["GET"])
@require_auth
def api_get_subjects():
    sid = g.school_id
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT id,name,abbreviation,sort_order FROM school_subjects WHERE school_id=%s ORDER BY sort_order,name",(sid,))
    rows = to_dicts(cur.fetchall(), cur); cur.close(); con.close()
    if rows: return jsonify(rows)
    return jsonify([{"id":i,"name":n,"abbreviation":_FALLBACK_ABBR.get(n,n[:4].upper()),"sort_order":i} for i,n in enumerate(_FALLBACK_SUBJECTS)])

@app.route("/api/subjects", methods=["POST"])
@require_auth
@require_role("admin")
def api_save_subjects():
    sid = g.school_id; subjects = request.json.get("subjects",[])
    con = get_db(); cur = con.cursor()
    cur.execute("DELETE FROM school_subjects WHERE school_id=%s",(sid,))
    for i,s in enumerate(subjects):
        name=s.get("name","").strip().lower(); ab=s.get("abbreviation","").strip().upper()
        if name:
            cur.execute("INSERT INTO school_subjects(school_id,name,abbreviation,sort_order) VALUES(%s,%s,%s,%s)",(sid,name,ab,i))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok":True})

@app.route("/api/grades", methods=["POST"])
@require_auth
@require_role("admin")
def api_save_grades():
    sid = g.school_id; grades = request.json.get("grades",[])
    con = get_db(); cur = con.cursor()
    cur.execute("DELETE FROM grade_config WHERE school_id=%s",(sid,))
    for i,g in enumerate(grades):
        cur.execute("INSERT INTO grade_config(school_id,min_score,max_score,grade,sort_order) VALUES(%s,%s,%s,%s,%s)",
                    (sid,float(g["min_score"]),float(g["max_score"]),str(g["grade"]).strip(),i))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok":True})

@app.route("/api/config/grading_system", methods=["GET"])
@require_auth
def api_get_grading_system():
    sid = g.school_id
    s = get_school_grading_settings(sid)
    s["principal_subjects"] = get_principal_subjects(sid)
    s["non_credit_subjects"] = get_noncredit_subjects(sid)
    return jsonify(s)

@app.route("/api/config/grading_system", methods=["POST"])
@require_auth
@require_role("admin")
def api_set_grading_system():
    sid = g.school_id; d = request.json or {}
    grading_system = d.get("grading_system")
    division_source = d.get("division_source")
    if grading_system not in ("o_level","a_level"):
        return jsonify({"ok":False,"error":"Invalid grading system"}),400
    if division_source not in ("school","necta"):
        return jsonify({"ok":False,"error":"Invalid division source"}),400
    con=get_db(); cur=con.cursor()
    cur.execute("UPDATE schools SET grading_system=%s, division_source=%s WHERE id=%s",
                (grading_system, division_source, sid))
    con.commit(); cur.close(); con.close()
    principal = d.get("principal_subjects")
    if grading_system=="a_level" and isinstance(principal, list):
        con=get_db(); cur=con.cursor()
        cur.execute("UPDATE school_subjects SET is_principal=0 WHERE school_id=%s",(sid,))
        for name in principal:
            cur.execute("UPDATE school_subjects SET is_principal=1 WHERE school_id=%s AND name=%s",(sid,name.strip().lower()))
        con.commit(); cur.close(); con.close()
    noncredit = d.get("non_credit_subjects")
    if isinstance(noncredit, list):
        con=get_db(); cur=con.cursor()
        cur.execute("UPDATE school_subjects SET is_noncredit=0 WHERE school_id=%s",(sid,))
        for name in noncredit:
            cur.execute("UPDATE school_subjects SET is_noncredit=1 WHERE school_id=%s AND name=%s",(sid,name.strip().lower()))
        con.commit(); cur.close(); con.close()
    return jsonify({"ok":True})

# ── STUDENTS ──────────────────────────────────────────────────
@app.route("/api/students", methods=["GET"])
@require_auth
def api_students():
    sid = g.school_id
    con = get_db(); cur = con.cursor()
    cur.execute("""SELECT s.id,s.name,s.class_id,s.stream_id,c.class_name,st.stream_name,s.school_student_no,s.flag_reason
                   FROM students s JOIN classes c ON s.class_id=c.id
                   LEFT JOIN streams st ON s.stream_id=st.id
                   WHERE s.school_id=%s ORDER BY c.class_name,st.stream_name,s.name""",(sid,))
    rows = to_dicts(cur.fetchall(),cur); cur.close(); con.close()
    for r in rows: r["display_id"] = format_student_display_id(sid, r.pop("school_student_no", None))
    return jsonify(rows)

@app.route("/api/students", methods=["POST"])
@require_auth
@require_role("admin","teacher")
def api_add_student():
    sid = g.school_id; d = request.json
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
    cur.execute("""INSERT INTO students(school_id,name,class_id,stream_id,phone_number,school_student_no)
                   VALUES(%s,%s,%s,%s,%s,(SELECT COALESCE(MAX(school_student_no),0)+1 FROM students WHERE school_id=%s))
                   RETURNING id""",
                (sid,name,class_id,stream_id,phone,sid))
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
    last4 = phone_number.strip()[-4:]
    # Normally the password is just the last 4 digits of the parent's phone.
    # Only append "-{student_id}" when another student already shares this
    # exact username with a DIFFERENT phone number whose last 4 digits happen
    # to collide with this one.
    con = get_db(); cur = con.cursor()
    cur.execute("""SELECT s.phone_number FROM users u JOIN students s ON u.student_id = s.id
                   WHERE u.username=%s AND u.school_id=%s AND u.role='parent'""",
                (username, school_id))
    existing_phones = [r[0] or "" for r in cur.fetchall()]
    cur.close(); con.close()
    needs_suffix = any(
        ph.strip() != phone_number.strip() and ph.strip()[-4:] == last4
        for ph in existing_phones
    )
    temp_pw = f"{last4}-{student_id}" if needs_suffix else last4
    return username, temp_pw

@app.route("/api/students/resolve_display_id", methods=["GET"])
@require_auth
def api_resolve_display_id():
    sid = g.school_id
    no = request.args.get("no")
    if not no: return jsonify({"ok":False,"error":"Missing student number"}),400
    try: no = int(no)
    except ValueError: return jsonify({"ok":False,"error":"Invalid student ID"}),400
    con=get_db(); cur=con.cursor()
    cur.execute("SELECT id FROM students WHERE school_id=%s AND school_student_no=%s",(sid,no))
    row=cur.fetchone(); cur.close(); con.close()
    if not row: return jsonify({"ok":False,"error":"Student not found"}),404
    return jsonify({"ok":True,"id":row[0]})

@app.route("/api/students/bulk_delete", methods=["POST"])
@require_auth
@require_role("admin")
def api_bulk_delete_students():
    sid = g.school_id; ids = request.json.get("ids", [])
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
@require_auth
@require_role("admin")
def api_delete_student(student_id):
    sid = g.school_id;
    con = get_db(); cur = con.cursor()
    cur.execute("DELETE FROM announcement_reads WHERE student_id=%s",(student_id,))
    cur.execute("DELETE FROM remarks WHERE school_id=%s AND student_id=%s",(sid,student_id))
    cur.execute("DELETE FROM ca_scores WHERE school_id=%s AND student_id=%s",(sid,student_id))
    cur.execute("DELETE FROM exam_scores WHERE school_id=%s AND student_id=%s",(sid,student_id))
    cur.execute("DELETE FROM users WHERE school_id=%s AND student_id=%s AND role='parent'",(sid,student_id))
    cur.execute("DELETE FROM students WHERE id=%s AND school_id=%s",(student_id,sid))
    con.commit(); cur.close(); con.close(); return jsonify({"ok":True})

@app.route("/api/students/<int:student_id>", methods=["PATCH"])
@require_auth
@require_role("admin")
def api_update_student(student_id):
    """Edits name/class/stream/phone. If the change touches name or phone, regenerate their
    username/password to match."""
    sid = g.school_id; d = request.json or {}
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT name,class_id,stream_id,phone_number FROM students WHERE id=%s AND school_id=%s",(student_id,sid))
    row = cur.fetchone()
    if not row:
        cur.close(); con.close(); return jsonify({"ok":False,"error":"Student not found"}),404
    old_name, old_class_id, old_stream_id, old_phone = row

    name = (d.get("name") if d.get("name") is not None else old_name).strip()
    try:
        class_id = int(d.get("class_id", old_class_id))
    except (TypeError, ValueError):
        cur.close(); con.close(); return jsonify({"ok":False,"error":"Invalid class"}),400
    sd = d.get("stream_id", old_stream_id)
    stream_id = int(sd) if sd else None
    phone = (d.get("phone_number") if d.get("phone_number") is not None else (old_phone or "")).strip()

    if not name:
        cur.close(); con.close(); return jsonify({"ok":False,"error":"Name required"}),400
    cur.execute("SELECT id FROM classes WHERE id=%s AND school_id=%s",(class_id,sid))
    if not cur.fetchone():
        cur.close(); con.close(); return jsonify({"ok":False,"error":"Invalid class"}),400

    cur.execute("""SELECT id FROM students WHERE school_id=%s AND LOWER(TRIM(name))=%s AND class_id=%s
                   AND COALESCE(stream_id,0)=%s AND phone_number=%s AND id!=%s""",
                (sid, name.lower(), class_id, stream_id or 0, phone, student_id))
    if cur.fetchone():
        cur.close(); con.close()
        return jsonify({"ok":False,"error":"Another student with this name, class, stream and phone already exists"}),409

    name_changed  = name.lower() != (old_name or "").strip().lower()
    phone_changed = phone != (old_phone or "").strip()

    cur.execute("""SELECT username, must_change_password FROM users
                   WHERE school_id=%s AND student_id=%s AND role='parent'""",(sid, student_id))
    parent_row = cur.fetchone()

    new_username = new_password = cred_note = None

    if parent_row and (name_changed or phone_changed):
        old_username, must_change = parent_row
        if phone:
            last4 = phone[-4:]
            cur.execute("""SELECT s.phone_number FROM users u JOIN students s ON u.student_id=s.id
                           WHERE u.username=%s AND u.school_id=%s AND u.role='parent' AND u.student_id!=%s""",
                        (gen_username, sid, student_id))
            other_phones = [r[0] or "" for r in cur.fetchall()]
            needs_suffix = any(ph.strip()!=phone and ph.strip()[-4:]==last4 for ph in other_phones)
            new_password = f"{last4}-{student_id}" if needs_suffix else last4
            new_username = gen_username
            try:
                cur.execute("""UPDATE users SET username=%s, password=%s, must_change_password=1
                               WHERE username=%s AND school_id=%s AND student_id=%s, token_version=COALESCE(token_version,0)+1""",
                            (new_username, hash_password(new_password), old_username, sid, student_id))
            except psycopg2.errors.UniqueViolation:
                con.rollback(); cur.close(); con.close()
                return jsonify({"ok":False,"error":f"Can't regenerate login — username '{new_username}' is already taken"}),409
            cred_note = "Credentials were regenerated to match the updated name/phone. The parent must log in again with the new password — their child's historical reports and marks are unaffected."
        else:
            cred_note = "Name/phone updated, but no phone on file — could not regenerate a login."
    elif not parent_row and phone:
        gen_username, temp_pw = _gen_parent_creds(sid, name, phone, student_id)
        try:
            cur.execute("""INSERT INTO users(username,password,role,school_id,must_change_password,student_id)
                           VALUES(%s,%s,'parent',%s,1,%s)""",
                        (gen_username, hash_password(temp_pw), sid, student_id))
            new_username, new_password = gen_username, temp_pw
            cred_note = "Phone was missing before — a parent login was just created."
        except psycopg2.errors.UniqueViolation:
            con.rollback(); cur.close(); con.close()
            return jsonify({"ok":False,"error":f"Can't create login — username '{gen_username}' already taken"}),409

    flag_reason = "Missing parent phone — no parent login was created" if not phone else None

    cur.execute("""UPDATE students SET name=%s, class_id=%s, stream_id=%s, phone_number=%s, flag_reason=%s
                   WHERE id=%s AND school_id=%s""",
                (name, class_id, stream_id, phone or None, flag_reason, student_id, sid))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok":True,"new_username":new_username,"new_password":new_password,"note":cred_note})

@app.route("/api/students/<int:student_id>/reset_parent_credentials", methods=["POST"])
@require_auth
@require_role("admin")
def api_reset_parent_credentials(student_id):
    sid = g.school_id
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT name, phone_number FROM students WHERE id=%s AND school_id=%s",(student_id,sid))
    row = cur.fetchone()
    if not row:
        cur.close(); con.close(); return jsonify({"ok":False,"error":"Student not found"}),404
    name, phone = row
    if not phone:
        cur.close(); con.close(); return jsonify({"ok":False,"error":"No parent phone on file — add one first"}),400
    cur.execute("SELECT username FROM users WHERE school_id=%s AND student_id=%s AND role='parent'",(sid,student_id))
    parent_row = cur.fetchone()
    gen_username = name.lower().replace(" ","_")
    last4 = phone.strip()[-4:]
    cur.execute("""SELECT s.phone_number FROM users u JOIN students s ON u.student_id=s.id
                   WHERE u.username=%s AND u.school_id=%s AND u.role='parent' AND u.student_id!=%s""",
                (gen_username, sid, student_id))
    other_phones = [r[0] or "" for r in cur.fetchall()]
    needs_suffix = any(ph.strip()!=phone.strip() and ph.strip()[-4:]==last4 for ph in other_phones)
    new_password = f"{last4}-{student_id}" if needs_suffix else last4
    try:
        if parent_row:
            cur.execute("""UPDATE users SET username=%s, password=%s, must_change_password=1
                           WHERE school_id=%s AND student_id=%s AND role='parent', token_version=COALESCE(token_version,0)+1""",
                        (gen_username, hash_password(new_password), sid, student_id))
        else:
            cur.execute("""INSERT INTO users(username,password,role,school_id,must_change_password,student_id)
                           VALUES(%s,%s,'parent',%s,1,%s)""",
                        (gen_username, hash_password(new_password), sid, student_id))
        con.commit()
    except psycopg2.errors.UniqueViolation:
        con.rollback(); cur.close(); con.close()
        return jsonify({"ok":False,"error":f"Username '{gen_username}' is already taken by another parent"}),409
    cur.close(); con.close()
    return jsonify({"ok":True,"username":gen_username,"temp_password":new_password})    


# ── MARKS ─────────────────────────────────────────────────────
@app.route("/api/marks/ca", methods=["POST"])
@require_auth
@require_role("admin","teacher")
def api_enter_ca():
    sid = g.school_id; d = request.json
    username = g.username  # no longer trusts the body
    subject=d.get("subject","").lower().strip()
    class_id=int(d.get("class_id")); stream_id=d.get("stream_id") or None
    student_id=int(d.get("student_id")); ca_name=d.get("ca_name",""); score=float(d.get("score"))
    if not (0<=score<=100): return jsonify({"ok":False,"error":"Score must be 0-100"}),400
    if g.role=="teacher" and not teacher_can_access(sid,username,subject,class_id,stream_id):
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
@require_auth
@require_role("admin","teacher")
def api_enter_exam():
    sid = g.school_id; d = request.json
    username = g.username
    subject=d.get("subject","").lower().strip()
    class_id=int(d.get("class_id")); stream_id=d.get("stream_id") or None
    student_id=int(d.get("student_id")); score=float(d.get("score"))
    if not (0<=score<=100): return jsonify({"ok":False,"error":"Score must be 0-100"}),400
    if g.role=="teacher" and not teacher_can_access(sid,username,subject,class_id,stream_id):
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
@require_auth
def api_config():
    sid = g.school_id; term = get_active_term(sid)
    subjects = get_subjects(sid); subj_map = get_subject_map(sid)
    info = {k: get_config_val(sid,k,"") for k in ["school_name","phone","email","admin_phone","motto","logo_path"]}
    return jsonify({"allowed_subjects":subjects,"subject_abbr":subj_map,"active_term":term,
                    "ca_count":term["ca_count"] if term else 2,"school_name":info.get("school_name","School Name"),
                    "school_info":info,"grade_rules":get_grade_rules(sid)})

@app.route("/api/config/school_name", methods=["POST"])
@require_auth
@require_role("admin")
def api_set_school_name():
    sid = g.school_id; name = request.json.get("school_name","").strip()
    if not name: return jsonify({"ok":False,"error":"Name cannot be empty"}),400
    set_config_val(sid,"school_name",name); return jsonify({"ok":True})

@app.route("/api/config/reg_code", methods=["GET"])
@require_auth
@require_role("admin")
def api_get_reg_code():
    sid = g.school_id
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT reg_code FROM schools WHERE id=%s", (sid,))
    row = cur.fetchone(); cur.close(); con.close()
    return jsonify({"reg_code": row[0] if row else ""})

@app.route("/api/config/reg_code", methods=["POST"])
@require_auth
@require_role("admin")
def api_set_reg_code():
    sid = g.school_id
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
@require_auth
@require_role("admin")
def api_set_school_info():
    sid = g.school_id; d = request.json
    for key in ["school_name","phone","email","admin_phone","motto"]:
        val = d.get(key)
        if val is not None: set_config_val(sid, key, val.strip())
    return jsonify({"ok":True})

# ── REPORT CARD ───────────────────────────────────────────────
@app.route("/api/report/<int:student_id>", methods=["GET"])
@require_auth
@require_role("parent","admin","class_teacher")
def api_report(student_id):
    sid = g.school_id
    if g.role == "parent" and g.student_id != student_id:
        return jsonify({"ok":False,"error":"Access denied"}),403
    subjects = get_subjects(sid)
    term_id = request.args.get("term_id")
    con = get_db(); cur = con.cursor()
    cur.execute("""SELECT s.id,s.name,s.class_id,s.stream_id,c.class_name,st.stream_name,s.school_student_no
                   FROM students s JOIN classes c ON s.class_id=c.id
                   LEFT JOIN streams st ON s.stream_id=st.id
                   WHERE s.id=%s AND s.school_id=%s""",(student_id,sid))
    row = cur.fetchone(); student = to_dict(row,cur) if row else None
    cur.close(); con.close()
    if not student: return jsonify({"ok":False,"error":"Student not found"}),404
    student["display_id"] = format_student_display_id(sid, student.pop("school_student_no", None))
    term = get_term_by_id(sid,int(term_id)) if term_id else get_active_term(sid)
    if not term: return jsonify({"ok":False,"error":"No term available"}),400
    tid=term["id"]; ca_count=term["ca_count"]; ca_w=term["ca_weight"]; ex_w=term["exam_weight"]
    class_id=student["class_id"]; stream_id=student["stream_id"]

    class_rows, class_rank_map, stream_rank_map, scores_bulk = get_class_report_data(
        sid, tid, class_id, stream_id, subjects, ca_w, ex_w)
    active_subjects = _active_subjects_in_scores(subjects, scores_bulk)
    subject_rank_maps = {subj: get_subject_rank_map(class_rows, subj) for subj in active_subjects}

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
    finals_for_division = student_finals  # you already have this dict
    division_points, division = compute_division_from_finals(sid, finals_for_division)

    rows = []
    for subject in active_subjects:
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
                    "ca_count":ca_count,"ca_weight":term["ca_weight"],"exam_weight":term["exam_weight"],"division":division,"division_points":division_points})

# ── REMARKS ───────────────────────────────────────────────────
@app.route("/api/remarks", methods=["POST"])
@require_auth
def api_remarks():
    sid = g.school_id; d = request.json
    username = g.username; role = g.role; is_ct=d.get("is_class_teacher",False)
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
@require_auth
@require_role("admin","teacher")
def api_subject_ranking():
    sid=g.school_id; subject=request.args.get("subject","").lower()
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
@require_auth
@subscription_required
def api_analytics_overview():
    sid = g.school_id
    username  = g.username
    role      = g.role
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
@require_auth
@subscription_required
def api_analytics_subject():
    sid       = g.school_id
    username  = g.username
    role      = g.role
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
@require_auth
@subscription_required
@require_role("admin")
def api_analytics_dashboard_classes():
    sid = g.school_id
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
@require_auth
@require_role("admin","teacher")
def api_scoresheet():
    sid=g.school_id; subjects=get_subjects(sid)
    mode=request.args.get("mode","ca"); class_id=request.args.get("class_id")
    stream_id=request.args.get("stream_id") or None; ca_name=request.args.get("ca_name","CA1")
    term_id=request.args.get("term_id")
    sheet_type=request.args.get("sheet_type","marks")  # "marks" or "grade"
    grading_system=request.args.get("grading_system") or None
    division_source=request.args.get("division_source") or None
    noncredit_param=request.args.get("noncredit","")
    noncredit_override=[x.strip().lower() for x in noncredit_param.split(",") if x.strip()] if noncredit_param else None
    if not term_id:
        term=get_active_term(sid)
        if not term: return jsonify({"subjects":[],"results":[]})
        term_id=term["id"]
    else: term_id=int(term_id)
    if class_id:  class_id=int(class_id)
    if stream_id: stream_id=int(stream_id)

    studs=get_students_in_scope(sid,class_id,stream_id)
    if not studs:
        return jsonify({"subjects":subjects,"results":[],"sheet_type":sheet_type})
    student_ids=[s["id"] for s in studs]

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
    elif mode=="test":
        test_id = int(request.args.get("test_id"))
        cur.execute("""SELECT student_id,subject,score FROM test_scores
                    WHERE school_id=%s AND term_id=%s AND test_id=%s AND student_id=ANY(%s)""",
                    (sid,term_id,test_id,student_ids))
        for student_id,subject,score in cur.fetchall(): exam_scores[(student_id,subject)]=score

    elif mode=="terminal":
        term=get_term_by_id(sid,term_id)
        if not term:
            cur.close(); con.close()
            return jsonify({"subjects":subjects,"results":[],"sheet_type":sheet_type})
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

    def score_for(stid, subject):
        if mode=="ca": return ca_scores.get((stid,subject))
        if mode in ("exam","test"): return exam_scores.get((stid,subject))
        if mode=="terminal":
            exam=exam_scores.get((stid,subject)); ca_avg=ca_avgs.get((stid,subject))
            if exam is not None and ca_avg is not None:
                return round((ca_avg/100)*term["ca_weight"] + (exam/100)*term["exam_weight"],1)
        return None

    # Drop subject columns nobody in this class/stream has a mark for, for
    # this specific assessment — makes the sheet reflect what the class
    # actually takes instead of a wall of "-" for unrelated subjects.
    active_subjects = [subj for subj in subjects if any(score_for(s["id"], subj) is not None for s in studs)]

    if sheet_type=="grade":
        settings = get_school_grading_settings(sid)
        level = grading_system or settings["grading_system"]
        div_source = division_source or settings["division_source"]
        rules = get_necta_grades(level) if div_source=="necta" else get_grade_rules(sid)
        results=[]
        for s in studs:
            subj_scores={}; grades={}
            for subject in active_subjects:
                score = score_for(s["id"], subject)
                subj_scores[subject]=score
                grades[subject],_ = grade_and_points_for_score(rules, score)
            points, division = compute_division_from_finals(sid, subj_scores, grading_system, division_source, noncredit_override)
            results.append({"id":s["id"],"name":s["name"],"stream_name":s.get("stream_name"),
                            "grades":grades,"points":points,"division":division or "-"})
        return jsonify({"subjects":active_subjects,"results":results,"sheet_type":"grade"})

    grade_rules=get_grade_rules(sid)
    def grade_for(score):
        if score is None: return "-"
        for r in grade_rules:
            if score>=r["min_score"]: return r["grade"]
        return "F"

    results=[]
    for s in studs:
        row={"id":s["id"],"name":s["name"],"stream_name":s.get("stream_name"),"scores":{},"total":0,"count":0}
        for subject in active_subjects:
            score=score_for(s["id"], subject)
            row["scores"][subject]=score
            if score is not None: row["total"]+=score; row["count"]+=1
        row["average"]=round(row["total"]/row["count"],2) if row["count"] else 0
        row["grade"]=grade_for(row["average"]); results.append(row)
    _assign_positions(results,"average")
    return jsonify({"subjects":active_subjects,"results":results,"sheet_type":"marks"})


# ── ANNOUNCEMENTS ─────────────────────────────────────────────
@app.route("/api/announcements", methods=["GET"])
@require_auth
def api_get_announcements():
    sid=g.school_id; student_id=request.args.get("student_id")
    con=get_db(); cur=con.cursor()
    if student_id:
        stid=int(student_id)
        if g.role == "parent" and g.student_id != stid:
            cur.close(); con.close()
            return jsonify({"ok":False,"error":"Access denied"}),403
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
@require_auth
@subscription_required
@require_role("admin")
def api_post_announcement():
    sid=g.school_id; d=request.json
    title=d.get("title","").strip(); body=d.get("body","").strip()
    posted_by=d.get("posted_by",""); target_classes=(d.get("target_classes") or "all").strip() or "all"
    if not title or not body: return jsonify({"ok":False,"error":"Title and body required"}),400
    con=get_db(); cur=con.cursor()
    cur.execute("INSERT INTO announcements(school_id,title,body,target_classes,posted_by) VALUES(%s,%s,%s,%s,%s) RETURNING id",
                (sid,title,body,target_classes,posted_by))
    new_id=cur.fetchone()[0]; con.commit(); cur.close(); con.close()
    return jsonify({"ok":True,"id":new_id})

@app.route("/api/announcements/<int:aid>", methods=["DELETE"])
@require_auth
@require_role("admin")
def api_delete_announcement(aid):
    sid=g.school_id
    con=get_db(); cur=con.cursor()
    cur.execute("DELETE FROM announcements WHERE id=%s AND school_id=%s",(aid,sid))
    con.commit(); cur.close(); con.close(); return jsonify({"ok":True})

@app.route("/api/announcements/<int:aid>/read", methods=["POST"])
@require_auth
def api_mark_announcement_read(aid):
    student_id=request.json.get("student_id")
    if not student_id: return jsonify({"ok":False,"error":"student_id required"}),400
    if g.role == "parent" and g.student_id != int(student_id):
        return jsonify({"ok":False,"error":"Access denied"}),403
    con=get_db(); cur=con.cursor()
    cur.execute("INSERT INTO announcement_reads(announcement_id,student_id) VALUES(%s,%s) ON CONFLICT DO NOTHING",(aid,int(student_id)))
    con.commit(); cur.close(); con.close(); return jsonify({"ok":True})

# ── RESULTS PUBLISHING ────────────────────────────────────────
@app.route("/api/results/status", methods=["GET"])
@require_auth
def api_results_status():
    sid=g.school_id; term_id=request.args.get("term_id")
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
@require_auth
@require_role("admin")
def api_toggle_results():
    sid=g.school_id; d=request.json
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

@app.route("/api/results/assessments", methods=["GET"])
@require_auth
def api_list_assessments_for_publish():
    sid = g.school_id; term_id = request.args.get("term_id")
    if not term_id:
        term = get_active_term(sid)
        if not term: return jsonify({"ok":True,"assessments":[]})
        term_id = term["id"]
    else: term_id = int(term_id)
    term = get_term_by_id(sid, term_id)
    if not term: return jsonify({"ok":False,"error":"Term not found"}),404
    tests = get_term_tests(sid, term_id)
    test_map = {t["id"]: t["label"] for t in tests}
    keys = [f"CA{i}" for i in range(1, term["ca_count"]+1)] + ["exam"] + [f"test:{t['id']}" for t in tests]
    con=get_db(); cur=con.cursor()
    cur.execute("SELECT assess_key, published FROM published_assessments WHERE school_id=%s AND term_id=%s",(sid,term_id))
    pub_map = dict(cur.fetchall()); cur.close(); con.close()
    result=[]
    for k in keys:
        label = "Final Exam" if k=="exam" else (test_map.get(int(k.split(":")[1])) if k.startswith("test:") else k)
        result.append({"assess_key":k, "label":label, "published": bool(pub_map.get(k,0))})
    return jsonify({"ok":True,"term_id":term_id,"assessments":result})

@app.route("/api/results/publish_assessments", methods=["POST"])
@require_auth
@require_role("admin")
def api_publish_assessments():
    sid = g.school_id; d = request.json or {}
    term_id = d.get("term_id"); keys = d.get("assess_keys") or []; publish = bool(d.get("publish", True))
    if publish and not is_subscribed(sid):
        return jsonify({"ok":False,"error":"subscription_required","message":"Publishing results requires an active subscription."}),402
    if not term_id or not keys: return jsonify({"ok":False,"error":"term_id and assess_keys required"}),400
    con=get_db(); cur=con.cursor()
    for k in keys:
        cur.execute("""INSERT INTO published_assessments(school_id,term_id,assess_key,published) VALUES(%s,%s,%s,%s)
                       ON CONFLICT(school_id,term_id,assess_key) DO UPDATE SET published=EXCLUDED.published""",
                    (sid,int(term_id),k,1 if publish else 0))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok":True})

# ── PARENT PORTAL ─────────────────────────────────────────────
@app.route("/api/parent/terms", methods=["GET"])
@require_auth
def api_parent_terms():
    sid=g.school_id
    con=get_db(); cur=con.cursor()
    # A term shows up here if EITHER the legacy whole-term publish switch is
    # on, OR at least one individual assessment has been published via the
    # newer per-assessment publisher — previously only the legacy flag was
    # checked, so terms published assessment-by-assessment (the normal flow)
    # never appeared for parents.
    cur.execute("""SELECT DISTINCT t.id,t.label,t.ca_count,t.ca_weight,t.exam_weight,t.status
                   FROM terms t
                   WHERE t.school_id=%s AND (
                       EXISTS (SELECT 1 FROM results_published rp WHERE rp.school_id=t.school_id AND rp.term_id=t.id AND rp.published=1)
                       OR EXISTS (SELECT 1 FROM published_assessments pa WHERE pa.school_id=t.school_id AND pa.term_id=t.id AND pa.published=1)
                   )
                   ORDER BY t.id ASC""",(sid,))
    rows=to_dicts(cur.fetchall(),cur); cur.close(); con.close(); return jsonify(rows)

@app.route("/api/parent/results", methods=["GET"])
@require_auth
@require_role("parent")
def api_parent_results():
    sid=g.school_id; subjects=get_subjects(sid)
    student_id=request.args.get("student_id"); term_id=request.args.get("term_id"); assess=request.args.get("assess")
    if not student_id: return jsonify({"ok":False,"error":"student_id required"}),400
    if int(student_id) !=g.student_id:
        return jsonify({"ok":False,"error":"Access denied"}),403 
    if assess:
        con=get_db(); cur=con.cursor()
        cur.execute("SELECT published FROM published_assessments WHERE school_id=%s AND term_id=%s AND assess_key=%s",(sid,term_id,assess))
        prow=cur.fetchone(); cur.close(); con.close()
        if not prow or not prow[0]:
            return jsonify({"ok":False,"error":"This assessment hasn't been published yet"}),403
    else:
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
        active_subjects = [subj for subj in subjects
                            if any(_score_for_assess(scores_bulk.get(cid, {}).get(subj), assess) is not None for cid in class_ids)]
        assess_rank_maps={}
        for subject in active_subjects:
            entry=student_scores.get(subject,{})
            ca_map=entry.get("ca",{})
            ca_scores={f"CA{i}": ca_map.get(f"CA{i}") for i in range(1,ca_count+1)}
            exam_val=entry.get("exam")
            score=_score_for_assess(entry, assess)
            if score is None: continue
            if subject not in assess_rank_maps:
                assess_rank_maps[subject]=get_subject_assess_rank_map(scores_bulk,class_ids,subject,assess)
            pos=assess_rank_maps[subject].get(stid,"-")
            results.append({"subject":subject,"ca":ca_scores,"exam":exam_val,"score":score,
                            "grade":get_grade(sid,score),"position":pos})
    else:
        active_subjects = _active_subjects_in_scores(subjects, scores_bulk)
        subject_rank_maps={subj: get_subject_rank_map(class_rows, subj) for subj in active_subjects}
        student_finals = class_rank_map.get(stid,{}).get("finals") or compute_student_finals(scores_bulk,stid,subjects,ca_w,ex_w)
        for subject in active_subjects:
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
                v = _score_for_assess(entry, assess)
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

    if assess:
        subj_scores_div = {r["subject"]: r["score"] for r in results if r.get("score") is not None}
    else:
        subj_scores_div = student_finals
    division_points, division = compute_division_from_finals(sid, subj_scores_div)

    return jsonify({"ok":True,"student":student,"term":term,"results":results,"ca_count":ca_count,
                    "average":avg,"grade":get_grade(sid,avg),
                    "class_position":c_pos,"class_total":c_total,
                    "stream_position":s_pos,"stream_total":s_total,"assess":assess,
                    "division":division,"division_points":division_points})

# ── PLATFORM ANNOUNCEMENTS (school-side) ──────────────────────
@app.route("/api/platform_announcements", methods=["GET"])
@require_auth
def api_platform_announcements():
    sid=g.school_id
    con=get_db(); cur=con.cursor()
    cur.execute("""SELECT pa.id,pa.title,pa.body,CAST(pa.posted_at AS TEXT) as posted_at,
                          CASE WHEN par.school_id IS NOT NULL THEN 1 ELSE 0 END AS is_read
                   FROM platform_announcements pa
                   LEFT JOIN platform_announcement_reads par ON par.announcement_id=pa.id AND par.school_id=%s
                   WHERE pa.target='all' OR pa.target=%s
                   ORDER BY pa.posted_at DESC""",(sid,str(sid)))
    rows=to_dicts(cur.fetchall(),cur); cur.close(); con.close(); return jsonify(rows)

@app.route("/api/platform_announcements/<int:aid>/read", methods=["POST"])
@require_auth
def api_platform_announcement_read(aid):
    sid=g.school_id
    con=get_db(); cur=con.cursor()
    cur.execute("INSERT INTO platform_announcement_reads(announcement_id,school_id) VALUES(%s,%s) ON CONFLICT DO NOTHING",(aid,sid))
    con.commit(); cur.close(); con.close(); return jsonify({"ok":True})

@app.route("/api/subscription/status", methods=["GET"])
@require_auth
@require_role("admin")
def api_subscription_status():
    sid = g.school_id
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
@require_auth
@require_role("admin")
def api_select_free_plan():
    sid = g.school_id
    con = get_db(); cur = con.cursor()
    cur.execute("""UPDATE schools SET subscription_status='active', subscription_plan='free',
                   subscription_expires_at=%s WHERE id=%s""",
                (datetime.utcnow() + timedelta(days=SUBSCRIPTION_PLANS["free"]["days"]), sid))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok": True})

@app.route("/api/subscription/request", methods=["POST"])
@require_auth
@require_role("admin")
def api_submit_payment_request():
    sid = g.school_id
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
@require_auth
@require_role("admin")
def api_cancel_payment_request():
    sid = g.school_id
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
from services.pdf import _esc, _school_header_story, _blue_sheet_pdf


@app.route("/api/pdf/report/<int:sid>", methods=["GET"])
@require_auth
@subscription_required
@require_role("admin","teacher","parent")
def pdf_report(sid):
    school_id=g.school_id
    if g.role == "parent" and g.student_id != sid:
        return  jsonify({"error":"Access denied"}),403
    subjects=get_subjects(school_id); subj_map=get_subject_map(school_id)
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
    active_subjects = _active_subjects_in_scores(subjects, scores_bulk)
    subject_rank_maps = {subj: get_subject_rank_map(class_rows, subj) for subj in active_subjects}
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
    for subject in active_subjects:
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
@require_auth
@subscription_required
@require_role("admin","teacher")
def pdf_ca_sheet():
    school_id=g.school_id; subjects=get_subjects(school_id)
    class_id=request.args.get("class_id"); stream_id=request.args.get("stream_id") or None
    ca_name=request.args.get("ca_name","CA1"); term_id=request.args.get("term_id")
    term=get_term_by_id(school_id,int(term_id)) if term_id else get_active_term(school_id)
    if not term: return jsonify({"error":"No term"}),400
    tid=term["id"]; class_id=int(class_id) if class_id else None
    if stream_id: stream_id=int(stream_id)
    studs=get_students_in_scope(school_id,class_id,stream_id)
    if not studs: return jsonify({"error":"No students"}),404
    fname=os.path.join(tempfile.gettempdir(),f"CA_{school_id}_{class_id}_{ca_name.replace(':','_')}_{tid}.pdf")
    scores_bulk=get_term_scores_bulk(school_id,tid,[s["id"] for s in studs])
    def get_score(stid,subj):
        entry=scores_bulk.get(stid,{}).get(subj)
        if not entry: return None
        if ca_name=="exam": return entry["exam"]
        if ca_name.startswith("test:"):
            tid_=int(ca_name.split(":",1)[1])
            return (entry.get("tests") or {}).get(tid_)
        return entry["ca"].get(ca_name)
    active_subjects = [subj for subj in subjects if any(get_score(s["id"], subj) is not None for s in studs)]
    subtitle_label = ca_name.upper()
    if ca_name.startswith("test:"):
        con=get_db(); cur=con.cursor()
        cur.execute("SELECT label FROM term_tests WHERE id=%s AND school_id=%s",(int(ca_name.split(":",1)[1]),school_id))
        r=cur.fetchone(); cur.close(); con.close()
        subtitle_label = (r[0].upper() if r else "TEST")
    class_label = studs[0]["class_name"] + (f" {studs[0]['stream_name']}" if stream_id and studs[0].get("stream_name") else "")
    _blue_sheet_pdf(school_id,fname,f"{subtitle_label} SCORE SHEET",studs,active_subjects,get_score,term,class_label=class_label)
    return send_file(fname,as_attachment=True,download_name=os.path.basename(fname),mimetype="application/pdf")

@app.route("/api/pdf/grade_sheet", methods=["GET"])
@require_auth
@subscription_required
@require_role("admin","teacher")
def pdf_grade_sheet():
    school_id=g.school_id; subjects=get_subjects(school_id)
    mode=request.args.get("mode","ca")
    class_id=request.args.get("class_id"); stream_id=request.args.get("stream_id") or None
    ca_name=request.args.get("ca_name","CA1"); term_id=request.args.get("term_id")
    grading_system=request.args.get("grading_system") or None
    division_source=request.args.get("division_source") or None
    noncredit_param=request.args.get("noncredit","")
    noncredit_override=[x.strip().lower() for x in noncredit_param.split(",") if x.strip()] if noncredit_param else None

    term=get_term_by_id(school_id,int(term_id)) if term_id else get_active_term(school_id)
    if not term: return jsonify({"error":"No term"}),400
    tid=term["id"]; class_id=int(class_id) if class_id else None
    if stream_id: stream_id=int(stream_id)
    studs=get_students_in_scope(school_id,class_id,stream_id)
    if not studs: return jsonify({"error":"No students"}),404

    scores_bulk=get_term_scores_bulk(school_id,tid,[s["id"] for s in studs])
    ca_w=term["ca_weight"]; ex_w=term["exam_weight"]
    def get_score(stid,subj):
        entry=scores_bulk.get(stid,{}).get(subj)
        if not entry: return None
        if mode=="ca":
            if ca_name.startswith("test:"):
                tid_=int(ca_name.split(":",1)[1])
                return (entry.get("tests") or {}).get(tid_)
            return entry["ca"].get(ca_name)
        if mode=="exam": return entry["exam"]
        if mode=="terminal": return _final_from_entry(entry,ca_w,ex_w)
        return None

    active_subjects = [subj for subj in subjects if any(get_score(s["id"], subj) is not None for s in studs)]

    settings = get_school_grading_settings(school_id)
    level = grading_system or settings["grading_system"]
    div_source = division_source or settings["division_source"]
    rules = get_necta_grades(level) if div_source=="necta" else get_grade_rules(school_id)

    fname=os.path.join(tempfile.gettempdir(),f"Grade_{school_id}_{class_id}_{mode}_{ca_name.replace(':','_')}_{tid}.pdf")
    class_label = studs[0]["class_name"] + (f" {studs[0]['stream_name']}" if stream_id and studs[0].get("stream_name") else "")
    if mode=="ca" and ca_name.startswith("test:"):
        con=get_db(); cur=con.cursor()
        cur.execute("SELECT label FROM term_tests WHERE id=%s AND school_id=%s",(int(ca_name.split(":",1)[1]),school_id))
        r=cur.fetchone(); cur.close(); con.close()
        title = f"{(r[0].upper() if r else 'TEST')} GRADE SHEET"
    else:
        title = {"ca": f"{ca_name.upper()} GRADE SHEET", "exam":"EXAM GRADE SHEET", "terminal":"TERMINAL GRADE SHEET"}.get(mode,"GRADE SHEET")

    subj_map=get_subject_map(school_id)
    H_BG=colors.HexColor("#1A6FA8"); ODD=colors.HexColor("#E8F4FC"); WHITE=colors.white
    page_size = landscape(A3) if len(active_subjects) > 10 else landscape(A4)
    doc=SimpleDocTemplate(fname,pagesize=page_size,rightMargin=1.2*cm,leftMargin=1.2*cm,topMargin=1.2*cm,bottomMargin=1.2*cm)
    styles=getSampleStyleSheet(); story=[]
    story+=_school_header_story(school_id,styles,f"{title} — {class_label}" if class_label else title, term["label"])

    name_style = ParagraphStyle("NameCell", parent=styles["Normal"], fontSize=7.5, leading=8.5)
    hdr=["#","Student"]+[subj_map.get(s,s[:4].upper()) for s in active_subjects]+["Points","Division"]
    tdata=[hdr]
    for ri,s in enumerate(studs,1):
        subj_scores={}
        row=[str(ri),Paragraph(_esc(s["name"]),name_style)]
        for subj in active_subjects:
            sc=get_score(s["id"],subj)
            subj_scores[subj]=sc
            grade,_ = grade_and_points_for_score(rules, sc)
            row.append(grade)
        points, division = compute_division_from_finals(school_id, subj_scores, grading_system, division_source, noncredit_override)
        row += [str(points) if points is not None else "-", division or "-"]
        tdata.append(row)

    sc_w=1.2*cm
    cw=[0.8*cm,6.2*cm]+[sc_w]*len(active_subjects)+[1.5*cm,1.5*cm]
    tbl=Table(tdata,colWidths=cw,repeatRows=1)
    ts=[("BACKGROUND",(0,0),(-1,0),H_BG),("TEXTCOLOR",(0,0),(-1,0),WHITE),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),7),
        ("ALIGN",(0,0),(-1,-1),"CENTER"),("ALIGN",(1,1),(1,-1),"LEFT"),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[ODD,WHITE]),("GRID",(0,0),(-1,-1),0.4,colors.HexColor("#A0C4E0")),
        ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3)]
    tbl.setStyle(TableStyle(ts)); story.append(tbl)
    story.append(Spacer(1,0.3*cm))
    ft=ParagraphStyle("F",parent=styles["Normal"],fontSize=6.5,textColor=colors.grey,alignment=2)
    story.append(Paragraph(f"Generated | {len(studs)} students | {term['label']}",ft))
    doc.build(story)
    return send_file(fname,as_attachment=True,download_name=os.path.basename(fname),mimetype="application/pdf")

@app.route("/api/pdf/terminal_sheet", methods=["GET"])
@require_auth
@subscription_required
@require_role("admin","teacher")
def pdf_terminal_sheet():
    school_id=g.school_id; subjects=get_subjects(school_id)
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
    active_subjects = [subj for subj in subjects if any(get_score(s["id"], subj) is not None for s in studs)]
    class_label = studs[0]["class_name"] + (f" {studs[0]['stream_name']}" if stream_id and studs[0].get("stream_name") else "")
    _blue_sheet_pdf(school_id,fname,f"TERMINAL SCORE SHEET (CA {term['ca_weight']}% + Exam {term['exam_weight']}%)",studs,active_subjects,get_score,term)
    return send_file(fname,as_attachment=True,download_name=os.path.basename(fname),mimetype="application/pdf")


# ══════════════════════════════════════════════════════════════
# SUPERADMIN ROUTES
# ══════════════════════════════════════════════════════════════
_SA_SESSIONS = {}

@app.route("/api/superadmin/login", methods=["POST"])
def api_superadmin_login():
    d=request.json; u=d.get("username","").strip(); p=d.get("password","")
    if not u or not p: return jsonify({"ok":False,"error":"Username and password required"}),400
    con=get_db(); cur=con.cursor()
    cur.execute("SELECT password FROM superadmins WHERE username=%s",(u,))
    row=cur.fetchone(); cur.close(); con.close()
    if not row or not verify_password(p,row[0]): return jsonify({"ok":False,"error":"Invalid credentials"}),401
    token=_sa_serializer.dumps({"username":u})
    return jsonify({"ok":True,"token":token,"username":u})

@app.route("/api/superadmin/logout", methods=["POST"])
def api_superadmin_logout():
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
    except Exception as e:
        app.loger.error("Superadmin schools listing failed: %s", e)
        return jsonify({"ok":False,"error":"Could not load schools list."}),500

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
_STATIC_FILES=["shared.css","DRDEMIC-LOGO.png"]

@app.route("/api/config/logo", methods=["POST"])
@require_auth
@require_role("admin")
def api_upload_logo():
    school_id = g.school_id
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


@app.route("/api/students/import/template", methods=["GET"])
@require_auth
@require_role("admin")
def api_import_template():
    """Download a pre-filled Excel template."""
    school_id = g.school_id
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
@require_auth
@require_role("admin")
def api_import_preview():
    school_id = g.school_id
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
    unmatched_classes = {}
    unmatched_streams = {}
    preview = []
    for i, row in enumerate(rows):
        name, class_name, stream_name, parent_phone = _extract_fields(row)
        cid = sid = err = None
        if class_name:
            cid, sid, err = _resolve_class_stream(class_name, stream_name, cmap)
            if cid is None:
                unmatched_classes[class_name.strip().lower()] = class_name.strip()
            elif stream_name and sid is None and err:
                unmatched_streams[f"{class_name.strip()}::{stream_name.strip()}".lower()] = \
                    {"class_raw": class_name.strip(), "stream_raw": stream_name.strip()}
        if i < 10:
            issues = []
            if not name: issues.append("Missing name")
            if not class_name: issues.append("Missing class")
            elif cid is None: issues.append(f"Class '{class_name}' needs matching")
            elif stream_name and sid is None: issues.append(f"Stream '{stream_name}' needs matching")
            if not parent_phone: issues.append("Missing phone — will still import, no parent login created")
            preview.append({"row":i+2,"name":name,"class_name":class_name,"stream_name":stream_name,
                            "parent_phone":parent_phone,"issues":issues})

    return jsonify({"ok":True,"total_rows":len(rows),"preview":preview,
                    "columns_detected":list(rows[0].keys()) if rows else [],
                    "unmatched_classes": list(unmatched_classes.values()),
                    "unmatched_streams": list(unmatched_streams.values())})


@app.route("/api/students/import/credentials/<token>")
@require_auth
@require_role("admin")
def download_import_credentials(token):
    sid = g.school_id
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT data FROM import_credential_batches WHERE token=%s AND school_id=%s",(token, sid))
    row = cur.fetchone(); cur.close(); con.close()
    if not row:
        return jsonify({"ok": False, "error": "File not found or expired"}), 404
    credentials = row[0]
    fname = os.path.join(tempfile.gettempdir(), f"creds_{token}.xlsx")
    _write_credentials_xlsx(credentials, fname)
    return send_file(fname, as_attachment=True,
                      download_name="parent_login_credentials.xlsx",
                      mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.route("/api/students/import", methods=["POST"])
@require_auth
@require_role("admin")
def api_import_students():
    """Full import: parse, validate, bulk insert."""
    school_id = g.school_id
    if "file" not in request.files:
        return jsonify({"ok":False,"error":"No file uploaded"}), 400
    f = request.files["file"]
    import traceback
    try:
        rows = _parse_import_file(f.stream, f.filename)
    except ValueError as e:
        return jsonify({"ok":False,"error":str(e)}),400
    except Exception as e:
        app.logger.error("Student import parse failed: %s", traceback.format_exc())
        return jsonify({"ok":False,"error":"Could not parse the uploaded file. Please check the format and try again."}), 500

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
    cur.execute("SELECT COALESCE(MAX(school_student_no),0) FROM students WHERE school_id=%s", (school_id,))
    next_student_no = cur.fetchone()[0] + 1

    # Track which phone numbers already use each parent username, so we only
    # append "-{student_id}" when two DIFFERENT phone numbers sharing a
    # username would otherwise collide on the same last-4 password.
    cur.execute("""SELECT u.username, s.phone_number FROM users u JOIN students s ON u.student_id=s.id
                   WHERE u.school_id=%s AND u.role='parent'""", (school_id,))
    username_phone_map = {}
    for uname, ph in cur.fetchall():
        username_phone_map.setdefault(uname, []).append(ph or "")

    mapping_raw = request.form.get("mapping", "{}")
    try:
        mapping = json.loads(mapping_raw) if mapping_raw else {}
    except Exception:
        mapping = {}
    mapping.setdefault("classes", {}); mapping.setdefault("streams", {})
    flagged = []  # imported OK but missing a non-essential field — shown as a red dot in the UI

    for i, row in enumerate(rows):
        row_num = i + 2
        name, class_name, stream_name, parent_phone = _extract_fields(row)
        if not name:
            skipped.append({"row":row_num,"reason":"Missing name — can't import a student with no name","data":str(list(row.values())[:4])})
            continue
        if not class_name:
            skipped.append({"row":row_num,"reason":"Missing class","data":name})
            continue
        class_id, stream_id, resolve_err = _resolve_class_stream(class_name, stream_name, cmap, mapping)
        if resolve_err:
            skipped.append({"row":row_num,"reason":resolve_err,"data":name})
            continue
        phone_clean = (parent_phone or "").strip()
        dup_key = (name.strip().lower(), class_id, stream_id or 0, phone_clean)
        if dup_key in existing_students:
            skipped.append({"row":row_num,"reason":"Duplicate — same name, class, stream & phone already exist","data":name})
            duplicates += 1
            continue
        try:
            cur.execute("SAVEPOINT sp_student")
            cur.execute("""INSERT INTO students(school_id,name,class_id,stream_id,phone_number,school_student_no)
                           VALUES(%s,%s,%s,%s,%s,%s) RETURNING id""",
                        (school_id, name, class_id, stream_id, phone_clean or None, next_student_no))
            student_id = cur.fetchone()[0]
            next_student_no += 1
            if not phone_clean:
                reason = "Missing parent phone — no parent login was created"
                flagged.append({"row":row_num,"name":name,"reason":reason})
                cur.execute("UPDATE students SET flag_reason=%s WHERE id=%s",(reason,student_id))
                cur.execute("RELEASE SAVEPOINT sp_student")
                inserted += 1; existing_students.add(dup_key)
                if inserted % 200 == 0: con.commit()
                continue
            username_base = name.strip().lower().replace(" ","_")
            last4 = phone_clean[-4:]
            existing_phones_for_username = username_phone_map.get(username_base, [])
            needs_suffix = any(ph.strip() != phone_clean and ph.strip()[-4:] == last4 for ph in existing_phones_for_username)
            temp_pw = f"{last4}-{student_id}" if needs_suffix else last4
            cur.execute("INSERT INTO users(username,password,role,school_id,must_change_password,student_id) VALUES(%s,%s,'parent',%s,1,%s) ON CONFLICT(username,school_id) DO NOTHING",
                        (username_base,hash_password_fast(temp_pw),school_id,student_id))
            login_created = cur.rowcount > 0
            username_phone_map.setdefault(username_base, []).append(phone_clean)
            cur.execute("RELEASE SAVEPOINT sp_student")
            inserted += 1; existing_students.add(dup_key)
            if login_created:
                credentials.append({"row":row_num,"name":name,"class_name":class_name,"stream_name":stream_name,
                                    "parent_phone":phone_clean,"username":username_base,"password":temp_pw})
            else:
                reason = f"Login username '{username_base}' already taken by another student with the same name"
                flagged.append({"row":row_num,"name":name,"reason":reason})
                cur.execute("UPDATE students SET flag_reason=%s WHERE id=%s",(reason,student_id))
            if inserted % 200 == 0: con.commit()
        except Exception as e:
            cur.execute("ROLLBACK TO SAVEPOINT sp_student")
            errors.append({"row":row_num,"error":str(e),"data":name})
    con.commit(); cur.close(); con.close()

    credentials_file = None
    if credentials:
        token = secrets.token_hex(16)
        con2 = get_db(); cur2 = con2.cursor()
        cur2.execute("INSERT INTO import_credential_batches(school_id,token,data) VALUES(%s,%s,%s)",
                     (school_id, token, json.dumps(credentials)))
        con2.commit(); cur2.close(); con2.close()
        credentials_file = f"/api/students/import/credentials/{token}"

    return jsonify({"ok":True,"inserted":inserted,"skipped":len(skipped),"errors":len(errors),"duplicates":duplicates,
                    "skipped_details":skipped[:20],"error_details":errors[:20],
                    "flagged_details":flagged[:50],
                    "credentials_file":credentials_file,"credentials_count":len(credentials)})


with app.app_context():
    init_db()

if __name__=="__main__":
    app.run(debug=False,host="0.0.0.0",port=int(os.environ.get("PORT",5000)))
