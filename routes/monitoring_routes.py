"""Superadmin monitoring API. Every route checks superadmin auth FIRST."""
import re
from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify

from core.db import get_db, to_dict, to_dicts
from core.auth import _require_superadmin
from core.monitoring import SEVERITIES, SEVERITY_COLORS, _alerts_enabled

monitoring_bp = Blueprint("monitoring", __name__)

STATUSES = ("new", "investigating", "resolved", "ignored")
_EVENT_ID = re.compile(r"^EVT-[0-9A-F]{10}$")


def _iso(v):
    return (v.isoformat() + "Z") if v else None


def _build_filters():
    a = request.args
    where, params = [], []
    sev = (a.get("severity") or "").strip().upper()
    if sev:
        if sev not in SEVERITIES: raise ValueError("Invalid severity")
        where.append("e.severity=%s"); params.append(sev)
    st = (a.get("status") or "").strip().lower()
    if st:
        if st not in STATUSES: raise ValueError("Invalid status")
        where.append("e.status=%s"); params.append(st)
    sid = (a.get("school_id") or "").strip()
    if sid:
        try: val = int(sid)
        except ValueError: raise ValueError("Invalid school_id")
        where.append("e.school_id=%s"); params.append(val)
    op = (a.get("operation") or "").strip()
    if op:
        where.append("e.operation=%s"); params.append(op)
    for key, clause, delta in (("date_from", "e.created_at >= %s", 0), ("date_to", "e.created_at < %s", 1)):
        raw = (a.get(key) or "").strip()
        if raw:
            try: d = datetime.strptime(raw, "%Y-%m-%d")
            except ValueError: raise ValueError(f"Invalid {key} (use YYYY-MM-DD)")
            where.append(clause); params.append(d + timedelta(days=delta))
    return where, params


@monitoring_bp.route("/api/superadmin/monitoring/summary", methods=["GET"])
def api_mon_summary():
    sa, err = _require_superadmin()
    if err: return err
    con = get_db(); cur = con.cursor()
    try:
        cur.execute("""
            SELECT
              COUNT(*) FILTER (WHERE e.created_at >= u.t - INTERVAL '24 hours'),
              COUNT(*) FILTER (WHERE e.created_at >= u.t - INTERVAL '24 hours' AND e.severity='CRITICAL'),
              COUNT(*) FILTER (WHERE e.status IN ('new','investigating')),
              COUNT(*) FILTER (WHERE e.status IN ('new','investigating') AND e.severity='CRITICAL'),
              COUNT(*) FILTER (WHERE e.status IN ('new','investigating') AND e.severity='CRITICAL'
                                 AND e.created_at >= u.t - INTERVAL '24 hours'),
              COUNT(*) FILTER (WHERE e.status IN ('new','investigating') AND e.severity='ERROR'
                                 AND e.created_at >= u.t - INTERVAL '24 hours'),
              MAX(e.created_at)
            FROM error_events e CROSS JOIN (SELECT NOW() AT TIME ZONE 'utc' AS t) u""")
        total, crit, unres, unres_crit, crit_open_24h, err_open_24h, last = cur.fetchone()
    finally:
        cur.close(); con.close()
    health = "critical" if crit_open_24h else ("warning" if err_open_24h else "healthy")
    return jsonify({"ok": True, "window_hours": 24, "total_recent": total, "critical_recent": crit,
                    "unresolved_total": unres, "unresolved_critical": unres_crit,
                    "health": health, "last_event_at": _iso(last)})


@monitoring_bp.route("/api/superadmin/monitoring/filters", methods=["GET"])
def api_mon_filters():
    sa, err = _require_superadmin()
    if err: return err
    con = get_db(); cur = con.cursor()
    try:
        cur.execute("SELECT DISTINCT operation FROM error_events WHERE operation IS NOT NULL ORDER BY operation")
        operations = [r[0] for r in cur.fetchall()]
        cur.execute("""SELECT DISTINCT e.school_id, s.school_name FROM error_events e
                       LEFT JOIN schools s ON s.id=e.school_id WHERE e.school_id IS NOT NULL
                       ORDER BY s.school_name NULLS LAST, e.school_id""")
        schools = [{"id": r[0], "name": r[1] or f"School #{r[0]}"} for r in cur.fetchall()]
    finally:
        cur.close(); con.close()
    return jsonify({"ok": True, "operations": operations, "schools": schools,
                    "statuses": list(STATUSES), "severities": list(SEVERITIES)})


