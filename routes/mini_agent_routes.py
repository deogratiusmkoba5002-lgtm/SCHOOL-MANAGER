"""DrDemic Mini agents: agent auth/dashboard + superadmin approval and reward queue."""
import re
from functools import wraps

from flask import Blueprint, request, jsonify, g, redirect, send_from_directory, current_app
from itsdangerous import URLSafeTimedSerializer, BadSignature

from config import SECRET_KEY, SESSION_MAX_AGE, BASE_DIR
from core.db import get_db, to_dicts
from core.auth import _require_superadmin
from core.ratelimit import rate_limit, _count, _record
from core.security import hash_password, verify_password
from services.access import normalize_phone
from services import mini_agents as AG
from services import mini_payouts as MP

mini_agent_bp = Blueprint("mini_agent", __name__)
_ser = URLSafeTimedSerializer(SECRET_KEY, salt="drdemic-mini-agent-session")


# ── public pages ────────────────────────────────────────────
@mini_agent_bp.route("/mini/a/<token>")
def agent_link(token):
    if not AG.TOKEN_RE.match(token):
        return ("Not found", 404)
    return redirect(f"/mini?ref={token}")          # never reveals whether the token is real


@mini_agent_bp.route("/mini/agent")
def agent_page():
    return send_from_directory(BASE_DIR, "agent.html")


# ── agent auth ──────────────────────────────────────────────
def _current_agent():
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    try:
        d = _ser.loads(auth[7:].strip(), max_age=SESSION_MAX_AGE)
    except BadSignature:
        return None
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT id,username,full_name,status,token_version,ref_token FROM mini_agents WHERE id=%s",
                (d.get("aid"),))
    r = cur.fetchone(); cur.close(); con.close()
    if not r or r[4] != d.get("tv"):
        return None
    return {"id": r[0], "username": r[1], "full_name": r[2], "status": r[3], "ref_token": r[5]}


def need_agent(approved=False):
    def deco(f):
        @wraps(f)
        def w(*a, **k):
            ag = _current_agent()
            if not ag:
                return jsonify({"ok": False, "error": "Please sign in"}), 401
            if approved and ag["status"] != "approved":
                return jsonify({"ok": False, "error": "Your agent link is not approved yet"}), 403
            g.agent = ag
            return f(*a, **k)
        return w
    return deco


@mini_agent_bp.route("/api/mini/agent/signup", methods=["POST"])
@rate_limit("mini_agent_signup", max_attempts=5, window_minutes=60, by="ip")
def agent_signup():
    d = request.get_json(silent=True) or {}
    u, p = (d.get("username") or "").strip(), d.get("password") or ""
    name = " ".join((d.get("full_name") or "").split())
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,40}", u) or u.isdigit():
        return jsonify({"ok": False, "error": "Username: 3-40 letters/numbers/_ . - with at least one letter"}), 400
    if not (3 <= len(name) <= 80):
        return jsonify({"ok": False, "error": "Enter your full name"}), 400
    if len(p) < 8:
        return jsonify({"ok": False, "error": "Password must be at least 8 characters"}), 400
    if p != (d.get("confirm_password") or ""):
        return jsonify({"ok": False, "error": "Passwords do not match"}), 400
    if not d.get("agree_terms"):
        return jsonify({"ok": False, "error": "You must accept the terms"}), 400
    phone = normalize_phone(d.get("phone"))
    if not phone:
        return jsonify({"ok": False, "error": "Enter a valid mobile-money number, e.g. 0712345678. Rewards are paid to it."}), 400
    con = get_db(); cur = con.cursor()
    cur.execute("INSERT INTO mini_agents(username,password,full_name,phone) VALUES(%s,%s,%s,%s) "
                "ON CONFLICT DO NOTHING RETURNING id", (u, hash_password(p), name, phone))
    row = cur.fetchone(); con.commit(); cur.close(); con.close()
    if not row:
        return jsonify({"ok": False, "error": "That username or phone number is already registered"}), 409
    return jsonify({"ok": True, "token": _ser.dumps({"aid": row[0], "tv": 0})})


