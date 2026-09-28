"""
Student import (Excel/CSV) logic: file parsing, flexible column detection,
class/stream resolution with admin-supplied mapping, and the credentials
workbook writer. No Flask request/response handling.
"""
import csv, io, re

from core.db import get_db

try:
    import openpyxl
    OPENPYXL_AVAILABLE = True
except ImportError:
    openpyxl = None
    OPENPYXL_AVAILABLE = False


def _parse_import_file(file_obj, filename):
    """Parse uploaded Excel or CSV. Returns list of raw row dicts."""
    ext = filename.rsplit(".",1)[-1].lower() if "." in filename else ""
    rows = []
    if ext in ("xlsx","xls"):
        if not OPENPYXL_AVAILABLE:
            raise ValueError("openpyxl not installed. Add it to requirements.txt")
        wb = openpyxl.load_workbook(file_obj, read_only=True, data_only=True)
        ws = wb.active
        headers = None
        for row in ws.iter_rows(values_only=True):
            # Skip fully empty rows
            if all(v is None for v in row): continue
            if headers is None:
                headers = [str(h).strip().lower() if h else "" for h in row]
                continue
            values = [str(v).strip() if v is not None else "" for v in row]
            row_dict = dict(zip(headers, values))
            # Skip completely empty rows
            if all(v == "" for v in values): continue
            rows.append(row_dict)
        wb.close()
    elif ext == "csv":
        text = file_obj.read().decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            rows.append({k.strip().lower(): str(v).strip() for k,v in row.items()})
    else:
        raise ValueError("Unsupported file type. Use .xlsx or .csv")
    return rows


def _normalize_col(row, *candidates):
    """Try multiple possible column name spellings — strip, lowercase, ignore spaces/underscores."""
    def clean(s): return s.strip().lower().replace(" ","").replace("_","").replace("-","")
    cleaned_row = {clean(k): v for k,v in row.items()}
    for c in candidates:
        key = clean(c)
        if key in cleaned_row and cleaned_row[key]:
            return str(cleaned_row[key]).strip()
    return ""


def _col_by_position(row, index):
    """Fallback: grab column by position index regardless of header name."""
    vals = list(row.values())
    if index < len(vals) and vals[index]:
        return str(vals[index]).strip()
    return ""


def _extract_fields(row):
    """
    Try named columns first. If name or class is still missing,
    fall back to positional: col0=name, col1=class, col2=stream, col3=phone.
    No conditions on format, length, or capitalization.
    """
    name         = _normalize_col(row,"name","student name","full name","jina","student","students","jina la mwanafunzi","mwanafunzi")
    class_name   = _normalize_col(row,"class_name","class","darasa","form","grade","class name","level","form name")
    stream_name  = _normalize_col(row,"stream_name","stream","mkondo","section","division","stream name","class stream")
    parent_phone = _normalize_col(row,"parent_phone","phone","parent phone","phone number","simu","contact","guardian phone","nambari","tel","telephone","mobile","simu ya mzazi","mzazi")
    # If name or class still missing — go positional, user probably has no headers or weird headers
    if not name:        name         = _col_by_position(row, 0)
    if not class_name:  class_name   = _col_by_position(row, 1)
    if not stream_name: stream_name  = _col_by_position(row, 2)
    if not parent_phone:parent_phone = _col_by_position(row, 3)
    return name, class_name, stream_name, parent_phone


def _build_class_map(school_id):
    """Return {class_name_lower: {"_id": class_id, "_streams": {stream_name_lower: (class_id, stream_id)}}}"""
    con = get_db(); cur = con.cursor()
    cur.execute("""SELECT c.id,c.class_name,s.id,s.stream_name
                   FROM classes c LEFT JOIN streams s ON s.class_id=c.id AND s.school_id=c.school_id
                   WHERE c.school_id=%s""", (school_id,))
    rows = cur.fetchall(); cur.close(); con.close()
    cmap = {}
    for (cid, cname, sid, sname) in rows:
        ckey = cname.strip().lower()
        if ckey not in cmap: cmap[ckey] = {"_id": cid, "_streams": {}}
        if sname:
            skey = sname.strip().lower()
            cmap[ckey]["_streams"][skey] = (cid, sid)
    return cmap


