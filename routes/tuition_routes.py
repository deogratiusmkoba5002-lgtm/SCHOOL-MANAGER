"""DrDemic Tuition API: own accounts (teacher/student), courses, scheduled sessions with a recorded video,
per-student Q&A, assignments and Snippe payments."""
import os, re, secrets
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import Blueprint, request, jsonify, send_file, g, make_response
from itsdangerous import URLSafeTimedSerializer, BadSignature

from config import (SECRET_KEY, SESSION_MAX_AGE, TUITION_MAX_STUDENTS, TUITION_MAX_VIDEO_MB,
                    TUITION_VIDEO_DIR, TUITION_FILE_DIR, TUITION_USE_XACCEL)
from core.db import get_db
from core.ratelimit import rate_limit
from core.security import hash_password, verify_password
from services.access import normalize_phone, SnippeError
from services import tuition as T

tuition_bp = Blueprint("tuition", __name__)
_ser = URLSafeTimedSerializer(SECRET_KEY, salt="drdemic-tuition-session")

VIDEO_EXT = {"mp4": "video/mp4", "m4v": "video/mp4", "webm": "video/webm", "mov": "video/quicktime"}
IMG_EXT = {"png", "jpg", "jpeg", "webp", "gif"}
DOC_EXT = IMG_EXT | {"pdf", "doc", "docx", "ppt", "pptx", "xls", "xlsx", "txt"}
MAX_VIDEO_SECONDS = 40 * 60 + 5


# ── helpers ─────────────────────────────────────────────────
@contextmanager
def db():
    con = get_db(); cur = con.cursor()
    try:
        yield con, cur
    finally:
        cur.close(); con.close()


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iso(d):
    return d.isoformat() + "Z" if d else None


def _int(v, default=None):
    try: return int(v)
    except (TypeError, ValueError): return default


def _err(msg, code=400):
    return jsonify({"ok": False, "error": msg}), code


def _parse_dt(s):
    try: d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError: return None
    return d.astimezone(timezone.utc).replace(tzinfo=None) if d.tzinfo else d


def _save_upload(f, exts, max_mb):
    """-> (stored_name, original_name, error). (None, None, None) when no file was sent."""
    if not f or not f.filename:
        return None, None, None
    ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
    if ext not in exts:
        return None, None, "That file type is not allowed"
    name = secrets.token_hex(16) + "." + ext
    path = os.path.join(TUITION_FILE_DIR, name)
    f.save(path)
    if os.path.getsize(path) > max_mb * 1024 * 1024:
        os.remove(path)
        return None, None, f"File must be smaller than {max_mb}MB"
    return name, re.sub(r"[^\w. -]", "_", f.filename)[:120], None


def _send_stored(name, orig=None):
    path = os.path.join(TUITION_FILE_DIR, os.path.basename(name or ""))
    if not name or not os.path.exists(path):
        return _err("File not found", 404)
    resp = send_file(path, download_name=orig or os.path.basename(path))
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


def _activate_due():
    """A session becomes active the moment the teacher is available AND the start time has arrived."""
    with db() as (con, cur):
        cur.execute("""UPDATE tuition_sessions SET status='active', started_at=NOW() AT TIME ZONE 'utc'
                       WHERE status='scheduled' AND teacher_available=1
                         AND scheduled_at <= NOW() AT TIME ZONE 'utc'""")
        con.commit()


# ── auth ────────────────────────────────────────────────────
def _current_user():
    auth = request.headers.get("Authorization", "")
    tok = auth[7:].strip() if auth.startswith("Bearer ") else request.args.get("token")
    if not tok:
        return None
    try:
        d = _ser.loads(tok, max_age=SESSION_MAX_AGE)
    except BadSignature:
        return None
    with db() as (con, cur):
        cur.execute("SELECT id,username,role,full_name,token_version,must_change_password FROM tuition_users WHERE id=%s",
                    (d.get("uid"),))
        r = cur.fetchone()
    if not r or r[4] != d.get("tv"):
        return None
    return {"id": r[0], "username": r[1], "role": r[2], "full_name": r[3], "must_change": bool(r[5])}


def need_user(*roles):
    def deco(f):
        @wraps(f)
        def w(*a, **k):
            u = _current_user()
            if not u:
                return _err("Please sign in", 401)
            if roles and u["role"] not in roles:
                return _err("Forbidden", 403)
            g.tu = u
            return f(*a, **k)
        return w
    return deco


def _token_reply(uid, username, role, full_name, must_change, tv):
    return jsonify({"ok": True, "token": _ser.dumps({"uid": uid, "tv": tv}), "username": username, "role": role,
                    "full_name": full_name, "must_change_password": bool(must_change)})


