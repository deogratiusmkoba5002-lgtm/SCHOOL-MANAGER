import os, tempfile
from flask import Blueprint, request, jsonify, g, send_file
from reportlab.lib.pagesizes import A4, A3, landscape
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm

from core.db import get_db, to_dict
from core.auth import require_auth, require_role
from services.subscriptions import subscription_required
from services.grading import (get_grade, get_grade_rules, get_school_grading_settings,
                              get_necta_grades, grade_and_points_for_score, compute_division_from_finals)
from services.scores import (
    get_subjects, get_subject_map, get_active_term, get_term_by_id, get_students_in_scope,
    get_term_scores_bulk, _final_from_entry, _active_subjects_in_scores, compute_student_finals,
    compute_average_from_finals, get_subject_rank_map, get_class_report_data,
)
from services.pdf import _esc, _school_header_story, _blue_sheet_pdf

pdf_bp = Blueprint("pdf", __name__)

@pdf_bp.route("/api/pdf/report/<int:sid>", methods=["GET"])
@require_auth
@subscription_required
@require_role("admin","teacher","parent")
def pdf_report(sid):
    school_id=g.school_id
    if g.role == "parent" and g.student_id != sid:
        return  jsonify({"error":"Access denied"}),403
    subjects=get_subjects(school_id); subj_map=get_subject_map(school_id)
    term_id=request.args.get("term_id")
    con=get_db(); cur=con.cursor()
    cur.execute("""SELECT s.id,s.name,s.class_id,s.stream_id,c.class_name,st.stream_name
                   FROM students s JOIN classes c ON s.class_id=c.id LEFT JOIN streams st ON s.stream_id=st.id
                   WHERE s.id=%s AND s.school_id=%s""",(sid,school_id))
    row=cur.fetchone(); student=to_dict(row,cur) if row else None; cur.close(); con.close()
    if not student: return jsonify({"error":"Not found"}),404
    term=get_term_by_id(school_id,int(term_id)) if term_id else get_active_term(school_id)
    if not term: return jsonify({"error":"No term"}),400
    tid=term["id"]; ca_count=term["ca_count"]; ca_w=term["ca_weight"]; ex_w=term["exam_weight"]
    class_id=student["class_id"]; stream_id=student["stream_id"]

    class_rows, class_rank_map, stream_rank_map, scores_bulk = get_class_report_data(
        school_id, tid, class_id, stream_id, subjects, ca_w, ex_w)
    active_subjects = _active_subjects_in_scores(subjects, scores_bulk)
    subject_rank_maps = {subj: get_subject_rank_map(class_rows, subj) for subj in active_subjects}
    c_entry=class_rank_map.get(sid)
    c_pos=c_entry["position"] if c_entry else "-"
    c_total=len(class_rows)
    s_pos=s_total=None
    if stream_id and stream_rank_map is not None:
        s_entry=stream_rank_map.get(sid)
        s_pos=s_entry["position"] if s_entry else "-"
        s_total=len(stream_rank_map)
    student_finals = c_entry["finals"] if c_entry else compute_student_finals(scores_bulk, sid, subjects, ca_w, ex_w)
    avg = c_entry["average"] if c_entry else compute_average_from_finals(student_finals)
    student_scores = scores_bulk.get(sid, {})

    safe=student["name"].replace(" ","_")
    fname=os.path.join(tempfile.gettempdir(),f"RC_{school_id}_{safe}_{tid}.pdf")
    # Many CA columns get cramped in portrait — switch to landscape automatically.
    page_size = landscape(A4) if ca_count > 4 else A4
    doc=SimpleDocTemplate(fname,pagesize=page_size,rightMargin=1.5*cm,leftMargin=1.5*cm,topMargin=1.5*cm,bottomMargin=1.5*cm)
    styles=getSampleStyleSheet(); story=[]
    H_BG=colors.HexColor("#1A6FA8"); ODD=colors.HexColor("#E8F4FC"); WHITE=colors.white; RED=colors.HexColor("#C0392B")
    story+=_school_header_story(school_id,styles,"STUDENT REPORT CARD")
    stream_label=f"{student['class_name']} {student['stream_name']}" if student.get("stream_name") else student["class_name"]
    info=[[" Name:",student["name"],"Class:",stream_label],
          ["Term:",term["label"],"Weights:",f"CA {ca_w}% | Exam {ex_w}%"],
          ["Class Position:",f"{c_pos}/{c_total}","Grade:",get_grade(school_id,avg)]]
    if s_pos is not None: info.append(["Stream Position:",f"{s_pos}/{s_total}","",""])
    it=Table(info,colWidths=[3*cm,6*cm,3*cm,5*cm])
    it.setStyle(TableStyle([("FONTNAME",(0,0),(-1,-1),"Helvetica"),("FONTNAME",(0,0),(0,-1),"Helvetica-Bold"),
        ("FONTNAME",(2,0),(2,-1),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),9),
        ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3)]))
    story+=[it,Spacer(1,0.4*cm)]
    hdr=["Subject"]+[f"CA{i}" for i in range(1,ca_count+1)]+["Exam","Final","Pos","Grd","Remark","Sign"]
    tdata=[hdr]; tot,cnt=0,0; fail_rows=[]
    for subject in active_subjects:
        entry=student_scores.get(subject,{})
        ca_map=entry.get("ca",{})
        row_data=[subject.title()]+[f"{ca_map.get(f'CA{i}'):.1f}" if ca_map.get(f"CA{i}") is not None else "-" for i in range(1,ca_count+1)]
        exam_v=entry.get("exam")
        row_data.append(f"{exam_v:.1f}" if exam_v is not None else "-")
        final_v=student_finals.get(subject)
        if final_v is not None: tot+=final_v; cnt+=1
        row_data.append(f"{final_v:.1f}" if final_v is not None else "-")
        row_data.append(str(subject_rank_maps[subject].get(sid,"-")) if final_v is not None else "-")
        row_data.append(get_grade(school_id,final_v) if final_v is not None else "-")
        row_data+=["",""]
        if final_v is not None and final_v<50: fail_rows.append(len(tdata))
        tdata.append(row_data)
    ca_cw=1.1*cm; cw=[4.0*cm]+[ca_cw]*ca_count+[1.4*cm,1.4*cm,1.0*cm,1.1*cm,2.4*cm,1.6*cm]
    mt=Table(tdata,colWidths=cw,repeatRows=1)
    mts=[("BACKGROUND",(0,0),(-1,0),H_BG),("TEXTCOLOR",(0,0),(-1,0),WHITE),
         ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),7.5),
         ("ALIGN",(0,0),(-1,-1),"CENTER"),("ALIGN",(0,1),(0,-1),"LEFT"),
         ("GRID",(0,0),(-1,-1),0.4,colors.HexColor("#A0C4E0")),("ROWBACKGROUNDS",(0,1),(-1,-1),[ODD,WHITE]),
         ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3)]
    for ri in fail_rows: mts.append(("TEXTCOLOR",(0,ri),(-1,ri),RED))
    mt.setStyle(TableStyle(mts)); story+=[mt,Spacer(1,0.4*cm)]
    comp_avg=tot/cnt if cnt else 0
    summary_data=[["AVERAGE",f"{comp_avg:.2f}","GRADE",get_grade(school_id,comp_avg),"CLASS POS",f"{c_pos}/{c_total}"]]
    summary_cols=[3*cm,3*cm,2*cm,2*cm,3*cm,4*cm]
    if s_pos is not None: summary_data[0]+=["STREAM POS",f"{s_pos}/{s_total}"]; summary_cols+=[3*cm,3*cm]
    sm=Table(summary_data,colWidths=summary_cols)
    sm.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),H_BG),("TEXTCOLOR",(0,0),(-1,-1),WHITE),
        ("FONTNAME",(0,0),(-1,-1),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),9),
        ("ALIGN",(0,0),(-1,-1),"CENTER"),("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5)]))
    story+=[sm,Spacer(1,0.4*cm)]
    con=get_db(); cur=con.cursor()
    cur.execute("SELECT * FROM remarks WHERE school_id=%s AND student_id=%s AND term_id=%s",(school_id,sid,tid))
    rmk_row=cur.fetchone(); rmk=to_dict(rmk_row,cur) if rmk_row else None; cur.close(); con.close()
    rm_data=[["Class Teacher Remark:",rmk["class_teacher_remark"] if rmk else "________________________"],
             ["Head of School Remark:",rmk["head_remark"] if rmk else "________________________"]]
    rmt=Table(rm_data,colWidths=[5*cm,12*cm])
    rmt.setStyle(TableStyle([("FONTNAME",(0,0),(0,-1),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),8),
        ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),("LINEBELOW",(1,0),(1,-1),0.5,colors.grey)]))
    story+=[rmt,Spacer(1,0.4*cm)]
    sig=Table([["Class Teacher Sign: _______________","Head Sign: _______________","Date: _______________"]],colWidths=[6*cm,6*cm,5*cm])
    sig.setStyle(TableStyle([("FONTSIZE",(0,0),(-1,-1),7.5),("FONTNAME",(0,0),(-1,-1),"Helvetica")]))
    story.append(sig); doc.build(story)
    return send_file(fname,as_attachment=True,
                     download_name=f"RC_{student['name'].replace(' ','_')}_{term['label'].replace(' ','_')}.pdf",
                     mimetype="application/pdf")

