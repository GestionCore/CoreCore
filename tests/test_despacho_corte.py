"""
Punto 6 de la auditoría (corte de Despacho), con la resolución de Diego sobre lo que responde la API REAL (2026-10-07):
· Correo: GET /users/{id}/shipping/schedule/drop_off trae el corte POR DÍA (13:00 de lunes a viernes, sábado y domingo `work: false`). Se guarda la semana y se refresca por día.
· Flex: no hay horario de corte en la API (schedule/self_service y los endpoints de configuración dan 404): lo carga la persona (configuracion_cuenta.flex_hora_corte).
· Sin dato no se inventa nada: «Corte de correo no informado» / «Corte Flex: No configurado (Ajustar)».
"""
import os
import re
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone

import pytest

import db
import despacho_corte
import logistica

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CON_BASE = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="Sin DATABASE_URL")


def _dia(trabaja, corte=""):
    return {"work": trabaja, "is_past": False, "date": "", "detail": [{"cutoff": corte, "sla": "same_day", "logistic_type": "drop_off"}] if trabaja else []}


SCHEDULE_REAL = {"seller_id": "619292584", "schedule": {d: _dia(True, "13:00") for d in ("monday", "tuesday", "wednesday", "thursday", "friday")}
                 | {"saturday": _dia(False), "sunday": _dia(False)}}
SEMANA = {"monday": "13:00", "tuesday": "13:00", "wednesday": "13:00", "thursday": "13:00", "friday": "13:00", "saturday": None, "sunday": None}


def _leer(*partes):
    return open(os.path.join(RAIZ, *partes), encoding="utf-8").read()


# ── La hora ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_la_hora_se_normaliza_y_lo_que_no_es_una_hora_se_rechaza():
    for entrada, esperada in (("14", "14:00"), ("14:30", "14:30"), ("9:05", "09:05"), (" 8 ", "08:00"), ("14.30", "14:30"), ("00:00", "00:00"), ("23:59", "23:59"), ("14h", "14:00")):
        assert despacho_corte.normalizar_hora(entrada) == esperada, entrada
    for mala in ("", None, "24:00", "12:60", "abc", "25", "14:5", "-3", "14:30:10", "1430", "14 30 x"):
        assert despacho_corte.normalizar_hora(mala) is None, mala


# ── Correo: la semana real ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_la_semana_se_arma_con_la_respuesta_real_del_schedule():
    assert despacho_corte.semana_desde_schedule(SCHEDULE_REAL) == SEMANA
    assert set(despacho_corte.semana_desde_schedule(None).values()) == {None}
    sin_detalle = {"schedule": {"monday": {"work": True, "detail": []}, "tuesday": {"work": True, "detail": [{"cutoff": ""}]}}}
    assert despacho_corte.semana_desde_schedule(sin_detalle)["monday"] is None and despacho_corte.semana_desde_schedule(sin_detalle)["tuesday"] is None


def test_el_corte_es_el_del_dia_de_la_semana_de_la_fecha_que_se_mira():
    horario = {"drop_off": SEMANA}
    assert despacho_corte.corte_del_dia(horario, "2026-10-07") == ("13:00", "informado")                  # miércoles
    assert despacho_corte.corte_del_dia(horario, date(2026, 10, 9)) == ("13:00", "informado")             # viernes
    assert despacho_corte.corte_del_dia(horario, "2026-10-10") == (None, "sin_retiro")                    # sábado: Mercado Libre no retira
    assert despacho_corte.corte_del_dia(horario, "2026-10-11") == (None, "sin_retiro")                    # domingo
    distinto = {"drop_off": dict(SEMANA, wednesday="11:30")}
    assert despacho_corte.corte_del_dia(distinto, "2026-10-07") == ("11:30", "informado") and despacho_corte.corte_del_dia(distinto, "2026-10-08") == ("13:00", "informado")


