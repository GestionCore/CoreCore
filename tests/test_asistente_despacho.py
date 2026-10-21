"""
La herramienta `despacho` del asistente: lo que hay para despachar HOY, de lo guardado en la base (sin llamar a Mercado Libre ni escribir nada).

Números hechos a mano. La consulta de «qué paquetes son de hoy» es UNA sola (`despacho.leer_paquetes_guardados`): la pantalla y la herramienta la comparten. Lo de la base se prueba con una cuenta nueva
y vacía creada DENTRO de una transacción que nunca se confirma (la de tests/test_cuenta_nueva.py).
"""
import inspect
import os
from datetime import date

import pytest

import asistente_herramientas as herr
import despacho as despacho_mod
import despacho_corte

CON_BASE = pytest.mark.skipif(not (os.getenv("DATABASE_URL") and os.getenv("DATABASE_URL_ADMIN")), reason="Sin DATABASE_URL/DATABASE_URL_ADMIN")
HOY = date(2030, 3, 31)                                                                                    # un domingo

if os.getenv("DATABASE_URL"):
    from tests.test_cuenta_nueva import _Compartida, cliente_nuevo  # noqa: F401  (cliente_nuevo es el fixture que usan las pruebas con base)

SIN_CORTES = {"correo": {"hora": None, "estado": "no_informado"}, "flex": None, "hora_agrupacion": 24}


class _Prestada:
    def __init__(self, conexion):
        self.conexion = conexion

    def __enter__(self):
        return self.conexion

    def __exit__(self, *a):
        return False


class _Cursor:
    def execute(self, *a, **k):
        pass

    def close(self):
        pass


class _Conexion:
    def cursor(self):
        return _Cursor()


def _ctx():
    return herr.Contexto(1, 1, HOY)


def _fila(titulo, cantidad, despachado=False, logistica="drop_off", etiqueta=None):
    return {"id_orden": "x", "id_meli": "MLA1", "id_variante": "", "titulo": titulo, "cantidad": cantidad, "despachado": despachado, "tipo_logistica": logistica,
            "talle_real": None, "etiqueta_variante": etiqueta, "shipment_id": 1}


def _preparar(monkeypatch, filas, cortes=SIN_CORTES):
    pedidos = {}

    def _leer(conexion, fecha, offset):
        pedidos["fecha"], pedidos["offset"] = fecha, offset
        return filas
    monkeypatch.setattr(herr.db, "conexion_usuario", lambda u, c=None: _Prestada(_Conexion()))
    monkeypatch.setattr(herr.despacho_corte, "cortes_guardados", lambda cursor, cuenta, fecha: cortes)
    monkeypatch.setattr(herr.despacho_mod, "leer_paquetes_guardados", _leer)
    return pedidos


def test_la_herramienta_esta_registrada_sin_parametros_ni_cuenta():
    h = herr.HERRAMIENTAS["despacho"]
    assert len(h["descripcion"]) > 40 and callable(h["funcion"]) and h["parametros"] == {}                    # solo de hoy: no hay nada que la IA pueda pedir ni cambiar
    assert "despacho" in {d["function"]["name"] for d in herr.definiciones()}


def test_cuenta_lo_que_falta_despachar(monkeypatch):
    filas = [_fila("Termo Acero", 2, logistica="drop_off", etiqueta="Negro"),                                  # pendiente, Correo
             _fila("Termo Acero", 1, logistica="self_service", etiqueta="Negro"),                              # pendiente, Flex
             _fila("Mate Premium", 3, logistica=None),                                                         # pendiente, todavía sin tipo de envío: cuenta como Correo (igual que la pantalla)
             _fila("Termo Acero", 4, despachado=True), _fila("Mate Premium", 1, despachado=True, logistica="self_service")]
    pedidos = _preparar(monkeypatch, filas)
    d = herr.ejecutar("despacho", "{}", _ctx())["datos"]
    assert d["paquetes_del_dia"] == 5 and d["ya_despachados"] == 2 and d["pendientes_de_despachar"] == 3 and d["unidades_pendientes"] == 6      # 2 + 1 + 3
    assert d["pendientes_por_modalidad"] == [{"modalidad": "Correo", "paquetes": 2, "unidades": 5}, {"modalidad": "Flex", "paquetes": 1, "unidades": 1}]
    assert d["que_hay_que_preparar"] == [{"modelo": "Mate Premium", "variante": "Única", "unidades": 3}, {"modelo": "Termo Acero", "variante": "Negro", "unidades": 3}]       # empatan en 3: por nombre
    assert d["otros_modelos_o_variantes_pendientes"] == 0 and d["dia_de_despacho"] == "2030-03-31"
    assert pedidos == {"fecha": HOY, "offset": 0}                                                              # sin horario de corte conocido, el día es el calendario
    assert "día calendario" in d["que_dias_abarca"] and "no informó" in d["horarios_de_corte"]["correo"] and "todavía no lo cargó" in d["horarios_de_corte"]["flex"]


