"""
Student business logic: parent credential generation shared by add/edit/
import/reset flows. No Flask request/response handling.
"""
import re


def parent_temp_password(phone_number):
    """First-login password = the parent's full phone number, digits only
    (so '0712 345 678' and '0712345678' both work)."""
    return re.sub(r"\D", "", phone_number or "")


def gen_parent_creds(school_id, student_name, phone_number, student_id):
    username = student_name.strip().lower().replace(" ", "_")
    return username, parent_temp_password(phone_number)