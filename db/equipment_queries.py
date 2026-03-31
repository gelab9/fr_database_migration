"""
Test Equipment queries against METER_SPECS.TEST_EQUIPMENT.

Mirrors frmSelectTestEquipment.vb data access layer.

Table: TEST_EQUIPMENT
  [INDEX]              INT          Primary key (identity)
  [ID]                 INT          Equipment ID — same across all revisions
  [MANUFACTURER]       nvarchar(255)
  [MODEL]              nvarchar(255)
  [DESCRIPTION]        nvarchar(MAX)
  [SERIAL NUMBER]      nvarchar(255)
  [ALT SERIAL NUMBER]  nvarchar(255)
  [LAST CAL]           nvarchar(255)
  [NEXT CAL]           nvarchar(255)
  [LAB ID]             nvarchar(255)
  [USER_ID]            INT
  [LOCATION]           nvarchar(255)
  [NOTE]               nvarchar(MAX)
  [REV]                nvarchar(255)
  [TEST GROUP MEMBERS] nvarchar(255)  semicolon-delimited equipment IDs
  [TYPE]               nvarchar(255)
  [TEST GROUP]         BIT
  [ACTIVE REV]         BIT           only ONE revision per ID is True
  [OBSOLETE]           BIT
  [CAL REQ]            BIT

Related table: TEST_EQUIPMENT_TYPE  — columns: ID, TEST_TYPE, ACTIVE
"""

import pyodbc
from db.connection import get_meter_specs_connection


def _rows_to_dicts(cursor, rows: list) -> list[dict]:
    cols = [c[0] for c in cursor.description]
    return [{c: v for c, v in zip(cols, row)} for row in rows]


def _run(sql: str, params: tuple = ()) -> list[dict]:
    """Execute against METER_SPECS and return list of dicts, or [] on error."""
    conn = get_meter_specs_connection()
    if conn is None:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        return _rows_to_dicts(cursor, cursor.fetchall())
    except pyodbc.Error as e:
        print(f"equipment_queries error [{sql[:60]}]: {e}")
        return []
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Equipment type lookup
# ---------------------------------------------------------------------------

def fetch_equipment_types() -> list[str]:
    """Return active TEST_EQUIPMENT_TYPE values for the Type filter combo."""
    rows = _run(
        "SELECT [TEST_TYPE] FROM [TEST_EQUIPMENT_TYPE] "
        "WHERE [ACTIVE] = 1 ORDER BY [TEST_TYPE]"
    )
    return [str(r["TEST_TYPE"]).strip() for r in rows if r.get("TEST_TYPE")]


# ---------------------------------------------------------------------------
# Fetch equipment rows
# ---------------------------------------------------------------------------

def fetch_all_equipment(
    active_rev_only: bool = True,
    include_obsolete: bool = False,
    type_filter: str = "",
) -> list[dict]:
    """
    Return TEST_EQUIPMENT rows matching the given filters.
    Default mirrors the VB initial filter: active revisions, non-obsolete.
    """
    conditions: list[str] = []
    params: list = []

    if active_rev_only:
        conditions.append("[ACTIVE REV] = 1")
    if not include_obsolete:
        conditions.append("[OBSOLETE] = 0")
    if type_filter:
        conditions.append("[TYPE] = ?")
        params.append(type_filter)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    sql = f"SELECT * FROM [TEST_EQUIPMENT] {where} ORDER BY [ID] DESC"
    return _run(sql, tuple(params))


def fetch_equipment_by_index(index: int) -> dict | None:
    """Return a single TEST_EQUIPMENT row by its [INDEX] PK."""
    rows = _run("SELECT * FROM [TEST_EQUIPMENT] WHERE [INDEX] = ?", (index,))
    return rows[0] if rows else None


def fetch_equipment_revisions(equipment_id: int) -> list[dict]:
    """Return all revisions for a given equipment [ID], newest first."""
    return _run(
        "SELECT * FROM [TEST_EQUIPMENT] WHERE [ID] = ? ORDER BY [REV] DESC",
        (equipment_id,),
    )


def get_max_equipment_id() -> int:
    """Return MAX([ID]) from TEST_EQUIPMENT, used when creating new equipment."""
    rows = _run("SELECT MAX([ID]) AS max_id FROM [TEST_EQUIPMENT]")
    if rows and rows[0].get("max_id") is not None:
        return int(rows[0]["max_id"])
    return 0


