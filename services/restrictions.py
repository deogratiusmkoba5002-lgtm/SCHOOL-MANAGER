"""
Per-student result restriction (e.g. unpaid school fees). The check is
always made with the student_id from the signed login token, never from
anything the client sends.
"""
from flask import jsonify
from core.db import get_db


def get_restriction(school_id, student_id):
    if not student_id:
        return None
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT reason FROM student_restrictions WHERE school_id=%s AND student_id=%s",
                (school_id, student_id))
    row = cur.fetchone(); cur.close(); con.close()
    return {"reason": row[0] or ""} if row else None


def parent_restricted_response(school_id, role, token_student_id):
    """Returns a (response, 403) tuple if this is a restricted parent, else None."""
    if role != "parent":
        return None
    r = get_restriction(school_id, token_student_id)
    if not r:
        return None
    msg = "Results for this student are currently restricted by the school."
    if r["reason"]:
        msg += " Reason: " + r["reason"]
    return jsonify({"ok": False, "error": msg, "code": "results_restricted",
                    "reason": r["reason"]}), 403