"""
Confirmación antes de vincular otra cuenta de Mercado Libre (migración 0042). El enlace de «conectar otra cuenta» se abre en otro navegador a propósito (0013) y es una credencial: antes de
vincular se muestra a QUÉ cuenta de CoreLux y con QUÉ cuenta de Mercado Libre, y se vincula recién al confirmar. Un enlace completado en otro navegador NO inicia sesión ahí.
"""
import os
from contextlib import contextmanager

import pytest

import crypto_utils
from auth import confirmacion_oauth

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CON_BASE = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="Sin DATABASE_URL")


def _leer(*partes):
    return open(os.path.join(RAIZ, *partes), encoding="utf-8").read()


# ── Pantalla: enmascarar ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_el_email_se_enmascara_y_el_provisorio_no_se_muestra():
    assert confirmacion_oauth.enmascarar_email("diego@gmail.com") == "d***@gmail.com"
    assert confirmacion_oauth.enmascarar_email("  Ana.Perez@empresa.com.ar ") == "A***@empresa.com.ar"
    for sin_email in (None, "", "sin-arroba", "meli-123@pendiente.corelux.app"):
        assert confirmacion_oauth.enmascarar_email(sin_email) is None


# ── El flujo completo con una base y un Mercado Libre de mentira ───────────────────────────────────────────────────────────────────────────
class Mundo:
    """Base de mentira para las tablas de vinculación y confirmación, y registro de lo que se vinculó."""

    def __init__(self, pendientes=None, usuarios=None):
        self.vinculaciones = dict(pendientes or {})          # state → usuario_id
        self.confirmaciones = {}                              # token → fila
        self.usuarios = usuarios or {7: ("diego@gmail.com", "Diego"), 9: ("otra@correo.com", "Otra")}
        self.sentencias, self.vinculadas, self.tokens_guardados, self.auditorias, self.sesiones_iniciadas = [], [], [], [], []

    @contextmanager
    def conexion_admin(self):
        mundo = self

        class Cursor:
            def __init__(c):
                c.fila = None

            def execute(c, sql, params=None):
                t = " ".join(sql.split())
                mundo.sentencias.append(t)
                c.fila = None
                if t.startswith("DELETE FROM oauth_vinculaciones_pendientes WHERE state = %s AND creado_en"):
                    usuario = mundo.vinculaciones.pop(params[0], None)
                    c.fila = (usuario,) if usuario else None
                elif t.startswith("DELETE FROM oauth_vinculaciones_pendientes WHERE state = %s"):
                    mundo.vinculaciones.pop(params[0], None)
                elif t.startswith("INSERT INTO oauth_confirmaciones_pendientes"):
                    token, usuario_id, meli_id, nick, site, acceso, refresco, expira = params
                    mundo.confirmaciones[token] = (usuario_id, meli_id, nick, site, acceso, refresco, expira)
                elif t.startswith("DELETE FROM oauth_confirmaciones_pendientes WHERE token = %s"):
                    c.fila = mundo.confirmaciones.pop(params[0], None)
                elif t.startswith("SELECT email, nombre FROM usuarios"):
                    c.fila = mundo.usuarios.get(params[0])

            def fetchone(c):
                return c.fila

        class Conexion:
            def cursor(c):
                return Cursor()
        yield Conexion()


@pytest.fixture(autouse=True)
def _limitador_en_cero():
    import limitador
    limitador.reiniciar()


@pytest.fixture
def mundo(monkeypatch):
    import app as aplicacion
    m = Mundo(pendientes={"S1": 7})
    monkeypatch.setattr(aplicacion.db, "conexion_admin", m.conexion_admin)
    monkeypatch.setattr(aplicacion.oauth_meli, "intercambiar_codigo_por_token", lambda code: (True, {"access_token": "ACCESO-SECRETO", "refresh_token": "REFRESCO-SECRETO", "expires_in": 21600}))
    monkeypatch.setattr(aplicacion.oauth_meli, "obtener_datos_usuario_meli", lambda tok: (True, {"meli_user_id": 555, "nickname": "TIENDA_NUEVA", "site_id": "MLA", "email": "x@y.com"}))

    def vincular(usuario_id, datos):
        m.vinculadas.append((usuario_id, datos["meli_user_id"]))
        return 99, m.resultado_vinculo
    m.resultado_vinculo = "vinculada"
    monkeypatch.setattr(aplicacion.registro, "vincular_cuenta_adicional", vincular)
    monkeypatch.setattr(aplicacion.token_manager, "guardar_tokens", lambda cuenta_id, a, r, e: m.tokens_guardados.append((cuenta_id, a, r, e)))
    monkeypatch.setattr(aplicacion.auditoria, "registrar", lambda accion, detalle=None, usuario_id=None, cuenta_id=None: m.auditorias.append((accion, usuario_id, cuenta_id, detalle)))
    monkeypatch.setattr(aplicacion, "_en_segundo_plano", lambda *a: None)
    m.app = aplicacion
    return m


