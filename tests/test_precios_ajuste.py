import pytest

import precios


def _datos():
    base = {"thumbnail": None, "permalink": None, "unidades": 10, "estimado": False}
    return {
        "publicidad_pct": 0.0,
        "items": [
            # comisión 20 %, envío $5.000, costo $20.000: mínimo = (20.000 + 5.000) / 0,8 = $31.250
            {**base, "id_meli": "A", "titulo": "Con datos", "precio": 40000.0, "comision_pct": 20.0, "envio": 5000.0, "costo": 20000.0},
        ],
        "sin_ventas": [{**base, "id_meli": "B", "titulo": "Sin ventas", "precio": 30000.0, "costo": 25000.0}],
        "sin_costo": [{**base, "id_meli": "C", "titulo": "Sin costo", "precio": 10000.0}],
    }


def _por_id(items):
    return {i["id_meli"]: i for i in items}


def test_una_suba_calcula_el_precio_nuevo_en_pesos_enteros_y_el_margen():
    a = _por_id(precios.calcular_ajuste(_datos(), 10))["A"]
    assert a["nuevo"] == 44000.0 and a["estado"] == "ok" and a["aplicable"] is True
    assert a["margen_nuevo"] == round((44000 * 0.8 - 5000 - 20000) / 44000 * 100, 1)


def test_una_baja_que_deja_la_publicacion_bajo_su_minimo_no_se_aplica():
    """Bajar 25 % deja $30.000 < mínimo $31.250: cada venta perdería plata. Antes el cambio masivo no miraba esto."""
    a = _por_id(precios.calcular_ajuste(_datos(), -25))["A"]
    assert a["estado"] == "pierde" and a["aplicable"] is False and "mínimo" in a["motivo"]


def test_sin_ventas_se_juzga_contra_el_costo_y_sin_costo_no_se_sabe():
    r = _por_id(precios.calcular_ajuste(_datos(), -20))
    assert r["B"]["nuevo"] == 24000.0 and r["B"]["estado"] == "pierde" and "costo" in r["B"]["motivo"]      # 24.000 <= 25.000 de costo
    assert r["C"]["estado"] == "sin_datos" and r["C"]["aplicable"] is True and "costo" in r["C"]["motivo"]
    assert _por_id(precios.calcular_ajuste(_datos(), 10))["B"]["estado"] == "ok"


def test_el_precio_sin_cambio_no_es_aplicable():
    r = _por_id(precios.calcular_ajuste({**_datos(), "items": [], "sin_costo": [{"id_meli": "C", "titulo": "x", "precio": 3.0, "thumbnail": None}]}, 1))
    assert r["C"]["estado"] == "sin_cambio" and r["C"]["aplicable"] is False


@pytest.mark.parametrize("valor, esperado", [("10", 10.0), ("-5,5".replace(",", "."), -5.5), (50, 50.0), (-50, -50.0),
                                             (0, None), ("0", None), (51, None), (-200, None), ("abc", None), (None, None), ("nan", None), ("inf", None)])
def test_el_porcentaje_tiene_tope(valor, esperado):
    """Un "200" por un dedo de más no puede arruinar el catálogo."""
    assert precios.porcentaje_valido(valor) == esperado


class _Cursor:
    def __init__(self):
        self.sql = []

    def execute(self, sql, params=None):
        self.sql.append((" ".join(sql.split()), params))


class _Resp:
    def __init__(self, codigo):
        self.status_code = codigo

    def json(self):
        return {"message": "rechazado"}


def _aplicar(monkeypatch, ids, porcentaje=10, codigo=200):
    enviados, cursor = [], _Cursor()
    monkeypatch.setattr(precios.meli_http, "put", lambda url, **kw: enviados.append((url, kw["json"])) or _Resp(codigo))
    return precios.aplicar_ajuste(cursor, 1, "tok", porcentaje, ids, _datos()), enviados, cursor.sql


def test_aplicar_manda_el_precio_calculado_en_el_servidor_y_lo_anota(monkeypatch):
    resultados, enviados, sql = _aplicar(monkeypatch, ["A"])
    assert resultados == [{"id": "A", "ok": True, "detalle": "Precio actualizado", "precio": 44000.0}]
    assert enviados == [("https://api.mercadolibre.com/items/A", {"price": 44000.0})]
    assert any("INSERT INTO historial_precios" in s and p == (1, "A", 40000.0, 44000.0) for s, p in sql)


def test_aplicar_no_toca_lo_que_quedaria_bajo_el_minimo_ni_ids_ajenos(monkeypatch):
    resultados, enviados, sql = _aplicar(monkeypatch, ["A", "ZZZ", "A"], porcentaje=-25)
    assert enviados == [] and sql == []
    assert [r["ok"] for r in resultados] == [False, False] and "mínimo" in resultados[0]["detalle"] and "ya no está activa" in resultados[1]["detalle"]


def test_si_mercado_libre_rechaza_no_se_guarda_nada(monkeypatch):
    resultados, enviados, sql = _aplicar(monkeypatch, ["A"], codigo=400)
    assert resultados[0]["ok"] is False and len(enviados) == 1 and sql == []
