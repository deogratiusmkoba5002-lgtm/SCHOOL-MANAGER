import os
from core.db import get_db
from core.security import hash_password

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
        CREATE TABLE IF NOT EXISTS student_access (
        school_id  INTEGER NOT NULL,
        student_id INTEGER NOT NULL,
        plan       TEXT NOT NULL DEFAULT '',
        expires_at TIMESTAMP NOT NULL,
        updated_at TIMESTAMP DEFAULT NOW(),
        PRIMARY KEY(school_id, student_id)
    );
    CREATE TABLE IF NOT EXISTS student_payments (
        id              SERIAL PRIMARY KEY,
        school_id       INTEGER NOT NULL,
        student_id      INTEGER NOT NULL,
        plan            TEXT NOT NULL,
        duration_days   INTEGER NOT NULL,
        amount          INTEGER NOT NULL,
        currency        TEXT NOT NULL DEFAULT 'TZS',
        reference       TEXT UNIQUE,
        idempotency_key TEXT,
        phone           TEXT,
        status          TEXT NOT NULL DEFAULT 'pending',
        method          TEXT,
        initiated_by    TEXT,
        initiated_role  TEXT,
        failure_reason  TEXT,
        applied         INTEGER NOT NULL DEFAULT 0,
        created_at      TIMESTAMP DEFAULT NOW(),
        paid_at         TIMESTAMP,
        expires_at      TIMESTAMP
    );
    """)

     # ── STAR SYSTEM ──────────────────────────────────────────
    cur.execute("""
    CREATE TABLE IF NOT EXISTS star_referral_tokens (
        id         SERIAL PRIMARY KEY,
        school_id  INTEGER NOT NULL UNIQUE,
        token      TEXT NOT NULL UNIQUE,
        revoked    INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMP DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS star_referral_relationships (
        id                   SERIAL PRIMARY KEY,
        referring_school_id  INTEGER NOT NULL,
        referred_school_id   INTEGER NOT NULL UNIQUE,
        created_at           TIMESTAMP DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS star_cycles (
        id                       SERIAL PRIMARY KEY,
        school_id                INTEGER NOT NULL,
        cycle_number             INTEGER NOT NULL,
        status                   TEXT NOT NULL DEFAULT 'IN_PROGRESS',
        qualifying_parent_count  INTEGER NOT NULL DEFAULT 0,
        started_at               TIMESTAMP DEFAULT NOW(),
        completed_at             TIMESTAMP,
        created_at               TIMESTAMP DEFAULT NOW(),
        updated_at               TIMESTAMP DEFAULT NOW(),
        UNIQUE(school_id, cycle_number),
        CHECK (status IN ('IN_PROGRESS','PENDING_VERIFICATION','COMPLETED','REJECTED'))
    );
    CREATE TABLE IF NOT EXISTS star_qualifying_parents (
        id                SERIAL PRIMARY KEY,
        cycle_id          INTEGER NOT NULL REFERENCES star_cycles(id),
        school_id         INTEGER NOT NULL,
        student_id        INTEGER NOT NULL,
        payment_reference TEXT NOT NULL,
        qualified_at      TIMESTAMP DEFAULT NOW(),
        UNIQUE(cycle_id, student_id)
    );
    CREATE TABLE IF NOT EXISTS star_transactions (
        id             SERIAL PRIMARY KEY,
        school_id      INTEGER NOT NULL,
        type           TEXT NOT NULL,
        stars          INTEGER NOT NULL,
        amount         INTEGER NOT NULL,
        reference_type TEXT,
        reference_id   INTEGER,
        description    TEXT DEFAULT '',
        status         TEXT NOT NULL DEFAULT 'PENDING',
        created_at     TIMESTAMP DEFAULT NOW(),
        CHECK (type IN ('CYCLE_REWARD','REFERRAL_REWARD','WITHDRAWAL','REVERSAL','ADJUSTMENT')),
        CHECK (status IN ('PENDING','AVAILABLE','WITHDRAWAL_REQUESTED','PROCESSING','WITHDRAWN','FAILED','ON_HOLD','REVERSED'))
    );
    CREATE TABLE IF NOT EXISTS star_payout_accounts (
        id                 SERIAL PRIMARY KEY,
        school_id          INTEGER NOT NULL,
        provider           TEXT NOT NULL DEFAULT 'snippe',
        account_identifier TEXT NOT NULL,
        verified           INTEGER NOT NULL DEFAULT 0,
        created_at         TIMESTAMP DEFAULT NOW(),
        updated_at         TIMESTAMP DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS star_withdrawals (
        id                SERIAL PRIMARY KEY,
        school_id         INTEGER NOT NULL,
        stars             INTEGER NOT NULL,
        amount            INTEGER NOT NULL,
        status            TEXT NOT NULL DEFAULT 'REQUESTED',
        payout_account_id INTEGER REFERENCES star_payout_accounts(id),
        idempotency_key   TEXT NOT NULL UNIQUE,
        requested_at      TIMESTAMP DEFAULT NOW(),
        decided_at        TIMESTAMP,
        decided_by        TEXT,
        note              TEXT DEFAULT '',
        CHECK (status IN ('REQUESTED','PROCESSING','WITHDRAWN','FAILED','REJECTED'))
    );
    CREATE TABLE IF NOT EXISTS star_audit_logs (
        id              SERIAL PRIMARY KEY,
        school_id       INTEGER,
        actor_username  TEXT,
        event           TEXT NOT NULL,
        reference_id    INTEGER,
        old_state       TEXT,
        new_state       TEXT,
        ip_address      TEXT,
        user_agent      TEXT,
        created_at      TIMESTAMP DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_star_cycles_school ON star_cycles(school_id);
    CREATE INDEX IF NOT EXISTS idx_star_transactions_school ON star_transactions(school_id);
    CREATE INDEX IF NOT EXISTS idx_star_withdrawals_school ON star_withdrawals(school_id);
    CREATE INDEX IF NOT EXISTS idx_star_qualifying_parents_school ON star_qualifying_parents(school_id);
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
        "ALTER TABLE schools ADD COLUMN IF NOT EXISTS terms_accepted_at TIMESTAMP",
        "ALTER TABLE schools ADD COLUMN IF NOT EXISTS terms_accepted_by TEXT",
        "ALTER TABLE schools ADD COLUMN IF NOT EXISTS verification_status TEXT DEFAULT 'approved'",
        "ALTER TABLE schools ADD COLUMN IF NOT EXISTS necta_code TEXT",
        "ALTER TABLE schools ADD COLUMN IF NOT EXISTS rejection_reason TEXT",
        "ALTER TABLE schools ADD COLUMN IF NOT EXISTS rejected_at TIMESTAMP",
        "ALTER TABLE schools ADD COLUMN IF NOT EXISTS approved_notice_pending INTEGER DEFAULT 0",
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
        cur.execute("CREATE INDEX IF NOT EXISTS idx_student_payments_student ON student_payments(school_id, student_id)")
    except Exception as e:
        print(f"Index creation note: {e}")

    con.commit(); cur.close(); con.close()
    print("DB ready (multi-tenant).")

   