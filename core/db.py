import psycopg2
from config import DATABASE_URL

def get_db():
    con = psycopg2.connect(DATABASE_URL)
    con.autocommit = False
    return con

def to_dict(row, cur):
    if row is None: return None
    return dict(zip([d[0] for d in cur.description], row))

def to_dicts(rows, cur):
    if not rows: return []
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in rows]