def test_sin_horario_de_la_cuenta_se_dice_no_informado_y_no_se_inventa_ninguno():
    for horario in (None, {}, {"drop_off": None}, {"drop_off": {}}, {"actualizado_en": "x"}):
        assert despacho_corte.corte_del_dia(horario, "2026-10-07") == (None, "no_informado")


def test_el_dia_de_despacho_se_arma_con_el_corte_que_se_conoce_y_sin_corte_es_el_dia_calendario():
    horario = {"drop_off": SEMANA}
    assert despacho_corte.resolver_cortes(horario, None, "2026-10-07") == {"correo": {"hora": "13:00", "estado": "informado"}, "flex": None, "hora_agrupacion": 13}
    assert despacho_corte.resolver_cortes(None, "14:30", "2026-10-07")["hora_agrupacion"] == 14                       # sin Correo: el de Flex que cargó la persona
    assert despacho_corte.resolver_cortes(horario, "14:00", "2026-10-07")["hora_agrupacion"] == 13                    # con Correo informado manda el de Correo
    assert despacho_corte.resolver_cortes(None, None, "2026-10-07")["hora_agrupacion"] == 24                          # nada informado: 24 h = día calendario, no un 11 inventado
    assert despacho_corte.resolver_cortes(horario, None, "2026-10-10")["hora_agrupacion"] == 24                       # sábado sin retiro
    assert despacho_corte.resolver_cortes(None, "99:99", "2026-10-07")["flex"] is None                                # una hora inválida guardada no se usa


def test_el_contador_de_la_pantalla_solo_recibe_los_cortes_que_se_conocen():
    todos = despacho_corte.resolver_cortes({"drop_off": SEMANA}, "14:00", "2026-10-07")
    assert despacho_corte.cortes_js(todos) == [{"nombre": "Correo", "hora": "13:00"}, {"nombre": "Flex", "hora": "14:00"}]
    assert despacho_corte.cortes_js(despacho_corte.resolver_cortes(None, None, "2026-10-07")) == []


# ── La consulta a Mercado Libre ────────────────────────────────────────────────────────────────────────────────────────────────────────────
class Resp:
    def __init__(self, estado, cuerpo=None):
        self.status_code, self._c, self.text = estado, cuerpo, str(cuerpo)

    def json(self):
        return self._c


def test_la_consulta_semanal_distingue_ok_no_tiene_y_error(monkeypatch):
    import meli_http
    for respuesta, esperado in ((Resp(200, SCHEDULE_REAL), ("ok", SEMANA)), (Resp(404, {"message": "Seller does not have schedule"}), ("no_tiene", None)), (Resp(500, {}), ("error", None))):
        monkeypatch.setattr(meli_http, "get", lambda *a, _r=respuesta, **k: _r)
        assert logistica.obtener_horario_semanal("tok", 1, "drop_off") == esperado

    def cae(*a, **k):
        raise RuntimeError("sin red")
    monkeypatch.setattr(meli_http, "get", cae)
    assert logistica.obtener_horario_semanal("tok", 1) == ("error", None)


class _Cursor:
    def __init__(self, base):
        self.base = base

    def execute(self, sql, params=None):
        self.base.consultas.append((" ".join(sql.split()), params))

    def fetchone(self):
        return (self.base.guardado,)


class _Base:
    def __init__(self, guardado):
        self.guardado, self.consultas = guardado, []

    @contextmanager
    def conexion(self, *a, **k):
        class C:
            def cursor(c):
                return _Cursor(self)
        yield C()


def _horario(base, monkeypatch, consultar, ahora=None):
    monkeypatch.setattr(db, "conexion_usuario", base.conexion)
    return despacho_corte.horario_de_correo(1, 2, "tok", 99, ahora=ahora, consultar=consultar)


def test_un_horario_de_menos_de_un_dia_no_se_vuelve_a_pedir(monkeypatch):
    ahora = datetime(2026, 10, 7, 15, 0, tzinfo=timezone.utc)
    guardado = {"drop_off": SEMANA, "actualizado_en": (ahora - timedelta(hours=3)).isoformat()}
    base = _Base(guardado)
    assert _horario(base, monkeypatch, lambda *a: pytest.fail("no hay que consultar"), ahora) == guardado
    assert not any(q[0].startswith("UPDATE") for q in base.consultas)