@mini_agent_bp.route("/api/mini/agent/login", methods=["POST"])
@rate_limit("mini_agent_login", max_attempts=40, window_minutes=15, by="ip")
def agent_login():
    d = request.get_json(silent=True) or {}
    u, p = (d.get("username") or "").strip().lower(), d.get("password") or ""
    ident = f"{request.remote_addr}:{u}"
    if _count("mini_agent_fail", ident, 15) >= 5:
        return jsonify({"ok": False, "error": "Too many attempts. Try again in 15 minutes."}), 429
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT id,password,token_version FROM mini_agents WHERE LOWER(username)=%s", (u,))
    r = cur.fetchone(); cur.close(); con.close()
    if not r or not verify_password(p, r[1]):
        _record("mini_agent_fail", ident)
        return jsonify({"ok": False, "error": "Wrong username or password"}), 401
    return jsonify({"ok": True, "token": _ser.dumps({"aid": r[0], "tv": r[2]})})


@mini_agent_bp.route("/api/mini/agent/me", methods=["GET"])
@need_agent()
def agent_me():
    a = g.agent
    link = (request.host_url.rstrip("/") + "/mini/a/" + a["ref_token"]) if a["status"] == "approved" and a["ref_token"] else None
    return jsonify({"ok": True, "full_name": a["full_name"], "username": a["username"], "status": a["status"], "link": link})


@mini_agent_bp.route("/api/mini/agent/request_link", methods=["POST"])
@need_agent()
def agent_request_link():
    con = get_db(); cur = con.cursor()
    cur.execute("UPDATE mini_agents SET status='requested', requested_at=NOW() "
                "WHERE id=%s AND status IN ('new','rejected') RETURNING id", (g.agent["id"],))
    ok = cur.fetchone(); con.commit(); cur.close(); con.close()
    if not ok:
        return jsonify({"ok": False, "error": "Nothing to request right now"}), 409
    return jsonify({"ok": True})


@mini_agent_bp.route("/api/mini/agent/dashboard", methods=["GET"])
@need_agent(approved=True)
def agent_dashboard():
    try:
        AG.sweep_agent(g.agent["id"])
        MP.reconcile()
    except Exception:
        current_app.logger.exception("agent sweep/payout failed")
    return jsonify({"ok": True, **AG.dashboard(g.agent["id"])})


# ── superadmin ──────────────────────────────────────────────
@mini_agent_bp.route("/api/superadmin/mini/agents", methods=["GET"])
def sa_agents():
    sa, err = _require_superadmin()
    if err: return err
    st = (request.args.get("status") or "").strip()
    if st and st not in ("new", "requested", "approved", "rejected", "suspended"):
        return jsonify({"ok": False, "error": "Invalid status"}), 400
    con = get_db(); cur = con.cursor()
    cur.execute("""SELECT a.id,a.username,a.full_name,a.phone,a.status,CAST(a.created_at AS TEXT),
                          CAST(a.requested_at AS TEXT),a.decision_note,
                          (SELECT COUNT(*) FROM mini_agent_referrals r WHERE r.agent_id=a.id)
                   FROM mini_agents a WHERE (%s='' OR a.status=%s) ORDER BY a.id DESC LIMIT 200""", (st, st))
    rows = [dict(zip(("id", "username", "full_name", "phone", "status", "created_at", "requested_at", "note", "schools"), r))
            for r in cur.fetchall()]
    cur.close(); con.close()
    return jsonify({"ok": True, "agents": rows})


_FROM = {"approve": ("requested", "suspended", "rejected"), "reject": ("requested",), "suspend": ("approved",)}
_TO = {"approve": "approved", "reject": "rejected", "suspend": "suspended"}


