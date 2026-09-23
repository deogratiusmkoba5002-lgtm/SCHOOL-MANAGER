"""
Student business logic: parent credential generation shared by add/edit/
import/reset flows. No Flask request/response handling.
"""
from core.db import get_db


def gen_parent_creds(school_id, student_name, phone_number, student_id):
    """Normally the password is just the last 4 digits of the parent's phone.
    Only append "-{student_id}" when another student already shares this
    exact username with a DIFFERENT phone number whose last 4 digits happen
    to collide with this one."""
    username = student_name.strip().lower().replace(" ", "_")
    last4 = phone_number.strip()[-4:]
    con = get_db(); cur = con.cursor()
    cur.execute("""SELECT s.phone_number FROM users u JOIN students s ON u.student_id = s.id
                   WHERE u.username=%s AND u.school_id=%s AND u.role='parent'""",
                (username, school_id))
    existing_phones = [r[0] or "" for r in cur.fetchall()]
    cur.close(); con.close()
    needs_suffix = any(
        ph.strip() != phone_number.strip() and ph.strip()[-4:] == last4
        for ph in existing_phones
    )
    temp_pw = f"{last4}-{student_id}" if needs_suffix else last4
    return username, temp_pw