"""DrDemic Mini: PDF score sheet, same look as the main DrDemic score sheets. No Flask."""
import base64, io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A3, A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from services import mini as M


def _esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _letter(table, v):
    for m, g, _p in table:
        if v >= m:
            return g
    return table[-1][1]


def _logo(b64, max_h=1.8 * cm):
    if not b64:
        return None
    try:
        img = Image(io.BytesIO(base64.b64decode(b64)))
        img.drawHeight = max_h
        img.drawWidth = max_h * img.imageWidth / img.imageHeight
        return img
    except Exception:
        return None


def build_pdf(meta, ranked, logo_b64=None):
    """meta: a mini sheet dict (school_name, exam_name, class_name, sheet_type, grade_rules, data)."""
    stype, rules = meta["sheet_type"], meta["grade_rules"]
    subs = [x for x in meta["data"]["subjects"] if x["name"]]
    rows = [r for r in ranked if r["name"] or r["marks"]]
    table = M.O_LEVEL if stype == "secondary" else M.A_LEVEL

    H_BG, ODD, RED = colors.HexColor("#1A6FA8"), colors.HexColor("#E8F4FC"), colors.HexColor("#C0392B")
    buf = io.BytesIO()
    page = landscape(A3) if len(subs) > 10 else landscape(A4)
    doc = SimpleDocTemplate(buf, pagesize=page, rightMargin=1.2 * cm, leftMargin=1.2 * cm,
                            topMargin=1.2 * cm, bottomMargin=1.2 * cm)
    st = getSampleStyleSheet()
    t_s = ParagraphStyle("T", parent=st["Title"], fontSize=16, textColor=H_BG, spaceAfter=2, alignment=1)
    s_s = ParagraphStyle("S", parent=st["Normal"], fontSize=9, alignment=1, spaceAfter=4)
    story = []

    school = _esc(meta["school_name"] or "School")
    logo = _logo(logo_b64)
    if logo:
        box = Table([[logo, [Paragraph(f"<b>{school}</b>", t_s)]]], colWidths=[2.4 * cm, None])
        box.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                 ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 6)]))
        story.append(box)
    else:
        story.append(Paragraph(school, t_s))
    if meta["exam_name"]:
        story.append(Paragraph(f"<b>{_esc(meta['exam_name'])}</b>", s_s))
    if meta.get("class_name"):
        story.append(Paragraph(_esc(meta["class_name"]), s_s))
    story.append(Spacer(1, 0.3 * cm))

    if stype == "marks":
        tail_h, tail_w = ["Total", "Avg", "Pos", "Grd"], [1.5 * cm, 1.3 * cm, 0.9 * cm, 1.0 * cm]
    elif stype == "primary":
        tail_h, tail_w = ["Avg", "Grade"], [1.5 * cm, 1.5 * cm]
    else:
        tail_h, tail_w = ["Points", "Division"], [1.5 * cm, 1.5 * cm]

    name_style = ParagraphStyle("N", parent=st["Normal"], fontSize=7.5, leading=8.5)
    data = [["#", "Student"] + [s["name"][:5].upper() for s in subs] + tail_h]
    fails = []
    for ri, r in enumerate(rows, 1):
        line = [str(ri), Paragraph(_esc(r["name"]), name_style)]
        for ci, s in enumerate(subs):
            v = r["marks"].get(s["id"])
            if v is None:
                line.append("-")
                continue
            if v < 50:
                fails.append((ri, ci + 2))
            if stype == "marks":
                line.append(f"{v:.1f}")
            else:
                line.append(M.grade_for(rules, v))
        show = lambda x: "-" if x is None else (f"{x:.1f}" if isinstance(x, float) else str(x))
        if stype == "marks":
            line += [show(r["total"]), show(r["average"]), show(r["position"]),
                     r["grade"] if r["average"] is not None else "-"]
        elif stype == "primary":
            line += [show(r["average"]), r["grade"] if r["average"] is not None else "-"]
        else:
            line += [show(r["points"]), r["division"] or "-"]
        data.append(line)

    cw = [0.8 * cm, 6.2 * cm] + [1.2 * cm] * len(subs) + tail_w
    tbl = Table(data, colWidths=cw, repeatRows=1)
    ts = [("BACKGROUND", (0, 0), (-1, 0), H_BG), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
          ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, 0), 6.5),
          ("FONTNAME", (0, 1), (-1, -1), "Helvetica"), ("FONTSIZE", (0, 1), (-1, -1), 7),
          ("ALIGN", (0, 0), (-1, -1), "CENTER"), ("ALIGN", (1, 1), (1, -1), "LEFT"),
          ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
          ("ROWBACKGROUNDS", (0, 1), (-1, -1), [ODD, colors.white]),
          ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#A0C4E0")),
          ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
          ("BACKGROUND", (-len(tail_h), 0), (-1, 0), colors.HexColor("#5BA4CF")),
          ("FONTNAME", (-len(tail_h), 1), (-1, -1), "Helvetica-Bold")]
    ts += [("TEXTCOLOR", (c, r), (c, r), RED) for r, c in fails]
    tbl.setStyle(TableStyle(ts))
    story.append(tbl)
    story.append(Spacer(1, 0.3 * cm))
    foot = ParagraphStyle("F", parent=st["Normal"], fontSize=6.5, textColor=colors.grey, alignment=2)
    story.append(Paragraph(f"Generated | {len(rows)} students | {_esc(meta['exam_name'])}", foot))
    doc.build(story)
    buf.seek(0)
    return buf