@pdf_bp.route("/api/pdf/ca_sheet", methods=["GET"])
@require_auth
@subscription_required
@require_role("admin","teacher")
def pdf_ca_sheet():
    school_id=g.school_id; subjects=get_subjects(school_id)
    class_id=request.args.get("class_id"); stream_id=request.args.get("stream_id") or None
    ca_name=request.args.get("ca_name","CA1"); term_id=request.args.get("term_id")
    term=get_term_by_id(school_id,int(term_id)) if term_id else get_active_term(school_id)
    if not term: return jsonify({"error":"No term"}),400
    tid=term["id"]; class_id=int(class_id) if class_id else None
    if stream_id: stream_id=int(stream_id)
    studs=get_students_in_scope(school_id,class_id,stream_id)
    if not studs: return jsonify({"error":"No students"}),404
    fname=os.path.join(tempfile.gettempdir(),f"CA_{school_id}_{class_id}_{ca_name.replace(':','_')}_{tid}.pdf")
    scores_bulk=get_term_scores_bulk(school_id,tid,[s["id"] for s in studs])
    def get_score(stid,subj):
        entry=scores_bulk.get(stid,{}).get(subj)
        if not entry: return None
        if ca_name=="exam": return entry["exam"]
        if ca_name.startswith("test:"):
            tid_=int(ca_name.split(":",1)[1])
            return (entry.get("tests") or {}).get(tid_)
        return entry["ca"].get(ca_name)
    active_subjects = [subj for subj in subjects if any(get_score(s["id"], subj) is not None for s in studs)]
    subtitle_label = ca_name.upper()
    if ca_name.startswith("test:"):
        con=get_db(); cur=con.cursor()
        cur.execute("SELECT label FROM term_tests WHERE id=%s AND school_id=%s",(int(ca_name.split(":",1)[1]),school_id))
        r=cur.fetchone(); cur.close(); con.close()
        subtitle_label = (r[0].upper() if r else "TEST")
    class_label = studs[0]["class_name"] + (f" {studs[0]['stream_name']}" if stream_id and studs[0].get("stream_name") else "")
    _blue_sheet_pdf(school_id,fname,f"{subtitle_label} SCORE SHEET",studs,active_subjects,get_score,term,class_label=class_label)
    return send_file(fname,as_attachment=True,download_name=os.path.basename(fname),mimetype="application/pdf")

