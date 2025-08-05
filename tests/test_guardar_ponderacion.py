import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

import app as app_module

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
