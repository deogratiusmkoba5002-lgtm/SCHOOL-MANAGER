"""Automatic Snippe payouts for Mini agent rewards. Same rules as services/payouts.py:
status always comes from asking Snippe; a stable idempotency key makes retries safe.
No Flask."""
import logging
import requests

from config import (SNIPPE_API_KEY, PUBLIC_BASE_URL, MINI_AGENT_PAYOUT_ENABLED, MINI_AGENT_PAYOUT_HOLD_HOURS,
                    MINI_AGENT_PAYOUT_AGENT_DAILY_TZS, MINI_AGENT_PAYOUT_GLOBAL_DAILY_TZS)
from core.db import get_db
from services.access import _headers, _snippe_call, SnippeError
from services.payouts import _post_payout

log = logging.getLogger(__name__)
MIN_PAYOUT_TZS = 5000


def _apply_remote(rid, remote, reference=None, reason=None):
    """Idempotent. remote: completed | failed | reversed | anything else = still in flight."""
    con = get_db(); cur = con.cursor()
    try:
        cur.execute("SELECT status FROM mini_agent_rewards WHERE id=%s FOR UPDATE", (rid,))
        row = cur.fetchone()
        if not row:
            con.rollback(); return None
        status = row[0]
        if status in ("PAID", "FAILED", "REJECTED"):
            con.commit(); return status
        if remote == "completed":
            new = "PAID"
        elif remote in ("failed", "reversed"):
            new = "FAILED"
        else:
            if reference:
                cur.execute("UPDATE mini_agent_rewards SET payout_reference=%s WHERE id=%s", (reference, rid))
            con.commit(); return status
        cur.execute("""UPDATE mini_agent_rewards SET status=%s, decided_by='snippe-auto', decided_at=NOW(),
                       note=%s, payout_reference=COALESCE(%s,payout_reference) WHERE id=%s""",
                    (new, (reason or "")[:300], reference, rid))
        con.commit(); return new
    except Exception:
        con.rollback(); raise
    finally:
        cur.close(); con.close()


def check_payout(rid, reference):
    try:
        data = _snippe_call("GET", f"/v1/payouts/{requests.utils.quote(reference, safe='')}", headers=_headers())
    except SnippeError as e:
        log.warning("mini agent payout check failed for reward %s: %s", rid, e)
        return None
    return _apply_remote(rid, (data.get("status") or "").lower(), reference, data.get("failure_reason"))


def _send_and_apply(rid):
    con = get_db(); cur = con.cursor()
    cur.execute("""SELECT w.amount, a.phone, a.full_name, w.agent_id FROM mini_agent_rewards w
                   JOIN mini_agents a ON a.id=w.agent_id
                   WHERE w.id=%s AND w.status='PROCESSING' AND w.payout_reference IS NULL""", (rid,))
    row = cur.fetchone(); cur.close(); con.close()
    if not row:
        return
    amount, phone, name, agent_id = row
    body = {"channel": "mobile", "amount": amount, "recipient_phone": phone,
            "recipient_name": (name or "Agent")[:60], "narration": f"DrDemic Mini agent reward #{rid}",
            "metadata": {"mini_reward_id": str(rid), "agent_id": str(agent_id)}}
    if PUBLIC_BASE_URL.startswith("https://"):
        body["webhook_url"] = f"{PUBLIC_BASE_URL}/api/access/webhook"
    kind, data = _post_payout(f"mar{rid}", body)          # stable key => retries can never double-pay
    if kind == "ok":
        _apply_remote(rid, (data.get("status") or "pending").lower(), data.get("reference"), data.get("failure_reason"))
    elif kind == "rejected":
        try:
            from core.monitoring import record_event
            record_event(f"Mini agent payout #{rid} rejected by Snippe: {data}", severity="ERROR", operation="Mini agent payout")
        except Exception:
            log.exception("could not record mini payout rejection")
        _apply_remote(rid, "failed", None, str(data))
    else:
        log.warning("mini payout %s outcome unknown (%s); will retry with same key", rid, data)


def try_auto_payout(rid):
    """Moves one due PENDING reward to PROCESSING and sends it. Everything is re-checked under a row lock."""
    if not (MINI_AGENT_PAYOUT_ENABLED and SNIPPE_API_KEY):
        return
    con = get_db(); cur = con.cursor()
    try:
        cur.execute("""SELECT w.agent_id, w.amount FROM mini_agent_rewards w
                       JOIN mini_agents a ON a.id=w.agent_id
                       WHERE w.id=%s AND w.status='PENDING' AND w.payout_reference IS NULL
                         AND a.status='approved'
                         AND w.created_at < NOW() - (%s * INTERVAL '1 hour')
                         AND a.created_at < NOW() - INTERVAL '24 hours'
                       FOR UPDATE OF w""", (rid, MINI_AGENT_PAYOUT_HOLD_HOURS))
        row = cur.fetchone()
        if not row or row[1] < MIN_PAYOUT_TZS:
            con.rollback(); return
        agent_id, amount = row
        cur.execute("""SELECT COALESCE(SUM(amount),0) FROM mini_agent_rewards
                       WHERE agent_id=%s AND status IN ('PROCESSING','PAID')
                         AND payout_started_at > NOW() - INTERVAL '24 hours'""", (agent_id,))
        if cur.fetchone()[0] + amount > MINI_AGENT_PAYOUT_AGENT_DAILY_TZS:
            con.rollback(); return                         # stays PENDING for manual review
        cur.execute("""SELECT COALESCE(SUM(amount),0) FROM mini_agent_rewards
                       WHERE status IN ('PROCESSING','PAID') AND payout_started_at > NOW() - INTERVAL '24 hours'""")
        if cur.fetchone()[0] + amount > MINI_AGENT_PAYOUT_GLOBAL_DAILY_TZS:
            con.rollback(); return
        # commit PROCESSING *before* talking to Snippe so a crash can't lose track of it
        cur.execute("UPDATE mini_agent_rewards SET status='PROCESSING', payout_started_at=NOW() WHERE id=%s", (rid,))
        con.commit()
    except Exception:
        con.rollback(); raise
    finally:
        cur.close(); con.close()
    _send_and_apply(rid)


def reconcile(limit=10):
    """No scheduler: called lazily. Settles in-flight payouts, retries unsent ones (first 2h only),
    and releases PENDING rewards once the hold has passed."""
    con = get_db(); cur = con.cursor()
    cur.execute("""SELECT id,status,payout_reference,(payout_started_at > NOW() - INTERVAL '2 hours')
                   FROM mini_agent_rewards WHERE status IN ('PENDING','PROCESSING')
                   ORDER BY id LIMIT %s""", (limit,))
    rows = cur.fetchall(); cur.close(); con.close()
    for rid, status, ref, recent in rows:
        try:
            if status == "PENDING":
                try_auto_payout(rid)
            elif ref:
                check_payout(rid, ref)
            elif recent:
                _send_and_apply(rid)
        except Exception:
            log.exception("mini agent payout reconcile failed for reward %s", rid)