"""
Database query functions for the Failure Report management system.

All queries target the 'Failure Report' table. Column names with spaces
must use SQL Server bracket notation: [Column Name].
"""

import pyodbc
from db.connection import get_connection


# ---------------------------------------------------------------------------
# Column helpers
# ---------------------------------------------------------------------------

# Columns used for the dashboard list view (lightweight — avoids pulling all
# 70 columns for every row when only a summary is needed).
SUMMARY_COLUMNS = [
    "[Index]",
    "[New ID]",
    "[Original ID]",
    "[Project]",
    "[Project_Number]",
    "[Meter_Type]",
    "[Meter_Serial_Number]",
    "[Test_Type]",
    "[Date Failed]",
    "[Tested By]",
    "[Assigned To]",
    "[Pass]",
    "[Anomaly]",
    "[FR_Approved]",
    "[Date Closed]",
]


def _row_to_dict(cursor, row):
    """Convert a pyodbc Row to a plain dict keyed by column name."""
    return {col[0]: val for col, val in zip(cursor.description, row)}


def _rows_to_dicts(cursor, rows):
    return [_row_to_dict(cursor, row) for row in rows]


# ---------------------------------------------------------------------------
# Fetch all reports (summary columns only, ordered by [New ID])
# ---------------------------------------------------------------------------

def fetch_all_reports():
    """
    Return a list of dicts for every report, using summary columns only.
    Ordered by [New ID] ascending (mirrors the GET_FR_DATA stored procedure).
    """
    cols = ", ".join(SUMMARY_COLUMNS)
    sql = f"SELECT {cols} FROM [Failure Report] ORDER BY [New ID]"

    conn = get_connection()
    if conn is None:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute(sql)
        return _rows_to_dicts(cursor, cursor.fetchall())
    except pyodbc.Error as e:
        print(f"fetch_all_reports error: {e}")
        return []
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Fetch a single report by Index (all 70 columns)
# ---------------------------------------------------------------------------

def fetch_report_by_id(index: int):
    """
    Return a single report dict (all columns) for the given [Index] value,
    or None if not found.
    """
    sql = "SELECT * FROM [Failure Report] WHERE [Index] = ?"

    conn = get_connection()
    if conn is None:
        return None
    try:
        cursor = conn.cursor()
        cursor.execute(sql, (index,))
        row = cursor.fetchone()
        return _row_to_dict(cursor, row) if row else None
    except pyodbc.Error as e:
        print(f"fetch_report_by_id error: {e}")
        return None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Fetch a single report by New ID (all 70 columns)
# ---------------------------------------------------------------------------

def fetch_report_by_new_id(new_id: int):
    """
    Return a single report dict (all columns) for the given [New ID] value,
    or None if not found.
    """
    sql = "SELECT * FROM [Failure Report] WHERE [New ID] = ?"

    conn = get_connection()
    if conn is None:
        return None
    try:
        cursor = conn.cursor()
        cursor.execute(sql, (new_id,))
        row = cursor.fetchone()
        return _row_to_dict(cursor, row) if row else None
    except pyodbc.Error as e:
        print(f"fetch_report_by_new_id error: {e}")
        return None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Search / filter reports
# ---------------------------------------------------------------------------

def search_reports(
    search_text: str = "",
    project: str = "",
    test_type: str = "",
    assigned_to: str = "",
    approved: bool | None = None,
    date_failed_from=None,
    date_failed_to=None,
):
    """
    Return summary-column rows matching the supplied filters.

    Parameters
    ----------
    search_text : str
        Free-text search applied across [New ID], [Meter_Serial_Number],
        [Failure Description], and [Corrective Action].
    project : str
        Exact match on [Project].
    test_type : str
        Exact match on [Test_Type].
    assigned_to : str
        Exact match on [Assigned To].
    approved : bool | None
        Filter on [FR_Approved]. None means no filter.
    date_failed_from : date | str | None
        Lower bound (inclusive) for [Date Failed].
    date_failed_to : date | str | None
        Upper bound (inclusive) for [Date Failed].
    """
    cols = ", ".join(SUMMARY_COLUMNS)
    conditions = []
    params = []

    if search_text:
        term = f"%{search_text}%"
        conditions.append(
            "("
            "CAST([New ID] AS NVARCHAR) LIKE ? OR "
            "[Meter_Serial_Number] LIKE ? OR "
            "[Failure Description] LIKE ? OR "
            "[Corrective Action] LIKE ?"
            ")"
        )
        params.extend([term, term, term, term])

    if project:
        conditions.append("[Project] = ?")
        params.append(project)

    if test_type:
        conditions.append("[Test_Type] = ?")
        params.append(test_type)

    if assigned_to:
        conditions.append("[Assigned To] = ?")
        params.append(assigned_to)

    # [FR_Approved] is nvarchar(255). Distinct values found across 2003 records:
    #   'Checked'   -> 1917 rows  (approved)
    #   'Unchecked' ->   84 rows  (not approved)
    #   NULL        ->    2 rows  (no value set)
    if approved is not None:
        conditions.append("[FR_Approved] = ?")
        params.append("Checked" if approved else "Unchecked")

    if date_failed_from is not None:
        conditions.append("[Date Failed] >= ?")
        params.append(date_failed_from)

    if date_failed_to is not None:
        conditions.append("[Date Failed] <= ?")
        params.append(date_failed_to)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    sql = f"SELECT {cols} FROM [Failure Report] {where} ORDER BY [New ID]"

    conn = get_connection()
    if conn is None:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        return _rows_to_dicts(cursor, cursor.fetchall())
    except pyodbc.Error as e:
        print(f"search_reports error: {e}")
        return []
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Create a new report
# ---------------------------------------------------------------------------

