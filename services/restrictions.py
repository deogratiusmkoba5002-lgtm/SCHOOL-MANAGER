"""
Per-student result restriction (e.g. unpaid school fees).
Rule: a restriction only locks results published AFTER it was set. Anything
published at or before restricted_at (or before publish timestamps existed)
is permanently the parent's. The student_id always comes from the signed
token, never from the client.
"""
from flask import jsonify
from core.db import get_db


def get_restriction(school_id, student_id):
    if not student_id:
        return None
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT reason, restricted_at FROM student_restrictions WHERE school_id=%s AND student_id=%s",
                (school_id, student_id))
    row = cur.fetchone(); cur.close(); con.close()
    return {"reason": row[0] or "", "restricted_at": row[1]} if row else None


def public_restriction(school_id, student_id):
    r = get_restriction(school_id, student_id)
    if not r:
        return None
    return {"reason": r["reason"], "restricted_at": r["restricted_at"].isoformat() + "Z"}


def parent_restriction(school_id, role, student_id):
    """The restriction that applies to this request, or None. Only parents are ever restricted."""
    if role != "parent":
        return None
    return get_restriction(school_id, student_id)


def _published_rows(school_id, term_id):
    """[(assess_key, published_at)] for published assessments; the legacy whole-term flag is key '*'."""
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT assess_key, published_at FROM published_assessments "
                "WHERE school_id=%s AND term_id=%s AND published=1", (school_id, term_id))
    rows = list(cur.fetchall())
    cur.execute("SELECT published_at FROM results_published "
                "WHERE school_id=%s AND term_id=%s AND published=1", (school_id, term_id))
    legacy = cur.fetchone(); cur.close(); con.close()
    if legacy:
        rows.append(("*", legacy[0]))
    return rows


def _earned(published_at, restriction):
    return published_at is None or published_at <= restriction["restricted_at"]


def earned_keys(school_id, term_id, restriction):
    """Assessment keys of this term the restricted parent may still see."""
    return {k for k, at in _published_rows(school_id, term_id) if _earned(at, restriction)}


def term_report_allowed(school_id, term_id, restriction):
    """Report card of a term: only if something is published and none of it is newer than the restriction."""
    rows = _published_rows(school_id, term_id)
    return bool(rows) and all(_earned(at, restriction) for _, at in rows)


def locked_response(restriction):
    msg = "These results were published after your access was restricted by the school."
    if restriction["reason"]:
        msg += " Reason: " + restriction["reason"]
    return jsonify({"ok": False, "error": msg, "code": "results_restricted",
                    "reason": restriction["reason"]}), 403