_NUM_WORDS = {"one":"1","two":"2","three":"3","four":"4","five":"5","six":"6",
              "seven":"7","eight":"8","nine":"9","ten":"10","i":"1","ii":"2","iii":"3","iv":"4","v":"5"}


def _normalize_class_key(s):
    """Loose match key: lowercase, strip punctuation, collapse spaces, and turn
    spelled-out numbers ('form one') into digits ('form 1') so 'Form 1' and
    'FORM ONE' compare equal without the admin retyping anything."""
    if not s: return ""
    s = re.sub(r'[^a-z0-9\s]', ' ', str(s).strip().lower())
    s = re.sub(r'\s+', ' ', s).strip()
    return ' '.join(_NUM_WORDS.get(w, w) for w in s.split(' '))


def _resolve_class_stream(class_name, stream_name, cmap, mapping=None):
    """Resolve raw text from an import file to (class_id, stream_id, error).
    Tries an admin-supplied mapping first, then a loose normalized match,
    else returns an error string explaining what needs matching."""
    mapping = mapping or {"classes": {}, "streams": {}}
    resolved_class = (mapping["classes"].get(class_name.strip()) or class_name).strip()
    ckey = resolved_class.lower()
    if ckey not in cmap:
        norm = _normalize_class_key(resolved_class)
        ckey = next((k for k in cmap if _normalize_class_key(k) == norm), ckey)
    if ckey not in cmap:
        return None, None, f"Class '{class_name}' not found — match it in the mapping step"
    class_id = cmap[ckey]["_id"]; stream_id = None
    if stream_name:
        streams = cmap[ckey]["_streams"]
        resolved_stream = (mapping["streams"].get(f"{class_name.strip()}::{stream_name.strip()}") or stream_name).strip()
        skey = resolved_stream.lower()
        if skey not in streams:
            norm = _normalize_class_key(resolved_stream)
            skey = next((k for k in streams if _normalize_class_key(k) == norm), skey)
        if skey not in streams:
            return class_id, None, f"Stream '{stream_name}' not found in '{resolved_class}' — match it in the mapping step"
        class_id, stream_id = streams[skey]
    return class_id, stream_id, None


def _write_credentials_xlsx(rows, path):
    """Write a workbook of parent username/one-time-password pairs for a completed import."""
    from openpyxl.styles import Font, PatternFill

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Parent Login Credentials"

    headers = ["Row", "Student Name", "Class", "Stream", "Parent Phone", "Username", "Temporary Password"]
    ws.append(headers)
    header_fill = PatternFill(start_color="1A6FA8", end_color="1A6FA8", fill_type="solid")
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = header_fill

    for r in rows:
        ws.append([
            r["row"], r["name"], r["class_name"], r["stream_name"] or "-",
            r["parent_phone"], r["username"], r["password"],
        ])

    widths = [6, 26, 14, 12, 16, 22, 20]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = w

    note_row = ws.max_row + 2
    ws.cell(row=note_row, column=1,
            value="Note: this is a one-time password. Parents must change it after first login.").font = \
        Font(italic=True, color="888888")

    wb.save(path)

# ── FLEXIBLE COLUMN MAPPING ───────────────────────────────────
import json as _json

def _hclean(s):
    """Loose header key: lowercase, drop '(...)' notes and non-alphanumerics."""
    return re.sub(r"\(.*?\)|[^a-z0-9]", "", str(s).lower())

_FULL_NAME_KEYS = {"name","fullname","studentname","studentfullname","student","students",
                   "jina","jinakamili","jinalamwanafunzi","mwanafunzi"}
_FIRST_KEYS  = {"firstname","first","givenname","forename","jinalakwanza"}
_MIDDLE_KEYS = {"middlename","middle","secondname","second","othername","othernames","jinalapili"}
_LAST_KEYS   = {"surname","lastname","last","familyname","jinalaukoo","jinalamwisho"}
_FIELD_KEYS = {
    "class":  {"class","classname","form","formname","grade","level","darasa"},
    "stream": {"stream","streamname","division","section","mkondo","classstream"},
    "phone":  {"phone","parentphone","phonenumber","parentphonenumber","guardianphone",
               "guardianphonenumber","contact","parentcontact","simu","simuyamzazi",
               "tel","telephone","mobile","nambari","mzazi"},
}


