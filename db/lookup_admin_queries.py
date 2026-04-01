"""
Generic CRUD helpers for METER_SPECS lookup tables.
Used exclusively by ui/manage_lookups.py (ADMIN-only).

All table and column names are bracket-quoted to handle spaces
(e.g. [TESTED BY], [TEST STANDARDS], [FW Ver]).
"""

import pyodbc
from db.connection import get_meter_specs_connection


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _rows_to_dicts(cursor, rows: list) -> list[dict]:
    cols = [c[0] for c in cursor.description]
    return [{c: v for c, v in zip(cols, row)} for row in rows]


def _conn():
    return get_meter_specs_connection()


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def fetch_lookup_rows(table_name: str) -> list[dict]:
    """
    Return all rows from a METER_SPECS lookup table, ordered by ID.
    Returns [] on any error (permission, missing table, etc.).
    """
    sql = f"SELECT * FROM [{table_name}] ORDER BY [ID]"
    conn = _conn()
    if conn is None:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute(sql)
        return _rows_to_dicts(cursor, cursor.fetchall())
    except pyodbc.Error as e:
        print(f"fetch_lookup_rows({table_name}) error: {e}")
        return []
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

def add_lookup_row(table_name: str, fields: dict) -> bool:
    """
    Insert a new row into a lookup table.
    'fields' must NOT include ID (identity column).
    Returns True on success.
    """
    if not fields:
        return False
    cols   = ", ".join(f"[{c}]" for c in fields)
    params = ", ".join("?" for _ in fields)
    sql    = f"INSERT INTO [{table_name}] ({cols}) VALUES ({params})"
    conn = _conn()
    if conn is None:
        return False
    try:
        conn.cursor().execute(sql, list(fields.values()))
        conn.commit()
        return True
    except pyodbc.Error as e:
        print(f"add_lookup_row({table_name}) error: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

def update_lookup_row(table_name: str, row_id: int, fields: dict) -> bool:
    """
    Update columns on an existing lookup row by its ID.
    'fields' must NOT include ID.
    """
    if not fields:
        return False
    set_clause = ", ".join(f"[{c}] = ?" for c in fields)
    sql    = f"UPDATE [{table_name}] SET {set_clause} WHERE [ID] = ?"
    params = list(fields.values()) + [row_id]
    conn = _conn()
    if conn is None:
        return False
    try:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        conn.commit()
        return cursor.rowcount > 0
    except pyodbc.Error as e:
        print(f"update_lookup_row({table_name}, id={row_id}) error: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Toggle ACTIVE flag
# ---------------------------------------------------------------------------

def set_lookup_active(table_name: str, row_id: int, active: bool) -> bool:
    """
    Flip the ACTIVE bit on a lookup row.
    Soft-delete pattern — mirrors VB: never hard-delete, just deactivate.
    """
    sql = f"UPDATE [{table_name}] SET [ACTIVE] = ? WHERE [ID] = ?"
    conn = _conn()
    if conn is None:
        return False
    try:
        cursor = conn.cursor()
        cursor.execute(sql, (1 if active else 0, row_id))
        conn.commit()
        return cursor.rowcount > 0
    except pyodbc.Error as e:
        print(f"set_lookup_active({table_name}, id={row_id}) error: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()