@tuition_bp.route("/api/tuition/auth/signup", methods=["POST"])
@rate_limit("tuition_signup_attempts", max_attempts=60, window_minutes=60, by="ip")
@rate_limit("tuition_signup", max_attempts=10, window_minutes=60, by="ip", count_on="success")
def signup():
    d = request.get_json(silent=True) or {}
    u, p = (d.get("username") or "").strip(), d.get("password") or ""
    name = " ".join((d.get("full_name") or "").split())
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,40}", u) or u.isdigit():
        return _err("Username: 3-40 letters/numbers/_ . - with at least one letter")
    if not (3 <= len(name) <= 80):
        return _err("Enter your full name")
    if len(p) < 6:
        return _err("Password must be at least 6 characters")
    if p != (d.get("confirm_password") or ""):
        return _err("Passwords do not match")
    if not d.get("agree_terms"):
        return _err("You must agree to the Privacy Policy and Terms")
    phone = normalize_phone(d.get("phone"))
    if not phone:
        return _err("Enter a valid phone number, e.g. 0712345678")
    with db() as (con, cur):
        cur.execute("INSERT INTO tuition_users(username,password,role,full_name,phone) VALUES(%s,%s,'teacher',%s,%s) "
                    "ON CONFLICT DO NOTHING RETURNING id", (u, hash_password(p), name, phone))
        row = cur.fetchone(); con.commit()
    if not row:
        return _err("That username is taken", 409)
    return _token_reply(row[0], u, "teacher", name, False, 0)


@tuition_bp.route("/api/tuition/auth/login", methods=["POST"])
@rate_limit("tuition_login", max_attempts=60, window_minutes=15, by="ip")
def login():
    d = request.get_json(silent=True) or {}
    u, p = (d.get("username") or "").strip(), d.get("password") or ""
    if not u or not p:
        return _err("Enter username and password")
    with db() as (con, cur):
        cur.execute("SELECT id,username,password,role,full_name,must_change_password,token_version "
                    "FROM tuition_users WHERE LOWER(username)=%s", (u.lower(),))
        r = cur.fetchone()
    if not r or not verify_password(p, r[2]):
        return _err("Wrong username or password", 401)
    return _token_reply(r[0], r[1], r[3], r[4], r[5], r[6])


@tuition_bp.route("/api/tuition/auth/change_password", methods=["POST"])
@need_user()
@rate_limit("tuition_pw", max_attempts=10, window_minutes=15, by="ip")
def change_password():
    d = request.get_json(silent=True) or {}
    new = d.get("new_password") or ""
    if len(new) < 6:
        return _err("Password must be at least 6 characters")
    with db() as (con, cur):
        cur.execute("SELECT password FROM tuition_users WHERE id=%s", (g.tu["id"],))
        if not verify_password(d.get("old_password") or "", cur.fetchone()[0]):
            return _err("Current password is incorrect", 401)
        cur.execute("UPDATE tuition_users SET password=%s,must_change_password=0,token_version=token_version+1 "
                    "WHERE id=%s RETURNING token_version", (hash_password(new), g.tu["id"]))
        tv = cur.fetchone()[0]; con.commit()
    u = g.tu
    return _token_reply(u["id"], u["username"], u["role"], u["full_name"], False, tv)


# ── courses & students ──────────────────────────────────────
_CC = "c.id,c.teacher_id,c.subject,c.title,c.price_tzs,c.access_days,c.max_students"
_CK = ("id", "teacher_id", "subject", "title", "price", "access_days", "max_students")


def _course(cur, cid, u):
    if u["role"] == "teacher":
        cur.execute(f"SELECT {_CC} FROM tuition_courses c WHERE c.id=%s AND c.teacher_id=%s", (cid, u["id"]))
    else:
        cur.execute(f"SELECT {_CC} FROM tuition_courses c JOIN tuition_enrollments e ON e.course_id=c.id "
                    "WHERE c.id=%s AND e.student_id=%s", (cid, u["id"]))
    r = cur.fetchone()
    return dict(zip(_CK, r)) if r else None


@tuition_bp.route("/api/tuition/courses", methods=["GET"])
@need_user("teacher", "student")
def courses_list():
    u = g.tu
    if u["role"] == "student":
        T.refresh_pending(u["id"])
    with db() as (con, cur):
        if u["role"] == "teacher":
            cur.execute("""SELECT c.id,c.subject,c.title,c.price_tzs,c.access_days,c.max_students,
                                  (SELECT COUNT(*) FROM tuition_enrollments e WHERE e.course_id=c.id),
                                  (SELECT COUNT(*) FROM tuition_sessions s WHERE s.course_id=c.id)
                           FROM tuition_courses c WHERE c.teacher_id=%s ORDER BY c.id DESC""", (u["id"],))
            out = [{"id": r[0], "subject": r[1], "title": r[2], "price": r[3], "access_days": r[4],
                    "max_students": r[5], "students": r[6], "sessions": r[7]} for r in cur.fetchall()]
        else:
            cur.execute("""SELECT c.id,c.subject,c.title,c.price_tzs,c.access_days,t.full_name,a.expires_at
                           FROM tuition_enrollments e JOIN tuition_courses c ON c.id=e.course_id
                           JOIN tuition_users t ON t.id=c.teacher_id
                           LEFT JOIN tuition_access a ON a.course_id=c.id AND a.student_id=e.student_id
                           WHERE e.student_id=%s ORDER BY c.id DESC""", (u["id"],))
            now = _now()
            out = [{"id": r[0], "subject": r[1], "title": r[2], "price": r[3], "access_days": r[4], "teacher": r[5],
                    "active": r[3] <= 0 or bool(r[6] and r[6] > now), "expires_at": _iso(r[6])} for r in cur.fetchall()]
    return jsonify({"ok": True, "courses": out})


