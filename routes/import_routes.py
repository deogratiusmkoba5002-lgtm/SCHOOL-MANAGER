import io, json, os, secrets, tempfile
from flask import Blueprint, request, jsonify, g, send_file, current_app

from core.db import get_db
from core.auth import require_auth, require_role
from core.security import hash_password_fast
from services.students_import import (
    OPENPYXL_AVAILABLE, openpyxl, _parse_import_file, _extract_fields,
    _build_class_map, _resolve_class_stream, _write_credentials_xlsx,
)

import_bp = Blueprint("student_import", __name__)


@import_bp.route("/api/students/import/template", methods=["GET"])
@require_auth
@require_role("admin")
def api_import_template():
    """Download a pre-filled Excel template."""
    school_id = g.school_id
    if not OPENPYXL_AVAILABLE:
        # Fallback: return CSV template
        csv_content = "name,class_name,stream_name,parent_phone\nJuma Hassan,Form 1,A,0712345678\nFatuma Ally,Form 1,B,0754987654\n"
        return send_file(io.BytesIO(csv_content.encode()), as_attachment=True,
                        download_name="student_import_template.csv", mimetype="text/csv")
    wb = openpyxl.Workbook()
    ws = wb.active; ws.title = "Students"
    # Header row
    headers = ["name","class_name","stream_name","parent_phone"]
    header_labels = ["Student Full Name *","Class Name *","Stream Name (if any)","Parent Phone Number *"]
    from openpyxl.styles import Font, PatternFill, Alignment
    header_fill = PatternFill("solid", fgColor="1A6FA8")
    for col, (h, label) in enumerate(zip(headers, header_labels), 1):
        cell = ws.cell(row=1, column=col, value=label)
        cell.font = Font(bold=True, color="FFFFFF", size=11)
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")
    # Column widths
    ws.column_dimensions["A"].width = 28
    ws.column_dimensions["B"].width = 16
    ws.column_dimensions["C"].width = 18
    ws.column_dimensions["D"].width = 20
    # Pull existing classes for reference
    cmap = _build_class_map(school_id)
    # Example rows
    examples = []
    for ckey, cval in list(cmap.items())[:3]:
        cname = ckey.title()
        if cval["_streams"]:
            for skey in list(cval["_streams"].keys())[:2]:
                examples.append([f"Example Student", cname, skey.title(), "07XXXXXXXXX"])
        else:
            examples.append(["Example Student", cname, "", "07XXXXXXXXX"])
    if not examples:
        examples = [
            ["Juma Hassan","Form 1","A","0712345678"],
            ["Fatuma Ally","Form 1","B","0754987654"],
            ["Emmanuel Peter","Form 2","","0622123456"],
        ]
    from openpyxl.styles import Font as F2
    for ri, row in enumerate(examples, 2):
        for ci, val in enumerate(row, 1):
            cell = ws.cell(row=ri, column=ci, value=val)
            cell.font = F2(color="888888", italic=True)
    # Instructions sheet
    ws2 = wb.create_sheet("Instructions")
    instructions = [
        ("STUDENT IMPORT INSTRUCTIONS",""),
        ("",""),
        ("Column","What to put"),
        ("name","Full name of the student (e.g. Juma Hassan Ally)"),
        ("class_name","Must match exactly a class in your school (e.g. Form 1, Form 2)"),
        ("stream_name","Stream if your class has streams (e.g. A, B, Science, Arts). Leave blank if no streams."),
        ("parent_phone","Parent or guardian phone number (e.g. 0712345678)"),
        ("",""),
        ("IMPORTANT",""),
        ("• Delete the example rows before importing",""),
        ("• class_name must exactly match your school classes",""),
        ("• stream_name must exactly match your stream names",""),
        ("• Do not change the column headers",""),
        ("• Save as .xlsx or .csv before uploading",""),
    ]
    from openpyxl.styles import Font as F3
    for ri, (a,b) in enumerate(instructions, 1):
        ws2.cell(row=ri, column=1, value=a)
        ws2.cell(row=ri, column=2, value=b)
        if ri == 1:
            ws2.cell(row=ri, column=1).font = F3(bold=True, size=13, color="1A6FA8")
        if ri == 3:
            ws2.cell(row=ri, column=1).font = F3(bold=True)
            ws2.cell(row=ri, column=2).font = F3(bold=True)
    ws2.column_dimensions["A"].width = 40
    ws2.column_dimensions["B"].width = 50
    # Classes reference
    if cmap:
        ws3 = wb.create_sheet("Your Classes")
        ws3.cell(row=1,column=1,value="Class Name").font = F3(bold=True)
        ws3.cell(row=1,column=2,value="Streams").font = F3(bold=True)
        for ri,(ckey,cval) in enumerate(cmap.items(),2):
            ws3.cell(row=ri,column=1,value=ckey.title())
            streams = ", ".join(s.title() for s in cval["_streams"].keys())
            ws3.cell(row=ri,column=2,value=streams or "(no streams)")
        ws3.column_dimensions["A"].width = 20
        ws3.column_dimensions["B"].width = 30
    buf = io.BytesIO(); wb.save(buf); buf.seek(0)
    return send_file(buf, as_attachment=True,
                    download_name="student_import_template.xlsx",
                    mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

@import_bp.route("/api/students/import/preview", methods=["POST"])
@require_auth
@require_role("admin")
def api_import_preview():
    school_id = g.school_id
    if "file" not in request.files:
        return jsonify({"ok":False,"error":"No file uploaded"}), 400
    f = request.files["file"]
    try:
        rows = _parse_import_file(f.stream, f.filename)
    except ValueError as e:
        return jsonify({"ok":False,"error":str(e)}), 400
    if not rows:
        return jsonify({"ok":False,"error":"File is empty or has no data rows"}), 400

    cmap = _build_class_map(school_id)
    unmatched_classes = {}
    unmatched_streams = {}
    preview = []
    for i, row in enumerate(rows):
        name, class_name, stream_name, parent_phone = _extract_fields(row)
        cid = sid = err = None
        if class_name:
            cid, sid, err = _resolve_class_stream(class_name, stream_name, cmap)
            if cid is None:
                unmatched_classes[class_name.strip().lower()] = class_name.strip()
            elif stream_name and sid is None and err:
                unmatched_streams[f"{class_name.strip()}::{stream_name.strip()}".lower()] = \
                    {"class_raw": class_name.strip(), "stream_raw": stream_name.strip()}
        if i < 10:
            issues = []
            if not name: issues.append("Missing name")
            if not class_name: issues.append("Missing class")
            elif cid is None: issues.append(f"Class '{class_name}' needs matching")
            elif stream_name and sid is None: issues.append(f"Stream '{stream_name}' needs matching")
            if not parent_phone: issues.append("Missing phone — will still import, no parent login created")
            preview.append({"row":i+2,"name":name,"class_name":class_name,"stream_name":stream_name,
                            "parent_phone":parent_phone,"issues":issues})

    return jsonify({"ok":True,"total_rows":len(rows),"preview":preview,
                    "columns_detected":list(rows[0].keys()) if rows else [],
                    "unmatched_classes": list(unmatched_classes.values()),
                    "unmatched_streams": list(unmatched_streams.values())})


@import_bp.route("/api/students/import/credentials/<token>")
@require_auth
@require_role("admin")
def download_import_credentials(token):
    sid = g.school_id
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT data FROM import_credential_batches WHERE token=%s AND school_id=%s",(token, sid))
    row = cur.fetchone(); cur.close(); con.close()
    if not row:
        return jsonify({"ok": False, "error": "File not found or expired"}), 404
    credentials = row[0]
    fname = os.path.join(tempfile.gettempdir(), f"creds_{token}.xlsx")
    _write_credentials_xlsx(credentials, fname)
    return send_file(fname, as_attachment=True,
                      download_name="parent_login_credentials.xlsx",
                      mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@import_bp.route("/api/students/import", methods=["POST"])
@require_auth
@require_role("admin")
def api_import_students():
    """Full import: parse, validate, bulk insert."""
    school_id = g.school_id
    if "file" not in request.files:
        return jsonify({"ok":False,"error":"No file uploaded"}), 400
    f = request.files["file"]
    import traceback
    try:
        rows = _parse_import_file(f.stream, f.filename)
    except ValueError as e:
        return jsonify({"ok":False,"error":str(e)}),400
    except Exception as e:
        current_app.logger.error("Student import parse failed: %s", traceback.format_exc())
        return jsonify({"ok":False,"error":"Could not parse the uploaded file. Please check the format and try again."}), 500

    if not rows:
        return jsonify({"ok":False,"error":"File is empty"}), 400
    cmap     = _build_class_map(school_id)
    inserted = 0; skipped = []; errors = []; credentials = []; duplicates = 0
    con = get_db(); cur = con.cursor()

    # Snapshot of existing students for duplicate detection (name+class+stream+phone).
    # Also grows as we insert, so repeated rows within the same file are caught too —
    # and re-running an import on the same file becomes a safe no-op instead of creating dupes.
    cur.execute("SELECT LOWER(TRIM(name)), class_id, COALESCE(stream_id,0), phone_number "
                "FROM students WHERE school_id=%s", (school_id,))
    existing_students = set(cur.fetchall())
    cur.execute("SELECT COALESCE(MAX(school_student_no),0) FROM students WHERE school_id=%s", (school_id,))
    next_student_no = cur.fetchone()[0] + 1

    # Track which phone numbers already use each parent username, so we only
    # append "-{student_id}" when two DIFFERENT phone numbers sharing a
    # username would otherwise collide on the same last-4 password.
    cur.execute("""SELECT u.username, s.phone_number FROM users u JOIN students s ON u.student_id=s.id
                   WHERE u.school_id=%s AND u.role='parent'""", (school_id,))
    username_phone_map = {}
    for uname, ph in cur.fetchall():
        username_phone_map.setdefault(uname, []).append(ph or "")

    mapping_raw = request.form.get("mapping", "{}")
    try:
        mapping = json.loads(mapping_raw) if mapping_raw else {}
    except Exception:
        mapping = {}
    mapping.setdefault("classes", {}); mapping.setdefault("streams", {})
    flagged = []  # imported OK but missing a non-essential field — shown as a red dot in the UI

    for i, row in enumerate(rows):
        row_num = i + 2
        name, class_name, stream_name, parent_phone = _extract_fields(row)
        if not name:
            skipped.append({"row":row_num,"reason":"Missing name — can't import a student with no name","data":str(list(row.values())[:4])})
            continue
        if not class_name:
            skipped.append({"row":row_num,"reason":"Missing class","data":name})
            continue
        class_id, stream_id, resolve_err = _resolve_class_stream(class_name, stream_name, cmap, mapping)
        if resolve_err:
            skipped.append({"row":row_num,"reason":resolve_err,"data":name})
            continue
        phone_clean = (parent_phone or "").strip()
        dup_key = (name.strip().lower(), class_id, stream_id or 0, phone_clean)
        if dup_key in existing_students:
            skipped.append({"row":row_num,"reason":"Duplicate — same name, class, stream & phone already exist","data":name})
            duplicates += 1
            continue
        try:
            cur.execute("SAVEPOINT sp_student")
            cur.execute("""INSERT INTO students(school_id,name,class_id,stream_id,phone_number,school_student_no)
                           VALUES(%s,%s,%s,%s,%s,%s) RETURNING id""",
                        (school_id, name, class_id, stream_id, phone_clean or None, next_student_no))
            student_id = cur.fetchone()[0]
            next_student_no += 1
            if not phone_clean:
                reason = "Missing parent phone — no parent login was created"
                flagged.append({"row":row_num,"name":name,"reason":reason})
                cur.execute("UPDATE students SET flag_reason=%s WHERE id=%s",(reason,student_id))
                cur.execute("RELEASE SAVEPOINT sp_student")
                inserted += 1; existing_students.add(dup_key)
                if inserted % 200 == 0: con.commit()
                continue
            username_base = name.strip().lower().replace(" ","_")
            last4 = phone_clean[-4:]
            existing_phones_for_username = username_phone_map.get(username_base, [])
            needs_suffix = any(ph.strip() != phone_clean and ph.strip()[-4:] == last4 for ph in existing_phones_for_username)
            temp_pw = f"{last4}-{student_id}" if needs_suffix else last4
            cur.execute("INSERT INTO users(username,password,role,school_id,must_change_password,student_id) VALUES(%s,%s,'parent',%s,1,%s) ON CONFLICT(username,school_id) DO NOTHING",
                        (username_base,hash_password_fast(temp_pw),school_id,student_id))
            login_created = cur.rowcount > 0
            username_phone_map.setdefault(username_base, []).append(phone_clean)
            cur.execute("RELEASE SAVEPOINT sp_student")
            inserted += 1; existing_students.add(dup_key)
            if login_created:
                credentials.append({"row":row_num,"name":name,"class_name":class_name,"stream_name":stream_name,
                                    "parent_phone":phone_clean,"username":username_base,"password":temp_pw})
            else:
                reason = f"Login username '{username_base}' already taken by another student with the same name"
                flagged.append({"row":row_num,"name":name,"reason":reason})
                cur.execute("UPDATE students SET flag_reason=%s WHERE id=%s",(reason,student_id))
            if inserted % 200 == 0: con.commit()
        except Exception as e:
            cur.execute("ROLLBACK TO SAVEPOINT sp_student")
            errors.append({"row":row_num,"error":str(e),"data":name})
    con.commit(); cur.close(); con.close()

    credentials_file = None
    if credentials:
        token = secrets.token_hex(16)
        con2 = get_db(); cur2 = con2.cursor()
        cur2.execute("INSERT INTO import_credential_batches(school_id,token,data) VALUES(%s,%s,%s)",
                     (school_id, token, json.dumps(credentials)))
        con2.commit(); cur2.close(); con2.close()
        credentials_file = f"/api/students/import/credentials/{token}"

    return jsonify({"ok":True,"inserted":inserted,"skipped":len(skipped),"errors":len(errors),"duplicates":duplicates,
                    "skipped_details":skipped[:20],"error_details":errors[:20],
                    "flagged_details":flagged[:50],
                    "credentials_file":credentials_file,"credentials_count":len(credentials)})
