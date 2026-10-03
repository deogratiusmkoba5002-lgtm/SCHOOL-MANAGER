"""
Centralized error monitoring + grouping + throttled email alerts.
Rules: nothing here may raise into the request path; storage uses its own short-timeout connection;
secrets are never stored (no bodies/headers/cookies/query VALUES, route templates not real paths,
pattern scrubbing of text). Grouping/alert state lives in the DB because gunicorn runs 2 workers.
"""
import hashlib
import logging
import os
import re
import secrets
import smtplib
import threading
import traceback
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

import psycopg2
import requests
from psycopg2.extras import Json
from flask import jsonify, request, g, has_request_context
from werkzeug.exceptions import HTTPException

log = logging.getLogger("drdemic.monitoring")

SEVERITIES = ("INFO", "WARNING", "ERROR", "CRITICAL")
SEV_RANK = {s: i for i, s in enumerate(SEVERITIES)}
SEVERITY_COLORS = {"INFO": "#1565C0", "WARNING": "#F9A825", "ERROR": "#EF6C00", "CRITICAL": "#C62828"}
SAFE_USER_MESSAGE = "Something went wrong on our side. Please try again."
MAX_EVENTS_PER_GROUP = 25                      # newest N occurrences kept per group; the counter keeps counting
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Unexpected failures in these endpoints involve money -> always CRITICAL.
PAYMENT_ENDPOINTS = {"access.api_access_pay", "access.api_access_check", "access.api_access_webhook"}

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


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


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


# ── CLASSIFICATION + FINGERPRINT ────────────────────────────────
def classify_severity(exc, endpoint=None):
    if isinstance(exc, (psycopg2.OperationalError, psycopg2.InterfaceError)):
        return "CRITICAL"
    if endpoint in PAYMENT_ENDPOINTS:
        return "CRITICAL"
    if isinstance(exc, (ValueError, KeyError, TypeError)):
        return "WARNING"
    return "ERROR"


def _origin(exc):
    """(relative file, function) of the innermost traceback frame inside the project; line numbers are
    deliberately ignored so a redeploy does not split a group."""
    try:
        frames = traceback.extract_tb(exc.__traceback__)
    except Exception:
        return "", ""
    if not frames:
        return "", ""
    chosen = frames[-1]
    for fr in reversed(frames):
        path = os.path.abspath(fr.filename)
        if path.startswith(_PROJECT_ROOT + os.sep) and "site-packages" not in path:
            chosen = fr
            break
    try:
        rel = os.path.relpath(os.path.abspath(chosen.filename), _PROJECT_ROOT).replace("\\", "/")
    except ValueError:
        rel = os.path.basename(chosen.filename)
    return rel, chosen.name


def make_fingerprint(exc, endpoint, operation, message):
    if exc is not None:
        file, func = _origin(exc)
        # A database outage is one underlying problem no matter which endpoint tripped over it.
        db_down = isinstance(exc, (psycopg2.OperationalError, psycopg2.InterfaceError))
        parts = ["exc", type(exc).__name__, "" if db_down else (endpoint or ""), file, func]
    else:
        parts = ["evt", operation or "", endpoint or "", re.sub(r"\d+", "#", message or "")[:120]]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:32]


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
          "school_id": None, "username": None, "role": None, "context": {}, "fingerprint": None}
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
    try:
        ev["fingerprint"] = make_fingerprint(exc, ev["endpoint"], ev["operation"], ev["message"])
    except Exception:
        ev["fingerprint"] = None            # event is still stored, just not grouped
    return ev


# ── ALERT SETTINGS / FORMATTING / DELIVERY ──────────────────────
def _alert_settings():
    env = os.environ.get

    def _int(name, default):
        try:
            return max(int(env(name) or default), 0)
        except (TypeError, ValueError):
            return default
    min_sev = (env("ALERT_MIN_SEVERITY") or "CRITICAL").upper()
    return {
        "min_sev": min_sev if min_sev in SEV_RANK else "CRITICAL",
        "throttle_min": _int("ALERT_THROTTLE_MINUTES", 60),
        "max_per_hour": _int("ALERT_MAX_PER_HOUR", 10),
        "to": [a.strip() for a in (env("ALERT_EMAIL_TO") or "").split(",") if a.strip()],
        "from": env("ALERT_EMAIL_FROM") or "",
        "api_key": env("ALERT_EMAIL_API_KEY") or "",
        "smtp_host": env("ALERT_SMTP_HOST") or "",
        "smtp_port": _int("ALERT_SMTP_PORT", 587),
        "smtp_user": env("ALERT_SMTP_USER") or "",
        "smtp_password": env("ALERT_SMTP_PASSWORD") or "",
    }


def _alerts_enabled():
    s = _alert_settings()
    return bool(s["to"] and (s["api_key"] or s["smtp_host"]))


