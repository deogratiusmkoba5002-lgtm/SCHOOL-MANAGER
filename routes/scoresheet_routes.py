from flask import Blueprint, request, jsonify, g

from core.db import get_db
from core.auth import require_auth, require_role
from services.grading import (get_grade_rules, get_school_grading_settings, get_necta_grades,
                              grade_and_points_for_score, compute_division_from_finals)
from services.scores import (get_subjects, get_active_term, get_term_by_id,
                             get_students_in_scope, _assign_positions)

scoresheet_bp = Blueprint("scoresheet", __name__)

# ── SCORE SHEETS ──────────────────────────────────────────────
@scoresheet_bp.route("/api/scoresheet", methods=["GET"])
@require_auth
@require_role("admin","teacher")
def api_scoresheet():
    sid=g.school_id; subjects=get_subjects(sid)
    mode=request.args.get("mode","ca"); class_id=request.args.get("class_id")
    stream_id=request.args.get("stream_id") or None; ca_name=request.args.get("ca_name","CA1")
    term_id=request.args.get("term_id")
    sheet_type=request.args.get("sheet_type","marks")  # "marks" or "grade"
    grading_system=request.args.get("grading_system") or None
    division_source=request.args.get("division_source") or None
    noncredit_param=request.args.get("noncredit","")
    noncredit_override=[x.strip().lower() for x in noncredit_param.split(",") if x.strip()] if noncredit_param else None
    if not term_id:
        term=get_active_term(sid)
        if not term: return jsonify({"subjects":[],"results":[]})
        term_id=term["id"]
    else: term_id=int(term_id)
    if class_id:  class_id=int(class_id)
    if stream_id: stream_id=int(stream_id)

    studs=get_students_in_scope(sid,class_id,stream_id)
    if not studs:
        return jsonify({"subjects":subjects,"results":[],"sheet_type":sheet_type})
    student_ids=[s["id"] for s in studs]

    con=get_db(); cur=con.cursor()
    ca_scores={}; exam_scores={}; ca_avgs={}; term=None
    if mode=="ca":
        cur.execute("""SELECT student_id,subject,score FROM ca_scores
                       WHERE school_id=%s AND term_id=%s AND ca_name=%s AND student_id=ANY(%s)""",
                    (sid,term_id,ca_name,student_ids))
        for student_id,subject,score in cur.fetchall(): ca_scores[(student_id,subject)]=score
    elif mode=="exam":
        cur.execute("""SELECT student_id,subject,score FROM exam_scores
                       WHERE school_id=%s AND term_id=%s AND student_id=ANY(%s)""",
                    (sid,term_id,student_ids))
        for student_id,subject,score in cur.fetchall(): exam_scores[(student_id,subject)]=score
    elif mode=="test":
        test_id = int(request.args.get("test_id"))
        cur.execute("""SELECT student_id,subject,score FROM test_scores
                    WHERE school_id=%s AND term_id=%s AND test_id=%s AND student_id=ANY(%s)""",
                    (sid,term_id,test_id,student_ids))
        for student_id,subject,score in cur.fetchall(): exam_scores[(student_id,subject)]=score

    elif mode=="terminal":
        term=get_term_by_id(sid,term_id)
        if not term:
            cur.close(); con.close()
            return jsonify({"subjects":subjects,"results":[],"sheet_type":sheet_type})
        cur.execute("""SELECT student_id,subject,score FROM exam_scores
                       WHERE school_id=%s AND term_id=%s AND student_id=ANY(%s)""",
                    (sid,term_id,student_ids))
        for student_id,subject,score in cur.fetchall(): exam_scores[(student_id,subject)]=score
        cur.execute("""SELECT student_id,subject,AVG(score) FROM ca_scores
                       WHERE school_id=%s AND term_id=%s AND student_id=ANY(%s)
                       GROUP BY student_id,subject""",
                    (sid,term_id,student_ids))
        for student_id,subject,avg_score in cur.fetchall(): ca_avgs[(student_id,subject)]=float(avg_score)
    cur.close(); con.close()

    def score_for(stid, subject):
        if mode=="ca": return ca_scores.get((stid,subject))
        if mode in ("exam","test"): return exam_scores.get((stid,subject))
        if mode=="terminal":
            exam=exam_scores.get((stid,subject)); ca_avg=ca_avgs.get((stid,subject))
            if exam is not None and ca_avg is not None:
                return round((ca_avg/100)*term["ca_weight"] + (exam/100)*term["exam_weight"],1)
        return None

    # Drop subject columns nobody in this class/stream has a mark for, for
    # this specific assessment — makes the sheet reflect what the class
    # actually takes instead of a wall of "-" for unrelated subjects.
    active_subjects = [subj for subj in subjects if any(score_for(s["id"], subj) is not None for s in studs)]

    if sheet_type=="grade":
        settings = get_school_grading_settings(sid)
        level = grading_system or settings["grading_system"]
        div_source = division_source or settings["division_source"]
        rules = get_necta_grades(level) if div_source=="necta" else get_grade_rules(sid)
        results=[]
        for s in studs:
            subj_scores={}; grades={}
            for subject in active_subjects:
                score = score_for(s["id"], subject)
                subj_scores[subject]=score
                grades[subject],_ = grade_and_points_for_score(rules, score)
            points, division = compute_division_from_finals(sid, subj_scores, grading_system, division_source, noncredit_override)
            results.append({"id":s["id"],"name":s["name"],"stream_name":s.get("stream_name"),
                            "grades":grades,"points":points,"division":division or "-"})
        return jsonify({"subjects":active_subjects,"results":results,"sheet_type":"grade"})

    grade_rules=get_grade_rules(sid)
    def grade_for(score):
        if score is None: return "-"
        for r in grade_rules:
            if score>=r["min_score"]: return r["grade"]
        return "F"

    results=[]
    for s in studs:
        row={"id":s["id"],"name":s["name"],"stream_name":s.get("stream_name"),"scores":{},"total":0,"count":0}
        for subject in active_subjects:
            score=score_for(s["id"], subject)
            row["scores"][subject]=score
            if score is not None: row["total"]+=score; row["count"]+=1
        row["average"]=round(row["total"]/row["count"],2) if row["count"] else 0
        row["grade"]=grade_for(row["average"]); results.append(row)
    _assign_positions(results,"average")
    return jsonify({"subjects":active_subjects,"results":results,"sheet_type":"marks"})

