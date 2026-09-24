"""
School-scoping helpers: resolving which school a request belongs to,
registration-code validation, and school_config key/value storage.
"""
import re
from flask import request
from core.db import get_db

_REG_CODE_RE = re.compile(r'^[A-Za-z0-9_-]{3,32}$')


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


def valid_reg_code(code):
    return bool(code) and bool(_REG_CODE_RE.match(code.strip()))


def format_student_display_id(school_id, school_student_no):
    if not school_student_no: return str(school_id)
    return f"{int(school_id):05d}/{int(school_student_no):04d}"


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

_NECTA_CODE_RE = re.compile(r'^[A-Za-z]\d{3,6}$')

def valid_necta_code(code):
    # Placeholder pattern (one letter + 3–6 digits, e.g. S1234). Swap this
    # regex for the real NECTA format once you confirm it exactly.
    return bool(code) and bool(_NECTA_CODE_RE.match(code.strip()))


def purge_expired_rejected_schools():
    """Deletes schools rejected more than 6 hours ago that were never
    re-verified. Called lazily (no scheduler needed) whenever superadmin
    loads the verification queue."""
    con = get_db(); cur = con.cursor()
    cur.execute("""SELECT id FROM schools WHERE verification_status='rejected'
                   AND rejected_at IS NOT NULL AND rejected_at < NOW() - INTERVAL '6 hours'""")
    ids = [r[0] for r in cur.fetchall()]
    for sid in ids:
        cur.execute("DELETE FROM ca_scores WHERE school_id=%s", (sid,))
        cur.execute("DELETE FROM exam_scores WHERE school_id=%s", (sid,))
        cur.execute("DELETE FROM test_scores WHERE school_id=%s", (sid,))
        cur.execute("DELETE FROM subject_assignments WHERE school_id=%s", (sid,))
        cur.execute("DELETE FROM remarks WHERE school_id=%s", (sid,))
        cur.execute("DELETE FROM announcement_reads WHERE announcement_id IN (SELECT id FROM announcements WHERE school_id=%s)", (sid,))
        cur.execute("DELETE FROM announcements WHERE school_id=%s", (sid,))
        cur.execute("DELETE FROM students WHERE school_id=%s", (sid,))
        cur.execute("DELETE FROM streams WHERE school_id=%s", (sid,))
        cur.execute("DELETE FROM classes WHERE school_id=%s", (sid,))
        cur.execute("DELETE FROM school_subjects WHERE school_id=%s", (sid,))
        cur.execute("DELETE FROM grade_config WHERE school_id=%s", (sid,))
        cur.execute("DELETE FROM terms WHERE school_id=%s", (sid,))
        cur.execute("DELETE FROM users WHERE school_id=%s", (sid,))
        cur.execute("DELETE FROM school_config WHERE school_id=%s", (sid,))
        cur.execute("DELETE FROM schools WHERE id=%s", (sid,))
    if ids: con.commit()
    cur.close(); con.close()
    return len(ids)