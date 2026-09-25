"""
Star System routes: read-only dashboard/history, notifications, and the
withdrawal request flow. All financial figures are computed server-side
from services/stars.py; nothing here accepts stars/amount/balance from
the client. Withdrawal and payout-account changes are rate-limited.
"""
from flask import Blueprint, jsonify, g, request

from config import STAR_VALUE_TZS, STAR_CYCLE_MIN_PARENTS
from core.auth import require_auth, require_role
from core.ratelimit import rate_limit
from services.stars import (
    get_or_create_referral_token, get_star_balance, get_star_history,
    get_current_cycle, get_referral_stats,
    get_payout_account, set_payout_account, get_withdrawals, request_withdrawal,
    get_star_notifications, get_unread_star_notification_count,
    mark_star_notification_read, mark_all_star_notifications_read,
)

stars_bp = Blueprint("stars", __name__)


def _masked(acc):
    if not acc: return None
    acc = dict(acc)
    ident = acc.get("account_identifier") or ""
    acc["account_identifier"] = ("*" * max(0, len(ident) - 4)) + ident[-4:]
    return acc


@stars_bp.route("/api/stars/dashboard", methods=["GET"])
@require_auth
@require_role("admin")
def api_stars_dashboard():
    sid = g.school_id
    token = get_or_create_referral_token(sid)
    balance = get_star_balance(sid)
    cycle = get_current_cycle(sid)
    referral_stats = get_referral_stats(sid)
    payout = _masked(get_payout_account(sid))

    progress = None
    if cycle:
        needed = max(0, STAR_CYCLE_MIN_PARENTS - cycle["qualifying_parent_count"])
        progress = {
            "qualifying_parent_count": cycle["qualifying_parent_count"],
            "required": STAR_CYCLE_MIN_PARENTS,
            "remaining": needed,
        }

    return jsonify({
        "ok": True,
        "star_value_tzs": STAR_VALUE_TZS,
        "balance": balance,
        "cycle_progress": progress,
        "referral_link": f"{request.host_url.rstrip('/')}/r/{token}",
        "referral_stats": referral_stats,
        "payout_account": payout,
        "unread_notifications": get_unread_star_notification_count(sid),
    })


@stars_bp.route("/api/stars/history", methods=["GET"])
@require_auth
@require_role("admin")
def api_stars_history():
    return jsonify({"ok": True, "history": get_star_history(g.school_id)})


@stars_bp.route("/api/stars/payout_account", methods=["GET"])
@require_auth
@require_role("admin")
def api_get_payout_account():
    return jsonify({"ok": True, "account": _masked(get_payout_account(g.school_id))})


@stars_bp.route("/api/stars/payout_account", methods=["POST"])
@require_auth
@require_role("admin")
@rate_limit("stars_payout_account", max_attempts=5, window_minutes=60, by="user")
def api_set_payout_account():
    d = request.json or {}
    try:
        acc = set_payout_account(g.school_id, d.get("account_identifier", ""))
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({"ok": True, "account": _masked(acc)})


@stars_bp.route("/api/stars/withdraw", methods=["POST"])
@require_auth
@require_role("admin")
@rate_limit("stars_withdraw", max_attempts=5, window_minutes=60, by="user")
def api_request_withdrawal():
    d = request.json or {}
    idem = (d.get("idempotency_key") or "").strip()
    if not idem:
        return jsonify({"ok": False, "error": "Missing idempotency_key"}), 400
    try:
        result = request_withdrawal(g.school_id, g.username, d.get("stars"), idem)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({"ok": True, **result})


@stars_bp.route("/api/stars/withdrawals", methods=["GET"])
@require_auth
@require_role("admin")
def api_list_withdrawals():
    return jsonify({"ok": True, "withdrawals": get_withdrawals(g.school_id)})


@stars_bp.route("/api/stars/notifications", methods=["GET"])
@require_auth
@require_role("admin")
def api_star_notifications():
    return jsonify({"ok": True, "notifications": get_star_notifications(g.school_id)})


@stars_bp.route("/api/stars/notifications/<int:nid>/read", methods=["POST"])
@require_auth
@require_role("admin")
def api_mark_star_notification_read(nid):
    mark_star_notification_read(g.school_id, nid)
    return jsonify({"ok": True})


@stars_bp.route("/api/stars/notifications/read_all", methods=["POST"])
@require_auth
@require_role("admin")
def api_mark_all_star_notifications_read():
    mark_all_star_notifications_read(g.school_id)
    return jsonify({"ok": True})