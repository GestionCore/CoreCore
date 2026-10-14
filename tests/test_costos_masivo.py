"""
La pantalla Costos guarda en bloque (`/guardar_costos_masivo`): por publicación y por variante, en pesos o en dólares, y cambiar el dólar recalcula lo cargado en dólares.
Corre con la app real contra la base real, dentro de una transacción que se revierte (la migración 0050 se aplica ahí adentro). Se omite sin DATABASE_URL_ADMIN.
"""
import os

import pytest

pytestmark = pytest.mark.db
if not (os.getenv("DATABASE_URL") and os.getenv("DATABASE_URL_ADMIN")):
    pytest.skip("Sin DATABASE_URL/DATABASE_URL_ADMIN: se omiten las pruebas con la app real", allow_module_level=True)

import app as aplicacion  # noqa: E402
import db  # noqa: E402
import dolar  # noqa: E402
from tests.test_costos_moneda import _Prestada, _Revertir, _cuenta, _estado, _migrar, _padre, _variante  # noqa: E402


def _sin_decoradores(funcion):
    while hasattr(funcion, "__wrapped__"):
        funcion = funcion.__wrapped__
    return funcion


def _llamar(funcion, usuario, cuenta, cuerpo):
    with aplicacion.app.test_request_context(json=cuerpo, method="POST"):
        aplicacion.g.usuario_id, aplicacion.g.cuenta_id = usuario, cuenta
        r = _sin_decoradores(funcion)()
        respuesta, codigo = (r if isinstance(r, tuple) else (r, 200))
        return respuesta.get_json(), codigo


def _preparar(monkeypatch, conexion, usuario, cuenta, valor_dolar):
    """La conexión de la prueba reemplaza a la de la app (nada se confirma) y la cuenta usa un dólar manual conocido (None = sin cotización alguna)."""
    monkeypatch.setattr(db, "conexion_usuario", lambda u, c=None: _Prestada(conexion))
    cur = conexion.cursor()
    _migrar(cur)
    if valor_dolar is None:
        monkeypatch.setattr(dolar, "ultimo_mep", lambda cursor, hoy=None: None)
        assert dolar.guardar_modo(cur, cuenta, "automatico", None)[0] is True
    else:
        assert dolar.guardar_modo(cur, cuenta, "manual", valor_dolar)[0] is True
    return cur


def test_el_guardado_en_bloque_acepta_pesos_dolares_y_costos_por_variante(monkeypatch):
    usuario, cuenta = _cuenta()
    p = f"PRUEBA-MAS-{os.getpid()}"
    try:
        with db.conexion_admin() as conexion:
            cur = _preparar(monkeypatch, conexion, usuario, cuenta, 1500)
            id_a = _padre(cur, cuenta, f"{p}-A")
            _padre(cur, cuenta, f"{p}-B", costo=3000)
            _variante(cur, cuenta, id_a, f"{p}-V1")
            _variante(cur, cuenta, id_a, f"{p}-V2")
            cuerpo, codigo = _llamar(aplicacion.guardar_costos_masivo, usuario, cuenta, {
                "costos": {f"{p}-A": 10, f"{p}-B": 4200}, "monedas": {f"{p}-A": "USD"},                    # A en dólares (sin «moneda» de B = pesos), B en pesos
                "variantes": {f"{p}-V1": 7}, "monedas_variantes": {f"{p}-V1": "USD"}})
            assert codigo == 200 and cuerpo["ok"] is True and cuerpo["actualizados"] == 3 and cuerpo["errores"] == []
            assert _estado(cur, "productos_padre", "id_meli", f"{p}-A", cuenta) == (15000.0, 10.0, "USD")        # 10 US$ × 1.500
            assert _estado(cur, "productos_padre", "id_meli", f"{p}-B", cuenta) == (4200.0, 4200.0, "ARS")
            assert _estado(cur, "productos_variantes", "id_variante", f"{p}-V1", cuenta) == (10500.0, 7.0, "USD")   # 7 US$ × 1.500
            assert _estado(cur, "productos_variantes", "id_variante", f"{p}-V2", cuenta) == (None, None, None)      # la otra variante sigue sin costo propio
            raise _Revertir()
    except _Revertir:
        pass


def test_un_costo_invalido_se_informa_y_los_demas_se_guardan(monkeypatch):
    usuario, cuenta = _cuenta()
    p = f"PRUEBA-INV-{os.getpid()}"
    try:
        with db.conexion_admin() as conexion:
            cur = _preparar(monkeypatch, conexion, usuario, cuenta, 1500)
            _padre(cur, cuenta, f"{p}-A")
            _padre(cur, cuenta, f"{p}-B", costo=3000)
            cuerpo, codigo = _llamar(aplicacion.guardar_costos_masivo, usuario, cuenta, {"costos": {f"{p}-A": -5, f"{p}-B": 3500}})
            assert codigo == 200 and cuerpo["actualizados"] == 1 and len(cuerpo["errores"]) == 1                 # el negativo se rechaza con su mensaje; el otro se guarda
            assert _estado(cur, "productos_padre", "id_meli", f"{p}-B", cuenta)[0] == 3500.0
            assert _estado(cur, "productos_padre", "id_meli", f"{p}-A", cuenta)[0] is None
            cuerpo, codigo = _llamar(aplicacion.guardar_costos_masivo, usuario, cuenta, {"costos": {f"{p}-A": "abc"}})
            assert codigo == 400 and cuerpo["ok"] is False and cuerpo["error"]                                   # si no se guarda nada, es un error con el motivo a la vista
            cuerpo, codigo = _llamar(aplicacion.guardar_costos_masivo, usuario, cuenta, {})
            assert codigo == 400 and cuerpo["error"] == "Nada para guardar"
            raise _Revertir()
    except _Revertir:
        pass


