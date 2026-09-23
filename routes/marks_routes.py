"""
Marks entry routes: CA, Exam, and Test score submission.
"""
from flask import Blueprint, request, jsonify, g

from core.db import get_db
from core.auth import require_auth, require_role
from services.scores import get_active_term, teacher_can_access

marks_bp = Blueprint("marks", __name__)


@marks_bp.route("/api/marks/ca", methods=["POST"])
@require_auth
@require_role("admin","teacher")
def api_enter_ca():
    sid = g.school_id; d = request.json
    username = g.username
    subject=d.get("subject","").lower().strip()
    class_id=int(d.get("class_id")); stream_id=d.get("stream_id") or None
    student_id=int(d.get("student_id")); ca_name=d.get("ca_name",""); score=float(d.get("score"))
    if not (0<=score<=100): return jsonify({"ok":False,"error":"Score must be 0-100"}),400
    if g.role=="teacher" and not teacher_can_access(sid,username,subject,class_id,stream_id):
        return jsonify({"ok":False,"error":"Access denied"}),403
    term = get_active_term(sid)
    if not term: return jsonify({"ok":False,"error":"No active term"}),400
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
    sid = g.school_id; d = request.json
    username = g.username
    subject=d.get("subject","").lower().strip()
    class_id=int(d.get("class_id")); stream_id=d.get("stream_id") or None
    student_id=int(d.get("student_id")); score=float(d.get("score"))
    if not (0<=score<=100): return jsonify({"ok":False,"error":"Score must be 0-100"}),400
    if g.role=="teacher" and not teacher_can_access(sid,username,subject,class_id,stream_id):
        return jsonify({"ok":False,"error":"Access denied"}),403
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
    sid = g.school_id; d = request.json
    username = g.username
    subject=d.get("subject","").lower().strip()
    class_id=int(d.get("class_id")); stream_id=d.get("stream_id") or None
    student_id=int(d.get("student_id")); test_id=int(d.get("test_id")); score=float(d.get("score"))
    if not (0<=score<=100): return jsonify({"ok":False,"error":"Score must be 0-100"}),400
    if g.role=="teacher" and not teacher_can_access(sid,username,subject,class_id,stream_id):
        return jsonify({"ok":False,"error":"Access denied"}),403
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