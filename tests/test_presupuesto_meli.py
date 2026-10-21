"""
Presupuesto de un pedido web (meli_http): gunicorn corta un pedido a los 60 s y un GET a Mercado Libre con 3 reintentos podía tardar ~70 s: el pedido moría con un error en vez de mostrar «Mercado Libre no respondió».
Dentro de un pedido web cada llamada recorta su timeout a lo que queda de 45 s, no reintenta si queda poco y, agotado, falla sin llamar; fuera de un pedido web (sincronizaciones, tareas) nada cambia.
"""
import time

import pytest
import requests
from flask import Flask, g

import meli_http


@pytest.fixture
def app():
    return Flask(__name__)


def _pedido(app, segundos_transcurridos):
    contexto = app.test_request_context()
    contexto.push()
    g.inicio_pedido = time.perf_counter() - segundos_transcurridos
    return contexto


def test_fuera_de_un_pedido_web_no_hay_tope():
    assert meli_http.presupuesto_restante() is None
    assert meli_http.ajustar_timeout(15) == 15
    assert meli_http.ajustar_timeout((3, 15)) == (3, 15)


def test_con_holgura_el_timeout_se_reparte_entre_los_intentos(app):
    contexto = _pedido(app, 10)                       # quedan ~35 s: caben 4 intentos de ~8,7 s
    try:
        resto = meli_http.presupuesto_restante()
        assert 34 < resto <= 35
        assert meli_http.ajustar_timeout(15) == pytest.approx(resto / 4, abs=0.5)
        assert meli_http.ajustar_timeout(3) == 3          # un timeout ya chico no se agranda
    finally:
        contexto.pop()


def test_con_poco_presupuesto_un_solo_intento_que_usa_lo_que_queda(app):
    contexto = _pedido(app, 37)                       # quedan ~8 s (< 12): sin reintentos
    try:
        assert meli_http.ajustar_timeout(15) == pytest.approx(meli_http.presupuesto_restante(), abs=0.5)
        assert meli_http.ajustar_timeout((3, 15))[0] == 3 and meli_http.ajustar_timeout((3, 15))[1] < 9
    finally:
        contexto.pop()


def test_agotado_el_presupuesto_falla_sin_llamar_a_mercado_libre(app, monkeypatch):
    llamadas = []
    monkeypatch.setattr(meli_http._sesion, "get", lambda *a, **k: llamadas.append("con reintentos"))
    monkeypatch.setattr(meli_http._sesion_sin_reintentos, "get", lambda *a, **k: llamadas.append("sin reintentos"))
    monkeypatch.setitem(meli_http._pausa, "hasta", 0.0)
    contexto = _pedido(app, 44)                       # quedan ~1 s
    try:
        with pytest.raises(requests.exceptions.Timeout):
            meli_http.get("https://api.mercadolibre.com/x")
    finally:
        contexto.pop()
    assert llamadas == []


def test_con_poco_presupuesto_usa_la_sesion_sin_reintentos(app, monkeypatch):
    usadas = []

    class Resp:
        status_code, headers = 200, {}

    monkeypatch.setattr(meli_http._sesion, "get", lambda url, **k: usadas.append(("con", k["timeout"])) or Resp())
    monkeypatch.setattr(meli_http._sesion_sin_reintentos, "get", lambda url, **k: usadas.append(("sin", k["timeout"])) or Resp())
    monkeypatch.setitem(meli_http._pausa, "hasta", 0.0)
    contexto = _pedido(app, 40)                       # quedan ~5 s
    try:
        meli_http.get("https://api.mercadolibre.com/x")
    finally:
        contexto.pop()
    contexto = _pedido(app, 5)                        # quedan ~40 s
    try:
        meli_http.get("https://api.mercadolibre.com/x")
    finally:
        contexto.pop()
    assert [u[0] for u in usadas] == ["sin", "con"] and usadas[0][1] < 6 and usadas[1][1] < 11


def test_fuera_de_un_pedido_web_se_usa_la_sesion_con_reintentos_y_el_timeout_de_siempre(monkeypatch):
    usadas = []

    class Resp:
        status_code, headers = 200, {}

    monkeypatch.setattr(meli_http._sesion, "get", lambda url, **k: usadas.append(k["timeout"]) or Resp())
    monkeypatch.setitem(meli_http._pausa, "hasta", 0.0)
    meli_http.get("https://api.mercadolibre.com/x")
    assert usadas == [15]


def test_la_pausa_tras_un_rechazo_no_se_come_el_presupuesto_de_un_pedido_web(app, monkeypatch):
    dormidos = []
    monkeypatch.setattr(meli_http.time, "sleep", lambda s: dormidos.append(s))
    monkeypatch.setitem(meli_http._pausa, "hasta", time.monotonic() + 20)
    contexto = _pedido(app, 30)                       # quedan ~15 s: la pausa de 20 s se recorta a ~5 s
    try:
        meli_http._respetar_pausa()
    finally:
        contexto.pop()
    assert dormidos and dormidos[0] <= 5.5


def test_llamar_api_meli_tambien_respeta_el_presupuesto(app, monkeypatch):
    from auth import token_manager
    pedidos = []

    class Resp:
        status_code, headers = 200, {}

    monkeypatch.setattr(token_manager, "asegurar_token_valido", lambda cuenta_id: "token")
    monkeypatch.setattr(token_manager.requests, "request", lambda metodo, url, **k: pedidos.append(k["timeout"]) or Resp())
    monkeypatch.setitem(meli_http._pausa, "hasta", 0.0)
    contexto = _pedido(app, 25)                       # quedan ~20 s
    try:
        token_manager.llamar_api_meli(1, "get", "https://api.mercadolibre.com/x")
        assert pedidos and pedidos[0] <= 5.5
        g.inicio_pedido = time.perf_counter() - 44
        with pytest.raises(requests.exceptions.Timeout):
            token_manager.llamar_api_meli(1, "get", "https://api.mercadolibre.com/x")
    finally:
        contexto.pop()
    assert len(pedidos) == 1                          # el segundo ni se envió
