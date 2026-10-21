"""
Registro de pedidos lentos (seguridad._registrar_si_fue_lento): una línea `[Lento] GET /ruta 200 4.2s` por pedido que tarda más del umbral, sin parámetros ni datos de la persona.
Es lo que permite medir con datos de producción qué pantallas tardan de verdad (desde otra PC la latencia a la base distorsiona todo).
"""
import logging

import pytest
from flask import Flask

import seguridad


@pytest.fixture
def cliente():
    app = Flask(__name__)
    app.config["TESTING"] = True
    seguridad.iniciar(app)

    @app.route("/pantalla")
    def pantalla():
        return "ok"

    @app.route("/static/archivo.js")
    def archivo():
        return "x"

    return app.test_client()


def test_un_pedido_lento_deja_una_linea_con_metodo_ruta_codigo_y_tiempo(cliente, monkeypatch, caplog):
    monkeypatch.setattr(seguridad, "SEGUNDOS_PEDIDO_LENTO", 0.0)
    with caplog.at_level(logging.WARNING, logger="corelux.seguridad"):
        cliente.get("/pantalla?fecha_desde=2026-09-01&token=secreto")
    lineas = [r.getMessage() for r in caplog.records if "[Lento]" in r.getMessage()]
    assert len(lineas) == 1 and lineas[0].startswith("[Lento] GET /pantalla 200 ") and lineas[0].endswith("s")
    assert "secreto" not in lineas[0] and "fecha_desde" not in lineas[0]                  # nunca los parámetros del pedido


def test_un_pedido_lento_lista_los_tramos_que_mas_tardaron_y_omite_los_rapidos(cliente, monkeypatch, caplog):
    import time

    @cliente.application.route("/con_partes")
    def con_partes():
        with seguridad.parte("publicidad"):
            time.sleep(0.35)
        with seguridad.parte("factura"):
            time.sleep(0.31)
        with seguridad.parte("rapido"):
            pass
        with seguridad.parte("publicidad"):              # el mismo tramo dos veces se suma
            time.sleep(0.05)
        return "ok"
    monkeypatch.setattr(seguridad, "SEGUNDOS_PEDIDO_LENTO", 0.0)
    with caplog.at_level(logging.WARNING, logger="corelux.seguridad"):
        cliente.get("/con_partes")
    linea = next(r.getMessage() for r in caplog.records if "[Lento]" in r.getMessage())
    assert linea.split(" | ")[1].startswith("publicidad 0.4s, factura 0.3s") and "rapido" not in linea


def test_medir_un_tramo_fuera_de_un_pedido_no_hace_nada():
    with seguridad.parte("scheduler"):
        pass


def test_un_pedido_rapido_no_deja_nada(cliente, monkeypatch, caplog):
    monkeypatch.setattr(seguridad, "SEGUNDOS_PEDIDO_LENTO", 60.0)
    with caplog.at_level(logging.WARNING, logger="corelux.seguridad"):
        cliente.get("/pantalla")
    assert not [r for r in caplog.records if "[Lento]" in r.getMessage()]


def test_archivos_y_consultas_periodicas_no_se_miden(cliente, monkeypatch, caplog):
    monkeypatch.setattr(seguridad, "SEGUNDOS_PEDIDO_LENTO", 0.0)
    with caplog.at_level(logging.WARNING, logger="corelux.seguridad"):
        cliente.get("/static/archivo.js")
        cliente.get("/healthz")
    assert not [r for r in caplog.records if "[Lento]" in r.getMessage()]


def test_medir_nunca_rompe_la_respuesta(cliente, monkeypatch):
    monkeypatch.setattr(seguridad, "SEGUNDOS_PEDIDO_LENTO", "no es un numero")           # un umbral roto no puede tumbar la página
    assert cliente.get("/pantalla").status_code == 200
