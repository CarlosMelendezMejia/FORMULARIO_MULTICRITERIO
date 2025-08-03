import os
from mysql.connector import pooling

# Crear un pool de conexiones para reutilizar conexiones a la base de datos
_pool = pooling.MySQLConnectionPool(
    pool_name="app_pool",
    pool_size=5,
    host=os.environ.get("DB_HOST"),
    user=os.environ.get("DB_USER"),
    password=os.environ.get("DB_PASSWORD"),
    database=os.environ.get("DB_NAME"),
)


def get_connection():
    """Obtener una conexión del pool de conexiones."""
    return _pool.get_connection()

