"""
Per-student paid access ("parent access"): entitlement lookups, the Snippe
client, and payment finalization. No Flask request/response handling.

Rule: access is granted ONLY by finalize_payment(), which asks Snippe for the
payment's real status and checks the amount. Nothing the browser or a webhook
body says is trusted.
"""
import hashlib, hmac, logging, math, re, secrets
from datetime import datetime

import requests

from config import (PARENT_PLANS, SNIPPE_API_BASE, SNIPPE_API_KEY, SNIPPE_WEBHOOK_SECRET,
                    SNIPPE_MIN_AMOUNT, SNIPPE_FALLBACK_EMAIL, PUBLIC_BASE_URL)
from core.db import get_db

log = logging.getLogger(__name__)


class SnippeError(Exception):
    pass


# ── ENTITLEMENT ───────────────────────────────────────────────
def plans_public():
    return [{"key": k, "label": p["label"], "amount": p["amount"], "days": p["days"]}
            for k, p in PARENT_PLANS.items()]


def get_access(school_id, student_id):
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT plan, expires_at FROM student_access WHERE school_id=%s AND student_id=%s",
                (school_id, student_id))
    row = cur.fetchone(); cur.close(); con.close()
    if not row:
        return {"active": False, "plan": None, "plan_label": None, "expires_at": None, "days_left": 0}
    plan, exp = row
    now = datetime.utcnow()
    active = exp > now
    return {"active": active, "plan": plan,
            "plan_label": PARENT_PLANS.get(plan, {}).get("label", plan),
            "expires_at": exp.isoformat() + "Z",
            "days_left": math.ceil((exp - now).total_seconds() / 86400) if active else 0}


def has_active_access(school_id, student_id):
    if not student_id: return False
    return get_access(school_id, student_id)["active"]


# ── SNIPPE CLIENT ─────────────────────────────────────────────
def normalize_phone(raw):
    d = re.sub(r"\D", "", raw or "")
    if len(d) == 10 and d.startswith("0"): d = "255" + d[1:]
    elif len(d) == 9: d = "255" + d
    return d if re.fullmatch(r"255\d{9}", d) else None


def _headers(idem=None):
    h = {"Authorization": f"Bearer {SNIPPE_API_KEY}", "Content-Type": "application/json"}
    if idem: h["Idempotency-Key"] = idem   # Snippe: max 30 chars
    return h


def _snippe_call(method, path, **kw):
    try:
        r = requests.request(method, f"{SNIPPE_API_BASE}{path}", timeout=15, **kw)
    except requests.RequestException:
        raise SnippeError("Could not reach the payment provider. Try again in a moment.")
    try: j = r.json()
    except ValueError: raise SnippeError("Payment provider returned an invalid response")
    if r.status_code >= 400 or j.get("status") != "success":
        raise SnippeError(j.get("message") or f"Payment provider error ({r.status_code})")
    return j.get("data") or {}


def snippe_create_payment(amount, phone, first, last, email, metadata, webhook_url, idem):
    body = {"payment_type": "mobile",
            "details": {"amount": amount, "currency": "TZS"},
            "phone_number": phone,
            "customer": {"firstname": first, "lastname": last, "email": email},
            "metadata": metadata}
    if webhook_url: body["webhook_url"] = webhook_url
    return _snippe_call("POST", "/v1/payments", json=body, headers=_headers(idem))


def snippe_get_payment(reference):
    return _snippe_call("GET", f"/v1/payments/{requests.utils.quote(reference, safe='')}", headers=_headers())


def verify_webhook_signature(raw_body, headers):
    """HMAC-SHA256 of "{timestamp}.{raw_body}". If no secret is configured we
    accept the call, which is still safe: the body is never trusted, we
    re-fetch the payment from Snippe before granting anything."""
    if not SNIPPE_WEBHOOK_SECRET:
        return True
    ts  = headers.get("X-Webhook-Timestamp", "")
    sig = headers.get("X-Webhook-Signature", "")
    expected = hmac.new(SNIPPE_WEBHOOK_SECRET.encode(), ts.encode() + b"." + raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected)


# ── PAYMENT LIFECYCLE ─────────────────────────────────────────
def _mark(payment_id, status, reason=None):
    con = get_db(); cur = con.cursor()
    cur.execute("UPDATE student_payments SET status=%s, failure_reason=%s WHERE id=%s AND applied=0",
                (status, reason, payment_id))
    con.commit(); cur.close(); con.close()


