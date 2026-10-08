"""
Registro diario de palabras en tendencia (tendencias.registrar_y_detectar_emergentes): una sola sentencia para todas las palabras en lugar de un INSERT por palabra
(~2 s por visita a Tendencias medido desde la PC), con el mismo resultado. Se prueba contra la base real dentro de una transacción que se revierte.
"""
import os
from datetime import timedelta

import pytest

import tendencias
from utils import hoy_argentina


class _Revertir(Exception):
    pass


@pytest.mark.db
@pytest.mark.skipif(not os.getenv("DATABASE_URL_ADMIN"), reason="Sin DATABASE_URL_ADMIN")
def test_registra_cada_palabra_una_vez_y_detecta_solo_las_emergentes():
    import db
    prefijo = f"zz-prueba-{os.getpid()}"
    hoy = hoy_argentina()
    try:
        with db.conexion_admin() as c:
            cur = c.cursor()
            cur.execute("SELECT id FROM cuentas_meli ORDER BY id LIMIT 1")
            cuenta = cur.fetchone()[0]
            vieja, nueva, vacia = f"{prefijo}-vieja", f"{prefijo}-nueva", ""
            cur.execute("INSERT INTO tendencias_historial (cuenta_id, keyword, fecha) VALUES (%s, %s, %s)", (cuenta, vieja, hoy - timedelta(days=5)))   # ya se había visto hace 5 días

            emergentes = tendencias.registrar_y_detectar_emergentes(cur, cuenta, {vieja, nueva, vacia})
            assert emergentes == {nueva, vacia}                              # emergente = no figuraba en los 14 días anteriores (el vacío no se guarda, pero tampoco rompe)
            cur.execute("SELECT keyword, fecha FROM tendencias_historial WHERE cuenta_id = %s AND keyword LIKE %s ORDER BY keyword, fecha", (cuenta, f"{prefijo}%"))
            assert [(k, f) for k, f in cur.fetchall()] == [(nueva, hoy), (vieja, hoy - timedelta(days=5)), (vieja, hoy)]

            tendencias.registrar_y_detectar_emergentes(cur, cuenta, [nueva, nueva, vieja])        # repetir el mismo día no duplica (clave primaria) ni falla con repetidas
            cur.execute("SELECT count(*) FROM tendencias_historial WHERE cuenta_id = %s AND keyword LIKE %s", (cuenta, f"{prefijo}%"))
            assert cur.fetchone()[0] == 3

            assert tendencias.registrar_y_detectar_emergentes(cur, cuenta, set()) == set()        # sin palabras: no inserta nada ni falla
            raise _Revertir()
    except _Revertir:
        pass
