import pytest

import reactivar
from tests.conftest import CursorFalso


class RespuestaFalsa:
    def __init__(self, codigo=200, cuerpo=None):
        self.status_code, self._cuerpo = codigo, cuerpo or {}

    def json(self):
        return self._cuerpo


@pytest.mark.parametrize("sub, esperado", [
    ("", True),                      # pausada a mano
    ("out_of_stock", True),          # se pausó sola por falta de stock
    ("out_of_stock,", True),
    ("paused_by_seller", True),       # valores reales que informa Mercado Libre
    ("out_of_stock,paused_by_seller", True),
    ("suspended", False),            # bloqueada por Mercado Libre
    ("out_of_stock,under_review", False),
    ("waiting_for_patch", False),
    (None, False),                   # todavía no se conoce el motivo
])
def test_puede_reactivarse(sub, esperado):
    assert reactivar.puede_reactivarse(sub) is esperado


def _fila(id_meli, sub, stock=5):
    return (id_meli, f"Producto {id_meli}", None, 1000, None, sub, stock)


def test_listar_ofrece_solo_las_reactivables():
    filas = [_fila("MLA1", "paused_by_seller"), _fila("MLA2", "suspended"), _fila("MLA3", "out_of_stock"), _fila("MLA4", None)]
    lista = reactivar.listar(CursorFalso(filas))
    assert [x["id_meli"] for x in lista] == ["MLA1", "MLA3"]
    assert lista[0]["motivo"] == "Pausada por vos" and lista[1]["motivo"] == "Se pausó por falta de stock"


def test_solo_se_reactivan_las_que_siguen_siendo_candidatas(monkeypatch):
    llamadas = []
    monkeypatch.setattr(reactivar.meli_http, "put", lambda url, **kw: llamadas.append((url, kw["json"])) or RespuestaFalsa(200))
    cur = CursorFalso([_fila("MLA1", "")])
    res = reactivar.reactivar(cur, 7, "token", ["MLA1", "MLA999"])          # MLA999 no está pausada/reactivable: se rechaza sin llamar a MeLi
    assert [(r["id"], r["ok"]) for r in res] == [("MLA1", True), ("MLA999", False)]
    assert llamadas == [("https://api.mercadolibre.com/items/MLA1", {"status": "active"})]
    assert any("UPDATE productos_padre SET estado = 'active'" in sql for sql, _ in cur.consultas)


def test_si_mercado_libre_rechaza_no_se_toca_la_base_y_se_informa_el_motivo(monkeypatch):
    monkeypatch.setattr(reactivar.meli_http, "put", lambda url, **kw: RespuestaFalsa(400, {"message": "Item has no stock"}))
    cur = CursorFalso([_fila("MLA1", "out_of_stock")])
    res = reactivar.reactivar(cur, 7, "token", ["MLA1"])
    assert res == [{"id": "MLA1", "ok": False, "detalle": "La publicación no tiene stock disponible: cargale unidades antes de reactivarla."}]
    assert not any("UPDATE" in sql for sql, _ in cur.consultas)


def test_un_error_de_red_en_una_no_corta_a_las_demas(monkeypatch):
    def put(url, **kw):
        if url.endswith("MLA1"):
            raise ConnectionError("sin red")
        return RespuestaFalsa(200)
    monkeypatch.setattr(reactivar.meli_http, "put", put)
    res = reactivar.reactivar(CursorFalso([_fila("MLA1", ""), _fila("MLA2", "")]), 7, "token", ["MLA1", "MLA2"])
    assert [r["ok"] for r in res] == [False, True]


def test_hay_un_tope_por_pedido_y_se_ignoran_repetidos(monkeypatch):
    monkeypatch.setattr(reactivar.meli_http, "put", lambda url, **kw: RespuestaFalsa(200))
    ids = [f"MLA{i}" for i in range(80)] + ["MLA0", "MLA0"]
    res = reactivar.reactivar(CursorFalso([_fila(i, "") for i in ids]), 7, "token", ids)
    assert len(res) == reactivar.MAXIMO_POR_PEDIDO