def test_un_horario_viejo_se_refresca_y_se_guarda(monkeypatch):
    ahora = datetime(2026, 10, 7, 15, 0, tzinfo=timezone.utc)
    base = _Base({"drop_off": {"monday": "11:00"}, "actualizado_en": (ahora - timedelta(hours=30)).isoformat()})
    nuevo = _horario(base, monkeypatch, lambda *a: ("ok", SEMANA), ahora)
    assert nuevo["drop_off"] == SEMANA and nuevo["actualizado_en"] == ahora.isoformat()
    guardados = [q for q in base.consultas if q[0].startswith("UPDATE cuentas_meli SET horario_corte")]
    assert len(guardados) == 1 and guardados[0][1][1] == 2                                              # (json, cuenta_id)


def test_si_la_consulta_falla_se_sigue_con_lo_ultimo_guardado_y_no_se_borra(monkeypatch):
    ahora = datetime(2026, 10, 7, 15, 0, tzinfo=timezone.utc)
    viejo = {"drop_off": SEMANA, "actualizado_en": (ahora - timedelta(days=3)).isoformat()}
    base = _Base(viejo)
    assert _horario(base, monkeypatch, lambda *a: ("error", None), ahora) == viejo
    assert not any(q[0].startswith("UPDATE") for q in base.consultas)
    assert _horario(_Base(None), monkeypatch, lambda *a: ("error", None), ahora) is None                  # nunca se supo: no hay horario


def test_si_mercado_libre_dice_que_no_tiene_horario_de_correo_se_recuerda_un_dia(monkeypatch):
    ahora = datetime(2026, 10, 7, 15, 0, tzinfo=timezone.utc)
    base = _Base(None)
    nuevo = _horario(base, monkeypatch, lambda *a: ("no_tiene", None), ahora)
    assert nuevo == {"drop_off": None, "actualizado_en": ahora.isoformat()}
    assert despacho_corte.corte_del_dia(nuevo, "2026-10-07") == (None, "no_informado")


def test_si_la_columna_todavia_no_existe_la_pantalla_sigue_funcionando(monkeypatch):
    @contextmanager
    def explota(*a, **k):
        raise RuntimeError('column "horario_corte" does not exist')
        yield
    monkeypatch.setattr(db, "conexion_usuario", explota)
    assert despacho_corte.horario_de_correo(1, 2, "tok", 99) is None


# ── Flex: lo carga la persona ──────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_guardar_el_corte_de_flex_valida_y_vaciar_lo_quita():
    base = _Base(None)
    cursor = _Cursor(base)
    assert despacho_corte.guardar_flex(cursor, 7, "14") == "14:00"
    assert "INSERT INTO configuracion_cuenta" in base.consultas[-1][0] and base.consultas[-1][1] == (7, "flex_hora_corte", "14:00")
    assert despacho_corte.guardar_flex(cursor, 7, "") is None and base.consultas[-1][0].startswith("DELETE FROM configuracion_cuenta")
    n = len(base.consultas)
    assert despacho_corte.guardar_flex(cursor, 7, "25:00") is False and len(base.consultas) == n                  # una hora inválida no toca la base


@CON_BASE
def test_el_corte_de_flex_se_guarda_y_se_lee_en_la_base_real_y_se_deshace():
    class Deshacer(Exception):
        pass
    try:
        with db.conexion_admin() as con:
            cur = con.cursor()
            cur.execute("SELECT id FROM cuentas_meli ORDER BY id LIMIT 1")
            cuenta = cur.fetchone()[0]
            assert despacho_corte.guardar_flex(cur, cuenta, "14:30") == "14:30"
            assert despacho_corte.guardar_flex(cur, cuenta, "15:00") == "15:00"                                    # el ON CONFLICT pisa
            assert despacho_corte.leer_flex(cur, cuenta) == "15:00"
            assert despacho_corte.guardar_flex(cur, cuenta, "") is None and despacho_corte.leer_flex(cur, cuenta) is None
            raise Deshacer()
    except Deshacer:
        pass


