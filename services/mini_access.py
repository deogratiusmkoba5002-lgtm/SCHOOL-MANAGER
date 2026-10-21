"""
DrDemic Mini parent subscription. Same rule as services/access.py: access is granted ONLY by
finalize_payment(), which asks Snippe for the real status and checks the amount.
Reuses the Snippe client from services.access. No Flask request/response handling.
"""
import logging, math, secrets
from datetime import datetime

from config import MINI_PLANS
from core.db import get_db
from services import access as A

log = logging.getLogger(__name__)


def plans_public():
    return [{"key": k, "label": p["label"], "amount": p["amount"], "days": p["days"]}
            for k, p in MINI_PLANS.items()]


def get_access(user_id):
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT plan, expires_at FROM mini_access WHERE user_id=%s", (user_id,))
    row = cur.fetchone(); cur.close(); con.close()
    if not row:
        return {"active": False, "plan": None, "plan_label": None, "expires_at": None, "days_left": 0}
    plan, exp = row
    now = datetime.utcnow()
    active = exp > now
    return {"active": active, "plan": plan,
            "plan_label": MINI_PLANS.get(plan, {}).get("label", plan),
            "expires_at": exp.isoformat() + "Z",
            "days_left": math.ceil((exp - now).total_seconds() / 86400) if active else 0}


def _mark(pid, status, reason=None):
    con = get_db(); cur = con.cursor()
    cur.execute("UPDATE mini_payments SET status=%s, failure_reason=%s WHERE id=%s AND applied=0",
                (status, reason, pid))
    con.commit(); cur.close(); con.close()


def start_payment(user_id, plan_key, phone_raw):
    plan = MINI_PLANS.get(plan_key)
    if not plan: raise ValueError("Unknown plan")
    if not A.SNIPPE_API_KEY: raise ValueError("Payments are not configured on the server yet")
    if plan["amount"] < A.SNIPPE_MIN_AMOUNT:
        raise ValueError(f"This plan costs {plan['amount']} TZS but Snippe's minimum is {A.SNIPPE_MIN_AMOUNT} TZS.")
    phone = A.normalize_phone(phone_raw)
    if not phone: raise ValueError("Enter a valid mobile number, e.g. 0712345678")

    con = get_db(); cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM mini_payments WHERE user_id=%s AND created_at > NOW() - INTERVAL '1 hour'",
                (user_id,))
    if cur.fetchone()[0] >= 5:
        cur.close(); con.close()
        raise ValueError("Too many payment attempts. Wait an hour and try again.")
    cur.execute("SELECT name FROM mini_students WHERE parent_user_id=%s LIMIT 1", (user_id,))
    srow = cur.fetchone()
    idem = "mn" + secrets.token_hex(12)                       # 26 chars (Snippe max 30)
    cur.execute("""INSERT INTO mini_payments(user_id,plan,duration_days,amount,idempotency_key,phone,status)
                   VALUES(%s,%s,%s,%s,%s,%s,'pending') RETURNING id""",
                (user_id, plan_key, plan["days"], plan["amount"], idem, phone))
    pid = cur.fetchone()[0]; con.commit(); cur.close(); con.close()

    parts = ((srow[0] if srow else "") or "").split()
    first = parts[0] if parts else "Parent"
    last = " ".join(parts[1:]) or "Parent"
    webhook = f"{A.PUBLIC_BASE_URL}/api/access/webhook" if A.PUBLIC_BASE_URL.startswith("https://") else None
    try:
        data = A.snippe_create_payment(plan["amount"], phone, first, last, A.SNIPPE_FALLBACK_EMAIL,
                                       {"mini_payment_id": str(pid), "mini_user_id": str(user_id)}, webhook, idem)
    except A.SnippeError as e:
        _mark(pid, "failed", str(e)); raise
    ref = data.get("reference")
    if not ref:
        _mark(pid, "failed", "No reference returned"); raise A.SnippeError("Provider did not return a payment reference")
    con = get_db(); cur = con.cursor()
    cur.execute("UPDATE mini_payments SET reference=%s WHERE id=%s", (ref, pid))
    con.commit(); cur.close(); con.close()
    return {"payment_id": pid, "reference": ref, "amount": plan["amount"], "plan": plan_key,
            "message": "Payment prompt sent. Approve it on the phone with your mobile-money PIN."}


