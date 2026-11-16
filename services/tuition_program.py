"""DrDemic Tuition courses (programs): instalment payments via Snippe + the DrDemic Mini bridge. No Flask.
Same rule as every payment: access is granted ONLY after Snippe confirms status and amount."""
import logging, secrets
from datetime import datetime
from psycopg2.extras import Json

from config import TUITION_FEE_PERCENT
from core.db import get_db
from core.security import hash_password
from services import access as A
from services import mini as M

log = logging.getLogger(__name__)


def paid_summary(cur, prog_id, sid):
    cur.execute("SELECT COALESCE(SUM(amount),0),COUNT(*) FROM tuition_program_payments "
                "WHERE program_id=%s AND student_id=%s AND applied=1", (prog_id, sid))
    return cur.fetchone()


def register(cur, prog_id, sid):
    """Idempotent: mark registered and enrol in every topic of the course."""
    cur.execute("UPDATE tuition_applications SET status='registered',registered_at=NOW() "
                "WHERE program_id=%s AND student_id=%s AND status='applied'", (prog_id, sid))
    cur.execute("INSERT INTO tuition_enrollments(course_id,student_id) SELECT id,%s FROM tuition_courses "
                "WHERE program_id=%s ON CONFLICT DO NOTHING", (sid, prog_id))


def _mark(pay_id, status, reason=None):
    con = get_db(); cur = con.cursor()
    cur.execute("UPDATE tuition_program_payments SET status=%s,failure_reason=%s WHERE id=%s AND applied=0",
                (status, reason, pay_id))
    con.commit(); cur.close(); con.close()


def start_payment(sid, prog_id, amount, phone_raw):
    if not A.SNIPPE_API_KEY:
        raise ValueError("Payments are not configured on the server yet")
    phone = A.normalize_phone(phone_raw)
    if not phone:
        raise ValueError("Enter a valid mobile number, e.g. 0712345678")
    try:
        amount = int(amount)
    except (TypeError, ValueError):
        raise ValueError("Enter the amount to pay")
    con = get_db(); cur = con.cursor()
    try:
        cur.execute("""SELECT p.fee_tzs,p.advance_tzs,p.installments,a.full_name FROM tuition_programs p
                       JOIN tuition_applications a ON a.program_id=p.id AND a.student_id=%s WHERE p.id=%s""",
                    (sid, prog_id))
        row = cur.fetchone()
        if not row:
            raise ValueError("Apply to this course first")
        fee, adv, inst, name = row
        paid, cnt = paid_summary(cur, prog_id, sid)
        bal = fee - paid
        if bal <= 0:
            raise ValueError("This course is already fully paid")
        cur.execute("SELECT 1 FROM tuition_program_payments WHERE program_id=%s AND student_id=%s "
                    "AND status='pending' AND created_at > NOW() - INTERVAL '10 minutes'", (prog_id, sid))
        if cur.fetchone():
            raise ValueError("You already have a payment waiting for approval. Approve it on your phone or wait a few minutes.")
        if amount < A.SNIPPE_MIN_AMOUNT:
            raise ValueError(f"The minimum payment is {A.SNIPPE_MIN_AMOUNT} TZS")
        if amount > bal:
            raise ValueError(f"The remaining balance is {bal} TZS")
        if cnt == 0 and amount < adv:
            raise ValueError(f"The first payment must be at least {adv} TZS")
        if cnt + 1 >= inst and amount != bal:
            raise ValueError(f"This is your last allowed instalment. Pay the full balance of {bal} TZS")
        cur.execute("SELECT COUNT(*) FROM tuition_program_payments WHERE student_id=%s "
                    "AND created_at > NOW() - INTERVAL '1 hour'", (sid,))
        if cur.fetchone()[0] >= 5:
            raise ValueError("Too many payment attempts. Wait an hour and try again.")
        idem = "tp" + secrets.token_hex(12)
        cur.execute("""INSERT INTO tuition_program_payments(program_id,student_id,amount,fee_tzs,kind,idempotency_key,phone,status)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,'pending') RETURNING id""",
                    (prog_id, sid, amount, amount * TUITION_FEE_PERCENT // 100,
                     "advance" if cnt == 0 else "installment", idem, phone))
        pay_id = cur.fetchone()[0]
        con.commit()
    finally:
        cur.close(); con.close()
    parts = (name or "").split()
    first = parts[0] if parts else "Student"
    last = " ".join(parts[1:]) or "Student"
    webhook = f"{A.PUBLIC_BASE_URL}/api/access/webhook" if A.PUBLIC_BASE_URL.startswith("https://") else None
    try:
        data = A.snippe_create_payment(amount, phone, first, last, A.SNIPPE_FALLBACK_EMAIL,
                                       {"tuition_program_payment_id": str(pay_id), "program_id": str(prog_id)},
                                       webhook, idem)
    except A.SnippeError as e:
        _mark(pay_id, "failed", str(e)); raise
    ref = data.get("reference")
    if not ref:
        _mark(pay_id, "failed", "No reference returned")
        raise A.SnippeError("Provider did not return a payment reference")
    con = get_db(); cur = con.cursor()
    cur.execute("UPDATE tuition_program_payments SET reference=%s WHERE id=%s", (ref, pay_id))
    con.commit(); cur.close(); con.close()
    return {"payment_id": pay_id, "reference": ref, "amount": amount}


