import pyodbc
from config.settings import CONNECTION_STRING, METER_SPECS_CONNECTION_STRING


def get_connection():
    """Return a pyodbc connection to the FAILURE_REPORT database, or None on failure."""
    try:
        conn = pyodbc.connect(CONNECTION_STRING)
        return conn
    except pyodbc.Error as e:
        print(f"FAILURE_REPORT connection failed: {e}")
        return None


def get_meter_specs_connection():
    """Return a pyodbc connection to the METER_SPECS database, or None on failure."""
    try:
        conn = pyodbc.connect(METER_SPECS_CONNECTION_STRING)
        return conn
    except pyodbc.Error as e:
        print(f"METER_SPECS connection failed: {e}")
        return None