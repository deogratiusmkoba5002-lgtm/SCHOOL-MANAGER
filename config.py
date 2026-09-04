"""
Central configuration: env vars, paths, and static fallback data.
"""
import os

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
DATABASE_URL  = os.environ.get("DATABASE_URL", "")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "storage", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
IMPORT_EXPORT_FOLDER = os.path.join(BASE_DIR, "storage", "import_exports")
os.makedirs(IMPORT_EXPORT_FOLDER, exist_ok=True)

ALLOWED_LOGO_EXT = {"png","jpg","jpeg","gif","webp","svg"}

def _mime_for_ext(ext):
    return {"png":"image/png","jpg":"image/jpeg","jpeg":"image/jpeg",
            "gif":"image/gif","webp":"image/webp","svg":"image/svg+xml"}.get(ext, "application/octet-stream")

_FALLBACK_SUBJECTS = [
    "mathematics","physics","chemistry","biology","geography","history","civics",
    "english","literature","kiswahili","bible knowledge","book keeping","commerce",
    "business studies","historia ya tanzania na maadili",
]
_FALLBACK_ABBR = {
    "historia ya tanzania na maadili":"HTM","mathematics":"MATH","physics":"PHY",
    "chemistry":"CHEM","biology":"BIO","geography":"GEO","history":"HIST",
    "civics":"CIV","english":"ENG","literature":"LIT","kiswahili":"KIS",
    "bible knowledge":"BK","book keeping":"BKP","commerce":"COM","business studies":"BS",
}
_FALLBACK_GRADES = [
    {"min_score":80,"max_score":100,"grade":"A","points":1},{"min_score":70,"max_score":79,"grade":"B","points":2},
    {"min_score":60,"max_score":69,"grade":"C","points":3},{"min_score":50,"max_score":59,"grade":"D","points":4},
    {"min_score":0,"max_score":49,"grade":"F","points":5},
]

SUBSCRIPTION_PLANS = {
    "free":     {"amount": 0,      "days": 36500,
                 "label": "Free — basic features, forever",
                 "features": ["Marks entry", "On-screen viewing"]},
    "standard": {"amount": 300000, "days": 182,
                 "label": "Standard — 300,000 TZS / 6 months",
                 "features": ["Everything in Free", "Analytics", "PDF downloads", "Announcements", "Results publishing"]},
    "premium":  {"amount": 500000, "days": 365,
                 "label": "Premium — 500,000 TZS / year",
                 "features": ["Everything in Standard", "Priority support"]},
}

SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY env var is required. Generate one with "
                        "`python -c \"import secrets;print(secrets.token_hex(32))\"` and set it.")

SESSION_MAX_AGE    = 12 * 3600  # 12h
SA_SESSION_MAX_AGE = 12 * 3600