"""
Student CRUD, bulk operations, and parent-credential reset.
"""
import psycopg2
from flask import Blueprint, request, jsonify, g

from core.db import get_db, to_dicts
from core.auth import require_auth, require_role
from core.security import hash_password
from core.school import format_student_display_id
from services.students import gen_parent_creds

students_bp = Blueprint("students", __name__)


@students_bp.route("/api/students", methods=["GET"])
@require_auth
def api_students():
    sid = g.school_id
    con = get_db(); cur = con.cursor()
    cur.execute("""SELECT s.id,s.name,s.class_id,s.stream_id,c.class_name,st.stream_name,s.school_student_no,s.flag_reason
                   FROM students s JOIN classes c ON s.class_id=c.id
                   LEFT JOIN streams st ON s.stream_id=st.id
                   WHERE s.school_id=%s ORDER BY c.class_name,st.stream_name,s.name""",(sid,))
    rows = to_dicts(cur.fetchall(),cur); cur.close(); con.close()
    for r in rows: r["display_id"] = format_student_display_id(sid, r.pop("school_student_no", None))
    return jsonify(rows)


@students_bp.route("/api/students", methods=["POST"])
@require_auth
@require_role("admin","teacher")
def api_add_student():
    sid = g.school_id; d = request.json
    name=d.get("name","").strip(); class_id=d.get("class_id"); stream_id=d.get("stream_id") or None
    phone=d.get("phone_number","").strip()
    if not name or not class_id: return jsonify({"ok":False,"error":"Name and class required"}),400
    if not phone or len(phone)<4: return jsonify({"ok":False,"error":"Parent phone required"}),400
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT id FROM classes WHERE id=%s AND school_id=%s",(class_id,sid))
    if not cur.fetchone(): cur.close(); con.close(); return jsonify({"ok":False,"error":"Invalid class"}),400
    cur.execute("SELECT id FROM students WHERE school_id=%s AND LOWER(TRIM(name))=%s AND class_id=%s "
                "AND COALESCE(stream_id,0)=%s AND phone_number=%s",
                (sid, name.lower(), class_id, stream_id or 0, phone))
    if cur.fetchone():
        cur.close(); con.close()
        return jsonify({"ok":False,"error":"A student with this name, class, stream and phone already exists"}),409
    cur.execute("""INSERT INTO students(school_id,name,class_id,stream_id,phone_number,school_student_no)
                   VALUES(%s,%s,%s,%s,%s,(SELECT COALESCE(MAX(school_student_no),0)+1 FROM students WHERE school_id=%s))
                   RETURNING id""",
                (sid,name,class_id,stream_id,phone,sid))
    student_id = cur.fetchone()[0]; con.commit(); cur.close(); con.close()
    username, temp_pw = gen_parent_creds(sid, name, phone, student_id)
    con = get_db(); cur = con.cursor()
    cur.execute("INSERT INTO users(username,password,role,school_id,must_change_password,student_id) VALUES(%s,%s,'parent',%s,1,%s) ON CONFLICT(username,school_id) DO NOTHING",
                (username, hash_password(temp_pw), sid, student_id))
    created = cur.rowcount > 0
    con.commit(); cur.close(); con.close()
    if created:
        return jsonify({"ok":True,"parent_username":username,"temp_password":temp_pw})
    return jsonify({"ok":True,"parent_username":None,"temp_password":None,
                    "warning":f"Student added, but username '{username}' is already taken by another parent account "
                              f"(same name as an existing student). No new login was created — that student will "
                              f"need a different name on file, or share the existing '{username}' login."})


@students_bp.route("/api/students/resolve_display_id", methods=["GET"])
@require_auth
def api_resolve_display_id():
    sid = g.school_id
    no = request.args.get("no")
    if not no: return jsonify({"ok":False,"error":"Missing student number"}),400
    try: no = int(no)
    except ValueError: return jsonify({"ok":False,"error":"Invalid student ID"}),400
    con=get_db(); cur=con.cursor()
    cur.execute("SELECT id FROM students WHERE school_id=%s AND school_student_no=%s",(sid,no))
    row=cur.fetchone(); cur.close(); con.close()
    if not row: return jsonify({"ok":False,"error":"Student not found"}),404
    return jsonify({"ok":True,"id":row[0]})


