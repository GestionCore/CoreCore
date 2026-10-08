"""
Política de seguridad de contenido (CSP) estricta: sin 'unsafe-inline' en script-src, con un nonce distinto en cada pedido. Se activa por etapas (CSP_MODO: prueba / estricta / actual).
Lo que la hace posible: ninguna plantilla tiene un manejador escrito en el HTML ni una URL javascript: (test_correcciones_frontend) y todo <script> inline lleva el nonce (acá).
"""
import glob
import logging
import os
import re

import pytest

import seguridad

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT_INLINE = re.compile(r"<script(?P<atributos>[^>]*)>")


def test_todo_script_inline_lleva_el_nonce():
    """Un <script> sin src y sin nonce lo bloquearía la política estricta: la pantalla quedaría sin funcionar."""
    sin_nonce = []
    for ruta in glob.glob(os.path.join(RAIZ, "templates", "*.html")):
        for m in SCRIPT_INLINE.finditer(open(ruta, encoding="utf-8").read()):
            atributos = m.group("atributos")
            if "src=" in atributos or "application/json" in atributos or "application/ld+json" in atributos:
                continue                                              # uno externo es del propio sitio; un bloque de datos no se ejecuta
            if 'nonce="{{ csp_nonce }}"' not in atributos:
                sin_nonce.append(os.path.basename(ruta))
    assert not sin_nonce, f"<script> inline sin nonce=\"{{{{ csp_nonce }}}}\": {sorted(set(sin_nonce))}"


@pytest.fixture
def cliente():
    import app as modulo_app
    return modulo_app.app.test_client()


def _nonce_de(cabecera):
    return re.search(r"'nonce-([\w-]+)'", cabecera).group(1)


def test_en_modo_prueba_se_aplica_la_politica_de_siempre_y_la_estricta_va_en_report_only(cliente, monkeypatch):
    monkeypatch.setattr(seguridad, "CSP_MODO", "prueba")
    r = cliente.get("/planes")
    vigente, prueba = r.headers["Content-Security-Policy"], r.headers["Content-Security-Policy-Report-Only"]
    assert "script-src 'self' 'unsafe-inline'" in vigente
    assert "'unsafe-inline'" not in prueba.split("style-src")[0] and "report-uri /csp-report" in prueba
    # el nonce de la cabecera es el mismo que llevan los <script> inline de ESA página
    nonce = _nonce_de(prueba)
    paginas = r.get_data(as_text=True)
    assert f'<script nonce="{nonce}">' in paginas
    assert 'nonce="{{' not in paginas                                  # no quedó sin renderizar


def test_cada_pedido_trae_un_nonce_distinto(cliente, monkeypatch):
    monkeypatch.setattr(seguridad, "CSP_MODO", "estricta")
    nonces = {_nonce_de(cliente.get("/planes").headers["Content-Security-Policy"]) for _ in range(5)}
    assert len(nonces) == 5 and all(len(n) >= 16 for n in nonces)


def test_en_modo_estricta_script_src_no_admite_inline_y_no_hay_report_only(cliente, monkeypatch):
    monkeypatch.setattr(seguridad, "CSP_MODO", "estricta")
    r = cliente.get("/planes")
    politica = r.headers["Content-Security-Policy"]
    script_src = re.search(r"script-src ([^;]*)", politica).group(1)
    assert "'unsafe-inline'" not in script_src and "'self'" in script_src and "'nonce-" in script_src
    assert "Content-Security-Policy-Report-Only" not in r.headers
    assert "object-src 'none'" in politica and "frame-ancestors 'self'" in politica and "default-src 'self'" in politica


def test_en_modo_actual_se_vuelve_a_la_politica_de_siempre_sin_nonce(cliente, monkeypatch):
    monkeypatch.setattr(seguridad, "CSP_MODO", "actual")
    r = cliente.get("/planes")
    assert r.headers["Content-Security-Policy"] == seguridad.CSP and "Content-Security-Policy-Report-Only" not in r.headers


def test_un_modo_desconocido_cae_en_prueba(monkeypatch):
    monkeypatch.setenv("CSP_MODO", "cualquier-cosa")
    import importlib
    recargado = importlib.reload(seguridad)
    try:
        assert recargado.CSP_MODO == "prueba"
    finally:
        monkeypatch.delenv("CSP_MODO", raising=False)
        importlib.reload(seguridad)


def test_las_paginas_de_error_tambien_llevan_la_politica(cliente, monkeypatch):
    monkeypatch.setattr(seguridad, "CSP_MODO", "estricta")
    r = cliente.get("/esta-pagina-no-existe")
    assert r.status_code == 404 and "'nonce-" in r.headers["Content-Security-Policy"]


def test_el_receptor_de_reportes_acepta_lo_que_manda_el_navegador_y_lo_deja_en_el_log(cliente, caplog):
    seguridad._reportes_csp.update(desde=0.0, cuenta=0)
    informe = {"csp-report": {"violated-directive": "script-src-elem", "blocked-uri": "inline", "document-uri": "https://corelux.app/costos", "line-number": 12, "script-sample": "x" * 500}}
    with caplog.at_level(logging.WARNING, logger="corelux.seguridad"):
        r = cliente.post("/csp-report", data=__import__("json").dumps(informe), content_type="application/csp-report")      # sin Origin: lo manda el navegador
    assert r.status_code == 204
    assert "[CSP] violación" in caplog.text and "script-src-elem" in caplog.text and "document-uri=https://corelux.app/costos" in caplog.text
    assert "x" * 200 not in caplog.text                                # el fragmento se corta: no se llena el log


def test_el_receptor_tiene_tope_por_minuto_y_no_revienta_con_basura(cliente, caplog):
    seguridad._reportes_csp.update(desde=0.0, cuenta=0)
    with caplog.at_level(logging.WARNING, logger="corelux.seguridad"):
        for _ in range(seguridad.MAX_REPORTES_CSP_POR_MINUTO + 15):
            assert cliente.post("/csp-report", data="no es json", content_type="application/csp-report").status_code == 204
        assert cliente.post("/csp-report", data='[1,2]', content_type="application/json").status_code == 204
    assert caplog.text.count("[CSP] violación") <= seguridad.MAX_REPORTES_CSP_POR_MINUTO
    seguridad._reportes_csp.update(desde=0.0, cuenta=0)
