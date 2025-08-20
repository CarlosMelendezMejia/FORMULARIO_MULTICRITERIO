import os
import sys
import pytest
from werkzeug.security import generate_password_hash

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

import db
import app as app_module

app = app_module.app


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

    def cursor(self, dictionary=True):
        return self._cursor

    def close(self):
        pass


def create_dummy(monkeypatch, fetchone_results=None, fetchall_results=None):
    cursor = DummyCursor(fetchone_results=fetchone_results, fetchall_results=fetchall_results)
    conn = DummyConnection(cursor)
    monkeypatch.setattr(db, "get_connection", lambda: conn)
    monkeypatch.setattr(app_module, "get_connection", lambda: conn)
    return cursor, conn


def assignment_dict(hash_value):
    return {
        "id_formulario": 2,
        "nombre_formulario": "F1",
        "requiere_password": 1,
        "password_hash": hash_value,
    }


def test_password_correcta(monkeypatch):
    hash_secret = generate_password_hash("secret")
    fetchone_results = [
        assignment_dict(hash_secret),
        assignment_dict(hash_secret),
        assignment_dict(hash_secret),
        assignment_dict(hash_secret),
        {
            "id": 1,
            "nombre": "N",
            "apellidos": "A",
            "cargo": "C",
            "dependencia": "D",
        },
    ]
    fetchall_results = [[]]
    cursor, _ = create_dummy(monkeypatch, fetchone_results, fetchall_results)
    monkeypatch.setattr(app_module, "get_factores", lambda: [{"id": 1, "nombre": "Factor"}])
    monkeypatch.setattr(app_module, "is_formulario_bloqueado", lambda *args, **kwargs: False)

    with app.test_client() as client:
        resp = client.get("/formulario/1")
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/formulario/1/password")

        resp2 = client.get("/formulario/1/password")
        assert resp2.status_code == 200
        assert b"contrase" in resp2.data.lower()

        resp3 = client.post("/formulario/1/password", data={"password": "secret"})
        assert resp3.status_code == 302
        assert resp3.headers["Location"].endswith("/formulario/1")

        resp4 = client.get("/formulario/1")
        assert resp4.status_code == 200
        assert b"Formulario de Evalu" in resp4.data

    assert len(cursor.queries) >= 5


def test_password_incorrecta(monkeypatch):
    hash_secret = generate_password_hash("secret")
    fetchone_results = [
        assignment_dict(hash_secret),
        assignment_dict(hash_secret),
        assignment_dict(hash_secret),
        assignment_dict(hash_secret),
    ]
    cursor, _ = create_dummy(monkeypatch, fetchone_results)

    with app.test_client() as client:
        resp = client.get("/formulario/1")
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/formulario/1/password")

        resp2 = client.get("/formulario/1/password")
        assert resp2.status_code == 200

        resp3 = client.post("/formulario/1/password", data={"password": "wrong"})
        assert resp3.status_code == 401
        assert b"contrase" in resp3.data.lower()

        resp4 = client.get("/formulario/1")
        assert resp4.status_code == 302
        assert resp4.headers["Location"].endswith("/formulario/1/password")

    assert len(cursor.queries) >= 3


def test_password_no_configurada(monkeypatch, caplog):
    fetchone_results = [
        assignment_dict(None),
        assignment_dict(None),
        assignment_dict(None),
        assignment_dict(None),
    ]
    cursor, _ = create_dummy(monkeypatch, fetchone_results)
    caplog.set_level("WARNING")

    with app.test_client() as client:
        resp = client.get("/formulario/1")
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/formulario/1/password")

        resp2 = client.get("/formulario/1/password")
        assert resp2.status_code == 200

        resp3 = client.post("/formulario/1/password", data={"password": "whatever"})
        assert resp3.status_code == 500
        assert "no está configurada" in resp3.get_data(as_text=True).lower()

    assert len(cursor.queries) >= 3
    assert any("no configurada" in rec.message.lower() for rec in caplog.records)
