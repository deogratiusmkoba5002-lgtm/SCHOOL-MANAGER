"""
Star System core helpers: referral token issuance, audit logging,
ledger/balance reads, and the withdrawal engine. Nothing here trusts
client input — every function takes a school_id that must come from
g.school_id (the authenticated session), never from a request body or
query string.

No route in this file. Routes call into these functions and are
responsible for auth/authorization before calling them.
"""
import secrets
from flask import request

from core.db import get_db, to_dicts
from config import (STAR_VALUE_TZS, STAR_WITHDRAWAL_MIN_STARS,
                     STAR_WITHDRAWAL_MAX_STARS, STAR_WITHDRAWAL_WINDOW_HOURS)


# ── REFERRAL TOKENS ─────────────────────────────────────────────
def get_or_create_referral_token(school_id):
    """Every school gets exactly one active referral token. Idempotent —
    safe to call on every dashboard load."""
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT token FROM star_referral_tokens WHERE school_id=%s AND revoked=0", (school_id,))
    row = cur.fetchone()
    if row:
        cur.close(); con.close()
        return row[0]
    token = secrets.token_urlsafe(12)  # ~16 chars, opaque, no embedded IDs
    try:
        cur.execute("INSERT INTO star_referral_tokens(school_id, token) VALUES(%s,%s)", (school_id, token))
        con.commit()
    except Exception:
        con.rollback()
        cur.execute("SELECT token FROM star_referral_tokens WHERE school_id=%s AND revoked=0", (school_id,))
        row = cur.fetchone()
        token = row[0] if row else None
    cur.close(); con.close()
    return token


def resolve_school_by_referral_token(token):
    """Public lookup used only at registration time to find the referring
    school. Returns school_id or None. Revoked tokens never resolve."""
    if not token: return None
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT school_id FROM star_referral_tokens WHERE token=%s AND revoked=0", (token.strip(),))
    row = cur.fetchone(); cur.close(); con.close()
    return row[0] if row else None


def record_referral_relationship(referring_school_id, referred_school_id):
    """Called once, at the referred school's registration/activation time.
    Permanent — never editable afterward. One referrer per school, ever."""
    if referring_school_id == referred_school_id:
        return False  # can't refer yourself
    con = get_db(); cur = con.cursor()
    try:
        cur.execute("""INSERT INTO star_referral_relationships(referring_school_id, referred_school_id)
                       VALUES(%s,%s)""", (referring_school_id, referred_school_id))
        con.commit()
        ok = True
    except Exception:
        con.rollback()
        ok = False
    cur.close(); con.close()
    return ok


def get_referring_school(school_id):
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT referring_school_id FROM star_referral_relationships WHERE referred_school_id=%s", (school_id,))
    row = cur.fetchone(); cur.close(); con.close()
    return row[0] if row else None


# ── AUDIT LOG ────────────────────────────────────────────────────
def log_star_event(school_id, event, actor_username=None, reference_id=None, old_state=None, new_state=None):
    """Append-only. Called by every mutating Star System operation.
    Never call this in response to client-supplied event names — event
    must always be a literal string from server code."""
    con = get_db(); cur = con.cursor()
    ip = request.remote_addr if request else None
    ua = request.headers.get("User-Agent", "")[:255] if request else None
    cur.execute("""INSERT INTO star_audit_logs(school_id, actor_username, event, reference_id,
                                                old_state, new_state, ip_address, user_agent)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""",
                (school_id, actor_username, event, reference_id, old_state, new_state, ip, ua))
    con.commit(); cur.close(); con.close()

# ── NOTIFICATIONS (surfaced to the admin, not just the audit log) ──
def create_star_notification(school_id, event, title, body="", reference_id=None):
    con = get_db(); cur = con.cursor()
    cur.execute("""INSERT INTO star_notifications(school_id, event, title, body, reference_id)
                   VALUES(%s,%s,%s,%s,%s)""", (school_id, event, title, body, reference_id))
    con.commit(); cur.close(); con.close()


def get_star_notifications(school_id, limit=30):
    con = get_db(); cur = con.cursor()
    cur.execute("""SELECT id, event, title, body, reference_id, is_read, CAST(created_at AS TEXT)
                   FROM star_notifications WHERE school_id=%s ORDER BY id DESC LIMIT %s""", (school_id, limit))
    rows = to_dicts(cur.fetchall(), cur); cur.close(); con.close()
    return rows


