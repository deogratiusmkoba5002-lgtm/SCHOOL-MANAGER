"""
Marks entry routes: CA, Exam, and Test score submission.
"""
from flask import Blueprint, request, jsonify, g

from core.db import get_db
from core.auth import require_auth, require_role
from services.scores import get_active_term, teacher_can_access, student_in_class

marks_bp = Blueprint("marks", __name__)

def _opt_int(v):
    return int(v) if v not in (None, "", 0, "0") else None


def _parse(d, **casts):
    """Returns (values, None) or (None, name_of_first_bad_field)."""
    out = {}
    for name, cast in casts.items():
        try:
            out[name] = cast(d.get(name))
        except (TypeError, ValueError):
            return None, name
    return out, None


@marks_bp.route("/api/marks/ca", methods=["POST"])
@require_auth
@require_role("admin","teacher")
def api_enter_ca():
    sid = g.school_id; d = request.get_json(silent=True) or {}
    username = g.username
    subject=d.get("subject","").lower().strip()
    p, bad = _parse(d, class_id=int, stream_id=_opt_int, student_id=int, score=float)
    if bad: return jsonify({"ok":False,"error":f"Invalid {bad}"}),400
    class_id, stream_id, student_id, score = p["class_id"], p["stream_id"], p["student_id"], p["score"]
    ca_name = d.get("ca_name","")
    if not (0<=score<=100): return jsonify({"ok":False,"error":"Score must be 0-100"}),400
    if g.role=="teacher" and not teacher_can_access(sid,username,subject,class_id,stream_id):
        return jsonify({"ok":False,"error":"Access denied"}),403
    if not student_in_class(sid, student_id, class_id, stream_id):
        return jsonify({"ok":False,"error":"Student is not in that class"}),400
    term = get_active_term(sid)
    if not term: return jsonify({"ok":False,"error":"No active term"}),400
    if ca_name not in {f"CA{i}" for i in range(1, term["ca_count"] + 1)}:
        return jsonify({"ok": False, "error": "Invalid CA name"}), 400
    con = get_db(); cur = con.cursor()
    cur.execute("""INSERT INTO ca_scores(school_id,student_id,subject,ca_name,score,entered_by,term_id)
                   VALUES(%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT(school_id,student_id,subject,ca_name,term_id)
                   DO UPDATE SET score=EXCLUDED.score,entered_by=EXCLUDED.entered_by""",
                (sid,student_id,subject,ca_name,score,username,term["id"]))
    con.commit(); cur.close(); con.close(); return jsonify({"ok":True})


@marks_bp.route("/api/marks/exam", methods=["POST"])
@require_auth
@require_role("admin","teacher")
def api_enter_exam():
    sid = g.school_id; d = request.get_json(silent=True) or {}
    username = g.username
    subject=d.get("subject","").lower().strip()
    p, bad = _parse(d, class_id=int, stream_id=_opt_int, student_id=int, score=float)
    if bad: return jsonify({"ok":False,"error":f"Invalid {bad}"}),400
    class_id, stream_id, student_id, score = p["class_id"], p["stream_id"], p["student_id"], p["score"]
    if not (0<=score<=100): return jsonify({"ok":False,"error":"Score must be 0-100"}),400
    if g.role=="teacher" and not teacher_can_access(sid,username,subject,class_id,stream_id):
        return jsonify({"ok":False,"error":"Access denied"}),403
    if not student_in_class(sid, student_id, class_id, stream_id):
        return jsonify({"ok":False,"error":"Student is not in that class"}),400
    term = get_active_term(sid)
    if not term: return jsonify({"ok":False,"error":"No active term"}),400
    con = get_db(); cur = con.cursor()
    cur.execute("""INSERT INTO exam_scores(school_id,student_id,subject,score,entered_by,term_id)
                   VALUES(%s,%s,%s,%s,%s,%s)
                   ON CONFLICT(school_id,student_id,subject,term_id)
                   DO UPDATE SET score=EXCLUDED.score,entered_by=EXCLUDED.entered_by""",
                (sid,student_id,subject,score,username,term["id"]))
    con.commit(); cur.close(); con.close(); return jsonify({"ok":True})


@marks_bp.route("/api/marks/test", methods=["POST"])
@require_auth
@require_role("admin","teacher")
def api_enter_test():
    sid = g.school_id; d = request.get_json(silent=True) or {}
    username = g.username
    subject=d.get("subject","").lower().strip()
    p, bad = _parse(d, class_id=int, stream_id=_opt_int, student_id=int, test_id=int, score=float)
    if bad: return jsonify({"ok":False,"error":f"Invalid {bad}"}),400
    class_id, stream_id, student_id, test_id, score = (p["class_id"], p["stream_id"], p["student_id"],
                                                       p["test_id"], p["score"])
    if not (0<=score<=100): return jsonify({"ok":False,"error":"Score must be 0-100"}),400
    if g.role=="teacher" and not teacher_can_access(sid,username,subject,class_id,stream_id):
        return jsonify({"ok":False,"error":"Access denied"}),403
    if not student_in_class(sid, student_id, class_id, stream_id):
        return jsonify({"ok":False,"error":"Student is not in that class"}),400   
    con=get_db(); cur=con.cursor()
    cur.execute("SELECT term_id, all_classes FROM term_tests WHERE id=%s AND school_id=%s",(test_id,sid))
    row=cur.fetchone()
    if not row: cur.close(); con.close(); return jsonify({"ok":False,"error":"Test not found"}),404
    term_id, all_classes = row
    if not all_classes:
        cur.execute("SELECT 1 FROM test_classes WHERE test_id=%s AND class_id=%s",(test_id,class_id))
        if not cur.fetchone():
            cur.close(); con.close()
            return jsonify({"ok":False,"error":"This class is not part of this test"}),403
    cur.execute("""INSERT INTO test_scores(school_id,student_id,subject,test_id,score,entered_by,term_id)
                   VALUES(%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT(school_id,student_id,subject,test_id,term_id)
                   DO UPDATE SET score=EXCLUDED.score,entered_by=EXCLUDED.entered_by""",
                (sid,student_id,subject,test_id,score,username,term_id))
    con.commit(); cur.close(); con.close(); return jsonify({"ok":True})