# ---------------------------------------------------------------------------
# Create new equipment
# ---------------------------------------------------------------------------

def create_equipment(fields: dict) -> int | None:
    """
    Insert a new TEST_EQUIPMENT row.
    Returns the [INDEX] identity value of the new row, or None on failure.
    """
    if not fields:
        raise ValueError("fields must not be empty")

    bracketed_cols = ", ".join(f"[{col}]" for col in fields)
    placeholders   = ", ".join("?" for _ in fields)
    sql = (
        f"INSERT INTO [TEST_EQUIPMENT] ({bracketed_cols}) "
        f"VALUES ({placeholders})"
    )

    conn = get_meter_specs_connection()
    if conn is None:
        return None
    try:
        cursor = conn.cursor()
        cursor.execute(sql, list(fields.values()))
        cursor.execute("SELECT SCOPE_IDENTITY()")
        row = cursor.fetchone()
        new_index = int(row[0]) if row and row[0] is not None else None
        if new_index is None:
            cursor.execute("SELECT @@IDENTITY")
            row = cursor.fetchone()
            new_index = int(row[0]) if row and row[0] is not None else None
        conn.commit()
        return new_index
    except pyodbc.Error as e:
        print(f"create_equipment error: {e}")
        conn.rollback()
        return None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Update existing equipment
# ---------------------------------------------------------------------------

def update_equipment(index: int, fields: dict) -> bool:
    """Update columns on an existing TEST_EQUIPMENT row by [INDEX]."""
    if not fields:
        raise ValueError("fields must not be empty")

    set_clause = ", ".join(f"[{col}] = ?" for col in fields)
    sql    = f"UPDATE [TEST_EQUIPMENT] SET {set_clause} WHERE [INDEX] = ?"
    params = list(fields.values()) + [index]

    conn = get_meter_specs_connection()
    if conn is None:
        return False
    try:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        conn.commit()
        return cursor.rowcount > 0
    except pyodbc.Error as e:
        print(f"update_equipment error: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Revise calibration — mirrors VB ReviseCalDevice state
# ---------------------------------------------------------------------------

def revise_equipment(old_index: int, new_fields: dict) -> int | None:
    """
    Create a new revision for existing equipment.
    Steps (matching VB frmSelectTestEquipment revision flow):
      1. Set old row's [ACTIVE REV] = 0
      2. Insert new row with same [ID], incremented [REV], [ACTIVE REV] = 1
    Returns the [INDEX] of the new row, or None on failure.
    """
    conn = get_meter_specs_connection()
    if conn is None:
        return None
    try:
        cursor = conn.cursor()

        # Deactivate old revision
        cursor.execute(
            "UPDATE [TEST_EQUIPMENT] SET [ACTIVE REV] = 0 WHERE [INDEX] = ?",
            (old_index,),
        )

        # Insert new revision
        if not new_fields:
            conn.rollback()
            return None

        bracketed_cols = ", ".join(f"[{col}]" for col in new_fields)
        placeholders   = ", ".join("?" for _ in new_fields)
        cursor.execute(
            f"INSERT INTO [TEST_EQUIPMENT] ({bracketed_cols}) VALUES ({placeholders})",
            list(new_fields.values()),
        )

        cursor.execute("SELECT SCOPE_IDENTITY()")
        row = cursor.fetchone()
        new_index = int(row[0]) if row and row[0] is not None else None
        if new_index is None:
            cursor.execute("SELECT @@IDENTITY")
            row = cursor.fetchone()
            new_index = int(row[0]) if row and row[0] is not None else None

        conn.commit()
        return new_index
    except pyodbc.Error as e:
        print(f"revise_equipment error: {e}")
        conn.rollback()
        return None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Obsolete equipment — mirrors VB ObsoleteDevice state
# ---------------------------------------------------------------------------

def obsolete_equipment(index: int) -> bool:
    """
    Mark equipment as obsolete (soft-delete).
    Sets [OBSOLETE] = 1 and [ACTIVE REV] = 0.
    Mirrors VB: no hard delete, maintains audit trail.
    """
    conn = get_meter_specs_connection()
    if conn is None:
        return False
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE [TEST_EQUIPMENT] SET [OBSOLETE] = 1, [ACTIVE REV] = 0 "
            "WHERE [INDEX] = ?",
            (index,),
        )
        conn.commit()
        return cursor.rowcount > 0
    except pyodbc.Error as e:
        print(f"obsolete_equipment error: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()
