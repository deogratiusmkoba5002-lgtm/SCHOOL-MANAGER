"""
Generic server-side rate limiting, DB-backed so it works correctly across
multiple gunicorn workers.

Protects sensitive endpoints including registration, withdrawals, payout
changes, payment callbacks, and password changes.
"""

from functools import wraps
from flask import g, request, jsonify, make_response

from core.db import get_db


def _record(scope, identifier):
    con = get_db()
    cur = con.cursor()

    try:
        cur.execute(
            "INSERT INTO rate_limit_events(scope, identifier) VALUES(%s,%s)",
            (scope, identifier),
        )

        # Remove expired events so the table doesn't grow indefinitely.
        cur.execute(
            "DELETE FROM rate_limit_events "
            "WHERE created_at < NOW() - INTERVAL '1 day'"
        )

        con.commit()

    except Exception:
        con.rollback()
        raise

    finally:
        cur.close()
        con.close()


def _count(scope, identifier, window_minutes):
    con = get_db()
    cur = con.cursor()

    try:
        cur.execute(
            """
            SELECT COUNT(*)
            FROM rate_limit_events
            WHERE scope = %s
              AND identifier = %s
              AND created_at > NOW() - (%s * INTERVAL '1 minute')
            """,
            (scope, identifier, window_minutes),
        )

        return cur.fetchone()[0]

    finally:
        cur.close()
        con.close()


def rate_limit(
    scope,
    max_attempts,
    window_minutes,
    by="user",
    count_on="all",
):
    """
    Apply a database-backed rate limit.

    by="user":
        Use g.username when available, otherwise the request IP.

    by="ip":
        Use the request IP.

    count_on="all":
        Count every permitted request, including failed requests.

    count_on="success":
        Count only responses with an HTTP status below 400.
    """

    if count_on not in ("all", "success"):
        raise ValueError("count_on must be 'all' or 'success'")

    def deco(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if by == "user":
                identifier = (
                    getattr(g, "username", None)
                    or request.remote_addr
                    or "unknown"
                )
            else:
                identifier = request.remote_addr or "unknown"

            if _count(scope, identifier, window_minutes) >= max_attempts:
                return jsonify({
                    "ok": False,
                    "error": (
                        "Too many requests. "
                        "Please slow down and try again shortly."
                    ),
                }), 429

            if count_on == "all":
                _record(scope, identifier)
                return f(*args, **kwargs)

            response = make_response(f(*args, **kwargs))

            if response.status_code < 400:
                _record(scope, identifier)

            return response

        return wrapper

    return deco