def get_unread_star_notification_count(school_id):
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM star_notifications WHERE school_id=%s AND is_read=0", (school_id,))
    n = cur.fetchone()[0]; cur.close(); con.close()
    return n


def mark_star_notification_read(school_id, notif_id):
    con = get_db(); cur = con.cursor()
    cur.execute("UPDATE star_notifications SET is_read=1 WHERE id=%s AND school_id=%s", (notif_id, school_id))
    con.commit(); cur.close(); con.close()


def mark_all_star_notifications_read(school_id):
    con = get_db(); cur = con.cursor()
    cur.execute("UPDATE star_notifications SET is_read=1 WHERE school_id=%s AND is_read=0", (school_id,))
    con.commit(); cur.close(); con.close()


# ── LEDGER / BALANCE (read-only) ────────────────────────────────
def get_star_balance(school_id):
    """Available balance: granted rewards minus anything reserved by a
    withdrawal that is requested, processing, or already paid out.
    REJECTED/FAILED withdrawals release their reservation because their
    star_transactions row gets flipped to REVERSED (see reject flow below).
    This is the ONLY place balance is computed; never store it as a
    mutable column."""
    con = get_db(); cur = con.cursor()
    cur.execute("""
        SELECT COALESCE(SUM(
            CASE
                WHEN type != 'WITHDRAWAL' AND status = 'AVAILABLE' THEN stars
                WHEN type  = 'WITHDRAWAL' AND status IN ('WITHDRAWAL_REQUESTED','PROCESSING','WITHDRAWN') THEN -stars
                ELSE 0
            END), 0)
        FROM star_transactions WHERE school_id=%s""", (school_id,))
    stars = cur.fetchone()[0] or 0
    cur.close(); con.close()
    return {"stars": stars, "amount": stars * STAR_VALUE_TZS}


def get_star_history(school_id, limit=50):
    con = get_db(); cur = con.cursor()
    cur.execute("""SELECT id, type, stars, amount, reference_type, reference_id,
                          description, status, CAST(created_at AS TEXT)
                   FROM star_transactions WHERE school_id=%s
                   ORDER BY id DESC LIMIT %s""", (school_id, limit))
    rows = to_dicts(cur.fetchall(), cur); cur.close(); con.close()
    return rows


def get_current_cycle(school_id):
    """The school's in-progress cycle, or None if none started yet."""
    con = get_db(); cur = con.cursor()
    cur.execute("""SELECT id, cycle_number, status, qualifying_parent_count, CAST(started_at AS TEXT)
                   FROM star_cycles WHERE school_id=%s AND status='IN_PROGRESS'
                   ORDER BY cycle_number DESC LIMIT 1""", (school_id,))
    row = cur.fetchone(); cur.close(); con.close()
    if not row: return None
    return {"id": row[0], "cycle_number": row[1], "status": row[2],
            "qualifying_parent_count": row[3], "started_at": row[4]}


def get_referral_stats(school_id):
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM star_referral_relationships WHERE referring_school_id=%s", (school_id,))
    total_referred = cur.fetchone()[0]
    cur.execute("""SELECT COUNT(*) FROM star_transactions
                   WHERE school_id=%s AND type='REFERRAL_REWARD' AND status!='REVERSED'""", (school_id,))
    successful = cur.fetchone()[0]
    cur.close(); con.close()
    return {"schools_referred": total_referred, "successful_referrals": successful}

# ── PREREQUISITES ────────────────────────────────────────────────
def _school_meets_cycle_prerequisites(school_id):
    """Registration complete + has students + has assigned teachers +
    has published results at least once. All checked server-side —
    this is never something the client can assert."""
    from core.school import is_registration_complete
    if not is_registration_complete(school_id):
        return False
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM students WHERE school_id=%s", (school_id,))
    if cur.fetchone()[0] < 1:
        cur.close(); con.close(); return False
    cur.execute("SELECT COUNT(*) FROM subject_assignments WHERE school_id=%s", (school_id,))
    if cur.fetchone()[0] < 1:
        cur.close(); con.close(); return False
    cur.execute("""SELECT COUNT(*) FROM results_published WHERE school_id=%s AND published=1
                   UNION ALL
                   SELECT COUNT(*) FROM published_assessments WHERE school_id=%s AND published=1""",
                (school_id, school_id))
    rows = cur.fetchall(); cur.close(); con.close()
    return any(r[0] > 0 for r in rows)


