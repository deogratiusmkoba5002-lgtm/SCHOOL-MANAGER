"""
Subscription logic: active-subscription check, lazy expiry of stale payment
requests, the @subscription_required route guard, and the platform payment
config lookup.
"""
from datetime import datetime
from functools import wraps
from flask import g, jsonify
from core.db import get_db
from config import SCHOOL_SUBSCRIPTION_ENFORCED

def is_subscribed(school_id):
    if not SCHOOL_SUBSCRIPTION_ENFORCED: return True
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT subscription_exempt, subscription_status, subscription_expires_at FROM schools WHERE id=%s", (school_id,))
    row = cur.fetchone(); cur.close(); con.close()
    if not row: return False
    exempt, status, expires_at = row
    if exempt: return True
    return bool(status == "active" and expires_at and expires_at > datetime.utcnow())


def _expire_stale_payment_requests(school_id=None):
    """Lazily flips any 'pending' request older than 48h to 'expired'. Called
    at the top of every read/write path that touches payment_requests, so the
    transition happens the moment anyone looks — no scheduler needed. Rows are
    never deleted; only their status changes, preserving the audit trail."""
    con = get_db(); cur = con.cursor()
    if school_id:
        cur.execute("""UPDATE payment_requests SET status='expired'
                       WHERE status='pending' AND school_id=%s
                       AND submitted_at < NOW() - INTERVAL '48 hours'""", (school_id,))
    else:
        cur.execute("""UPDATE payment_requests SET status='expired'
                       WHERE status='pending' AND submitted_at < NOW() - INTERVAL '48 hours'""")
    con.commit(); cur.close(); con.close()


def subscription_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        sid = g.school_id
        if not is_subscribed(sid):
            return jsonify({"ok": False, "error": "subscription_required",
                             "message": "This feature requires an active subscription."}), 402
        return f(*args, **kwargs)
    return wrapper


def _platform_payment_config():
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT business_name, payment_number, networks FROM platform_payment_config WHERE id=1")
    row = cur.fetchone(); cur.close(); con.close()
    if not row: return {"business_name": "", "payment_number": "", "networks": []}
    return {"business_name": row[0], "payment_number": row[1],
            "networks": row[2].split(",") if row[2] else []}