def finalize_payment(pay_id):
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT reference,applied,status FROM tuition_program_payments WHERE id=%s", (pay_id,))
    row = cur.fetchone(); cur.close(); con.close()
    if not row: return None
    reference, applied, status = row
    if applied: return "completed"
    if not reference: return status
    try:
        data = A.snippe_get_payment(reference)
    except A.SnippeError as e:
        log.warning("Snippe check failed for program payment %s: %s", pay_id, e)
        return status
    remote = (data.get("status") or "").lower()
    if remote not in ("completed", "failed", "voided", "expired"):
        return "pending"
    con = get_db(); cur = con.cursor()
    try:
        cur.execute("SELECT program_id,student_id,amount,applied FROM tuition_program_payments WHERE id=%s FOR UPDATE",
                    (pay_id,))
        prog_id, sid, amount, applied = cur.fetchone()
        if applied:
            con.commit(); return "completed"
        if remote != "completed":
            cur.execute("UPDATE tuition_program_payments SET status=%s,failure_reason=%s WHERE id=%s",
                        (remote, data.get("failure_reason"), pay_id))
            con.commit(); return remote
        amt = data.get("amount") or {}
        try: got = int(amt.get("value"))
        except (TypeError, ValueError): got = None
        if got is None or got < amount or (amt.get("currency") or "TZS") != "TZS":
            cur.execute("UPDATE tuition_program_payments SET status='amount_mismatch',failure_reason=%s WHERE id=%s",
                        (f"Expected {amount} TZS, provider reported {amt.get('value')} {amt.get('currency')}", pay_id))
            con.commit(); return "amount_mismatch"
        cur.execute("UPDATE tuition_program_payments SET status='completed',applied=1,paid_at=%s WHERE id=%s",
                    (A._parse_ts(data.get("completed_at")) or datetime.utcnow(), pay_id))
        cur.execute("SELECT advance_tzs FROM tuition_programs WHERE id=%s", (prog_id,))
        adv = cur.fetchone()[0]
        paid, _ = paid_summary(cur, prog_id, sid)
        if paid >= adv:
            register(cur, prog_id, sid)
        con.commit()
        return "completed"
    except Exception:
        con.rollback(); raise
    finally:
        cur.close(); con.close()


def refresh_pending(prog_id, sid):
    con = get_db(); cur = con.cursor()
    cur.execute("""SELECT id FROM tuition_program_payments WHERE program_id=%s AND student_id=%s AND applied=0
                   AND status='pending' AND reference IS NOT NULL ORDER BY id DESC LIMIT 3""", (prog_id, sid))
    ids = [r[0] for r in cur.fetchall()]; cur.close(); con.close()
    for i in ids:
        try: finalize_payment(i)
        except Exception: log.exception("program finalize failed for %s", i)


# ── DrDemic Mini bridge ─────────────────────────────────────
def _mini_user(cur, tuser_id, role, username, phone=None):
    cur.execute("SELECT mini_user_id FROM tuition_users WHERE id=%s FOR UPDATE", (tuser_id,))
    r = cur.fetchone()
    if r and r[0]:
        return r[0]
    cur.execute("INSERT INTO mini_users(username,password,role,phone) VALUES(%s,%s,%s,%s) RETURNING id",
                (username, hash_password(secrets.token_hex(16)), role, phone or None))
    uid = cur.fetchone()[0]
    cur.execute("UPDATE tuition_users SET mini_user_id=%s WHERE id=%s", (uid, tuser_id))
    return uid


