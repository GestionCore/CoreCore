"""Los comentarios contra la base REAL: se guardan, son privados de cada usuario y no se pueden modificar ni borrar. Todo dentro de transacciones que se revierten."""
import os

import pytest

pytestmark = pytest.mark.db
if not os.getenv("DATABASE_URL"):
    pytest.skip("Sin DATABASE_URL: se omiten las pruebas contra la base", allow_module_level=True)

import db  # noqa: E402


class _Revertir(Exception):
    pass


def _usuario_y_cuenta():
    with db.conexion_admin() as c:
        cur = c.cursor()
        cur.execute("SELECT usuario_id, id FROM cuentas_meli ORDER BY id LIMIT 1")
        return cur.fetchone()


def test_un_comentario_se_guarda_y_otro_usuario_no_lo_ve():
    usuario_id, cuenta_id = _usuario_y_cuenta()
    vistos_por_otro = None
    try:
        with db.conexion_usuario(usuario_id, cuenta_id) as c:
            cur = c.cursor()
            cur.execute("INSERT INTO feedback (usuario_id, cuenta_id, tipo, mensaje, pantalla) VALUES (%s, %s, 'idea', 'PRUEBA AUTOMATICA', '/stock') RETURNING id", (usuario_id, cuenta_id))
            cur.execute("SELECT count(*) FROM feedback WHERE mensaje = 'PRUEBA AUTOMATICA'")
            assert cur.fetchone()[0] == 1
            raise _Revertir()
    except _Revertir:
        pass
    with db.conexion_usuario(usuario_id + 1000000, None) as c:
        cur = c.cursor()
        cur.execute("SELECT count(*) FROM feedback")
        vistos_por_otro = cur.fetchone()[0]
    assert vistos_por_otro == 0                                        # un usuario ajeno no ve comentarios de otros
    with db.conexion_usuario(usuario_id, cuenta_id) as c:
        cur = c.cursor()
        cur.execute("SELECT count(*) FROM feedback WHERE mensaje = 'PRUEBA AUTOMATICA'")
        assert cur.fetchone()[0] == 0                                  # la transacción se revirtió


def test_no_se_puede_escribir_a_nombre_de_otro_ni_modificar_o_borrar():
    usuario_id, cuenta_id = _usuario_y_cuenta()
    with pytest.raises(Exception, match="row-level security"):
        with db.conexion_usuario(usuario_id, cuenta_id) as c:
            c.cursor().execute("INSERT INTO feedback (usuario_id, tipo, mensaje) VALUES (%s, 'idea', 'intruso')", (usuario_id + 1000000,))
    for sql in ("UPDATE feedback SET atendido = true", "DELETE FROM feedback"):
        with pytest.raises(Exception, match="permission denied"):
            with db.conexion_usuario(usuario_id, cuenta_id) as c:
                c.cursor().execute(sql)
