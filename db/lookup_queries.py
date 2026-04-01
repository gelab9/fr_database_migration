"""
Lookup queries against the METER_SPECS database.

Mirrors the table/column definitions in cDatabaseDefinations.vb (cMeterSpecDBDef).
Each function returns a list of dicts or a flat list of strings for populating
combo boxes.  Only ACTIVE records are returned unless noted otherwise.

Table reference (from cDatabaseDefinations.vb):
  AMR              — AMR models             col: AMR, ACTIVE
  AMR Rev          — legacy FW revs         col: [AMR Rev]
  APPROVER_TYPE    — TCC disciplines        col: DISCIPLINE
  APPROVERS        — TCC approver persons   cols: many
  BASE             — meter base types       col: BASE, ACTIVE
  FORM             — meter form numbers     col: FORM, ACTIVE
  FW Ver           — legacy FW ver          col: [FW Ver]  (obsolete)
  LEVEL            — PAC test levels        col: LEVEL, ACTIVE
  METER            — meter models           col: METER, METER_TYPE, ... ACTIVE
  TEST STANDARDS   — standard test defs     col: TEST, TEST_TYPE, ACTIVE
  TEST_EQUIPMENT   — test equipment inv.    many cols
  TEST_EQUIPMENT_TYPE — equip categories   col: TEST_TYPE, ACTIVE
  TEST_TYPE        — test type defs         col: TEST_TYPE, ACTIVE
  TESTED BY        — tester names           col: [TESTED BY], ACTIVE
  USERS            — system users           cols: many
"""

import pyodbc
from db.connection import get_meter_specs_connection


def _rows_to_dicts(cursor, rows: list) -> list[dict]:
    cols = [c[0] for c in cursor.description]
    return [{c: v for c, v in zip(cols, row)} for row in rows]


def _flat_list(cursor, rows: list, col: str) -> list[str]:
    """Return a flat sorted list of non-null string values from a single column."""
    result = []
    for row in rows:
        val = row[0] if not isinstance(row, (list, tuple)) or len(row) == 1 else None
        # rows here are raw pyodbc Row objects; index by position
        try:
            val = row[0]
        except Exception:
            continue
        if val is not None:
            s = str(val).strip()
            if s:
                result.append(s)
    return sorted(set(result))


def _run(sql: str, params: tuple = ()) -> list:
    """Execute sql against METER_SPECS and return raw rows, or [] on error."""
    conn = get_meter_specs_connection()
    if conn is None:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        return cursor.fetchall()
    except pyodbc.Error as e:
        print(f"lookup_queries error [{sql[:60]}]: {e}")
        return []
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# AMR  (table: "AMR")
# ---------------------------------------------------------------------------

def fetch_amr_models(active_only: bool = True) -> list[str]:
    """Return distinct AMR model names for combo population."""
    where = "WHERE [ACTIVE] = 1" if active_only else ""
    rows = _run(f"SELECT DISTINCT [AMR] FROM [AMR] {where} ORDER BY [AMR]")
    return [str(r[0]).strip() for r in rows if r[0]]


def fetch_amr_rows(active_only: bool = True) -> list[dict]:
    """Return full AMR rows (ID, AMR, AMR_MANUFACTURER, AMR_TYPE, AMR_SUBTYPE, ...)."""
    where = "WHERE [ACTIVE] = 1" if active_only else ""
    conn = get_meter_specs_connection()
    if conn is None:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute(f"SELECT * FROM [AMR] {where} ORDER BY [AMR]")
        return _rows_to_dicts(cursor, cursor.fetchall())
    except pyodbc.Error as e:
        print(f"fetch_amr_rows error: {e}")
        return []
    finally:
        conn.close()


def fetch_amr_manufacturers(active_only: bool = True) -> list[str]:
    where = "WHERE [ACTIVE] = 1" if active_only else ""
    rows = _run(
        f"SELECT DISTINCT [AMR_MANUFACTURER] FROM [AMR] {where} ORDER BY [AMR_MANUFACTURER]"
    )
    return [str(r[0]).strip() for r in rows if r[0]]


