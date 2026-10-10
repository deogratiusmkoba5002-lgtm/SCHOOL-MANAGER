"""
Admin-only: restrict / un-restrict parents' access to results per student.
"""
from flask import Blueprint, request, jsonify, g

from core.db import get_db
from core.auth import require_auth, require_role
from services.restrictions import public_restriction

restrictions_bp = Blueprint("restrictions", __name__)


@restrictions_bp.route("/api/restrictions", methods=["GET"])
@require_auth
@require_role("admin")
def api_list_restrictions():
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT student_id, reason FROM student_restrictions WHERE school_id=%s", (g.school_id,))
    rows = cur.fetchall(); cur.close(); con.close()
    return jsonify({"ok": True, "restrictions": {str(sid): reason or "" for sid, reason in rows}})


@restrictions_bp.route("/api/restrictions/bulk", methods=["POST"])
@require_auth
@require_role("admin")
def api_bulk_restrictions():
    sid = g.school_id
    d = request.get_json(silent=True) or {}
    restrict, lift = {}, []
    try:
        for item in (d.get("restrict") or []):
            restrict[int(item["student_id"])] = str(item.get("reason") or "").strip()[:300]
        lift = [int(i) for i in (d.get("unrestrict") or [])]
    except (TypeError, ValueError, KeyError, AttributeError):
        return jsonify({"ok": False, "error": "Invalid data"}), 400
    all_ids = list(set(restrict) | set(lift))
    if not all_ids:
        return jsonify({"ok": False, "error": "Nothing to update"}), 400

    con = get_db(); cur = con.cursor()
    try:
        # Only students that belong to THIS school are ever touched.
        cur.execute("SELECT id FROM students WHERE school_id=%s AND id=ANY(%s)", (sid, all_ids))
        valid = {r[0] for r in cur.fetchall()}
        for stid, reason in restrict.items():
            if stid in valid:
                cur.execute("""INSERT INTO student_restrictions(school_id,student_id,reason,restricted_by)
                               VALUES(%s,%s,%s,%s)
                               ON CONFLICT(school_id,student_id)
                               DO UPDATE SET reason=EXCLUDED.reason, restricted_by=EXCLUDED.restricted_by""",
                            (sid, stid, reason, g.username))
        lift_valid = [i for i in lift if i in valid]
        if lift_valid:
            cur.execute("DELETE FROM student_restrictions WHERE school_id=%s AND student_id=ANY(%s)",
                        (sid, lift_valid))
        con.commit()
    except Exception:
        con.rollback(); raise
    finally:
        cur.close(); con.close()
    return jsonify({"ok": True})
@restrictions_bp.route("/api/restrictions/mine", methods=["GET"])
@require_auth
@require_role("parent")
def api_my_restriction():
    return jsonify({"ok": True, "restriction": public_restriction(g.school_id, g.student_id)})