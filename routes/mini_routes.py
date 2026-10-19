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
from services.access import normalize_phone, SnippeError
from services import mini as M
from services import mini_access as MA
from services.mini_pdf import build_pdf
from services.mini_agents import attach_referral

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
@rate_limit("mini_signup_attempts", max_attempts=60, window_minutes=60, by="ip")
@rate_limit("mini_signup", max_attempts=10, window_minutes=60, by="ip", count_on="success")
def mini_signup():
    d = request.get_json(silent=True) or {}
    u, p = (d.get("username") or "").strip(), d.get("password") or ""
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,40}", u) or u.isdigit():
        return jsonify({"ok": False, "error": "Username: 3-40 letters/numbers/_ . - and at least one letter"}), 400
    if len(p) < 6:
        return jsonify({"ok": False, "error": "Password must be at least 6 characters"}), 400
    if p != (d.get("confirm_password") or ""):
        return jsonify({"ok": False, "error": "Passwords do not match"}), 400
    if not d.get("agree_terms"):
        return jsonify({"ok": False, "error": "You must agree to the Privacy Policy and Terms to create an account"}), 400
    phone = normalize_phone(d.get("phone"))
    if not phone:
        return jsonify({"ok": False, "error": "Enter a valid phone number, e.g. 0712345678 (used to verify you if you lose your password)"}), 400
    con = get_db(); cur = con.cursor()
    cur.execute("INSERT INTO mini_users(username,password,role,phone) VALUES(%s,%s,'owner',%s) ON CONFLICT DO NOTHING RETURNING id",
                (u, hash_password(p), phone))
    row = cur.fetchone(); con.commit(); cur.close(); con.close()
    if not row:
        return jsonify({"ok": False, "error": "That username is taken"}), 409
    attach_referral(row[0], phone, d.get("ref"))
    return _token_reply(row[0], u, "owner", False, 0)


@mini_bp.route("/api/mini/auth/login", methods=["POST"])
@rate_limit("mini_login", max_attempts=60, window_minutes=15, by="ip")
def mini_login():
    d = request.get_json(silent=True) or {}
    u, p = (d.get("username") or "").strip(), d.get("password") or ""
    if not u or not p:
        return jsonify({"ok": False, "error": "Enter username and password"}), 400
    names = [u.lower()] + ([normalize_phone(u)] if normalize_phone(u) else [])
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT id,username,password,role,must_change_password,token_version FROM mini_users "
                "WHERE LOWER(username)=ANY(%s)", (names,))
    rows = cur.fetchall()
    # a linked parent can also sign in with the child's name
    cur.execute("SELECT u.id,s.name,u.password,u.role,u.must_change_password,u.token_version "
                "FROM mini_students s JOIN mini_users u ON u.id=s.parent_user_id WHERE s.name_norm=%s", (M.norm(u),))
    rows += cur.fetchall()
    cur.close(); con.close()
    matches = {r[0]: r for r in rows if verify_password(p, r[2])}
    if len(matches) == 1:
        r = next(iter(matches.values()))
        return _token_reply(r[0], r[1], r[3], r[4], r[5])
    if len(matches) > 1:
        return jsonify({"ok": False, "error": "Several children share this name and password. "
                        "Please sign in through the results link your teacher shared."}), 409
    return jsonify({"ok": False, "error": "Wrong username/name or password"}), 401


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
      "published", "has_logo", "pub_token")


def _sheet(cur, key, lock=False):
    cur.execute("SELECT id,owner_id,school_name,exam_name,class_name,sheet_type,grade_rules,data,version,published,"
                "logo_data IS NOT NULL,pub_token FROM mini_sheets WHERE share_key=%s" + (" FOR UPDATE" if lock else ""), (key,))
    r = cur.fetchone()
    return dict(zip(_F, r)) if r else None


