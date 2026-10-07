"""
Automated Star payouts via Snippe disbursements. Same rule as access.py:
nothing the browser or a webhook body says is trusted; status always comes
from asking Snippe. No Flask request/response handling.
"""
import logging
import requests

from config import (SNIPPE_API_BASE, SNIPPE_API_KEY, PUBLIC_BASE_URL, STAR_AUTO_PAYOUT_ENABLED,
                    STAR_AUTO_PAYOUT_MAX_STARS, STAR_PAYOUT_COOLDOWN_HOURS)
from core.db import get_db
from services.access import _headers, _snippe_call, SnippeError
from services.stars import create_star_notification, log_star_event

log = logging.getLogger(__name__)
MIN_PAYOUT_TZS = 5000


def _status_of(wid):
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT status FROM star_withdrawals WHERE id=%s", (wid,))
    row = cur.fetchone(); cur.close(); con.close()
    return row[0] if row else None


def _post_payout(idem, body):
    """-> ('ok', data) | ('rejected', msg) | ('unknown', msg).
    'unknown' = can't tell if Snippe got it (timeout/5xx). Retrying with the
    SAME idempotency key is safe."""
    try:
        r = requests.post(f"{SNIPPE_API_BASE}/v1/payouts/send", json=body,
                          headers=_headers(idem), timeout=20)
    except requests.RequestException:
        return "unknown", "network error"
    try:
        j = r.json()
    except ValueError:
        return "unknown", f"invalid response ({r.status_code})"
    if r.status_code >= 500:
        return "unknown", f"provider error ({r.status_code})"
    if r.status_code >= 400 or j.get("status") != "success":
        return "rejected", (j.get("message") or f"provider error ({r.status_code})")
    return "ok", (j.get("data") or {})


def _apply_remote(wid, remote, reference=None, reason=None):
    """Idempotent. remote: completed | failed | reversed | anything else = still in flight."""
    con = get_db(); cur = con.cursor()
    try:
        cur.execute("SELECT school_id,status FROM star_withdrawals WHERE id=%s FOR UPDATE", (wid,))
        row = cur.fetchone()
        if not row:
            con.rollback(); return None
        school_id, status = row
        if status in ("WITHDRAWN", "FAILED", "REJECTED"):
            con.commit(); return status
        if remote == "completed":
            new, tx = "WITHDRAWN", "WITHDRAWN"
        elif remote in ("failed", "reversed"):
            new, tx = "FAILED", "REVERSED"          # REVERSED releases the reserved stars
        else:
            if reference:
                cur.execute("UPDATE star_withdrawals SET payout_reference=%s WHERE id=%s", (reference, wid))
            con.commit(); return status
        cur.execute("""UPDATE star_withdrawals SET status=%s, decided_by='snippe-auto', decided_at=NOW(),
                       note=%s, payout_reference=COALESCE(%s,payout_reference) WHERE id=%s""",
                    (new, (reason or "")[:300], reference, wid))
        cur.execute("""UPDATE star_transactions SET status=%s
                       WHERE reference_type='star_withdrawal' AND reference_id=%s""", (tx, wid))
        con.commit()
    except Exception:
        con.rollback(); raise
    finally:
        cur.close(); con.close()

    if new == "WITHDRAWN":
        log_star_event(school_id, "WITHDRAWAL_PAID_AUTO", actor_username="snippe-auto", reference_id=wid, new_state="WITHDRAWN")
        create_star_notification(school_id, "WITHDRAWAL_APPROVED", "Withdrawal completed",
                                 f"Your withdrawal request #{wid} was sent to your mobile-money number.", wid)
    else:
        log_star_event(school_id, "WITHDRAWAL_FAILED_AUTO", actor_username="snippe-auto", reference_id=wid, new_state="FAILED")
        create_star_notification(school_id, "WITHDRAWAL_REJECTED", "Withdrawal could not be completed",
                                 f"Your withdrawal request #{wid} failed and the stars were returned to your balance. "
                                 f"Please check your payout number and try again.", wid)
    return new


def check_payout(wid, reference):
    """Ask Snippe for the truth about one payout."""
    try:
        data = _snippe_call("GET", f"/v1/payouts/{requests.utils.quote(reference, safe='')}", headers=_headers())
    except SnippeError as e:
        log.warning("payout status check failed for withdrawal %s: %s", wid, e)
        return None
    return _apply_remote(wid, (data.get("status") or "").lower(), reference, data.get("failure_reason"))


