from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, current_app

from config import SUBSCRIPTION_PLANS
from core.db import get_db, to_dicts
from core.security import verify_password
from core.auth import _require_superadmin, _sa_serializer
from services.subscriptions import _expire_stale_payment_requests, _platform_payment_config

superadmin_bp = Blueprint("superadmin", __name__)

@superadmin_bp.route("/api/superadmin/login", methods=["POST"])
def api_superadmin_login():
    d=request.json; u=d.get("username","").strip(); p=d.get("password","")
    if not u or not p: return jsonify({"ok":False,"error":"Username and password required"}),400
    con=get_db(); cur=con.cursor()
    cur.execute("SELECT password FROM superadmins WHERE username=%s",(u,))
    row=cur.fetchone(); cur.close(); con.close()
    if not row or not verify_password(p,row[0]): return jsonify({"ok":False,"error":"Invalid credentials"}),401
    token=_sa_serializer.dumps({"username":u})
    return jsonify({"ok":True,"token":token,"username":u})

@superadmin_bp.route("/api/superadmin/logout", methods=["POST"])
def api_superadmin_logout():
    return jsonify({"ok":True})

@superadmin_bp.route("/api/superadmin/schools", methods=["GET"])
def api_superadmin_schools():
    sa,err=_require_superadmin()
    if err: return err
    try:
        con=get_db(); cur=con.cursor()
        cur.execute("SELECT id,school_name,CAST(registered_at AS TEXT) FROM schools ORDER BY id")
        schools_raw=to_dicts(cur.fetchall(),cur); result=[]
        for s in schools_raw:
            sid=s["id"]
            cur.execute("SELECT COUNT(*) FROM students WHERE school_id=%s",(sid,)); sc=cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM users WHERE school_id=%s AND role='teacher'",(sid,)); tc=cur.fetchone()[0]
            cur.execute("SELECT label FROM terms WHERE school_id=%s AND status='open' ORDER BY id DESC LIMIT 1",(sid,))
            r=cur.fetchone(); at=r[0] if r else "—"
            cur.execute("SELECT subscription_exempt, subscription_status, subscription_plan, subscription_expires_at FROM schools WHERE id=%s",(sid,))
            sub_row = cur.fetchone()
            exempt, sub_status, sub_plan, sub_expires = sub_row if sub_row else (0,"inactive","",None)
            payment_status = "demo" if exempt else (sub_status or "inactive")
            result.append({"id":sid,"school_name":s["school_name"],"registered_at":s.get("cast") or "—",
                           "student_count":sc,"teacher_count":tc,"active_term":at,
                           "payment_status":payment_status,
                           "subscription_plan": sub_plan or "—",
                           "subscription_expires_at": sub_expires.isoformat() if sub_expires else None})
        cur.close(); con.close()
        return jsonify({"ok":True,"schools":result})
    except Exception as e:
        current_app.loger.error("Superadmin schools listing failed: %s", e)
        return jsonify({"ok":False,"error":"Could not load schools list."}),500

@superadmin_bp.route("/api/superadmin/announce", methods=["GET"])
def api_superadmin_announce_list():
    sa,err=_require_superadmin()
    if err: return err
    try:
        con=get_db(); cur=con.cursor()
        cur.execute("SELECT id,title,body,target,CAST(posted_at AS TEXT) as posted_at FROM platform_announcements ORDER BY posted_at DESC")
        rows=to_dicts(cur.fetchall(),cur); cur.close(); con.close()
        return jsonify({"ok":True,"announcements":rows})
    except Exception as e: return jsonify({"ok":False,"error":str(e)}),500

@superadmin_bp.route("/api/superadmin/announce", methods=["POST"])
def api_superadmin_announce():
    sa,err=_require_superadmin()
    if err: return err
    d=request.json; title=d.get("title","").strip(); body=d.get("body","").strip(); target=d.get("target","all").strip()
    if not title or not body: return jsonify({"ok":False,"error":"Title and body required"}),400
    try:
        con=get_db(); cur=con.cursor()
        cur.execute("INSERT INTO platform_announcements(title,body,target) VALUES(%s,%s,%s) RETURNING id",(title,body,target))
        new_id=cur.fetchone()[0]; con.commit(); cur.close(); con.close()
        return jsonify({"ok":True,"id":new_id})
    except Exception as e: return jsonify({"ok":False,"error":str(e)}),500

@superadmin_bp.route("/api/superadmin/announce/<int:aid>", methods=["DELETE"])
def api_superadmin_announce_delete(aid):
    sa,err=_require_superadmin()
    if err: return err
    try:
        con=get_db(); cur=con.cursor()
        cur.execute("DELETE FROM platform_announcements WHERE id=%s",(aid,))
        con.commit(); cur.close(); con.close()
        return jsonify({"ok":True})
    except Exception as e: return jsonify({"ok":False,"error":str(e)}),500

