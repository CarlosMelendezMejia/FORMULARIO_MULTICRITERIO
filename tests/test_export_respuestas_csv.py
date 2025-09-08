import os
import sys

import pytest


sys.path.append(os.path.dirname(os.path.dirname(__file__)))

import app as app_module
import db


app = app_module.app


class DummyCursor:
    def __init__(self, rows):
        self.rows = rows
        self.queries = []

    def execute(self, query, params=None):
        self.queries.append((query, params))

    def fetchall(self):
        return self.rows

    def close(self):
        pass


class DummyConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self, dictionary=True):
        return self._cursor

    def close(self):
        pass


def create_dummy(monkeypatch, rows):
    cursor = DummyCursor(rows)
    conn = DummyConnection(cursor)
    monkeypatch.setattr(db, "get_connection", lambda: conn)
    monkeypatch.setattr(app_module, "get_connection", lambda: conn)
    return cursor


def test_export_respuestas_csv(monkeypatch):
    rows = [
        {
            "formulario": "Formulario 01",
            "nombre": "Juan",
            "apellidos": "Perez",
            "dependencia": "Dep",
            "cargo": "Cargo",
            "factor_1": 5,
            "factor_2": 3,
        }
    ]
    create_dummy(monkeypatch, rows)
    monkeypatch.setattr(app_module, "get_factores", lambda: [{"id": 1}, {"id": 2}])

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["is_admin"] = True
        resp = client.get("/admin/export_csv")
        assert resp.status_code == 200
        content = resp.data.decode("utf-8-sig")
        lines = content.strip().splitlines()
        assert (
            lines[0]
            == "formulario,nombre,apellidos,dependencia,cargo,factor_1,factor_2"
        )
        assert lines[1] == "Formulario 01,Juan,Perez,Dep,Cargo,5,3"

