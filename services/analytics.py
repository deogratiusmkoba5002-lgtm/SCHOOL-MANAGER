"""
Analytics business logic: per-assessment time series (overall and per
subject), the shared insight cards (outstanding / support / improved /
declining / at-risk), and best/weakest subject. No Flask request/response
handling.
"""
from services.grading import get_grade_rules
from services.scores import (
    get_students_in_scope, get_all_students_in_school, _get_all_terms_ordered,
    get_term_scores_bulk, get_term_tests, _score_for_assess, _assign_positions,
)


def _assessments_for_term(school_id, term, class_id=None):
    assessments = [f"CA{i}" for i in range(1, term["ca_count"] + 1)] + ["exam"]
    for t in get_term_tests(school_id, term["id"], class_id):
        assessments.append(f"test:{t['id']}")
    return assessments


def _compute_overall_series(school_id, class_id, stream_id, subjects):
    students = get_students_in_scope(school_id, class_id, stream_id) if class_id \
        else get_all_students_in_school(school_id)
    student_ids = [s["id"] for s in students]
    name_map = {s["id"]: s["name"] for s in students}
    if not student_ids: return [], name_map
    points = []
    for term in _get_all_terms_ordered(school_id):
        scores_bulk = get_term_scores_bulk(school_id, term["id"], student_ids)
        test_label_map = {t["id"]: t["label"] for t in get_term_tests(school_id, term["id"], class_id)}
        for assess in _assessments_for_term(school_id, term, class_id):
            values = {}
            for sid in student_ids:
                entry_map = scores_bulk.get(sid, {})
                vals = []
                for subj in subjects:
                    v = _score_for_assess(entry_map.get(subj), assess)
                    if v is not None: vals.append(v)
                values[sid] = round(sum(vals) / len(vals), 2) if vals else None
            present = {sid: v for sid, v in values.items() if v is not None}
            if not present: continue
            ranked = [{"id": sid, "score": v} for sid, v in present.items()]
            _assign_positions(ranked, "score")
            ranks = {r["id"]: r["position"] for r in ranked}
            avg = round(sum(present.values()) / len(present), 2)
            if assess == "exam": label = f"{term['label']} Exam"
            elif assess.startswith("test:"):
                label = f"{term['label']} {test_label_map.get(int(assess.split(':')[1]),'Test')}"
            else: label = f"{term['label']} {assess}"
            points.append({"term_id": term["id"], "assess": assess, "label": label,
                           "values": values, "avg": avg, "ranks": ranks, "student_count": len(present)})
    return points, name_map


def _compute_subject_series(school_id, class_id, stream_id, subject):
    students = get_students_in_scope(school_id, class_id, stream_id)
    student_ids = [s["id"] for s in students]
    name_map = {s["id"]: s["name"] for s in students}
    if not student_ids: return [], name_map
    points = []
    for term in _get_all_terms_ordered(school_id):
        scores_bulk = get_term_scores_bulk(school_id, term["id"], student_ids)
        test_label_map = {t["id"]: t["label"] for t in get_term_tests(school_id, term["id"], class_id)}
        for assess in _assessments_for_term(school_id, term, class_id):
            values = {}
            for sid in student_ids:
                v = _score_for_assess(scores_bulk.get(sid, {}).get(subject), assess)
                if v is not None: values[sid] = v
            if not values: continue
            ranked = [{"id": sid, "score": v} for sid, v in values.items()]
            _assign_positions(ranked, "score")
            ranks = {r["id"]: r["position"] for r in ranked}
            avg = round(sum(values.values()) / len(values), 2)
            if assess == "exam": label = f"{term['label']} Exam"
            elif assess.startswith("test:"):
                label = f"{term['label']} {test_label_map.get(int(assess.split(':')[1]),'Test')}"
            else: label = f"{term['label']} {assess}"
            points.append({"term_id": term["id"], "assess": assess, "label": label,
                           "values": values, "avg": avg, "ranks": ranks, "student_count": len(values)})
    return points, name_map


