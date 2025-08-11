import os
import sys

from flask import abort

# Ensure we can import the application module
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

import app as app_module

app = app_module.app


@app.route("/trigger-400")
def trigger_400():
    abort(400)


@app.route("/trigger-500")
def trigger_500():
    raise Exception("boom")


def test_error_handler_404():
    with app.test_client() as client:
        resp = client.get("/ruta-inexistente")
        assert resp.status_code == 404
        assert b"Error 404" in resp.data


def test_error_handler_400():
    with app.test_client() as client:
        resp = client.get("/trigger-400")
        assert resp.status_code == 400
        assert b"Error 400" in resp.data


def test_error_handler_500():
    with app.test_client() as client:
        resp = client.get("/trigger-500")
        assert resp.status_code == 500
        assert b"Error 500" in resp.data

