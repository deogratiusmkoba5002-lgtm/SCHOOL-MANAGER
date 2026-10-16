"""DrDemic Mini API. Own accounts (owner/parent), own token salt. A sheet's random key is its edit link."""
import base64, io, re, secrets
from functools import wraps

from flask import Blueprint, request, jsonify, send_file, g
from itsdangerous import URLSafeTimedSerializer, BadSignature
from psycopg2.extras import Json

from config import SECRET_KEY, SESSION_MAX_AGE, ALLOWED_LOGO_EXT, _mime_for_ext
from core.db import get_db
from core.ratelimit import rate_limit
from core.security import hash_password, verify_password
from services.access import normalize_phone
from services import mini as M
from services.mini_pdf import build_pdf

mini_bp = Blueprint("mini", __name__)
_ser = URLSafeTimedSerializer(SECRET_KEY, salt="drdemic-mini-session")
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# ── auth ────────────────────────────────────────────────────
def _current_user():
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    try:
        d = _ser.loads(auth[7:].strip(), max_age=SESSION_MAX_AGE)
    except BadSignature:
        return None
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT id,username,role,token_version FROM mini_users WHERE id=%s", (d.get("uid"),))
    row = cur.fetchone(); cur.close(); con.close()
    if not row or row[3] != d.get("tv"):
        return None
    return {"id": row[0], "username": row[1], "role": row[2]}


def need_user(*roles):
    def deco(f):
        @wraps(f)
        def w(*a, **k):
            u = _current_user()
            if not u:
                return jsonify({"ok": False, "error": "Please sign in"}), 401
            if roles and u["role"] not in roles:
                return jsonify({"ok": False, "error": "Forbidden"}), 403
            g.mini_user = u
            return f(*a, **k)
        return w
    return deco


def _token_reply(uid, username, role, must_change, tv):
    return jsonify({"ok": True, "token": _ser.dumps({"uid": uid, "tv": tv}), "username": username,
                    "role": role, "must_change_password": bool(must_change)})


@mini_bp.route("/api/mini/auth/signup", methods=["POST"])
@rate_limit("mini_signup", max_attempts=5, window_minutes=60, by="ip")
def mini_signup():
    d = request.get_json(silent=True) or {}
    u, p = (d.get("username") or "").strip(), d.get("password") or ""
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,40}", u) or u.isdigit():
        return jsonify({"ok": False, "error": "Username: 3-40 letters/numbers/_ . - and at least one letter"}), 400
    if len(p) < 6:
        return jsonify({"ok": False, "error": "Password must be at least 6 characters"}), 400
    con = get_db(); cur = con.cursor()
    cur.execute("INSERT INTO mini_users(username,password,role) VALUES(%s,%s,'owner') ON CONFLICT DO NOTHING RETURNING id",
                (u, hash_password(p)))
    row = cur.fetchone(); con.commit(); cur.close(); con.close()
    if not row:
        return jsonify({"ok": False, "error": "That username is taken"}), 409
    return _token_reply(row[0], u, "owner", False, 0)


@mini_bp.route("/api/mini/auth/login", methods=["POST"])
@rate_limit("mini_login", max_attempts=15, window_minutes=15, by="ip")
def mini_login():
    d = request.get_json(silent=True) or {}
    u, p = (d.get("username") or "").strip(), d.get("password") or ""
    if not u or not p:
        return jsonify({"ok": False, "error": "Enter username and password"}), 400
    names = [u.lower()] + ([normalize_phone(u)] if normalize_phone(u) else [])
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT id,username,password,role,must_change_password,token_version FROM mini_users "
                "WHERE LOWER(username)=ANY(%s)", (names,))
    rows = cur.fetchall(); cur.close(); con.close()
    for r in rows:
        if verify_password(p, r[2]):
            return _token_reply(r[0], r[1], r[3], r[4], r[5])
    return jsonify({"ok": False, "error": "Wrong username/phone or password"}), 401