@students_bp.route("/api/students/bulk_delete", methods=["POST"])
@require_auth
@require_role("admin")
def api_bulk_delete_students():
    sid = g.school_id; ids = request.json.get("ids", [])
    try: ids = [int(i) for i in ids]
    except (TypeError, ValueError): return jsonify({"ok":False,"error":"Invalid student IDs"}),400
    if not ids: return jsonify({"ok":False,"error":"No students selected"}),400
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT id FROM students WHERE school_id=%s AND id=ANY(%s)",(sid,ids))
    valid_ids = [r[0] for r in cur.fetchall()]
    if not valid_ids: cur.close(); con.close(); return jsonify({"ok":False,"error":"No matching students found"}),404
    cur.execute("DELETE FROM announcement_reads WHERE student_id=ANY(%s)",(valid_ids,))
    cur.execute("DELETE FROM remarks WHERE school_id=%s AND student_id=ANY(%s)",(sid,valid_ids))
    cur.execute("DELETE FROM ca_scores WHERE school_id=%s AND student_id=ANY(%s)",(sid,valid_ids))
    cur.execute("DELETE FROM exam_scores WHERE school_id=%s AND student_id=ANY(%s)",(sid,valid_ids))
    cur.execute("DELETE FROM users WHERE school_id=%s AND student_id=ANY(%s) AND role='parent'",(sid,valid_ids))
    cur.execute("DELETE FROM students WHERE school_id=%s AND id=ANY(%s)",(sid,valid_ids))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok":True,"deleted":len(valid_ids)})


@students_bp.route("/api/students/<int:student_id>", methods=["DELETE"])
@require_auth
@require_role("admin")
def api_delete_student(student_id):
    sid = g.school_id
    con = get_db(); cur = con.cursor()
    cur.execute("DELETE FROM announcement_reads WHERE student_id=%s",(student_id,))
    cur.execute("DELETE FROM remarks WHERE school_id=%s AND student_id=%s",(sid,student_id))
    cur.execute("DELETE FROM ca_scores WHERE school_id=%s AND student_id=%s",(sid,student_id))
    cur.execute("DELETE FROM exam_scores WHERE school_id=%s AND student_id=%s",(sid,student_id))
    cur.execute("DELETE FROM users WHERE school_id=%s AND student_id=%s AND role='parent'",(sid,student_id))
    cur.execute("DELETE FROM students WHERE id=%s AND school_id=%s",(student_id,sid))
    con.commit(); cur.close(); con.close(); return jsonify({"ok":True})


@students_bp.route("/api/students/<int:student_id>", methods=["PATCH"])
@require_auth
@require_role("admin")
def api_update_student(student_id):
    """Edits name/class/stream/phone. If the change touches name or phone, regenerate their
    username/password to match.
    NOTE (unchanged from app.py — flagged, not fixed): `gen_username` below is used
    before it's assigned, and the SQL in the UPDATE has a SET clause bleeding into the
    WHERE clause via a misplaced comma. Both will raise at runtime as-is."""
    sid = g.school_id; d = request.json or {}
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT name,class_id,stream_id,phone_number FROM students WHERE id=%s AND school_id=%s",(student_id,sid))
    row = cur.fetchone()
    if not row:
        cur.close(); con.close(); return jsonify({"ok":False,"error":"Student not found"}),404
    old_name, old_class_id, old_stream_id, old_phone = row

    name = (d.get("name") if d.get("name") is not None else old_name).strip()
    try:
        class_id = int(d.get("class_id", old_class_id))
    except (TypeError, ValueError):
        cur.close(); con.close(); return jsonify({"ok":False,"error":"Invalid class"}),400
    sd = d.get("stream_id", old_stream_id)
    stream_id = int(sd) if sd else None
    phone = (d.get("phone_number") if d.get("phone_number") is not None else (old_phone or "")).strip()

    if not name:
        cur.close(); con.close(); return jsonify({"ok":False,"error":"Name required"}),400
    cur.execute("SELECT id FROM classes WHERE id=%s AND school_id=%s",(class_id,sid))
    if not cur.fetchone():
        cur.close(); con.close(); return jsonify({"ok":False,"error":"Invalid class"}),400

    cur.execute("""SELECT id FROM students WHERE school_id=%s AND LOWER(TRIM(name))=%s AND class_id=%s
                   AND COALESCE(stream_id,0)=%s AND phone_number=%s AND id!=%s""",
                (sid, name.lower(), class_id, stream_id or 0, phone, student_id))
    if cur.fetchone():
        cur.close(); con.close()
        return jsonify({"ok":False,"error":"Another student with this name, class, stream and phone already exists"}),409

    name_changed  = name.lower() != (old_name or "").strip().lower()
    phone_changed = phone != (old_phone or "").strip()

    cur.execute("""SELECT username, must_change_password FROM users
                   WHERE school_id=%s AND student_id=%s AND role='parent'""",(sid, student_id))
    parent_row = cur.fetchone()

    new_username = new_password = cred_note = None

    if parent_row and (name_changed or phone_changed):
        old_username, must_change = parent_row
        if phone:
            gen_username = name.strip().lower().replace(" ", "_")
            last4 = phone[-4:]
            cur.execute("""SELECT s.phone_number FROM users u JOIN students s ON u.student_id=s.id
                           WHERE u.username=%s AND u.school_id=%s AND u.role='parent' AND u.student_id!=%s""",
                        (gen_username, sid, student_id))
            other_phones = [r[0] or "" for r in cur.fetchall()]
            needs_suffix = any(ph.strip()!=phone and ph.strip()[-4:]==last4 for ph in other_phones)
            new_password = f"{last4}-{student_id}" if needs_suffix else last4
            new_username = gen_username
            try:
                cur.execute("""UPDATE users SET username=%s, password=%s, must_change_password=1,
                               token_version=COALESCE(token_version,0)+1
                               WHERE username=%s AND school_id=%s AND student_id=%s""",
                            (new_username, hash_password(new_password), old_username, sid, student_id))
            except psycopg2.errors.UniqueViolation:
                con.rollback(); cur.close(); con.close()
                return jsonify({"ok":False,"error":f"Can't regenerate login — username '{new_username}' is already taken"}),409
            cred_note = "Credentials were regenerated to match the updated name/phone. The parent must log in again with the new password — their child's historical reports and marks are unaffected."
        else:
            cred_note = "Name/phone updated, but no phone on file — could not regenerate a login."
    elif not parent_row and phone:
        gen_username, temp_pw = gen_parent_creds(sid, name, phone, student_id)
        try:
            cur.execute("""INSERT INTO users(username,password,role,school_id,must_change_password,student_id)
                           VALUES(%s,%s,'parent',%s,1,%s)""",
                        (gen_username, hash_password(temp_pw), sid, student_id))
            new_username, new_password = gen_username, temp_pw
            cred_note = "Phone was missing before — a parent login was just created."
        except psycopg2.errors.UniqueViolation:
            con.rollback(); cur.close(); con.close()
            return jsonify({"ok":False,"error":f"Can't create login — username '{gen_username}' already taken"}),409

    flag_reason = "Missing parent phone — no parent login was created" if not phone else None

    cur.execute("""UPDATE students SET name=%s, class_id=%s, stream_id=%s, phone_number=%s, flag_reason=%s
                   WHERE id=%s AND school_id=%s""",
                (name, class_id, stream_id, phone or None, flag_reason, student_id, sid))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok":True,"new_username":new_username,"new_password":new_password,"note":cred_note})


