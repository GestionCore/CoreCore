"""
Aislamiento entre cuentas y entre usuarios con Row Level Security, contra una base REAL. Se omite si no hay DATABASE_URL.
Lectura solamente: no deja nada escrito (los intentos de escritura de prueba se rechazan).
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


def test_la_auditoria_es_solo_de_agregar():
    """El rol de la app puede insertar y leer el registro de actividad, no modificarlo ni borrarlo."""
    usuario_id, cuenta_id = _primer_usuario_con_cuenta()
    for sql in ("UPDATE auditoria SET accion = 'x'", "DELETE FROM auditoria"):
        with pytest.raises(Exception, match="permission denied"):
            with db.conexion_usuario(usuario_id, cuenta_id) as c:
                c.cursor().execute(sql)


def test_la_auditoria_no_deja_escribir_a_nombre_de_otro_usuario():
    usuario_id, cuenta_id = _primer_usuario_con_cuenta()
    with pytest.raises(Exception, match="row-level security"):
        with db.conexion_usuario(usuario_id, cuenta_id) as c:
            c.cursor().execute("INSERT INTO auditoria (usuario_id, accion) VALUES (%s, 'intruso')", (usuario_id + 1000000,))


def test_un_usuario_ajeno_no_ve_la_auditoria():
    _usuario, cuenta_id = _primer_usuario_con_cuenta()
    with db.conexion_usuario(999999999, cuenta_id) as c:
        cur = c.cursor()
        cur.execute("SELECT count(*) FROM auditoria")
        assert cur.fetchone()[0] == 0