def test_sin_paquetes_devuelve_ceros_y_no_inventa_nada(monkeypatch):
    _preparar(monkeypatch, [])
    d = herr.ejecutar("despacho", "{}", _ctx())["datos"]
    assert (d["paquetes_del_dia"], d["ya_despachados"], d["pendientes_de_despachar"], d["unidades_pendientes"]) == (0, 0, 0, 0)
    assert d["pendientes_por_modalidad"] == [] and d["que_hay_que_preparar"] == []


def test_solo_se_listan_los_ocho_productos_con_mas_unidades_y_se_cuenta_el_resto(monkeypatch):
    _preparar(monkeypatch, [_fila(f"Modelo {k:02d}", k) for k in range(1, 12)])                                # 11 modelos con 1 a 11 unidades
    d = herr.ejecutar("despacho", "{}", _ctx())["datos"]
    assert [x["unidades"] for x in d["que_hay_que_preparar"]] == [11, 10, 9, 8, 7, 6, 5, 4] and d["otros_modelos_o_variantes_pendientes"] == 3
    assert d["unidades_pendientes"] == 66                                                                      # 1 + 2 + … + 11, aunque la lista se corte


def test_con_horario_de_corte_el_dia_de_despacho_arranca_ayer_a_esa_hora(monkeypatch):
    cortes = {"correo": {"hora": "13:00", "estado": "informado"}, "flex": "18:30", "hora_agrupacion": 13}
    pedidos = _preparar(monkeypatch, [_fila("Termo", 1)], cortes)
    d = herr.ejecutar("despacho", "{}", _ctx())["datos"]
    assert pedidos["offset"] == 11                                                                             # 24 − 13: lo vendido desde las 13:00 de ayer entra al día de hoy
    assert d["horarios_de_corte"] == {"correo": "hoy a las 13:00", "flex": "hoy a las 18:30"} and "desde ayer a las 13:00 hasta hoy a las 13:00" in d["que_dias_abarca"]


def test_un_dia_sin_retiro_del_correo_se_dice():
    cortes = {"correo": {"hora": None, "estado": "sin_retiro"}, "flex": None, "hora_agrupacion": 24}
    assert herr._texto_de_cortes(cortes)["correo"] == "hoy el correo no retira"


def test_la_pantalla_y_la_herramienta_comparten_la_misma_consulta():
    assert "leer_paquetes_guardados" in inspect.getsource(despacho_mod.obtener_paquetes_del_dia)
    assert "leer_paquetes_guardados" in inspect.getsource(herr._despacho)
    assert "FROM ventas" not in inspect.getsource(herr._despacho)                                              # la herramienta no repite el SQL: si el filtro cambia, cambia para los dos


# ── Con la base: una cuenta nueva y vacía dentro de una transacción que se revierte ─────────────────────────────────────────────────────────

def _venta(cur, cuenta, orden, dia, hora, logistica, cantidad, titulo, despachado=False, origen="meli"):
    cur.execute("""INSERT INTO ventas (cuenta_id, id_orden, id_meli, id_variante, titulo, cantidad, precio_venta, tipo_logistica, despachado, fecha_venta, hora_venta, origen, hora_normalizada)
                   VALUES (%s, %s, 'MLA-DESP', '', %s, %s, 1000, %s, %s, %s, make_time(%s, %s, 0), %s, true)""",
                (cuenta, orden, titulo, cantidad, logistica, despachado, dia, hora[0], hora[1], origen))


