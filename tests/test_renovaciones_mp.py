"""Renovaciones de Mercado Pago: se consulta SOLO el día del cobro; el rechazo da 3 días de gracia y recién después se corta; las cuentas de cortesía no se tocan."""
import os
from datetime import datetime, timedelta, timezone

import pytest

import pagos
import renovaciones_mp

UTC = timezone.utc
VENCIA = datetime(2026, 11, 8, 0, 25, 37, tzinfo=UTC)               # 7/11 20:25 (-04:00)
ULTIMO_COBRO_VIEJO = "2026-10-07T20:25:38.000-04:00"                # el cobro del mes anterior
COBRO_NUEVO = "2026-11-07T20:25:38.000-04:00"
PROXIMO = "2026-12-07T20:25:37.000-04:00"


def _info(estado="authorized", ultimo=COBRO_NUEVO, proximo=PROXIMO):
    return {"status": estado, "next_payment_date": proximo, "summarized": {"last_charged_date": ultimo}}


# ── La decisión (función pura) ───────────────────────────────────────────────────────────────────────────────────────────────

def test_cobro_acreditado_anota_el_proximo_dia_y_deja_todo_como_esta():
    accion, proximo, _ = pagos.evaluar_renovacion(_info(), VENCIA, VENCIA + timedelta(hours=12))
    assert accion == "cobrado"
    assert proximo == datetime(2026, 12, 8, 0, 25, 37, tzinfo=UTC)


def test_cancelada_en_mercado_pago_da_de_baja_enseguida():
    assert pagos.evaluar_renovacion(_info("cancelled"), VENCIA, VENCIA + timedelta(hours=1))[:2] == ("cancelada", None)


def test_rechazo_dentro_de_los_3_dias_sigue_esperando_y_conserva_la_fecha():
    # Sigue «authorized» pero el último cobro es el del mes pasado: el de hoy no se acreditó (tarjeta rechazada, reintento pendiente).
    for dias in (0, 1, 2):
        accion, proximo, _ = pagos.evaluar_renovacion(_info(ultimo=ULTIMO_COBRO_VIEJO), VENCIA, VENCIA + timedelta(days=dias, hours=9))
        assert (accion, proximo) == ("esperar", VENCIA), dias


def test_pasados_los_3_dias_sin_cobro_se_corta():
    assert pagos.DIAS_DE_GRACIA_COBRO == 3
    assert pagos.evaluar_renovacion(_info(ultimo=ULTIMO_COBRO_VIEJO), VENCIA, VENCIA + timedelta(days=3))[0] == "esperar"      # justo a los 3 días todavía no
    assert pagos.evaluar_renovacion(_info(ultimo=ULTIMO_COBRO_VIEJO), VENCIA, VENCIA + timedelta(days=3, hours=1))[0] == "sin_cobro"
    assert pagos.evaluar_renovacion(_info("paused", ultimo=ULTIMO_COBRO_VIEJO), VENCIA, VENCIA + timedelta(days=4))[0] == "sin_cobro"


def test_si_el_cobro_pasa_durante_la_gracia_no_se_corta():
    # Rechazado el día 0 y reintentado con éxito el día 2: el chequeo del día 2 lo ve acreditado.
    accion, _, _ = pagos.evaluar_renovacion(_info(ultimo="2026-11-09T09:00:00.000-04:00"), VENCIA, VENCIA + timedelta(days=2, hours=12))
    assert accion == "cobrado"


def test_sin_respuesta_de_mercado_pago_no_se_cambia_nada_ni_se_corta():
    assert pagos.evaluar_renovacion(None, VENCIA, VENCIA + timedelta(days=30)) == ("esperar", VENCIA, "Mercado Pago no respondió")


def test_sin_fecha_anotada_se_completa_con_lo_que_informa_mercado_pago():
    accion, proximo, _ = pagos.evaluar_renovacion(_info(), None, VENCIA)
    assert (accion, proximo) == ("cobrado", datetime(2026, 12, 8, 0, 25, 37, tzinfo=UTC))
    accion, proximo, _ = pagos.evaluar_renovacion(_info(ultimo=None), None, VENCIA)
    assert accion == "esperar" and proximo == datetime(2026, 12, 8, 0, 25, 37, tzinfo=UTC)         # todavía sin cobro: solo se anota el día


def test_una_fecha_ilegible_no_rompe():
    assert pagos.proximo_cobro({"next_payment_date": "basura"}) is None
    assert pagos.proximo_cobro(None) is None
    assert pagos.evaluar_renovacion({"status": "authorized", "next_payment_date": "basura"}, VENCIA, VENCIA)[0] == "esperar"


# ── Contra la base real ──────────────────────────────────────────────────────────────────────────────────────────────────────

class _Revertir(Exception):
    pass


def _usuario(cur, n, plan, mp_id, proximo_sql):
    cur.execute(f"INSERT INTO usuarios (email, plan, mp_suscripcion_id, mp_proximo_cobro, activo) VALUES (%s, %s, %s, {proximo_sql}, false) RETURNING id",
                (f"prueba-renov-{os.getpid()}-{n}@test.invalid", plan, mp_id))
    return cur.fetchone()[0]


