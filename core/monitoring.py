"""
Centralized error monitoring. Design rules:
  * NOTHING in here may raise into the request path (every public entry point swallows its own failures).
  * Storage uses its own short-timeout connection, never the request's connection.
  * Secrets are never stored: no bodies/headers/cookies/query VALUES; route templates instead of real paths;
    pattern-based scrubbing of messages and tracebacks.
"""
import logging
import re
import secrets
import traceback

import psycopg2
from psycopg2.extras import Json
from flask import jsonify, request, g, has_request_context
from werkzeug.exceptions import HTTPException

log = logging.getLogger("drdemic.monitoring")

SEVERITIES = ("INFO", "WARNING", "ERROR", "CRITICAL")
SEVERITY_COLORS = {"INFO": "#1565C0", "WARNING": "#F9A825", "ERROR": "#EF6C00", "CRITICAL": "#C62828"}
SAFE_USER_MESSAGE = "Something went wrong on our side. Please try again."

# Unexpected failures in these endpoints involve money -> always CRITICAL.
PAYMENT_ENDPOINTS = {"access.api_access_pay", "access.api_access_check", "access.api_access_webhook"}

# (endpoint prefix, human-readable operation). First match wins.
OPERATIONS = [
    ("pdf.", "PDF generation"), ("student_import.", "Student import"),
    ("access.", "Parent payment"), ("subscription.", "School subscription"),
    ("auth.api_login", "Login"), ("auth.", "Authentication"),
    ("marks.", "Marks entry"), ("reports.", "Report cards"), ("scoresheet.", "Score sheets"),
    ("analytics.", "Analytics"), ("parent.", "Parent portal"), ("stars.", "Star system"),
    ("superadmin.", "Superadmin"), ("registration.", "School registration"),
    ("students.", "Students"), ("teachers.", "Teachers"), ("classes.", "Classes"),
    ("terms.", "Terms"), ("config.", "School config"), ("announcements.", "Announcements"),
    ("static_pages.", "Static pages"),
]


def operation_for(endpoint):
    for prefix, name in OPERATIONS:
        if endpoint and endpoint.startswith(prefix):
            return name
    return None


# ── REDACTION ───────────────────────────────────────────────────
_SENSITIVE_KEY = re.compile(
    r"pass(word|wd)?|token|secret|authoriz|api[_-]?key|cookie|session|signature|credential|^pin$", re.I)
_TEXT_PATTERNS = [
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+"), "Bearer [REDACTED]"),
    (re.compile(r"(?i)\b(password|passwd|pwd|token|secret|api[_-]?key|authorization|signature)"
                r"(['\"]?\s*[:=]\s*['\"]?)([^\s,;&'\"}]+)"), r"\1\2[REDACTED]"),
    (re.compile(r"(?i)(postgres(?:ql)?://[^:/\s]+:)[^@\s]+@"), r"\1[REDACTED]@"),
]


def scrub_text(text, limit):
    text = str(text)
    for pattern, repl in _TEXT_PATTERNS:
        text = pattern.sub(repl, text)
    return text[:limit]