@CON_BASE
def test_con_la_base_solo_entran_los_paquetes_de_hoy_que_despacha_el_vendedor(cliente_nuevo):
    cur = _Compartida.conexion.cursor()
    cuenta, usuario = _Compartida.cuenta, _Compartida.usuario
    _venta(cur, cuenta, "A1", HOY, (10, 0), "drop_off", 2, "Termo Acero")                                      # Correo, pendiente
    _venta(cur, cuenta, "A2", HOY, (11, 0), "self_service", 1, "Mate Premium")                                 # Flex, pendiente
    _venta(cur, cuenta, "A3", HOY, (9, 0), None, 3, "Termo Acero", despachado=True)                            # ya despachada
    _venta(cur, cuenta, "A4", HOY, (12, 0), "fulfillment", 5, "Termo Acero")                                   # FULL: lo despacha Mercado Libre
    _venta(cur, cuenta, "A5", date(2030, 3, 30), (23, 0), "drop_off", 7, "Termo Acero")                        # de ayer (sin corte conocido el día es el calendario)
    _venta(cur, cuenta, "A6", HOY, (8, 0), "drop_off", 9, "Termo Acero", origen="manual")                      # venta manual: no hay nada que despachar por Mercado Libre
    paquetes = despacho_mod.obtener_paquetes_del_dia(usuario, cuenta, None, HOY, 0)[0]                         # la pantalla (sin token: no llama a Mercado Libre) ve lo mismo
    d = herr.ejecutar("despacho", "{}", herr.Contexto(usuario, cuenta, HOY))["datos"]
    assert d["paquetes_del_dia"] == len(paquetes) == 3 and d["ya_despachados"] == 1 and d["pendientes_de_despachar"] == 2 and d["unidades_pendientes"] == 3
    assert d["pendientes_por_modalidad"] == [{"modalidad": "Correo", "paquetes": 1, "unidades": 2}, {"modalidad": "Flex", "paquetes": 1, "unidades": 1}]
    assert [(x["modelo"], x["unidades"]) for x in d["que_hay_que_preparar"]] == [("Termo Acero", 2), ("Mate Premium", 1)]


@CON_BASE
def test_con_la_base_el_corte_de_flex_que_cargo_la_persona_mueve_el_dia_de_despacho(cliente_nuevo):
    cur = _Compartida.conexion.cursor()
    cuenta, usuario = _Compartida.cuenta, _Compartida.usuario
    assert despacho_corte.guardar_flex(cur, cuenta, "13") == "13:00"
    _venta(cur, cuenta, "B1", date(2030, 3, 30), (14, 0), "drop_off", 1, "Termo")                              # 14:00 de ayer + 11 h = 01:00 de hoy: entra
    _venta(cur, cuenta, "B2", HOY, (12, 59), "self_service", 2, "Termo")                                       # 12:59 + 11 h = 23:59 de hoy: entra
    _venta(cur, cuenta, "B3", HOY, (14, 0), "drop_off", 4, "Termo")                                            # 14:00 + 11 h = 01:00 de mañana: es del despacho de mañana
    _venta(cur, cuenta, "B4", date(2030, 3, 30), (12, 59), "drop_off", 8, "Termo")                             # 12:59 de ayer + 11 h = 23:59 de ayer: es de ayer
    d = herr.ejecutar("despacho", "{}", herr.Contexto(usuario, cuenta, HOY))["datos"]
    assert d["paquetes_del_dia"] == 2 and d["unidades_pendientes"] == 3                                        # 1 + 2
    assert d["horarios_de_corte"]["flex"] == "hoy a las 13:00" and "desde ayer a las 13:00" in d["que_dias_abarca"]
    assert d["horarios_de_corte"]["correo"].startswith("Mercado Libre no informó")                             # una cuenta nueva no tiene horario de correo guardado
