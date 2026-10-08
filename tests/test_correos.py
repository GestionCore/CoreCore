"""
Mails del servicio (correos.py): cobro que no se pudo hacer, plan dado de baja o cambiado, fin de la prueba.
Lo que tiene que cumplirse siempre: APAGADO sin configuración (ni HTTP ni base), nunca un mail a un email provisorio, cada aviso una sola vez, un envío fallido se reintenta,
y nada de esto puede levantar una excepción dentro de un pago, una baja o un webhook. Ningún mail real sale de estas pruebas: el proveedor está simulado.
"""
import logging
import os
from datetime import datetime, timedelta, timezone

import pytest

import correos
import db
import pagos
import renovaciones_mp

UTC = timezone.utc
CONFIG = {"CORREO_PROVEEDOR": "resend", "CORREO_API_KEY": "clave-de-prueba-123", "CORREO_REMITENTE": "CoreLux <avisos@corelux.app>"}


@pytest.fixture
def mails_encendidos(monkeypatch):
    for k, v in CONFIG.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("CORREO_RESPONDER_A", raising=False)


@pytest.fixture(autouse=True)
def sin_configuracion_por_defecto(monkeypatch):
    for k in list(CONFIG) + ["CORREO_RESPONDER_A", "APP_URL"]:
        monkeypatch.delenv(k, raising=False)


class _Resp:
    def __init__(self, codigo=200, texto="{}"):
        self.status_code, self.text = codigo, texto


def _proveedor(monkeypatch, codigo=200):
    """Simula la API de Resend; devuelve la lista de pedidos hechos."""
    pedidos = []

    def falso(url, json=None, headers=None, timeout=None):
        pedidos.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        if isinstance(codigo, Exception):
            raise codigo
        return _Resp(codigo, '{"message": "algo salió mal"}' if codigo >= 400 else '{"id": "abc"}')
    monkeypatch.setattr(correos.requests, "post", falso)
    return pedidos


# ── Apagado por defecto ────────────────────────────────────────────────────────────────────────────────────────────────────

def test_sin_configuracion_esta_apagado_y_no_toca_ni_la_red_ni_la_base(monkeypatch):
    assert correos.habilitado() is False and correos.configuracion() is None
    monkeypatch.setattr(correos.requests, "post", lambda *a, **k: pytest.fail("no debe haber ningún pedido HTTP"))
    monkeypatch.setattr(correos.db, "conexion_usuario", lambda *a, **k: pytest.fail("no debe tocar la base"))
    assert correos.enviar("alguien@ejemplo.com", "Asunto", "Texto") == "apagado"
    assert correos.avisar(1, "alguien@ejemplo.com", "cobro_pendiente", "2026-11-08", plan="base") == "apagado"


def test_hace_falta_la_configuracion_completa_y_un_proveedor_conocido(monkeypatch):
    for faltante in CONFIG:
        for k, v in CONFIG.items():
            monkeypatch.setenv(k, v)
        monkeypatch.delenv(faltante)
        assert correos.habilitado() is False, faltante
    for k, v in CONFIG.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("CORREO_PROVEEDOR", "proveedor-que-no-existe")
    assert correos.habilitado() is False
    monkeypatch.setenv("CORREO_PROVEEDOR", "  Resend ")
    assert correos.habilitado() is True


# ── Envío ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_el_envio_por_resend_arma_el_pedido_con_la_clave_en_la_cabecera(mails_encendidos, monkeypatch):
    pedidos = _proveedor(monkeypatch)
    monkeypatch.setenv("CORREO_RESPONDER_A", "soporte@corelux.app")
    assert correos.enviar("  persona@ejemplo.com ", "Hola", "Texto plano", "<p>Texto</p>") == "enviado"
    p = pedidos[0]
    assert p["url"] == "https://api.resend.com/emails" and p["timeout"] == 10
    assert p["headers"] == {"Authorization": "Bearer clave-de-prueba-123"}
    assert p["json"] == {"from": "CoreLux <avisos@corelux.app>", "to": ["persona@ejemplo.com"], "subject": "Hola", "text": "Texto plano", "html": "<p>Texto</p>", "reply_to": "soporte@corelux.app"}