def _parse_with_headers(file_obj, filename):
    """Like _parse_import_file, but returns (headers, rows) where rows are dicts
    keyed by the ORIGINAL header text. Blank/duplicate headers are made unique."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in ("xlsx", "xls"):
        if not OPENPYXL_AVAILABLE:
            raise ValueError("openpyxl not installed. Add it to requirements.txt")
        wb = openpyxl.load_workbook(file_obj, read_only=True, data_only=True)
        raw = [list(r) for r in wb.active.iter_rows(values_only=True)]
        wb.close()
    elif ext == "csv":
        raw = list(csv.reader(io.StringIO(file_obj.read().decode("utf-8-sig"))))
    else:
        raise ValueError("Unsupported file type. Use .xlsx or .csv")

    def cell(v):
        if v is None: return ""
        if isinstance(v, float) and v.is_integer(): v = int(v)
        return str(v).strip()

    raw = [[cell(v) for v in r] for r in raw]
    raw = [r for r in raw if any(r)]
    if not raw: return [], []
    headers, seen = [], set()
    for i, h in enumerate(raw[0]):
        h = h or f"Column {i+1}"
        base, n = h, 2
        while h in seen:
            h = f"{base} ({n})"; n += 1
        seen.add(h); headers.append(h)
    rows = []
    for r in raw[1:]:
        r = r + [""] * (len(headers) - len(r))
        rows.append(dict(zip(headers, r)))
    return headers, rows


def _guess_column_map(headers):
    """Best-guess mapping from common header spellings. Admin can override in the wizard."""
    cleaned = [(h, _hclean(h)) for h in headers]
    def find(keys): return next((h for h, c in cleaned if c in keys), None)
    full = find(_FULL_NAME_KEYS)
    if full:
        name = [full]
    else:  # First / Second / Surname style — keep the sheet's own column order
        parts = _FIRST_KEYS | _MIDDLE_KEYS | _LAST_KEYS
        name = [h for h, c in cleaned if c in parts]
    return {"name": name, "class": find(_FIELD_KEYS["class"]),
            "stream": find(_FIELD_KEYS["stream"]), "phone": find(_FIELD_KEYS["phone"])}


def parse_column_map(raw):
    """Form field (JSON string) -> dict, or None if not supplied."""
    if not raw: return None
    try: cm = _json.loads(raw)
    except Exception: raise ValueError("Invalid column mapping")
    if not isinstance(cm, dict): raise ValueError("Invalid column mapping")
    return cm


def _validated_column_map(cm, headers):
    hs = set(headers)
    name = [h for h in (cm.get("name") or []) if isinstance(h, str) and h in hs]
    if not name: raise ValueError("Select at least one column for Student Name")
    def one(k):
        v = cm.get(k)
        return v if isinstance(v, str) and v in hs else None
    if not one("class"): raise ValueError("Select the column that contains the Class")
    return {"name": name, "class": one("class"), "stream": one("stream"), "phone": one("phone")}


def _extract_mapped(row, cm):
    # Join name columns in the chosen order, collapse extra spaces -> same `name` format as before
    name = " ".join(" ".join(row.get(h, "") for h in cm["name"]).split())
    g = lambda k: (row.get(cm[k], "") or "").strip() if cm[k] else ""
    return name, g("class"), g("stream"), g("phone")


def _extract_all(file_obj, filename, column_map=None):
    """Returns a list of (name, class_name, stream_name, parent_phone) tuples.
    With no column_map the legacy header/positional detection is used."""
    if not column_map:
        return [_extract_fields(r) for r in _parse_import_file(file_obj, filename)]
    headers, rows = _parse_with_headers(file_obj, filename)
    cm = _validated_column_map(column_map, headers)
    return [_extract_mapped(r, cm) for r in rows]