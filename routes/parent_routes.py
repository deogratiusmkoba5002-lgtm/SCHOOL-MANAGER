from flask import Blueprint, request, jsonify, g

from core.db import get_db, to_dict, to_dicts
from core.auth import require_auth, require_role
from services.grading import get_grade, compute_division_from_finals
from services.subscriptions import is_subscribed
from services.scores import (
    get_subjects, get_active_term, get_term_by_id, get_term_tests, _assign_positions,
    _score_for_assess, _active_subjects_in_scores, compute_student_finals,
    compute_average_from_finals, get_subject_rank_map, get_subject_assess_rank_map,
    get_class_report_data,
)
from services.access import has_active_access
from services.stars import ensure_cycle_started

parent_bp = Blueprint("parent", __name__)

# ── RESULTS PUBLISHING ────────────────────────────────────────
@parent_bp.route("/api/results/status", methods=["GET"])
@require_auth
def api_results_status():
    sid=g.school_id; term_id=request.args.get("term_id")
    if not term_id:
        term=get_active_term(sid)
        if not term: return jsonify({"published":False,"term":None,"term_id":None})
        term_id=term["id"]
    else: term_id=int(term_id)
    con=get_db(); cur=con.cursor()
    cur.execute("SELECT published FROM results_published WHERE school_id=%s AND term_id=%s",(sid,term_id))
    row=cur.fetchone(); cur.close(); con.close()
    return jsonify({"published":bool(row[0]) if row else False,"term":get_term_by_id(sid,term_id),"term_id":term_id})

@parent_bp.route("/api/results/toggle", methods=["POST"])
@require_auth
@require_role("admin")
def api_toggle_results():
    sid=g.school_id; d=request.json
    term_id=d.get("term_id"); publish=bool(d.get("publish",True))
    if publish and not is_subscribed(sid):
        return jsonify({"ok": False, "error": "subscription_required",
                        "message": "Publishing results requires an active subscription."}), 402
    if not term_id: return jsonify({"ok":False,"error":"term_id required"}),400
    con=get_db(); cur=con.cursor()
    cur.execute("""INSERT INTO results_published(school_id,term_id,published) VALUES(%s,%s,%s)
                   ON CONFLICT(school_id,term_id) DO UPDATE SET published=EXCLUDED.published""",
                (sid,int(term_id),1 if publish else 0))
    con.commit(); cur.close(); con.close()
    if publish:
        ensure_cycle_started(sid)
    return jsonify({"ok":True,"published":publish})

@parent_bp.route("/api/results/assessments", methods=["GET"])
@require_auth
def api_list_assessments_for_publish():
    sid = g.school_id; term_id = request.args.get("term_id")
    if not term_id:
        term = get_active_term(sid)
        if not term: return jsonify({"ok":True,"assessments":[]})
        term_id = term["id"]
    else: term_id = int(term_id)
    term = get_term_by_id(sid, term_id)
    if not term: return jsonify({"ok":False,"error":"Term not found"}),404
    tests = get_term_tests(sid, term_id)
    test_map = {t["id"]: t["label"] for t in tests}
    keys = [f"CA{i}" for i in range(1, term["ca_count"]+1)] + ["exam"] + [f"test:{t['id']}" for t in tests]
    con=get_db(); cur=con.cursor()
    cur.execute("SELECT assess_key, published FROM published_assessments WHERE school_id=%s AND term_id=%s",(sid,term_id))
    pub_map = dict(cur.fetchall()); cur.close(); con.close()
    result=[]
    for k in keys:
        label = "Final Exam" if k=="exam" else (test_map.get(int(k.split(":")[1])) if k.startswith("test:") else k)
        result.append({"assess_key":k, "label":label, "published": bool(pub_map.get(k,0))})
    return jsonify({"ok":True,"term_id":term_id,"assessments":result})

@parent_bp.route("/api/results/publish_assessments", methods=["POST"])
@require_auth
@require_role("admin")
def api_publish_assessments():
    sid = g.school_id; d = request.json or {}
    term_id = d.get("term_id"); keys = d.get("assess_keys") or []; publish = bool(d.get("publish", True))
    if publish and not is_subscribed(sid):
        return jsonify({"ok":False,"error":"subscription_required","message":"Publishing results requires an active subscription."}),402
    if not term_id or not keys: return jsonify({"ok":False,"error":"term_id and assess_keys required"}),400
    con=get_db(); cur=con.cursor()
    for k in keys:
        cur.execute("""INSERT INTO published_assessments(school_id,term_id,assess_key,published) VALUES(%s,%s,%s,%s)
                       ON CONFLICT(school_id,term_id,assess_key) DO UPDATE SET published=EXCLUDED.published""",
                    (sid,int(term_id),k,1 if publish else 0))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok":True})

