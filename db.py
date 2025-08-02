import os
import mysql.connector

def get_connection():
    """Create a connection to the MySQL database using environment variables."""
    return mysql.connector.connect(
        host=os.environ.get("DB_HOST"),
        user=os.environ.get("DB_USER"),
        password=os.environ.get("DB_PASSWORD"),
        database=os.environ.get("DB_NAME"),
    )

def get_cursor(conn):
    return conn.cursor(dictionary=True)
