import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

import app as app_module
import db
from decimal import Decimal

app = app_module.app


def _get_flashes(client):
    with client.session_transaction() as sess:
        return sess.get('_flashes', [])


class DummyCursor:
    def __init__(self, fetchone_results=None, fetchall_results=None):
        self.queries = []
        self.fetchone_results = fetchone_results or []
        self.fetchall_results = fetchall_results or []

    def execute(self, query, params=None):
        self.queries.append((query, params))

    def executemany(self, query, seq_params):
        self.queries.append((query, seq_params))

    def fetchone(self):
        return self.fetchone_results.pop(0) if self.fetchone_results else None

    def fetchall(self):
        return self.fetchall_results.pop(0) if self.fetchall_results else []

    def close(self):
        pass


class DummyConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.commit_called = 0

    def cursor(self, dictionary=True):
        return self._cursor

    def commit(self):
        self.commit_called += 1

    def close(self):
        pass


def create_dummy(monkeypatch, fetchone_results=None, fetchall_results=None):
    cursor = DummyCursor(fetchone_results=fetchone_results, fetchall_results=fetchall_results)
    conn = DummyConnection(cursor)
    monkeypatch.setattr(db, 'get_connection', lambda: conn)
    monkeypatch.setattr(app_module, 'get_connection', lambda: conn)
    return cursor, conn


def test_modal_in_admin(monkeypatch):
    create_dummy(monkeypatch, fetchone_results=[{'total': 0, 'bloqueados': 0, 'abiertos': 0}], fetchall_results=[[]])
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['is_admin'] = True
        resp = client.get('/admin')
        assert resp.status_code == 200
        assert b'id="ponderacionUniversalModal"' in resp.data
        assert b'name="valor"' in resp.data


def test_ponderacion_universal_get_not_allowed():
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['is_admin'] = True
        resp = client.get('/admin/ponderacion_universal')
        assert resp.status_code == 405


def test_post_ponderacion_universal_valido(monkeypatch):
    fetchone = [{
        'id_respuesta': 1,
        'nombre': 'N',
        'apellidos': 'A',
        'cargo': 'C',
        'dependencia': 'D',
        'formulario': 'F',
    }]
    factores_detalle = [
        {
            'id_factor': 1,
            'nombre': 'F1',
            'descripcion': 'D',
            'color': None,
            'dimension': 1,
            'valor_usuario': 3,
            'peso_admin': Decimal('5.5'),
        }
    ]
    cursor, conn = create_dummy(
        monkeypatch,
        fetchone_results=fetchone,
        fetchall_results=[
            [{'id': 1}, {'id': 2}],
            factores_detalle,
            [],
        ],
    )
    monkeypatch.setattr(app_module, 'get_factores', lambda: [{'id': 1}, {'id': 2}])
    called = {'v': False}

    def fake_invalidate():
        called['v'] = True

    monkeypatch.setattr(app_module, 'invalidate_ranking_cache', fake_invalidate)

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['is_admin'] = True
        resp = client.post('/admin/ponderacion_universal', data={'valor': '5.5'})
        assert resp.status_code == 302
        assert resp.headers['Location'].endswith('/admin')
        delete_q = [q for q, _ in cursor.queries if 'DELETE FROM ponderacion_admin' in q]
        assert delete_q
        insert_q, insert_params = cursor.queries[-1]
        assert insert_params == [
            (1, 1, Decimal('5.5')),
            (1, 2, Decimal('5.5')),
            (2, 1, Decimal('5.5')),
            (2, 2, Decimal('5.5')),
        ]
        assert conn.commit_called == 1
        assert called['v']
        resp2 = client.get('/admin/respuesta/1')
        assert resp2.status_code == 200
        assert b'value="5.5"' in resp2.data


def test_post_ponderacion_universal_invalido():
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['is_admin'] = True
        resp = client.post('/admin/ponderacion_universal', data={'valor': '11'})
        assert resp.status_code == 302
        assert resp.headers['Location'].endswith('/admin')
        flashes = _get_flashes(client)
        assert any('entre 0 y 10' in msg for _, msg in flashes)
        resp2 = client.post('/admin/ponderacion_universal', data={'valor': 'abc'})
        assert resp2.status_code == 302
        flashes = _get_flashes(client)
        assert any('num' in msg.lower() for _, msg in flashes)
