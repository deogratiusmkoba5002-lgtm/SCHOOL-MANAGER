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