def _payload(key, s, viewer):
    is_owner = bool(viewer and viewer["id"] == s["owner_id"])
    con = get_db(); cur = con.cursor()
    linked = sorted(M.linked_names(cur, s["owner_id"]))
    cur.execute("SELECT DISTINCT TRIM(e->>'name') FROM mini_sheets, jsonb_array_elements(data->'subjects') e "
                "WHERE owner_id=%s", (s["owner_id"],))
    _sg = {}
    for (n,) in cur.fetchall():
        if n: _sg.setdefault(n.lower(), n)
    suggestions = sorted(_sg.values(), key=str.lower)
    restr = {}
    if is_owner:
        cur.execute("SELECT name_norm,reason FROM mini_restrictions WHERE sheet_id=%s", (s["id"],))
        restr = dict(cur.fetchall())
    cur.close(); con.close()
    return {"ok": True, "key": key, "school_name": s["school_name"], "exam_name": s["exam_name"], "class_name": s["class_name"],
            "sheet_type": s["sheet_type"], "grade_rules": s["grade_rules"], "subjects": s["data"]["subjects"],
            "noncredit": s["data"].get("noncredit",[]),
            "rows": M.compute(s["data"], s["sheet_type"], s["grade_rules"]), "version": s["version"],
            "published": bool(s["published"]), "has_logo": s["has_logo"], "is_owner": is_owner,
            "linked": linked, "restrictions": restr, "subject_suggestions": suggestions,
            "link": f"/mini/parents/{M.slug(s['school_name'])}/{s['pub_token']}" if s["pub_token"] else None}


def _load(key):
    con = get_db(); cur = con.cursor()
    s = _sheet(cur, key); cur.close(); con.close()
    return s


NOT_FOUND = ({"ok": False, "error": "Sheet not found"}, 404)

