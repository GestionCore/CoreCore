"""
Aislamiento por CUENTA ACTIVA en TODA tabla con cuenta_id, contra la base real (se omite sin DATABASE_URL). Dos pruebas generales, para que una tabla nueva (o una
migración que recree una política, como hizo la 0014 con Tendencias) no deje a un usuario con 2 cuentas viendo los datos de ambas mezclados:

  1. cada tabla con cuenta_id tiene una política que mira la cuenta activa (app.cuenta_actual), salvo las que son del USUARIO a propósito;
  2. con una cuenta activa, ninguna de esas tablas devuelve filas de otra cuenta del mismo usuario.

Todo es lectura, salvo la prueba del margen, que escribe dentro de una transacción que se revierte.
"""
import os

import pytest

pytestmark = pytest.mark.db
if not os.getenv("DATABASE_URL"):
    pytest.skip("Sin DATABASE_URL: se omiten las pruebas contra la base", allow_module_level=True)

import db  # noqa: E402

# Tienen cuenta_id pero pertenecen a la PERSONA, no a una cuenta de Mercado Libre (su política es por usuario a propósito), o no se leen con el rol de la app.
POR_USUARIO_A_PROPOSITO = {"alertas_usuario", "auditoria", "feedback", "meli_tokens"}


class _Revertir(Exception):
    pass


def _tablas_con_cuenta():
    with db.conexion_admin() as c:
        cur = c.cursor()
        cur.execute("SELECT DISTINCT table_name FROM information_schema.columns WHERE table_schema = 'public' AND column_name = 'cuenta_id' ORDER BY 1")
        return [r[0] for r in cur.fetchall()]


def _usuario_con_mas_cuentas():
    with db.conexion_admin() as c:
        cur = c.cursor()
        cur.execute("SELECT usuario_id, array_agg(id ORDER BY id) FROM cuentas_meli GROUP BY usuario_id ORDER BY count(*) DESC, usuario_id LIMIT 1")
        return cur.fetchone()


def test_toda_tabla_con_cuenta_id_tiene_politica_por_cuenta_activa():
    with db.conexion_admin() as c:
        cur = c.cursor()
        cur.execute("SELECT tablename, qual FROM pg_policies WHERE schemaname = 'public'")
        politicas = {}
        for tabla, qual in cur.fetchall():
            politicas.setdefault(tabla, []).append(qual or "")
    sin_cuenta_activa = [t for t in _tablas_con_cuenta()
                         if t not in POR_USUARIO_A_PROPOSITO and not any("cuenta_actual" in q for q in politicas.get(t, []))]
    assert not sin_cuenta_activa, (
        f"Estas tablas filtran por usuario pero NO por la cuenta activa: {sin_cuenta_activa}. Un usuario con 2 cuentas vería los datos de ambas mezclados. "
        "Copiar la política de ventas (migración 0010 / 0036) o, si la tabla es de la persona y no de una cuenta, agregarla a POR_USUARIO_A_PROPOSITO.")


def test_con_una_cuenta_activa_no_se_ven_filas_de_otra_cuenta_del_mismo_usuario():
    usuario_id, cuentas = _usuario_con_mas_cuentas()
    if len(cuentas) < 2:
        pytest.skip("Hace falta un usuario con 2 cuentas para esta prueba")
    for activa in cuentas:
        with db.conexion_usuario(usuario_id, activa) as conexion:
            cursor = conexion.cursor()
            for tabla in _tablas_con_cuenta():
                if tabla in POR_USUARIO_A_PROPOSITO:
                    continue
                cursor.execute("SAVEPOINT t")
                try:
                    cursor.execute(f'SELECT DISTINCT cuenta_id FROM "{tabla}"')
                    vistas = {fila[0] for fila in cursor.fetchall()}
                    cursor.execute("RELEASE SAVEPOINT t")
                except Exception:
                    cursor.execute("ROLLBACK TO SAVEPOINT t")      # una tabla que el rol no puede leer no es una fuga
                    continue
                assert vistas <= {activa}, f"{tabla}: con la cuenta {activa} activa se ven filas de {sorted(vistas - {activa})}"


def test_la_app_puede_guardar_el_margen_minimo_de_su_cuenta_y_el_rango_se_respeta():
    import preferencias
    usuario_id, cuentas = _usuario_con_mas_cuentas()
    try:
        with db.conexion_usuario(usuario_id, cuentas[0]) as conexion:
            cursor = conexion.cursor()
            assert preferencias.guardar_margen_minimo(cursor, cuentas[0], "22,5") == 22.5
            cursor.execute("SELECT margen_minimo FROM cuentas_meli WHERE id = %s", (cuentas[0],))
            assert float(cursor.fetchone()[0]) == 22.5
            cursor.execute("SAVEPOINT r")
            with pytest.raises(Exception, match="margen_minimo_rango"):
                cursor.execute("UPDATE cuentas_meli SET margen_minimo = 80 WHERE id = %s", (cuentas[0],))      # la base también defiende el rango
            cursor.execute("ROLLBACK TO SAVEPOINT r")
            raise _Revertir()
    except _Revertir:
        pass
    assert preferencias.margenes_de_usuario(usuario_id)[cuentas[0]] == 15.0           # nada quedó guardado