# ── CYCLE LIFECYCLE ──────────────────────────────────────────────
def ensure_cycle_started(school_id):
    """Idempotent. Starts a new IN_PROGRESS cycle for this school if
    prerequisites are met and no cycle is currently in progress."""
    if get_current_cycle(school_id) is not None:
        return
    if not _school_meets_cycle_prerequisites(school_id):
        return
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT COALESCE(MAX(cycle_number),0)+1 FROM star_cycles WHERE school_id=%s", (school_id,))
    next_num = cur.fetchone()[0]
    try:
        cur.execute("""INSERT INTO star_cycles(school_id, cycle_number, status)
                       VALUES(%s,%s,'IN_PROGRESS')""", (school_id, next_num))
        con.commit()
    except Exception:
        con.rollback()
    cur.close(); con.close()
    log_star_event(school_id, "CYCLE_STARTED", new_state=f"cycle_number={next_num}")


def record_qualifying_parent(school_id, student_id, payment_reference):
    """Call this ONLY after independently verifying, server-side, that:
      1) the payment for this student is genuinely completed
      2) the parent has actually accessed/viewed the student's results
    (see maybe_record_qualifying_parent below — that's the real entry
    point most of the app should use).

    Idempotent per (cycle, student) via UNIQUE(cycle_id, student_id) —
    the same student can never double-count in one cycle."""
    ensure_cycle_started(school_id)
    cycle = get_current_cycle(school_id)
    if not cycle:
        return {"ok": False, "reason": "no_active_cycle"}

    con = get_db(); cur = con.cursor()
    try:
        cur.execute("""INSERT INTO star_qualifying_parents(cycle_id, school_id, student_id, payment_reference)
                       VALUES(%s,%s,%s,%s)""", (cycle["id"], school_id, student_id, payment_reference))
        cur.execute("""UPDATE star_cycles SET qualifying_parent_count = qualifying_parent_count + 1,
                       updated_at = NOW() WHERE id=%s""", (cycle["id"],))
        con.commit()
    except Exception:
        con.rollback()
        cur.close(); con.close()
        return {"ok": False, "reason": "already_qualified_or_error"}
    cur.close(); con.close()

    log_star_event(school_id, "QUALIFYING_PARENT_RECORDED", reference_id=cycle["id"])
    _maybe_complete_cycle(school_id, cycle["id"])
    return {"ok": True, "cycle_id": cycle["id"]}


def maybe_record_qualifying_parent(school_id, student_id):
    """THE REAL ENTRY POINT. Call this every time a parent legitimately
    views their student's results or report card while access is active.
    Safe to call on every single view — the DB-level unique constraint
    means only the first call per cycle per student actually does anything;
    every call after that is a harmless no-op."""
    from services.access import has_active_access, get_latest_completed_payment_reference
    if not has_active_access(school_id, student_id):
        return
    ref = get_latest_completed_payment_reference(school_id, student_id)
    if not ref:
        return
    record_qualifying_parent(school_id, student_id, ref)


def _maybe_complete_cycle(school_id, cycle_id):
    """Checks whether a cycle has hit the required parent count and, if
    so, completes it exactly once and awards the reward(s). Uses a
    row lock + status guard so concurrent calls can never double-award."""
    from config import STAR_CYCLE_MIN_PARENTS
    con = get_db(); cur = con.cursor()
    try:
        cur.execute("""SELECT qualifying_parent_count, status FROM star_cycles
                       WHERE id=%s FOR UPDATE""", (cycle_id,))
        row = cur.fetchone()
        if not row:
            con.rollback(); cur.close(); con.close(); return
        count, status = row
        if status != "IN_PROGRESS" or count < STAR_CYCLE_MIN_PARENTS:
            con.commit(); cur.close(); con.close(); return

        cur.execute("""UPDATE star_cycles SET status='COMPLETED', completed_at=NOW(), updated_at=NOW()
                       WHERE id=%s""", (cycle_id,))
        cur.execute("""INSERT INTO star_transactions(school_id, type, stars, amount, reference_type,
                                                       reference_id, description, status)
                       VALUES(%s,'CYCLE_REWARD',1,%s,'star_cycle',%s,%s,'AVAILABLE')""",
                    (school_id, STAR_VALUE_TZS, cycle_id, f"Cycle {cycle_id} completed"))
        con.commit()
    except Exception:
        con.rollback(); cur.close(); con.close(); raise
    cur.close(); con.close()

    log_star_event(school_id, "CYCLE_COMPLETED", reference_id=cycle_id, new_state="COMPLETED")
    log_star_event(school_id, "STAR_EARNED", reference_id=cycle_id, new_state="CYCLE_REWARD")
    create_star_notification(school_id, "STAR_EARNED", "⭐ You earned a Star!",
                              f"Your school completed a qualifying cycle and earned 1 Star "
                              f"(TZS {STAR_VALUE_TZS:,}).", cycle_id)
    _maybe_award_referral_reward(school_id)