def create_report(fields: dict):
    """
    Insert a new row into [Failure Report].

    Parameters
    ----------
    fields : dict
        Keys are column names (without brackets); values are the data to
        insert.  [Index] is an identity column and must NOT be included.

    Returns
    -------
    int | None
        The [Index] of the newly created row, or None on failure.
    """
    if not fields:
        raise ValueError("fields dict must not be empty")

    bracketed_cols = ", ".join(f"[{col}]" for col in fields)
    placeholders = ", ".join("?" for _ in fields)
    sql = (
        f"INSERT INTO [Failure Report] ({bracketed_cols}) "
        f"VALUES ({placeholders}); "
        f"SELECT SCOPE_IDENTITY();"
    )

    conn = get_connection()
    if conn is None:
        return None
    try:
        cursor = conn.cursor()
        cursor.execute(sql, list(fields.values()))
        row = cursor.fetchone()
        new_index = int(row[0]) if row and row[0] is not None else None
        conn.commit()
        return new_index
    except pyodbc.Error as e:
        print(f"create_report error: {e}")
        conn.rollback()
        return None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Update an existing report
# ---------------------------------------------------------------------------

def update_report(index: int, fields: dict):
    """
    Update columns on an existing [Failure Report] row.

    Parameters
    ----------
    index : int
        The [Index] of the report to update.
    fields : dict
        Keys are column names (without brackets); values are the new data.
        [Index] is the PK and must NOT be included in fields.

    Returns
    -------
    bool
        True if the update succeeded, False otherwise.
    """
    if not fields:
        raise ValueError("fields dict must not be empty")

    set_clause = ", ".join(f"[{col}] = ?" for col in fields)
    sql = f"UPDATE [Failure Report] SET {set_clause} WHERE [Index] = ?"
    params = list(fields.values()) + [index]

    conn = get_connection()
    if conn is None:
        return False
    try:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        conn.commit()
        return cursor.rowcount > 0
    except pyodbc.Error as e:
        print(f"update_report error: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Next available [New ID]
# ---------------------------------------------------------------------------

def get_next_new_id() -> int:
    """
    Return MAX([New ID]) + 1 from [Failure Report].

    [New ID] is a required non-nullable int that is NOT an identity column,
    so every INSERT must supply it explicitly.  This function derives the
    next safe value by incrementing the current maximum.

    Raises RuntimeError if the table is empty or the connection fails,
    since inserting without a valid [New ID] would violate the NOT NULL
    constraint.
    """
    sql = "SELECT MAX([New ID]) FROM [Failure Report]"

    conn = get_connection()
    if conn is None:
        raise RuntimeError("get_next_new_id: could not connect to database.")
    try:
        cursor = conn.cursor()
        cursor.execute(sql)
        row = cursor.fetchone()
        if row is None or row[0] is None:
            raise RuntimeError("get_next_new_id: MAX([New ID]) returned NULL — table may be empty.")
        return int(row[0]) + 1
    except pyodbc.Error as e:
        raise RuntimeError(f"get_next_new_id error: {e}") from e
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Fetch attachment metadata for a report (by New ID)
# ---------------------------------------------------------------------------

def fetch_attachments_by_new_id(new_id: int) -> list[dict]:
    """
    Return attachment metadata rows from the ATTACHMENT table for the given
    [New ID].  The binary ATTACHMENT column is intentionally excluded — it
    can be large and is not suitable for display in a form.

    The ATTACHMENT table schema:
        ID          int         (PK)
        FR_ID       int         (FK → [Failure Report].[New ID])
        ATTACHMENT  varbinary   (file content — excluded here)
    """
    sql = "SELECT [ID], [FR_ID] FROM [ATTACHMENT] WHERE [FR_ID] = ?"

    conn = get_connection()
    if conn is None:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute(sql, (new_id,))
        return _rows_to_dicts(cursor, cursor.fetchall())
    except pyodbc.Error as e:
        print(f"fetch_attachments_by_new_id error: {e}")
        return []
    finally:
        conn.close()
