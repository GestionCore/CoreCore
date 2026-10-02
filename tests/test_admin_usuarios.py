"""Panel /admin: cuántos días le quedan a cada prueba, quién es "activo" y la extensión de la prueba (esta última contra la base real, revertida)."""
import os
from datetime import date, datetime, timedelta, timezone

import pytest

import admin_usuarios as au

AHORA = datetime(2026, 10, 2, 15, 0, tzinfo=timezone.utc)
HOY = date(2026, 10, 2)


def _fila(uid=1, plan="trial", fin=None, activo=True, visita=None):
    return (uid, f"u{uid}@x.com", "", plan, activo, AHORA - timedelta(days=20), fin, True, 1, AHORA, 0, True, visita)


def test_dias_de_prueba_vence_hoy_manana_y_vencida():
    assert au.dias_de_prueba("trial", AHORA + timedelta(hours=5), AHORA) == 0           # vence hoy
    assert au.dias_de_prueba("trial", AHORA + timedelta(days=3, hours=2), AHORA) == 3
    assert au.dias_de_prueba("trial", AHORA - timedelta(hours=1), AHORA) == -1          # venció hace una hora: ya está vencida
    assert au.dias_de_prueba("trial", AHORA - timedelta(days=2, hours=3), AHORA) == -3


def test_dias_de_prueba_solo_para_el_plan_trial_con_fecha():
    assert au.dias_de_prueba("base", AHORA + timedelta(days=5), AHORA) is None
    assert au.dias_de_prueba("trial", None, AHORA) is None
    assert au.dias_de_prueba("trial", "", AHORA) is None


def test_estadisticas_por_vencer_vencidas_y_activos():
    filas = [
        _fila(1, fin=AHORA + timedelta(days=2), visita=HOY),                       # por vencer, activo hoy
        _fila(2, fin=AHORA - timedelta(days=5), visita=HOY - timedelta(days=30)),  # vencida, inactiva
        _fila(3, fin=AHORA + timedelta(days=12), visita=HOY - timedelta(days=7)),  # sobrada, activa (7 días justo)
        _fila(4, plan="base", visita=HOY - timedelta(days=8)),                     # base, ya no activa
        _fila(5, plan="elite", activo=False, visita=None),
    ]
    usuarios, s = au.armar_usuarios(filas, HOY, AHORA)
    assert len(usuarios) == 5
    assert (s["total"], s["trial"], s["base"], s["elite"], s["inactivos"]) == (5, 3, 1, 1, 1)
    assert (s["por_vencer"], s["vencidas"], s["activos_7d"]) == (1, 1, 2)


def test_el_panel_renderiza_con_estas_filas():
    """Que la plantilla acepte lo que arma el módulo (fechas como date/datetime, sin visita, pruebas vencidas)."""
    pytest.importorskip("flask")
    if not os.getenv("DATABASE_URL"):
        pytest.skip("importar app abre el pool: sin DATABASE_URL se omite")
    import app as aplicacion
    usuarios, stats = au.armar_usuarios([_fila(1, fin=AHORA - timedelta(days=1), visita=HOY), _fila(2, plan="base"), _fila(3, fin=AHORA + timedelta(days=2))], HOY, AHORA)
    with aplicacion.app.test_request_context("/admin"):
        aplicacion.g.usuario_id, aplicacion.g.cuenta_id = 1, 1
        html = aplicacion.render_template("admin_panel.html", active_nav="admin", usuarios=usuarios, stats=stats)
    assert "vencida" in html and "+7 días" in html and "por vencer" in html


# ── Contra la base real: la sentencia de extender la prueba (todo dentro de una transacción que se revierte) ──────────────────────

class _Revertir(Exception):
    pass


def _extender_en_transaccion(plan, fin_sql, dias):
    import db
    resultado = {}
    try:
        with db.conexion_admin() as c:
            cur = c.cursor()
            cur.execute(f"INSERT INTO usuarios (email, plan, trial_termina_en) VALUES ('prueba-trial-{os.getpid()}@test.invalid', %s, {fin_sql}) RETURNING id, now()", (plan,))
            uid, ahora_db = cur.fetchone()
            resultado["fin"] = au.extender_prueba(cur, uid, dias)
            resultado["ahora"] = ahora_db
            raise _Revertir()
    except _Revertir:
        pass
    return resultado


@pytest.mark.db
@pytest.mark.skipif(not os.getenv("DATABASE_URL_ADMIN"), reason="Sin DATABASE_URL_ADMIN")
def test_extender_una_prueba_vencida_cuenta_desde_hoy():
    r = _extender_en_transaccion("trial", "now() - interval '10 days'", 7)
    assert r["fin"] - r["ahora"] == timedelta(days=7)


@pytest.mark.db
@pytest.mark.skipif(not os.getenv("DATABASE_URL_ADMIN"), reason="Sin DATABASE_URL_ADMIN")
def test_extender_una_prueba_vigente_suma_a_su_fecha_de_fin():
    r = _extender_en_transaccion("trial", "now() + interval '5 days'", 7)
    assert r["fin"] - r["ahora"] == timedelta(days=12)


@pytest.mark.db
@pytest.mark.skipif(not os.getenv("DATABASE_URL_ADMIN"), reason="Sin DATABASE_URL_ADMIN")
def test_no_se_extiende_la_prueba_de_quien_ya_pago_un_plan():
    assert _extender_en_transaccion("base", "now() + interval '5 days'", 7)["fin"] is None