def _build_common_cards(points, name_map, school_id):
    """Shared card logic for both overall (admin/class-teacher) and
    subject-level (subject teacher) analytics. A student is only flagged as
    improved/declining/outstanding/at-risk when BOTH the mark and the
    position move together — this is the whole point of the spec: marks
    alone or position alone can mislead when exam difficulty varies."""
    if not points:
        return {"graph": [], "current_label": None, "average": None,
                "outstanding": [], "needs_support": [], "improved": [],
                "declining": [], "at_risk": []}

    graph = [{"label": p["label"], "value": p["avg"]} for p in points[-5:]]
    latest = points[-1]
    prev = points[-2] if len(points) >= 2 else None
    latest_vals, latest_ranks, latest_avg = latest["values"], latest["ranks"], latest["avg"]
    total = len(latest_ranks)

    outstanding, needs_support = [], []
    for sid, val in latest_vals.items():
        if val is None: continue
        pos = latest_ranks.get(sid)
        if pos is None: continue
        name = name_map.get(sid, "?")
        if pos <= 3 and val >= latest_avg + 5:
            outstanding.append({"id": sid, "name": name, "value": val, "position": pos})
        if total >= 3 and pos > total - 3 and val <= latest_avg - 5:
            needs_support.append({"id": sid, "name": name, "value": val, "position": pos})
    outstanding.sort(key=lambda r: r["position"])
    needs_support.sort(key=lambda r: -r["position"])

    improved, declining = [], []
    if prev:
        prev_vals, prev_ranks = prev["values"], prev["ranks"]
        for sid in set(latest_vals) & set(prev_vals):
            lv, pv = latest_vals[sid], prev_vals[sid]
            lp, pp = latest_ranks.get(sid), prev_ranks.get(sid)
            if None in (lv, pv, lp, pp): continue
            name = name_map.get(sid, "?")
            if lv > pv and lp < pp:
                improved.append({"id": sid, "name": name, "prev_value": pv, "current_value": lv,
                                 "prev_position": pp, "current_position": lp})
            elif lv < pv and lp > pp:
                declining.append({"id": sid, "name": name, "prev_value": pv, "current_value": lv,
                                  "prev_position": pp, "current_position": lp})

    at_risk = []
    grade_rules = get_grade_rules(school_id)
    lowest_rule = min(grade_rules, key=lambda r: r["min_score"]) if grade_rules else None
    if prev and lowest_rule:
        prev_vals = prev["values"]
        for sid in set(latest_vals) & set(prev_vals):
            lv, pv = latest_vals[sid], prev_vals[sid]
            if lv is None or pv is None: continue
            if lowest_rule["min_score"] <= lv <= lowest_rule["max_score"] and \
               lowest_rule["min_score"] <= pv <= lowest_rule["max_score"]:
                at_risk.append({"id": sid, "name": name_map.get(sid, "?"), "value": lv,
                                "reason": "Lowest grade in two consecutive examinations."})

    return {"graph": graph, "current_label": latest["label"], "average": round(latest_avg, 2),
            "outstanding": outstanding, "needs_support": needs_support,
            "improved": improved, "declining": declining, "at_risk": at_risk}


def _best_weakest_subject(school_id, class_id, stream_id, subjects, term_id, assess):
    students = get_students_in_scope(school_id, class_id, stream_id) if class_id \
        else get_all_students_in_school(school_id)
    ids = [s["id"] for s in students]
    if not ids: return None, None
    scores_bulk = get_term_scores_bulk(school_id, term_id, ids)
    subj_avgs = {}
    for subj in subjects:
        vals = []
        for sid in ids:
            entry = scores_bulk.get(sid, {}).get(subj)
            if not entry: continue
            v = entry["exam"] if assess == "exam" else entry["ca"].get(assess)
            if v is not None: vals.append(v)
        if vals: subj_avgs[subj] = round(sum(vals) / len(vals), 2)
    if not subj_avgs: return None, None
    best = max(subj_avgs.items(), key=lambda kv: kv[1])
    weak = min(subj_avgs.items(), key=lambda kv: kv[1])
    return {"subject": best[0], "average": best[1]}, {"subject": weak[0], "average": weak[1]}