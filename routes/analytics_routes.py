"""
Analytics routes: overall/class-teacher overview, subject-teacher view,
and the dashboard's best/weakest class card.
"""
from flask import Blueprint, request, jsonify, g

from core.db import get_db, to_dicts
from core.auth import require_auth, require_role
from services.subscriptions import subscription_required
from services.scores import get_subjects, teacher_can_access
from services.analytics import (
    _compute_overall_series, _compute_subject_series,
    _build_common_cards, _best_weakest_subject,
)

analytics_bp = Blueprint("analytics", __name__)


@analytics_bp.route("/api/analytics/overview", methods=["GET"])
@require_auth
@subscription_required
def api_analytics_overview():
    sid = g.school_id
    username  = g.username
    role      = g.role
    class_id  = request.args.get("class_id") or None
    stream_id = request.args.get("stream_id") or None
    class_id  = int(class_id) if class_id else None
    stream_id = int(stream_id) if stream_id else None

    # A class teacher can only ever see their own class/stream — enforced
    # server-side regardless of what the request asked for, since this is
    # the same trust boundary marks entry already relies on.
    if role == "teacher":
        con = get_db(); cur = con.cursor()
        cur.execute("SELECT is_class_teacher,class_id,stream_id FROM users WHERE username=%s AND school_id=%s",
                    (username, sid))
        row = cur.fetchone(); cur.close(); con.close()
        if not row or not row[0]:
            return jsonify({"ok": False, "error": "Not a class teacher"}), 403
        if row[1] is None:
            return jsonify({"ok": False, "error": "No class assigned"}), 403
        class_id, stream_id = row[1], row[2]

    subjects = get_subjects(sid)
    points, name_map = _compute_overall_series(sid, class_id, stream_id, subjects)
    result = _build_common_cards(points, name_map, sid)
    if points:
        best_subj, weak_subj = _best_weakest_subject(
            sid, class_id, stream_id, subjects, points[-1]["term_id"], points[-1]["assess"])
        result["best_subject"] = best_subj
        result["weakest_subject"] = weak_subj
    else:
        result["best_subject"] = None
        result["weakest_subject"] = None
    return jsonify({"ok": True, **result})


@analytics_bp.route("/api/analytics/subject", methods=["GET"])
@require_auth
@subscription_required
def api_analytics_subject():
    sid       = g.school_id
    username  = g.username
    role      = g.role
    subject   = request.args.get("subject", "").lower().strip()
    class_id  = request.args.get("class_id")
    stream_id = request.args.get("stream_id") or None
    if not subject or not class_id:
        return jsonify({"ok": False, "error": "subject and class_id required"}), 400
    class_id  = int(class_id)
    stream_id = int(stream_id) if stream_id else None
    if role == "teacher" and not teacher_can_access(sid, username, subject, class_id, stream_id):
        return jsonify({"ok": False, "error": "Access denied"}), 403

    points, name_map = _compute_subject_series(sid, class_id, stream_id, subject)
    result = _build_common_cards(points, name_map, sid)
    return jsonify({"ok": True, **result})


@analytics_bp.route("/api/analytics/dashboard_classes", methods=["GET"])
@require_auth
@subscription_required
@require_role("admin")
def api_analytics_dashboard_classes():
    sid = g.school_id
    subjects = get_subjects(sid)
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT id,class_name FROM classes WHERE school_id=%s ORDER BY class_name", (sid,))
    classes = to_dicts(cur.fetchall(), cur); cur.close(); con.close()
    results = []
    for c in classes:
        points, _ = _compute_overall_series(sid, c["id"], None, subjects)
        if points:
            results.append({"class_id": c["id"], "class_name": c["class_name"], "average": points[-1]["avg"]})
    if not results:
        return jsonify({"ok": True, "best": None, "weakest": None})
    best = max(results, key=lambda r: r["average"])
    weakest = min(results, key=lambda r: r["average"])
    return jsonify({"ok": True, "best": best, "weakest": weakest})