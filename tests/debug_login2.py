"""
Debug script — run from project root:
    python tests\debug_login2.py

Checks:
  1. Can we connect to METER_SPECS at all?
  2. What usernames actually exist in the USERS table?
  3. Does our username appear under any casing / format?
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db.connection import get_meter_specs_connection

conn = get_meter_specs_connection()

if conn is None:
    print("FAILED: Could not connect to METER_SPECS database at all.")
    print("Check your METER_SPECS_CONNECTION_STRING in config/settings.py")
    sys.exit(1)

print("OK: Connected to METER_SPECS successfully.\n")

cursor = conn.cursor()

# ── 1. Dump ALL usernames so we can see what format they are stored in ──
print("=" * 60)
print("ALL usernames in USERS table:")
print("=" * 60)
try:
    cursor.execute("SELECT [ID], [USERNAME], [FIRSTNAME], [LASTNAME], [ACTIVE], [ACCESSLEVEL] FROM [USERS] ORDER BY [USERNAME]")
    rows = cursor.fetchall()
    if not rows:
        print("  (table is empty or no rows returned)")
    for row in rows:
        print(f"  ID={row[0]}  USERNAME={repr(row[1])}  NAME={row[2]} {row[3]}  ACTIVE={repr(row[4])}  LEVEL={repr(row[5])}")
except Exception as e:
    print(f"  ERROR querying USERS table: {e}")

print()

# ── 2. Try a LIKE search so partial matches show up ──
print("=" * 60)
print("LIKE search for 'kogutama' (case-insensitive, partial):")
print("=" * 60)
try:
    cursor.execute("SELECT [ID], [USERNAME], [FIRSTNAME], [LASTNAME] FROM [USERS] WHERE [USERNAME] LIKE ?", ("%kogutama%",))
    rows = cursor.fetchall()
    if not rows:
        print("  No rows matched '%kogutama%'")
    for row in rows:
        print(f"  ID={row[0]}  USERNAME={repr(row[1])}  NAME={row[2]} {row[3]}")
except Exception as e:
    print(f"  ERROR: {e}")

print()

# ── 3. Check what columns actually exist on the USERS table ──
print("=" * 60)
print("USERS table column names:")
print("=" * 60)
try:
    cursor.execute("SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = 'USERS' ORDER BY ORDINAL_POSITION")
    cols = cursor.fetchall()
    for col in cols:
        print(f"  {col[0]}  ({col[1]})")
except Exception as e:
    print(f"  ERROR: {e}")

conn.close()