@mini_bp.route("/api/mini/sheets", methods=["GET"])
@need_user("owner")
def mini_list():
    uid = g.mini_user["id"]
    con = get_db(); cur = con.cursor()
    cur.execute("""SELECT share_key,school_name,exam_name,sheet_type,published,CAST(updated_at AS TEXT),
                          jsonb_array_length(data->'rows'), owner_id<>%s
                   FROM mini_sheets
                   WHERE owner_id=%s OR id IN (SELECT sheet_id FROM mini_sheet_access WHERE user_id=%s)
                   ORDER BY updated_at DESC""", (uid, uid, uid))
    rows = [{"key": r[0], "school_name": r[1], "exam_name": r[2], "sheet_type": r[3], "published": bool(r[4]),
             "updated_at": r[5], "students": r[6], "shared": bool(r[7])} for r in cur.fetchall()]
    cur.execute("SELECT phone FROM mini_users WHERE id=%s", (uid,))
    has_phone = bool(cur.fetchone()[0])
    cur.close(); con.close()
    return jsonify({"ok": True, "sheets": rows, "has_phone": has_phone})


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
    if not s:
        return NOT_FOUND
    viewer = _current_user()
    if viewer and viewer["role"] == "owner" and viewer["id"] != s["owner_id"]:
        con = get_db(); cur = con.cursor()
        cur.execute("INSERT INTO mini_sheet_access(user_id,sheet_id) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                    (viewer["id"], s["id"]))
        con.commit(); cur.close(); con.close()
    return _payload(key, s, viewer)


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
                M.sync_students(cur, s["owner_id"], data["rows"])
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
    d = request.get_json(silent=True) or {}
    publish = bool(d.get("publish", True))
    restrict = d.get("restrict")
    out = {"ok": True, "published": publish}
    con = get_db(); cur = con.cursor()
    try:
        s = _sheet(cur, key, lock=True)
        if not s or s["owner_id"] != g.mini_user["id"]:
            cur.close(); con.close(); return NOT_FOUND
        if publish:
            seen_names, dupes = set(), set()
            for r in s["data"]["rows"]:
                nn = M.norm(r["name"])
                if nn and nn in seen_names:
                    dupes.add(r["name"].strip())
                seen_names.add(nn)
            if dupes:
                con.rollback(); cur.close(); con.close()
                return jsonify({"ok": False, "error": "These names appear more than once: "
                                + ", ".join(sorted(dupes)[:5])
                                + ". Make each name unique (add a middle name) before publishing."}), 400
            token = s["pub_token"] or secrets.token_urlsafe(6)
            cur.execute("UPDATE mini_sheets SET published=1, pub_token=%s, published_at=CASE WHEN published=1 "
                        "THEN published_at ELSE NOW() END WHERE id=%s", (token, s["id"]))
            rows = s["data"]["rows"]
            M.sync_students(cur, s["owner_id"], rows)
            if isinstance(restrict, list):
                M.set_restrictions(cur, s["id"], restrict)
            linked = M.linked_names(cur, s["owner_id"])
            named = [r for r in rows if r["name"]]
            cur.execute("SELECT COUNT(*) FROM mini_restrictions WHERE sheet_id=%s", (s["id"],))
            out.update(students=len(named), restricted=cur.fetchone()[0],
                       linked=sum(1 for r in named if M.norm(r["name"]) in linked),
                       missing_phone=sum(1 for r in named if M.norm(r["name"]) not in linked
                                         and not normalize_phone(r["phone"])),
                       link=f"/mini/parents/{M.slug(s['school_name'])}/{token}")
        else:
            cur.execute("UPDATE mini_sheets SET published=0 WHERE id=%s", (s["id"],))
        con.commit()
    except Exception:
        con.rollback(); raise
    finally:
        if not cur.closed:
            cur.close(); con.close()
    return jsonify(out)

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
def _covered(at, periods):
    """Was the parent subscribed at time `at`? Each completed payment covers [paid_at, expires_at]."""
    return any(p and e and p <= at <= e for p, e in periods)


@mini_bp.route("/api/mini/parent/results", methods=["GET"])
@need_user("parent")
def mini_parent_results():
    pub = (request.args.get("pub") or "").strip()
    uid = g.mini_user["id"]
    active = MA.get_access(uid)["active"]
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT owner_id,name_norm FROM mini_students WHERE parent_user_id=%s", (uid,))
    mine = set(cur.fetchall())
    owners = sorted({o for o, _ in mine})
    sheets, restr, anns, periods = [], {}, [], []
    if owners:
        cur.execute("SELECT paid_at,expires_at FROM mini_payments WHERE user_id=%s "
                    "AND status='completed' AND applied=1", (uid,))
        periods = cur.fetchall()
        q = ("SELECT id,owner_id,school_name,exam_name,class_name,sheet_type,grade_rules,data,published_at,"
             "grandfathered,pub_token FROM mini_sheets WHERE owner_id=ANY(%s) AND published=1")
        args = [owners]
        if pub:
            q += " AND pub_token=%s"; args.append(pub)
        cur.execute(q + " ORDER BY published_at DESC LIMIT 200", args)
        sheets = cur.fetchall()
        ids = [x[0] for x in sheets]
        if ids:
            cur.execute("SELECT sheet_id,name_norm,reason FROM mini_restrictions WHERE sheet_id=ANY(%s)", (ids,))
            restr = {(a, b): c for a, b, c in cur.fetchall()}
        cur.execute("""SELECT a.owner_id,a.title,a.body,CAST(a.posted_at AS TEXT),s.exam_name,s.data
                       FROM mini_announcements a JOIN mini_sheets s ON s.id=a.sheet_id
                       WHERE a.owner_id=ANY(%s) ORDER BY a.id DESC LIMIT 100""", (owners,))
        anns = cur.fetchall()
    cur.close(); con.close()
    out = []
    for sid, owner, school, exam, cls, stype, rules, data, pubat, gf, ptoken in sheets:
        locked = not (active or gf or not pubat or _covered(pubat, periods))
        ranked = M.compute(data, stype, rules)
        of = sum(1 for r in ranked if r["average"] is not None)
        subs = [x for x in data["subjects"] if x["name"]]
        def _pos(x, r, ranked=ranked, stype=stype):
            v = r["marks"].get(x["id"])
            if stype != "marks" or v is None:
                return None, None
            col = [o["marks"][x["id"]] for o in ranked if o["name"] and o["marks"].get(x["id"]) is not None]
            return 1 + sum(1 for m in col if m > v), len(col)
        kids = []
        for r in ranked:
            nn = M.norm(r["name"])
            if (owner, nn) not in mine:
                continue
            if locked:                                           # no scores leave the server
                kids.append({"student": r["name"], "locked": True})
                continue
            if (sid, nn) in restr:
                kids.append({"student": r["name"], "restricted": True, "reason": restr[(sid, nn)]})
                continue
            kids.append({"student": r["name"], "total": r["total"], "average": r["average"], "position": r["position"],
                         "out_of": of, "grade": r["grade"], "points": r["points"], "division": r["division"],
                         "subjects": [{"name": x["name"], "score": r["marks"].get(x["id"]),
                                       "position": p, "out_of": n}
                                       for x in subs for p, n in [_pos(x, r)]]})
        if kids:
            out.append({"token": ptoken, "school_name": school, "exam_name": exam, "class_name": cls,
                        "sheet_type": stype, "published_at": str(pubat) if pubat else None,
                        "locked": locked, "children": kids})
    ann_out = []
    for owner, title, body, at, exam, data in anns:
        if any((owner, M.norm(r["name"])) in mine for r in data["rows"]):
            ann_out.append({"title": title, "body": body, "posted_at": at, "exam_name": exam})
            if len(ann_out) >= 30:
                break
    return jsonify({"ok": True, "results": out, "announcements": ann_out, "subscribed": active})

# ── parent link (shared on WhatsApp) ────────────────────────
@mini_bp.route("/api/mini/link/<token>", methods=["GET"])
def mini_link_info(token):
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT school_name,exam_name,class_name FROM mini_sheets WHERE pub_token=%s AND published=1", (token,))
    row = cur.fetchone(); cur.close(); con.close()
    if not row:
        return NOT_FOUND
    return jsonify({"ok": True, "school_name": row[0], "exam_name": row[1], "class_name": row[2]})


@mini_bp.route("/api/mini/link/<token>/login", methods=["POST"])
@rate_limit("mini_link_login", max_attempts=120, window_minutes=15, by="ip")
def mini_link_login(token):
    d = request.get_json(silent=True) or {}
    mode = d.get("mode") or "signin"
    nn = M.norm(d.get("name"))

    def fail(msg, code=None, status=401):
        return jsonify({"ok": False, "error": msg, "code": code}), status

    if not nn:
        return fail("Enter the child's full name", "no_name", 400)
    con = get_db(); cur = con.cursor()
    try:
        cur.execute("SELECT owner_id,data FROM mini_sheets WHERE pub_token=%s AND published=1", (token,))
        sh = cur.fetchone()
        if not sh:
            return NOT_FOUND
        owner, data = sh
        if nn not in {M.norm(r["name"]) for r in data["rows"]}:
            return fail("That name is not on this results sheet. Type the child's full name exactly as the school wrote it.",
                        "no_such_child")
        cur.execute("SELECT id,name,phone,parent_user_id FROM mini_students "
                    "WHERE owner_id=%s AND name_norm=%s FOR UPDATE", (owner, nn))
        st = cur.fetchone()
        if not st:
            return fail("These results are not ready yet. Please ask the teacher to publish again.", "not_ready", 404)
        sid, name, phone, puid = st

        if mode == "activate":
            if puid:
                return fail("This child already has an account. Choose 'I have an account' and sign in.",
                            "already_linked", 409)
            if not phone:
                return fail("The school has no phone number saved for this child. Please ask the teacher to add it, then try again.",
                            "no_phone", 400)
            given = normalize_phone(d.get("phone"))
            if not given:
                return fail("Enter a valid phone number, e.g. 0712345678", "bad_phone", 400)
            if given != phone:
                return fail("This phone number does not match the one the school has for this child. Check it, or ask the teacher to correct it.",
                            "phone_mismatch")
            new = d.get("new_password") or ""
            if len(new) < 6:
                return fail("Password must be at least 6 characters", "weak_password", 400)
            if new != (d.get("confirm_password") or ""):
                return fail("Passwords do not match", "pw_mismatch", 400)
            cur.execute("INSERT INTO mini_users(username,password,role) VALUES(%s,%s,'parent') RETURNING id",
                        (f"p{owner}:{nn}"[:200], hash_password(new)))
            uid = cur.fetchone()[0]
            cur.execute("UPDATE mini_students SET parent_user_id=%s WHERE id=%s", (uid, sid))
            con.commit()
            return _token_reply(uid, name, "parent", False, 0)

        # sign in
        pw = d.get("password") or ""
        if not pw:
            return fail("Enter your password", "no_password", 400)
        if not puid:
            return fail("No account exists for this child yet. Choose 'First time? Activate'.", "not_activated")
        cur.execute("SELECT password,token_version,must_change_password FROM mini_users WHERE id=%s", (puid,))
        u = cur.fetchone()
        if not u or not verify_password(pw, u[0]):
            return fail("Wrong password. If you forgot it, ask the teacher for a reset code.", "bad_password")
        return _token_reply(puid, name, "parent", u[2], u[1])
    except Exception:
        con.rollback(); raise
    finally:
        cur.close(); con.close()


@mini_bp.route("/api/mini/sheet/<key>/announce", methods=["POST"])
@need_user("owner")
@rate_limit("mini_announce", max_attempts=30, window_minutes=60, by="ip")
def mini_announce(key):
    d = request.get_json(silent=True) or {}
    title, body = str(d.get("title") or "").strip()[:150], str(d.get("body") or "").strip()[:2000]
    if not title or not body:
        return jsonify({"ok": False, "error": "Title and message are required"}), 400
    con = get_db(); cur = con.cursor()
    try:
        s = _sheet(cur, key)
        if not s or s["owner_id"] != g.mini_user["id"]:
            cur.close(); con.close(); return NOT_FOUND
        cur.execute("INSERT INTO mini_announcements(sheet_id,owner_id,title,body) VALUES(%s,%s,%s,%s)",
                    (s["id"], s["owner_id"], title, body))
        names = {M.norm(r["name"]) for r in s["data"]["rows"] if r["name"]}
        n = len(names & M.linked_names(cur, s["owner_id"]))
        con.commit()
    except Exception:
        con.rollback(); raise
    finally:
        if not cur.closed:
            cur.close(); con.close()
    return jsonify({"ok": True, "parents": n})

# ── parent subscription (Snippe) ────────────────────────────
def _iso(d):
    return d.isoformat() + "Z" if d else None


@mini_bp.route("/api/mini/access/status", methods=["GET"])
@need_user("parent")
def mini_access_status():
    uid = g.mini_user["id"]
    MA.refresh_pending(uid)
    acc = MA.get_access(uid)
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT id,plan,amount,status,paid_at,expires_at,created_at FROM mini_payments "
                "WHERE user_id=%s ORDER BY id DESC LIMIT 10", (uid,))
    hist = [{"id": r[0], "plan": r[1], "amount": r[2], "status": r[3], "paid_at": _iso(r[4]),
             "expires_at": _iso(r[5]), "created_at": _iso(r[6])} for r in cur.fetchall()]
    cur.close(); con.close()
    pending = next((h for h in hist if h["status"] == "pending"), None)
    return jsonify({"ok": True, **acc, "plans": MA.plans_public(), "pending": pending, "history": hist})


