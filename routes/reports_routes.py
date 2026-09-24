from flask import Blueprint, request, jsonify, g

from core.db import get_db, to_dict
from core.auth import require_auth, require_role
from core.school import format_student_display_id
from services.grading import get_grade, compute_division_from_finals
from services.scores import (
    get_subjects, get_active_term, get_term_by_id, get_students_in_scope,
    get_class_report_data, _active_subjects_in_scores, get_subject_rank_map,
    compute_student_finals, compute_average_from_finals, _assign_positions,
)

reports_bp = Blueprint("reports", __name__)

# ── REPORT CARD ───────────────────────────────────────────────
@reports_bp.route("/api/report/<int:student_id>", methods=["GET"])
@require_auth
@require_role("parent","admin","teacher")
def api_report(student_id):
    sid = g.school_id
    if g.role == "parent" and g.student_id != student_id:
        return jsonify({"ok":False,"error":"Access denied"}),403
    subjects = get_subjects(sid)
    term_id = request.args.get("term_id")
    con = get_db(); cur = con.cursor()
    cur.execute("""SELECT s.id,s.name,s.class_id,s.stream_id,c.class_name,st.stream_name,s.school_student_no
                   FROM students s JOIN classes c ON s.class_id=c.id
                   LEFT JOIN streams st ON s.stream_id=st.id
                   WHERE s.id=%s AND s.school_id=%s""",(student_id,sid))
    row = cur.fetchone(); student = to_dict(row,cur) if row else None
    cur.close(); con.close()
    if not student: return jsonify({"ok":False,"error":"Student not found"}),404
    student["display_id"] = format_student_display_id(sid, student.pop("school_student_no", None))
    term = get_term_by_id(sid,int(term_id)) if term_id else get_active_term(sid)
    if not term: return jsonify({"ok":False,"error":"No term available"}),400
    tid=term["id"]; ca_count=term["ca_count"]; ca_w=term["ca_weight"]; ex_w=term["exam_weight"]
    class_id=student["class_id"]; stream_id=student["stream_id"]

    class_rows, class_rank_map, stream_rank_map, scores_bulk = get_class_report_data(
        sid, tid, class_id, stream_id, subjects, ca_w, ex_w)
    active_subjects = _active_subjects_in_scores(subjects, scores_bulk)
    subject_rank_maps = {subj: get_subject_rank_map(class_rows, subj) for subj in active_subjects}

    c_entry = class_rank_map.get(student_id)
    c_pos   = c_entry["position"] if c_entry else "-"
    c_total = len(class_rows)
    s_pos = s_total = None
    if stream_id and stream_rank_map is not None:
        s_entry = stream_rank_map.get(student_id)
        s_pos   = s_entry["position"] if s_entry else "-"
        s_total = len(stream_rank_map)

    student_finals = c_entry["finals"] if c_entry else compute_student_finals(scores_bulk, student_id, subjects, ca_w, ex_w)
    avg = c_entry["average"] if c_entry else round(compute_average_from_finals(student_finals), 2)
    student_scores = scores_bulk.get(student_id, {})
    finals_for_division = student_finals  # you already have this dict
    division_points, division = compute_division_from_finals(sid, finals_for_division)

    rows = []
    for subject in active_subjects:
        entry     = student_scores.get(subject, {})
        ca_map    = entry.get("ca", {})
        ca_scores = {f"CA{i}": ca_map.get(f"CA{i}") for i in range(1,ca_count+1)}
        exam_val  = entry.get("exam")
        final_val = student_finals.get(subject)
        subj_pos  = subject_rank_maps[subject].get(student_id, "-") if final_val is not None else "-"
        rows.append({"subject":subject,"ca":ca_scores,"exam":exam_val,
                     "final":round(final_val,1) if final_val is not None else None,
                     "grade":get_grade(sid,final_val) if final_val is not None else "-","position":subj_pos})
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM remarks WHERE school_id=%s AND student_id=%s AND term_id=%s",(sid,student_id,tid))
    rmk_row = cur.fetchone(); rmk = to_dict(rmk_row,cur) if rmk_row else None
    cur.close(); con.close()
    return jsonify({"ok":True,"student":student,"term":term,"rows":rows,
                    "average":avg,"grade":get_grade(sid,avg),
                    "class_position":c_pos,"class_total":c_total,
                    "stream_position":s_pos,"stream_total":s_total,
                    "class_teacher_remark":rmk["class_teacher_remark"] if rmk else "",
                    "head_remark":rmk["head_remark"] if rmk else "",
                    "ca_count":ca_count,"ca_weight":term["ca_weight"],"exam_weight":term["exam_weight"],"division":division,"division_points":division_points})

