"""
Parent-access routes: status, start a payment, manual re-check, Snippe webhook.
"""
import json
from flask import Blueprint, request, jsonify, g

from core.db import get_db, to_dicts
from core.auth import require_auth, require_role
from services.access import (
    get_access, plans_public, start_payment, finalize_payment, refresh_pending,
    verify_webhook_signature, SnippeError,
)
from core.ratelimit import rate_limit

access_bp = Blueprint("access", __name__)


def _resolve_student_id():
    """Parents are pinned to their own student. Admins/teachers must name a
    student that belongs to THEIR school."""
    if g.role == "parent":
        return g.student_id
    raw = request.args.get("student_id") or (request.get_json(silent=True) or {}).get("student_id")
    try: stid = int(raw)
    except (TypeError, ValueError): return None
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT 1 FROM students WHERE id=%s AND school_id=%s", (stid, g.school_id))
    ok = cur.fetchone(); cur.close(); con.close()
    return stid if ok else None


@access_bp.route("/api/access/status", methods=["GET"])
@require_auth
@require_role("parent", "admin", "teacher")
def api_access_status():
    stid = _resolve_student_id()
    if not stid: return jsonify({"ok": False, "error": "Student not found"}), 404
    refresh_pending(g.school_id, stid)
    acc = get_access(g.school_id, stid)
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT name FROM students WHERE id=%s AND school_id=%s", (stid, g.school_id))
    name = cur.fetchone()[0]
    cur.execute("""SELECT id,plan,amount,status,method,paid_at,expires_at,created_at,initiated_role
                   FROM student_payments WHERE school_id=%s AND student_id=%s
                   ORDER BY id DESC LIMIT 10""", (g.school_id, stid))
    hist = to_dicts(cur.fetchall(), cur); cur.close(); con.close()
    for h in hist:
        for k in ("paid_at", "expires_at", "created_at"):
            if h[k]: h[k] = h[k].isoformat() + "Z"
    pending = next((h for h in hist if h["status"] == "pending"), None)
    return jsonify({"ok": True, "student_id": stid, "student_name": name, **acc,
                    "plans": plans_public(), "pending": pending, "history": hist})


@access_bp.route("/api/access/pay", methods=["POST"])
@require_auth
@require_role("parent", "admin")
def api_access_pay():
    d = request.get_json(silent=True) or {}
    stid = _resolve_student_id()
    if not stid: return jsonify({"ok": False, "error": "Student not found"}), 404
    try:
        res = start_payment(g.school_id, stid, (d.get("plan") or "").strip(),
                            d.get("phone") or "", g.username, g.role)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except SnippeError as e:
        return jsonify({"ok": False, "error": str(e)}), 502
    return jsonify({"ok": True, **res})


@access_bp.route("/api/access/check/<int:payment_id>", methods=["POST"])
@require_auth
@require_role("parent", "admin")
def api_access_check(payment_id):
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT student_id FROM student_payments WHERE id=%s AND school_id=%s", (payment_id, g.school_id))
    row = cur.fetchone(); cur.close(); con.close()
    if not row: return jsonify({"ok": False, "error": "Payment not found"}), 404
    if g.role == "parent" and row[0] != g.student_id:
        return jsonify({"ok": False, "error": "Access denied"}), 403
    status = finalize_payment(payment_id)
    return jsonify({"ok": True, "status": status, "access": get_access(g.school_id, row[0])})


@access_bp.route("/api/access/webhook", methods=["POST"])
@rate_limit("access_webhook", max_attempts=120, window_minutes=5, by="ip")
def api_access_webhook():
    raw = request.get_data()
    if not verify_webhook_signature(raw, request.headers):
        return "Invalid signature", 400
    try: event = json.loads(raw.decode("utf-8"))
    except ValueError: return "Bad JSON", 400
    etype = event.get("type") or event.get("event") or ""
    data  = event.get("data") or event          # legacy flat format fallback
    ref   = data.get("reference")
    if etype.startswith("payment.") and ref:
        con = get_db(); cur = con.cursor()
        cur.execute("SELECT id FROM student_payments WHERE reference=%s", (ref,))
        row = cur.fetchone(); cur.close(); con.close()
        if row:                                  # unknown references are ignored
            finalize_payment(row[0])             # re-verifies with Snippe; body isn't trusted
    return "OK", 200