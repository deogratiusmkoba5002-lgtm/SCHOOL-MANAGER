"""
Teacher accounts, class-teacher assignment, subject assignment.
"""
import psycopg2
from flask import Blueprint, request, jsonify, g

from core.db import get_db, to_dicts
from core.auth import require_auth, require_role
from core.security import hash_password

teachers_bp = Blueprint("teachers", __name__)


@teachers_bp.route("/api/teachers", methods=["GET"])
@require_auth
def api_get_teachers():
    sid = g.school_id
    con = get_db(); cur = con.cursor()
    cur.execute("""SELECT u.username,u.is_class_teacher,u.class_id,u.stream_id,u.must_change_password,
                          c.class_name,st.stream_name
                   FROM users u
                   LEFT JOIN classes c ON u.class_id=c.id AND c.school_id=%s
                   LEFT JOIN streams st ON u.stream_id=st.id
                   WHERE u.role='teacher' AND u.school_id=%s ORDER BY u.username""",(sid,sid))
    teachers = to_dicts(cur.fetchall(),cur); result=[]
    for t in teachers:
        cur.execute("""SELECT sa.subject,sa.class_id,sa.stream_id,c.class_name,st.stream_name
                       FROM subject_assignments sa JOIN classes c ON sa.class_id=c.id
                       LEFT JOIN streams st ON sa.stream_id=st.id
                       WHERE sa.school_id=%s AND sa.username=%s""",(sid,t["username"]))
        result.append({**t,"assignments":to_dicts(cur.fetchall(),cur)})
    cur.close(); con.close(); return jsonify(result)


@teachers_bp.route("/api/teachers", methods=["POST"])
@require_auth
@require_role("admin")
def api_create_teacher():
    sid = g.school_id; d = request.json
    username=d.get("username","").strip(); password=d.get("password","")
    if not username or not password: return jsonify({"ok":False,"error":"Username and password required"}),400
    con = get_db(); cur = con.cursor()
    try:
        cur.execute("INSERT INTO users(username,password,role,school_id,must_change_password) VALUES(%s,%s,'teacher',%s,1)",
                    (username,hash_password(password),sid))
        con.commit()
    except psycopg2.errors.UniqueViolation:
        con.rollback(); cur.close(); con.close()
        return jsonify({"ok":False,"error":"Username already exists"}),409
    cur.close(); con.close(); return jsonify({"ok":True})


@teachers_bp.route("/api/teachers/<username>", methods=["DELETE"])
@require_auth
@require_role("admin")
def api_delete_teacher(username):
    sid = g.school_id
    con = get_db(); cur = con.cursor()
    cur.execute("DELETE FROM subject_assignments WHERE school_id=%s AND username=%s",(sid,username))
    cur.execute("DELETE FROM users WHERE username=%s AND role='teacher' AND school_id=%s",(username,sid))
    con.commit(); cur.close(); con.close(); return jsonify({"ok":True})


@teachers_bp.route("/api/teachers/<username>/class_teacher", methods=["POST"])
@require_auth
@require_role("admin")
def api_set_class_teacher(username):
    sid = g.school_id; d = request.json
    is_ct=bool(d.get("is_class_teacher",False)); class_id=d.get("class_id") or None; stream_id=d.get("stream_id") or None
    if is_ct and not class_id: return jsonify({"ok":False,"error":"Class required"}),400
    con = get_db(); cur = con.cursor()
    cur.execute("UPDATE users SET is_class_teacher=%s,class_id=%s,stream_id=%s WHERE username=%s AND school_id=%s AND role='teacher'",
                (1 if is_ct else 0, class_id if is_ct else None, stream_id if is_ct else None, username, sid))
    con.commit(); cur.close(); con.close(); return jsonify({"ok":True})


@teachers_bp.route("/api/assign_teacher", methods=["POST"])
@require_auth
@require_role("admin")
def api_assign_teacher():
    sid = g.school_id; d = request.json
    username=d.get("username",""); subject=d.get("subject","").lower().strip()
    class_id=d.get("class_id"); stream_id=d.get("stream_id") or None
    con = get_db(); cur = con.cursor()
    try:
        cur.execute("INSERT INTO subject_assignments(school_id,username,subject,class_id,stream_id) VALUES(%s,%s,%s,%s,%s)",
                    (sid,username,subject,class_id,stream_id))
        con.commit()
    except psycopg2.errors.UniqueViolation:
        con.rollback(); cur.close(); con.close(); return jsonify({"ok":False,"error":"Already assigned"}),409
    cur.close(); con.close(); return jsonify({"ok":True})


@teachers_bp.route("/api/unassign_teacher", methods=["POST"])
@require_auth
@require_role("admin")
def api_unassign_teacher():
    sid = g.school_id; d = request.json
    username=d.get("username",""); subject=d.get("subject","").lower()
    class_id=d.get("class_id"); stream_id=d.get("stream_id") or None
    con = get_db(); cur = con.cursor()
    if stream_id:
        cur.execute("DELETE FROM subject_assignments WHERE school_id=%s AND username=%s AND subject=%s AND class_id=%s AND stream_id=%s",
                    (sid,username,subject,class_id,stream_id))
    else:
        cur.execute("DELETE FROM subject_assignments WHERE school_id=%s AND username=%s AND subject=%s AND class_id=%s AND stream_id IS NULL",
                    (sid,username,subject,class_id))
    con.commit(); cur.close(); con.close(); return jsonify({"ok":True})