import precios
from tests.conftest import CursorFalso


class Resp:
    def __init__(self, codigo=200, cuerpo=None):
        self.status_code, self._c = codigo, cuerpo or {}

    def json(self):
        return self._c


def _datos(precio=10000.0, costo=6000.0, envio=1000.0, comision_pct=0.2, unidades=10):
    """Datos como los arma obtener_datos, a partir de una publicación con ventas reales."""
    cursor = CursorFalso(
        [("MLA1", unidades, precio * unidades, precio * unidades * comision_pct, envio * unidades)],
        [("MLA1", "Campera", None, None, precio, costo)],
    )
    return precios.obtener_datos(cursor, 1, margen_objetivo=20, publicidad_pct=0)


def test_una_publicacion_con_margen_justo_es_aplicable_con_el_recomendado():
    datos = _datos(precio=9000.0)
    item = datos["items"][0]
    assert item["estado"] in ("pierde", "justo") and item["recomendado"] > item["precio"]
    assert item["aplicable"] and item["suba_pct"] > 0
    assert list(precios.aplicables(datos)) == ["MLA1"]


def test_una_publicacion_que_ya_cubre_el_margen_no_es_aplicable():
    datos = _datos(precio=20000.0)
    assert datos["items"][0]["estado"] == "ok" and precios.aplicables(datos) == {}


def test_una_suba_enorme_se_trata_como_costo_mal_cargado_y_no_se_aplica():
    datos = _datos(precio=1000.0, costo=6000.0)
    item = datos["items"][0]
    assert item["suba_excesiva"] and not item["aplicable"] and precios.aplicables(datos) == {}


def test_solo_se_acepta_el_precio_recomendado_exacto(monkeypatch):
    llamadas = []
    monkeypatch.setattr(precios.meli_http, "put", lambda url, **kw: llamadas.append((url, kw["json"])) or Resp(200))
    datos = _datos(precio=9000.0)
    rec = datos["items"][0]["recomendado"]
    cur = CursorFalso()
    res = precios.aplicar(cur, 1, "tok", [{"id": "MLA1", "precio": rec + 500}], datos)       # el navegador manda otro precio
    assert res[0]["ok"] is False and llamadas == []
    res = precios.aplicar(cur, 1, "tok", [{"id": "MLA1", "precio": rec}], datos)
    assert res == [{"id": "MLA1", "ok": True, "detalle": "Precio actualizado", "precio": rec}]
    assert llamadas == [("https://api.mercadolibre.com/items/MLA1", {"price": rec})]


def test_al_aplicar_se_actualiza_la_base_y_se_deja_historial(monkeypatch):
    monkeypatch.setattr(precios.meli_http, "put", lambda url, **kw: Resp(200))
    datos = _datos(precio=9000.0)
    cur = CursorFalso()
    precios.aplicar(cur, 7, "tok", [{"id": "MLA1", "precio": datos["items"][0]["recomendado"]}], datos)
    sqls = [s for s, _ in cur.consultas]
    assert any("UPDATE productos_padre SET precio" in s for s in sqls)
    insert = [(s, p) for s, p in cur.consultas if "INSERT INTO historial_precios" in s][0]
    assert insert[1][0] == 7 and insert[1][2] == 9000.0


def test_un_id_que_no_es_aplicable_o_repetido_no_toca_mercado_libre(monkeypatch):
    llamadas = []
    monkeypatch.setattr(precios.meli_http, "put", lambda url, **kw: llamadas.append(url) or Resp(200))
    datos = _datos(precio=9000.0)
    rec = datos["items"][0]["recomendado"]
    res = precios.aplicar(CursorFalso(), 1, "tok", [{"id": "MLA999", "precio": 5}, {"id": "MLA1", "precio": rec}, {"id": "MLA1", "precio": rec}, {}, {"id": "MLA1", "precio": "x"}], datos)
    assert [r["ok"] for r in res] == [False, True]          # el repetido y el vacío se ignoran, no se aplica dos veces
    assert len(llamadas) == 1


def test_si_mercado_libre_rechaza_no_se_toca_la_base(monkeypatch):
    monkeypatch.setattr(precios.meli_http, "put", lambda url, **kw: Resp(400, {"message": "Item with variations: price must be set per variation"}))
    datos = _datos(precio=9000.0)
    cur = CursorFalso()
    res = precios.aplicar(cur, 1, "tok", [{"id": "MLA1", "precio": datos["items"][0]["recomendado"]}], datos)
    assert res[0]["ok"] is False and "variante" in res[0]["detalle"]
    assert not any("UPDATE" in s or "INSERT" in s for s, _ in cur.consultas)


def test_hay_un_tope_de_publicaciones_por_pedido(monkeypatch):
    monkeypatch.setattr(precios.meli_http, "put", lambda url, **kw: Resp(200))
    datos = _datos(precio=9000.0)
    pedidos = [{"id": f"X{i}", "precio": 1} for i in range(200)]
    assert len(precios.aplicar(CursorFalso(), 1, "tok", pedidos, datos)) == precios.MAXIMO_POR_PEDIDO
