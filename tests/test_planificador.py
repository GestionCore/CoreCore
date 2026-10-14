"""
Con RLS el planificador de Postgres estima ~1 fila por tabla grande y elige «bucles anidados» para unir ventas con publicaciones y variantes: con una cuenta grande (1.500 publicaciones, 30.000 ventas) una consulta
del Dashboard tardó 58 s y todo el recorrido de pantallas 164 s en vez de 61 s. db._dejar_lista_para_rls apaga los bucles anidados SOLO dentro de la transacción de un pedido de una persona.
"""
import os

import pytest

pytestmark = pytest.mark.db
if not os.getenv("DATABASE_URL"):
    pytest.skip("Sin DATABASE_URL", allow_module_level=True)

import db  # noqa: E402


def _estado(cur):
    cur.execute("SELECT current_setting('enable_nestloop'), current_setting('app.usuario_actual')")
    return cur.fetchone()


def test_dentro_del_pedido_de_una_persona_no_hay_bucles_anidados_y_afuera_si():
    assert db.SIN_BUCLES_ANIDADOS is True or os.getenv("DB_SIN_BUCLES_ANIDADOS") == "0"
    with db.conexion_usuario(999999999, None) as conexion:
        cur = conexion.cursor()
        nestloop, usuario = _estado(cur)
        assert nestloop == ("off" if db.SIN_BUCLES_ANIDADOS else "on") and usuario == "999999999"
    with db.conexion_usuario(999999999, None) as conexion:                          # otra transacción: vuelve a prepararse (no depende de la conexión que le tocó)
        assert _estado(conexion.cursor())[0] == ("off" if db.SIN_BUCLES_ANIDADOS else "on")
    with db.conexion_admin() as conexion:                                           # la conexión de administración (tokens, scheduler) no se toca
        cur = conexion.cursor()
        cur.execute("SELECT current_setting('enable_nestloop')")
        assert cur.fetchone()[0] == "on"


def test_se_puede_volver_atras_sin_desplegar(monkeypatch):
    monkeypatch.setattr(db, "SIN_BUCLES_ANIDADOS", False)
    with db.conexion_usuario(999999999, None) as conexion:
        assert _estado(conexion.cursor())[0] == "on"


def test_la_variable_de_entorno_decide_el_valor_por_defecto():
    fuente = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "db.py"), encoding="utf-8").read()
    assert 'SIN_BUCLES_ANIDADOS = os.getenv("DB_SIN_BUCLES_ANIDADOS", "1") != "0"' in fuente