def _maybe_award_referral_reward(referred_school_id):
    """When a referred school completes ITS FIRST cycle, the referring
    school earns exactly one referral star — never more, and never for
    that referred school's second-level referrals."""
    referring_school_id = get_referring_school(referred_school_id)
    if not referring_school_id:
        return

    con = get_db(); cur = con.cursor()
    cur.execute("""SELECT COUNT(*) FROM star_cycles WHERE school_id=%s AND status='COMPLETED'""",
                (referred_school_id,))
    completed_count = cur.fetchone()[0]
    if completed_count != 1:
        cur.close(); con.close(); return

    cur.execute("""SELECT 1 FROM star_transactions
                   WHERE school_id=%s AND type='REFERRAL_REWARD' AND reference_type='referred_school'
                   AND reference_id=%s""", (referring_school_id, referred_school_id))
    if cur.fetchone():
        cur.close(); con.close(); return

    cur.execute("""INSERT INTO star_transactions(school_id, type, stars, amount, reference_type,
                                                   reference_id, description, status)
                   VALUES(%s,'REFERRAL_REWARD',1,%s,'referred_school',%s,%s,'AVAILABLE')""",
                (referring_school_id, STAR_VALUE_TZS, referred_school_id,
                 f"Referral bonus for school #{referred_school_id}'s first completed cycle"))
    con.commit(); cur.close(); con.close()

    log_star_event(referring_school_id, "REFERRAL_REWARD_AWARDED", reference_id=referred_school_id)
    create_star_notification(referring_school_id, "REFERRAL_REWARD_AWARDED", "⭐ Referral bonus earned!",
                              f"A school you referred (#{referred_school_id}) completed its first cycle — "
                              f"you earned 1 bonus Star.", referred_school_id)

# ── PAYOUT ACCOUNTS ──────────────────────────────────────────────
def get_payout_account(school_id):
    con = get_db(); cur = con.cursor()
    cur.execute("""SELECT id, provider, account_identifier, verified, CAST(updated_at AS TEXT)
                   FROM star_payout_accounts WHERE school_id=%s ORDER BY id DESC LIMIT 1""", (school_id,))
    row = cur.fetchone(); cur.close(); con.close()
    if not row: return None
    return {"id": row[0], "provider": row[1], "account_identifier": row[2],
            "verified": bool(row[3]), "updated_at": row[4]}


def set_payout_account(school_id, account_identifier, provider="snippe"):
    """Snippe payouts aren't wired for disbursement yet — this just records
    the destination so a superadmin can pay out manually and verify it
    later. Never trust this as 'verified' on write."""
    from services.access import normalize_phone
    phone = normalize_phone(account_identifier)
    if not phone:
        raise ValueError("Enter a valid mobile-money number, e.g. 0712345678")
    con = get_db(); cur = con.cursor()
    cur.execute("""INSERT INTO star_payout_accounts(school_id, provider, account_identifier, verified, updated_at)
                   VALUES(%s,%s,%s,0,NOW()) RETURNING id""", (school_id, provider, phone))
    new_id = cur.fetchone()[0]
    con.commit(); cur.close(); con.close()
    log_star_event(school_id, "PAYOUT_ACCOUNT_CHANGED", reference_id=new_id)
    create_star_notification(school_id, "PAYOUT_ACCOUNT_CHANGED", "Payout number changed",
                              "Your Star System payout mobile-money number was changed. "
                              "If this wasn't you, contact support immediately.", new_id)
    return {"id": new_id, "provider": provider, "account_identifier": phone, "verified": False}

# ── WITHDRAWALS ──────────────────────────────────────────────────
def get_withdrawals(school_id, limit=50):
    con = get_db(); cur = con.cursor()
    cur.execute("""SELECT id, stars, amount, status, CAST(requested_at AS TEXT),
                          CAST(decided_at AS TEXT), decided_by, note
                   FROM star_withdrawals WHERE school_id=%s ORDER BY id DESC LIMIT %s""", (school_id, limit))
    rows = to_dicts(cur.fetchall(), cur); cur.close(); con.close()
    return rows


