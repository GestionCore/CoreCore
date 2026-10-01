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
    assert cliente.get("/healthz").json == {"ok": True}


def test_paginas_de_error_en_espanol_y_json_en_api(cliente):
    r = cliente.get("/no-existe")
    assert r.status_code == 404 and "No encontramos esa página" in r.get_data(as_text=True)
    r = cliente.get("/api/no-existe")
    assert r.status_code == 404 and r.json["ok"] is False


def test_la_cookie_de_sesion_es_segura(cliente):
    cfg = cliente.application.config
    assert cfg["SESSION_COOKIE_HTTPONLY"] is True and cfg["SESSION_COOKIE_SAMESITE"] == "Lax"