# ── REMARKS ───────────────────────────────────────────────────
@reports_bp.route("/api/remarks", methods=["POST"])
@require_auth
def api_remarks():
    sid = g.school_id; d = request.json
    username = g.username; role = g.role; is_ct=d.get("is_class_teacher",False)
    student_id=int(d.get("student_id")); remark=d.get("remark","").strip()
    term = get_active_term(sid)
    if not term: return jsonify({"ok":False,"error":"No active term"}),400
    tid=term["id"]
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT class_id FROM students WHERE id=%s AND school_id=%s",(student_id,sid))
    student = cur.fetchone()
    if not student: cur.close(); con.close(); return jsonify({"ok":False,"error":"Student not found"}),404
    if role=="admin": field="head_remark"
    elif role=="teacher" and is_ct:
        cur.execute("SELECT class_id FROM users WHERE username=%s AND school_id=%s AND is_class_teacher=1",(username,sid))
        u = cur.fetchone()
        if not u or u[0]!=student[0]:
            cur.close(); con.close(); return jsonify({"ok":False,"error":"Not your class"}),403
        field="class_teacher_remark"
    else:
        cur.close(); con.close(); return jsonify({"ok":False,"error":"Not allowed"}),403
    cur.execute(f"""INSERT INTO remarks(school_id,student_id,term_id,{field}) VALUES(%s,%s,%s,%s)
                    ON CONFLICT(school_id,student_id,term_id) DO UPDATE SET {field}=EXCLUDED.{field}""",
                (sid,student_id,tid,remark))
    con.commit(); cur.close(); con.close(); return jsonify({"ok":True})

# ── RANKINGS ──────────────────────────────────────────────────
@reports_bp.route("/api/ranking/subject", methods=["GET"])
@require_auth
@require_role("admin","teacher")
def api_subject_ranking():
    sid=g.school_id; subject=request.args.get("subject","").lower()
    class_id=request.args.get("class_id"); stream_id=request.args.get("stream_id") or None
    assess=request.args.get("assess","exam"); term_id=request.args.get("term_id")
    if not term_id:
        term=get_active_term(sid)
        if not term: return jsonify([])
        term_id=term["id"]
    else: term_id=int(term_id)
    if stream_id: stream_id=int(stream_id)
    if class_id:  class_id=int(class_id)
    studs=get_students_in_scope(sid,class_id,stream_id)
    if not studs: return jsonify([])
    student_ids=[s["id"] for s in studs]
    con=get_db(); cur=con.cursor()
    if assess=="exam":
        cur.execute("SELECT student_id,score FROM exam_scores WHERE school_id=%s AND student_id=ANY(%s) AND subject=%s AND term_id=%s",
                    (sid,student_ids,subject,term_id))
    else:
        cur.execute("SELECT student_id,score FROM ca_scores WHERE school_id=%s AND student_id=ANY(%s) AND subject=%s AND ca_name=%s AND term_id=%s",
                    (sid,student_ids,subject,assess,term_id))
    score_map=dict(cur.fetchall()); cur.close(); con.close()
    name_map={s["id"]:s["name"] for s in studs}
    rows=[{"id":stid,"name":name_map[stid],"score":round(sc,2),"grade":get_grade(sid,sc)}
          for stid,sc in score_map.items()]
    _assign_positions(rows,"score"); return jsonify(rows)