def request_withdrawal(school_id, username, stars, idempotency_key):
    """Atomic, race-safe, idempotent. Locks the school's own row for the
    duration of the check-then-insert, which serializes every concurrent
    withdrawal request for that school — no separate lock table needed."""
    if not idempotency_key or len(idempotency_key) > 64:
        raise ValueError("Missing or invalid idempotency key")
    try:
        stars = int(stars)
    except (TypeError, ValueError):
        raise ValueError("Invalid star amount")
    if stars < STAR_WITHDRAWAL_MIN_STARS:
        raise ValueError(f"Minimum withdrawal is {STAR_WITHDRAWAL_MIN_STARS} star(s)")
    if stars > STAR_WITHDRAWAL_MAX_STARS:
        raise ValueError(f"Maximum withdrawal is {STAR_WITHDRAWAL_MAX_STARS} star(s) per request")

    con = get_db(); cur = con.cursor()
    wid = None
    try:
        cur.execute("SELECT id FROM schools WHERE id=%s FOR UPDATE", (school_id,))
        if not cur.fetchone():
            raise ValueError("School not found")

        cur.execute("SELECT id, stars, amount, status FROM star_withdrawals WHERE idempotency_key=%s", (idempotency_key,))
        existing = cur.fetchone()
        if existing:
            con.commit()
            return {"id": existing[0], "stars": existing[1], "amount": existing[2],
                    "status": existing[3], "already_existed": True}

        payout = get_payout_account(school_id)
        if not payout:
            raise ValueError("Add a payout mobile-money number before requesting a withdrawal")

        cur.execute("""SELECT COALESCE(SUM(stars),0) FROM star_withdrawals
                       WHERE school_id=%s AND requested_at > NOW() - (%s * INTERVAL '1 hour')
                       AND status NOT IN ('REJECTED','FAILED')""",
                    (school_id, STAR_WITHDRAWAL_WINDOW_HOURS))
        recent_stars = cur.fetchone()[0] or 0
        if recent_stars + stars > STAR_WITHDRAWAL_MAX_STARS:
            raise ValueError(f"You can withdraw at most {STAR_WITHDRAWAL_MAX_STARS} star(s) per "
                             f"{STAR_WITHDRAWAL_WINDOW_HOURS}h — {recent_stars} already requested in that window")

        cur.execute("""
            SELECT COALESCE(SUM(
                CASE
                    WHEN type != 'WITHDRAWAL' AND status = 'AVAILABLE' THEN stars
                    WHEN type  = 'WITHDRAWAL' AND status IN ('WITHDRAWAL_REQUESTED','PROCESSING','WITHDRAWN') THEN -stars
                    ELSE 0
                END), 0)
            FROM star_transactions WHERE school_id=%s""", (school_id,))
        available = cur.fetchone()[0] or 0
        if stars > available:
            raise ValueError(f"Insufficient balance — you have {available} star(s) available")

        amount = stars * STAR_VALUE_TZS
        cur.execute("""INSERT INTO star_withdrawals(school_id, stars, amount, status, payout_account_id, idempotency_key)
                       VALUES(%s,%s,%s,'REQUESTED',%s,%s) RETURNING id""",
                    (school_id, stars, amount, payout["id"], idempotency_key))
        wid = cur.fetchone()[0]
        cur.execute("""INSERT INTO star_transactions(school_id, type, stars, amount, reference_type,
                                                       reference_id, description, status)
                       VALUES(%s,'WITHDRAWAL',%s,%s,'star_withdrawal',%s,%s,'WITHDRAWAL_REQUESTED')""",
                    (school_id, stars, amount, wid, f"Withdrawal request #{wid} by {username}"))
        con.commit()
    except ValueError:
        con.rollback(); raise
    except Exception:
        con.rollback(); raise
    finally:
        cur.close(); con.close()

    log_star_event(school_id, "WITHDRAWAL_REQUESTED", actor_username=username, reference_id=wid,
                   new_state=f"stars={stars}")
    note = f"A withdrawal of {stars} star(s) (TZS {amount:,}) was requested."
    if stars >= STAR_WITHDRAWAL_MAX_STARS // 2:
        note += " This is a large withdrawal — if this wasn't you, contact support immediately."
    create_star_notification(school_id, "WITHDRAWAL_REQUESTED", "Withdrawal requested", note, wid)
    return {"id": wid, "stars": stars, "amount": amount, "status": "REQUESTED", "already_existed": False}