def redact(value, _depth=0):
    if _depth > 6:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        return {str(k): ("[REDACTED]" if _SENSITIVE_KEY.search(str(k)) else redact(v, _depth + 1))
                for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [redact(v, _depth + 1) for v in list(value)[:50]]
    if isinstance(value, str):
        return scrub_text(value, 500)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return scrub_text(repr(value), 200)


# ── CLASSIFICATION ──────────────────────────────────────────────
def classify_severity(exc, endpoint=None):
    if isinstance(exc, (psycopg2.OperationalError, psycopg2.InterfaceError)):
        return "CRITICAL"
    if endpoint in PAYMENT_ENDPOINTS:
        return "CRITICAL"
    if isinstance(exc, (ValueError, KeyError, TypeError)):
        return "WARNING"
    return "ERROR"


# ── EVENT CONSTRUCTION ──────────────────────────────────────────
def _as_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _request_context():
    """Field NAMES only, never values (values may be passwords/tokens)."""
    ctx = {}
    try:
        ctx["query_params"] = sorted(request.args.keys())[:50]
        ctx["content_type"] = request.content_type
        ctx["content_length"] = request.content_length
        if (request.content_length or 0) < 1_000_000:
            if request.is_json:
                body = request.get_json(silent=True)
                if isinstance(body, dict):
                    ctx["json_fields"] = sorted(str(k) for k in body.keys())[:50]
            elif request.form:
                ctx["form_fields"] = sorted(request.form.keys())[:50]
        if request.files:
            ctx["file_fields"] = sorted(request.files.keys())[:20]
        ctx["view_args"] = redact(request.view_args or {})
    except Exception:
        ctx["context_error"] = "could not read request context"
    return ctx


def _build_event(exc, severity, message, operation, kind, status):
    ev = {"event_id": "EVT-" + secrets.token_hex(5).upper(), "kind": kind, "http_status": status,
          "method": None, "path": None, "endpoint": None, "blueprint": None,
          "school_id": None, "username": None, "role": None, "context": {}}
    override = None
    if has_request_context():
        rule = request.url_rule
        ev.update(method=request.method,
                  path=(rule.rule if rule else request.path)[:300],   # template, not the real path
                  endpoint=request.endpoint, blueprint=request.blueprint,
                  school_id=_as_int(getattr(g, "school_id", None)),
                  username=getattr(g, "username", None), role=getattr(g, "role", None))
        ev["context"] = _request_context()
        override = getattr(g, "monitor_operation", None)
    ev["operation"] = operation or override or operation_for(ev["endpoint"])

    if exc is not None:
        ev["exception_type"] = type(exc).__name__
        ev["message"] = scrub_text(str(exc) or type(exc).__name__, 2000)
        ev["traceback"] = scrub_text("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)), 20000)
        ev["severity"] = severity if severity in SEVERITIES else classify_severity(exc, ev["endpoint"])
    else:
        ev["exception_type"] = None
        ev["message"] = scrub_text(message or "", 2000)
        ev["traceback"] = None
        ev["severity"] = severity if severity in SEVERITIES else "INFO"
    return ev


def _store_event(ev):
    from config import DATABASE_URL
    con = psycopg2.connect(DATABASE_URL, connect_timeout=3, options="-c statement_timeout=3000")
    try:
        cur = con.cursor()
        cur.execute("""INSERT INTO error_events(event_id,kind,severity,exception_type,message,http_status,method,
                                                path,endpoint,blueprint,operation,school_id,username,role,traceback,context)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (ev["event_id"], ev["kind"], ev["severity"], ev["exception_type"], ev["message"],
                     ev["http_status"], ev["method"], ev["path"], ev["endpoint"], ev["blueprint"],
                     ev["operation"], ev["school_id"], ev["username"], ev["role"], ev["traceback"],
                     Json(redact(ev["context"]))))
        con.commit()
        cur.close()
    finally:
        con.close()


def _record(exc, severity=None, message=None, operation=None, kind="exception", status=500):
    """Always returns an event id. Never raises."""
    try:
        ev = _build_event(exc, severity, message, operation, kind, status)
    except Exception:
        event_id = "EVT-" + secrets.token_hex(5).upper()
        try:
            log.error("monitoring build failed; event %s: %s", event_id, scrub_text(repr(exc), 500), exc_info=True)
        except Exception:
            pass
        return event_id
    try:
        _store_event(ev)
        log.log(logging.ERROR if ev["severity"] in ("ERROR", "CRITICAL") else logging.WARNING,
                "event %s [%s] %s %s: %s", ev["event_id"], ev["severity"], ev["endpoint"],
                ev["exception_type"], ev["message"][:300])
    except Exception:
        try:
            log.error("monitoring storage failed; event %s [%s] %s %s: %s\n%s", ev["event_id"], ev["severity"],
                      ev["endpoint"], ev["exception_type"], ev["message"][:300], (ev["traceback"] or "")[:3000],
                      exc_info=True)
        except Exception:
            pass
    return ev["event_id"]


# ── PUBLIC API ──────────────────────────────────────────────────
def capture_exception(exc, status=500):
    return _record(exc, status=status)


def record_event(message, severity="INFO", operation=None, exc=None):
    """For code that handles an exception itself but still wants it visible."""
    return _record(exc, severity=severity, message=message, operation=operation, kind="event",
                   status=None)


def init_monitoring(app):
    @app.errorhandler(Exception)
    def _on_exception(exc):
        try:
            if isinstance(exc, HTTPException):
                if (exc.code or 0) >= 500:
                    capture_exception(exc, exc.code)
                return exc                      # 4xx / redirects behave exactly as before
            event_id = capture_exception(exc, 500)
            return jsonify({"ok": False, "error": SAFE_USER_MESSAGE, "event_id": event_id}), 500
        except Exception:
            return jsonify({"ok": False, "error": SAFE_USER_MESSAGE}), 500