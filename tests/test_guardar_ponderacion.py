import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

import db
import app as app_module
from decimal import Decimal

app = app_module.app


def _get_flashes(client):
    with client.session_transaction() as sess:
        return sess.get('_flashes', [])


def test_guardar_ponderacion_sin_id_respuesta():
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['is_admin'] = True
        resp = client.post('/admin/ponderar', data={'ponderacion_1': '5'})
        assert resp.status_code == 302
        assert resp.headers['Location'].endswith('/admin')
        flashes = _get_flashes(client)
        assert any('Falta el identificador de la respuesta.' in msg for _, msg in flashes)


def test_guardar_ponderacion_id_no_numerico():
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['is_admin'] = True
        resp = client.post('/admin/ponderar', data={'id_respuesta': 'abc', 'ponderacion_1': '5'})
        assert resp.status_code == 302
        assert resp.headers['Location'].endswith('/admin')
        flashes = _get_flashes(client)
        assert any('El identificador de la respuesta debe ser un número entero.' in msg for _, msg in flashes)


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


def test_guardar_ponderacion_ignora_global(monkeypatch):
    all_factors = [{'id': 1}, {'id': 2}]
    detalle_factors = [
        {
            'id_factor': 2,
            'nombre': 'F2',
            'descripcion': 'D',
            'valor_usuario': 3,
            'peso_admin': Decimal("8.0"),
        }
    ]
    fetchone = [{'id_respuesta': 1, 'nombre': 'N', 'apellidos': 'A', 'formulario': 'Form'}]
    cursor, conn = create_dummy(
        monkeypatch,
        fetchone_results=fetchone,
        fetchall_results=[all_factors, detalle_factors, []],
    )

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['is_admin'] = True
        data = {
            'id_respuesta': '1',
            'ponderacion_global': '7',
            'ponderacion_2': '8',
        }
        resp = client.post('/admin/ponderar', data=data)
        assert resp.status_code == 302
        # First query selects factors, second deletes previous rows
        delete_q, delete_params = cursor.queries[1]
        assert 'DELETE FROM ponderacion_admin WHERE id_respuesta = %s' in delete_q
        assert delete_params == (1,)
        insert_q, insert_params = cursor.queries[2]
        assert insert_params == [
            (1, 1, Decimal("0.0")),
            (1, 2, Decimal("8.0")),
        ]
        assert conn.commit_called == 1

        resp2 = client.get('/admin/respuesta/1')
        assert resp2.status_code == 200
        assert b'value="8.0"' in resp2.data


def test_detalle_respuesta_no_filtra_bloqueadas(monkeypatch):
    """El administrador puede ver el detalle incluso si la respuesta está bloqueada."""
    factors = [
        {
            'id_factor': 1,
            'nombre': 'F1',
            'descripcion': 'Desc',
            'valor_usuario': 5,
            'peso_admin': '',
        }
    ]
    fetchone = [{'id_respuesta': 5, 'nombre': 'N', 'apellidos': 'A', 'formulario': 'Form'}]
    cursor, conn = create_dummy(
        monkeypatch,
        fetchone_results=fetchone,
        fetchall_results=[factors, []],
    )

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['is_admin'] = True
        resp = client.get('/admin/respuesta/5')
        assert resp.status_code == 200
        # La consulta no debe filtrar por "bloqueado = 0"
        assert 'bloqueado = 0' not in cursor.queries[0][0].lower()
        # Se muestra el campo de ponderación para el factor
        assert b'name="ponderacion_1"' in resp.data


def test_guardar_ponderacion_error_db(monkeypatch):
    class ErrorConnection:
        def __init__(self, cursor):
            self._cursor = cursor
            self.rollback_called = 0

        def cursor(self, dictionary=True):
            return self._cursor

        def commit(self):
            raise Exception("db fail")

        def rollback(self):
            self.rollback_called += 1

        def close(self):
            pass

    cursor = DummyCursor()
    conn = ErrorConnection(cursor)
    monkeypatch.setattr(db, 'get_connection', lambda: conn)
    monkeypatch.setattr(app_module, 'get_connection', lambda: conn)
    monkeypatch.setattr(app_module, 'get_factores', lambda: [{'id': 1}])
    app_module.invalidate_factores_cache()

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['is_admin'] = True
        resp = client.post(
            '/admin/ponderar', data={'id_respuesta': '1', 'ponderacion_1': '5'}
        )
        assert resp.status_code == 302
        assert resp.headers['Location'].endswith('/admin/respuesta/1')
        flashes = _get_flashes(client)
        assert any(
            'Error al guardar las ponderaciones' in msg for _, msg in flashes
        )
        assert conn.rollback_called == 1