def fetch_amr_types(active_only: bool = True) -> list[str]:
    where = "WHERE [ACTIVE] = 1" if active_only else ""
    rows = _run(
        f"SELECT DISTINCT [AMR_TYPE] FROM [AMR] {where} ORDER BY [AMR_TYPE]"
    )
    return [str(r[0]).strip() for r in rows if r[0]]


def fetch_amr_subtypes(active_only: bool = True) -> list[str]:
    where = "WHERE [ACTIVE] = 1" if active_only else ""
    rows = _run(
        f"SELECT DISTINCT [AMR_SUBTYPE] FROM [AMR] {where} ORDER BY [AMR_SUBTYPE]"
    )
    return [str(r[0]).strip() for r in rows if r[0]]


# ---------------------------------------------------------------------------
# AMR Rev  (table: "AMR Rev") — legacy, kept for completeness
# ---------------------------------------------------------------------------

def fetch_amr_revisions() -> list[str]:
    rows = _run("SELECT [AMR Rev] FROM [AMR Rev] ORDER BY [AMR Rev]")
    return [str(r[0]).strip() for r in rows if r[0]]


# ---------------------------------------------------------------------------
# APPROVER_TYPE  (table: "APPROVER_TYPE")
# ---------------------------------------------------------------------------

def fetch_approver_disciplines() -> list[str]:
    """Return list of TCC discipline names (Compliance, Engineering, ...)."""
    rows = _run("SELECT [DISCIPLINE] FROM [APPROVER_TYPE] ORDER BY [DISCIPLINE]")
    return [str(r[0]).strip() for r in rows if r[0]]


# ---------------------------------------------------------------------------
# APPROVERS  (table: "APPROVERS")
# ---------------------------------------------------------------------------

def fetch_approvers(active_only: bool = True) -> list[dict]:
    """
    Return full approver rows.
    Cols: ID, USER_ID, APPROVER_NAME, DISCIPLINE, APPROVER_TYPE_ID, ACTIVE,
          DELEGATE, VOTING_MEMBER
    """
    where = "WHERE [ACTIVE] = 1" if active_only else ""
    conn = get_meter_specs_connection()
    if conn is None:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT * FROM [APPROVERS] {where} ORDER BY [APPROVER_NAME]"
        )
        return _rows_to_dicts(cursor, cursor.fetchall())
    except pyodbc.Error as e:
        print(f"fetch_approvers error: {e}")
        return []
    finally:
        conn.close()


def fetch_approver_by_user_id(user_id: int) -> dict | None:
    """Return the active approver record for a given USERS.ID, or None."""
    conn = get_meter_specs_connection()
    if conn is None:
        return None
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM [APPROVERS] WHERE [USER_ID] = ? AND [ACTIVE] = 1",
            (user_id,),
        )
        rows = _rows_to_dicts(cursor, cursor.fetchall())
        return rows[0] if rows else None
    except pyodbc.Error as e:
        print(f"fetch_approver_by_user_id error: {e}")
        return None
    finally:
        conn.close()


def fetch_approvers_by_user_id_all(user_id: int) -> list[dict]:
    """Return ALL approver rows (active or not) for a given user id."""
    conn = get_meter_specs_connection()
    if conn is None:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM [APPROVERS] WHERE [USER_ID] = ?",
            (user_id,),
        )
        return _rows_to_dicts(cursor, cursor.fetchall())
    except pyodbc.Error as e:
        print(f"fetch_approvers_by_user_id_all error: {e}")
        return []
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# BASE  (table: "BASE")
# ---------------------------------------------------------------------------

def fetch_meter_bases(active_only: bool = True) -> list[str]:
    where = "WHERE [ACTIVE] = 1" if active_only else ""
    rows = _run(f"SELECT [BASE] FROM [BASE] {where} ORDER BY [BASE]")
    return [str(r[0]).strip() for r in rows if r[0]]


# ---------------------------------------------------------------------------
# FORM  (table: "FORM")
# ---------------------------------------------------------------------------

def fetch_meter_forms(active_only: bool = True) -> list[str]:
    where = "WHERE [ACTIVE] = 1" if active_only else ""
    rows = _run(f"SELECT [FORM] FROM [FORM] {where} ORDER BY [FORM]")
    return [str(r[0]).strip() for r in rows if r[0]]


