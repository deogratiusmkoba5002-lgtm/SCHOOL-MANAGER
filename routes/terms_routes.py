"""
Term lifecycle (open/edit/close) and per-term Tests management.
"""
from flask import Blueprint, request, jsonify, g

from core.db import get_db, to_dicts
from core.auth import require_auth, require_role
from services.scores import get_active_term, get_term_tests, get_test_class_ids

terms_bp = Blueprint("terms", __name__)


@terms_bp.route("/api/tests", methods=["GET"])
@require_auth
def api_get_tests():
    sid = g.school_id; term_id = request.args.get("term_id")
    class_id = request.args.get("class_id")
    class_id = int(class_id) if class_id else None
    if not term_id:
        term = get_active_term(sid)
        if not term: return jsonify([])
        term_id = term["id"]
    else: term_id = int(term_id)
    tests = get_term_tests(sid, term_id, class_id)
    if class_id is None:
        for t in tests:
            t["class_ids"] = [] if t["all_classes"] else get_test_class_ids(t["id"])
    return jsonify(tests)


@terms_bp.route("/api/tests", methods=["POST"])
@require_auth
@require_role("admin")
def api_create_test():
    sid = g.school_id; d = request.json or {}
    term_id = d.get("term_id"); label = (d.get("label") or "").strip()
    class_ids = d.get("class_ids") or []
    if not term_id or not label: return jsonify({"ok":False,"error":"term_id and label required"}),400
    all_classes = 0 if class_ids else 1
    con=get_db(); cur=con.cursor()
    cur.execute("INSERT INTO term_tests(school_id,term_id,label,all_classes) VALUES(%s,%s,%s,%s) RETURNING id",
                (sid,int(term_id),label,all_classes))
    new_id=cur.fetchone()[0]
    for cid in class_ids:
        try: cur.execute("INSERT INTO test_classes(test_id,class_id) VALUES(%s,%s) ON CONFLICT DO NOTHING",(new_id,int(cid)))
        except (TypeError,ValueError): pass
    con.commit(); cur.close(); con.close()
    return jsonify({"ok":True,"id":new_id})


@terms_bp.route("/api/tests/<int:tid>", methods=["DELETE"])
@require_auth
@require_role("admin")
def api_delete_test(tid):
    sid = g.school_id
    con=get_db(); cur=con.cursor()
    cur.execute("DELETE FROM test_scores WHERE school_id=%s AND test_id=%s",(sid,tid))
    cur.execute("DELETE FROM published_assessments WHERE school_id=%s AND assess_key=%s",(sid,f"test:{tid}"))
    cur.execute("DELETE FROM test_classes WHERE test_id=%s",(tid,))
    cur.execute("DELETE FROM term_tests WHERE id=%s AND school_id=%s",(tid,sid))
    con.commit(); cur.close(); con.close()
    return jsonify({"ok":True})


@terms_bp.route("/api/terms", methods=["GET"])
@require_auth
def api_get_terms():
    sid = g.school_id
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM terms WHERE school_id=%s ORDER BY id DESC",(sid,))
    rows = to_dicts(cur.fetchall(),cur); cur.close(); con.close(); return jsonify(rows)


@terms_bp.route("/api/terms/active", methods=["GET"])
@require_auth
def api_active_term():
    sid = g.school_id; t = get_active_term(sid)
    return jsonify({"ok":bool(t),"term":t})


@terms_bp.route("/api/terms", methods=["POST"])
@require_auth
@require_role("admin")
def api_create_term():
    sid = g.school_id; d = request.json
    label=d.get("label","").strip(); ca_count=int(d.get("ca_count",2))
    ca_weight=int(d.get("ca_weight",30)); ex_weight=int(d.get("exam_weight",70))
    if not label: return jsonify({"ok":False,"error":"Term label required"}),400
    if ca_weight+ex_weight!=100: return jsonify({"ok":False,"error":"Weights must sum to 100"}),400
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT id FROM terms WHERE school_id=%s AND status='open'",(sid,))
    if cur.fetchone(): cur.close(); con.close(); return jsonify({"ok":False,"error":"Close current term first"}),409
    cur.execute("INSERT INTO terms(school_id,label,ca_count,ca_weight,exam_weight,status) VALUES(%s,%s,%s,%s,%s,'open')",
                (sid,label,ca_count,ca_weight,ex_weight))
    con.commit(); cur.close(); con.close(); return jsonify({"ok":True})


@terms_bp.route("/api/terms/<int:tid>", methods=["PATCH"])
@require_auth
@require_role("admin")
def api_update_term(tid):
    sid = g.school_id; d = request.json or {}
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT status FROM terms WHERE id=%s AND school_id=%s",(tid,sid))
    row = cur.fetchone()
    if not row:
        cur.close(); con.close(); return jsonify({"ok":False,"error":"Term not found"}),404
    if row[0]=="closed":
        cur.close(); con.close(); return jsonify({"ok":False,"error":"Closed terms are locked and can't be edited"}),400

    fields=[]; vals=[]
    if d.get("label") is not None:
        label=d.get("label","").strip()
        if not label:
            cur.close(); con.close(); return jsonify({"ok":False,"error":"Term label required"}),400
        fields.append("label=%s"); vals.append(label)
    if d.get("ca_count") is not None:
        try: ca_count=int(d.get("ca_count"))
        except (TypeError,ValueError):
            cur.close(); con.close(); return jsonify({"ok":False,"error":"Invalid CA count"}),400
        if ca_count<1:
            cur.close(); con.close(); return jsonify({"ok":False,"error":"Number of CAs must be at least 1"}),400
        fields.append("ca_count=%s"); vals.append(ca_count)
    if d.get("ca_weight") is not None and d.get("exam_weight") is not None:
        try:
            ca_weight=int(d.get("ca_weight")); exam_weight=int(d.get("exam_weight"))
        except (TypeError,ValueError):
            cur.close(); con.close(); return jsonify({"ok":False,"error":"Invalid weights"}),400
        if ca_weight+exam_weight!=100:
            cur.close(); con.close(); return jsonify({"ok":False,"error":"Weights must sum to 100"}),400
        fields.append("ca_weight=%s"); vals.append(ca_weight)
        fields.append("exam_weight=%s"); vals.append(exam_weight)
    if not fields:
        cur.close(); con.close(); return jsonify({"ok":False,"error":"Nothing to update"}),400

    vals += [tid, sid]
    cur.execute(f"UPDATE terms SET {','.join(fields)} WHERE id=%s AND school_id=%s", vals)
    con.commit(); cur.close(); con.close()
    return jsonify({"ok":True})


@terms_bp.route("/api/terms/<int:tid>/close", methods=["POST"])
@require_auth
@require_role("admin")
def api_close_term(tid):
    sid = g.school_id
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT status FROM terms WHERE id=%s AND school_id=%s",(tid,sid))
    row = cur.fetchone()
    if not row: cur.close(); con.close(); return jsonify({"ok":False,"error":"Not found"}),404
    if row[0]=="closed": cur.close(); con.close(); return jsonify({"ok":False,"error":"Already closed"}),400
    cur.execute("UPDATE terms SET status='closed' WHERE id=%s AND school_id=%s",(tid,sid))
    con.commit(); cur.close(); con.close(); return jsonify({"ok":True})