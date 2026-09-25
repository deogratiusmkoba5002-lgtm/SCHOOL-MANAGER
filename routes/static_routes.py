"""
Static page and asset serving: index/setup/register/superadmin/privacy/terms
HTML pages, plus school logo delivery (both the legacy disk path and the
DB-stored base64 path).
"""
import base64, io, os
from flask import Blueprint, send_from_directory, send_file, redirect

from config import BASE_DIR, UPLOAD_FOLDER
from core.school import get_config_val


static_bp = Blueprint("static_pages", __name__)

_STATIC_FILES = ["shared.css", "DRDEMIC-LOGO.png"]


@static_bp.route("/")
def index(): return send_from_directory(BASE_DIR, "index.html")

@static_bp.route("/setup")
def setup_page(): return send_from_directory(BASE_DIR, "setup.html")

@static_bp.route("/register")
def register_page(): return send_from_directory(BASE_DIR, "register.html")

@static_bp.route("/r/<token>")
def referral_redirect(token):
    return redirect(f"/register?ref={token}")

@static_bp.route("/superadmin")
def superadmin_page(): return send_from_directory(BASE_DIR, "superadmin.html")

@static_bp.route("/privacy")
def privacy_page(): return send_from_directory(BASE_DIR, "privacy.html")

@static_bp.route("/terms")
def terms_page(): return send_from_directory(BASE_DIR, "terms.html")

@static_bp.route("/uploads/logos/<filename>")
def serve_logo(filename):
    return send_from_directory(os.path.join(UPLOAD_FOLDER, "logos"), filename)

@static_bp.route("/storage/uploads/logos/<filename>")
def serve_logo_static(filename):
    return send_from_directory(os.path.join(UPLOAD_FOLDER, "logos"), filename)

@static_bp.route("/api/logo/<int:school_id>")
def serve_logo_db(school_id):
    data = get_config_val(school_id, "logo_data", "")
    mime = get_config_val(school_id, "logo_mime", "image/png")
    if not data:
        return ("Not found", 404)
    try:
        raw = base64.b64decode(data)
    except Exception:
        return ("Not found", 404)
    return send_file(io.BytesIO(raw), mimetype=mime)

@static_bp.route("/<path:filename>")
def serve_static(filename):
    if filename in _STATIC_FILES: return send_from_directory(BASE_DIR, filename)
    return ("Not found", 404)

@static_bp.route("/js/<path:filename>")
def serve_js(filename):
    if not filename.endswith(".js"): return ("Not found", 404)
    return send_from_directory(os.path.join(BASE_DIR, "js"), filename)