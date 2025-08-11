import os
import sys
import pytest

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

import db
import app as app_module

app = app_module.app
cache = app_module.cache
bloqueo_key = app_module._bloqueo_cache_key


class DummyCursor:
    def __init__(self, fetchone_results=None, fetchall_results=None):
        self.queries = []
        self.fetchone_results = fetchone_results or []
        self.fetchall_results = fetchall_results or []

    def execute(self, query, params=None):
        self.queries.append((query, params))

    def fetchone(self):
        return self.fetchone_results.pop(0) if self.fetchone_results else None

    def fetchall(self):
        return self.fetchall_results.pop(0) if self.fetchall_results else []

    def close(self):
        pass


class DummyConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.commit_called = False

    def cursor(self, dictionary=True):
        return self._cursor

    def commit(self):
        self.commit_called = True

    def close(self):
        pass


def create_dummy(monkeypatch, fetchone_results=None, fetchall_results=None):
    cursor = DummyCursor(fetchone_results=fetchone_results, fetchall_results=fetchall_results)
    conn = DummyConnection(cursor)
    monkeypatch.setattr(db, "get_connection", lambda: conn)
    monkeypatch.setattr(app_module, "get_connection", lambda: conn)
    return cursor, conn


def test_mostrar_formulario_bloqueado(monkeypatch):
    fetchone_results = [
        {"id_formulario": 2, "nombre_formulario": "F1"},
        {"dummy": 1},
    ]
    cursor, _ = create_dummy(monkeypatch, fetchone_results=fetchone_results)
    cache.clear()

    with app.test_client() as client:
        resp = client.get("/formulario/1")
        assert resp.status_code == 200
        assert b"El formulario ya se respondi" in resp.data

    assert len(cursor.queries) == 2


def test_reapertura_permite_formulario(monkeypatch):
    fetchone_results = [
        {"id_usuario": 1, "id_formulario": 2},
        {"id_formulario": 2, "nombre_formulario": "F1"},
        None,
        {
            "id": 1,
            "nombre": "N",
            "apellidos": "A",
            "cargo": "C",
            "dependencia": "D",
        },
    ]
    fetchall_results = [
        [],
    ]
    cursor, conn = create_dummy(
        monkeypatch, fetchone_results=fetchone_results, fetchall_results=fetchall_results
    )
    monkeypatch.setattr(app_module, "get_factores", lambda: [{"id": 1, "nombre": "Factor"}])

    cache.clear()
    cache.set(bloqueo_key(1, 2), True, timeout=app_module.BLOQUEO_CACHE_TTL)

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["is_admin"] = True
        resp = client.post("/admin/formularios/abrir/5")
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/admin")
        assert conn.commit_called
        assert cache.get(bloqueo_key(1, 2)) is None

        resp2 = client.get("/formulario/1")
        assert resp2.status_code == 200
        assert b"Formulario de Evalu" in resp2.data

    assert len(cursor.queries) >= 4
