"""DrDemic Tuition: course access + Snippe payments. Same rule as access.py: access is granted ONLY by
finalize_payment(), which asks Snippe for the real status and checks the amount. No Flask."""
import logging, secrets
from datetime import datetime, timezone

from config import TUITION_FEE_PERCENT
from core.db import get_db
from services import access as A

log = logging.getLogger(__name__)


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def has_access(cur, student_id, course_id, price):
    if (price or 0) <= 0:
        return True
    cur.execute("SELECT expires_at FROM tuition_access WHERE student_id=%s AND course_id=%s", (student_id, course_id))
    r = cur.fetchone()
    return bool(r and r[0] > _now())


def start_payment(student_id, course_id, phone_raw):
    if not A.SNIPPE_API_KEY:
        raise ValueError("Payments are not configured on the server yet")
    phone = A.normalize_phone(phone_raw)
    if not phone:
        raise ValueError("Enter a valid mobile number, e.g. 0712345678")
    if not course_id:
        raise ValueError("Course not found")
    con = get_db(); cur = con.cursor()
    try:
        cur.execute("""SELECT c.price_tzs, c.access_days, u.full_name
                       FROM tuition_enrollments e JOIN tuition_courses c ON c.id=e.course_id
                       JOIN tuition_users u ON u.id=e.student_id
                       WHERE e.student_id=%s AND e.course_id=%s""", (student_id, course_id))
        row = cur.fetchone()
        if not row:
            raise ValueError("Course not found")
        price, days, name = row
        if price <= 0:
            raise ValueError("This course is free")
        if price < A.SNIPPE_MIN_AMOUNT:
            raise ValueError(f"Course price {price} TZS is below the provider minimum of {A.SNIPPE_MIN_AMOUNT} TZS")
        cur.execute("SELECT COUNT(*) FROM tuition_payments WHERE student_id=%s AND created_at > NOW() - INTERVAL '1 hour'",
                    (student_id,))
        if cur.fetchone()[0] >= 5:
            raise ValueError("Too many payment attempts. Wait an hour and try again.")
        idem = "tu" + secrets.token_hex(12)
        fee = price * TUITION_FEE_PERCENT // 100
        cur.execute("""INSERT INTO tuition_payments(student_id,course_id,amount,fee_tzs,duration_days,idempotency_key,phone,status)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,'pending') RETURNING id""",
                    (student_id, course_id, price, fee, days, idem, phone))
        pid = cur.fetchone()[0]
        con.commit()
    finally:
        cur.close(); con.close()

    parts = (name or "").split()
    first = parts[0] if parts else "Student"
    last = " ".join(parts[1:]) or "Student"
    webhook = f"{A.PUBLIC_BASE_URL}/api/access/webhook" if A.PUBLIC_BASE_URL.startswith("https://") else None
    try:
        data = A.snippe_create_payment(price, phone, first, last, A.SNIPPE_FALLBACK_EMAIL,
                                       {"tuition_payment_id": str(pid), "course_id": str(course_id)}, webhook, idem)
    except A.SnippeError as e:
        _mark(pid, "failed", str(e)); raise
    ref = data.get("reference")
    if not ref:
        _mark(pid, "failed", "No reference returned"); raise A.SnippeError("Provider did not return a payment reference")
    con = get_db(); cur = con.cursor()
    cur.execute("UPDATE tuition_payments SET reference=%s WHERE id=%s", (ref, pid))
    con.commit(); cur.close(); con.close()
    return {"payment_id": pid, "reference": ref, "amount": price,
            "message": "Payment prompt sent. Approve it on the phone with your mobile-money PIN."}


def _mark(pid, status, reason=None):
    con = get_db(); cur = con.cursor()
    cur.execute("UPDATE tuition_payments SET status=%s, failure_reason=%s WHERE id=%s AND applied=0", (status, reason, pid))
    con.commit(); cur.close(); con.close()


def finalize_payment(pid):
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT reference, applied, status FROM tuition_payments WHERE id=%s", (pid,))
    row = cur.fetchone(); cur.close(); con.close()
    if not row: return None
    reference, applied, status = row
    if applied: return "completed"
    if not reference: return status
    try:
        data = A.snippe_get_payment(reference)
    except A.SnippeError as e:
        log.warning("Snippe status check failed for tuition payment %s: %s", pid, e)
        return status
    remote = (data.get("status") or "").lower()
    if remote not in ("completed", "failed", "voided", "expired"):
        return "pending"

    con = get_db(); cur = con.cursor()
    try:
        cur.execute("SELECT student_id,course_id,duration_days,amount,applied FROM tuition_payments WHERE id=%s FOR UPDATE", (pid,))
        student_id, course_id, days, amount, applied = cur.fetchone()
        if applied:
            con.commit(); return "completed"
        if remote != "completed":
            cur.execute("UPDATE tuition_payments SET status=%s, failure_reason=%s WHERE id=%s",
                        (remote, data.get("failure_reason"), pid))
            con.commit(); return remote
        amt = data.get("amount") or {}
        try: paid = int(amt.get("value"))
        except (TypeError, ValueError): paid = None
        if paid is None or paid < amount or (amt.get("currency") or "TZS") != "TZS":
            cur.execute("UPDATE tuition_payments SET status='amount_mismatch', failure_reason=%s WHERE id=%s",
                        (f"Expected {amount} TZS, provider reported {amt.get('value')} {amt.get('currency')}", pid))
            con.commit(); return "amount_mismatch"
        cur.execute("""INSERT INTO tuition_access(student_id,course_id,expires_at,updated_at)
                       VALUES(%s,%s,(NOW() AT TIME ZONE 'utc') + (%s * INTERVAL '1 day'),NOW())
                       ON CONFLICT(student_id,course_id) DO UPDATE SET
                           expires_at = GREATEST(tuition_access.expires_at, NOW() AT TIME ZONE 'utc')
                                        + (%s * INTERVAL '1 day'),
                           updated_at = NOW()
                       RETURNING expires_at""", (student_id, course_id, days, days))
        new_exp = cur.fetchone()[0]
        cur.execute("UPDATE tuition_payments SET status='completed', applied=1, paid_at=%s, expires_at=%s WHERE id=%s",
                    (A._parse_ts(data.get("completed_at")) or _now(), new_exp, pid))
        con.commit()
        return "completed"
    except Exception:
        con.rollback(); raise
    finally:
        cur.close(); con.close()


def refresh_pending(student_id):
    con = get_db(); cur = con.cursor()
    cur.execute("""SELECT id FROM tuition_payments WHERE student_id=%s AND applied=0 AND status='pending'
                   AND reference IS NOT NULL ORDER BY id DESC LIMIT 3""", (student_id,))
    ids = [r[0] for r in cur.fetchall()]; cur.close(); con.close()
    for pid in ids:
        try: finalize_payment(pid)
        except Exception: log.exception("tuition finalize_payment failed for %s", pid)