@pdf_bp.route("/api/pdf/grade_sheet", methods=["GET"])
@require_auth
@subscription_required
@require_role("admin","teacher")
def pdf_grade_sheet():
    school_id=g.school_id; subjects=get_subjects(school_id)
    mode=request.args.get("mode","ca")
    class_id=request.args.get("class_id"); stream_id=request.args.get("stream_id") or None
    ca_name=request.args.get("ca_name","CA1"); term_id=request.args.get("term_id")
    grading_system=request.args.get("grading_system") or None
    division_source=request.args.get("division_source") or None
    noncredit_param=request.args.get("noncredit","")
    noncredit_override=[x.strip().lower() for x in noncredit_param.split(",") if x.strip()] if noncredit_param else None

    term=get_term_by_id(school_id,int(term_id)) if term_id else get_active_term(school_id)
    if not term: return jsonify({"error":"No term"}),400
    tid=term["id"]; class_id=int(class_id) if class_id else None
    if stream_id: stream_id=int(stream_id)
    studs=get_students_in_scope(school_id,class_id,stream_id)
    if not studs: return jsonify({"error":"No students"}),404

    scores_bulk=get_term_scores_bulk(school_id,tid,[s["id"] for s in studs])
    ca_w=term["ca_weight"]; ex_w=term["exam_weight"]
    def get_score(stid,subj):
        entry=scores_bulk.get(stid,{}).get(subj)
        if not entry: return None
        if mode=="ca":
            if ca_name.startswith("test:"):
                tid_=int(ca_name.split(":",1)[1])
                return (entry.get("tests") or {}).get(tid_)
            return entry["ca"].get(ca_name)
        if mode=="exam": return entry["exam"]
        if mode=="terminal": return _final_from_entry(entry,ca_w,ex_w)
        return None

    active_subjects = [subj for subj in subjects if any(get_score(s["id"], subj) is not None for s in studs)]

    settings = get_school_grading_settings(school_id)
    level = grading_system or settings["grading_system"]
    div_source = division_source or settings["division_source"]
    rules = get_necta_grades(level) if div_source=="necta" else get_grade_rules(school_id)

    fname=os.path.join(tempfile.gettempdir(),f"Grade_{school_id}_{class_id}_{mode}_{ca_name.replace(':','_')}_{tid}.pdf")
    class_label = studs[0]["class_name"] + (f" {studs[0]['stream_name']}" if stream_id and studs[0].get("stream_name") else "")
    if mode=="ca" and ca_name.startswith("test:"):
        con=get_db(); cur=con.cursor()
        cur.execute("SELECT label FROM term_tests WHERE id=%s AND school_id=%s",(int(ca_name.split(":",1)[1]),school_id))
        r=cur.fetchone(); cur.close(); con.close()
        title = f"{(r[0].upper() if r else 'TEST')} GRADE SHEET"
    else:
        title = {"ca": f"{ca_name.upper()} GRADE SHEET", "exam":"EXAM GRADE SHEET", "terminal":"TERMINAL GRADE SHEET"}.get(mode,"GRADE SHEET")

    subj_map=get_subject_map(school_id)
    H_BG=colors.HexColor("#1A6FA8"); ODD=colors.HexColor("#E8F4FC"); WHITE=colors.white
    page_size = landscape(A3) if len(active_subjects) > 10 else landscape(A4)
    doc=SimpleDocTemplate(fname,pagesize=page_size,rightMargin=1.2*cm,leftMargin=1.2*cm,topMargin=1.2*cm,bottomMargin=1.2*cm)
    styles=getSampleStyleSheet(); story=[]
    story+=_school_header_story(school_id,styles,f"{title} — {class_label}" if class_label else title, term["label"])

    name_style = ParagraphStyle("NameCell", parent=styles["Normal"], fontSize=7.5, leading=8.5)
    hdr=["#","Student"]+[subj_map.get(s,s[:4].upper()) for s in active_subjects]+["Points","Division"]
    tdata=[hdr]
    for ri,s in enumerate(studs,1):
        subj_scores={}
        row=[str(ri),Paragraph(_esc(s["name"]),name_style)]
        for subj in active_subjects:
            sc=get_score(s["id"],subj)
            subj_scores[subj]=sc
            grade,_ = grade_and_points_for_score(rules, sc)
            row.append(grade)
        points, division = compute_division_from_finals(school_id, subj_scores, grading_system, division_source, noncredit_override)
        row += [str(points) if points is not None else "-", division or "-"]
        tdata.append(row)

    sc_w=1.2*cm
    cw=[0.8*cm,6.2*cm]+[sc_w]*len(active_subjects)+[1.5*cm,1.5*cm]
    tbl=Table(tdata,colWidths=cw,repeatRows=1)
    ts=[("BACKGROUND",(0,0),(-1,0),H_BG),("TEXTCOLOR",(0,0),(-1,0),WHITE),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),7),
        ("ALIGN",(0,0),(-1,-1),"CENTER"),("ALIGN",(1,1),(1,-1),"LEFT"),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[ODD,WHITE]),("GRID",(0,0),(-1,-1),0.4,colors.HexColor("#A0C4E0")),
        ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3)]
    tbl.setStyle(TableStyle(ts)); story.append(tbl)
    story.append(Spacer(1,0.3*cm))
    ft=ParagraphStyle("F",parent=styles["Normal"],fontSize=6.5,textColor=colors.grey,alignment=2)
    story.append(Paragraph(f"Generated | {len(studs)} students | {term['label']}",ft))
    doc.build(story)
    return send_file(fname,as_attachment=True,download_name=os.path.basename(fname),mimetype="application/pdf")

