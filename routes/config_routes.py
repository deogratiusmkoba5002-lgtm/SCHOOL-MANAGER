import base64
from flask import Blueprint, request, jsonify, g

from config import _FALLBACK_SUBJECTS, _FALLBACK_ABBR, ALLOWED_LOGO_EXT, _mime_for_ext
from core.db import get_db, to_dicts
from core.auth import require_auth, require_role
from core.school import get_config_val, set_config_val, valid_reg_code
from services.grading import (get_grade_rules, get_school_grading_settings,
                              get_principal_subjects, get_noncredit_subjects)
from services.scores import get_subjects, get_subject_map, get_active_term

config_bp = Blueprint("config", __name__)


@config_bp.route("/api/subjects", methods=["GET"])
@require_auth
def api_get_subjects():
    sid = g.school_id
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT id,name,abbreviation,sort_order FROM school_subjects WHERE school_id=%s ORDER BY sort_order,name",(sid,))
    rows = to_dicts(cur.fetchall(), cur); cur.close(); con.close()
    if rows: return jsonify(rows)
    return jsonify([{"id":i,"name":n,"abbreviation":_FALLBACK_ABBR.get(n,n[:4].upper()),"sort_order":i} for i,n in enumerate(_FALLBACK_SUBJECTS)])

@config_bp.route("/api/subjects", methods=["POST"])
@require_auth
@require_role("admin")
def api_save_subjects():
    sid = g.school_id; subjects = request.json.get("subjects",[])
    con = get_db(); cur = con.cursor()
    cur.execute("DELETE FROM school_subjects WHERE school_id=%s",(sid,))
    for i,s in enumerate(subjects):
        name=s.get("name","").strip().lower(); ab=s.get("abbreviation","").strip().upper()
        if name:
            cur.execute("INSERT INTO school_subjects(school_id,name,abbreviation,sort_order) VALUES(%s,%s,%s,%s)",(sid,name,ab,i))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok":True})

@config_bp.route("/api/grades", methods=["POST"])
@require_auth
@require_role("admin")
def api_save_grades():
    sid = g.school_id; grades = request.json.get("grades",[])
    con = get_db(); cur = con.cursor()
    cur.execute("DELETE FROM grade_config WHERE school_id=%s",(sid,))
    for i,gr in enumerate(grades):
        cur.execute("INSERT INTO grade_config(school_id,min_score,max_score,grade,sort_order) VALUES(%s,%s,%s,%s,%s)",
                    (sid,float(gr["min_score"]),float(gr["max_score"]),str(gr["grade"]).strip(),i))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok":True})

@config_bp.route("/api/config/grading_system", methods=["GET"])
@require_auth
def api_get_grading_system():
    sid = g.school_id
    s = get_school_grading_settings(sid)
    s["principal_subjects"] = get_principal_subjects(sid)
    s["non_credit_subjects"] = get_noncredit_subjects(sid)
    return jsonify(s)

@config_bp.route("/api/config/grading_system", methods=["POST"])
@require_auth
@require_role("admin")
def api_set_grading_system():
    sid = g.school_id; d = request.json or {}
    grading_system = d.get("grading_system")
    division_source = d.get("division_source")
    if grading_system not in ("o_level","a_level"):
        return jsonify({"ok":False,"error":"Invalid grading system"}),400
    if division_source not in ("school","necta"):
        return jsonify({"ok":False,"error":"Invalid division source"}),400
    con=get_db(); cur=con.cursor()
    cur.execute("UPDATE schools SET grading_system=%s, division_source=%s WHERE id=%s",
                (grading_system, division_source, sid))
    con.commit(); cur.close(); con.close()
    principal = d.get("principal_subjects")
    if grading_system=="a_level" and isinstance(principal, list):
        con=get_db(); cur=con.cursor()
        cur.execute("UPDATE school_subjects SET is_principal=0 WHERE school_id=%s",(sid,))
        for name in principal:
            cur.execute("UPDATE school_subjects SET is_principal=1 WHERE school_id=%s AND name=%s",(sid,name.strip().lower()))
        con.commit(); cur.close(); con.close()
    noncredit = d.get("non_credit_subjects")
    if isinstance(noncredit, list):
        con=get_db(); cur=con.cursor()
        cur.execute("UPDATE school_subjects SET is_noncredit=0 WHERE school_id=%s",(sid,))
        for name in noncredit:
            cur.execute("UPDATE school_subjects SET is_noncredit=1 WHERE school_id=%s AND name=%s",(sid,name.strip().lower()))
        con.commit(); cur.close(); con.close()
    return jsonify({"ok":True})


