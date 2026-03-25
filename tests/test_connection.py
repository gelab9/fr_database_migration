import os
import sys

# Ensure direct script execution from tests/ can import top-level packages
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from db.connection import get_connection

def test_connection():
    conn = get_connection()
    if conn:
        cursor = conn.cursor()

        # Pull all table names
        cursor.execute("""
            SELECT TABLE_NAME 
            FROM INFORMATION_SCHEMA.TABLES 
            WHERE TABLE_TYPE = 'BASE TABLE'
            ORDER BY TABLE_NAME
        """)
        tables = cursor.fetchall()

        print(f"\nFound {len(tables)} tables:")
        for table in tables:
            # Get row count for each table
            cursor.execute(f"SELECT COUNT(*) FROM [{table[0]}]")
            count = cursor.fetchone()[0]
            print(f"  {table[0]} — {count} rows")

        # Pull stored procedures
        cursor.execute("""
            SELECT ROUTINE_NAME 
            FROM INFORMATION_SCHEMA.ROUTINES
            WHERE ROUTINE_TYPE = 'PROCEDURE'
            ORDER BY ROUTINE_NAME
        """)
        procs = cursor.fetchall()
        print(f"\nFound {len(procs)} stored procedures:")
        for proc in procs:
            print(f"  {proc[0]}")

        cursor.execute("""
            SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, CHARACTER_MAXIMUM_LENGTH
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_NAME = 'Failure Report'
            ORDER BY ORDINAL_POSITION
        """)
        columns = cursor.fetchall()
        print(f"\nFailure Report columns:")
        for col in columns:
            length = f"({col[3]})" if col[3] else ""
            nullable = "nullable" if col[2] == 'YES' else "required"
            print(f"  {col[0]} — {col[1]}{length} ({nullable})")

        # View the stored procedure definition
        cursor.execute("""
            SELECT ROUTINE_DEFINITION
            FROM INFORMATION_SCHEMA.ROUTINES
            WHERE ROUTINE_NAME = 'GET_FR_DATA'
        """)
        proc_def = cursor.fetchone()
        print(f"\nGET_FR_DATA definition:")
        print(proc_def[0])

        # Check what values are actually used in the dropdown fields
        for field in ['EUT_TYPE', 'Meter_Type', 'Test_Type']:
            cursor.execute(f"""
                SELECT DISTINCT [{field}], COUNT(*) as count
                FROM [Failure Report]
                WHERE [{field}] IS NOT NULL AND [{field}] != ''
                GROUP BY [{field}]
                ORDER BY count DESC
            """)
            values = cursor.fetchall()
            print(f"\n{field} values ({len(values)} distinct):")
            for val in values:
                print(f"  {val[0]} — {val[1]} records")

    conn.close()
test_connection()