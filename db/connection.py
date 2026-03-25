import pyodbc
from config.settings import CONNECTION_STRING

def get_connection():
    try:
        conn = pyodbc.connect(CONNECTION_STRING)
        print("Connection successful!")
        return conn
    except pyodbc.Error as e:
        print(f"Connection failed: {e}")
        return None