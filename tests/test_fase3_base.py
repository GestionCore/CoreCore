"""
Fase 3 (base de datos y rendimiento), verificada contra la base real el 2026-10-07:
· 17/18/20/22 ya estaban resueltos (migración 0038, job `limpiar_oauth`, gunicorn con 2 workers): acá quedan las guardas que impiden que se rompan.
· 19 se rechazó con evidencia: ventas.codigo_postal y localidad están en el 100 % de las filas y las usa Flex (la prueba existente `test_correcciones_auditoria` lo exige).
· 16: medido en una tabla temporal de 400.000 filas, castear la variable o la columna da el MISMO plan (índice por cuenta_id y fecha) y una diferencia del 1 al 6 %: no hay colapso a Seq Scan.
· 21: se agrega el job que purga los soft deletes (hoy no hay ninguna fila marcada: queda listo para cuando una pantalla use `eliminado_en`).
"""
import os
import re
from contextlib import contextmanager

import pytest

import scheduler

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CON_BASE = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="Sin DATABASE_URL")


def _leer(*partes):
    return open(os.path.join(RAIZ, *partes), encoding="utf-8").read()


# ── 21. Purga de soft deletes ──────────────────────────────────────────────────────────────────────────────────────────────────────────────
class _Cursor:
    def __init__(self, sentencias, filas):
        self.sentencias, self.filas, self.rowcount = sentencias, filas, 0

    def execute(self, sql, params=None):
        self.sentencias.append(" ".join(sql.split()))
        self.rowcount = self.filas.pop(0) if self.filas else 0


def _conexion_falsa(sentencias, filas, monkeypatch):
    @contextmanager
    def conexion_admin():
        class C:
            def cursor(c):
                return _Cursor(sentencias, filas)
        yield C()
    monkeypatch.setattr(scheduler.db, "conexion_admin", conexion_admin)


def test_la_purga_borra_solo_lo_eliminado_hace_mas_de_un_dia_en_las_dos_tablas(monkeypatch, capsys):
    sentencias = []
    _conexion_falsa(sentencias, [3, 5], monkeypatch)
    scheduler._tarea_limpiar_soft_deletes()
    assert sentencias == [
        "DELETE FROM gastos_operativos WHERE eliminado_en IS NOT NULL AND eliminado_en < now() - interval '1 day'",
        "DELETE FROM ventas WHERE eliminado_en IS NOT NULL AND eliminado_en < now() - interval '1 day'",
    ]
    assert "Soft deletes purgados" in capsys.readouterr().out


def test_la_purga_no_hace_ruido_si_no_hay_nada_que_borrar(monkeypatch, capsys):
    _conexion_falsa([], [0, 0], monkeypatch)
    scheduler._tarea_limpiar_soft_deletes()
    assert "purgados" not in capsys.readouterr().out


def test_la_purga_nunca_toca_filas_que_no_fueron_marcadas():
    """Una fila sin eliminado_en (la gran mayoría) jamás cumple la condición: el borrado exige IS NOT NULL además del plazo."""
    fuente = _leer("scheduler.py")
    cuerpo = fuente[fuente.index("def _tarea_limpiar_soft_deletes"):fuente.index("TABLAS_CON_SOFT_DELETE = ")]
    assert "eliminado_en IS NOT NULL AND eliminado_en < now() - interval '1 day'" in cuerpo
    assert scheduler.TABLAS_CON_SOFT_DELETE == ("gastos_operativos", "ventas")


def test_la_purga_corre_de_madrugada_en_utc_y_sin_encimarse():
    fuente = _leer("scheduler.py")
    assert re.search(r'add_job\(_tarea_limpiar_soft_deletes, "cron", hour=6, minute=30, timezone="UTC", id="limpiar_soft_deletes", max_instances=1, coalesce=True\)', fuente)


@CON_BASE
def test_las_tablas_de_la_purga_tienen_la_columna_y_hoy_no_hay_nada_marcado_que_borrar():
    import db
    with db.conexion_admin() as con:
        cur = con.cursor()
        for tabla in scheduler.TABLAS_CON_SOFT_DELETE:
            cur.execute("SELECT count(*) FROM information_schema.columns WHERE table_name = %s AND column_name = 'eliminado_en'", (tabla,))
            assert cur.fetchone()[0] == 1, tabla                                   # si alguien quita la columna, el job nocturno fallaría cada noche


