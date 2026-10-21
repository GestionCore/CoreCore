"""
Código de incidente: un error del lado del servidor (500, 503) muestra un código corto («A3F9C1») en la página, lo escribe en el registro y lo deja como etiqueta de Sentry, así «me dio error» se puede ubicar.
Un 404 o un 403 no lo lleva (no hay nada que buscar en los registros). Las rutas /api/ lo devuelven en el JSON.
"""
import logging
import os
import re

import pytest
from flask import Flask

import seguridad


@pytest.fixture
def cliente():
    app = Flask(__name__)
    app.secret_key = "prueba"
    app.template_folder = os.path.join(os.path.dirname(os.path.abspath(seguridad.__file__)), "templates")
    seguridad.iniciar(app)

    @app.route("/rompe")
    def rompe():
        raise RuntimeError("falla de prueba")

    @app.route("/api/rompe")
    def api_rompe():
        raise RuntimeError("falla de prueba")

    return app.test_client()


def test_un_error_500_muestra_un_codigo_de_incidente_y_lo_deja_en_el_registro(cliente, caplog):
    with caplog.at_level(logging.ERROR, logger="corelux.seguridad"):
        r = cliente.get("/rompe")
    assert r.status_code == 500
    html = r.get_data(as_text=True)
    codigo = re.search(r'class="incidente">[^<]*<b>([0-9A-F]{6})</b>', html)
    assert codigo, "la página de error no muestra el código"
    assert any(f"[Incidente {codigo.group(1)}]" in m for m in caplog.messages), caplog.messages          # el mismo código está en el registro


def test_cada_error_tiene_su_propio_codigo(cliente):
    a = re.search(r"<b>([0-9A-F]{6})</b>", cliente.get("/rompe").get_data(as_text=True)).group(1)
    b = re.search(r"<b>([0-9A-F]{6})</b>", cliente.get("/rompe").get_data(as_text=True)).group(1)
    assert a != b


def test_un_404_no_lleva_codigo(cliente):
    r = cliente.get("/no-existe")
    assert r.status_code == 404 and 'class="incidente"' not in r.get_data(as_text=True)                  # (la regla de estilo está siempre en la página; el párrafo, solo con código)


def test_las_rutas_api_devuelven_el_codigo_en_el_json(cliente):
    r = cliente.get("/api/rompe")
    assert r.status_code == 500
    cuerpo = r.get_json()
    assert cuerpo["ok"] is False and re.fullmatch(r"[0-9A-F]{6}", cuerpo["incidente"])
    assert f"Código: {cuerpo['incidente']}." in cuerpo["detalle"]                                       # lo que la pantalla le muestra a la persona lo lleva
    assert "incidente" not in cliente.get("/api/no-existe").get_json()                                  # un 404 de API tampoco
