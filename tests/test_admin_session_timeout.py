import os
import sys
from datetime import datetime, timedelta

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

import app as app_module

app = app_module.app


def test_admin_session_times_out(monkeypatch):
    app.permanent_session_lifetime = timedelta(seconds=1)
    with app.test_client() as client:
        resp = client.post(
            "/admin/login", data={"password": app_module.ADMIN_PASSWORD}
        )
        assert resp.status_code == 302
        with client.session_transaction() as sess:
            assert sess.get("is_admin")
            expired = datetime.utcnow() - app.permanent_session_lifetime - timedelta(seconds=1)
            sess["last_activity"] = expired.timestamp()
        resp = client.get("/admin/logout")
        assert resp.status_code == 302
        assert "/admin/login" in resp.headers["Location"]
        with client.session_transaction() as sess:
            assert "is_admin" not in sess
