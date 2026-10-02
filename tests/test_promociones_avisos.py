"""Promociones: un rechazo de Mercado Libre se avisa en pantalla (antes se ignoraba y parecía que el descuento se había creado) y no se da por cerrado acá un
descuento que MeLi no eliminó. Sin tocar la base ni MeLi."""
import os
from urllib.parse import parse_qs, urlparse

import pytest

pytestmark = pytest.mark.db
if not os.getenv("DATABASE_URL"):
    pytest.skip("Sin DATABASE_URL: se omiten las pruebas con la app real", allow_module_level=True)

import app as aplicacion  # noqa: E402
import promociones as promos  # noqa: E402


def _llamar(monkeypatch, vista, datos, **parches):
    monkeypatch.setattr(aplicacion.token_manager, "asegurar_token_valido", lambda cuenta: "token")
    for nombre, valor in parches.items():
        monkeypatch.setattr(aplicacion.promociones_mod, nombre, valor)
    funcion = getattr(aplicacion, vista)
    while hasattr(funcion, "__wrapped__"):
        funcion = funcion.__wrapped__
    with aplicacion.app.test_request_context(method="POST", data=datos):
        aplicacion.g.usuario_id, aplicacion.g.cuenta_id = 1, 1
        return funcion(**({"id_meli": "MLA1"} if vista == "eliminar_descuento" else {}))


def _aviso(respuesta):
    q = parse_qs(urlparse(respuesta.location).query)
    return q["tipo"][0], q["msg"][0]


def test_si_mercado_libre_rechaza_el_descuento_se_avisa_y_no_se_registra(monkeypatch):
    registrados = []
    r = _llamar(monkeypatch, "crear_descuento", {"id_meli": "MLA1", "deal_price": "9000", "fecha_desde": "2026-10-02", "fecha_hasta": "2026-10-09"},
                crear_descuento_individual=lambda *a, **k: (False, "Mercado Libre no aceptó ese precio."),
                registrar_inicio_promocion=lambda *a, **k: registrados.append(a))
    assert r.location.startswith("/promociones?") and _aviso(r) == ("error", "Mercado Libre no aceptó ese precio.")
    assert registrados == []


def test_un_precio_vacio_se_avisa_en_vez_de_dar_error_500(monkeypatch):
    r = _llamar(monkeypatch, "crear_descuento", {"id_meli": "MLA1", "deal_price": "", "fecha_desde": "x", "fecha_hasta": "y"})
    assert _aviso(r)[0] == "error" and "precio" in _aviso(r)[1]


def test_si_mercado_libre_no_elimina_el_descuento_no_se_lo_da_por_cerrado(monkeypatch):
    cerrados = []
    r = _llamar(monkeypatch, "eliminar_descuento", {},
                eliminar_promocion_item=lambda *a, **k: (False, "Mercado Libre no respondió bien. Probá de nuevo en unos minutos."),
                cerrar_promocion_activa=lambda *a, **k: cerrados.append(a))
    assert _aviso(r)[0] == "error" and cerrados == []


def test_las_funciones_de_promociones_devuelven_frases_humanas(monkeypatch):
    class R:
        status_code = 403
        text = '{"message":"forbidden"}'

        def json(self):
            return {"message": "forbidden"}

    monkeypatch.setattr(promos.meli_http, "post", lambda *a, **k: R())
    monkeypatch.setattr(promos.meli_http, "delete", lambda *a, **k: R())
    ok, detalle = promos.crear_descuento_individual("t", "MLA1", 100, "2026-10-02", "2026-10-09")
    assert not ok and "reconectar" in detalle and "403" not in detalle
    ok, detalle = promos.eliminar_promocion_item("t", "MLA1", "PRICE_DISCOUNT")
    assert not ok and "reconectar" in detalle
