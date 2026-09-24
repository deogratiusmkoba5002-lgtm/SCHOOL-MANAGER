from datetime import datetime, timedelta
import psycopg2
from flask import Blueprint, request, jsonify, g

from config import SUBSCRIPTION_PLANS, SCHOOL_SUBSCRIPTION_ENFORCED
from core.db import get_db
from core.auth import require_auth, require_role
from services.subscriptions import is_subscribed, _expire_stale_payment_requests, _platform_payment_config

subscription_bp = Blueprint("subscription", __name__)


@subscription_bp.route("/api/subscription/status", methods=["GET"])
@require_auth
@require_role("admin")
def api_subscription_status():
    sid = g.school_id
    _expire_stale_payment_requests(sid)
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT subscription_exempt, subscription_status, subscription_plan, subscription_expires_at FROM schools WHERE id=%s", (sid,))
    row = cur.fetchone()
    if not row:
        cur.close(); con.close(); return jsonify({"ok": False}), 404
    exempt, status, plan, expires_at = row

    cur.execute("""SELECT id, plan, claimed_amount, transaction_id, phone_used,
                          CAST(payment_date AS TEXT), note, status, CAST(submitted_at AS TEXT), decision_note
                   FROM payment_requests WHERE school_id=%s ORDER BY id DESC LIMIT 1""", (sid,))
    req_row = cur.fetchone(); cur.close(); con.close()

    pending_request = None
    last_decision = None
    if req_row:
        (rid, rplan, ramount, rtxn, rphone, rdate, rnote, rstatus, rsubmitted, rdecision_note) = req_row
        if rstatus == "pending":
            pending_request = {"id": rid, "plan": rplan, "claimed_amount": ramount,
                                "transaction_id": rtxn, "phone_used": rphone,
                                "payment_date": rdate, "note": rnote, "submitted_at": rsubmitted}
        elif rstatus == "expired":
            last_decision = {"status": "expired",
                              "note": "This payment request expired because it was not verified within 48 hours. "
                                      "If you already paid, contact support. Otherwise, submit a new payment request."}
        elif rstatus == "rejected":
            last_decision = {"status": "rejected", "note": rdecision_note}

    return jsonify({"ok": True, "active": is_subscribed(sid), "exempt": bool(exempt) or not SCHOOL_SUBSCRIPTION_ENFORCED,
                     "plan": plan, "status": status,
                     "expires_at": expires_at.isoformat() if expires_at else None,
                     "plans": SUBSCRIPTION_PLANS,
                     "payment_info": _platform_payment_config(),
                     "pending_request": pending_request,
                     "last_decision": last_decision})
@subscription_bp.route("/api/subscription/select_free", methods=["POST"])
@require_auth
@require_role("admin")
def api_select_free_plan():
    sid = g.school_id
    con = get_db(); cur = con.cursor()
    cur.execute("""UPDATE schools SET subscription_status='active', subscription_plan='free',
                   subscription_expires_at=%s WHERE id=%s""",
                (datetime.utcnow() + timedelta(days=SUBSCRIPTION_PLANS["free"]["days"]), sid))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok": True})

@subscription_bp.route("/api/subscription/request", methods=["POST"])
@require_auth
@require_role("admin")
def api_submit_payment_request():
    sid = g.school_id
    _expire_stale_payment_requests(sid)
    d = request.json or {}
    plan = d.get("plan", "")
    if plan not in SUBSCRIPTION_PLANS or plan == "free":
        return jsonify({"ok": False, "error": "Invalid plan"}), 400
    txn_id  = (d.get("transaction_id") or "").strip()
    phone   = (d.get("phone_used") or "").strip()
    pay_date= (d.get("payment_date") or "").strip()
    note    = (d.get("note") or "").strip()
    try:
        amount = float(d.get("claimed_amount"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Amount paid is required"}), 400
    if not txn_id:   return jsonify({"ok": False, "error": "Transaction ID is required"}), 400
    if not phone:    return jsonify({"ok": False, "error": "Phone number used is required"}), 400
    if amount <= 0:  return jsonify({"ok": False, "error": "Amount paid must be greater than zero"}), 400
    if not pay_date: return jsonify({"ok": False, "error": "Payment date is required"}), 400

    con = get_db(); cur = con.cursor()

    # Abuse guard: counts every submission attempt (any status) in the last
    # 24h, so rapid cancel-and-resubmit cycling still counts against the cap.
    cur.execute("SELECT COUNT(*) FROM payment_requests WHERE school_id=%s AND submitted_at > NOW() - INTERVAL '24 hours'", (sid,))
    if cur.fetchone()[0] >= 5:
        cur.close(); con.close()
        return jsonify({"ok": False, "error": "Too many verification requests. Please contact support if you continue experiencing problems."}), 429

    cur.execute("SELECT id FROM payment_requests WHERE school_id=%s AND status='pending'", (sid,))
    if cur.fetchone():
        cur.close(); con.close()
        return jsonify({"ok": False, "error": "You already have a payment request pending verification. Cancel it below before submitting a new one."}), 409
    try:
        cur.execute("""INSERT INTO payment_requests(school_id,plan,claimed_amount,transaction_id,phone_used,payment_date,note,status,submitted_by)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,'pending',%s) RETURNING id""",
                    (sid, plan, amount, txn_id, phone, pay_date, note, d.get("username", "")))
        new_id = cur.fetchone()[0]
        cur.execute("UPDATE schools SET subscription_status='pending' WHERE id=%s", (sid,))
        con.commit()
    except psycopg2.errors.UniqueViolation:
        con.rollback(); cur.close(); con.close()
        return jsonify({"ok": False, "error": "This transaction ID has already been submitted. If you believe this is an error, contact support."}), 409
    cur.close(); con.close()
    return jsonify({"ok": True, "id": new_id})

@subscription_bp.route("/api/subscription/request/cancel", methods=["POST"])
@require_auth
@require_role("admin")
def api_cancel_payment_request():
    sid = g.school_id
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT id FROM payment_requests WHERE school_id=%s AND status='pending' ORDER BY id DESC LIMIT 1", (sid,))
    row = cur.fetchone()
    if not row:
        cur.close(); con.close(); return jsonify({"ok": False, "error": "No pending request to cancel"}), 404
    cur.execute("UPDATE payment_requests SET status='cancelled', decided_at=NOW() WHERE id=%s", (row[0],))
    cur.execute("UPDATE schools SET subscription_status='inactive' WHERE id=%s AND subscription_status='pending'", (sid,))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok": True})