@monitoring_bp.route("/api/superadmin/monitoring/events", methods=["GET"])
def api_mon_events():
    sa, err = _require_superadmin()
    if err: return err
    try:
        where, params = _build_filters()
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    try:
        limit = min(max(int(request.args.get("limit", 50)), 1), 200)
        offset = max(int(request.args.get("offset", 0)), 0)
    except ValueError:
        return jsonify({"ok": False, "error": "Invalid limit/offset"}), 400
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    con = get_db(); cur = con.cursor()
    try:
        cur.execute(f"SELECT COUNT(*) FROM error_events e {clause}", params)
        total = cur.fetchone()[0]
        cur.execute(f"""SELECT e.event_id,e.severity,e.status,e.created_at,e.operation,e.endpoint,e.method,e.path,
                               e.http_status,e.exception_type,LEFT(e.message,200) AS message,e.school_id,
                               s.school_name,e.username,e.role
                        FROM error_events e LEFT JOIN schools s ON s.id=e.school_id {clause}
                        ORDER BY e.created_at DESC, e.id DESC LIMIT %s OFFSET %s""", params + [limit, offset])
        rows = to_dicts(cur.fetchall(), cur)
    finally:
        cur.close(); con.close()
    for r in rows:
        r["created_at"] = _iso(r["created_at"])
    return jsonify({"ok": True, "total": total, "limit": limit, "offset": offset, "events": rows})


@monitoring_bp.route("/api/superadmin/monitoring/events/<event_id>", methods=["GET"])
def api_mon_event_detail(event_id):
    sa, err = _require_superadmin()
    if err: return err
    if not _EVENT_ID.match(event_id):
        return jsonify({"ok": False, "error": "Event not found"}), 404
    con = get_db(); cur = con.cursor()
    try:
        cur.execute("""SELECT e.*, s.school_name FROM error_events e
                       LEFT JOIN schools s ON s.id=e.school_id WHERE e.event_id=%s""", (event_id,))
        row = cur.fetchone(); ev = to_dict(row, cur) if row else None
    finally:
        cur.close(); con.close()
    if not ev:
        return jsonify({"ok": False, "error": "Event not found"}), 404
    ev.pop("id", None)
    ev["created_at"] = _iso(ev["created_at"])
    ev["severity_color"] = SEVERITY_COLORS.get(ev["severity"])
    return jsonify({"ok": True, "event": ev})


@monitoring_bp.route("/api/superadmin/monitoring/events/<event_id>", methods=["POST"])
def api_mon_event_update(event_id):
    sa, err = _require_superadmin()
    if err: return err
    if not _EVENT_ID.match(event_id):
        return jsonify({"ok": False, "error": "Event not found"}), 404
    d = request.get_json(silent=True)
    if not isinstance(d, dict): d = {}
    sets, params = [], []
    if "status" in d:
        st = str(d["status"]).strip().lower()
        if st not in STATUSES:
            return jsonify({"ok": False, "error": "Invalid status"}), 400
        sets.append("status=%s"); params.append(st)
    if "admin_notes" in d:
        notes = str(d["admin_notes"] or "")
        if len(notes) > 5000:
            return jsonify({"ok": False, "error": "Notes are too long (max 5000 characters)"}), 400
        sets.append("admin_notes=%s"); params.append(notes)
    if not sets:
        return jsonify({"ok": False, "error": "Nothing to update"}), 400
    con = get_db(); cur = con.cursor()
    try:
        cur.execute(f"UPDATE error_events SET {','.join(sets)} WHERE event_id=%s", params + [event_id])
        found = cur.rowcount > 0
        con.commit()
    except Exception:
        con.rollback(); raise
    finally:
        cur.close(); con.close()
    if not found:
        return jsonify({"ok": False, "error": "Event not found"}), 404
    return jsonify({"ok": True})