@mini_bp.route("/api/mini/auth/change_password", methods=["POST"])
@need_user()
@rate_limit("mini_pw", max_attempts=10, window_minutes=15, by="ip")
def mini_change_password():
    d = request.get_json(silent=True) or {}
    new = d.get("new_password") or ""
    if len(new) < 6:
        return jsonify({"ok": False, "error": "Password must be at least 6 characters"}), 400
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT password FROM mini_users WHERE id=%s", (g.mini_user["id"],))
    if not verify_password(d.get("old_password") or "", cur.fetchone()[0]):
        cur.close(); con.close()
        return jsonify({"ok": False, "error": "Current password is incorrect"}), 401
    cur.execute("UPDATE mini_users SET password=%s,must_change_password=0,token_version=token_version+1 "
                "WHERE id=%s RETURNING token_version", (hash_password(new), g.mini_user["id"]))
    tv = cur.fetchone()[0]; con.commit(); cur.close(); con.close()
    return _token_reply(g.mini_user["id"], g.mini_user["username"], g.mini_user["role"], False, tv)


# ── sheets ──────────────────────────────────────────────────
_F = ("id", "owner_id", "school_name", "exam_name", "class_name", "sheet_type", "grade_rules", "data", "version",
      "published", "has_logo")


def _sheet(cur, key, lock=False):
    cur.execute("SELECT id,owner_id,school_name,exam_name,class_name,sheet_type,grade_rules,data,version,published,"
                "logo_data IS NOT NULL FROM mini_sheets WHERE share_key=%s" + (" FOR UPDATE" if lock else ""), (key,))
    r = cur.fetchone()
    return dict(zip(_F, r)) if r else None


def _payload(key, s, viewer):
    return {"ok": True, "key": key, "school_name": s["school_name"], "exam_name": s["exam_name"], "class_name": s["class_name"],
            "sheet_type": s["sheet_type"], "grade_rules": s["grade_rules"], "subjects": s["data"]["subjects"],
            "rows": M.compute(s["data"], s["sheet_type"], s["grade_rules"]), "version": s["version"],
            "published": bool(s["published"]), "has_logo": s["has_logo"],
            "is_owner": bool(viewer and viewer["id"] == s["owner_id"])}


def _load(key):
    con = get_db(); cur = con.cursor()
    s = _sheet(cur, key); cur.close(); con.close()
    return s


NOT_FOUND = ({"ok": False, "error": "Sheet not found"}, 404)

@mini_bp.route("/api/mini/sheets", methods=["GET"])
@need_user("owner")
def mini_list():
    con = get_db(); cur = con.cursor()
    cur.execute("""SELECT share_key,school_name,exam_name,sheet_type,published,CAST(updated_at AS TEXT),
                          jsonb_array_length(data->'rows') FROM mini_sheets WHERE owner_id=%s
                   ORDER BY updated_at DESC""", (g.mini_user["id"],))
    rows = [{"key": r[0], "school_name": r[1], "exam_name": r[2], "sheet_type": r[3], "published": bool(r[4]),
             "updated_at": r[5], "students": r[6]} for r in cur.fetchall()]
    cur.close(); con.close()
    return jsonify({"ok": True, "sheets": rows})


@mini_bp.route("/api/mini/sheets", methods=["POST"])
@need_user("owner")
def mini_create():
    key = secrets.token_urlsafe(16)
    con = get_db(); cur = con.cursor()
    cur.execute("INSERT INTO mini_sheets(owner_id,share_key,grade_rules,data) VALUES(%s,%s,%s,%s)",
                (g.mini_user["id"], key, Json(M.DEFAULT_GRADES), Json(M.default_data())))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok": True, "key": key})


@mini_bp.route("/api/mini/sheet/<key>", methods=["GET"])
def mini_get(key):
    s = _load(key)
    return _payload(key, s, _current_user()) if s else NOT_FOUND