@tuition_bp.route("/api/tuition/courses", methods=["POST"])
@need_user("teacher")
def course_create():
    d = request.get_json(silent=True) or {}
    subject = " ".join((d.get("subject") or "").split())[:60]
    title = " ".join((d.get("title") or "").split())[:100]
    price, days = _int(d.get("price"), 0), _int(d.get("access_days"), 30)
    mx = _int(d.get("max_students"), TUITION_MAX_STUDENTS)
    if not subject:
        return _err("Enter the subject")
    if price < 0 or (0 < price < 500):
        return _err("Price must be 0 (free) or at least 500 TZS")
    if not (1 <= days <= 365):
        return _err("Access days must be between 1 and 365")
    if not (1 <= mx <= TUITION_MAX_STUDENTS):
        return _err(f"Maximum students must be between 1 and {TUITION_MAX_STUDENTS}")
    with db() as (con, cur):
        cur.execute("INSERT INTO tuition_courses(teacher_id,subject,title,price_tzs,access_days,max_students) "
                    "VALUES(%s,%s,%s,%s,%s,%s) RETURNING id", (g.tu["id"], subject, title, price, days, mx))
        cid = cur.fetchone()[0]; con.commit()
    return jsonify({"ok": True, "id": cid})


@tuition_bp.route("/api/tuition/courses/<int:cid>/students", methods=["GET"])
@need_user("teacher")
def students_list(cid):
    with db() as (con, cur):
        if not _course(cur, cid, g.tu):
            return _err("Course not found", 404)
        cur.execute("""SELECT u.id,u.full_name,u.phone,a.expires_at FROM tuition_enrollments e
                       JOIN tuition_users u ON u.id=e.student_id
                       LEFT JOIN tuition_access a ON a.student_id=u.id AND a.course_id=e.course_id
                       WHERE e.course_id=%s ORDER BY u.full_name""", (cid,))
        now = _now()
        rows = [{"id": r[0], "name": r[1], "phone": r[2], "paid": bool(r[3] and r[3] > now),
                 "expires_at": _iso(r[3])} for r in cur.fetchall()]
    return jsonify({"ok": True, "students": rows})


@tuition_bp.route("/api/tuition/courses/<int:cid>/students", methods=["POST"])
@need_user("teacher")
def student_enroll(cid):
    d = request.get_json(silent=True) or {}
    name = " ".join((d.get("name") or "").split())[:80]
    phone = normalize_phone(d.get("phone"))
    if len(name) < 3 or not phone:
        return _err("Enter the student's full name and a valid parent phone number")
    with db() as (con, cur):
        c = _course(cur, cid, g.tu)
        if not c:
            return _err("Course not found", 404)
        cur.execute("SELECT COUNT(*) FROM tuition_enrollments WHERE course_id=%s", (cid,))
        if cur.fetchone()[0] >= c["max_students"]:
            return _err(f"This course is full ({c['max_students']} students)", 409)
        cur.execute("SELECT id FROM tuition_users WHERE role='student' AND phone=%s AND LOWER(full_name)=%s",
                    (phone, name.lower()))
        row = cur.fetchone(); creds = None
        if row:
            sid = row[0]
        else:
            base = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:20] or "student"
            temp = "".join(secrets.choice("0123456789") for _ in range(6))
            sid = None
            for _ in range(6):
                uname = f"{base}{secrets.randbelow(900) + 100}"
                cur.execute("INSERT INTO tuition_users(username,password,role,full_name,phone,must_change_password) "
                            "VALUES(%s,%s,'student',%s,%s,1) ON CONFLICT DO NOTHING RETURNING id",
                            (uname, hash_password(temp), name, phone))
                r = cur.fetchone()
                if r:
                    sid, creds = r[0], {"username": uname, "password": temp}
                    break
            if not sid:
                return _err("Could not create a username, try again", 500)
        cur.execute("INSERT INTO tuition_enrollments(course_id,student_id) VALUES(%s,%s) ON CONFLICT DO NOTHING", (cid, sid))
        added = cur.rowcount > 0
        con.commit()
    if not added:
        return _err("This student is already in the course", 409)
    return jsonify({"ok": True, "credentials": creds})


@tuition_bp.route("/api/tuition/courses/<int:cid>/students/<int:sid>", methods=["DELETE"])
@need_user("teacher")
def student_remove(cid, sid):
    with db() as (con, cur):
        if not _course(cur, cid, g.tu):
            return _err("Course not found", 404)
        cur.execute("DELETE FROM tuition_enrollments WHERE course_id=%s AND student_id=%s", (cid, sid))
        con.commit()
    return jsonify({"ok": True})


