"""
PDF building blocks: school logo/header helpers and the shared blue
score-sheet builder. No Flask request/response handling — routes call
these and then send the file.
"""
import base64, io, os

from reportlab.lib.pagesizes import A4, A3, landscape
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm

from config import BASE_DIR
from core.school import get_config_val, get_school_name
from services.grading import get_grade
from services.scores import get_subject_map, _assign_positions


def _get_logo_element(school_id, max_h=2*cm):
    logo_data = get_config_val(school_id, "logo_data", "")
    if logo_data:
        try:
            raw = base64.b64decode(logo_data)
            img = Image(io.BytesIO(raw)); img.drawHeight=max_h; img.drawWidth=max_h; return img
        except: pass
    # Fallback for any older logo still sitting on disk (e.g. one committed to Git)
    path = get_config_val(school_id,"logo_path","")
    if path and not path.startswith("api/logo/"):
        full = os.path.join(BASE_DIR, path)
        if os.path.exists(full):
            try:
                img=Image(full); img.drawHeight=max_h; img.drawWidth=max_h; return img
            except: pass
    return None

def _esc(s):
    return str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

def _school_header_story(school_id, styles, title_text, subtitle_text=""):
    story=[]; H_BG=colors.HexColor("#1A6FA8")
    t_s=ParagraphStyle("T",parent=styles["Title"],fontSize=16,textColor=H_BG,spaceAfter=2,alignment=1)
    s_s=ParagraphStyle("S",parent=styles["Normal"],fontSize=9,alignment=1,spaceAfter=4)
    motto=get_config_val(school_id,"motto",""); sname=get_school_name(school_id)
    logo=_get_logo_element(school_id,1.8*cm)
    if logo:
        name_para=Paragraph(f"<b>{sname}</b>",t_s)
        sub_para=Paragraph(motto,s_s) if motto else None
        inner=[[logo,[name_para]+([sub_para] if sub_para else [])]]
        tbl=Table(inner,colWidths=[2.2*cm,None])
        tbl.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"MIDDLE"),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),6)]))
        story.append(tbl)
    else:
        story.append(Paragraph(sname,t_s))
        if motto: story.append(Paragraph(f'<i>"{motto}"</i>',s_s))
    if title_text: story.append(Paragraph(title_text,s_s))
    if subtitle_text: story.append(Paragraph(subtitle_text,s_s))
    story.append(Spacer(1,0.3*cm)); return story

def _blue_sheet_pdf(school_id,filename,subtitle,students,subjects,get_score_fn,term=None,class_label=""):
    subj_map=get_subject_map(school_id)
    H_BG=colors.HexColor("#1A6FA8"); S_BG=colors.HexColor("#5BA4CF")
    ODD=colors.HexColor("#E8F4FC"); EVEN=colors.white
    RED=colors.HexColor("#C0392B"); WHITE=colors.white
    page_size = landscape(A3) if len(subjects) > 10 else landscape(A4)
    doc=SimpleDocTemplate(filename,pagesize=page_size,rightMargin=1.2*cm,leftMargin=1.2*cm,topMargin=1.2*cm,bottomMargin=1.2*cm)
    styles=getSampleStyleSheet(); story=[]
    tl=term["label"] if term else ""
    title_text = f"{subtitle} — {class_label}" if class_label else subtitle
    story+=_school_header_story(school_id,styles,title_text,tl)
    results=[]
    for s in students:
        row={"name":s["name"],"scores":{},"total":0,"count":0}
        for subj in subjects:
            sc=get_score_fn(s["id"],subj); row["scores"][subj]=sc
            if sc is not None: row["total"]+=sc; row["count"]+=1
        row["average"]=row["total"]/row["count"] if row["count"] else 0
        row["grade"]=get_grade(school_id,row["average"]); results.append(row)
    _assign_positions(results,"average")
    name_style = ParagraphStyle("NameCell", parent=styles["Normal"], fontSize=7.5, leading=8.5)
    hdr=["#","Student"]+[subj_map.get(s,s[:4].upper()) for s in subjects]+["Total","Avg","Pos","Grd"]
    tdata=[hdr]; fail_cells=[]
    for ri,r in enumerate(results,1):
        row=[str(ri),Paragraph(_esc(r["name"]),name_style)]
        for ci,subj in enumerate(subjects):
            sc=r["scores"][subj]
            if sc is not None:
                if sc<50: fail_cells.append((ri,ci+2))
                row.append(f"{sc:.1f}")
            else: row.append("-")
        row+=[f"{r['total']:.1f}" if r["count"] else "-",
              f"{r['average']:.1f}" if r["count"] else "-",
              str(r["position"]),r["grade"] if r["count"] else "-"]
        tdata.append(row)
    sc_w=1.2*cm
    cw=[0.8*cm,6.2*cm]+[sc_w]*len(subjects)+[1.5*cm,1.3*cm,0.9*cm,1.0*cm]
    tbl=Table(tdata,colWidths=cw,repeatRows=1)
    ts=[("BACKGROUND",(0,0),(-1,0),H_BG),("TEXTCOLOR",(0,0),(-1,0),WHITE),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,0),6.5),
        ("ALIGN",(0,0),(-1,0),"CENTER"),("FONTNAME",(0,1),(-1,-1),"Helvetica"),
        ("FONTSIZE",(0,1),(-1,-1),7),("ALIGN",(0,1),(-1,-1),"CENTER"),("ALIGN",(1,1),(1,-1),"LEFT"),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[ODD,EVEN]),("GRID",(0,0),(-1,-1),0.4,colors.HexColor("#A0C4E0")),
        ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3),
        ("BACKGROUND",(-4,0),(-1,0),S_BG),("FONTNAME",(-4,1),(-1,-1),"Helvetica-Bold")]
    for (ri,ci) in fail_cells: ts.append(("TEXTCOLOR",(ci,ri),(ci,ri),RED))
    tbl.setStyle(TableStyle(ts)); story.append(tbl)
    story.append(Spacer(1,0.3*cm))
    ft=ParagraphStyle("F",parent=styles["Normal"],fontSize=6.5,textColor=colors.grey,alignment=2)
    story.append(Paragraph(f"Generated | {len(students)} students | {tl}",ft))
    doc.build(story)