@pytest.mark.parametrize("destino", ["", None, "sin-arroba", "meli-123@pendiente.corelux.app", "META-9@Pendiente.CoreLux.app", "a@b.com\nbcc: otra@x.com", "a b@c.com", "a@b.com,c@d.com", "<a@b.com>"])
def test_nunca_se_manda_a_un_destino_inservible(mails_encendidos, monkeypatch, destino):
    pedidos = _proveedor(monkeypatch)
    assert correos.enviar(destino, "Asunto", "Texto") == "descartado"
    assert pedidos == []


def test_un_asunto_con_salto_de_linea_se_descarta(mails_encendidos, monkeypatch):
    pedidos = _proveedor(monkeypatch)
    assert correos.enviar("a@b.com", "Asunto\nBcc: x@y.com", "Texto") == "descartado" and pedidos == []


@pytest.mark.parametrize("falla", [500, 422, 401, ConnectionError("se cortó"), TimeoutError("lento")])
def test_un_fallo_del_proveedor_es_error_sin_excepcion_y_sin_filtrar_datos(mails_encendidos, monkeypatch, caplog, falla):
    _proveedor(monkeypatch, codigo=falla)
    with caplog.at_level(logging.WARNING, logger="corelux.correos"):
        assert correos.enviar("persona@ejemplo.com", "Asunto", "Cuerpo secreto") == "error"
    registro = " ".join(r.getMessage() for r in caplog.records)
    assert "persona@ejemplo.com" not in registro and "Cuerpo secreto" not in registro and "clave-de-prueba" not in registro      # el log dice qué falló, no a quién ni qué decía


# ── Textos ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_todos_los_tipos_se_redactan_con_asunto_texto_y_html():
    for tipo in correos.TIPOS:
        asunto, texto, html = correos.componer(tipo, plan="base", plan_anterior="base", plan_nuevo="elite", proximo_cobro=datetime(2026, 12, 8, tzinfo=UTC),
                                               limite=datetime(2026, 11, 11, tzinfo=UTC), termina_en=datetime(2026, 11, 8, tzinfo=UTC))
        assert asunto and "\n" not in asunto and texto.startswith("Hola,") and texto.rstrip().endswith("CoreLux")
        assert "None" not in texto and "None" not in html and "{" not in texto                      # nada de datos faltantes impresos como «None» ni de plantillas sin completar
        assert "https://corelux.app/" in texto and 'href="https://corelux.app/' in html


def test_un_tipo_desconocido_no_se_manda():
    assert correos.redactar("inventado") is None and correos.componer("inventado") is None


def test_el_cobro_pendiente_dice_hasta_cuando_sigue_activo_el_plan_sin_prometer_reintentos():
    asunto, texto, _ = correos.componer("cobro_pendiente", plan="elite", limite=datetime(2026, 11, 11, tzinfo=UTC))
    assert asunto == "No pudimos cobrar tu plan de CoreLux"
    assert "Plan Elite ($99.000 por mes)" in texto and "sigue activo hasta el 11 nov" in texto
    assert "puede volver a intentar" in texto and "garantiz" not in texto.lower()


def test_el_cambio_de_plan_aclara_que_no_hubo_cobro_adicional_y_cuando_se_paga_el_nuevo_monto():
    asunto, texto, _ = correos.componer("plan_cambiado", plan_anterior="base", plan_nuevo="elite", proximo_cobro=datetime(2026, 12, 8, 3, tzinfo=UTC))
    assert asunto == "Tu plan ahora es Plan Elite"
    assert "pasó de Plan Base a Plan Elite" in texto and "ningún cobro adicional" in texto and "pagás $99.000 por mes" in texto and "8 dic" in texto
    _, sin_fecha, _ = correos.componer("plan_cambiado", plan_nuevo="elite")                              # sin la fecha del próximo cobro se omite, no se inventa
    assert "Desde tu próximo cobro pagás $99.000" in sin_fecha


def test_el_plan_dado_de_baja_nombra_los_dias_de_gracia_reales():
    _, texto, _ = correos.componer("plan_dado_de_baja", plan="base")
    assert f"dentro de los {pagos.DIAS_DE_GRACIA_COBRO} días" in texto and "Tus datos quedan guardados" in texto


def test_el_html_escapa_lo_que_viene_de_afuera():
    _, _, html = correos.componer("plan_cambiado", plan_anterior="<script>alert(1)</script>", plan_nuevo="elite")
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_el_enlace_base_se_puede_cambiar_por_entorno(monkeypatch):
    monkeypatch.setenv("APP_URL", "https://beta.corelux.app/")
    _, texto, _ = correos.componer("prueba_vencida")
    assert "https://beta.corelux.app/planes" in texto and "https://corelux.app" not in texto


