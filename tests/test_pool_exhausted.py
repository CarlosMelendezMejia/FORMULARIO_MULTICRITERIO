import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

import app as app_module
import db
from db import PoolExhaustedError


app = app_module.app


@app.route("/trigger-pool")
def trigger_pool():
    app_module.get_db()
    return "ok"


def test_pool_exhausted_returns_503(monkeypatch):
    def fake_get_connection():
        raise PoolExhaustedError()

    monkeypatch.setattr(app_module, "get_connection", fake_get_connection)
    monkeypatch.setattr(db, "get_connection", fake_get_connection)

    with app.test_client() as client:
        resp = client.get("/trigger-pool")
        assert resp.status_code == 503
        assert b"base de datos" in resp.data.lower()