# ── PARENT PORTAL ─────────────────────────────────────────────
@parent_bp.route("/api/parent/terms", methods=["GET"])
@require_auth
def api_parent_terms():
    sid=g.school_id
    if g.role == "parent" and not has_active_access(sid, g.student_id):
        return jsonify([])
    con=get_db(); cur=con.cursor()
    # A term shows up here if EITHER the legacy whole-term publish switch is
    # on, OR at least one individual assessment has been published via the
    # newer per-assessment publisher — previously only the legacy flag was
    # checked, so terms published assessment-by-assessment (the normal flow)
    # never appeared for parents.
    cur.execute("""SELECT DISTINCT t.id,t.label,t.ca_count,t.ca_weight,t.exam_weight,t.status
                   FROM terms t
                   WHERE t.school_id=%s AND (
                       EXISTS (SELECT 1 FROM results_published rp WHERE rp.school_id=t.school_id AND rp.term_id=t.id AND rp.published=1)
                       OR EXISTS (SELECT 1 FROM published_assessments pa WHERE pa.school_id=t.school_id AND pa.term_id=t.id AND pa.published=1)
                   )
                   ORDER BY t.id ASC""",(sid,))
    rows=to_dicts(cur.fetchall(),cur); cur.close(); con.close(); return jsonify(rows)