@pdf_bp.route("/api/pdf/terminal_sheet", methods=["GET"])
@require_auth
@subscription_required
@require_role("admin","teacher")
def pdf_terminal_sheet():
    school_id=g.school_id; subjects=get_subjects(school_id)
    class_id=request.args.get("class_id"); stream_id=request.args.get("stream_id") or None; term_id=request.args.get("term_id")
    term=get_term_by_id(school_id,int(term_id)) if term_id else get_active_term(school_id)
    if not term: return jsonify({"error":"No term"}),400
    tid=term["id"]; class_id=int(class_id) if class_id else None
    if stream_id: stream_id=int(stream_id)
    studs=get_students_in_scope(school_id,class_id,stream_id)
    if not studs: return jsonify({"error":"No students"}),404
    fname=os.path.join(tempfile.gettempdir(),f"Terminal_{school_id}_{class_id}_{tid}.pdf")
    scores_bulk=get_term_scores_bulk(school_id,tid,[s["id"] for s in studs])
    ca_w=term["ca_weight"]; ex_w=term["exam_weight"]
    def get_score(stid,subj):
        f=_final_from_entry(scores_bulk.get(stid,{}).get(subj),ca_w,ex_w)
        return round(f,1) if f is not None else None
    active_subjects = [subj for subj in subjects if any(get_score(s["id"], subj) is not None for s in studs)]
    class_label = studs[0]["class_name"] + (f" {studs[0]['stream_name']}" if stream_id and studs[0].get("stream_name") else "")
    _blue_sheet_pdf(school_id,fname,f"TERMINAL SCORE SHEET (CA {term['ca_weight']}% + Exam {term['exam_weight']}%)",studs,active_subjects,get_score,term)
    return send_file(fname,as_attachment=True,download_name=os.path.basename(fname),mimetype="application/pdf")