def finalize_payment(pid):
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT reference, applied, status FROM mini_payments WHERE id=%s", (pid,))
    row = cur.fetchone(); cur.close(); con.close()
    if not row: return None
    reference, applied, status = row
    if applied: return "completed"
    if not reference: return status
    try:
        data = A.snippe_get_payment(reference)
    except A.SnippeError as e:
        log.warning("Snippe status check failed for mini payment %s: %s", pid, e)
        return status
    remote = (data.get("status") or "").lower()
    if remote not in ("completed", "failed", "voided", "expired"):
        return "pending"

    con = get_db(); cur = con.cursor()
    try:
        cur.execute("SELECT user_id,plan,duration_days,amount,applied FROM mini_payments WHERE id=%s FOR UPDATE", (pid,))
        user_id, plan, days, amount, applied = cur.fetchone()
        if applied:
            con.commit(); return "completed"
        if remote != "completed":
            cur.execute("UPDATE mini_payments SET status=%s, failure_reason=%s WHERE id=%s",
                        (remote, data.get("failure_reason"), pid))
            con.commit(); return remote
        amt = data.get("amount") or {}
        try: paid = int(amt.get("value"))
        except (TypeError, ValueError): paid = None
        if paid is None or paid < amount or (amt.get("currency") or "TZS") != "TZS":
            cur.execute("UPDATE mini_payments SET status='amount_mismatch', failure_reason=%s WHERE id=%s",
                        (f"Expected {amount} TZS, provider reported {amt.get('value')} {amt.get('currency')}", pid))
            con.commit(); return "amount_mismatch"
        cur.execute("""INSERT INTO mini_access(user_id,plan,expires_at,updated_at)
                       VALUES(%s,%s,(NOW() AT TIME ZONE 'utc') + (%s * INTERVAL '1 day'),NOW())
                       ON CONFLICT(user_id) DO UPDATE SET
                           plan = EXCLUDED.plan,
                           expires_at = GREATEST(mini_access.expires_at, NOW() AT TIME ZONE 'utc')
                                        + (%s * INTERVAL '1 day'),
                           updated_at = NOW()
                       RETURNING expires_at""", (user_id, plan, days, days))
        new_exp = cur.fetchone()[0]
        cur.execute("""UPDATE mini_payments SET status='completed', applied=1, paid_at=%s, expires_at=%s WHERE id=%s""",
                    (A._parse_ts(data.get("completed_at")) or datetime.utcnow(), new_exp, pid))
        con.commit()
        try:
            from services.mini_agents import on_payment_completed
            on_payment_completed(pid)
        except Exception:
            log.exception("agent qualification failed for mini payment %s", pid)
        return "completed"
    except Exception:
        con.rollback(); raise
    finally:
        cur.close(); con.close()


def refresh_pending(user_id):
    con = get_db(); cur = con.cursor()
    cur.execute("""SELECT id FROM mini_payments WHERE user_id=%s AND applied=0 AND status='pending'
                   AND reference IS NOT NULL ORDER BY id DESC LIMIT 3""", (user_id,))
    ids = [r[0] for r in cur.fetchall()]; cur.close(); con.close()
    for pid in ids:
        try: finalize_payment(pid)
        except Exception: log.exception("mini finalize_payment failed for %s", pid)

# ── Student-level PDF access (admin can pay for a parent without a smartphone) ──
def student_access_active(owner_id, nn):
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT expires_at FROM mini_student_access WHERE owner_id=%s AND name_norm=%s", (owner_id, nn))
    row = cur.fetchone(); cur.close(); con.close()
    return bool(row and row[0] > datetime.utcnow())


def has_pdf_access(owner_id, nn):
    """PDF allowed if the student itself is paid for, OR the linked parent account has an active subscription."""
    if student_access_active(owner_id, nn):
        return True
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT parent_user_id FROM mini_students WHERE owner_id=%s AND name_norm=%s", (owner_id, nn))
    row = cur.fetchone(); cur.close(); con.close()
    return bool(row and row[0] and get_access(row[0])["active"])


def start_student_payment(owner_id, nn, student_name, plan_key, phone_raw):
    plan = MINI_PLANS.get(plan_key)
    if not plan: raise ValueError("Unknown plan")
    if not A.SNIPPE_API_KEY: raise ValueError("Payments are not configured on the server yet")
    if plan["amount"] < A.SNIPPE_MIN_AMOUNT:
        raise ValueError(f"This plan costs {plan['amount']} TZS but Snippe's minimum is {A.SNIPPE_MIN_AMOUNT} TZS.")
    phone = A.normalize_phone(phone_raw)
    if not phone: raise ValueError("Enter a valid mobile number, e.g. 0712345678")

    con = get_db(); cur = con.cursor()
    cur.execute("""SELECT COUNT(*) FROM mini_student_payments WHERE owner_id=%s AND name_norm=%s
                   AND created_at > NOW() - INTERVAL '1 hour'""", (owner_id, nn))
    if cur.fetchone()[0] >= 5:
        cur.close(); con.close()
        raise ValueError("Too many payment attempts for this student. Wait an hour and try again.")
    idem = "ms" + secrets.token_hex(12)
    cur.execute("""INSERT INTO mini_student_payments(owner_id,name_norm,plan,duration_days,amount,idempotency_key,phone,status)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,'pending') RETURNING id""",
                (owner_id, nn, plan_key, plan["days"], plan["amount"], idem, phone))
    pid = cur.fetchone()[0]; con.commit(); cur.close(); con.close()

    parts = (student_name or "").split()
    first = parts[0] if parts else "Parent"
    last = " ".join(parts[1:]) or "Parent"
    webhook = f"{A.PUBLIC_BASE_URL}/api/access/webhook" if A.PUBLIC_BASE_URL.startswith("https://") else None
    try:
        data = A.snippe_create_payment(plan["amount"], phone, first, last, A.SNIPPE_FALLBACK_EMAIL,
                                       {"mini_student_payment_id": str(pid), "mini_owner_id": str(owner_id)},
                                       webhook, idem)
    except A.SnippeError as e:
        _mark_student(pid, "failed", str(e)); raise
    ref = data.get("reference")
    if not ref:
        _mark_student(pid, "failed", "No reference returned")
        raise A.SnippeError("Provider did not return a payment reference")
    con = get_db(); cur = con.cursor()
    cur.execute("UPDATE mini_student_payments SET reference=%s WHERE id=%s", (ref, pid))
    con.commit(); cur.close(); con.close()
    return {"payment_id": pid, "reference": ref, "amount": plan["amount"], "plan": plan_key}


