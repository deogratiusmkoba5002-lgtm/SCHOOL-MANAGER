"""
Run this ONCE to set up the database and create the admin account.
Usage:  python setup_admin.py
"""
import sqlite3, hashlib, os, secrets, getpass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE  = os.path.join(BASE_DIR, "school.db")

def hash_password(password):
    salt = secrets.token_hex(16)
    dk   = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000)
    return f"{salt}:{dk.hex()}"

def init_db():
    con = sqlite3.connect(DB_FILE)
    cur = con.cursor()
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        username         TEXT PRIMARY KEY,
        password         TEXT NOT NULL,
        role             TEXT NOT NULL CHECK(role IN ('admin','teacher')),
        is_class_teacher INTEGER DEFAULT 0,
        class_name       TEXT DEFAULT NULL
    );

    CREATE TABLE IF NOT EXISTS students (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        name       TEXT NOT NULL,
        class_name TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS subject_assignments (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        username   TEXT NOT NULL,
        subject    TEXT NOT NULL,
        class_name TEXT NOT NULL,
        UNIQUE(username, subject, class_name),
        FOREIGN KEY(username) REFERENCES users(username)
    );

    CREATE TABLE IF NOT EXISTS terms (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        label       TEXT NOT NULL,
        ca_count    INTEGER NOT NULL DEFAULT 2,
        ca_weight   INTEGER NOT NULL DEFAULT 30,
        exam_weight INTEGER NOT NULL DEFAULT 70,
        status      TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','closed'))
    );

    CREATE TABLE IF NOT EXISTS ca_scores (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL,
        subject    TEXT NOT NULL,
        class_name TEXT NOT NULL,
        ca_name    TEXT NOT NULL,
        score      REAL NOT NULL,
        entered_by TEXT,
        term_id    INTEGER NOT NULL,
        UNIQUE(student_id, subject, ca_name, term_id),
        FOREIGN KEY(student_id) REFERENCES students(id),
        FOREIGN KEY(term_id)    REFERENCES terms(id)
    );

    CREATE TABLE IF NOT EXISTS exam_scores (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL,
        subject    TEXT NOT NULL,
        class_name TEXT NOT NULL,
        score      REAL NOT NULL,
        entered_by TEXT,
        term_id    INTEGER NOT NULL,
        UNIQUE(student_id, subject, term_id),
        FOREIGN KEY(student_id) REFERENCES students(id),
        FOREIGN KEY(term_id)    REFERENCES terms(id)
    );

    CREATE TABLE IF NOT EXISTS remarks (
        student_id           INTEGER NOT NULL,
        term_id              INTEGER NOT NULL,
        class_teacher_remark TEXT DEFAULT '',
        head_remark          TEXT DEFAULT '',
        PRIMARY KEY(student_id, term_id),
        FOREIGN KEY(student_id) REFERENCES students(id),
        FOREIGN KEY(term_id)    REFERENCES terms(id)
    );
    """)
    con.commit()
    con.close()
    print("✓ Database tables ready.")

def create_admin():
    print("\n=== School Manager – Admin Setup ===\n")
    username = input("Choose admin username: ").strip()
    if not username:
        print("Username cannot be empty."); return

    password = getpass.getpass("Choose admin password: ")
    confirm  = getpass.getpass("Confirm password: ")
    if password != confirm:
        print("Passwords do not match."); return
    if len(password) < 4:
        print("Password too short (minimum 4 characters)."); return

    con = sqlite3.connect(DB_FILE)
    cur = con.cursor()
    existing = cur.execute("SELECT username FROM users WHERE role='admin'").fetchone()
    if existing:
        print(f"\nAdmin account already exists ({existing[0]}). Delete {DB_FILE} to reset.")
        con.close(); return

    cur.execute("INSERT INTO users(username,password,role) VALUES(?,?,?)",
                (username, hash_password(password), "admin"))
    con.commit(); con.close()
    print(f"\n✓ Admin account '{username}' created.")
    print("You can now run:  python app.py\n")

if __name__ == "__main__":
    init_db()
    create_admin()
