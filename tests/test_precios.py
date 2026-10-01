import precios
from tests.conftest import CursorFalso


def _datos(precio, costo, unidades, ingreso, cargos, envios, margen=20.0, pub=0.0):
    ventas = [("MLA1", unidades, ingreso, cargos, envios)] if unidades else []
    productos = [("MLA1", "Producto", None, None, precio, costo)]
    return precios.obtener_datos(CursorFalso(ventas, productos), 1, margen, pub)


def test_precio_minimo_es_el_que_deja_la_ganancia_en_cero():
    # comisión 20 % del ingreso, envío $1.000 por unidad, costo $5.000, 10 ventas a $20.000
    d = _datos(20000, 5000, 10, 200000, 40000, 10000)
    i = d["items"][0]
    minimo = i["minimo"]
    # a ese precio, lo que queda después de comisión (20 %) y envío es el costo
    assert minimo >= (5000 + 1000) / 0.8 and minimo < (5000 + 1000) / 0.8 + 10
    neto_al_minimo = minimo * (1 - 0.2) - 1000 - 5000
    assert 0 <= neto_al_minimo < 10 * 0.8 + 1      # el redondeo hacia arriba a $10 deja a lo sumo unos pesos


def test_precio_recomendado_deja_el_margen_pedido():
    d = _datos(20000, 5000, 10, 200000, 40000, 10000, margen=30)
    i = d["items"][0]
    margen = (i["recomendado"] * (1 - 0.2) - 1000 - 5000) / i["recomendado"]
    assert 0.30 <= margen < 0.31


def test_estados_segun_el_precio_actual():
    assert _datos(5000, 5000, 10, 50000, 10000, 10000)["items"][0]["estado"] == "pierde"
    assert _datos(9000, 5000, 10, 90000, 18000, 10000)["items"][0]["estado"] == "justo"
    assert _datos(60000, 5000, 10, 600000, 120000, 10000)["items"][0]["estado"] == "ok"


def test_sin_costo_o_sin_ventas_no_se_estima():
    sin_costo = _datos(20000, 0, 10, 200000, 40000, 10000)
    assert sin_costo["items"] == [] and len(sin_costo["sin_costo"]) == 1
    sin_ventas = _datos(20000, 5000, 0, 0, 0, 0)
    assert sin_ventas["items"] == [] and len(sin_ventas["sin_ventas"]) == 1


def test_parametros_se_sanean():
    assert precios.parametros("abc", None) == (precios.MARGEN_OBJETIVO_DEFECTO, 0.0)
    assert precios.parametros("500", "-5") == (60.0, 0.0)
