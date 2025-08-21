"""Gestión del pool de conexiones a la base de datos.

Ofrece utilidades para inicializar, obtener y cerrar el pool mediante
:func:`close_pool`.
"""

import os
import threading
import atexit
from mysql.connector import pooling
from mysql.connector.errors import DatabaseError

# Pool de conexiones global. Se inicializa en :func:`init_pool`.
_pool = None
_pool_lock = threading.Lock()


class PoolExhaustedError(RuntimeError):
    """Raised when the database connection pool cannot create new connections."""



def init_pool():
    """Inicializa el pool de conexiones si aún no existe."""
    global _pool
    with _pool_lock:
        if _pool is not None:
            return

        try:
            host = os.getenv("DB_HOST")
            user = os.getenv("DB_USER")
            password = os.getenv("DB_PASSWORD")
            database = os.getenv("DB_NAME")

            missing = [
                name
                for name, value in (
                    ("DB_HOST", host),
                    ("DB_USER", user),
                    ("DB_PASSWORD", password),
                    ("DB_NAME", database),
                )
                if not value
            ]
            if missing:
                raise RuntimeError(
                    "Variables de entorno faltantes: " + ", ".join(missing)
                )

            pool_size = int(os.getenv("DB_POOL_SIZE", "5"))
            _pool = pooling.MySQLConnectionPool(
                pool_name="app_pool",
                pool_size=pool_size,
                host=host,
                user=user,
                password=password,
                database=database,
                connection_timeout=10,
            )
        except DatabaseError as exc:  # pragma: no cover - logging side effect
            if getattr(exc, "errno", None) == 1040:
                raise PoolExhaustedError("Demasiadas conexiones a la base de datos") from exc
            from app import app

            app.logger.exception("Error al inicializar el pool de conexiones")
            raise
        except Exception:  # pragma: no cover - logging side effect
            from app import app

            app.logger.exception("Error al inicializar el pool de conexiones")
            raise


def get_connection():
    """Obtener una conexión del pool de conexiones."""
    if _pool is None:
        init_pool()
    conn = _pool.get_connection()
    conn.autocommit = True
    return conn


def close_pool():
    """Cerrar todas las conexiones activas del pool."""
    global _pool
    with _pool_lock:
        if _pool is None:
            return
        while True:
            try:
                conn = _pool.get_connection()
            except Exception:
                break
            conn.close()
        _pool = None


atexit.register(close_pool)

