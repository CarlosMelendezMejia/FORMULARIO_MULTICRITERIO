import os
import sys
import pytest

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

import db
import app as app_module

app = app_module.app

class DummyCursor:
    def __init__(self, fetchall_results=None):
        self.queries = []
        self.fetchall_results = fetchall_results or []

    def execute(self, query, params=None):
        self.queries.append((query, params))

    def fetchall(self):
        return self.fetchall_results.pop(0)

    def close(self):
        pass

class DummyConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.commit_called = 0
        self.start_transaction_called = False

    def cursor(self, dictionary=True):
        return self._cursor

    def start_transaction(self):
        self.start_transaction_called = True

    def commit(self):
        self.commit_called += 1

    def rollback(self):
        pass

    def close(self):
        pass


def create_dummy(monkeypatch, fetchall_results=None):
    cursor = DummyCursor(fetchall_results=fetchall_results)
    conn = DummyConnection(cursor)
    monkeypatch.setattr(db, "get_connection", lambda: conn)
    monkeypatch.setattr(app_module, "get_connection", lambda: conn)
    return cursor, conn


def test_post_factores_incluye_color_en_queries(monkeypatch):
    existing = [{"id": 1, "nombre": "F1", "descripcion": "D1", "color": "#111111"}]
    cursor, conn = create_dummy(monkeypatch, fetchall_results=[existing])

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["is_admin"] = True
        resp = client.post(
            "/admin/factores",
            data={
                "nombre_1": "Factor A",
                "descripcion_1": "Desc A",
                "color_1": "#ff0000",
                "nuevo_nombre": "Factor B",
                "nuevo_descripcion": "Desc B",
                "nuevo_color": "#00ff00",
            },
        )
        assert resp.status_code == 302

    assert cursor.queries == [
        ("SELECT * FROM factor ORDER BY id", None),
        (
            "UPDATE factor SET nombre=%s, descripcion=%s, color=%s, dimension=%s WHERE id=%s",
            ("Factor A", "Desc A", "#ff0000", 1, 1),
        ),
        (
            "INSERT INTO factor (nombre, descripcion, color, dimension) VALUES (%s, %s, %s, %s)",
            ("Factor B", "Desc B", "#00ff00", 1),
        ),
    ]
    assert conn.start_transaction_called
    assert conn.commit_called == 1
