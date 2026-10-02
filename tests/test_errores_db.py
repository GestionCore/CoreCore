"""Con la app real: si no hay conexiones libres, la persona ve 'mucha demanda' (503), y esa página de error no necesita la base. Se omite sin DATABASE_URL."""
import os

import pytest

pytestmark = pytest.mark.db
if not os.getenv("DATABASE_URL"):
    pytest.skip("Sin DATABASE_URL: se omiten las pruebas con la app real", allow_module_level=True)

from psycopg_pool import PoolTimeout  # noqa: E402

import app as aplicacion  # noqa: E402
import db  # noqa: E402


def _sin_conexiones(*a, **k):
    raise PoolTimeout("couldn't get a connection after 10.00 sec")


def test_con_el_pool_agotado_la_pantalla_da_503_y_no_un_500(monkeypatch):
    monkeypatch.setattr(db, "conexion_usuario", _sin_conexiones)
    cliente = aplicacion.app.test_client()
    with cliente.session_transaction() as s:
        s["usuario_id"], s["cuenta_id"] = 1, 1
    r = cliente.get("/stock")
    assert r.status_code == 503 and r.headers["Retry-After"] == "5" and "mucha demanda" in r.get_data(as_text=True)


def test_una_api_con_el_pool_agotado_responde_json(monkeypatch):
    monkeypatch.setattr(db, "conexion_usuario", _sin_conexiones)
    cliente = aplicacion.app.test_client()
    with cliente.session_transaction() as s:
        s["usuario_id"], s["cuenta_id"] = 1, 1
    r = cliente.get("/api/ticker")
    assert r.status_code == 503 and r.get_json()["ok"] is False