def _mark_student(pid, status, reason=None):
    con = get_db(); cur = con.cursor()
    cur.execute("UPDATE mini_student_payments SET status=%s, failure_reason=%s WHERE id=%s AND applied=0",
                (status, reason, pid))
    con.commit(); cur.close(); con.close()


def finalize_student_payment(pid):
    """Same rule as every other payment: ask Snippe for the truth, check the amount, then grant."""
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT reference, applied, status FROM mini_student_payments WHERE id=%s", (pid,))
    row = cur.fetchone(); cur.close(); con.close()
    if not row: return None
    reference, applied, status = row
    if applied: return "completed"
    if not reference: return status
    try:
        data = A.snippe_get_payment(reference)
    except A.SnippeError as e:
        log.warning("Snippe status check failed for mini student payment %s: %s", pid, e)
        return status
    remote = (data.get("status") or "").lower()
    if remote not in ("completed", "failed", "voided", "expired"):
        return "pending"

    con = get_db(); cur = con.cursor()
    try:
        cur.execute("""SELECT owner_id,name_norm,plan,duration_days,amount,applied
                       FROM mini_student_payments WHERE id=%s FOR UPDATE""", (pid,))
        owner_id, nn, plan, days, amount, applied = cur.fetchone()
        if applied:
            con.commit(); return "completed"
        if remote != "completed":
            cur.execute("UPDATE mini_student_payments SET status=%s, failure_reason=%s WHERE id=%s",
                        (remote, data.get("failure_reason"), pid))
            con.commit(); return remote
        amt = data.get("amount") or {}
        try: paid = int(amt.get("value"))
        except (TypeError, ValueError): paid = None
        if paid is None or paid < amount or (amt.get("currency") or "TZS") != "TZS":
            cur.execute("UPDATE mini_student_payments SET status='amount_mismatch', failure_reason=%s WHERE id=%s",
                        (f"Expected {amount} TZS, provider reported {amt.get('value')} {amt.get('currency')}", pid))
            con.commit(); return "amount_mismatch"
        cur.execute("""INSERT INTO mini_student_access(owner_id,name_norm,plan,expires_at,updated_at)
                       VALUES(%s,%s,%s,(NOW() AT TIME ZONE 'utc') + (%s * INTERVAL '1 day'),NOW())
                       ON CONFLICT(owner_id,name_norm) DO UPDATE SET
                           plan = EXCLUDED.plan,
                           expires_at = GREATEST(mini_student_access.expires_at, NOW() AT TIME ZONE 'utc')
                                        + (%s * INTERVAL '1 day'),
                           updated_at = NOW()
                       RETURNING expires_at""", (owner_id, nn, plan, days, days))
        new_exp = cur.fetchone()[0]
        # If this child's parent already has an account, unlock their account too.
        cur.execute("SELECT parent_user_id FROM mini_students WHERE owner_id=%s AND name_norm=%s", (owner_id, nn))
        p = cur.fetchone()
        if p and p[0]:
            cur.execute("""INSERT INTO mini_access(user_id,plan,expires_at,updated_at)
                           VALUES(%s,%s,(NOW() AT TIME ZONE 'utc') + (%s * INTERVAL '1 day'),NOW())
                           ON CONFLICT(user_id) DO UPDATE SET
                               plan = EXCLUDED.plan,
                               expires_at = GREATEST(mini_access.expires_at, NOW() AT TIME ZONE 'utc')
                                            + (%s * INTERVAL '1 day'),
                               updated_at = NOW()""", (p[0], plan, days, days))
        cur.execute("""UPDATE mini_student_payments SET status='completed', applied=1, paid_at=%s, expires_at=%s
                       WHERE id=%s""", (A._parse_ts(data.get("completed_at")) or datetime.utcnow(), new_exp, pid))
        con.commit()
        return "completed"
    except Exception:
        con.rollback(); raise
    finally:
        cur.close(); con.close()