"""Liveness + database reachability. Public on purpose; reveals nothing but ok/degraded."""
from flask import Blueprint, jsonify

from core.monitoring import _connect   # short connect/statement timeouts

health_bp = Blueprint("health", __name__)


@health_bp.route("/health", methods=["GET", "HEAD"])
def health():
    try:
        con = _connect()
        try:
            cur = con.cursor()
            cur.execute("SELECT 1")
            cur.fetchone()
            cur.close()
        finally:
            con.close()
    except Exception:
        # Deliberately NOT recorded as a monitoring event: an uptime pinger would flood the dashboard.
        resp = jsonify({"status": "degraded", "db": "unreachable"})
        resp.status_code = 503
    else:
        resp = jsonify({"status": "ok", "db": "ok"})
    resp.headers["Cache-Control"] = "no-store"
    return resp