@tuition_bp.route("/api/tuition/students/<int:sid>/reset_password", methods=["POST"])
@need_user("teacher")
@rate_limit("tuition_reset", max_attempts=30, window_minutes=60, by="ip")
def student_reset(sid):
    temp = "".join(secrets.choice("0123456789") for _ in range(6))
    with db() as (con, cur):
        cur.execute("""UPDATE tuition_users u SET password=%s, must_change_password=1, token_version=token_version+1
                       WHERE u.id=%s AND u.role='student' AND EXISTS
                         (SELECT 1 FROM tuition_enrollments e JOIN tuition_courses c ON c.id=e.course_id
                          WHERE e.student_id=u.id AND c.teacher_id=%s) RETURNING u.username""",
                    (hash_password(temp), sid, g.tu["id"]))
        row = cur.fetchone(); con.commit()
    if not row:
        return _err("Student not found", 404)
    return jsonify({"ok": True, "username": row[0], "temp_password": temp})


# ── sessions ────────────────────────────────────────────────
_SC = "s.id,s.course_id,s.title,s.scheduled_at,s.video_file,s.video_size,s.video_seconds,s.status,s.teacher_available"


def _sj(r):
    return {"id": r[0], "course_id": r[1], "title": r[2], "scheduled_at": _iso(r[3]), "has_video": bool(r[4]),
            "video_size": r[5], "video_seconds": r[6], "status": r[7], "teacher_available": bool(r[8])}


def _session(cur, sid, u):
    q = (f"SELECT {_SC}, c.teacher_id, c.price_tzs, c.subject FROM tuition_sessions s "
         "JOIN tuition_courses c ON c.id=s.course_id ")
    if u["role"] == "teacher":
        cur.execute(q + "WHERE s.id=%s AND c.teacher_id=%s", (sid, u["id"]))
    else:
        cur.execute(q + "JOIN tuition_enrollments e ON e.course_id=c.id AND e.student_id=%s WHERE s.id=%s", (u["id"], sid))
    r = cur.fetchone()
    if not r:
        return None
    d = _sj(r)
    d.update(video_file=r[4], raw_scheduled=r[3], teacher_id=r[9], price=r[10], subject=r[11])
    return d


@tuition_bp.route("/api/tuition/courses/<int:cid>/sessions", methods=["GET"])
@need_user("teacher", "student")
def sessions_list(cid):
    _activate_due()
    u = g.tu
    with db() as (con, cur):
        c = _course(cur, cid, u)
        if not c:
            return _err("Course not found", 404)
        paid = T.has_access(cur, u["id"], cid, c["price"]) if u["role"] == "student" else True
        sender = "student" if u["role"] == "teacher" else "teacher"
        extra, params = ("", [sender]) if u["role"] == "teacher" else ("AND m.student_id=%s", [sender, u["id"]])
        cur.execute(f"""SELECT {_SC}, (SELECT COUNT(*) FROM tuition_messages m WHERE m.session_id=s.id
                                       AND m.sender_role=%s AND m.is_read=0 {extra})
                        FROM tuition_sessions s WHERE s.course_id=%s ORDER BY s.scheduled_at DESC""", params + [cid])
        out = [dict(_sj(r), unread=r[9]) for r in cur.fetchall()]
    return jsonify({"ok": True, "sessions": out, "paid": paid})


@tuition_bp.route("/api/tuition/courses/<int:cid>/sessions", methods=["POST"])
@need_user("teacher")
def session_create(cid):
    d = request.get_json(silent=True) or {}
    title = " ".join((d.get("title") or "").split())[:120]
    when = _parse_dt(d.get("scheduled_at"))
    if not title or not when:
        return _err("Enter a title and the start time")
    with db() as (con, cur):
        if not _course(cur, cid, g.tu):
            return _err("Course not found", 404)
        cur.execute("INSERT INTO tuition_sessions(course_id,title,scheduled_at) VALUES(%s,%s,%s) RETURNING id",
                    (cid, title, when))
        sid = cur.fetchone()[0]; con.commit()
    return jsonify({"ok": True, "id": sid})


@tuition_bp.route("/api/tuition/sessions/<int:sid>", methods=["GET"])
@need_user("teacher", "student")
def session_get(sid):
    _activate_due()
    u = g.tu
    with db() as (con, cur):
        s = _session(cur, sid, u)
        if not s:
            return _err("Session not found", 404)
        paid = T.has_access(cur, u["id"], s["course_id"], s["price"]) if u["role"] == "student" else True
    out = {k: s[k] for k in ("id", "course_id", "title", "scheduled_at", "has_video", "video_size", "video_seconds",
                              "status", "teacher_available", "subject")}
    return jsonify({"ok": True, "session": out, "paid": paid})


