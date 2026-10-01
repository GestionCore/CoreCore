"""
Aislamiento entre cuentas y entre usuarios con Row Level Security, contra una base REAL. Se omite si no hay DATABASE_URL.
Lectura solamente: no escribe nada.
"""
import os
import pytest

pytestmark = pytest.mark.db
if not os.getenv("DATABASE_URL"):
    pytest.skip("Sin DATABASE_URL: se omiten las pruebas contra la base", allow_module_level=True)

import db  # noqa: E402

TABLAS_POR_CUENTA = ["ventas", "productos_padre", "productos_variantes", "incidencias_posventa", "gastos_operativos", "ventas_retiradas"]


def _primer_usuario_con_cuenta():
    with db.conexion_admin() as c:
        cur = c.cursor()
        cur.execute("SELECT usuario_id, id FROM cuentas_meli ORDER BY id LIMIT 1")
        return cur.fetchone()


@pytest.mark.parametrize("tabla", TABLAS_POR_CUENTA)
def test_una_cuenta_ajena_no_ve_nada(tabla):
    usuario_id, _cuenta = _primer_usuario_con_cuenta()
    with db.conexion_usuario(usuario_id, 999999999) as c:
        cur = c.cursor()
        cur.execute(f"SELECT count(*) FROM {tabla}")
        assert cur.fetchone()[0] == 0


@pytest.mark.parametrize("tabla", TABLAS_POR_CUENTA)
def test_un_usuario_ajeno_no_ve_nada(tabla):
    _usuario, cuenta_id = _primer_usuario_con_cuenta()
    with db.conexion_usuario(999999999, cuenta_id) as c:
        cur = c.cursor()
        cur.execute(f"SELECT count(*) FROM {tabla}")
        assert cur.fetchone()[0] == 0


def test_la_cuenta_propia_si_ve_sus_datos():
    usuario_id, cuenta_id = _primer_usuario_con_cuenta()
    with db.conexion_usuario(usuario_id, cuenta_id) as c:
        cur = c.cursor()
        cur.execute("SELECT count(*) FROM productos_padre")
        assert cur.fetchone()[0] > 0