@mini_bp.route("/api/mini/sheet/<key>/save", methods=["POST"])
def mini_save(key):
    d = request.get_json(silent=True) or {}
    data, err = M.clean_data(d)
    rules, stype = M.clean_grades(d.get("grade_rules")), d.get("sheet_type")
    if err or rules is None or stype not in M.TYPES:
        return jsonify({"ok": False, "error": err or "Invalid grade boundaries or sheet type"}), 400
    viewer = _current_user()
    con = get_db(); cur = con.cursor()
    try:
        s = _sheet(cur, key, lock=True)
        if not s:
            cur.close(); con.close(); return NOT_FOUND
        if d.get("version") != s["version"]:
            con.rollback(); cur.close(); con.close()
            return jsonify({"ok": False, "error": "Someone else saved changes to this sheet. Reload the page to get them."}), 409
        new_meta = {"school_name": str(d.get("school_name") or "").strip()[:150],
                    "exam_name": str(d.get("exam_name") or "").strip()[:150],
                    "class_name": str(d.get("class_name") or "").strip()[:80],
                    "sheet_type": stype, "grade_rules": rules}
        changes = M.diff(s["data"], data, {k: s[k] for k in new_meta}, new_meta)
        if changes:
            is_owner = viewer and viewer["id"] == s["owner_id"]
            editor = viewer["username"] if is_owner else (str(d.get("editor") or "").strip()[:60] or "Guest")
            cur.execute("""UPDATE mini_sheets SET school_name=%s,exam_name=%s,class_name=%s,sheet_type=%s,grade_rules=%s,data=%s,
                           version=version+1,updated_at=NOW() WHERE id=%s""",
                        (new_meta["school_name"], new_meta["exam_name"], new_meta["class_name"], stype,
                         Json(rules), Json(data), s["id"]))
            cur.execute("INSERT INTO mini_history(sheet_id,editor,changes) VALUES(%s,%s,%s)",
                        (s["id"], editor, Json(changes)))
            s.update(new_meta, data=data, version=s["version"] + 1)
            if s["published"]:
                M.sync_recipients(cur, s["id"], data["rows"], True)
        con.commit()
    except Exception:
        con.rollback(); raise
    finally:
        if not cur.closed:
            cur.close(); con.close()
    return jsonify(_payload(key, s, viewer))


@mini_bp.route("/api/mini/sheet/<key>/history", methods=["GET"])
def mini_history(key):
    s = _load(key)
    if not s:
        return NOT_FOUND
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT editor,CAST(changed_at AS TEXT),changes FROM mini_history WHERE sheet_id=%s "
                "ORDER BY id DESC LIMIT 100", (s["id"],))
    rows = [{"editor": r[0], "changed_at": r[1].replace(" ", "T") + "Z", "changes": r[2]} for r in cur.fetchall()]
    cur.close(); con.close()
    return jsonify({"ok": True, "history": rows})


@mini_bp.route("/api/mini/sheet/<key>/publish", methods=["POST"])
@need_user("owner")
def mini_publish(key):
    publish = bool((request.get_json(silent=True) or {}).get("publish", True))
    con = get_db(); cur = con.cursor()
    try:
        s = _sheet(cur, key, lock=True)
        if not s or s["owner_id"] != g.mini_user["id"]:
            cur.close(); con.close(); return NOT_FOUND
        n = missing = 0
        if publish:
            cur.execute("UPDATE mini_sheets SET published=1,published_at=CASE WHEN published=1 THEN published_at "
                        "ELSE NOW() END WHERE id=%s", (s["id"],))
            rows = s["data"]["rows"]
            n = M.sync_recipients(cur, s["id"], rows, True)
            missing = sum(1 for r in rows if r["name"] and not normalize_phone(r["phone"]))
        else:
            cur.execute("UPDATE mini_sheets SET published=0 WHERE id=%s", (s["id"],))
        con.commit()
    except Exception:
        con.rollback(); raise
    finally:
        if not cur.closed:
            cur.close(); con.close()
    return jsonify({"ok": True, "published": publish, "parents": n, "missing_phone": missing})


# ── logo / files ────────────────────────────────────────────
@mini_bp.route("/api/mini/sheet/<key>/logo", methods=["POST"])
def mini_logo_up(key):
    f = request.files.get("logo")
    ext = f.filename.rsplit(".", 1)[-1].lower() if f and f.filename and "." in f.filename else ""
    if ext not in ALLOWED_LOGO_EXT:
        return jsonify({"ok": False, "error": "Logo must be an image"}), 400
    raw = f.read()
    if len(raw) > 1024 * 1024:
        return jsonify({"ok": False, "error": "Logo must be smaller than 1MB"}), 400
    con = get_db(); cur = con.cursor()
    cur.execute("UPDATE mini_sheets SET logo_data=%s,logo_mime=%s WHERE share_key=%s",
                (base64.b64encode(raw).decode("ascii"), _mime_for_ext(ext), key))
    found = cur.rowcount > 0; con.commit(); cur.close(); con.close()
    return jsonify({"ok": True}) if found else NOT_FOUND