# ── Qué mail corresponde a cada decisión de renovación ─────────────────────────────────────────────────────────────────────

VENCIA = datetime(2026, 11, 8, 0, 25, tzinfo=UTC)


def test_cada_decision_de_renovacion_pide_su_mail():
    av = renovaciones_mp.avisos_de_renovacion
    assert av("base", "mp-1", "sin_cobro", VENCIA, VENCIA + timedelta(days=4)) == [("plan_dado_de_baja", "mp-1", {"plan": "base"})]
    assert av("elite", "mp-2", "cancelada", VENCIA, VENCIA + timedelta(hours=2)) == [("suscripcion_cancelada", "mp-2", {"plan": "elite"})]
    assert av("base", "mp-1", "cobrado", VENCIA, VENCIA + timedelta(hours=2)) == []


def test_el_cobro_pendiente_se_avisa_recien_al_dia_siguiente_y_una_vez_por_ciclo():
    av = renovaciones_mp.avisos_de_renovacion
    assert av("base", "mp-1", "esperar", VENCIA, VENCIA + timedelta(hours=9)) == []                    # unas horas después: puede ser un cobro sin procesar, no un rechazo
    assert av("base", "mp-1", "esperar", None, VENCIA) == []                                          # sin día de cobro anotado: no hay de qué avisar
    [(tipo, clave, datos)] = av("base", "mp-1", "esperar", VENCIA, VENCIA + timedelta(days=1, hours=1))
    assert (tipo, clave) == ("cobro_pendiente", "2026-11-08") and datos == {"plan": "base", "limite": VENCIA + timedelta(days=pagos.DIAS_DE_GRACIA_COBRO)}
    otra_corrida = av("base", "mp-1", "esperar", VENCIA, VENCIA + timedelta(days=2, hours=1))
    assert otra_corrida[0][1] == clave                                                                # mismo ciclo = misma clave: la tabla de envíos evita el duplicado


def test_con_los_mails_apagados_la_tarea_de_renovaciones_no_busca_ni_el_email(monkeypatch):
    monkeypatch.setattr(renovaciones_mp, "_email_de", lambda *a: pytest.fail("no debe consultar el email con los mails apagados"))
    renovaciones_mp._mandar_avisos(None, 1, [("plan_dado_de_baja", "mp-1", {"plan": "base"})])


def test_un_fallo_al_avisar_no_corta_la_tarea(monkeypatch, capsys):
    monkeypatch.setattr(renovaciones_mp, "_email_de", lambda *a: "a@b.com")
    def roto(*a, **k):
        raise RuntimeError("se cayó el proveedor")
    renovaciones_mp._mandar_avisos(roto, 1, [("plan_dado_de_baja", "mp-1", {"plan": "base"})])
    assert "no se pudo mandar el aviso" in capsys.readouterr().out


# ── Una sola vez, contra la base real (todo revertido) ───────────────────────────────────────────────────────────────────

class _Revertir(Exception):
    pass


class _MismaConexion:
    """Reemplaza db.conexion_usuario por la conexión de la prueba, que no confirma nada."""

    def __init__(self, conexion):
        self.conexion = conexion

    def __call__(self, usuario_id, cuenta_id=None):
        return self

    def __enter__(self):
        return self.conexion

    def __exit__(self, *a):
        return False