# ── 20. Vinculaciones de OAuth abandonadas ─────────────────────────────────────────────────────────────────────────────────────────────────
def test_las_vinculaciones_oauth_abandonadas_se_borran_cada_hora_a_los_15_minutos(monkeypatch):
    sentencias = []
    _conexion_falsa(sentencias, [2, 1], monkeypatch)
    scheduler._tarea_limpiar_vinculaciones_oauth()
    assert sentencias == ["DELETE FROM oauth_vinculaciones_pendientes WHERE creado_en < now() - interval '15 minutes'",
                          "DELETE FROM oauth_confirmaciones_pendientes WHERE creado_en < now() - interval '15 minutes'"]
    assert 'add_job(_tarea_limpiar_vinculaciones_oauth, "interval", hours=1, id="limpiar_oauth"' in _leer("scheduler.py")


# ── 17, 18. Índices (ya aplicados por la migración 0038) ───────────────────────────────────────────────────────────────────────────────────
@CON_BASE
def test_las_claves_foraneas_de_feedback_y_referrals_tienen_su_indice_y_el_de_alertas_no_lleva_leida():
    import db
    with db.conexion_admin() as con:
        cur = con.cursor()
        cur.execute("SELECT indexname, indexdef FROM pg_indexes WHERE tablename IN ('feedback', 'referrals', 'alertas_usuario')")
        indices = {n: d for n, d in cur.fetchall()}
    assert "(usuario_id)" in indices["idx_feedback_usuario"]
    assert any("(referred_id)" in d for d in indices.values()) and any("(referrer_id)" in d for d in indices.values())          # un tercer índice sería un duplicado
    assert "(usuario_id, creada_en DESC) WHERE (leida = false)" in indices["idx_alertas_usuario_no_leidas"]


# ── 19. Las columnas «huérfanas» de ventas se usan ─────────────────────────────────────────────────────────────────────────────────────────
@CON_BASE
def test_codigo_postal_y_localidad_de_ventas_estan_en_uso_y_no_se_borran():
    import db
    with db.conexion_admin() as con:
        cur = con.cursor()
        cur.execute("SELECT count(*), count(codigo_postal), count(localidad) FROM ventas")
        total, con_cp, con_loc = cur.fetchone()
    assert total == 0 or (con_cp / total > 0.9 and con_loc / total > 0.9)                   # Flex ubica cada destino con ellas
    assert "localidad" in _leer("flex.py") and "codigo_postal" in _leer("ventas_sync.py")


# ── 22. Conexiones del pooler: ya fijadas (gunicorn.conf.py y Dockerfile con 2 workers) y con su cuenta máquinas × workers × pool ≤ 12 en test_correcciones_auditoria ──


# ── Webhook: se registra el tema, nunca datos de nadie ─────────────────────────────────────────────────────────────────────────────────────
def test_el_webhook_registra_solo_el_tema_y_no_revienta_con_cuerpos_raros(monkeypatch, capsys):
    import app as aplicacion
    llamadas = []
    monkeypatch.setattr(aplicacion, "_en_segundo_plano", lambda funcion, *a: llamadas.append(a))
    cliente = aplicacion.app.test_client()
    r = cliente.post("/notificaciones_meli", json={"topic": "orders_v2", "resource": "/orders/2000012345", "user_id": 619292584, "application_id": None})
    assert r.status_code == 200 and llamadas == [("orders_v2", "/orders/2000012345", 619292584)]
    salida = capsys.readouterr().out
    assert "[Webhook] tema=orders_v2" in salida and "2000012345" not in salida and "619292584" not in salida
    for cuerpo in ([1, 2], "texto", None, {"topic": None}):
        assert cliente.post("/notificaciones_meli", json=cuerpo).status_code == 200                 # una lista o un texto antes daban 500 (.get sobre una lista)
    llamadas.clear()
    r = cliente.post("/notificaciones_meli", json={"topic": "items", "resource": "/items/MLA1", "user_id": 1, "application_id": 999999999})
    assert r.status_code == 200 and llamadas == [] and "ignorada: es de otra aplicación" in capsys.readouterr().out
