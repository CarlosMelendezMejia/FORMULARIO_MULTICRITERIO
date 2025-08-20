import os
import sys
import pytest
from werkzeug.security import generate_password_hash

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

import db
import app as app_module

app = app_module.app
cache = app_module.cache
RANKING_CACHE_KEY = app_module.RANKING_CACHE_KEY
bloqueo_key = app_module._bloqueo_cache_key

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


def test_crear_formulario_nombre_por_defecto(monkeypatch):
    fetchone_results = [{"siguiente_id": None}]
    cursor, conn = create_dummy(monkeypatch, fetchone_results=fetchone_results)

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["is_admin"] = True
        resp = client.post("/admin/formularios", data={"nombre": ""})
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/admin/formularios")

    assert len(cursor.queries) == 2
    assert "AUTO_INCREMENT AS siguiente_id" in cursor.queries[0][0]
    assert cursor.queries[1] == (
        "INSERT INTO formulario (nombre, requiere_password, password_hash) VALUES (%s, %s, %s)",
        ("Formulario 01", 0, None),
    )
    assert conn.commit_called


def test_reiniciar_formularios_requires_admin(monkeypatch):
    cursor, conn = create_dummy(monkeypatch)
    with app.test_client() as client:
        resp = client.post("/admin/formularios/reiniciar")
        assert resp.status_code == 302
        assert "/admin/login" in resp.headers["Location"]
        assert cursor.queries == []


def test_reiniciar_formularios(monkeypatch):
    cursor, conn = create_dummy(monkeypatch)
    cache.clear()
    cache.set(RANKING_CACHE_KEY, {"ranking": "x", "incompletas": "y"})
    cache.set(bloqueo_key(5, 9), True, timeout=app_module.BLOQUEO_CACHE_TTL)

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
    assert cache.get(bloqueo_key(5, 9)) is None


def test_eliminar_formulario_invalida_cache(monkeypatch):
    fetchone_results = [{"total": 0}]
    cursor, conn = create_dummy(monkeypatch, fetchone_results=fetchone_results)

    cache.clear()
    cache.set(RANKING_CACHE_KEY, {"ranking": "cached", "incompletas": "cached"})
    cache.set(bloqueo_key(2, 1), True, timeout=app_module.BLOQUEO_CACHE_TTL)

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["is_admin"] = True
        resp = client.post("/admin/formularios/eliminar/1", data={"confirm": "yes"})
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/admin/formularios")

    assert cursor.queries == [
        (
            "SELECT COUNT(*) AS total FROM respuesta WHERE id_formulario = %s AND bloqueado = 1",
            (1,),
        ),
        ("DELETE FROM respuesta WHERE id_formulario = %s", (1,)),
        ("DELETE FROM asignacion WHERE id_formulario = %s", (1,)),
        ("DELETE FROM formulario WHERE id = %s", (1,)),
    ]
    assert conn.commit_called
    assert cache.get(RANKING_CACHE_KEY) is None
    assert cache.get(bloqueo_key(2, 1)) is None


def test_activar_password_formulario(monkeypatch):
    fetchone_results = [{"siguiente_id": None}]
    cursor, conn = create_dummy(monkeypatch, fetchone_results=fetchone_results)

    expected_hash = generate_password_hash("secret")
    monkeypatch.setattr(app_module, "generate_password_hash", lambda pw: expected_hash)

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["is_admin"] = True
        resp = client.post(
            "/admin/formularios",
            data={"id_formulario": "1", "requiere_password": "on", "password": "secret"},
        )
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/admin/formularios")

    assert len(cursor.queries) == 2
    assert "AUTO_INCREMENT AS siguiente_id" in cursor.queries[0][0]
    assert cursor.queries[1] == (
        "UPDATE formulario SET requiere_password = %s, password_hash = %s WHERE id = %s",
        (1, expected_hash, 1),
    )
    assert conn.commit_called


def test_desactivar_password_formulario(monkeypatch):
    fetchone_results = [{"siguiente_id": None}]
    cursor, conn = create_dummy(monkeypatch, fetchone_results=fetchone_results)

    current_hash = generate_password_hash("old")

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["is_admin"] = True
        resp = client.post(
            "/admin/formularios",
            data={"id_formulario": "1", "current_password_hash": current_hash},
        )
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/admin/formularios")

    assert len(cursor.queries) == 2
    assert "AUTO_INCREMENT AS siguiente_id" in cursor.queries[0][0]
    assert cursor.queries[1] == (
        "UPDATE formulario SET requiere_password = %s, password_hash = %s WHERE id = %s",
        (0, None, 1),
    )
    assert conn.commit_called


def test_abrir_formulario_requires_admin(monkeypatch):
    cursor, conn = create_dummy(monkeypatch)
    with app.test_client() as client:
        resp = client.post("/admin/formularios/abrir/1")
        assert resp.status_code == 302
        assert "/admin/login" in resp.headers["Location"]
        assert cursor.queries == []


def test_abrir_formulario(monkeypatch):
    fetchone_results = [{"id_usuario": 2, "id_formulario": 7}]
    cursor, conn = create_dummy(monkeypatch, fetchone_results=fetchone_results)
    cache.clear()
    cache.set(RANKING_CACHE_KEY, {"ranking": "x"})
    cache.set(bloqueo_key(2, 7), True, timeout=app_module.BLOQUEO_CACHE_TTL)

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["is_admin"] = True
        resp = client.post("/admin/formularios/abrir/5")
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/admin")

    assert cursor.queries == [
        ("SELECT id_usuario, id_formulario FROM respuesta WHERE id = %s", (5,)),
        ("UPDATE respuesta SET bloqueado = 0 WHERE id = %s", (5,)),
    ]
    assert conn.commit_called
    assert cache.get(RANKING_CACHE_KEY) is None
    assert cache.get(bloqueo_key(2, 7)) is None