# ── GROUPS (what the dashboard shows) ───────────────────────────
_GROUP_SORTS = {
    "last_seen": "g.last_seen DESC, g.id DESC",
    "first_seen": "g.first_seen DESC, g.id DESC",
    "occurrences": "g.occurrence_count DESC, g.last_seen DESC, g.id DESC",
    "severity": "CASE g.severity WHEN 'CRITICAL' THEN 0 WHEN 'ERROR' THEN 1 WHEN 'WARNING' THEN 2 ELSE 3 END, "
                "g.last_seen DESC, g.id DESC",
}


def _group_filters():
    a = request.args
    where, params = [], []
    sev = (a.get("severity") or "").strip().upper()
    if sev:
        if sev not in SEVERITIES: raise ValueError("Invalid severity")
        where.append("g.severity=%s"); params.append(sev)
    st = (a.get("status") or "").strip().lower()
    if st:
        if st not in STATUSES: raise ValueError("Invalid status")
        where.append("g.status=%s"); params.append(st)
    sid = (a.get("school_id") or "").strip()
    if sid:
        try: val = int(sid)
        except ValueError: raise ValueError("Invalid school_id")
        where.append("EXISTS (SELECT 1 FROM error_events e WHERE e.fingerprint=g.fingerprint AND e.school_id=%s)")
        params.append(val)
    op = (a.get("operation") or "").strip()
    if op:
        where.append("g.operation=%s"); params.append(op)
    for key, clause, delta in (("date_from", "g.last_seen >= %s", 0), ("date_to", "g.last_seen < %s", 1)):
        raw = (a.get(key) or "").strip()
        if raw:
            try: d = datetime.strptime(raw, "%Y-%m-%d")
            except ValueError: raise ValueError(f"Invalid {key} (use YYYY-MM-DD)")
            where.append(clause); params.append(d + timedelta(days=delta))
    q = (a.get("q") or "").strip()[:100]
    if q:
        where.append("(g.exception_type ILIKE %s OR g.endpoint ILIKE %s OR g.operation ILIKE %s OR g.sample_message ILIKE %s)")
        params += [f"%{q}%"] * 4
    return where, params


@monitoring_bp.route("/api/superadmin/monitoring/groups/summary", methods=["GET"])
def api_mon_groups_summary():
    sa, err = _require_superadmin()
    if err: return err
    con = get_db(); cur = con.cursor()
    try:
        cur.execute("""
            SELECT
              COUNT(*) FILTER (WHERE g.last_seen >= u.t - INTERVAL '24 hours' AND g.status<>'ignored'),
              COUNT(*) FILTER (WHERE g.last_seen >= u.t - INTERVAL '24 hours' AND g.status<>'ignored' AND g.severity='CRITICAL'),
              COUNT(*) FILTER (WHERE g.status IN ('new','investigating')),
              COUNT(*) FILTER (WHERE g.status IN ('new','investigating') AND g.severity='CRITICAL'),
              COUNT(*) FILTER (WHERE g.status IN ('new','investigating') AND g.severity='CRITICAL'
                                 AND g.last_seen >= u.t - INTERVAL '24 hours'),
              COUNT(*) FILTER (WHERE g.status IN ('new','investigating') AND g.severity='ERROR'
                                 AND g.last_seen >= u.t - INTERVAL '24 hours'),
              MAX(g.last_seen)
            FROM error_groups g CROSS JOIN (SELECT NOW() AT TIME ZONE 'utc' AS t) u""")
        active, crit, unres, unres_crit, crit_open_24h, err_open_24h, last = cur.fetchone()
    finally:
        cur.close(); con.close()
    health = "critical" if crit_open_24h else ("warning" if err_open_24h else "healthy")
    return jsonify({"ok": True, "window_hours": 24, "active_recent": active, "critical_recent": crit,
                    "unresolved_total": unres, "unresolved_critical": unres_crit, "health": health,
                    "last_event_at": _iso(last), "alerts_enabled": _alerts_enabled()})


