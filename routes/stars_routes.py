"""
Star System routes — read-only dashboard for Phase 3. All financial
figures are computed server-side from services/stars.py; nothing here
accepts stars/amount/balance from the client.
"""
from flask import Blueprint, jsonify, g, request

from config import STAR_VALUE_TZS, STAR_CYCLE_MIN_PARENTS
from core.auth import require_auth, require_role
from core.school import get_school_id_by_reg_code
from services.stars import (
    get_or_create_referral_token, get_star_balance, get_star_history,
    get_current_cycle, get_referral_stats, log_star_event,
)

stars_bp = Blueprint("stars", __name__)


@stars_bp.route("/api/stars/dashboard", methods=["GET"])
@require_auth
@require_role("admin")
def api_stars_dashboard():
    sid = g.school_id
    token = get_or_create_referral_token(sid)
    balance = get_star_balance(sid)
    cycle = get_current_cycle(sid)
    referral_stats = get_referral_stats(sid)

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
    })


@stars_bp.route("/api/stars/history", methods=["GET"])
@require_auth
@require_role("admin")
def api_stars_history():
    sid = g.school_id
    return jsonify({"ok": True, "history": get_star_history(sid)})