@tuition_bp.route("/api/tuition/sessions/<int:sid>/video", methods=["POST"])
@need_user("teacher")
def video_upload(sid):
    f = request.files.get("video")
    secs = _int(request.form.get("seconds"), 0)
    ext = f.filename.rsplit(".", 1)[-1].lower() if f and f.filename and "." in f.filename else ""
    if ext not in VIDEO_EXT:
        return _err("Upload an MP4 (or WebM/MOV) video")
    if not (1 <= secs <= MAX_VIDEO_SECONDS):
        return _err("Lesson videos can be at most 40 minutes long")
    with db() as (con, cur):
        s = _session(cur, sid, g.tu)
        if not s:
            return _err("Session not found", 404)
        if s["status"] == "ended":
            return _err("This session has ended", 409)
    name = secrets.token_hex(16) + "." + ext
    path = os.path.join(TUITION_VIDEO_DIR, name)
    f.save(path)
    size = os.path.getsize(path)
    if size > TUITION_MAX_VIDEO_MB * 1024 * 1024:
        os.remove(path)
        return _err(f"Video must be smaller than {TUITION_MAX_VIDEO_MB}MB. Compress it (720p is plenty).")
    with db() as (con, cur):
        cur.execute("UPDATE tuition_sessions SET video_file=%s,video_size=%s,video_seconds=%s WHERE id=%s",
                    (name, size, secs, sid))
        con.commit()
    if s["video_file"]:
        try: os.remove(os.path.join(TUITION_VIDEO_DIR, os.path.basename(s["video_file"])))
        except OSError: pass
    return jsonify({"ok": True})


@tuition_bp.route("/api/tuition/sessions/<int:sid>/video", methods=["GET"])
@need_user("teacher", "student")
def video_get(sid):
    """Streaming needs an open session. Downloading for offline is allowed from 24h before the start time."""
    u = g.tu
    dl = request.args.get("dl") == "1"
    with db() as (con, cur):
        s = _session(cur, sid, u)
        if not s or not s["video_file"]:
            return _err("Video not found", 404)
        if u["role"] == "student":
            if not T.has_access(cur, u["id"], s["course_id"], s["price"]):
                return _err("Payment required", 402)
            if dl and _now() < s["raw_scheduled"] - timedelta(hours=24):
                return _err("Downloads open 24 hours before the session", 403)
            if not dl and s["status"] == "scheduled":
                return _err("The session has not started yet", 403)
    fname = os.path.basename(s["video_file"])
    mime = VIDEO_EXT.get(fname.rsplit(".", 1)[-1], "video/mp4")
    if TUITION_USE_XACCEL:                         # nginx serves the bytes; workers stay free
        resp = make_response("")
        resp.headers["X-Accel-Redirect"] = "/protected-tuition/" + fname
        resp.headers["Content-Type"] = mime
        resp.headers["Cache-Control"] = "private"
        return resp
    return send_file(os.path.join(TUITION_VIDEO_DIR, fname), mimetype=mime, conditional=True, max_age=0)


@tuition_bp.route("/api/tuition/sessions/<int:sid>/availability", methods=["POST"])
@need_user("teacher")
def availability(sid):
    on = 1 if (request.get_json(silent=True) or {}).get("available") else 0
    with db() as (con, cur):
        s = _session(cur, sid, g.tu)
        if not s:
            return _err("Session not found", 404)
        if s["status"] == "ended":
            return _err("This session has ended", 409)
        cur.execute("UPDATE tuition_sessions SET teacher_available=%s WHERE id=%s", (on, sid))
        con.commit()
    _activate_due()
    return jsonify({"ok": True})


@tuition_bp.route("/api/tuition/sessions/<int:sid>/end", methods=["POST"])
@need_user("teacher")
def session_end(sid):
    with db() as (con, cur):
        if not _session(cur, sid, g.tu):
            return _err("Session not found", 404)
        cur.execute("UPDATE tuition_sessions SET status='ended', teacher_available=0, "
                    "ended_at=NOW() AT TIME ZONE 'utc' WHERE id=%s", (sid,))
        con.commit()
    return jsonify({"ok": True})


@tuition_bp.route("/api/tuition/due", methods=["GET"])
@need_user("teacher")
def due():
    """Sessions about to begin (or already late) where the teacher has not gone available yet."""
    _activate_due()
    with db() as (con, cur):
        cur.execute("""SELECT s.id,s.title,s.scheduled_at,c.id,c.subject FROM tuition_sessions s
                       JOIN tuition_courses c ON c.id=s.course_id
                       WHERE c.teacher_id=%s AND s.status='scheduled' AND s.teacher_available=0
                         AND s.scheduled_at <= (NOW() AT TIME ZONE 'utc') + INTERVAL '15 minutes'
                         AND s.scheduled_at > (NOW() AT TIME ZONE 'utc') - INTERVAL '12 hours'
                       ORDER BY s.scheduled_at""", (g.tu["id"],))
        rows = [{"id": r[0], "title": r[1], "scheduled_at": _iso(r[2]), "course_id": r[3], "subject": r[4]}
                for r in cur.fetchall()]
    return jsonify({"ok": True, "due": rows})


