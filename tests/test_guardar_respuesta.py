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
    def __init__(self, fetchone_results=None):
        self.queries = []
        self.fetchone_results = fetchone_results or []
        self.lastrowid = 10

    def execute(self, query, params=None):
        self.queries.append((query, params))

    def executemany(self, query, seq_params):
        self.queries.append((query, seq_params))

    def fetchone(self):
        return self.fetchone_results.pop(0) if self.fetchone_results else None

    def close(self):
        pass

class DummyConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.start_transaction_called = False
        self.commit_called = False

    def cursor(self, dictionary=True):
        return self._cursor

    def start_transaction(self):
        self.start_transaction_called = True

    def commit(self):
        self.commit_called = True

    def rollback(self):
        pass

    def close(self):
        pass

def create_dummy(monkeypatch, fetchone_results=None):
    cursor = DummyCursor(fetchone_results=fetchone_results)
    conn = DummyConnection(cursor)
    monkeypatch.setattr(db, "get_connection", lambda: conn)
    monkeypatch.setattr(app_module, "get_connection", lambda: conn)
    return cursor, conn

def test_guardar_respuesta_cache_bloqueado_evita_db(monkeypatch):
    called = {"value": False}

    def fake_get_connection():
        called["value"] = True
        cursor = DummyCursor()
        return DummyConnection(cursor)

    monkeypatch.setattr(db, "get_connection", fake_get_connection)
    monkeypatch.setattr(app_module, "get_connection", fake_get_connection)

    cache.clear()
    cache.set(bloqueo_key(1, 2), True, timeout=app_module.BLOQUEO_CACHE_TTL)

    with app.test_client() as client:
        resp = client.post("/guardar_respuesta", data={"usuario_id": "1", "formulario_id": "2"})
        assert resp.status_code == 200
        assert b"El formulario ya se respondi" in resp.data

    assert not called["value"]


def test_guardar_respuesta_invalida_cache(monkeypatch):
    cursor, conn = create_dummy(monkeypatch, fetchone_results=[None, {"dummy": 1}, None])
    monkeypatch.setattr(app_module, "get_factores", lambda: [{"id": 1}])

    cache.clear()
    cache.set(bloqueo_key(1, 2), False, timeout=app_module.BLOQUEO_CACHE_TTL)

    data = {
        "usuario_id": "1",
        "formulario_id": "2",
        "nombre": "N",
        "apellidos": "A",
        "cargo": "C",
        "dependencia": "D",
        "factor_id_1": "1",
        "valor_1": "1",
    }

    with app.test_client() as client:
        resp = client.post("/guardar_respuesta", data=data)
        assert resp.status_code == 200
        assert b"Formulario enviado y bloqueado" in resp.data
        assert cache.get(bloqueo_key(1, 2)) is None

        resp2 = client.post("/guardar_respuesta", data=data)
        assert resp2.status_code == 200
        assert b"El formulario ya se respondi" in resp2.data

    assert len(cursor.queries) == 5
    assert "UPDATE usuario" in cursor.queries[0][0]
    assert "SELECT id FROM respuesta" in cursor.queries[1][0]
    assert "INSERT INTO respuesta" in cursor.queries[2][0]
    # Datos completos deben marcar la respuesta como bloqueada (bloqueado=1)
    assert cursor.queries[2][1] == (1, 2, 1)
    assert "INSERT INTO respuesta_detalle" in cursor.queries[3][0]
    assert "SELECT 1 FROM respuesta" in cursor.queries[4][0]
    assert conn.start_transaction_called
    assert conn.commit_called
    assert cache.get(bloqueo_key(1, 2)) is True


def test_guardar_respuesta_incompleta(monkeypatch):
    cursor, conn = create_dummy(monkeypatch)
    monkeypatch.setattr(app_module, "get_factores", lambda: [{"id": 1}, {"id": 2}])

    cache.clear()
    cache.set(bloqueo_key(1, 2), False, timeout=app_module.BLOQUEO_CACHE_TTL)

    data = {
        "usuario_id": "1",
        "formulario_id": "2",
        "nombre": "N",
        "apellidos": "A",
        "cargo": "C",
        "dependencia": "D",
        # Solo se envía un factor de dos
        "factor_id_1": "1",
        "valor_1": "1",
    }

    with app.test_client() as client:
        resp = client.post("/guardar_respuesta", data=data)
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/formulario/1")
        with client.session_transaction() as sess:
            flashes = sess.get("_flashes", [])
        assert (
            "message",
            "Respuestas incompletas; se guardó el progreso sin bloquear",
        ) in flashes
        assert cache.get(bloqueo_key(1, 2)) is None

    assert len(cursor.queries) == 4
    assert "UPDATE usuario" in cursor.queries[0][0]
    assert "SELECT id FROM respuesta" in cursor.queries[1][0]
    assert "INSERT INTO respuesta" in cursor.queries[2][0]
    assert cursor.queries[2][1] == (1, 2, 0)
    assert "INSERT INTO respuesta_detalle" in cursor.queries[3][0]
    assert conn.start_transaction_called
    assert conn.commit_called


def test_guardar_respuesta_incompleta_sin_valor(monkeypatch):
    cursor, conn = create_dummy(monkeypatch)
    monkeypatch.setattr(app_module, "get_factores", lambda: [{"id": 1}, {"id": 2}])

    cache.clear()
    cache.set(bloqueo_key(1, 2), False, timeout=app_module.BLOQUEO_CACHE_TTL)

    data = {
        "usuario_id": "1",
        "formulario_id": "2",
        "nombre": "N",
        "apellidos": "A",
        "cargo": "C",
        "dependencia": "D",
        # Se envían ambos factores pero falta uno de los valores
        "factor_id_1": "1",
        "valor_1": "1",
        "factor_id_2": "2",
        # Falta valor_2
    }

    with app.test_client() as client:
        resp = client.post("/guardar_respuesta", data=data)
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/formulario/1")
        with client.session_transaction() as sess:
            flashes = sess.get("_flashes", [])
        assert (
            "message",
            "Respuestas incompletas; se guardó el progreso sin bloquear",
        ) in flashes
        # El bloqueo no debe marcarse como True
        assert cache.get(bloqueo_key(1, 2)) is None

    # Se insertó la respuesta pero sin bloquear
    assert len(cursor.queries) == 4
    assert "UPDATE usuario" in cursor.queries[0][0]
    assert "SELECT id FROM respuesta" in cursor.queries[1][0]
    assert "INSERT INTO respuesta" in cursor.queries[2][0]
    assert cursor.queries[2][1] == (1, 2, 0)
    assert "INSERT INTO respuesta_detalle" in cursor.queries[3][0]
    assert conn.start_transaction_called
    assert conn.commit_called