@mini_bp.route("/api/mini/sheet/<key>/logo", methods=["GET"])
def mini_logo_get(key):
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT logo_data,logo_mime FROM mini_sheets WHERE share_key=%s", (key,))
    row = cur.fetchone(); cur.close(); con.close()
    if not row or not row[0]:
        return ("Not found", 404)
    resp = send_file(io.BytesIO(base64.b64decode(row[0])), mimetype=row[1])
    resp.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


def _fname(s, suffix, ext="xlsx"):
    base = re.sub(r"[^A-Za-z0-9_-]+", "_", s["exam_name"] or "DrDemic_Sheet").strip("_") or "DrDemic_Sheet"
    return f"{base}_{suffix}.{ext}"


@mini_bp.route("/api/mini/sheet/<key>/download.pdf", methods=["GET"])
def mini_download(key):
    s = _load(key)
    if not s:
        return NOT_FOUND
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT logo_data FROM mini_sheets WHERE share_key=%s", (key,))
    row = cur.fetchone(); cur.close(); con.close()
    buf = build_pdf(s, M.compute(s["data"], s["sheet_type"], s["grade_rules"]), row[0] if row else None)
    return send_file(buf, as_attachment=True, download_name=_fname(s, "sheet", "pdf"), mimetype="application/pdf")


@mini_bp.route("/api/mini/sheet/<key>/template.xlsx", methods=["GET"])
def mini_template(key):
    s = _load(key)
    if not s:
        return NOT_FOUND
    return send_file(M.template_xlsx(s["data"]["subjects"], s["data"]["rows"]), as_attachment=True,
                     download_name=_fname(s, "template"), mimetype=XLSX)

@mini_bp.route("/api/mini/sheet/<key>/import", methods=["POST"])
def mini_import(key):
    if not _load(key):
        return NOT_FOUND
    f = request.files.get("file")
    if not f:
        return jsonify({"ok": False, "error": "No file uploaded"}), 400
    try:
        data, err = M.clean_data(M.parse_import(f.stream, f.filename))
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    if err:
        return jsonify({"ok": False, "error": err}), 400
    return jsonify({"ok": True, **data})      # not saved: the page fills the grid, teacher presses SAVE


# ── parents ─────────────────────────────────────────────────
@mini_bp.route("/api/mini/parent/results", methods=["GET"])
@need_user("parent")
def mini_parent_results():
    phone = g.mini_user["username"]
    con = get_db(); cur = con.cursor()
    cur.execute("""SELECT s.school_name,s.exam_name,s.sheet_type,s.grade_rules,s.data,CAST(s.published_at AS TEXT)
                   FROM mini_sheets s JOIN mini_recipients r ON r.sheet_id=s.id
                   WHERE r.phone=%s AND s.published=1 ORDER BY s.published_at DESC LIMIT 50""", (phone,))
    sheets = cur.fetchall(); cur.close(); con.close()
    out = []
    for school, exam, stype, rules, data, pub in sheets:
        ranked = M.compute(data, stype, rules)
        of = sum(1 for r in ranked if r["average"] is not None)
        subs = [x for x in data["subjects"] if x["name"]]
        kids = [{"student": r["name"], "total": r["total"], "average": r["average"], "position": r["position"],
                 "out_of": of, "grade": r["grade"], "points": r["points"], "division": r["division"],
                 "subjects": [{"name": x["name"], "score": r["marks"].get(x["id"])} for x in subs]}
                for r in ranked if normalize_phone(r["phone"]) == phone]
        if kids:
            out.append({"school_name": school, "exam_name": exam, "sheet_type": stype,
                        "published_at": pub, "children": kids})
    return jsonify({"ok": True, "results": out})