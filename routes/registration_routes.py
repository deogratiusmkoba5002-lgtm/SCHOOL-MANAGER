"""
School self-registration route (the multi-step wizard in register.html).
"""
import base64, json
from flask import Blueprint, request, jsonify

from core.db import get_db
from core.security import hash_password
from core.school import valid_reg_code, get_school_id_by_reg_code, generate_unique_reg_code
from config import ALLOWED_LOGO_EXT, _mime_for_ext

registration_bp = Blueprint("registration", __name__)


@registration_bp.route("/api/register/school", methods=["POST"])
def api_register_school():
    data         = request.form
    school_name  = data.get("school_name","").strip()
    admin_user   = data.get("admin_username","").strip()
    admin_pass   = data.get("admin_password","").strip()
    phone        = data.get("phone","").strip()
    email        = data.get("email","").strip()
    admin_phone  = data.get("admin_phone","").strip()
    motto        = data.get("motto","").strip()
    reg_code     = data.get("reg_code","").strip()
    agree_terms  = data.get("agree_terms","").strip()
    if not school_name: return jsonify({"ok":False,"error":"School name required"}), 400
    if not admin_user or not admin_pass: return jsonify({"ok":False,"error":"Admin username and password required"}), 400
    if agree_terms != "1":
        return jsonify({"ok":False,"error":"You must agree to the Terms & Conditions and Privacy Policy"}), 400
    if reg_code:
        if not valid_reg_code(reg_code):
            return jsonify({"ok":False,"error":"Registration code must be 3-32 characters: letters, numbers, underscore or hyphen only"}), 400
        if get_school_id_by_reg_code(reg_code):
            return jsonify({"ok":False,"error":f"Registration code '{reg_code}' is already taken by another school. Please choose a different one."}), 409
    else:
        reg_code = generate_unique_reg_code(school_name)
    logo_b64 = ""; logo_mime = ""
    if "logo" in request.files:
        f = request.files["logo"]
        if f and f.filename:
            ext = f.filename.rsplit(".",1)[-1].lower() if "." in f.filename else ""
            if ext not in ALLOWED_LOGO_EXT: return jsonify({"ok":False,"error":"Logo must be an image"}), 400
            raw = f.read()
            if len(raw) > 2*1024*1024:
                return jsonify({"ok":False,"error":"Logo must be smaller than 2MB"}), 400
            logo_mime = _mime_for_ext(ext)
            logo_b64  = base64.b64encode(raw).decode("ascii")
    try:
        classes_data  = json.loads(data.get("classes","[]"))
        subjects_data = json.loads(data.get("subjects","[]"))
        grades_data   = json.loads(data.get("grades","[]"))
    except Exception as e:
        return jsonify({"ok":False,"error":f"Invalid JSON: {e}"}), 400
    if not subjects_data: return jsonify({"ok":False,"error":"At least one subject required"}), 400
    if not grades_data:   return jsonify({"ok":False,"error":"At least one grade rule required"}), 400
    con = get_db(); cur = con.cursor()
    try:
        cur.execute("""INSERT INTO schools(school_name,reg_code,terms_accepted_at,terms_accepted_by)
                       VALUES(%s,%s,NOW(),%s) RETURNING id""", (school_name, reg_code, admin_user))
        school_id = cur.fetchone()[0]
        cur.execute("INSERT INTO users(username,password,role,school_id) VALUES(%s,%s,'admin',%s)",
                    (admin_user, hash_password(admin_pass), school_id))
        logo_path = f"api/logo/{school_id}" if logo_b64 else ""
        cfg = {"school_name":school_name,"phone":phone,"email":email,"admin_phone":admin_phone,
               "motto":motto,"logo_path":logo_path,"registration_complete":"1"}
        if logo_b64:
            cfg["logo_data"] = logo_b64
            cfg["logo_mime"] = logo_mime
        for k,v in cfg.items():
            cur.execute("INSERT INTO school_config(school_id,key,value) VALUES(%s,%s,%s) ON CONFLICT(school_id,key) DO UPDATE SET value=EXCLUDED.value",
                        (school_id, k, v))
        for i,s in enumerate(subjects_data):
            name = s.get("name","").strip().lower(); ab = s.get("abbreviation","").strip().upper()
            if name:
                cur.execute("INSERT INTO school_subjects(school_id,name,abbreviation,sort_order) VALUES(%s,%s,%s,%s) ON CONFLICT(school_id,name) DO UPDATE SET abbreviation=EXCLUDED.abbreviation",
                            (school_id, name, ab, i))
        for i,g in enumerate(grades_data):
            cur.execute("INSERT INTO grade_config(school_id,min_score,max_score,grade,sort_order) VALUES(%s,%s,%s,%s,%s)",
                        (school_id, float(g["min_score"]), float(g["max_score"]), str(g["grade"]).strip(), i))
        for cls in classes_data:
            cname = cls.get("name","").strip()
            if not cname: continue
            cur.execute("INSERT INTO classes(school_id,class_name) VALUES(%s,%s) ON CONFLICT(school_id,class_name) DO NOTHING RETURNING id",
                        (school_id, cname))
            row = cur.fetchone()
            if not row:
                cur.execute("SELECT id FROM classes WHERE school_id=%s AND class_name=%s", (school_id, cname))
                row = cur.fetchone()
            cid = row[0]
            for sname in cls.get("streams",[]):
                sname = sname.strip()
                if sname:
                    cur.execute("INSERT INTO streams(school_id,class_id,stream_name) VALUES(%s,%s,%s) ON CONFLICT(class_id,stream_name) DO NOTHING",
                                (school_id, cid, sname))
        con.commit()
    except Exception as e:
        con.rollback(); cur.close(); con.close()
        return jsonify({"ok":False,"error":str(e)}), 500
    cur.close(); con.close()
    return jsonify({"ok":True,"school_id":school_id})