@mini_bp.route("/api/mini/access/pay", methods=["POST"])
@need_user("parent")
def mini_access_pay():
    d = request.get_json(silent=True) or {}
    try:
        res = MA.start_payment(g.mini_user["id"], (d.get("plan") or "").strip(), d.get("phone") or "")
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except SnippeError as e:
        return jsonify({"ok": False, "error": str(e)}), 502
    return jsonify({"ok": True, **res})


@mini_bp.route("/api/mini/access/check/<int:pid>", methods=["POST"])
@need_user("parent")
def mini_access_check(pid):
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT user_id FROM mini_payments WHERE id=%s", (pid,))
    row = cur.fetchone(); cur.close(); con.close()
    if not row or row[0] != g.mini_user["id"]:
        return jsonify({"ok": False, "error": "Payment not found"}), 404
    status = MA.finalize_payment(pid)
    return jsonify({"ok": True, "status": status, "access": MA.get_access(g.mini_user["id"])})


# ── parent analytics (subscribers only) ─────────────────────
@mini_bp.route("/api/mini/parent/analytics", methods=["GET"])
@need_user("parent")
def mini_parent_analytics():
    uid = g.mini_user["id"]
    if not MA.get_access(uid)["active"]:
        return jsonify({"ok": False, "error": "Subscribe to unlock analytics",
                        "code": "subscription_required"}), 402
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT owner_id,name_norm,name FROM mini_students WHERE parent_user_id=%s", (uid,))
    mine = cur.fetchall()
    owners = sorted({m[0] for m in mine})
    sheets, restr = [], set()
    if owners:
        # stable order: published_at, then id as tie-breaker
        cur.execute("SELECT id,owner_id,exam_name,sheet_type,grade_rules,data,published_at FROM mini_sheets "
                    "WHERE owner_id=ANY(%s) AND published=1 "
                    "ORDER BY published_at DESC NULLS LAST, id DESC LIMIT 60", (owners,))
        sheets = cur.fetchall()
        ids = [x[0] for x in sheets]
        if ids:
            cur.execute("SELECT sheet_id,name_norm FROM mini_restrictions WHERE sheet_id=ANY(%s)", (ids,))
            restr = set(cur.fetchall())
    cur.close(); con.close()
    sheets.reverse()                                            # oldest -> newest

    # label every point uniquely so two exams never look like one
    name_count = {}
    for s in sheets:
        n = (s[2] or "").strip() or "Exam"
        name_count[n] = name_count.get(n, 0) + 1
    seen = {}

    def make_label(exam, pubat):
        base = (exam or "").strip() or "Exam"
        if name_count.get(base, 0) > 1:
            seen[base] = seen.get(base, 0) + 1
            d = pubat.strftime("%d %b") if pubat else ""
            return f"{base} #{seen[base]}" + (f" ({d})" if d else "")
        return base

    kids = {(o, nn): {"student": name, "points": []} for o, nn, name in mine}
    for sid, owner, exam, stype, rules, data, pubat in sheets:
        label = make_label(exam, pubat)
        ranked = M.compute(data, stype, rules)
        of = sum(1 for r in ranked if r["average"] is not None)
        subs = {x["id"]: x["name"] for x in data["subjects"] if x["name"]}
        for r in ranked:
            key = (owner, M.norm(r["name"]))
            if key not in kids or (sid, key[1]) in restr or r["average"] is None:
                continue
            scores = {}
            for i, n in subs.items():
                v = r["marks"].get(i)
                if v is not None:
                    scores[M.norm(n)] = v
            kids[key]["points"].append({"sheet_id": sid, "label": label, "avg": r["average"],
                                        "position": r["position"], "out_of": of, "subjects": scores})
    out = []
    for c in kids.values():
        c["points"] = c["points"][-5:]
        out.append(c)
    return jsonify({"ok": True, "children": out})