@pytest.mark.db
@pytest.mark.skipif(not os.getenv("DATABASE_URL_ADMIN"), reason="Sin DATABASE_URL_ADMIN")
def test_cada_aviso_sale_una_vez_se_reintenta_si_falla_y_un_hecho_nuevo_si_se_avisa(mails_encendidos, monkeypatch):
    try:
        with db.conexion_admin() as c:
            cur = c.cursor()
            cur.execute("INSERT INTO usuarios (email, plan, activo) VALUES (%s, 'base', false) RETURNING id", (f"prueba-correos-{os.getpid()}@test.invalid",))
            uid = cur.fetchone()[0]
            monkeypatch.setattr(correos.db, "conexion_usuario", _MismaConexion(c))
            email = f"prueba-correos-{os.getpid()}@test.invalid"

            pedidos = _proveedor(monkeypatch)
            assert correos.avisar(uid, email, "cobro_pendiente", "2026-11-08", plan="base") == "enviado"
            assert correos.avisar(uid, email, "cobro_pendiente", "2026-11-08", plan="base") == "ya_enviado"            # el mismo hecho no se repite
            assert len(pedidos) == 1
            assert correos.avisar(uid, email, "cobro_pendiente", "2026-12-08", plan="base") == "enviado"               # otro ciclo de cobro: aviso nuevo
            assert correos.avisar(uid, email, "plan_dado_de_baja", "2026-11-08", plan="base") == "enviado"             # otro tipo: aviso nuevo
            assert len(pedidos) == 3

            fallando = _proveedor(monkeypatch, codigo=503)
            assert correos.avisar(uid, email, "plan_cambiado", "x", plan_nuevo="elite") == "error"
            cur.execute("SELECT count(*) FROM correos_enviados WHERE usuario_id = %s AND tipo = 'plan_cambiado'", (uid,))
            assert cur.fetchone()[0] == 0                                                                           # el envío falló: la reserva se liberó…
            _proveedor(monkeypatch)
            assert correos.avisar(uid, email, "plan_cambiado", "x", plan_nuevo="elite") == "enviado"                   # …y la próxima corrida lo manda
            assert len(fallando) == 1

            assert correos.avisar(uid, "meli-77@pendiente.corelux.app", "prueba_vencida", "2026-11-08") == "descartado"   # email provisorio: nada
            cur.execute("SELECT count(*) FROM correos_enviados WHERE usuario_id = %s AND tipo = 'prueba_vencida'", (uid,))
            assert cur.fetchone()[0] == 0
            cur.execute("SELECT tipo, clave, destino FROM correos_enviados WHERE usuario_id = %s ORDER BY id", (uid,))
            assert cur.fetchall() == [("cobro_pendiente", "2026-11-08", email), ("cobro_pendiente", "2026-12-08", email), ("plan_dado_de_baja", "2026-11-08", email), ("plan_cambiado", "x", email)]
            raise _Revertir()
    except _Revertir:
        pass


def test_avisar_nunca_levanta_una_excepcion(mails_encendidos, monkeypatch):
    def roto(*a, **k):
        raise RuntimeError("la base no responde")
    monkeypatch.setattr(correos.db, "conexion_usuario", roto)
    assert correos.avisar(1, "persona@ejemplo.com", "cobro_pendiente", "2026-11-08", plan="base") == "error"


# ── De punta a punta con la tarea de renovaciones y Mercado Pago simulado ──────────────────────────────────────────────────

def _usuario(cur, n, plan, mp_id, proximo_sql):
    cur.execute(f"INSERT INTO usuarios (email, plan, mp_suscripcion_id, mp_proximo_cobro, activo) VALUES (%s, %s, %s, {proximo_sql}, false) RETURNING id",
                (f"prueba-correos-ren-{os.getpid()}-{n}@test.invalid", plan, mp_id))
    return cur.fetchone()[0]


@pytest.mark.db
@pytest.mark.skipif(not os.getenv("DATABASE_URL_ADMIN"), reason="Sin DATABASE_URL_ADMIN")
def test_la_tarea_de_renovaciones_avisa_a_quien_corresponde():
    ahora = datetime.now(UTC)
    mp = {n: f"prueba-correos-{os.getpid()}-{n}" for n in ("cobra", "cancela", "rechaza_ayer", "rechaza_4_dias", "recien")}
    ultimo_viejo = (ahora - timedelta(days=35)).isoformat()
    respuestas = {
        mp["cobra"]: {"status": "authorized", "next_payment_date": (ahora + timedelta(days=30)).isoformat(), "summarized": {"last_charged_date": ahora.isoformat()}},
        mp["cancela"]: {"status": "cancelled"},
        mp["rechaza_ayer"]: {"status": "paused", "summarized": {"last_charged_date": ultimo_viejo}},
        mp["rechaza_4_dias"]: {"status": "paused", "summarized": {"last_charged_date": ultimo_viejo}},
        mp["recien"]: {"status": "paused", "summarized": {"last_charged_date": ultimo_viejo}},
    }
    enviados = []
    ids = {}
    try:
        with db.conexion_admin() as c:
            cur = c.cursor()
            ids["cobra"] = _usuario(cur, 1, "base", mp["cobra"], "now() - interval '1 hour'")
            ids["cancela"] = _usuario(cur, 2, "elite", mp["cancela"], "now() - interval '1 hour'")
            ids["rechaza_ayer"] = _usuario(cur, 3, "base", mp["rechaza_ayer"], "now() - interval '30 hours'")
            ids["rechaza_4_dias"] = _usuario(cur, 4, "base", mp["rechaza_4_dias"], "now() - interval '4 days'")
            ids["recien"] = _usuario(cur, 5, "base", mp["recien"], "now() - interval '3 hours'")
        resumen = renovaciones_mp.chequear_renovaciones(
            ahora=ahora, obtener=lambda mp_id: respuestas.get(mp_id), cancelar=lambda mp_id: True,
            avisar=lambda uid, email, tipo, clave, **datos: enviados.append((uid, email, tipo, clave, datos)))
        assert resumen["errores"] == 0
        por_usuario = {uid: tipo for uid, _e, tipo, _c, _d in enviados}
        assert por_usuario == {ids["cancela"]: "suscripcion_cancelada", ids["rechaza_ayer"]: "cobro_pendiente", ids["rechaza_4_dias"]: "plan_dado_de_baja"}      # nada para quien pagó ni para el cobro de hace 3 horas
        assert all(email.endswith("@test.invalid") for _u, email, *_ in enviados)
    finally:
        with db.conexion_admin() as c:
            c.cursor().execute("DELETE FROM usuarios WHERE email LIKE %s", (f"prueba-correos-ren-{os.getpid()}-%@test.invalid",))


