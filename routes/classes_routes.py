"""
Classes & streams CRUD.
"""
import psycopg2
from flask import Blueprint, request, jsonify, g

from core.db import get_db, to_dicts
from core.auth import require_auth, require_role

classes_bp = Blueprint("classes", __name__)


@classes_bp.route("/api/classes", methods=["GET"])
@require_auth
def api_get_classes():
    sid = g.school_id
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM classes WHERE school_id=%s ORDER BY class_name",(sid,))
    classes = to_dicts(cur.fetchall(), cur); result = []
    for c in classes:
        cur.execute("SELECT * FROM streams WHERE school_id=%s AND class_id=%s ORDER BY stream_name",(sid,c["id"]))
        result.append({**c,"streams":to_dicts(cur.fetchall(),cur)})
    cur.close(); con.close(); return jsonify(result)


@classes_bp.route("/api/classes", methods=["POST"])
@require_auth
@require_role("admin")
def api_add_class():
    sid = g.school_id; name = request.json.get("class_name","").strip()
    if not name: return jsonify({"ok":False,"error":"Class name required"}),400
    con = get_db(); cur = con.cursor()
    try:
        cur.execute("INSERT INTO classes(school_id,class_name) VALUES(%s,%s) RETURNING id",(sid,name))
        new_id = cur.fetchone()[0]; con.commit()
    except psycopg2.errors.UniqueViolation:
        con.rollback(); cur.close(); con.close(); return jsonify({"ok":False,"error":"Class already exists"}),409
    cur.close(); con.close(); return jsonify({"ok":True,"id":new_id})


@classes_bp.route("/api/classes/<int:cid>", methods=["DELETE"])
@require_auth
@require_role("admin")
def api_delete_class(cid):
    sid = g.school_id
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM students WHERE school_id=%s AND class_id=%s",(sid,cid))
    if cur.fetchone()[0]>0:
        cur.close(); con.close(); return jsonify({"ok":False,"error":"Students exist in this class"}),409
    cur.execute("DELETE FROM streams WHERE school_id=%s AND class_id=%s",(sid,cid))
    cur.execute("DELETE FROM classes WHERE id=%s AND school_id=%s",(cid,sid))
    con.commit(); cur.close(); con.close(); return jsonify({"ok":True})


@classes_bp.route("/api/classes/<int:cid>/streams", methods=["POST"])
@require_auth
@require_role("admin")
def api_add_stream(cid):
    sid = g.school_id; name = request.json.get("stream_name","").strip()
    if not name: return jsonify({"ok":False,"error":"Stream name required"}),400
    con = get_db(); cur = con.cursor()
    try:
        cur.execute("INSERT INTO streams(school_id,class_id,stream_name) VALUES(%s,%s,%s) RETURNING id",(sid,cid,name))
        new_id = cur.fetchone()[0]; con.commit()
    except psycopg2.errors.UniqueViolation:
        con.rollback(); cur.close(); con.close(); return jsonify({"ok":False,"error":"Stream already exists"}),409
    cur.close(); con.close(); return jsonify({"ok":True,"id":new_id})


@classes_bp.route("/api/streams/<int:stream_id>", methods=["DELETE"])
@require_auth
@require_role("admin")
def api_delete_stream(stream_id):
    sid = g.school_id
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM students WHERE school_id=%s AND stream_id=%s",(sid,stream_id))
    if cur.fetchone()[0]>0:
        cur.close(); con.close(); return jsonify({"ok":False,"error":"Students exist in this stream"}),409
    cur.execute("DELETE FROM streams WHERE id=%s AND school_id=%s",(stream_id,sid))
    con.commit(); cur.close(); con.close(); return jsonify({"ok":True})