# ---------------------------------------------------------------------------
# FW Ver  (table: "FW Ver") — obsolete, kept for legacy display
# ---------------------------------------------------------------------------

def fetch_fw_versions() -> list[str]:
    rows = _run("SELECT [FW Ver] FROM [FW Ver] ORDER BY [FW Ver]")
    return [str(r[0]).strip() for r in rows if r[0]]


# ---------------------------------------------------------------------------
# LEVEL  (table: "LEVEL") — PAC test levels
# ---------------------------------------------------------------------------

def fetch_test_levels(active_only: bool = True) -> list[str]:
    where = "WHERE [ACTIVE] = 1" if active_only else ""
    rows = _run(f"SELECT [LEVEL] FROM [LEVEL] {where} ORDER BY [LEVEL]")
    return [str(r[0]).strip() for r in rows if r[0]]


# ---------------------------------------------------------------------------
# METER  (table: "METER")
# ---------------------------------------------------------------------------

def fetch_meter_models(active_only: bool = True) -> list[str]:
    where = "WHERE [ACTIVE] = 1" if active_only else ""
    rows = _run(f"SELECT DISTINCT [METER] FROM [METER] {where} ORDER BY [METER]")
    return [str(r[0]).strip() for r in rows if r[0]]


def fetch_meter_rows(active_only: bool = True) -> list[dict]:
    """Full METER rows (ID, METER, METER_MANUFACTURER, METER_TYPE, ...)."""
    where = "WHERE [ACTIVE] = 1" if active_only else ""
    conn = get_meter_specs_connection()
    if conn is None:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute(f"SELECT * FROM [METER] {where} ORDER BY [METER]")
        return _rows_to_dicts(cursor, cursor.fetchall())
    except pyodbc.Error as e:
        print(f"fetch_meter_rows error: {e}")
        return []
    finally:
        conn.close()


def fetch_meter_manufacturers(active_only: bool = True) -> list[str]:
    where = "WHERE [ACTIVE] = 1" if active_only else ""
    rows = _run(
        f"SELECT DISTINCT [METER_MANUFACTURER] FROM [METER] {where} ORDER BY [METER_MANUFACTURER]"
    )
    return [str(r[0]).strip() for r in rows if r[0]]


def fetch_meter_types(active_only: bool = True) -> list[str]:
    where = "WHERE [ACTIVE] = 1" if active_only else ""
    rows = _run(
        f"SELECT DISTINCT [METER_TYPE] FROM [METER] {where} ORDER BY [METER_TYPE]"
    )
    return [str(r[0]).strip() for r in rows if r[0]]


def fetch_meter_subtypes(active_only: bool = True) -> list[str]:
    where = "WHERE [ACTIVE] = 1" if active_only else ""
    rows = _run(
        f"SELECT DISTINCT [METER_SUBTYPE] FROM [METER] {where} ORDER BY [METER_SUBTYPE]"
    )
    return [str(r[0]).strip() for r in rows if r[0]]


# ---------------------------------------------------------------------------
# TEST STANDARDS  (table: "TEST STANDARDS")
# ---------------------------------------------------------------------------

def fetch_test_standards(active_only: bool = True) -> list[dict]:
    """Return full test standard rows: ID, TEST, TEST_TYPE, TAGS, ACTIVE."""
    where = "WHERE [ACTIVE] = 1" if active_only else ""
    conn = get_meter_specs_connection()
    if conn is None:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT * FROM [TEST STANDARDS] {where} ORDER BY [TEST]"
        )
        return _rows_to_dicts(cursor, cursor.fetchall())
    except pyodbc.Error as e:
        print(f"fetch_test_standards error: {e}")
        return []
    finally:
        conn.close()


def fetch_test_names(test_type: str = "", active_only: bool = True) -> list[str]:
    """Return test name strings, optionally filtered by TEST_TYPE."""
    conditions = []
    params = []
    if active_only:
        conditions.append("[ACTIVE] = 1")
    if test_type:
        conditions.append("[TEST_TYPE] = ?")
        params.append(test_type)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    rows = _run(
        f"SELECT DISTINCT [TEST] FROM [TEST STANDARDS] {where} ORDER BY [TEST]",
        tuple(params),
    )
    return [str(r[0]).strip() for r in rows if r[0]]