@superadmin_bp.route("/api/superadmin/payment_requests", methods=["GET"])
def api_sa_payment_requests():
    sa, err = _require_superadmin()
    if err: return err
    _expire_stale_payment_requests()
    status = request.args.get("status", "pending")
    con = get_db(); cur = con.cursor()
    q = """SELECT pr.id, pr.school_id, s.school_name, pr.plan, pr.claimed_amount, pr.transaction_id,
                  pr.phone_used, CAST(pr.payment_date AS TEXT), pr.note, pr.status,
                  pr.submitted_by, CAST(pr.submitted_at AS TEXT),
                  pr.decided_by, CAST(pr.decided_at AS TEXT), pr.decision_note
           FROM payment_requests pr JOIN schools s ON s.id = pr.school_id"""
    params = ()
    if status != "all":
        q += " WHERE pr.status=%s"; params = (status,)
    q += " ORDER BY pr.submitted_at ASC"
    cur.execute(q, params)
    rows = to_dicts(cur.fetchall(), cur); cur.close(); con.close()
    return jsonify({"ok": True, "requests": rows})

@superadmin_bp.route("/api/superadmin/payment_requests/<int:rid>/approve", methods=["POST"])
def api_sa_approve_payment(rid):
    sa, err = _require_superadmin()
    if err: return err
    note = (request.json or {}).get("note", "")
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT school_id, plan, status FROM payment_requests WHERE id=%s", (rid,))
    row = cur.fetchone()
    if not row: cur.close(); con.close(); return jsonify({"ok": False, "error": "Not found"}), 404
    school_id, plan, status = row
    if status not in ("pending", "expired"):
        cur.close(); con.close(); return jsonify({"ok": False, "error": "This request was already decided"}), 409
    if plan not in SUBSCRIPTION_PLANS:
        cur.close(); con.close(); return jsonify({"ok": False, "error": "Unknown plan on this request"}), 400
    days = SUBSCRIPTION_PLANS[plan]["days"]
    cur.execute("SELECT subscription_expires_at FROM schools WHERE id=%s", (school_id,))
    exp_row = cur.fetchone()
    base = exp_row[0] if exp_row and exp_row[0] and exp_row[0] > datetime.utcnow() else datetime.utcnow()
    cur.execute("""UPDATE schools SET subscription_status='active', subscription_plan=%s,
                   subscription_expires_at=%s WHERE id=%s""",
                (plan, base + timedelta(days=days), school_id))
    cur.execute("""UPDATE payment_requests SET status='approved', decided_by=%s, decided_at=NOW(), decision_note=%s
                   WHERE id=%s""", (sa, note, rid))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok": True})

@superadmin_bp.route("/api/superadmin/payment_requests/<int:rid>/reject", methods=["POST"])
def api_sa_reject_payment(rid):
    sa, err = _require_superadmin()
    if err: return err
    note = (request.json or {}).get("note", "").strip()
    if not note: return jsonify({"ok": False, "error": "A rejection reason is required"}), 400
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT school_id, status FROM payment_requests WHERE id=%s", (rid,))
    row = cur.fetchone()
    if not row: cur.close(); con.close(); return jsonify({"ok": False, "error": "Not found"}), 404
    school_id, status = row
    if status not in ("pending", "expired"):
        cur.close(); con.close(); return jsonify({"ok": False, "error": "This request was already decided"}), 409
    cur.execute("UPDATE payment_requests SET status='rejected', decided_by=%s, decided_at=NOW(), decision_note=%s WHERE id=%s",
                (sa, note, rid))
    cur.execute("UPDATE schools SET subscription_status='inactive' WHERE id=%s AND subscription_status='pending'", (school_id,))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok": True})

@superadmin_bp.route("/api/superadmin/payment_config", methods=["GET"])
def api_sa_get_payment_config():
    sa, err = _require_superadmin()
    if err: return err
    return jsonify({"ok": True, **_platform_payment_config()})

@superadmin_bp.route("/api/superadmin/payment_config", methods=["POST"])
def api_sa_set_payment_config():
    sa, err = _require_superadmin()
    if err: return err
    d = request.json or {}
    business_name = (d.get("business_name") or "").strip()
    payment_number = (d.get("payment_number") or "").strip()
    networks = d.get("networks") or []
    if not business_name or not payment_number:
        return jsonify({"ok": False, "error": "Business name and payment number required"}), 400
    con = get_db(); cur = con.cursor()
    cur.execute("""UPDATE platform_payment_config SET business_name=%s, payment_number=%s, networks=%s, updated_at=NOW() WHERE id=1""",
                (business_name, payment_number, ",".join(networks)))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok": True})