# ── questions / messages ────────────────────────────────────
@tuition_bp.route("/api/tuition/sessions/<int:sid>/messages", methods=["POST"])
@need_user("teacher", "student")
def msg_post(sid):
    u = g.tu
    body = (request.form.get("body") or "").strip()[:2000]
    img = request.files.get("image")
    if not body and not (img and img.filename):
        return _err("Write a message or attach an image")
    with db() as (con, cur):
        s = _session(cur, sid, u)
        if not s:
            return _err("Session not found", 404)
        if s["status"] == "ended":
            return _err("This session has ended", 409)
        if u["role"] == "student":
            student_id = u["id"]
            if not T.has_access(cur, u["id"], s["course_id"], s["price"]):
                return _err("Payment required", 402)
            if s["status"] == "scheduled":
                return _err("The session has not started yet", 409)
            ts = _int(request.form.get("video_ts"))
        else:
            student_id, ts = _int(request.form.get("student_id")), None
            cur.execute("SELECT 1 FROM tuition_enrollments WHERE course_id=%s AND student_id=%s", (s["course_id"], student_id))
            if not cur.fetchone():
                return _err("Student not found", 404)
        fname, _, err = _save_upload(img, IMG_EXT, 5)
        if err:
            return _err(err)
        cur.execute("INSERT INTO tuition_messages(session_id,student_id,sender_role,body,video_ts,image_file) "
                    "VALUES(%s,%s,%s,%s,%s,%s) RETURNING id", (sid, student_id, u["role"], body, ts, fname))
        mid = cur.fetchone()[0]; con.commit()
    return jsonify({"ok": True, "id": mid})


@tuition_bp.route("/api/tuition/sessions/<int:sid>/messages", methods=["GET"])
@need_user("teacher", "student")
def msg_get(sid):
    _activate_due()
    u = g.tu
    after = _int(request.args.get("after"), 0)
    with db() as (con, cur):
        s = _session(cur, sid, u)
        if not s:
            return _err("Session not found", 404)
        student_id = u["id"] if u["role"] == "student" else _int(request.args.get("student_id"))
        cur.execute("""SELECT id,sender_role,body,video_ts,image_file IS NOT NULL,created_at FROM tuition_messages
                       WHERE session_id=%s AND student_id=%s AND id>%s ORDER BY id""", (sid, student_id, after))
        msgs = [{"id": r[0], "sender_role": r[1], "body": r[2], "video_ts": r[3], "has_image": r[4],
                 "at": _iso(r[5])} for r in cur.fetchall()]
        other = "teacher" if u["role"] == "student" else "student"
        cur.execute("UPDATE tuition_messages SET is_read=1 WHERE session_id=%s AND student_id=%s "
                    "AND sender_role=%s AND is_read=0", (sid, student_id, other))
        con.commit()
    return jsonify({"ok": True, "messages": msgs,
                    "session": {"status": s["status"], "teacher_available": s["teacher_available"]}})


@tuition_bp.route("/api/tuition/sessions/<int:sid>/inbox", methods=["GET"])
@need_user("teacher")
def inbox(sid):
    _activate_due()
    with db() as (con, cur):
        s = _session(cur, sid, g.tu)
        if not s:
            return _err("Session not found", 404)
        cur.execute("""SELECT u.id,u.full_name,
              (SELECT COUNT(*) FROM tuition_messages m WHERE m.session_id=%s AND m.student_id=u.id
                  AND m.sender_role='student' AND m.is_read=0),
              (SELECT body FROM tuition_messages m WHERE m.session_id=%s AND m.student_id=u.id ORDER BY id DESC LIMIT 1),
              (SELECT video_ts FROM tuition_messages m WHERE m.session_id=%s AND m.student_id=u.id
                  AND m.sender_role='student' AND m.is_read=0 ORDER BY id LIMIT 1)
            FROM tuition_enrollments e JOIN tuition_users u ON u.id=e.student_id WHERE e.course_id=%s""",
                    (sid, sid, sid, s["course_id"]))
        rows = [{"id": r[0], "name": r[1], "unread": r[2], "last": r[3] or "", "video_ts": r[4]} for r in cur.fetchall()]
    rows.sort(key=lambda r: (-r["unread"], r["name"].lower()))
    return jsonify({"ok": True, "students": rows,
                    "session": {"status": s["status"], "teacher_available": s["teacher_available"]}})


@tuition_bp.route("/api/tuition/messages/<int:mid>/image", methods=["GET"])
@need_user("teacher", "student")
def msg_image(mid):
    with db() as (con, cur):
        cur.execute("""SELECT m.image_file,m.student_id,c.teacher_id FROM tuition_messages m
                       JOIN tuition_sessions s ON s.id=m.session_id JOIN tuition_courses c ON c.id=s.course_id
                       WHERE m.id=%s""", (mid,))
        r = cur.fetchone()
    if not r or not r[0] or g.tu["id"] not in (r[1], r[2]):
        return _err("Not found", 404)
    return _send_stored(r[0])