# ── Pantallas ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def _pagina(**cambios):
    import app as aplicacion
    from tests.test_dia_a_dia import CONTEXTO
    contexto = dict(CONTEXTO, **cambios)
    with aplicacion.app.test_request_context("/dia"):
        html = aplicacion.render_template("dia.html", active_nav="despacho", errores={}, **contexto)
    return html.split('id="despacho"')[1].split("</section>")[0]


@CON_BASE
def test_despacho_muestra_el_corte_de_correo_informado_y_flex_sin_configurar_con_su_link():
    sub = _pagina(flex_habilitado=True)
    assert "corte de Correo <strong>13:00</strong>" in sub
    assert "Corte Flex: No configurado" in sub and re.search(r'<a href="/cuenta#flex-corte"[^>]*>\(Ajustar\)</a>', sub)


@CON_BASE
def test_despacho_con_flex_configurado_lo_muestra_y_permite_cambiarlo():
    sub = _pagina(flex_habilitado=True, corte_flex="14:00", cortes_js=[{"nombre": "Correo", "hora": "13:00"}, {"nombre": "Flex", "hora": "14:00"}])
    assert "corte Flex <strong>14:00</strong>" in sub and "(Cambiar)" in sub and "No configurado" not in sub
    assert '{"hora": "14:00", "nombre": "Flex"}' in sub or '"nombre": "Flex"' in sub                            # el contador lo recibe


@CON_BASE
def test_despacho_sin_horario_de_correo_no_inventa_uno_ni_nombra_el_11():
    sub = _pagina(corte_correo={"hora": None, "estado": "no_informado"}, cortes_js=[])
    assert "Corte de correo no informado" in sub and "11:00" not in sub and "corte a las" not in sub
    assert "Corte Flex" not in sub and "Ajustar" not in sub                                                      # sin Flex habilitado no se le pide nada de Flex


@CON_BASE
def test_despacho_un_sabado_dice_que_correo_no_retira():
    sub = _pagina(corte_correo={"hora": None, "estado": "sin_retiro"}, cortes_js=[])
    assert "Correo no retira este día" in sub


def test_la_pantalla_ya_no_tiene_un_corte_fijo_y_el_contador_usa_la_hora_de_argentina():
    t = _leer("templates", "_dia_despacho.html")
    assert "HORA_CORTE" not in t and "hora_corte" not in t and "const CORTES" in t and "ahoraArgentina().minutos" in t
    app = _leer("app.py")
    assert "hora_corte = 11" not in app and "obtener_horario_corte_hoy" not in app                             # el 11 inventado ya no existe


def test_mi_cuenta_tiene_el_campo_del_corte_de_flex_y_su_endpoint_esta_auditado():
    t = _leer("templates", "cuenta.html")
    assert 'id="flex-corte"' in t and 'type="time"' in t and "/api/cuenta/flex_hora_corte" in t
    app = _leer("app.py")
    bloque = app[app.index('@app.route("/api/cuenta/flex_hora_corte"'):app.index('@app.route("/cuenta/descargar_datos"')]
    assert "@login_requerido" in bloque and '@auditar("flex_hora_corte")' in bloque
    assert "flex_hora_corte" in _leer("auditoria.py")


def test_las_migraciones_agregan_solo_la_columna_del_horario():
    sql = _leer("migrations", "0041_horario_corte.sql")
    instrucciones = "\n".join(l for l in sql.splitlines() if not l.strip().startswith("--")).upper()               # sin los comentarios (hablan de «drop_off»)
    assert "ADD COLUMN IF NOT EXISTS HORARIO_CORTE JSONB" in instrucciones and "DROP" not in instrucciones and "UPDATE" not in instrucciones
