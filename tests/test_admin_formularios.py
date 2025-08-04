import os
import sys
import pytest

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

import db
import app as app_module

app = app_module.app
cache = app_module.cache
RANKING_CACHE_KEY = app_module.RANKING_CACHE_KEY

class DummyCursor:
    def __init__(self, fetchone_results=None):
        self.queries = []
        self.fetchone_results = fetchone_results or []

    def execute(self, query, params=None):
        self.queries.append((query, params))

    def fetchone(self):
        return self.fetchone_results.pop(0)

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


def create_dummy(monkeypatch, fetchone_results=None):
    cursor = DummyCursor(fetchone_results=fetchone_results)
    conn = DummyConnection(cursor)
    monkeypatch.setattr(db, "get_connection", lambda: conn)
    monkeypatch.setattr(app_module, "get_connection", lambda: conn)
    return cursor, conn


def test_reiniciar_formularios_requires_admin(monkeypatch):
    cursor, conn = create_dummy(monkeypatch)
    with app.test_client() as client:
        resp = client.post("/admin/formularios/reiniciar")
        assert resp.status_code == 302
        assert "/admin/login" in resp.headers["Location"]
        assert cursor.queries == []


def test_reiniciar_formularios(monkeypatch):
    cursor, conn = create_dummy(monkeypatch)
    cache.set(RANKING_CACHE_KEY, {"ranking": "x", "incompletas": "y"})

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["is_admin"] = True
        resp = client.post("/admin/formularios/reiniciar")
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/admin/formularios")

    assert cursor.queries == [
        ("DELETE FROM ponderacion_admin", None),
        ("DELETE FROM respuesta_detalle", None),
        ("DELETE FROM respuesta", None),
    ]
    assert conn.commit_called
    assert cache.get(RANKING_CACHE_KEY) is None


def test_eliminar_formulario_invalida_cache(monkeypatch):
    fetchone_results = [{"total": 0}]
    cursor, conn = create_dummy(monkeypatch, fetchone_results=fetchone_results)

    cache.set(RANKING_CACHE_KEY, {"ranking": "cached", "incompletas": "cached"})

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["is_admin"] = True
        resp = client.post("/admin/formularios/eliminar/1", data={"confirm": "yes"})
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/admin/formularios")

    assert cursor.queries == [
        ("SELECT COUNT(*) AS total FROM respuesta WHERE id_formulario = %s", (1,)),
        ("DELETE FROM respuesta WHERE id_formulario = %s", (1,)),
        ("DELETE FROM asignacion WHERE id_formulario = %s", (1,)),
        ("DELETE FROM formulario WHERE id = %s", (1,)),
    ]
    assert conn.commit_called
    assert cache.get(RANKING_CACHE_KEY) is None