# ── assignments ─────────────────────────────────────────────
@tuition_bp.route("/api/tuition/courses/<int:cid>/assignments", methods=["GET"])
@need_user("teacher", "student")
def assign_list(cid):
    u = g.tu
    with db() as (con, cur):
        if not _course(cur, cid, u):
            return _err("Course not found", 404)
        if u["role"] == "teacher":
            cur.execute("""SELECT a.id,a.title,a.instructions,a.due_at,a.max_score,a.file_name,
                  (SELECT COUNT(*) FROM tuition_submissions s WHERE s.assignment_id=a.id),
                  (SELECT COUNT(*) FROM tuition_submissions s WHERE s.assignment_id=a.id AND s.marked_at IS NOT NULL)
                  FROM tuition_assignments a WHERE a.course_id=%s ORDER BY a.id DESC""", (cid,))
            out = [{"id": r[0], "title": r[1], "instructions": r[2], "due_at": _iso(r[3]), "max_score": r[4],
                    "file_name": r[5], "submitted": r[6], "marked": r[7]} for r in cur.fetchall()]
        else:
            cur.execute("""SELECT a.id,a.title,a.instructions,a.due_at,a.max_score,a.file_name,
                  s.id,s.body,s.file_name,s.submitted_at,s.score,s.feedback
                  FROM tuition_assignments a LEFT JOIN tuition_submissions s
                    ON s.assignment_id=a.id AND s.student_id=%s WHERE a.course_id=%s ORDER BY a.id DESC""", (u["id"], cid))
            out = [{"id": r[0], "title": r[1], "instructions": r[2], "due_at": _iso(r[3]), "max_score": r[4],
                    "file_name": r[5],
                    "mine": ({"id": r[6], "body": r[7], "file_name": r[8], "submitted_at": _iso(r[9]),
                              "score": r[10], "feedback": r[11]} if r[6] else None)} for r in cur.fetchall()]
    return jsonify({"ok": True, "assignments": out})


@tuition_bp.route("/api/tuition/courses/<int:cid>/assignments", methods=["POST"])
@need_user("teacher")
def assign_create(cid):
    title = " ".join((request.form.get("title") or "").split())[:150]
    instr = (request.form.get("instructions") or "").strip()[:4000]
    due = _parse_dt(request.form.get("due_at")) if request.form.get("due_at") else None
    mx = _int(request.form.get("max_score"), 100)
    if not title or not (1 <= mx <= 1000):
        return _err("Enter a title and a maximum score between 1 and 1000")
    with db() as (con, cur):
        if not _course(cur, cid, g.tu):
            return _err("Course not found", 404)
        stored, orig, err = _save_upload(request.files.get("file"), DOC_EXT, 10)
        if err:
            return _err(err)
        cur.execute("INSERT INTO tuition_assignments(course_id,title,instructions,due_at,max_score,file_path,file_name) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING id", (cid, title, instr, due, mx, stored, orig))
        aid = cur.fetchone()[0]; con.commit()
    return jsonify({"ok": True, "id": aid})


def _assignment(cur, aid, u):
    cur.execute("""SELECT a.id,a.course_id,a.max_score,a.file_path,a.file_name,a.due_at FROM tuition_assignments a
                   WHERE a.id=%s""", (aid,))
    a = cur.fetchone()
    if not a or not _course(cur, a[1], u):
        return None
    return a


@tuition_bp.route("/api/tuition/assignments/<int:aid>/file", methods=["GET"])
@need_user("teacher", "student")
def assign_file(aid):
    with db() as (con, cur):
        a = _assignment(cur, aid, g.tu)
    return _send_stored(a[3], a[4]) if a and a[3] else _err("Not found", 404)


@tuition_bp.route("/api/tuition/assignments/<int:aid>/submit", methods=["POST"])
@need_user("student")
def assign_submit(aid):
    body = (request.form.get("body") or "").strip()[:6000]
    with db() as (con, cur):
        a = _assignment(cur, aid, g.tu)
        if not a:
            return _err("Assignment not found", 404)
        cur.execute("SELECT price_tzs FROM tuition_courses WHERE id=%s", (a[1],))
        if not T.has_access(cur, g.tu["id"], a[1], cur.fetchone()[0]):
            return _err("Payment required", 402)
        cur.execute("SELECT marked_at FROM tuition_submissions WHERE assignment_id=%s AND student_id=%s", (aid, g.tu["id"]))
        ex = cur.fetchone()
        if ex and ex[0]:
            return _err("This work has already been marked", 409)
        stored, orig, err = _save_upload(request.files.get("file"), DOC_EXT, 10)
        if err:
            return _err(err)
        if not body and not stored and not ex:
            return _err("Write your answer or attach a file")
        cur.execute("""INSERT INTO tuition_submissions(assignment_id,student_id,body,file_path,file_name)
                       VALUES(%s,%s,%s,%s,%s)
                       ON CONFLICT(assignment_id,student_id) DO UPDATE SET body=EXCLUDED.body,
                         file_path=COALESCE(EXCLUDED.file_path,tuition_submissions.file_path),
                         file_name=COALESCE(EXCLUDED.file_name,tuition_submissions.file_name),
                         submitted_at=NOW()""", (aid, g.tu["id"], body, stored, orig))
        con.commit()
    return jsonify({"ok": True, "late": bool(a[5] and _now() > a[5])})


