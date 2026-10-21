"""
Cargar un gasto a mano (/agregar_gasto): el monto se lee como lo escribe una persona en Argentina y un dato mal puesto se avisa en pantalla en vez de dar un error 500.
Antes: float(«1.500,50») daba error 500, float(«150.000») guardaba $150 (mil veces menos), la categoría y la fecha no se validaban y el período volvía tal cual (hasta como «None»).
La base se simula.
"""
from urllib.parse import parse_qs, urlparse

import pytest

import app as modulo_app


class _Cursor:
    def __init__(self, escrituras):
        self.escrituras = escrituras

    def execute(self, sql, params=None):
        self.escrituras.append((" ".join(sql.split()), params))


class _Conexion:
    def __init__(self, escrituras):
        self.escrituras = escrituras

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self):
        return _Cursor(self.escrituras)


def _enviar(monkeypatch, **campos):
    escrituras = []
    monkeypatch.setattr(modulo_app.db, "conexion_usuario", lambda *a, **k: _Conexion(escrituras))
    base = {"concepto": "Alquiler", "categoria": "fijo", "monto": "150000", "fecha": "2030-03-10", "fecha_desde": "2030-03-01", "fecha_hasta": "2030-03-31"}
    funcion = modulo_app.agregar_gasto
    while hasattr(funcion, "__wrapped__"):
        funcion = funcion.__wrapped__
    with modulo_app.app.test_request_context("/agregar_gasto", method="POST", data={**base, **campos}):
        from flask import g
        g.usuario_id, g.cuenta_id = 3, 7
        respuesta = funcion()
    return respuesta, escrituras


def _mensaje(respuesta):
    return parse_qs(urlparse(respuesta.location).query).get("msg", [None])[0]


@pytest.mark.parametrize("escrito, guardado", [("150000", 150000.0), ("150.000", 150000.0), ("1.500,50", 1500.5), ("1500.5", 1500.5), ("$ 12.500", 12500.0), ("0,01", 0.01)])
def test_el_monto_se_lee_como_lo_escribe_una_persona_en_argentina(monkeypatch, escrito, guardado):
    respuesta, escrituras = _enviar(monkeypatch, monto=escrito)
    assert _mensaje(respuesta) is None and len(escrituras) == 1
    assert escrituras[0][1] == (7, "Alquiler", "fijo", guardado, "2030-03-10")


def test_un_gasto_bueno_vuelve_a_costos_con_el_periodo_que_se_estaba_mirando(monkeypatch):
    respuesta, _ = _enviar(monkeypatch)
    consulta = parse_qs(urlparse(respuesta.location).query)
    assert urlparse(respuesta.location).path == "/costos" and consulta == {"fecha_desde": ["2030-03-01"], "fecha_hasta": ["2030-03-31"]}


@pytest.mark.parametrize("campos, texto", [
    ({"monto": "abc"}, "monto"), ({"monto": ""}, "monto"), ({"monto": "0"}, "monto"), ({"monto": "-50"}, "monto"), ({"monto": "nan"}, "monto"), ({"monto": "inf"}, "monto"),
    ({"monto": "1e15"}, "monto"), ({"concepto": "   "}, "en qué fue"), ({"categoria": "otro"}, "fijo o variable"), ({"categoria": ""}, "fijo o variable"),
    ({"fecha": "10/03/2030"}, "fecha"), ({"fecha": "2030-13-45"}, "fecha"),
])
def test_un_dato_mal_puesto_se_avisa_y_no_se_guarda_nada(monkeypatch, campos, texto):
    respuesta, escrituras = _enviar(monkeypatch, **campos)
    assert escrituras == [] and texto in (_mensaje(respuesta) or "")
    assert parse_qs(urlparse(respuesta.location).query)["tipo"] == ["error"]                 # global.js lo muestra como un aviso rojo


def test_el_periodo_que_no_es_una_fecha_no_viaja_de_vuelta(monkeypatch):
    respuesta, _ = _enviar(monkeypatch, fecha_desde="None", fecha_hasta="<script>")
    assert respuesta.location == "/costos"                                                   # sin parámetros raros en la dirección
    respuesta, _ = _enviar(monkeypatch, fecha_desde="", fecha_hasta="2030-03-31")
    assert parse_qs(urlparse(respuesta.location).query) == {"fecha_hasta": ["2030-03-31"]}


def test_un_concepto_largo_se_corta_a_200_caracteres(monkeypatch):
    _, escrituras = _enviar(monkeypatch, concepto="x" * 500)
    assert len(escrituras[0][1][1]) == 200