@mini_agent_bp.route("/api/superadmin/mini/agents/<int:aid>/decide", methods=["POST"])
def sa_agent_decide(aid):
    sa, err = _require_superadmin()
    if err: return err
    d = request.get_json(silent=True) or {}
    act, note = d.get("action"), str(d.get("note") or "").strip()[:300]
    if act not in _TO:
        return jsonify({"ok": False, "error": "Invalid action"}), 400
    if act != "approve" and not note:
        return jsonify({"ok": False, "error": "A reason is required"}), 400
    con = get_db(); cur = con.cursor()
    cur.execute("""UPDATE mini_agents SET status=%s, ref_token=COALESCE(ref_token,%s), decided_by=%s,
                   decided_at=NOW(), decision_note=%s, token_version=token_version+%s
                   WHERE id=%s AND status=ANY(%s) RETURNING id""",
                (_TO[act], AG.new_ref_token(), sa, note, 1 if act == "suspend" else 0, aid, list(_FROM[act])))
    ok = cur.fetchone(); con.commit(); cur.close(); con.close()
    if not ok:
        return jsonify({"ok": False, "error": "Not allowed from the agent's current status"}), 409
    return jsonify({"ok": True})


@mini_agent_bp.route("/api/superadmin/mini/agent_rewards", methods=["GET"])
def sa_agent_rewards():
    sa, err = _require_superadmin()
    if err: return err
    try:
        MP.reconcile()
    except Exception:
        current_app.logger.exception("mini payout reconcile failed")
    st = (request.args.get("status") or "PENDING").strip().upper()
    if st not in ("PENDING", "PROCESSING", "PAID", "FAILED", "REJECTED", "ALL"):
        return jsonify({"ok": False, "error": "Invalid status"}), 400
    con = get_db(); cur = con.cursor()
    cur.execute("""SELECT w.id,a.full_name,a.phone,w.amount,w.status,CAST(w.created_at AS TEXT),w.note,u.username,
                          COALESCE((SELECT NULLIF(m.school_name,'') FROM mini_sheets m
                                    WHERE m.owner_id=w.owner_id AND m.school_name<>'' ORDER BY m.updated_at DESC LIMIT 1),''),
                          (SELECT array_agg(RIGHT(q.payer_phone,4) ORDER BY q.id) FROM mini_agent_qualifying q
                           WHERE q.owner_id=w.owner_id)
                   FROM mini_agent_rewards w JOIN mini_agents a ON a.id=w.agent_id JOIN mini_users u ON u.id=w.owner_id
                   WHERE (%s='ALL' OR w.status=%s) ORDER BY w.id""", (st, st))
    keys = ("id", "agent", "agent_phone", "amount", "status", "created_at", "note", "teacher", "school", "payers_last4")
    rows = [dict(zip(keys, r)) for r in cur.fetchall()]
    cur.close(); con.close()
    return jsonify({"ok": True, "rewards": rows})


@mini_agent_bp.route("/api/superadmin/mini/agent_rewards/<int:rid>/decide", methods=["POST"])
def sa_reward_decide(rid):
    sa, err = _require_superadmin()
    if err: return err
    d = request.get_json(silent=True) or {}
    act, note = d.get("action"), str(d.get("note") or "").strip()[:300]
    if act not in ("paid", "reject") or (act == "reject" and not note):
        return jsonify({"ok": False, "error": "Invalid action, or a reason is required"}), 400
    con = get_db(); cur = con.cursor()
    cur.execute("""UPDATE mini_agent_rewards SET status=%s, decided_by=%s, decided_at=NOW(), note=%s
                   WHERE id=%s AND ((status='PENDING' AND payout_reference IS NULL) OR status='FAILED')
                   RETURNING id""",
                ("PAID" if act == "paid" else "REJECTED", sa, note, rid))
    ok = cur.fetchone(); con.commit(); cur.close(); con.close()
    if not ok:
        return jsonify({"ok": False, "error": "Already decided"}), 409
    return jsonify({"ok": True})