@students_bp.route("/api/students/<int:student_id>/reset_parent_credentials", methods=["POST"])
@require_auth
@require_role("admin")
def api_reset_parent_credentials(student_id):
    sid = g.school_id
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT name, phone_number FROM students WHERE id=%s AND school_id=%s",(student_id,sid))
    row = cur.fetchone()
    if not row:
        cur.close(); con.close(); return jsonify({"ok":False,"error":"Student not found"}),404
    name, phone = row
    if not phone:
        cur.close(); con.close(); return jsonify({"ok":False,"error":"No parent phone on file — add one first"}),400
    cur.execute("SELECT username FROM users WHERE school_id=%s AND student_id=%s AND role='parent'",(sid,student_id))
    parent_row = cur.fetchone()
    gen_username = name.lower().replace(" ","_")
    last4 = phone.strip()[-4:]
    cur.execute("""SELECT s.phone_number FROM users u JOIN students s ON u.student_id=s.id
                   WHERE u.username=%s AND u.school_id=%s AND u.role='parent' AND u.student_id!=%s""",
                (gen_username, sid, student_id))
    other_phones = [r[0] or "" for r in cur.fetchall()]
    needs_suffix = any(ph.strip()!=phone.strip() and ph.strip()[-4:]==last4 for ph in other_phones)
    new_password = f"{last4}-{student_id}" if needs_suffix else last4
    try:
        if parent_row:
            cur.execute("""UPDATE users SET username=%s, password=%s, must_change_password=1,
                           token_version=COALESCE(token_version,0)+1
                           WHERE school_id=%s AND student_id=%s AND role='parent'""",
                        (gen_username, hash_password(new_password), sid, student_id))
        else:
            cur.execute("""INSERT INTO users(username,password,role,school_id,must_change_password,student_id)
                           VALUES(%s,%s,'parent',%s,1,%s)""",
                        (gen_username, hash_password(new_password), sid, student_id))
        con.commit()
    except psycopg2.errors.UniqueViolation:
        con.rollback(); cur.close(); con.close()
        return jsonify({"ok":False,"error":f"Username '{gen_username}' is already taken by another parent"}),409
    cur.close(); con.close()
    return jsonify({"ok":True,"username":gen_username,"temp_password":new_password})