def _cliente(mundo, usuario_en_sesion=None, cookie_state=None):
    cliente = mundo.app.app.test_client()
    with cliente.session_transaction() as s:
        if usuario_en_sesion:
            s["usuario_id"] = usuario_en_sesion
        if cookie_state:
            s["oauth_state"] = cookie_state
            s["vinculando_cuenta_extra"] = True
    return cliente


def _token_de(mundo):
    assert len(mundo.confirmaciones) == 1, mundo.confirmaciones
    return next(iter(mundo.confirmaciones))


def test_al_volver_de_mercado_libre_en_otro_navegador_se_pide_confirmar_y_todavia_no_se_vincula_nada(mundo):
    r = _cliente(mundo).get("/callback?code=C1&state=S1")
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "¿Confirmás esta vinculación?" in html
    assert "@TIENDA_NUEVA" in html and "d***@gmail.com" in html and "diego@gmail.com" not in html          # el email va enmascarado
    assert 'name="token"' in html and "Sí, vincular" in html and "No, cancelar" in html
    assert mundo.vinculadas == [] and mundo.tokens_guardados == []                                          # nada se guardó todavía
    guardado = next(iter(mundo.confirmaciones.values()))
    assert guardado[4] != "ACCESO-SECRETO" and guardado[5] != "REFRESCO-SECRETO"                             # los permisos quedan cifrados
    assert crypto_utils.descifrar(guardado[4]) == "ACCESO-SECRETO"


def test_confirmar_en_otro_navegador_vincula_sin_iniciar_sesion_ahi(mundo):
    cliente = _cliente(mundo)
    cliente.get("/callback?code=C1&state=S1")
    r = cliente.post("/conectar_otra_cuenta/confirmar", data={"token": _token_de(mundo)})
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "Cuenta TIENDA_NUEVA conectada" in html and "Volvé a CoreLux en tu navegador de siempre" in html
    assert mundo.vinculadas == [(7, 555)] and mundo.tokens_guardados == [(99, "ACCESO-SECRETO", "REFRESCO-SECRETO", 21600)]
    with cliente.session_transaction() as s:
        assert "usuario_id" not in s                                                                         # un enlace completado en otro navegador no le da una sesión a nadie
    assert mundo.auditorias == [("cuenta_vincular", 7, 99, {"resultado": "vinculada", "desde_este_navegador": False})]


def test_el_token_de_confirmacion_es_de_un_solo_uso(mundo):
    cliente = _cliente(mundo)
    cliente.get("/callback?code=C1&state=S1")
    token = _token_de(mundo)
    cliente.post("/conectar_otra_cuenta/confirmar", data={"token": token})
    r = cliente.post("/conectar_otra_cuenta/confirmar", data={"token": token})
    assert "venció" in r.get_data(as_text=True) and mundo.vinculadas == [(7, 555)]


def test_un_token_inexistente_o_vacio_no_vincula_nada(mundo):
    cliente = _cliente(mundo)
    for datos in ({"token": "inventado"}, {"token": ""}, {}):
        assert "venció" in cliente.post("/conectar_otra_cuenta/confirmar", data=datos).get_data(as_text=True)
    assert mundo.vinculadas == []


def test_cancelar_gasta_el_token_y_no_vincula(mundo):
    cliente = _cliente(mundo)
    cliente.get("/callback?code=C1&state=S1")
    token = _token_de(mundo)
    r = cliente.post("/conectar_otra_cuenta/cancelar", data={"token": token})
    assert r.status_code == 302 and mundo.vinculadas == [] and mundo.confirmaciones == {}
    assert "venció" in cliente.post("/conectar_otra_cuenta/confirmar", data={"token": token}).get_data(as_text=True)