def _send_and_apply(wid):
    con = get_db(); cur = con.cursor()
    cur.execute("""SELECT w.school_id,w.amount,pa.account_identifier,s.school_name
                   FROM star_withdrawals w JOIN schools s ON s.id=w.school_id
                   LEFT JOIN star_payout_accounts pa ON pa.id=w.payout_account_id
                   WHERE w.id=%s AND w.status='PROCESSING' AND w.payout_reference IS NULL""", (wid,))
    row = cur.fetchone(); cur.close(); con.close()
    if not row:
        return
    school_id, amount, phone, school_name = row
    body = {"channel": "mobile", "amount": amount, "recipient_phone": phone,
            "recipient_name": (school_name or "School")[:60],
            "narration": f"DrDemic Star reward #{wid}",
            "metadata": {"withdrawal_id": str(wid), "school_id": str(school_id)}}
    if PUBLIC_BASE_URL.startswith("https://"):
        body["webhook_url"] = f"{PUBLIC_BASE_URL}/api/access/webhook"

    kind, data = _post_payout(f"swd{wid}", body)       # stable key => retries can never double-pay
    if kind == "ok":
        _apply_remote(wid, (data.get("status") or "pending").lower(), data.get("reference"), data.get("failure_reason"))
    elif kind == "rejected":
        try:
            from core.monitoring import record_event
            record_event(f"Star payout #{wid} rejected by Snippe: {data}", severity="ERROR", operation="Star payout")
        except Exception:
            log.exception("could not record payout rejection")
        _apply_remote(wid, "failed", None, str(data))
    else:
        log.warning("payout %s outcome unknown (%s); will retry with same key", wid, data)


def try_auto_payout(wid):
    """Returns the withdrawal's status afterwards ('REQUESTED' = left for manual review/cooldown)."""
    if not (STAR_AUTO_PAYOUT_ENABLED and SNIPPE_API_KEY):
        return "REQUESTED"
    con = get_db(); cur = con.cursor()
    try:
        cur.execute("""SELECT w.stars,w.amount,w.status,pa.account_identifier,
                              COALESCE(pa.created_at > NOW() - (%s * INTERVAL '1 hour'), TRUE)
                       FROM star_withdrawals w
                       LEFT JOIN star_payout_accounts pa ON pa.id=w.payout_account_id
                       WHERE w.id=%s FOR UPDATE OF w""", (STAR_PAYOUT_COOLDOWN_HOURS, wid))
        row = cur.fetchone()
        if not row:
            con.rollback(); return "REQUESTED"
        stars, amount, status, phone, too_fresh = row
        if (status != "REQUESTED" or not phone or too_fresh
                or stars > STAR_AUTO_PAYOUT_MAX_STARS or amount < MIN_PAYOUT_TZS):
            con.commit(); return status
        # Commit PROCESSING *before* talking to Snippe so a crash can't lose track of it.
        cur.execute("UPDATE star_withdrawals SET status='PROCESSING' WHERE id=%s", (wid,))
        cur.execute("""UPDATE star_transactions SET status='PROCESSING'
                       WHERE reference_type='star_withdrawal' AND reference_id=%s""", (wid,))
        con.commit()
    except Exception:
        con.rollback(); raise
    finally:
        cur.close(); con.close()
    _send_and_apply(wid)
    return _status_of(wid)


def reconcile_school_payouts(school_id):
    """No scheduler needed (same trick as refresh_pending): runs when the admin opens the
    Star page. Settles in-flight payouts, retries unsent ones (first 2h only, inside any
    idempotency window), and releases queued ones once the cooldown has passed."""
    con = get_db(); cur = con.cursor()
    cur.execute("""SELECT id,status,payout_reference,(requested_at > NOW() - INTERVAL '2 hours')
                   FROM star_withdrawals WHERE school_id=%s AND status IN ('REQUESTED','PROCESSING')
                   ORDER BY id LIMIT 10""", (school_id,))
    rows = cur.fetchall(); cur.close(); con.close()
    for wid, status, ref, recent in rows:
        try:
            if status == "REQUESTED":
                try_auto_payout(wid)
            elif ref:
                check_payout(wid, ref)
            elif recent:
                _send_and_apply(wid)
        except Exception:
            log.exception("payout reconcile failed for withdrawal %s", wid)