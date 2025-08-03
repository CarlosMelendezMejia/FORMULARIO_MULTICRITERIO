import os
from mysql.connector import pooling

# Pool de conexiones global. Se inicializa en :func:`init_pool`.
_pool = None


def init_pool():
    """Inicializa el pool de conexiones si aún no existe."""
    global _pool
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

        _pool = pooling.MySQLConnectionPool(
            pool_name="app_pool",
            pool_size=5,
            host=host,
            user=user,
            password=password,
            database=database,
        )
    except Exception:  # pragma: no cover - logging side effect
        from app import app

        app.logger.exception("Error al inicializar el pool de conexiones")
        raise


def get_connection():
    """Obtener una conexión del pool de conexiones."""
    if _pool is None:
        init_pool()
    return _pool.get_connection()