@pytest.mark.db
@pytest.mark.skipif(not os.getenv("DATABASE_URL_ADMIN"), reason="Sin DATABASE_URL_ADMIN")
def test_solo_son_candidatos_los_que_ya_les_llego_el_dia_de_cobro_y_la_cortesia_nunca():
    import db
    try:
        with db.conexion_admin() as c:
            cur = c.cursor()
            vencida = _usuario(cur, 1, "base", "mp-a", "now() - interval '1 day'")
            futura = _usuario(cur, 2, "base", "mp-b", "now() + interval '20 days'")
            cortesia = _usuario(cur, 3, "elite", None, "NULL")                   # Elite gratis a mano: sin suscripción de Mercado Pago
            sin_fecha = _usuario(cur, 4, "elite", "mp-d", "NULL")
            en_prueba = _usuario(cur, 5, "trial", "mp-e", "now() - interval '1 day'")
            ids = {i for i, *_ in renovaciones_mp.candidatos(cur)}
            assert {vencida, sin_fecha} <= ids
            assert not ({futura, cortesia, en_prueba} & ids)

            renovaciones_mp.aplicar(cur, vencida, "sin_cobro", None)
            renovaciones_mp.aplicar(cur, futura, "cobrado", datetime(2026, 12, 8, tzinfo=UTC))
            renovaciones_mp.aplicar(cur, cortesia, "cancelada", None)             # aunque se le pidiera, una cuenta sin suscripción de MP no se da de baja
            cur.execute("SELECT id, plan, mp_proximo_cobro FROM usuarios WHERE id IN (%s, %s, %s)", (vencida, futura, cortesia))
            estado = {i: (plan, prox) for i, plan, prox in cur.fetchall()}
            assert estado[vencida] == ("cancelado", None)
            assert estado[futura] == ("base", datetime(2026, 12, 8, tzinfo=UTC))
            assert estado[cortesia][0] == "elite"
            raise _Revertir()
    except _Revertir:
        pass


@pytest.mark.db
@pytest.mark.skipif(not os.getenv("DATABASE_URL_ADMIN"), reason="Sin DATABASE_URL_ADMIN")
def test_la_tarea_de_renovaciones_de_punta_a_punta_con_mercado_pago_simulado():
    import db
    ahora = datetime.now(UTC)
    ids = {}
    mp = {n: f"prueba-renov-{os.getpid()}-{n}" for n in ("cobra", "cancela", "rechaza_hoy", "rechaza_4_dias")}
    respuestas = {
        mp["cobra"]: _info(ultimo=ahora.isoformat(), proximo=(ahora + timedelta(days=30)).isoformat()),
        mp["cancela"]: _info("cancelled"),
        mp["rechaza_hoy"]: _info("paused", ultimo=(ahora - timedelta(days=30)).isoformat()),
        mp["rechaza_4_dias"]: _info("paused", ultimo=(ahora - timedelta(days=34)).isoformat()),
    }
    canceladas_en_mp = []
    try:
        with db.conexion_admin() as c:
            cur = c.cursor()
            ids["cobra"] = _usuario(cur, 11, "base", mp["cobra"], "now() - interval '1 hour'")
            ids["cancela"] = _usuario(cur, 12, "elite", mp["cancela"], "now() - interval '1 hour'")
            ids["rechaza_hoy"] = _usuario(cur, 13, "base", mp["rechaza_hoy"], "now() - interval '1 hour'")
            ids["rechaza_4_dias"] = _usuario(cur, 14, "base", mp["rechaza_4_dias"], "now() - interval '4 days'")
        resumen = renovaciones_mp.chequear_renovaciones(ahora=ahora, obtener=lambda mp_id: respuestas.get(mp_id), cancelar=lambda mp_id: canceladas_en_mp.append(mp_id) or True)
        assert resumen["errores"] == 0 and resumen["cobrado"] == 1 and resumen["cancelada"] == 1 and resumen["sin_cobro"] == 1
        with db.conexion_admin() as c:
            cur = c.cursor()
            cur.execute("SELECT id, plan, mp_proximo_cobro FROM usuarios WHERE id = ANY(%s)", (list(ids.values()),))
            estado = {i: (plan, prox) for i, plan, prox in cur.fetchall()}
        assert estado[ids["cobra"]][0] == "base" and estado[ids["cobra"]][1] > ahora + timedelta(days=29)
        assert estado[ids["cancela"]] == ("cancelado", None)
        assert estado[ids["rechaza_hoy"]][0] == "base"                  # dentro de los 3 días: se sigue mirando, no se corta
        assert estado[ids["rechaza_4_dias"]] == ("cancelado", None)     # pasados los 3 días sin cobro: se corta…
        assert canceladas_en_mp == [mp["rechaza_4_dias"]]                # …y se cancela también en Mercado Pago (la cancelada por MP ya lo está)
    finally:
        with db.conexion_admin() as c:
            c.cursor().execute("DELETE FROM usuarios WHERE email LIKE %s", (f"prueba-renov-{os.getpid()}-%@test.invalid",))


def test_la_tarea_diaria_no_hace_nada_sin_cobro_habilitado(monkeypatch):
    import config
    import renovaciones_mp as modulo
    import scheduler
    monkeypatch.setattr(config, "PAGOS_HABILITADOS", False)
    monkeypatch.setattr(modulo, "chequear_renovaciones", lambda *a, **k: pytest.fail("no debe consultar nada en la beta gratuita"))
    scheduler._tarea_renovaciones_mp()
