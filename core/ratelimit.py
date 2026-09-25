"""
Generic server-side rate limiting, DB-backed so it works correctly across
multiple gunicorn workers — an in-memory counter would give each worker
its own private, useless copy. Guards sensitive endpoints per the Star
System security spec (section 26): registration, withdrawals, payout
changes, payment callbacks, password changes.
"""
from functools import wraps
from flask import g, request, jsonify

from core.db import get_db


def _record(scope, identifier):
    con = get_db(); cur = con.cursor()
    cur.execute("INSERT INTO rate_limit_events(scope, identifier) VALUES(%s,%s)", (scope, identifier))
    # Housekeeping on every write so this table never becomes its own liability.
    cur.execute("DELETE FROM rate_limit_events WHERE created_at < NOW() - INTERVAL '1 day'")
    con.commit(); cur.close(); con.close()


def _count(scope, identifier, window_minutes):
    con = get_db(); cur = con.cursor()
    cur.execute("""SELECT COUNT(*) FROM rate_limit_events
                   WHERE scope=%s AND identifier=%s AND created_at > NOW() - (%s * INTERVAL '1 minute')""",
                (scope, identifier, window_minutes))
    n = cur.fetchone()[0]; cur.close(); con.close()
    return n


def rate_limit(scope, max_attempts, window_minutes, by="user"):
    """Decorator. by="user" keys on g.username (set by require_auth, which
    must sit ABOVE this decorator in the stack — i.e. closer to the route
    line); by="ip" keys on the request's remote address for unauthenticated
    endpoints. Every call counts, even ones that later fail validation —
    that's the point, it's what stops a client hammering the endpoint."""
    def deco(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if by == "user":
                identifier = getattr(g, "username", None) or request.remote_addr or "unknown"
            else:
                identifier = request.remote_addr or "unknown"
            if _count(scope, identifier, window_minutes) >= max_attempts:
                return jsonify({"ok": False, "error": "Too many requests. Please slow down and try again shortly."}), 429
            _record(scope, identifier)
            return f(*args, **kwargs)
        return wrapper
    return deco