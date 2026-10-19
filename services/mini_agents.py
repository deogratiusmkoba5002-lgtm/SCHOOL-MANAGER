"""DrDemic Mini agents: referral attachment, qualification, dashboard data. No Flask.
Money rule: a parent only counts after Snippe-verified payment (mini_payments.status='completed', applied=1).
Rewards are only ever CREATED here as PENDING; a human pays them from superadmin."""
import logging, re, secrets

from config import MINI_AGENT_REWARD_TZS, MINI_AGENT_PARENTS_REQUIRED, MINI_AGENT_MIN_PAYMENT_TZS
from core.db import get_db

log = logging.getLogger(__name__)
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{6,40}$")


def new_ref_token():
    return secrets.token_urlsafe(9)


def attach_referral(owner_id, owner_phone, ref):
    """Called at Mini signup. NEVER raises, silently ignores anything invalid. One agent per owner, forever."""
    try:
        if not ref or not TOKEN_RE.match(str(ref)):
            return False
        con = get_db(); cur = con.cursor()
        try:
            cur.execute("SELECT id, phone FROM mini_agents WHERE ref_token=%s AND status='approved'", (str(ref),))
            a = cur.fetchone()
            if not a or a[1] == owner_phone:          # unknown/unapproved agent, or agent signing up themselves
                return False
            cur.execute("INSERT INTO mini_agent_referrals(owner_id,agent_id) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                        (owner_id, a[0]))
            con.commit()
            return True
        finally:
            cur.close(); con.close()
    except Exception:
        log.exception("attach_referral failed")
        return False


def qualify_payment(pid):
    """Count one verified payment toward the referred school it belongs to. Idempotent."""
    con = get_db(); cur = con.cursor()
    try:
        cur.execute("SELECT user_id,amount,phone FROM mini_payments WHERE id=%s AND status='completed' AND applied=1",
                    (pid,))
        pay = cur.fetchone()
        if not pay or pay[1] < MINI_AGENT_MIN_PAYMENT_TZS or not pay[2]:
            con.rollback(); return False
        user_id, _amount, payer = pay
        cur.execute("""SELECT s.owner_id, r.agent_id, a.phone, o.phone, s.phone
                       FROM mini_students s
                       JOIN mini_agent_referrals r ON r.owner_id=s.owner_id
                       JOIN mini_agents a ON a.id=r.agent_id AND a.status='approved'
                       JOIN mini_users o ON o.id=s.owner_id
                       WHERE s.parent_user_id=%s ORDER BY s.id LIMIT 1""", (user_id,))
        row = cur.fetchone()
        if not row:
            con.rollback(); return False
        owner_id, agent_id, agent_phone, owner_phone, student_phone = row
        # self-dealing: agent or teacher paying/being the "parent"
        if payer in (agent_phone, owner_phone) or student_phone == agent_phone:
            con.rollback(); return False
        cur.execute("SELECT 1 FROM mini_agent_referrals WHERE owner_id=%s FOR UPDATE", (owner_id,))   # serialize per school
        cur.execute("SELECT COUNT(*) FROM mini_agent_qualifying WHERE owner_id=%s", (owner_id,))
        if cur.fetchone()[0] >= MINI_AGENT_PARENTS_REQUIRED:
            con.rollback(); return False                     # school is "closed" for this agent forever
        cur.execute("""INSERT INTO mini_agent_qualifying(owner_id,agent_id,parent_user_id,payment_id,payer_phone)
                       VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                    (owner_id, agent_id, user_id, pid, payer))
        added = cur.rowcount > 0
        cur.execute("SELECT COUNT(*) FROM mini_agent_qualifying WHERE owner_id=%s", (owner_id,))
        if cur.fetchone()[0] >= MINI_AGENT_PARENTS_REQUIRED:
            cur.execute("INSERT INTO mini_agent_rewards(agent_id,owner_id,amount) VALUES(%s,%s,%s) "
                        "ON CONFLICT DO NOTHING", (agent_id, owner_id, MINI_AGENT_REWARD_TZS))
        con.commit()
        return added
    except Exception:
        con.rollback(); raise
    finally:
        cur.close(); con.close()


def on_payment_completed(pid):
    qualify_payment(pid)


def sweep_agent(agent_id):
    """Self-healing: re-check this agent's schools in case a hook was missed. Capped so it stays cheap."""
    con = get_db(); cur = con.cursor()
    cur.execute("""SELECT DISTINCT p.id FROM mini_payments p
                   JOIN mini_students s ON s.parent_user_id=p.user_id
                   JOIN mini_agent_referrals r ON r.owner_id=s.owner_id
                   WHERE r.agent_id=%s AND p.status='completed' AND p.applied=1
                     AND p.id NOT IN (SELECT payment_id FROM mini_agent_qualifying)
                   ORDER BY p.id LIMIT 200""", (agent_id,))
    ids = [r[0] for r in cur.fetchall()]; cur.close(); con.close()
    for pid in ids:
        try:
            qualify_payment(pid)
        except Exception:
            log.exception("agent sweep failed for payment %s", pid)


def dashboard(agent_id):
    """Read-only numbers for the agent. Never exposes owner ids, usernames, phones or parent names."""
    con = get_db(); cur = con.cursor()
    cur.execute("""SELECT CAST(r.created_at AS TEXT),
                          COALESCE((SELECT NULLIF(m.school_name,'') FROM mini_sheets m
                                    WHERE m.owner_id=r.owner_id AND m.school_name<>''
                                    ORDER BY m.updated_at DESC LIMIT 1), ''),
                          (SELECT COUNT(*) FROM mini_agent_qualifying q WHERE q.owner_id=r.owner_id),
                          (SELECT w.status FROM mini_agent_rewards w WHERE w.owner_id=r.owner_id)
                   FROM mini_agent_referrals r WHERE r.agent_id=%s ORDER BY r.created_at DESC""", (agent_id,))
    rows = cur.fetchall()
    cur.execute("SELECT status, COUNT(*), COALESCE(SUM(amount),0) FROM mini_agent_rewards WHERE agent_id=%s GROUP BY status",
                (agent_id,))
    tot = {s: (n, amt) for s, n, amt in cur.fetchall()}
    cur.close(); con.close()
    n = len(rows)
    schools = [{"label": name or f"School #{n - i}", "joined": joined, "paid_parents": min(cnt, MINI_AGENT_PARENTS_REQUIRED),
                "reward_status": rs} for i, (joined, name, cnt, rs) in enumerate(rows)]
    def _n(*ss): return sum(tot.get(s, (0, 0))[0] for s in ss)
    def _t(*ss): return sum(tot.get(s, (0, 0))[1] for s in ss)
    return {"required": MINI_AGENT_PARENTS_REQUIRED, "reward": MINI_AGENT_REWARD_TZS,
            "stars": _n("PENDING", "PROCESSING", "PAID", "FAILED"), "paid_stars": _n("PAID"),
            "pending_tzs": _t("PENDING", "PROCESSING", "FAILED"), "paid_tzs": _t("PAID"),
            "schools": schools}