# ── admin phone (for superadmin verification) ───────────────
@mini_bp.route("/api/mini/auth/phone", methods=["POST"])
@need_user("owner")
def mini_set_phone():
    phone = normalize_phone((request.get_json(silent=True) or {}).get("phone"))
    if not phone:
        return jsonify({"ok": False, "error": "Enter a valid phone number, e.g. 0712345678"}), 400
    con = get_db(); cur = con.cursor()
    cur.execute("UPDATE mini_users SET phone=%s WHERE id=%s", (phone, g.mini_user["id"]))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok": True})


# ── admin resets a parent's password (no superadmin needed) ─
@mini_bp.route("/api/mini/parents", methods=["GET"])
@need_user("owner")
def mini_parents():
    q = M.norm(request.args.get("q"))[:60]
    q = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT id,name,phone,parent_user_id IS NOT NULL FROM mini_students "
                "WHERE owner_id=%s AND name_norm LIKE %s ORDER BY name_norm LIMIT 50",
                (g.mini_user["id"], f"%{q}%"))
    rows = [{"id": r[0], "name": r[1], "phone": r[2], "linked": r[3]} for r in cur.fetchall()]
    cur.close(); con.close()
    return jsonify({"ok": True, "parents": rows})


@mini_bp.route("/api/mini/parents/<int:sid>/reset_password", methods=["POST"])
@need_user("owner")
@rate_limit("mini_parent_reset", max_attempts=30, window_minutes=60, by="ip")
def mini_parent_reset(sid):
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"
    temp = "".join(secrets.choice(alphabet) for _ in range(8))
    con = get_db(); cur = con.cursor()
    cur.execute("""UPDATE mini_users u SET password=%s, must_change_password=1, token_version=token_version+1
                   FROM mini_students s
                   WHERE s.id=%s AND s.owner_id=%s AND s.parent_user_id=u.id AND u.role='parent'
                   RETURNING s.name""", (hash_password(temp), sid, g.mini_user["id"]))
    row = cur.fetchone()
    con.commit(); cur.close(); con.close()
    if not row:
        return jsonify({"ok": False, "error": "This parent has not signed up yet, or is not yours"}), 404
    return jsonify({"ok": True, "temp_password": temp, "student": row[0]})