def test_sin_cotizacion_un_costo_en_dolares_no_se_guarda_con_un_numero_supuesto(monkeypatch):
    usuario, cuenta = _cuenta()
    p = f"PRUEBA-SIN-{os.getpid()}"
    try:
        with db.conexion_admin() as conexion:
            cur = _preparar(monkeypatch, conexion, usuario, cuenta, None)
            _padre(cur, cuenta, f"{p}-A", costo=3000)
            cuerpo, codigo = _llamar(aplicacion.guardar_costos_masivo, usuario, cuenta, {"costos": {f"{p}-A": 10}, "monedas": {f"{p}-A": "USD"}})
            assert codigo == 400 and cuerpo["ok"] is False and "dólar" in cuerpo["error"].lower()
            assert _estado(cur, "productos_padre", "id_meli", f"{p}-A", cuenta)[0] == 3000.0                     # el costo de antes queda como estaba
            raise _Revertir()
    except _Revertir:
        pass


def test_cambiar_el_dolar_de_la_cuenta_recalcula_los_costos_en_dolares(monkeypatch):
    usuario, cuenta = _cuenta()
    p = f"PRUEBA-DOL-{os.getpid()}"
    try:
        with db.conexion_admin() as conexion:
            cur = _preparar(monkeypatch, conexion, usuario, cuenta, 1500)
            id_a = _padre(cur, cuenta, f"{p}-A")
            _padre(cur, cuenta, f"{p}-B", costo=3000)
            _variante(cur, cuenta, id_a, f"{p}-V1")
            _llamar(aplicacion.guardar_costos_masivo, usuario, cuenta, {"costos": {f"{p}-A": 10}, "monedas": {f"{p}-A": "USD"}, "variantes": {f"{p}-V1": 4}, "monedas_variantes": {f"{p}-V1": "USD"}})
            cuerpo, codigo = _llamar(aplicacion.api_cuenta_dolar, usuario, cuenta, {"modo": "manual", "valor": 1600})
            assert codigo == 200 and cuerpo["ok"] is True and cuerpo["costos_recalculados"] >= 2
            assert _estado(cur, "productos_padre", "id_meli", f"{p}-A", cuenta) == (16000.0, 10.0, "USD")        # 10 × 1.600
            assert _estado(cur, "productos_variantes", "id_variante", f"{p}-V1", cuenta) == (6400.0, 4.0, "USD")  # 4 × 1.600
            assert _estado(cur, "productos_padre", "id_meli", f"{p}-B", cuenta)[0] == 3000.0                      # lo cargado en pesos no se mueve
            raise _Revertir()
    except _Revertir:
        pass


def test_la_pantalla_de_costos_muestra_lo_cargado_en_dolares_y_el_costo_de_cada_variante(monkeypatch):
    import costos
    usuario, cuenta = _cuenta()
    p = f"PRUEBA-PAN-{os.getpid()}"
    try:
        with db.conexion_admin() as conexion:
            cur = _preparar(monkeypatch, conexion, usuario, cuenta, 1500)
            id_a = _padre(cur, cuenta, f"{p}-A")
            _variante(cur, cuenta, id_a, f"{p}-V1")
            _variante(cur, cuenta, id_a, f"{p}-V2")
            _llamar(aplicacion.guardar_costos_masivo, usuario, cuenta, {"costos": {f"{p}-A": 10}, "monedas": {f"{p}-A": "USD"}, "variantes": {f"{p}-V2": 8000}})
            monkeypatch.setattr(db, "conexion_usuario", lambda u, c=None: _Prestada(conexion))
            productos = costos.obtener_datos_costos(usuario, "2030-03-01", "2030-03-31", cuenta)[2]
            fila = next((x for x in productos if x["id"] == f"{p}-A"), None)
            assert fila is not None, "la publicación de prueba no aparece en la pantalla de costos"
            assert fila["moneda"] == "USD" and fila["costo_mostrado"] == 10.0                                   # se muestra lo que la persona cargó, no los pesos
            por_variante = {v["id_variante"]: v for v in fila["variantes_ml"]}
            assert por_variante[f"{p}-V2"]["pesos"] == 8000.0 and por_variante[f"{p}-V2"]["moneda"] == "ARS"
            assert por_variante[f"{p}-V1"]["pesos"] is None                                                    # sin costo propio: usa el de la publicación
            raise _Revertir()
    except _Revertir:
        pass

