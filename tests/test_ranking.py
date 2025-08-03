import os
import types
import pytest

import sys
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

import db
import app as app_module

app = app_module.app
RANKING_CACHE = app_module.RANKING_CACHE

class DummyCursor:
    def __init__(self):
        self.queries = []
        self.fetchone_results = [
            {"total": 1},  # total_asignados
            {"total": 1},  # total_respuestas
        ]
        self.fetchall_results = [
            [],  # incompletas_rows
            [{"nombre": "Factor X", "total": 5}],  # ranking
        ]

    def execute(self, query, params=None):
        self.queries.append((query, params))

    def fetchone(self):
        return self.fetchone_results.pop(0)

    def fetchall(self):
        return self.fetchall_results.pop(0)

    def close(self):
        pass

class DummyConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self, dictionary=True):
        return self._cursor

    def close(self):
        pass


def test_vista_ranking_parametrized(monkeypatch):
    cursor = DummyCursor()
    conn = DummyConnection(cursor)
    monkeypatch.setattr(db, "get_connection", lambda: conn)
    monkeypatch.setattr(app_module, "get_connection", lambda: conn)

    # reset cache
    RANKING_CACHE["data"] = None
    RANKING_CACHE["timestamp"] = 0
    RANKING_CACHE["incompletas"] = None

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["is_admin"] = True
        resp = client.get("/admin/ranking")
        assert resp.status_code == 200
        assert b"Factor X" in resp.data

    # verify queries used placeholders
    # queries: total_asignados, total_respuestas, incompletas, ranking
    incompletas_query, incompletas_params = cursor.queries[2]
    ranking_query, ranking_params = cursor.queries[3]
    assert "HAVING COUNT(p.id_factor) < %s" in incompletas_query
    assert incompletas_params == (10,)
    assert "HAVING COUNT(pa2.id_factor) < %s" in ranking_query
    assert ranking_params == (10,)