# ── CONFIG ─────────────────────────────────────────────────────
@config_bp.route("/api/config", methods=["GET"])
@require_auth
def api_config():
    sid = g.school_id; term = get_active_term(sid)
    subjects = get_subjects(sid); subj_map = get_subject_map(sid)
    info = {k: get_config_val(sid,k,"") for k in ["school_name","phone","email","admin_phone","motto","logo_path"]}
    return jsonify({"allowed_subjects":subjects,"subject_abbr":subj_map,"active_term":term,
                    "ca_count":term["ca_count"] if term else 2,"school_name":info.get("school_name","School Name"),
                    "school_info":info,"grade_rules":get_grade_rules(sid)})

@config_bp.route("/api/config/school_name", methods=["POST"])
@require_auth
@require_role("admin")
def api_set_school_name():
    sid = g.school_id; name = request.json.get("school_name","").strip()
    if not name: return jsonify({"ok":False,"error":"Name cannot be empty"}),400
    set_config_val(sid,"school_name",name); return jsonify({"ok":True})

@config_bp.route("/api/config/reg_code", methods=["GET"])
@require_auth
@require_role("admin")
def api_get_reg_code():
    sid = g.school_id
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT reg_code FROM schools WHERE id=%s", (sid,))
    row = cur.fetchone(); cur.close(); con.close()
    return jsonify({"reg_code": row[0] if row else ""})

@config_bp.route("/api/config/reg_code", methods=["POST"])
@require_auth
@require_role("admin")
def api_set_reg_code():
    sid = g.school_id
    new_code = ((request.json or {}).get("reg_code") or "").strip()
    if not valid_reg_code(new_code):
        return jsonify({"ok":False,"error":"Registration code must be 3-32 characters: letters, numbers, underscore or hyphen only"}), 400
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT id FROM schools WHERE LOWER(reg_code)=LOWER(%s) AND id!=%s", (new_code, sid))
    if cur.fetchone():
        cur.close(); con.close()
        return jsonify({"ok":False,"error":"That registration code is already taken by another school. Please choose a different one."}), 409
    cur.execute("UPDATE schools SET reg_code=%s WHERE id=%s", (new_code, sid))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok":True,"reg_code":new_code})

@config_bp.route("/api/config/school_info", methods=["POST"])
@require_auth
@require_role("admin")
def api_set_school_info():
    sid = g.school_id; d = request.json
    for key in ["school_name","phone","email","admin_phone","motto"]:
        val = d.get(key)
        if val is not None: set_config_val(sid, key, val.strip())
    return jsonify({"ok":True})

@config_bp.route("/api/config/logo", methods=["POST"])
@require_auth
@require_role("admin")
def api_upload_logo():
    school_id = g.school_id
    if "logo" not in request.files:
        return jsonify({"ok":False,"error":"No logo file uploaded"}), 400
    f = request.files["logo"]
    if not f or not f.filename:
        return jsonify({"ok":False,"error":"No logo file uploaded"}), 400
    ext = f.filename.rsplit(".",1)[-1].lower() if "." in f.filename else ""
    if ext not in ALLOWED_LOGO_EXT:
        return jsonify({"ok":False,"error":"Logo must be an image (png, jpg, jpeg, gif, webp, svg)"}), 400
    raw = f.read()
    if len(raw) > 2*1024*1024:
        return jsonify({"ok":False,"error":"Logo must be smaller than 2MB"}), 400
    logo_mime = _mime_for_ext(ext)
    logo_b64  = base64.b64encode(raw).decode("ascii")
    set_config_val(school_id, "logo_data", logo_b64)
    set_config_val(school_id, "logo_mime", logo_mime)
    logo_path = f"api/logo/{school_id}"
    set_config_val(school_id, "logo_path", logo_path)
    return jsonify({"ok":True,"logo_path":logo_path})

@config_bp.route("/api/grades", methods=["GET"])
@require_auth
def api_get_grades():
    return jsonify(get_grade_rules(g.school_id))