def _fmt_time(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC") if dt else "-"


def _alert_subject(p):
    return f"[DrDemic {p['severity']}] {p['operation'] or p['endpoint'] or 'error'} - {p['exception_type'] or 'event'}"


def _format_alert(p):
    school = p.get("school_name") or ""
    if p.get("school_id"):
        school = f"{school} (#{p['school_id']})".strip()
    where = f"{p.get('method') or ''} {p.get('endpoint') or p.get('path') or '-'}".strip()
    occ = f"Occurrences: {p['occurrences']}"
    if p.get("suppressed"):
        occ += f" ({p['suppressed']} more since the last alert)"
    lines = [f"{p['severity']} DRDEMIC ERROR", "",
             f"Event ID: {p['event_id']}",
             f"Operation: {p.get('operation') or '-'}",
             f"School: {school or '-'}",
             f"Endpoint: {where}",
             f"Error: {p.get('exception_type') or 'event'}: {p.get('message') or ''}",
             occ,
             f"First seen: {p.get('first_seen') or '-'}",
             f"Last seen: {p.get('last_seen') or '-'}"]
    if p.get("reopened"):
        lines.append("Note: this error had been marked resolved and has come back.")
    elif p.get("new_group"):
        lines.append("Note: first time this error has been seen.")
    base = (os.environ.get("PUBLIC_BASE_URL") or os.environ.get("RENDER_EXTERNAL_URL") or "").rstrip("/")
    if base:
        lines += ["", f"Details: {base}/superadmin"]
    return "\n".join(lines)


def _deliver_alert(p):
    """Raises on failure (caller contains it). HTTP email API preferred; SMTP as an alternative."""
    s = _alert_settings()
    subject, body = _alert_subject(p), _format_alert(p)
    if s["api_key"]:
        r = requests.post("https://api.resend.com/emails", timeout=8,
                          headers={"Authorization": f"Bearer {s['api_key']}", "Content-Type": "application/json"},
                          json={"from": s["from"] or "DrDemic Alerts <onboarding@resend.dev>",
                                "to": s["to"], "subject": subject, "text": body})
        if r.status_code >= 300:
            raise RuntimeError(f"email API returned HTTP {r.status_code}")
        return
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = s["from"] or s["smtp_user"]
    msg["To"] = ", ".join(s["to"])
    msg.set_content(body)
    with smtplib.SMTP(s["smtp_host"], s["smtp_port"], timeout=8) as smtp:
        smtp.starttls()
        if s["smtp_user"]:
            smtp.login(s["smtp_user"], s["smtp_password"])
        smtp.send_message(msg)


def _connect():
    from config import DATABASE_URL
    return psycopg2.connect(DATABASE_URL, connect_timeout=3, options="-c statement_timeout=3000")


def _run_delivery(p):
    """Runs in a background thread. Never raises."""
    ok, err = True, None
    try:
        _deliver_alert(p)
    except Exception as e:
        ok, err = False, scrub_text(f"{type(e).__name__}: {e}", 300)
        try:
            log.error("alert delivery failed for %s: %s", p.get("event_id"), err)
        except Exception:
            pass
    try:
        con = _connect()
        try:
            cur = con.cursor()
            cur.execute("UPDATE error_alerts SET delivered=%s, error=%s WHERE id=%s", (ok, err, p.get("alert_id")))
            con.commit()
            cur.close()
        finally:
            con.close()
    except Exception:
        try:
            log.error("could not record alert delivery result for %s", p.get("event_id"))
        except Exception:
            pass


def _dispatch_alert(p):
    threading.Thread(target=_run_delivery, args=(p,), daemon=True).start()


# ── STORAGE + GROUPING ──────────────────────────────────────────
def _group_step(cur, ev, now):
    """Upsert the group row and decide whether an alert is due. Runs inside the caller's transaction.
    The group row is locked (FOR UPDATE), so two workers can never both claim the same alert."""
    fp = ev["fingerprint"]
    cur.execute("""INSERT INTO error_groups(fingerprint,severity,kind,exception_type,endpoint,operation,sample_message,
                                            occurrence_count,first_seen,last_seen,last_event_id,last_school_id)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,1,%s,%s,%s,%s)
                   ON CONFLICT(fingerprint) DO NOTHING RETURNING id""",
                (fp, ev["severity"], ev["kind"], ev["exception_type"], ev["endpoint"], ev["operation"],
                 (ev["message"] or "")[:500], now, now, ev["event_id"], ev["school_id"]))
    created = cur.fetchone() is not None
    cur.execute("""SELECT id,status,severity,occurrence_count,first_seen,last_alert_at,suppressed_since_alert
                   FROM error_groups WHERE fingerprint=%s FOR UPDATE""", (fp,))
    gid, status, sev, count, first_seen, last_alert_at, suppressed = cur.fetchone()
    reopened = False
    if not created:
        count += 1
        if SEV_RANK[ev["severity"]] > SEV_RANK.get(sev, 0):
            sev = ev["severity"]
        if status == "resolved":
            status, reopened = "new", True          # a "fixed" error that came back is never hidden
        cur.execute("""UPDATE error_groups SET occurrence_count=%s, severity=%s, status=%s, last_seen=%s,
                       last_event_id=%s, last_school_id=%s, sample_message=%s WHERE id=%s""",
                    (count, sev, status, now, ev["event_id"], ev["school_id"], (ev["message"] or "")[:500], gid))

    cfg = _alert_settings()
    if not _alerts_enabled() or status == "ignored" or SEV_RANK.get(sev, 0) < SEV_RANK[cfg["min_sev"]]:
        return None
    due = created or reopened or last_alert_at is None or \
        (now - last_alert_at) >= timedelta(minutes=cfg["throttle_min"])
    claimed = False
    if due:
        cur.execute("SELECT COUNT(*) FROM error_alerts WHERE sent_at > %s", (now - timedelta(hours=1),))
        claimed = cur.fetchone()[0] < cfg["max_per_hour"]
    if not claimed:
        cur.execute("UPDATE error_groups SET suppressed_since_alert=suppressed_since_alert+1 WHERE id=%s", (gid,))
        return None
    cur.execute("INSERT INTO error_alerts(group_id,sent_at) VALUES(%s,%s) RETURNING id", (gid, now))
    alert_id = cur.fetchone()[0]
    cur.execute("UPDATE error_groups SET last_alert_at=%s, suppressed_since_alert=0 WHERE id=%s", (now, gid))
    cur.execute("DELETE FROM error_alerts WHERE sent_at < %s", (now - timedelta(days=7),))
    school_name = None
    if ev["school_id"]:
        cur.execute("SELECT school_name FROM schools WHERE id=%s", (ev["school_id"],))
        row = cur.fetchone()
        school_name = row[0] if row else None
    return {"alert_id": alert_id, "group_id": gid, "severity": sev, "event_id": ev["event_id"],
            "operation": ev["operation"], "school_id": ev["school_id"], "school_name": school_name,
            "method": ev["method"], "path": ev["path"], "endpoint": ev["endpoint"],
            "exception_type": ev["exception_type"], "message": (ev["message"] or "")[:500],
            "occurrences": count, "suppressed": suppressed,
            "first_seen": _fmt_time(now if created else first_seen), "last_seen": _fmt_time(now),
            "reopened": reopened, "new_group": created}


def _store_event(ev):
    """Stores the event (always first, committed), then groups it. Returns an alert payload or None."""
    con = _connect()
    alert = None
    try:
        cur = con.cursor()
        cur.execute("""INSERT INTO error_events(event_id,kind,severity,exception_type,message,http_status,method,
                                                path,endpoint,blueprint,operation,school_id,username,role,traceback,
                                                context,fingerprint)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (ev["event_id"], ev["kind"], ev["severity"], ev["exception_type"], ev["message"],
                     ev["http_status"], ev["method"], ev["path"], ev["endpoint"], ev["blueprint"],
                     ev["operation"], ev["school_id"], ev["username"], ev["role"], ev["traceback"],
                     Json(redact(ev["context"])), ev["fingerprint"]))
        con.commit()                                      # the raw event is safe from here on
        if ev.get("fingerprint"):
            try:
                alert = _group_step(cur, ev, _utcnow())
                cur.execute("""DELETE FROM error_events WHERE fingerprint=%s AND id NOT IN
                               (SELECT id FROM error_events WHERE fingerprint=%s ORDER BY id DESC LIMIT %s)""",
                            (ev["fingerprint"], ev["fingerprint"], MAX_EVENTS_PER_GROUP))
                con.commit()
            except Exception:
                con.rollback()
                alert = None
                log.error("monitoring grouping failed for event %s", ev["event_id"], exc_info=True)
        cur.close()
    finally:
        con.close()
    return alert


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
    alert = None
    try:
        alert = _store_event(ev)
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
    if alert:
        try:
            _dispatch_alert(alert)
        except Exception:
            try:
                log.error("alert dispatch failed for event %s", ev["event_id"], exc_info=True)
            except Exception:
                pass
    return ev["event_id"]


# ── PUBLIC API ──────────────────────────────────────────────────
def capture_exception(exc, status=500):
    return _record(exc, status=status)


def record_event(message, severity="INFO", operation=None, exc=None):
    """For code that handles an exception itself but still wants it visible."""
    return _record(exc, severity=severity, message=message, operation=operation, kind="event", status=None)


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