# ---------------------------------------------------------------------------
# TEST_TYPE  (table: "TEST_TYPE")
# ---------------------------------------------------------------------------

def fetch_test_types(active_only: bool = True) -> list[str]:
    where = "WHERE [ACTIVE] = 1" if active_only else ""
    rows = _run(
        f"SELECT [TEST_TYPE] FROM [TEST_TYPE] {where} ORDER BY [TEST_TYPE]"
    )
    return [str(r[0]).strip() for r in rows if r[0]]


# ---------------------------------------------------------------------------
# TEST_EQUIPMENT_TYPE  (table: "TEST_EQUIPMENT_TYPE")
# ---------------------------------------------------------------------------

def fetch_equipment_types(active_only: bool = True) -> list[str]:
    where = "WHERE [ACTIVE] = 1" if active_only else ""
    rows = _run(
        f"SELECT [TEST_TYPE] FROM [TEST_EQUIPMENT_TYPE] {where} ORDER BY [TEST_TYPE]"
    )
    return [str(r[0]).strip() for r in rows if r[0]]


# ---------------------------------------------------------------------------
# TEST_EQUIPMENT  (table: "TEST_EQUIPMENT")
# ---------------------------------------------------------------------------

def fetch_test_equipment(active_rev_only: bool = True, include_obsolete: bool = False) -> list[dict]:
    """
    Return TEST_EQUIPMENT rows.
    Mirrors the VB default filter: [Active Rev] = True AND [Obsolete] = False
    """
    conditions = []
    if active_rev_only:
        conditions.append("[ACTIVE REV] = 1")
    if not include_obsolete:
        conditions.append("[OBSOLETE] = 0")
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    conn = get_meter_specs_connection()
    if conn is None:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT * FROM [TEST_EQUIPMENT] {where} ORDER BY [ID]"
        )
        return _rows_to_dicts(cursor, cursor.fetchall())
    except pyodbc.Error as e:
        print(f"fetch_test_equipment error: {e}")
        return []
    finally:
        conn.close()


def fetch_equipment_by_index(index: int) -> dict | None:
    conn = get_meter_specs_connection()
    if conn is None:
        return None
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM [TEST_EQUIPMENT] WHERE [INDEX] = ?", (index,))
        rows = _rows_to_dicts(cursor, cursor.fetchall())
        return rows[0] if rows else None
    except pyodbc.Error as e:
        print(f"fetch_equipment_by_index error: {e}")
        return None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# TESTED BY  (table: "TESTED BY")
# ---------------------------------------------------------------------------

def fetch_testers(active_only: bool = True) -> list[str]:
    where = "WHERE [ACTIVE] = 1" if active_only else ""
    rows = _run(
        f"SELECT [TESTED BY] FROM [TESTED BY] {where} ORDER BY [TESTED BY]"
    )
    return [str(r[0]).strip() for r in rows if r[0]]


# ---------------------------------------------------------------------------
# USERS  (table: "USERS")
# ---------------------------------------------------------------------------

def fetch_user_by_username(username: str) -> dict | None:
    """
    Return the USERS row for the given username, or None.
    Mirrors the VB query: SELECT * FROM [Users] WHERE username = '<username>'
    Note: username is stripped of wildcards before querying.
    """
    safe_username = username.strip().replace("%", "")
    conn = get_meter_specs_connection()
    if conn is None:
        return None
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM [USERS] WHERE [USERNAME] = ?", (safe_username,)
        )
        rows = _rows_to_dicts(cursor, cursor.fetchall())
        if len(rows) == 1:
            return rows[0]
        if len(rows) > 1:
            print(f"fetch_user_by_username: multiple rows for '{safe_username}'")
        return None
    except pyodbc.Error as e:
        print(f"fetch_user_by_username error: {e}")
        # Distinguish SQL Server permission errors (SQLSTATE 42000) from other failures
        # so the login dialog can show a meaningful message instead of "Username not found".
        sqlstate = e.args[0] if e.args else ""
        msg = str(e).lower()
        if sqlstate == "42000" and "permission" in msg:
            raise PermissionError(
                "Your Windows account does not have SELECT permission on "
                "METER_SPECS.dbo.USERS.\n\n"
                "Ask your DBA to run:\n"
                "  GRANT SELECT ON [METER_SPECS].[dbo].[USERS] TO [<your-domain\\username>]\n"
                "  GRANT SELECT ON [METER_SPECS].[dbo].[APPROVERS] TO [<your-domain\\username>]"
            ) from e
        return None
    finally:
        conn.close()


