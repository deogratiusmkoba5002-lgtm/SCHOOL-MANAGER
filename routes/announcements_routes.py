from flask import Blueprint, request, jsonify, g

from core.db import get_db, to_dicts
from core.auth import require_auth, require_role
from services.subscriptions import subscription_required

announcements_bp = Blueprint("announcements", __name__)

@announcements_bp.route("/api/announcements", methods=["GET"])
@require_auth
def api_get_announcements():
    sid=g.school_id; student_id=request.args.get("student_id")
    con=get_db(); cur=con.cursor()
    if student_id:
        stid=int(student_id)
        if g.role == "parent" and g.student_id != stid:
            cur.close(); con.close()
            return jsonify({"ok":False,"error":"Access denied"}),403
        cur.execute("SELECT class_id FROM students WHERE id=%s AND school_id=%s",(stid,sid))
        row=cur.fetchone()
        if not row: cur.close(); con.close(); return jsonify([])
        cur.execute("SELECT class_name FROM classes WHERE id=%s AND school_id=%s",(row[0],sid))
        cls_row=cur.fetchone(); class_name=cls_row[0] if cls_row else ""
        cur.execute("""SELECT a.id,a.title,a.body,a.target_classes,a.posted_by,CAST(a.posted_at AS TEXT),
                              CASE WHEN ar.student_id IS NOT NULL THEN 1 ELSE 0 END as is_read
                       FROM announcements a
                       LEFT JOIN announcement_reads ar ON ar.announcement_id=a.id AND ar.student_id=%s
                       WHERE a.school_id=%s AND (a.target_classes='all' OR a.target_classes LIKE %s)
                       ORDER BY a.posted_at DESC""",(stid,sid,f"%{class_name}%"))
    else:
        cur.execute("SELECT id,title,body,target_classes,posted_by,CAST(posted_at AS TEXT),0 as is_read FROM announcements WHERE school_id=%s ORDER BY posted_at DESC",(sid,))
    rows=to_dicts(cur.fetchall(),cur); cur.close(); con.close(); return jsonify(rows)

@announcements_bp.route("/api/announcements", methods=["POST"])
@require_auth
@subscription_required
@require_role("admin")
def api_post_announcement():
    sid=g.school_id; d=request.json
    title=d.get("title","").strip(); body=d.get("body","").strip()
    posted_by=d.get("posted_by",""); target_classes=(d.get("target_classes") or "all").strip() or "all"
    if not title or not body: return jsonify({"ok":False,"error":"Title and body required"}),400
    con=get_db(); cur=con.cursor()
    cur.execute("INSERT INTO announcements(school_id,title,body,target_classes,posted_by) VALUES(%s,%s,%s,%s,%s) RETURNING id",
                (sid,title,body,target_classes,posted_by))
    new_id=cur.fetchone()[0]; con.commit(); cur.close(); con.close()
    return jsonify({"ok":True,"id":new_id})

@announcements_bp.route("/api/announcements/<int:aid>", methods=["DELETE"])
@require_auth
@require_role("admin")
def api_delete_announcement(aid):
    sid=g.school_id
    con=get_db(); cur=con.cursor()
    cur.execute("DELETE FROM announcements WHERE id=%s AND school_id=%s",(aid,sid))
    con.commit(); cur.close(); con.close(); return jsonify({"ok":True})

@announcements_bp.route("/api/announcements/<int:aid>/read", methods=["POST"])
@require_auth
def api_mark_announcement_read(aid):
    student_id=request.json.get("student_id")
    if not student_id: return jsonify({"ok":False,"error":"student_id required"}),400
    if g.role == "parent" and g.student_id != int(student_id):
        return jsonify({"ok":False,"error":"Access denied"}),403
    con=get_db(); cur=con.cursor()
    cur.execute("INSERT INTO announcement_reads(announcement_id,student_id) VALUES(%s,%s) ON CONFLICT DO NOTHING",(aid,int(student_id)))
    con.commit(); cur.close(); con.close(); return jsonify({"ok":True})

# ── PLATFORM ANNOUNCEMENTS (school-side) ──────────────────────
@announcements_bp.route("/api/platform_announcements", methods=["GET"])
@require_auth
def api_platform_announcements():
    sid=g.school_id
    con=get_db(); cur=con.cursor()
    cur.execute("""SELECT pa.id,pa.title,pa.body,CAST(pa.posted_at AS TEXT) as posted_at,
                          CASE WHEN par.school_id IS NOT NULL THEN 1 ELSE 0 END AS is_read
                   FROM platform_announcements pa
                   LEFT JOIN platform_announcement_reads par ON par.announcement_id=pa.id AND par.school_id=%s
                   WHERE pa.target='all' OR pa.target=%s
                   ORDER BY pa.posted_at DESC""",(sid,str(sid)))
    rows=to_dicts(cur.fetchall(),cur); cur.close(); con.close(); return jsonify(rows)

@announcements_bp.route("/api/platform_announcements/<int:aid>/read", methods=["POST"])
@require_auth
def api_platform_announcement_read(aid):
    sid=g.school_id
    con=get_db(); cur=con.cursor()
    cur.execute("INSERT INTO platform_announcement_reads(announcement_id,school_id) VALUES(%s,%s) ON CONFLICT DO NOTHING",(aid,sid))
    con.commit(); cur.close(); con.close(); return jsonify({"ok":True})