@tuition_bp.route("/api/tuition/assignments/<int:aid>/submissions", methods=["GET"])
@need_user("teacher")
def subs_list(aid):
    with db() as (con, cur):
        a = _assignment(cur, aid, g.tu)
        if not a:
            return _err("Assignment not found", 404)
        cur.execute("""SELECT u.id,u.full_name,s.id,s.body,s.file_name,s.submitted_at,s.score,s.feedback
                       FROM tuition_enrollments e JOIN tuition_users u ON u.id=e.student_id
                       LEFT JOIN tuition_submissions s ON s.student_id=u.id AND s.assignment_id=%s
                       WHERE e.course_id=%s ORDER BY u.full_name""", (aid, a[1]))
        rows = [{"student_id": r[0], "name": r[1],
                 "sub": ({"id": r[2], "body": r[3], "file_name": r[4], "submitted_at": _iso(r[5]),
                          "score": r[6], "feedback": r[7], "late": bool(a[5] and r[5] and r[5] > a[5])} if r[2] else None)}
                for r in cur.fetchall()]
    return jsonify({"ok": True, "max_score": a[2], "rows": rows})


@tuition_bp.route("/api/tuition/submissions/<int:subid>/file", methods=["GET"])
@need_user("teacher", "student")
def sub_file(subid):
    with db() as (con, cur):
        cur.execute("""SELECT s.file_path,s.file_name,s.student_id,c.teacher_id FROM tuition_submissions s
                       JOIN tuition_assignments a ON a.id=s.assignment_id JOIN tuition_courses c ON c.id=a.course_id
                       WHERE s.id=%s""", (subid,))
        r = cur.fetchone()
    if not r or not r[0] or g.tu["id"] not in (r[2], r[3]):
        return _err("Not found", 404)
    return _send_stored(r[0], r[1])


@tuition_bp.route("/api/tuition/submissions/<int:subid>/mark", methods=["POST"])
@need_user("teacher")
def sub_mark(subid):
    d = request.get_json(silent=True) or {}
    try: score = float(d.get("score"))
    except (TypeError, ValueError): return _err("Enter a score")
    with db() as (con, cur):
        cur.execute("""SELECT a.max_score FROM tuition_submissions s JOIN tuition_assignments a ON a.id=s.assignment_id
                       JOIN tuition_courses c ON c.id=a.course_id WHERE s.id=%s AND c.teacher_id=%s""", (subid, g.tu["id"]))
        r = cur.fetchone()
        if not r:
            return _err("Submission not found", 404)
        if not (0 <= score <= r[0]):
            return _err(f"Score must be between 0 and {r[0]}")
        cur.execute("UPDATE tuition_submissions SET score=%s,feedback=%s,marked_at=NOW() WHERE id=%s",
                    (score, str(d.get("feedback") or "").strip()[:2000], subid))
        con.commit()
    return jsonify({"ok": True})


@tuition_bp.route("/api/tuition/courses/<int:cid>/progress", methods=["GET"])
@need_user("teacher", "student")
def progress(cid):
    u = g.tu
    with db() as (con, cur):
        if not _course(cur, cid, u):
            return _err("Course not found", 404)
        extra, params = ("AND u.id=%s", [cid, u["id"]]) if u["role"] == "student" else ("", [cid])
        cur.execute(f"""SELECT u.id,u.full_name,COUNT(DISTINCT a.id),COUNT(s.id),COUNT(s.score),
                               AVG(s.score*100.0/a.max_score)
                        FROM tuition_enrollments e JOIN tuition_users u ON u.id=e.student_id
                        LEFT JOIN tuition_assignments a ON a.course_id=e.course_id
                        LEFT JOIN tuition_submissions s ON s.assignment_id=a.id AND s.student_id=u.id
                        WHERE e.course_id=%s {extra} GROUP BY u.id,u.full_name ORDER BY u.full_name""", params)
        rows = [{"id": r[0], "name": r[1], "assigned": r[2], "submitted": r[3], "marked": r[4],
                 "avg_pct": round(float(r[5]), 1) if r[5] is not None else None} for r in cur.fetchall()]
    return jsonify({"ok": True, "rows": rows})


# ── payments ────────────────────────────────────────────────
@tuition_bp.route("/api/tuition/pay", methods=["POST"])
@need_user("student")
def pay():
    d = request.get_json(silent=True) or {}
    try:
        res = T.start_payment(g.tu["id"], _int(d.get("course_id")), d.get("phone") or "")
    except ValueError as e:
        return _err(str(e))
    except SnippeError as e:
        return _err(str(e), 502)
    return jsonify({"ok": True, **res})


@tuition_bp.route("/api/tuition/pay/check/<int:pid>", methods=["POST"])
@need_user("student")
def pay_check(pid):
    with db() as (con, cur):
        cur.execute("SELECT student_id FROM tuition_payments WHERE id=%s", (pid,))
        r = cur.fetchone()
    if not r or r[0] != g.tu["id"]:
        return _err("Payment not found", 404)
    return jsonify({"ok": True, "status": T.finalize_payment(pid)})