@monitoring_bp.route("/api/superadmin/monitoring/groups", methods=["GET"])
def api_mon_groups():
    sa, err = _require_superadmin()
    if err: return err
    try:
        where, params = _group_filters()
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    sort = (request.args.get("sort") or "last_seen").strip()
    if sort not in _GROUP_SORTS:
        return jsonify({"ok": False, "error": "Invalid sort"}), 400
    try:
        limit = min(max(int(request.args.get("limit", 25)), 1), 100)
        offset = max(int(request.args.get("offset", 0)), 0)
    except ValueError:
        return jsonify({"ok": False, "error": "Invalid limit/offset"}), 400
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    con = get_db(); cur = con.cursor()
    try:
        cur.execute(f"SELECT COUNT(*) FROM error_groups g {clause}", params)
        total = cur.fetchone()[0]
        cur.execute(f"""SELECT g.id,g.severity,g.status,g.exception_type,g.endpoint,g.operation,g.occurrence_count,
                               g.first_seen,g.last_seen,g.last_event_id,g.last_school_id,s.school_name,
                               LEFT(g.sample_message,200) AS message
                        FROM error_groups g LEFT JOIN schools s ON s.id=g.last_school_id {clause}
                        ORDER BY {_GROUP_SORTS[sort]} LIMIT %s OFFSET %s""", params + [limit, offset])
        rows = to_dicts(cur.fetchall(), cur)
    finally:
        cur.close(); con.close()
    for r in rows:
        r["first_seen"] = _iso(r["first_seen"]); r["last_seen"] = _iso(r["last_seen"])
    return jsonify({"ok": True, "total": total, "limit": limit, "offset": offset, "groups": rows})


@monitoring_bp.route("/api/superadmin/monitoring/groups/<int:gid>", methods=["GET"])
def api_mon_group_detail(gid):
    sa, err = _require_superadmin()
    if err: return err
    con = get_db(); cur = con.cursor()
    try:
        cur.execute("""SELECT g.*, s.school_name FROM error_groups g
                       LEFT JOIN schools s ON s.id=g.last_school_id WHERE g.id=%s""", (gid,))
        row = cur.fetchone(); grp = to_dict(row, cur) if row else None
        if not grp:
            return jsonify({"ok": False, "error": "Group not found"}), 404
        cur.execute("""SELECT e.*, s.school_name FROM error_events e
                       LEFT JOIN schools s ON s.id=e.school_id WHERE e.event_id=%s""", (grp["last_event_id"],))
        row = cur.fetchone(); latest = to_dict(row, cur) if row else None
        cur.execute("""SELECT e.event_id,e.created_at,e.school_id,s.school_name,e.username,e.role,e.http_status
                       FROM error_events e LEFT JOIN schools s ON s.id=e.school_id
                       WHERE e.fingerprint=%s ORDER BY e.id DESC LIMIT 25""", (grp["fingerprint"],))
        occurrences = to_dicts(cur.fetchall(), cur)
    finally:
        cur.close(); con.close()
    for k in ("first_seen", "last_seen", "last_alert_at"):
        grp[k] = _iso(grp[k])
    if latest:
        latest.pop("id", None); latest["created_at"] = _iso(latest["created_at"])
    for o in occurrences:
        o["created_at"] = _iso(o["created_at"])
    return jsonify({"ok": True, "group": grp, "latest": latest, "occurrences": occurrences,
                    "severity_color": SEVERITY_COLORS.get(grp["severity"])})


@monitoring_bp.route("/api/superadmin/monitoring/groups/<int:gid>", methods=["POST"])
def api_mon_group_update(gid):
    sa, err = _require_superadmin()
    if err: return err
    d = request.get_json(silent=True)
    if not isinstance(d, dict): d = {}
    sets, params = [], []
    if "status" in d:
        st = str(d["status"]).strip().lower()
        if st not in STATUSES:
            return jsonify({"ok": False, "error": "Invalid status"}), 400
        sets.append("status=%s"); params.append(st)
    if "admin_notes" in d:
        notes = str(d["admin_notes"] or "")
        if len(notes) > 5000:
            return jsonify({"ok": False, "error": "Notes are too long (max 5000 characters)"}), 400
        sets.append("admin_notes=%s"); params.append(notes)
    if not sets:
        return jsonify({"ok": False, "error": "Nothing to update"}), 400
    con = get_db(); cur = con.cursor()
    try:
        cur.execute(f"UPDATE error_groups SET {','.join(sets)} WHERE id=%s", params + [gid])
        found = cur.rowcount > 0
        con.commit()
    except Exception:
        con.rollback(); raise
    finally:
        cur.close(); con.close()
    if not found:
        return jsonify({"ok": False, "error": "Group not found"}), 404
    return jsonify({"ok": True})