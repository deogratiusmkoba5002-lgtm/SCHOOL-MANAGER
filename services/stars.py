"""
Star System core helpers: referral token issuance, audit logging, and
ledger/balance reads. Nothing here trusts client input — every function
takes a school_id that must come from g.school_id (the authenticated
session), never from a request body or query string.

No route in this file. Routes call into these functions and are
responsible for auth/authorization before calling them.
"""
import secrets
from flask import request

from core.db import get_db, to_dicts
from config import STAR_VALUE_TZS


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
        # Extremely unlikely collision or race — just re-read what's there.
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
        ok = False  # already has a referrer, or bad input — silently ignored by design
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


# ── LEDGER / BALANCE (read-only) ────────────────────────────────
def get_star_balance(school_id):
    """Available balance only — PENDING/ON_HOLD/WITHDRAWAL_REQUESTED etc.
    don't count as spendable yet. This is the only place balance is computed;
    never store balance as a mutable column."""
    con = get_db(); cur = con.cursor()
    cur.execute("""SELECT COALESCE(SUM(CASE WHEN type='WITHDRAWAL' THEN -stars ELSE stars END), 0)
                   FROM star_transactions
                   WHERE school_id=%s AND status='AVAILABLE'""", (school_id,))
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