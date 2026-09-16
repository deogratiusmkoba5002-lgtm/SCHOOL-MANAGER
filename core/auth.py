"""
Authentication & session helpers: token issuing/verification, role guards,
login rate-limiting, and superadmin session handling.
"""
from functools import wraps
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from flask import g, request, jsonify

from config import SECRET_KEY, SESSION_MAX_AGE, SA_SESSION_MAX_AGE
from core.db import get_db

_serializer = URLSafeTimedSerializer(SECRET_KEY, salt="schoolmanager-session")
_sa_serializer = URLSafeTimedSerializer(SECRET_KEY, salt="superadmin-session")

LOGIN_MAX_ATTEMPTS = 5
LOGIN_WINDOW_MINUTES = 15


def issue_token(username, school_id, role, student_id=None, is_class_teacher=False,
                 class_id=None, stream_id=None, token_version=0):
    return _serializer.dumps({
        "username": username, "school_id": school_id, "role": role,
        "student_id": student_id, "is_class_teacher": is_class_teacher,
        "class_id": class_id, "stream_id": stream_id, "token_version": token_version,
    })


def require_auth(f):
    """Verifies the Bearer token and sets g.username / g.school_id / g.role etc.
    school_id now comes ONLY from the signed token — never from a header the
    client can freely change."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        token = auth[7:].strip() if auth.startswith("Bearer ") else request.args.get("token")
        if not token:
            return jsonify({"ok": False, "error": "Authentication required"}), 401
        try:
            data = _serializer.loads(token, max_age=SESSION_MAX_AGE)
        except SignatureExpired:
            return jsonify({"ok": False, "error": "Session expired, please log in again"}), 401
        except BadSignature:
            return jsonify({"ok": False, "error": "Invalid session"}), 401
        g.username = data["username"]; g.school_id = data["school_id"]; g.role = data["role"]
        g.student_id = data.get("student_id"); g.is_class_teacher = data.get("is_class_teacher", False)
        g.class_id = data.get("class_id"); g.stream_id = data.get("stream_id")
        con = get_db(); cur = con.cursor()
        cur.execute("SELECT token_version FROM users WHERE username=%s AND school_id=%s", (g.username, g.school_id))
        row = cur.fetchone(); cur.close(); con.close()
        if not row or (row[0] or 0) != data.get("token_version", 0):
            return jsonify({"ok": False, "error": "Session expired, please log in again"}), 401
        return f(*args, **kwargs)
    return wrapper


def require_role(*roles):
    def deco(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if g.role not in roles:
                return jsonify({"ok": False, "error": "Forbidden"}), 403
            return f(*args, **kwargs)
        return wrapper
    return deco


def _login_attempts_count(identifier):
    con = get_db(); cur = con.cursor()
    cur.execute("""SELECT COUNT(*) FROM login_attempts
                   WHERE identifier=%s AND attempted_at > NOW() - (%s * INTERVAL '1minute')""",
                (identifier, LOGIN_WINDOW_MINUTES))
    n = cur.fetchone()[0]; cur.close(); con.close()
    return n


def _record_login_attempt(identifier):
    con = get_db(); cur = con.cursor()
    cur.execute("INSERT INTO login_attempts(identifier) VALUES(%s)", (identifier,))
    cur.execute("DELETE FROM login_attempts WHERE attempted_at < NOW() - INTERVAL '1 hour'")
    con.commit(); cur.close(); con.close()


def _sa_token():
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "): return auth[7:].strip()
    return None


def _require_superadmin():
    token = _sa_token()
    if not token:
        return None, (jsonify({"ok": False, "error": "Superadmin authentication required"}), 401)
    try:
        data = _sa_serializer.loads(token, max_age=SA_SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None, (jsonify({"ok": False, "error": "Superadmin authentication required"}), 401)
    return data["username"], None