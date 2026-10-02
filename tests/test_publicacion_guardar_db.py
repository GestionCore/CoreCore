"""
El guardado del panel de una publicación con la app real pero SIN tocar la base ni Mercado Libre: la base y la API se reemplazan por dobles que
anotan lo que reciben. Lo que se verifica: qué se le manda a MeLi, y que si MeLi rechaza no cambia nada en CoreLux. Se omite sin DATABASE_URL
(importar app abre el pool).
"""
import contextlib
import os

import pytest

pytestmark = pytest.mark.db
if not os.getenv("DATABASE_URL"):
    pytest.skip("Sin DATABASE_URL: se omiten las pruebas con la app real", allow_module_level=True)

import app as aplicacion  # noqa: E402
import db  # noqa: E402


class _Cursor:
    def __init__(self, base):
        self.base = base

    def execute(self, sql, params=None):
        self.base.sentencias.append((" ".join(sql.split()), params))
        self.ultima = sql

    def fetchone(self):
        return self.base.fila if "FROM productos_padre" in self.ultima else None


class _Base:
    def __init__(self, fila):
        self.fila, self.sentencias = fila, []

    @contextlib.contextmanager
    def conexion(self, *a, **k):
        yield type("Con", (), {"cursor": lambda s: _Cursor(self)})()


class _Respuesta:
    def __init__(self, codigo, cuerpo=None):
        self.status_code, self._cuerpo, self.text = codigo, cuerpo or {}, str(cuerpo)

    def json(self):
        return self._cuerpo


def _guardar(monkeypatch, pedido, respuesta_meli, fila=("Campera", 54999, "active")):
    base, enviados = _Base(fila), []
    monkeypatch.setattr(db, "conexion_usuario", base.conexion)
    monkeypatch.setattr(aplicacion.token_manager, "asegurar_token_valido", lambda cuenta: "token")

    def _put(url, **kw):
        enviados.append((url, kw["json"]))
        return respuesta_meli

    monkeypatch.setattr(aplicacion.meli_http, "put", _put)
    funcion = aplicacion.api_drawer_guardar
    while hasattr(funcion, "__wrapped__"):
        funcion = funcion.__wrapped__
    with aplicacion.app.test_request_context(json=pedido, method="POST"):
        aplicacion.g.usuario_id, aplicacion.g.cuenta_id = 1, 1
        r = funcion("MLA123")
        cuerpo = (r[0] if isinstance(r, tuple) else r).get_json()
    return cuerpo, enviados, base.sentencias


def test_cambiar_solo_el_precio_manda_solo_el_precio_y_lo_anota(monkeypatch):
    cuerpo, enviados, sql = _guardar(monkeypatch, {"titulo": "Campera", "precio": 59999, "estado": "active", "precio_costo": 12000}, _Respuesta(200))
    assert cuerpo["ok"] is True
    assert enviados == [("https://api.mercadolibre.com/items/MLA123", {"price": 59999.0})]
    texto = " | ".join(s for s, _ in sql)
    assert "UPDATE productos_padre SET precio = %s WHERE" in texto and "INSERT INTO historial_precios" in texto and "precio_costo = %s" in texto


def test_si_mercado_libre_rechaza_no_cambia_nada_en_corelux(monkeypatch):
    cuerpo, enviados, sql = _guardar(monkeypatch, {"titulo": "Otro título", "precio": 54999, "estado": "active"}, _Respuesta(400, {"cause": [{"code": "item.title.not_modifiable"}]}))
    assert cuerpo["ok"] is False and "ya tiene ventas" in cuerpo["detalle"]
    assert enviados == [("https://api.mercadolibre.com/items/MLA123", {"title": "Otro título"})]
    assert not any(s.startswith("UPDATE productos_padre SET titulo") or "historial_precios" in s for s, _ in sql)


def test_finalizar_se_rechaza_antes_de_llamar_a_mercado_libre(monkeypatch):
    cuerpo, enviados, _ = _guardar(monkeypatch, {"estado": "closed"}, _Respuesta(200))
    assert cuerpo["ok"] is False and enviados == []


def test_solo_el_costo_no_llama_a_mercado_libre(monkeypatch):
    cuerpo, enviados, sql = _guardar(monkeypatch, {"titulo": "Campera", "precio": 54999, "estado": "active", "precio_costo": 8000}, _Respuesta(500))
    assert cuerpo["ok"] is True and cuerpo["costo_guardado"] is True and enviados == []
    assert any("precio_costo = %s" in s for s, _ in sql)
