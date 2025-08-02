import mysql.connector

def get_connection():
    return mysql.connector.connect(
        host='localhost',
        user='root',
        password='wavedlizard2115',
        database='sistema_formularios'
    )

def get_cursor(conn):
    return conn.cursor(dictionary=True)
