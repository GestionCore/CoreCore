import pytest
import requests

import meli_http


@pytest.fixture(autouse=True)
def _sin_pausa(monkeypatch):
    monkeypatch.setitem(meli_http._pausa, "hasta", 0.0)


def test_un_post_no_se_reintenta_solo():
    """Si Mercado Libre procesó el POST y falló al responder, repetirlo duplicaría la acción (una respuesta, una promoción)."""
    reintento = meli_http._sesion.get_adapter("https://api.mercadolibre.com").max_retries
    permitidos = {m.upper() for m in (getattr(reintento, "allowed_methods", None) or getattr(reintento, "method_whitelist", None))}
    assert "POST" not in permitidos and {"GET", "PUT", "DELETE"} <= permitidos


def test_si_mercado_libre_sigue_rechazando_todos_esperan(monkeypatch):
    llamadas = []

    def rechaza(url, **kw):
        llamadas.append(url)
        raise requests.exceptions.RetryError("too many 429 error responses")

    monkeypatch.setattr(meli_http._sesion, "get", rechaza)
    esperas = []
    monkeypatch.setattr(meli_http.time, "sleep", lambda s: esperas.append(s))
    with pytest.raises(requests.exceptions.RetryError):
        meli_http.get("https://api.mercadolibre.com/items/1")
    assert esperas == []                                   # la primera falla no espera: todavía no había pausa
    with pytest.raises(requests.exceptions.RetryError):
        meli_http.get("https://api.mercadolibre.com/items/2")
    assert len(esperas) == 1 and 0 < esperas[0] <= meli_http.PAUSA_TRAS_RECHAZO   # el segundo pedido (de cualquier hilo) espera antes de insistir


def test_sin_rechazos_no_hay_pausa(monkeypatch):
    class Ok:
        status_code = 200

    monkeypatch.setattr(meli_http._sesion, "get", lambda url, **kw: Ok())
    esperas = []
    monkeypatch.setattr(meli_http.time, "sleep", lambda s: esperas.append(s))
    assert meli_http.get("https://api.mercadolibre.com/items/1").status_code == 200 and esperas == []
