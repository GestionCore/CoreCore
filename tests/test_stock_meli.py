import contextlib

import pytest

import stock_meli
import ventas_manuales


class Resp:
    def __init__(self, codigo=200, cuerpo=None):
        self.status_code, self._c = codigo, cuerpo or {}

    def json(self):
        return self._c


@pytest.mark.parametrize("variantes, esperado", [
    (["MLA1_unica"], {"available_quantity": 4}),                                   # sin variaciones: va a la publicación (no a una variación inexistente)
    ([], {"available_quantity": 4}),
    (["174839201"], {"variations": [{"id": 174839201, "available_quantity": 4}]}),  # una variación real
    (["111", "222"], None),                                                        # varias: no se decide sola
])
def test_cuerpo_del_cambio_de_stock(variantes, esperado):
    assert stock_meli.payload_para_stock(variantes, 4) == esperado


def test_se_descuenta_de_lo_que_mercado_libre_tiene_ahora():
    enviados = []
    ok, _, nuevo = stock_meli.ajustar_en_meli(
        "tok", "MLA1", "MLA1_unica", -2,
        obtener=lambda url, **kw: Resp(200, {"available_quantity": 5}),
        escribir=lambda url, **kw: enviados.append(kw["json"]) or Resp(200))
    assert (ok, nuevo) == (True, 3) and enviados == [{"available_quantity": 3}]


def test_con_variaciones_se_ajusta_la_correcta_y_nunca_baja_de_cero():
    enviados = []
    ok, _, nuevo = stock_meli.ajustar_en_meli(
        "tok", "MLA1", "222", -5,
        obtener=lambda url, **kw: Resp(200, {"available_quantity": 9, "variations": [{"id": 111, "available_quantity": 4}, {"id": 222, "available_quantity": 2}]}),
        escribir=lambda url, **kw: enviados.append(kw["json"]) or Resp(200))
    assert (ok, nuevo) == (True, 0) and enviados == [{"variations": [{"id": 222, "available_quantity": 0}]}]


@pytest.mark.parametrize("obtener, escribir, texto", [
    (lambda u, **k: Resp(500), None, "consultar"),
    (lambda u, **k: Resp(200, {"available_quantity": 3, "variations": [{"id": 1, "available_quantity": 1}]}), None, "ya no existe"),
    (lambda u, **k: Resp(200, {"available_quantity": 3}), lambda u, **k: Resp(400), "no aceptó"),
    (lambda u, **k: (_ for _ in ()).throw(TimeoutError("lento")), None, "conectar"),
])
def test_si_algo_falla_se_informa_y_no_se_lanza(obtener, escribir, texto):
    ok, motivo, nuevo = stock_meli.ajustar_en_meli("tok", "MLA1", "999" if "ya no existe" in texto else "MLA1_unica", -1, obtener=obtener, escribir=escribir)
    assert ok is False and texto in motivo and nuevo is None


# ── La venta manual con y sin descuento en Mercado Libre ──────────────────────────────────────────────────────────────────────────────

class _Cur:
    def __init__(self, base):
        self.b = base

    def execute(self, sql, params=None):
        self.b.sql.append(" ".join(sql.split()))
        self.ultima = sql

    def fetchone(self):
        if "RETURNING id" in self.ultima:
            return {"id": 77}
        if "FROM productos_variantes pv" in self.ultima:
            return self.b.variante
        return self.b.venta


class _Base:
    def __init__(self, variante=None, venta=None):
        self.variante, self.venta, self.sql = variante, venta, []

    @contextlib.contextmanager
    def conexion(self, *a, **k):
        yield type("C", (), {"cursor": lambda s, **kw: _Cur(self)})()


VARIANTE = {"id_variante": "MLA1_unica", "id_meli": "MLA1", "titulo": "Campera", "tipo_logistica": "cross_docking", "inventory_id": None}


def _preparar(monkeypatch, base, ajuste=(True, "", 4)):
    monkeypatch.setattr(ventas_manuales.db, "conexion_usuario", base.conexion)
    monkeypatch.setattr(ventas_manuales.token_manager, "asegurar_token_valido", lambda c: "tok")
    llamadas = []
    monkeypatch.setattr(ventas_manuales.stock_meli, "ajustar_en_meli", lambda *a, **k: llamadas.append(a[-1]) or ajuste)
    return llamadas


def test_la_venta_manual_descuenta_en_meli_cuando_se_pide(monkeypatch):
    base = _Base(VARIANTE)
    llamadas = _preparar(monkeypatch, base)
    r = ventas_manuales.registrar_venta_manual(1, 1, "MLA1_unica", 2, 50000, "2026-10-02", "Marcela", descontar_en_meli=True)
    assert r == (True, None, None) and llamadas == [-2]
    assert any("stock_descontado_meli = true" in s for s in base.sql)


def test_sin_pedirlo_no_se_toca_mercado_libre(monkeypatch):
    base = _Base(VARIANTE)
    llamadas = _preparar(monkeypatch, base)
    assert ventas_manuales.registrar_venta_manual(1, 1, "MLA1_unica", 1, 50000, "2026-10-02", "", descontar_en_meli=False) == (True, None, None)
    assert llamadas == []


def test_una_publicacion_de_full_no_se_escribe(monkeypatch):
    base = _Base({**VARIANTE, "tipo_logistica": "fulfillment"})
    llamadas = _preparar(monkeypatch, base)
    ok, error, aviso = ventas_manuales.registrar_venta_manual(1, 1, "MLA1_unica", 1, 50000, "2026-10-02", "", descontar_en_meli=True)
    assert ok and error is None and "FULL" in aviso and llamadas == []


def test_si_meli_falla_la_venta_queda_registrada_con_un_aviso(monkeypatch):
    base = _Base(VARIANTE)
    _preparar(monkeypatch, base, ajuste=(False, "Mercado Libre no aceptó el cambio de stock.", None))
    ok, error, aviso = ventas_manuales.registrar_venta_manual(1, 1, "MLA1_unica", 1, 50000, "2026-10-02", "", descontar_en_meli=True)
    assert ok and error is None and "Se registró la venta" in aviso and "Descontalo vos" in aviso
    assert not any("stock_descontado_meli = true" in s for s in base.sql)      # no se marca como descontada: no lo está


def test_al_borrar_una_venta_descontada_se_devuelve_en_meli(monkeypatch):
    base = _Base(venta={"id_variante": "MLA1_unica", "id_meli": "MLA1", "cantidad": 2, "stock_descontado_meli": True})
    llamadas = _preparar(monkeypatch, base)
    assert ventas_manuales.eliminar_venta_manual(1, 1, 77) == (True, None) and llamadas == [2]


def test_al_borrar_una_venta_que_no_se_descontó_no_se_toca_meli(monkeypatch):
    base = _Base(venta={"id_variante": "MLA1_unica", "id_meli": "MLA1", "cantidad": 2, "stock_descontado_meli": False})
    llamadas = _preparar(monkeypatch, base)
    assert ventas_manuales.eliminar_venta_manual(1, 1, 77) == (True, None) and llamadas == []


@pytest.mark.parametrize("cantidad, precio", [(0, 100), (1, 0), ("x", 100), (1, "abc")])
def test_cantidad_y_precio_invalidos(cantidad, precio):
    assert ventas_manuales.registrar_venta_manual(1, 1, "v", cantidad, precio, "2026-10-02", "")[0] is False