def _grant_mini_access(cur, uid):
    cur.execute("""INSERT INTO mini_access(user_id,plan,expires_at) VALUES(%s,'tuition',(NOW() AT TIME ZONE 'utc')+INTERVAL '365 days')
                   ON CONFLICT(user_id) DO UPDATE SET expires_at=GREATEST(mini_access.expires_at,EXCLUDED.expires_at)""",
                (uid,))


def mini_session(cur, user):
    """Signed-in Mini session for a tuition user (teacher = Mini owner, student = Mini parent)."""
    from routes.mini_routes import _ser                      # lazy: avoids a circular import
    teacher = user["role"] == "teacher"
    cur.execute("SELECT phone FROM tuition_users WHERE id=%s", (user["id"],))
    phone = (cur.fetchone() or [None])[0]
    uid = _mini_user(cur, user["id"], "owner" if teacher else "parent",
                     f"tuition_{'t' if teacher else 's'}{user['id']}", phone if teacher else None)
    if not teacher:
        _grant_mini_access(cur, uid)
    cur.execute("SELECT token_version FROM mini_users WHERE id=%s", (uid,))
    tv = cur.fetchone()[0]
    return {"token": _ser.dumps({"uid": uid, "tv": tv}), "role": "owner" if teacher else "parent",
            "username": user["full_name"] or user["username"]}


def send_results(teacher_id, prog_id, title, assignment_ids):
    """Builds a published Mini sheet from marked exams of this course's registered students."""
    title = " ".join((title or "").split())[:150]
    if not title:
        raise ValueError("Enter a title for these results")
    con = get_db(); cur = con.cursor()
    try:
        cur.execute("SELECT name FROM tuition_programs WHERE id=%s AND teacher_id=%s", (prog_id, teacher_id))
        prog = cur.fetchone()
        if not prog:
            raise ValueError("Course not found")
        cur.execute("""SELECT a.id,a.title,a.max_score,c.subject FROM tuition_assignments a
                       JOIN tuition_courses c ON c.id=a.course_id
                       WHERE a.id=ANY(%s) AND a.kind='exam' AND c.program_id=%s ORDER BY a.id""",
                    (list(assignment_ids), prog_id))
        exams = cur.fetchall()
        if not exams:
            raise ValueError("Pick at least one exam")
        cur.execute("""SELECT student_id,full_name,phone FROM tuition_applications
                       WHERE program_id=%s AND status='registered' ORDER BY full_name""", (prog_id,))
        studs = cur.fetchall()
        if not studs:
            raise ValueError("No registered students yet")
        subjects = [{"id": M.new_id("s"), "name": f"{e[3]}: {e[1]}"[:40]} for e in exams]
        cur.execute("SELECT assignment_id,student_id,score FROM tuition_submissions "
                    "WHERE assignment_id=ANY(%s) AND score IS NOT NULL", ([e[0] for e in exams],))
        sc = {(a, s): v for a, s, v in cur.fetchall()}
        rows = []
        for sid, name, phone in studs:
            marks = {}
            for e, sub in zip(exams, subjects):
                v = sc.get((e[0], sid))
                if v is not None:
                    marks[sub["id"]] = round(v * 100.0 / e[2], 2)       # always out of 100
            rows.append({"id": M.new_id("r"), "name": name, "phone": phone, "marks": marks})
        data, err = M.clean_data({"subjects": subjects, "rows": rows})
        if err:
            raise ValueError(err)
        cur.execute("SELECT phone FROM tuition_users WHERE id=%s", (teacher_id,))
        owner = _mini_user(cur, teacher_id, "owner", f"tuition_t{teacher_id}", cur.fetchone()[0])
        key, pub = secrets.token_urlsafe(16), secrets.token_urlsafe(6)
        cur.execute("""INSERT INTO mini_sheets(owner_id,share_key,school_name,exam_name,sheet_type,grade_rules,data,
                                               published,published_at,pub_token,grandfathered)
                       VALUES(%s,%s,%s,%s,'marks',%s,%s,1,NOW(),%s,1)""",
                    (owner, key, prog[0][:150], title, Json(M.DEFAULT_GRADES), Json(data), pub))
        M.sync_students(cur, owner, data["rows"])
        for sid, name, _p in studs:
            puid = _mini_user(cur, sid, "parent", f"tuition_s{sid}")
            cur.execute("UPDATE mini_students SET parent_user_id=%s WHERE owner_id=%s AND name_norm=%s "
                        "AND parent_user_id IS NULL", (puid, owner, M.norm(name)))
            _grant_mini_access(cur, puid)
        con.commit()
        return {"key": key, "students": len(studs)}
    except Exception:
        con.rollback(); raise
    finally:
        cur.close(); con.close()