@pytest.mark.db
@pytest.mark.skipif(not os.getenv("DATABASE_URL_ADMIN"), reason="Sin DATABASE_URL_ADMIN")
def test_los_avisos_de_la_prueba_gratuita(monkeypatch):
    import config
    monkeypatch.setattr(config, "PAGOS_HABILITADOS", True)
    ahora = datetime.now(UTC)
    enviados = []
    try:
        with db.conexion_admin() as c:
            cur = c.cursor()
            casos = {"en_2_dias": 2, "en_10_dias": 10, "ayer": -1, "hace_5_dias": -5}
            for n, (nombre, dias) in enumerate(casos.items()):
                cur.execute("INSERT INTO usuarios (email, plan, activo, trial_termina_en) VALUES (%s, 'trial', true, %s) RETURNING id",
                            (f"prueba-correos-tr-{os.getpid()}-{nombre}@test.invalid", ahora + timedelta(days=dias)))
            cur.execute("INSERT INTO usuarios (email, plan, activo, trial_termina_en) VALUES (%s, 'base', true, %s)", (f"prueba-correos-tr-{os.getpid()}-pago@test.invalid", ahora + timedelta(days=1)))
        resumen = renovaciones_mp.avisar_pruebas(ahora=ahora, avisar=lambda uid, email, tipo, clave, **d: enviados.append((email, tipo, clave)) if "prueba-correos-tr-" in email else None)
        mios = {email.split("-")[-1].split("@")[0]: (tipo, clave) for email, tipo, clave in enviados}
        assert mios["en_2_dias"][0] == "prueba_por_vencer" and mios["ayer"][0] == "prueba_vencida"
        assert "en_10_dias" not in mios and "hace_5_dias" not in mios and "pago" not in mios      # ni la que falta mucho, ni la que venció hace tiempo, ni quien ya pagó
        assert resumen["prueba_por_vencer"] >= 1 and resumen["prueba_vencida"] >= 1
        assert mios["en_2_dias"][1] == (ahora + timedelta(days=2)).date().isoformat()                   # la clave es la fecha de fin: si se extiende la prueba, es otro aviso
    finally:
        with db.conexion_admin() as c:
            c.cursor().execute("DELETE FROM usuarios WHERE email LIKE %s", (f"prueba-correos-tr-{os.getpid()}-%@test.invalid",))


def test_sin_cobro_habilitado_o_sin_mails_los_avisos_de_prueba_no_consultan_nada(monkeypatch):
    import config
    monkeypatch.setattr(renovaciones_mp.db, "conexion_admin", lambda: pytest.fail("no debe tocar la base"))
    monkeypatch.setattr(config, "PAGOS_HABILITADOS", False)
    assert renovaciones_mp.avisar_pruebas(avisar=lambda *a, **k: None) == {"prueba_por_vencer": 0, "prueba_vencida": 0}      # beta gratuita: la prueba no bloquea nada
    monkeypatch.setattr(config, "PAGOS_HABILITADOS", True)
    assert renovaciones_mp.avisar_pruebas() == {"prueba_por_vencer": 0, "prueba_vencida": 0}                                 # sin mails configurados
