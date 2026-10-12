"""PDF translations. English strings are the keys; anything unknown falls back to English."""
from flask import request

_SW = {
    "STUDENT REPORT CARD": "RIPOTI YA MWANAFUNZI",
    "Name:": "Jina:", "Class:": "Darasa:", "Term:": "Muhula:", "Weights:": "Uzito:",
    "Exam": "Mtihani",
    "Class Position:": "Nafasi ya Darasa:", "Stream Position:": "Nafasi ya Mkondo:", "Grade:": "Daraja:",
    "Subject": "Somo", "Final": "Mwisho", "Pos": "Naf.", "Grd": "Dar.", "Remark": "Maoni", "Sign": "Sahihi",
    "AVERAGE": "WASTANI", "GRADE": "DARAJA", "CLASS POS": "NAFASI DARASA", "STREAM POS": "NAFASI MKONDO",
    "Class Teacher Remark:": "Maoni ya Mwalimu wa Darasa:",
    "Head of School Remark:": "Maoni ya Mkuu wa Shule:",
    "Class Teacher Sign:": "Sahihi ya Mwalimu wa Darasa:",
    "Head Sign:": "Sahihi ya Mkuu:", "Date:": "Tarehe:",
    "Student": "Mwanafunzi", "Total": "Jumla", "Avg": "Wast.", "Grade": "Daraja",
    "Points": "Pointi", "Division": "Divisheni",
    "Generated": "Imetolewa", "students": "wanafunzi",
}

_SUBJECTS_SW = {
    "mathematics": "Hisabati", "english": "Kiingereza", "kiswahili": "Kiswahili", "biology": "Baiolojia",
    "chemistry": "Kemia", "physics": "Fizikia", "geography": "Jiografia", "history": "Historia",
    "civics": "Uraia", "literature": "Fasihi ya Kiingereza", "bible knowledge": "Elimu ya Biblia",
    "book keeping": "Uhasibu", "commerce": "Biashara", "business studies": "Masomo ya Biashara",
    "historia ya tanzania na maadili": "Historia ya Tanzania na Maadili",
}

_SHEET_WORD = {"EXAM": "MTIHANI", "TERMINAL": "MUHULA", "TEST": "JARIBIO"}


def pdf_lang():
    """'sw' only if the request explicitly asks for it; everything else is English."""
    return "sw" if (request.args.get("lang") or "").lower() == "sw" else "en"


def pt(key, lang):
    return _SW.get(key, key) if lang == "sw" else key


def pdf_subject(name, lang):
    if lang == "sw":
        return _SUBJECTS_SW.get((name or "").lower().strip(), (name or "").title())
    return (name or "").title()


def sheet_title(kind, label, lang):
    """kind: 'score' | 'grade'. label: 'CA1', 'EXAM', 'TERMINAL', a test name..."""
    label = (label or "").strip().upper()
    if lang != "sw":
        return f"{label} {'SCORE' if kind == 'score' else 'GRADE'} SHEET".strip()
    label = _SHEET_WORD.get(label, label)
    base = "KARATASI YA ALAMA ZA" if kind == "score" else "KARATASI YA MADARAJA YA"
    return f"{base} {label}".strip()