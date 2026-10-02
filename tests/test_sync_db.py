"""
El camino de escritura del sync de ventas contra la base REAL. Se omite sin DATABASE_URL. Todo ocurre dentro de una transacción que se revierte:
no queda ninguna fila.
"""
import os

import pytest

pytestmark = pytest.mark.db
if not os.getenv("DATABASE_URL"):
    pytest.skip("Sin DATABASE_URL: se omiten las pruebas contra la base", allow_module_level=True)

import db  # noqa: E402
import ventas_sync  # noqa: E402


class _Revertir(Exception):
    pass


def _cuenta_con_publicacion():
    with db.conexion_admin() as c:
        cur = c.cursor()
        cur.execute("SELECT c.usuario_id, c.id, p.id_meli FROM cuentas_meli c JOIN productos_padre p ON p.cuenta_id = c.id ORDER BY c.id LIMIT 1")
        return cur.fetchone()


def test_una_orden_nueva_se_guarda_en_hora_argentina_y_marcada_como_normalizada():
    usuario_id, cuenta_id, id_meli = _cuenta_con_publicacion()
    orden = {"id": 9999999999990001, "status": "paid", "date_created": "2026-09-30T23:30:00.000-04:00",
             "order_items": [{"item": {"id": id_meli, "title": "PRUEBA SINTETICA", "variation_id": None}, "quantity": 1, "unit_price": 1000.0, "sale_fee": 100.0}],
             "shipping": {}, "buyer": {"nickname": "TEST"}, "payments": []}
    fila = None
    try:
        with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
            cursor = conexion.cursor()
            assert ventas_sync._escribir_pagina(cursor, cuenta_id, [orden], "token-que-no-se-usa") == (1, 1)
            cursor.execute("SELECT fecha_venta, hora_venta, hora_normalizada, origen FROM ventas WHERE id_orden = '9999999999990001'")
            fila = cursor.fetchone()
            raise _Revertir()
    except _Revertir:
        pass
    assert str(fila[0]) == "2026-10-01" and str(fila[1]) == "00:30:00" and fila[2] is True and fila[3] == "meli"
    with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("SELECT count(*) FROM ventas WHERE id_orden = '9999999999990001'")
        assert cursor.fetchone()[0] == 0