@parent_bp.route("/api/parent/results", methods=["GET"])
@require_auth
@require_role("parent")
def api_parent_results():
    sid=g.school_id; subjects=get_subjects(sid)
    student_id=request.args.get("student_id"); term_id=request.args.get("term_id"); assess=request.args.get("assess")
    if not student_id: return jsonify({"ok":False,"error":"student_id required"}),400
    if int(student_id) !=g.student_id:
        return jsonify({"ok":False,"error":"Access denied"}),403 
    if not has_active_access(sid, g.student_id):
        return jsonify({"ok":False,"error":"Parent access required. Subscribe to unlock results.","code":"parent_access_required"}),402
    if assess:
        con=get_db(); cur=con.cursor()
        cur.execute("SELECT published FROM published_assessments WHERE school_id=%s AND term_id=%s AND assess_key=%s",(sid,term_id,assess))
        prow=cur.fetchone(); cur.close(); con.close()
        if not prow or not prow[0]:
            return jsonify({"ok":False,"error":"This assessment hasn't been published yet"}),403
    else:
        con=get_db(); cur=con.cursor()
        cur.execute("SELECT published FROM results_published WHERE school_id=%s AND term_id=%s",(sid,term_id))
        row=cur.fetchone(); cur.close(); con.close()
        if not row or not row[0]: return jsonify({"ok":False,"error":"Results not yet published"}),403
    stid=int(student_id); term=get_term_by_id(sid,term_id)
    con=get_db(); cur=con.cursor()
    cur.execute("""SELECT s.id,s.name,s.class_id,s.stream_id,c.class_name,st.stream_name
                   FROM students s JOIN classes c ON s.class_id=c.id LEFT JOIN streams st ON s.stream_id=st.id
                   WHERE s.id=%s AND s.school_id=%s""",(stid,sid))
    row=cur.fetchone(); student=to_dict(row,cur) if row else None; cur.close(); con.close()
    if not student: return jsonify({"ok":False,"error":"Student not found"}),404
    ca_count=term["ca_count"]; ca_w=term["ca_weight"]; ex_w=term["exam_weight"]
    class_id=student["class_id"]; stream_id=student["stream_id"]

    class_rows, class_rank_map, stream_rank_map, scores_bulk = get_class_report_data(
        sid, term_id, class_id, stream_id, subjects, ca_w, ex_w)
    class_ids = [r["id"] for r in class_rows]
    student_scores = scores_bulk.get(stid, {})

    results=[]
    if assess:
        active_subjects = [subj for subj in subjects
                            if any(_score_for_assess(scores_bulk.get(cid, {}).get(subj), assess) is not None for cid in class_ids)]
        assess_rank_maps={}
        for subject in active_subjects:
            entry=student_scores.get(subject,{})
            ca_map=entry.get("ca",{})
            ca_scores={f"CA{i}": ca_map.get(f"CA{i}") for i in range(1,ca_count+1)}
            exam_val=entry.get("exam")
            score=_score_for_assess(entry, assess)
            if score is None: continue
            if subject not in assess_rank_maps:
                assess_rank_maps[subject]=get_subject_assess_rank_map(scores_bulk,class_ids,subject,assess)
            pos=assess_rank_maps[subject].get(stid,"-")
            results.append({"subject":subject,"ca":ca_scores,"exam":exam_val,"score":score,
                            "grade":get_grade(sid,score),"position":pos})
    else:
        active_subjects = _active_subjects_in_scores(subjects, scores_bulk)
        subject_rank_maps={subj: get_subject_rank_map(class_rows, subj) for subj in active_subjects}
        student_finals = class_rank_map.get(stid,{}).get("finals") or compute_student_finals(scores_bulk,stid,subjects,ca_w,ex_w)
        for subject in active_subjects:
            entry=student_scores.get(subject,{})
            ca_map=entry.get("ca",{})
            ca_scores={f"CA{i}": ca_map.get(f"CA{i}") for i in range(1,ca_count+1)}
            exam_val=entry.get("exam")
            if not ca_map and exam_val is None: continue
            final_val=student_finals.get(subject)
            subj_pos=subject_rank_maps[subject].get(stid,"-") if final_val is not None else "-"
            results.append({"subject":subject,"ca":ca_scores,"exam":exam_val,
                            "final":round(final_val,1) if final_val is not None else None,
                            "grade":get_grade(sid,final_val) if final_val is not None else "-","position":subj_pos})

    if assess:
        # Rank by THIS assessment's own average across subjects, not the term's
        # weighted final. Finals are only computable once both CA and exam marks
        # exist, so before the exam is entered every student's final average is
        # 0 — that ties the whole class and everyone was showing up as "1st".
        stream_id_map = {r["id"]: r.get("stream_id") for r in class_rows}
        assess_scores=[]
        for cid in class_ids:
            student_data = scores_bulk.get(cid, {})
            vals=[]
            for subject in subjects:
                entry = student_data.get(subject, {})
                v = _score_for_assess(entry, assess)
                if v is not None: vals.append(v)
            if vals: assess_scores.append({"id":cid,"score":sum(vals)/len(vals)})
        _assign_positions(assess_scores,"score")
        assess_pos_map={r["id"]:r["position"] for r in assess_scores}
        c_pos = assess_pos_map.get(stid,"-")
        c_total = len(assess_scores)
        s_pos=s_total=None
        if stream_id:
            stream_scores=[dict(r) for r in assess_scores if stream_id_map.get(r["id"])==stream_id]
            _assign_positions(stream_scores,"score")
            stream_pos_map={r["id"]:r["position"] for r in stream_scores}
            s_pos = stream_pos_map.get(stid,"-")
            s_total = len(stream_scores)
        if results:
            scores_only=[r["score"] for r in results if r.get("score") is not None]
            avg=round(sum(scores_only)/len(scores_only),2) if scores_only else 0
        else:
            avg = 0
    else:
        c_entry=class_rank_map.get(stid)
        c_pos=c_entry["position"] if c_entry else "-"
        c_total=len(class_rows)
        s_pos=s_total=None
        if stream_id and stream_rank_map is not None:
            s_entry=stream_rank_map.get(stid)
            s_pos=s_entry["position"] if s_entry else "-"
            s_total=len(stream_rank_map)
        avg = c_entry["average"] if c_entry else round(compute_average_from_finals(compute_student_finals(scores_bulk,stid,subjects,ca_w,ex_w)),2)

    if assess:
        subj_scores_div = {r["subject"]: r["score"] for r in results if r.get("score") is not None}
    else:
        subj_scores_div = student_finals
    division_points, division = compute_division_from_finals(sid, subj_scores_div)

    return jsonify({"ok":True,"student":student,"term":term,"results":results,"ca_count":ca_count,
                    "average":avg,"grade":get_grade(sid,avg),
                    "class_position":c_pos,"class_total":c_total,
                    "stream_position":s_pos,"stream_total":s_total,"assess":assess,
                    "division":division,"division_points":division_points})

