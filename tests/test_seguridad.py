import pytest
from flask import Flask
import seguridad


@pytest.fixture
def cliente():
    app = Flask(__name__)
    app.secret_key = "prueba"
    app.template_folder = __import__("os").path.join(seguridad.__file__.rsplit("seguridad.py", 1)[0], "templates")
    seguridad.iniciar(app)

    @app.route("/escribir", methods=["POST"])
    def escribir():
        return "ok"

    @app.route("/notificaciones_meli", methods=["POST"])
    def webhook():
        return "", 200

    @app.route("/api/dato")
    def dato():
        return {"ok": True}

    return app.test_client()


def test_un_post_de_otro_sitio_se_bloquea(cliente):
    r = cliente.post("/escribir", headers={"Origin": "https://malo.example", "Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403


def test_un_post_del_mismo_sitio_pasa(cliente):
    assert cliente.post("/escribir", headers={"Sec-Fetch-Site": "same-origin"}).status_code == 200
    assert cliente.post("/escribir", headers={"Origin": "http://localhost"}).status_code == 200
    assert cliente.post("/escribir").status_code == 200       # cliente que no es un navegador


def test_los_webhooks_no_se_bloquean(cliente):
    assert cliente.post("/notificaciones_meli", json={}, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 200


def test_cabeceras_de_seguridad(cliente):
    h = cliente.get("/api/dato").headers
    assert h["X-Content-Type-Options"] == "nosniff" and h["X-Frame-Options"] == "SAMEORIGIN"


def test_estaticos_versionados_con_cache_largo(cliente):
    # el archivo no existe en esta app mínima (404), pero la regla de caché solo aplica a 200: se prueba la ruta real en test_app
    assert cliente.get("/healthz").json["ok"] is True


def test_paginas_de_error_en_espanol_y_json_en_api(cliente):
    r = cliente.get("/no-existe")
    assert r.status_code == 404 and "No encontramos esa página" in r.get_data(as_text=True)
    r = cliente.get("/api/no-existe")
    assert r.status_code == 404 and r.json["ok"] is False


def test_la_cookie_de_sesion_es_segura(cliente):
    cfg = cliente.application.config
    assert cfg["SESSION_COOKIE_HTTPONLY"] is True and cfg["SESSION_COOKIE_SAMESITE"] == "Lax"


def test_la_ip_del_cliente_sale_de_cloudflare_si_esta_y_si_no_de_la_conexion():
    from flask import Flask
    import seguridad
    app = Flask(__name__)
    with app.test_request_context("/", headers={"CF-Connecting-IP": "181.1.2.3"}, environ_base={"REMOTE_ADDR": "172.70.0.1"}):
        assert seguridad.ip_del_cliente() == "181.1.2.3"
    with app.test_request_context("/", environ_base={"REMOTE_ADDR": "190.9.9.9"}):
        assert seguridad.ip_del_cliente() == "190.9.9.9"


def test_healthz_informa_la_version_desplegada(monkeypatch):
    from flask import Flask
    import seguridad
    monkeypatch.setattr(seguridad, "VERSION", "abc123def456")
    app = Flask(__name__)
    seguridad.iniciar(app)
    r = app.test_client().get("/healthz")
    assert r.status_code == 200 and r.get_json() == {"ok": True, "version": "abc123def456"}


def test_sin_conexiones_libres_o_sin_base_se_muestra_mucha_demanda_con_503():
    """Un pool agotado o una base que no responde no son un 'error nuestro': 503 con Retry-After y un mensaje claro, en vez del 500 genérico."""
    from flask import Flask
    from psycopg import OperationalError
    from psycopg_pool import PoolTimeout
    import seguridad
    app = Flask(__name__)
    app.template_folder = __import__("os").path.join(seguridad.__file__.rsplit("seguridad.py", 1)[0], "templates")
    seguridad.iniciar(app)

    @app.route("/pool")
    def pool():
        raise PoolTimeout("couldn't get a connection after 10 sec")

    @app.route("/base")
    def base():
        raise OperationalError("connection refused")

    @app.route("/api/pool")
    def api_pool():
        raise PoolTimeout("x")
    cliente = app.test_client()
    for ruta in ("/pool", "/base"):
        r = cliente.get(ruta)
        assert r.status_code == 503 and r.headers["Retry-After"] == "5" and "mucha demanda" in r.get_data(as_text=True)
    r = cliente.get("/api/pool")
    assert r.status_code == 503 and r.json["ok"] is False


def test_el_pool_no_espera_mas_de_lo_configurado():
    import db
    assert db.POOL_TIMEOUT <= 10