def start_payment(school_id, student_id, plan_key, phone_raw, initiated_by, initiated_role):
    plan = PARENT_PLANS.get(plan_key)
    if not plan: raise ValueError("Unknown plan")
    if not SNIPPE_API_KEY: raise ValueError("Payments are not configured on the server yet")
    if plan["amount"] < SNIPPE_MIN_AMOUNT:
        raise ValueError(f"This plan costs {plan['amount']} TZS but Snippe's minimum is {SNIPPE_MIN_AMOUNT} TZS. "
                         f"Raise the price in config.py or the PARENT_PRICE_* env vars.")
    phone = normalize_phone(phone_raw)
    if not phone: raise ValueError("Enter a valid mobile number, e.g. 0712345678")

    con = get_db(); cur = con.cursor()
    cur.execute("SELECT name FROM students WHERE id=%s AND school_id=%s", (student_id, school_id))
    srow = cur.fetchone()
    if not srow:
        cur.close(); con.close(); raise ValueError("Student not found")
    cur.execute("""SELECT COUNT(*) FROM student_payments WHERE school_id=%s AND student_id=%s
                   AND created_at > NOW() - INTERVAL '1 hour'""", (school_id, student_id))
    if cur.fetchone()[0] >= 5:
        cur.close(); con.close()
        raise ValueError("Too many payment attempts for this student. Wait an hour and try again.")
    idem = "dd" + secrets.token_hex(12)          # 26 chars
    cur.execute("""INSERT INTO student_payments(school_id,student_id,plan,duration_days,amount,currency,
                                                idempotency_key,phone,status,initiated_by,initiated_role)
                   VALUES(%s,%s,%s,%s,%s,'TZS',%s,%s,'pending',%s,%s) RETURNING id""",
                (school_id, student_id, plan_key, plan["days"], plan["amount"], idem, phone,
                 initiated_by, initiated_role))
    pid = cur.fetchone()[0]; con.commit(); cur.close(); con.close()

    parts = (srow[0] or "").split()
    first = parts[0] if parts else "Parent"
    last  = " ".join(parts[1:]) or "Parent"
    webhook = f"{PUBLIC_BASE_URL}/api/access/webhook" if PUBLIC_BASE_URL.startswith("https://") else None
    try:
        data = snippe_create_payment(plan["amount"], phone, first, last, SNIPPE_FALLBACK_EMAIL,
                                     {"payment_id": str(pid), "student_id": str(student_id),
                                      "school_id": str(school_id)}, webhook, idem)
    except SnippeError as e:
        _mark(pid, "failed", str(e)); raise
    ref = data.get("reference")
    if not ref:
        _mark(pid, "failed", "No reference returned"); raise SnippeError("Provider did not return a payment reference")
    con = get_db(); cur = con.cursor()
    cur.execute("UPDATE student_payments SET reference=%s WHERE id=%s", (ref, pid))
    con.commit(); cur.close(); con.close()
    return {"payment_id": pid, "reference": ref, "amount": plan["amount"], "plan": plan_key,
            "message": "Payment prompt sent. Approve it on the phone with your mobile-money PIN."}


def _parse_ts(s):
    try: return datetime.strptime(str(s)[:19], "%Y-%m-%dT%H:%M:%S")
    except (ValueError, TypeError): return None


def finalize_payment(payment_id):
    """Ask Snippe for the truth and, if (and only if) it's a completed payment
    for the right amount, grant/extend access. Idempotent and safe to call
    concurrently from the webhook and the poller. Returns the resulting status."""
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT reference, applied, status FROM student_payments WHERE id=%s", (payment_id,))
    row = cur.fetchone(); cur.close(); con.close()
    if not row: return None
    reference, applied, status = row
    if applied: return "completed"
    if not reference: return status

    try:
        data = snippe_get_payment(reference)
    except SnippeError as e:
        log.warning("Snippe status check failed for payment %s: %s", payment_id, e)
        return status
    remote = (data.get("status") or "").lower()
    if remote not in ("completed", "failed", "voided", "expired"):
        return "pending"

    con = get_db(); cur = con.cursor()
    try:
        cur.execute("""SELECT school_id,student_id,plan,duration_days,amount,applied
                       FROM student_payments WHERE id=%s FOR UPDATE""", (payment_id,))
        school_id, student_id, plan, days, amount, applied = cur.fetchone()
        if applied:
            con.commit(); return "completed"
        if remote != "completed":
            cur.execute("UPDATE student_payments SET status=%s, failure_reason=%s WHERE id=%s",
                        (remote, data.get("failure_reason"), payment_id))
            con.commit(); return remote

        amt = data.get("amount") or {}
        try: paid_value = int(amt.get("value"))
        except (TypeError, ValueError): paid_value = None
        if paid_value is None or paid_value < amount or (amt.get("currency") or "TZS") != "TZS":
            cur.execute("UPDATE student_payments SET status='amount_mismatch', failure_reason=%s WHERE id=%s",
                        (f"Expected {amount} TZS, provider reported {amt.get('value')} {amt.get('currency')}", payment_id))
            con.commit(); return "amount_mismatch"

        # Atomic grant/extend: new expiry = max(current expiry, now) + plan days
        cur.execute("""INSERT INTO student_access(school_id,student_id,plan,expires_at,updated_at)
                       VALUES(%s,%s,%s,(NOW() AT TIME ZONE 'utc') + (%s * INTERVAL '1 day'),NOW())
                       ON CONFLICT(school_id,student_id) DO UPDATE SET
                           plan = EXCLUDED.plan,
                           expires_at = GREATEST(student_access.expires_at, NOW() AT TIME ZONE 'utc')
                                        + (%s * INTERVAL '1 day'),
                           updated_at = NOW()
                       RETURNING expires_at""", (school_id, student_id, plan, days, days))
        new_exp = cur.fetchone()[0]
        cur.execute("""UPDATE student_payments SET status='completed', applied=1, paid_at=%s,
                       expires_at=%s, method=%s WHERE id=%s""",
                    (_parse_ts(data.get("completed_at")) or datetime.utcnow(), new_exp,
                     (data.get("channel") or {}).get("provider"), payment_id))
        con.commit(); return "completed"
    except Exception:
        con.rollback(); raise
    finally:
        cur.close(); con.close()


def refresh_pending(school_id, student_id):
    """Re-check this student's pending payments so status pages are honest even without a webhook."""
    con = get_db(); cur = con.cursor()
    cur.execute("""SELECT id FROM student_payments WHERE school_id=%s AND student_id=%s
                   AND applied=0 AND status='pending' AND reference IS NOT NULL
                   ORDER BY id DESC LIMIT 3""", (school_id, student_id))
    ids = [r[0] for r in cur.fetchall()]; cur.close(); con.close()
    for pid in ids:
        try: finalize_payment(pid)
        except Exception: log.exception("finalize_payment failed for %s", pid)