"""
Auth routes: login, school-info lookup (for login branding), setup, password change.
"""
import os
from flask import Blueprint, request, jsonify, g

from core.db import get_db
from core.security import hash_password, verify_password
from core.auth import (
    issue_token, require_auth,
    LOGIN_MAX_ATTEMPTS, _login_attempts_count, _record_login_attempt,
)
from core.school import get_school_id_by_reg_code, is_registration_complete

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/api/login", methods=["POST"])
def api_login():
    d = request.json or {}
    reg_code = (d.get("reg_code") or "").strip()
    u, p = d.get("username","").strip(), d.get("password","")
    if not reg_code: return jsonify({"ok":False,"error":"Enter your school's registration code"}), 400
    if not u or not p: return jsonify({"ok":False,"error":"Enter username and password"}), 400

    identifier = f"{request.remote_addr}:{reg_code.lower()}:{u.lower()}"
    if _login_attempts_count(identifier) >= LOGIN_MAX_ATTEMPTS:
        return jsonify({"ok":False,"error":"Too many login attempts. Please try again in a few minutes."}), 429

    school_id = get_school_id_by_reg_code(reg_code)
    if not school_id:
        _record_login_attempt(identifier)
        return jsonify({"ok":False,"error":"School registration code not recognized"}), 401
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM users WHERE username=%s AND school_id=%s", (u, school_id))
    row = cur.fetchone(); cols = [x[0] for x in cur.description] if cur.description else []
    cur.close(); con.close()
    if not row:
        _record_login_attempt(identifier)
        return jsonify({"ok":False,"error":"Invalid registration code, username or password"}), 401
    user = dict(zip(cols, row))
    if not verify_password(p, user["password"]):
        _record_login_attempt(identifier)
        return jsonify({"ok":False,"error":"Invalid registration code, username or password"}), 401
    token = issue_token(user["username"], school_id, user["role"], user.get("student_id"),
                         bool(user.get("is_class_teacher", 0)), user.get("class_id"), user.get("stream_id"),
                         user.get("token_version") or 0)
    return jsonify({"ok":True,"token":token,"user":{
        "username":             user["username"],
        "role":                 user["role"],
        "school_id":            school_id,
        "is_class_teacher":     bool(user.get("is_class_teacher",0)),
        "class_id":             user.get("class_id"),
        "stream_id":            user.get("stream_id"),
        "must_change_password": bool(user.get("must_change_password",0)),
        "student_id":           user.get("student_id"),
    },"registration_complete": is_registration_complete(school_id)})


@auth_bp.route("/api/school/info", methods=["GET"])
def api_school_info():
    reg_code = request.args.get("reg_code")
    if reg_code:
        school_id = get_school_id_by_reg_code(reg_code)
        if not school_id: return jsonify({})
    else:
        school_id = request.args.get("school_id",1,type=int)
    keys = ["school_name","phone","email","admin_phone","motto","logo_path","registration_complete"]
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT key,value FROM school_config WHERE school_id=%s AND key=ANY(%s)", (school_id, keys))
    rows = cur.fetchall(); cur.close(); con.close()
    return jsonify({r[0]:r[1] for r in rows})


@auth_bp.route("/api/setup_admin", methods=["POST"])
def api_setup_admin():
    d = request.json
    secret = d.get("secret",""); username = d.get("username","").strip(); password = d.get("password","")
    if not os.environ.get("ADMIN_SETUP_SECRET") or secret != os.environ.get("ADMIN_SETUP_SECRET"):
        return jsonify({"ok":False,"error":"Invalid setup secret"}), 403
    if not username or not password: return jsonify({"ok":False,"error":"Username and password required"}), 400
    con = get_db(); cur = con.cursor()
    cur.execute("INSERT INTO schools(id,school_name) VALUES(1,'Default School') ON CONFLICT DO NOTHING")
    cur.execute("SELECT username FROM users WHERE role='admin' AND school_id=1")
    if cur.fetchone():
        cur.close(); con.close()
        return jsonify({"ok":False,"error":"Admin already exists"}), 409
    cur.execute("INSERT INTO users(username,password,role,school_id) VALUES(%s,%s,'admin',1)",
                (username, hash_password(password)))
    for k,v in [("school_name","School Name"),("registration_complete","0"),("phone",""),
                 ("email",""),("motto",""),("logo_path",""),("admin_phone","")]:
        cur.execute("INSERT INTO school_config(school_id,key,value) VALUES(1,%s,%s) ON CONFLICT DO NOTHING",(k,v))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok":True,"school_id":1})


@auth_bp.route("/api/change_password", methods=["POST"])
@require_auth
def api_change_password():
    d = request.json
    username  = g.username
    school_id = g.school_id
    old_pw    = d.get("old_password","")
    new_pw    = d.get("new_password","").strip()
    if len(new_pw) < 6: return jsonify({"ok":False,"error":"Password must be at least 6 characters"}), 400
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT password FROM users WHERE username=%s AND school_id=%s", (username, school_id))
    row = cur.fetchone()
    if not row or not verify_password(old_pw, row[0]):
        cur.close(); con.close(); return jsonify({"ok":False,"error":"Current password is incorrect"}), 401
    cur.execute("UPDATE users SET password=%s,must_change_password=0,token_version=COALESCE(token_version,0)+1 WHERE username=%s AND school_id=%s",
                (hash_password(new_pw), username, school_id))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok":True})