def test_si_el_navegador_donde_se_confirma_tiene_la_sesion_de_otra_persona_se_rechaza(mundo):
    cliente = _cliente(mundo)
    cliente.get("/callback?code=C1&state=S1")
    with cliente.session_transaction() as s:
        s["usuario_id"] = 9                                                                                   # en el medio alguien entró con otra sesión
    r = cliente.post("/conectar_otra_cuenta/confirmar", data={"token": _token_de_o_ninguno(mundo)})
    assert "otra persona de CoreLux" in r.get_data(as_text=True) and mundo.vinculadas == []


def _token_de_o_ninguno(mundo):
    return next(iter(mundo.confirmaciones), "")


def test_si_quien_confirma_ya_tiene_la_sesion_del_dueno_se_activa_la_cuenta_nueva(mundo):
    cliente = _cliente(mundo)
    cliente.get("/callback?code=C1&state=S1")
    with cliente.session_transaction() as s:
        s["usuario_id"] = 7
    r = cliente.post("/conectar_otra_cuenta/confirmar", data={"token": _token_de_o_ninguno(mundo)})
    assert r.status_code == 302 and mundo.vinculadas == [(7, 555)]
    with cliente.session_transaction() as s:
        assert s["usuario_id"] == 7 and s["cuenta_id"] == 99
    assert mundo.auditorias[0][3]["desde_este_navegador"] is True


def test_en_el_mismo_navegador_con_la_cookie_se_vincula_directo_sin_pantalla_de_confirmacion(mundo):
    mundo.vinculaciones.clear()                                                                               # el flujo se inició acá: no hay vinculación pendiente que valga
    cliente = _cliente(mundo, usuario_en_sesion=7, cookie_state="S1")
    r = cliente.get("/callback?code=C1&state=S1")
    assert r.status_code == 302 and mundo.vinculadas == [(7, 555)] and mundo.confirmaciones == {}
    with cliente.session_transaction() as s:
        assert s["usuario_id"] == 7 and s["cuenta_id"] == 99


def test_si_la_cuenta_ya_es_de_otro_usuario_se_avisa_y_no_se_guardan_permisos(mundo):
    mundo.resultado_vinculo = "ya_de_otro_usuario"
    cliente = _cliente(mundo)
    cliente.get("/callback?code=C1&state=S1")
    r = cliente.post("/conectar_otra_cuenta/confirmar", data={"token": _token_de_o_ninguno(mundo)})
    assert "ya está conectada a otro login" in r.get_data(as_text=True)
    assert mundo.tokens_guardados == []


def test_el_titular_sin_email_real_se_nombra_por_su_nombre_o_de_forma_generica(monkeypatch, mundo):
    mundo.usuarios[7] = ("meli-1@pendiente.corelux.app", "Diego Santiago")
    assert confirmacion_oauth.titular_de(7) == "Diego Santiago"
    mundo.usuarios[7] = (None, None)
    assert confirmacion_oauth.titular_de(7) == "un usuario de CoreLux"
    assert confirmacion_oauth.titular_de(12345) == "un usuario de CoreLux"


# ── Estructura ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_las_rutas_de_confirmacion_no_piden_login_y_solo_aceptan_post():
    app = _leer("app.py")
    for ruta, funcion in (("/conectar_otra_cuenta/confirmar", "confirmar_vinculacion"), ("/conectar_otra_cuenta/cancelar", "cancelar_vinculacion")):
        bloque = app[app.index(f'@app.route("{ruta}", methods=["POST"])'):].split("\n\n\n")[0]
        assert f"def {funcion}" in bloque and "login_requerido" not in bloque
    import limitador
    assert any(("/conectar_otra_cuenta" in regla[0]) for regla in limitador.REGLAS)                          # el limitador de OAuth las cubre por prefijo


@CON_BASE
def test_la_tabla_de_confirmaciones_existe_con_su_indice_y_su_politica():
    import db
    with db.conexion_admin() as con:
        cur = con.cursor()
        cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'oauth_confirmaciones_pendientes'")
        assert cur.fetchone()[0] == 1
        cur.execute("SELECT count(*) FROM pg_indexes WHERE tablename = 'oauth_confirmaciones_pendientes' AND indexname = 'idx_oauth_confirmaciones_usuario'")
        assert cur.fetchone()[0] == 1
        cur.execute("SELECT count(*) FROM pg_policies WHERE tablename = 'oauth_confirmaciones_pendientes'")
        assert cur.fetchone()[0] == 1