def fetch_approvers_by_discipline(discipline_name: str) -> list[str]:
    """
    Return active approver names for a specific discipline.
    Used to populate TCC 1-6 combo boxes in the approval tab.
    Maps to VB's per-discipline dropdown population in frmFailureBrowser.vb.

    discipline_name values (from APPROVERS.DISCIPLINE column):
      "Compliance", "Development Engineering", "Manufacturing",
      "Product Management", "Supplier Quality", "Systems"
    """
    rows = _run(
        "SELECT [APPROVER_NAME] FROM [APPROVERS] "
        "WHERE [ACTIVE] = 1 AND [DISCIPLINE] = ? "
        "ORDER BY [APPROVER_NAME]",
        (discipline_name,),
    )
    return [str(r[0]).strip() for r in rows if r[0]]


def fetch_all_users() -> list[dict]:
    """Return all USERS rows ordered by LastName for the Manage Users admin dialog."""
    conn = get_meter_specs_connection()
    if conn is None:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT [ID], [username], [FirstName], [LastName], [AccessLevel], "
            "[Active], [email] FROM [USERS] ORDER BY [LastName], [FirstName]"
        )
        return _rows_to_dicts(cursor, cursor.fetchall())
    except pyodbc.Error as e:
        print(f"fetch_all_users error: {e}")
        return []
    finally:
        conn.close()


def set_user_active(user_id: int, active: bool) -> bool:
    """Enable or disable a user account (ADMIN only)."""
    conn = get_meter_specs_connection()
    if conn is None:
        return False
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE [USERS] SET [Active] = ? WHERE [ID] = ?",
            (1 if active else 0, user_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    except pyodbc.Error as e:
        print(f"set_user_active error: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def create_user(username: str, first_name: str, last_name: str,
                access_level: int, email: str = "") -> bool:
    """Insert a new USERS row. Password is blank; user must reset on first login."""
    conn = get_meter_specs_connection()
    if conn is None:
        return False
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO [USERS] ([username],[password],[FirstName],[LastName],"
            "[AccessLevel],[Active],[PassWordIsReset],[email]) "
            "VALUES (?,?,?,?,?,1,1,?)",
            (username.strip(), "", first_name.strip(), last_name.strip(),
             access_level, email.strip()),
        )
        conn.commit()
        return True
    except pyodbc.Error as e:
        print(f"create_user error: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def update_user(user_id: int, first_name: str, last_name: str,
                access_level: int, email: str) -> bool:
    """Update editable fields on a USERS row (ADMIN only)."""
    conn = get_meter_specs_connection()
    if conn is None:
        return False
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE [USERS] SET [FirstName]=?, [LastName]=?, "
            "[AccessLevel]=?, [email]=? WHERE [ID]=?",
            (first_name.strip(), last_name.strip(), access_level,
             email.strip(), user_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    except pyodbc.Error as e:
        print(f"update_user error: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def fetch_active_usernames() -> list[str]:
    rows = _run(
        "SELECT [USERNAME] FROM [USERS] WHERE [ACTIVE] = 1 ORDER BY [USERNAME]"
    )
    return [str(r[0]).strip() for r in rows if r[0]]


def update_user_password(user_id: int, new_password: str) -> bool:
    """Update a user's internal password and clear the PASSWORDISRESET flag."""
    conn = get_meter_specs_connection()
    if conn is None:
        return False
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE [USERS] SET [PASSWORD] = ?, [PASSWORDISRESET] = 0 WHERE [ID] = ?",
            (new_password, user_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    except pyodbc.Error as e:
        print(f"update_user_password error: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()
