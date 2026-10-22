"""
Beta cerrada (2026-10-22): sin cobro visible, entrada con invitación y lista de espera.

  · config: MODO_BETA está encendido por defecto, así que aunque producción tenga un MP_ACCESS_TOKEN (hoy de prueba) NO se muestra ni se aplica ningún cobro;
  · beta.py contra la base real, SIEMPRE dentro de una transacción que se revierte (aplica la migración 0051 dos veces y no deja nada);
  · las rutas /beta, /beta/entrar, /beta/espera y la puerta de /callback: quien ya tiene cuenta entra sin invitación, una cuenta nueva solo con un código que sirva,
    y el uso del código se devuelve si la cuenta no llega a crearse.
"""
import os
import re
import subprocess
import sys
from contextlib import contextmanager

import pytest

import beta

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CON_BASE = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="Sin DATABASE_URL")


def _leer(*partes):
    return open(os.path.join(RAIZ, *partes), encoding="utf-8").read()


@pytest.fixture(autouse=True)
def _limitador_en_cero():
    import limitador
    limitador.reiniciar()


# ── Modo beta ─────────────────────────────────────────────────────────────────
def _config_con(**entorno):
    """Lo que dice config.py con ese entorno, en un proceso aparte (config se lee una sola vez al importarlo)."""
    env = {k: v for k, v in os.environ.items() if k not in ("MODO_BETA", "BETA_SOLO_INVITADOS", "MP_ACCESS_TOKEN")}
    env["MP_ACCESS_TOKEN"] = ""                  # el .env de la PC del dueño trae el de prueba: load_dotenv no pisa una variable ya definida
    env.update(entorno)
    salida = subprocess.run([sys.executable, "-c", "import config; print(config.MODO_BETA, config.PAGOS_HABILITADOS, config.COBRO_ACTIVO, config.BETA_SOLO_INVITADOS)"],
                            cwd=RAIZ, env=env, capture_output=True, text=True, timeout=60).stdout.split()
    return tuple(x == "True" for x in salida[-4:])


def test_por_defecto_es_beta_y_con_token_de_mercado_pago_no_se_cobra_ni_se_pide_nada_a_nadie():
    assert _config_con() == (True, False, False, True)
    assert _config_con(MP_ACCESS_TOKEN="TEST-123") == (True, True, False, True)           # el motor de cobro puede correr, la persona no lo ve ni lo sufre


def test_al_apagar_la_beta_vuelve_el_cobro_y_se_abre_el_registro():
    assert _config_con(MP_ACCESS_TOKEN="TEST-123", MODO_BETA="0") == (False, True, True, False)
    assert _config_con(MODO_BETA="false")[0] is False


def test_se_puede_abrir_el_registro_sin_apagar_la_beta():
    assert _config_con(BETA_SOLO_INVITADOS="0") == (True, False, False, False)


def test_el_vencimiento_de_la_prueba_y_las_pantallas_miran_cobro_activo_no_el_token():
    for ruta in ("auth/middleware.py",):
        assert "config.PAGOS_HABILITADOS" not in _leer(ruta), "el paywall tiene que depender de COBRO_ACTIVO"
    app_py = _leer("app.py")
    assert "pagos_habilitados=config.PAGOS_HABILITADOS" not in app_py and '"pagos_habilitados": config.PAGOS_HABILITADOS' not in app_py


# ── Códigos ─────────────────────────────────────────────────────────────────────
def test_los_codigos_se_normalizan_sin_importar_como_los_escriba_la_persona():
    assert beta.normalizar_codigo("cl-7k4m-9qxd") == "CL-7K4M-9QXD"
    assert beta.normalizar_codigo(" CL 7K4M 9QXD ") == "CL-7K4M-9QXD"
    assert beta.normalizar_codigo("cl7k4m9qxd") == "CL-7K4M-9QXD"
    assert beta.normalizar_codigo("") == "" and beta.normalizar_codigo(None) == "" and beta.normalizar_codigo("---") == ""
    assert len(beta.normalizar_codigo("x" * 500)) <= 40


def test_los_codigos_generados_son_legibles_y_distintos():
    codigos = {beta.generar_codigo() for _ in range(200)}
    assert len(codigos) == 200
    for c in codigos:
        assert re.fullmatch(r"CL-[A-Z2-9]{4}-[A-Z2-9]{4}", c)
        assert not set("0O1IL") & set(c.replace("CL-", "")), c
        assert beta.normalizar_codigo(c) == c


def test_el_motivo_por_el_que_una_invitacion_no_sirve():
    assert beta._motivo((True, 0, 1, False)) is None
    assert beta._motivo((False, 0, 1, False)) == "inactivo"
    assert beta._motivo((True, 0, 1, True)) == "vencido"
    assert beta._motivo((True, 1, 1, False)) == "agotado"
    assert beta._motivo((True, 2, 5, False)) is None


def test_los_mensajes_de_rechazo_estan_para_todos_los_motivos_y_no_hablan_en_codigo():
    for motivo in ("no_existe", "agotado", "vencido", "inactivo", "vacio"):
        texto = beta.MOTIVOS[motivo]
        assert texto and "error" not in texto.lower() and "exception" not in texto.lower()


# ── Migración 0051 ─────────────────────────────────────────────────────────────
def _sin_comentarios(sql):
    return "\n".join(re.sub(r"--.*$", "", linea) for linea in sql.splitlines())


def test_la_migracion_es_aditiva_idempotente_y_la_app_no_puede_leer_las_tablas():
    sql = _sin_comentarios(_leer("migrations", "0051_beta_cerrada.sql"))
    assert not re.search(r"\bDROP\b", sql, re.I)
    assert not re.search(r"CREATE\s+TABLE\s+(?!IF NOT EXISTS)", sql, re.I)
    assert not re.search(r"CREATE\s+(UNIQUE\s+)?INDEX\s+(?!IF NOT EXISTS)", sql, re.I)
    for tabla in ("beta_invitaciones", "beta_canjes", "beta_espera"):
        assert re.search(rf"ALTER TABLE {tabla}\s+ENABLE ROW LEVEL SECURITY", sql), f"{tabla} sin RLS"
    assert "CREATE POLICY" not in sql and "app_backend" not in sql          # sin política ni permisos: solo la conexión de administración las toca
    assert "cuenta_id" not in sql


class _Revertir(Exception):
    pass


@contextmanager
def _en_transaccion(monkeypatch):
    """beta.py usa db.conexion_admin(): se le da la misma conexión de la prueba (con la migración aplicada) y todo se revierte al final."""
    import db
    try:
        with db.conexion_admin() as con:
            cur = con.cursor()
            cur.execute("SET LOCAL lock_timeout = '5s'")
            for _ in range(2):
                cur.execute(_leer("migrations", "0051_beta_cerrada.sql"))
            monkeypatch.setattr(beta.db, "conexion_admin", lambda: _Mantener(con))
            yield con
            raise _Revertir()
    except _Revertir:
        pass


class _Mantener:
    """Entrega la conexión de la prueba sin cerrarla ni confirmarla."""

    def __init__(self, con):
        self.con = con

    def __enter__(self):
        return self.con

    def __exit__(self, *a):
        return False


@CON_BASE
def test_una_invitacion_de_un_solo_uso_la_gana_una_sola_persona(monkeypatch):
    with _en_transaccion(monkeypatch):
        codigo = beta.crear_invitacion("prueba", usos_max=1)
        assert beta.validar(codigo) == (True, None)
        assert beta.validar(codigo.lower().replace("-", " ")) == (True, None)
        primero = beta.reservar(codigo)
        assert primero is not None
        assert beta.reservar(codigo) is None                                       # la segunda persona ya no pasa
        assert beta.validar(codigo) == (False, "agotado")
        beta.liberar(primero)                                                      # la cuenta no se llegó a crear: el uso vuelve
        assert beta.validar(codigo) == (True, None)
        assert beta.reservar(codigo) is not None


@CON_BASE
def test_invitaciones_de_varios_usos_vencidas_y_desactivadas(monkeypatch):
    with _en_transaccion(monkeypatch) as con:
        tres = beta.crear_invitacion("grupo", usos_max=3)
        assert [beta.reservar(tres) is not None for _ in range(4)] == [True, True, True, False]
        con.cursor().execute("UPDATE beta_invitaciones SET expira_en = now() - interval '1 day' WHERE codigo = %s", (tres,))
        vencida = beta.crear_invitacion("vence", usos_max=1, dias=1)
        con.cursor().execute("UPDATE beta_invitaciones SET expira_en = now() - interval '1 minute' WHERE codigo = %s", (vencida,))
        assert beta.validar(vencida) == (False, "vencido") and beta.reservar(vencida) is None
        apagada = beta.crear_invitacion("apagada")
        fila = [i for i in beta.listar_invitaciones() if i["codigo"] == apagada][0]
        assert fila["estado"] == "disponible"
        beta.desactivar(fila["id"])
        assert beta.validar(apagada) == (False, "inactivo") and beta.reservar(apagada) is None
        assert beta.validar("CL-ZZZZ-ZZZZ") == (False, "no_existe") and beta.validar("") == (False, "vacio")


@CON_BASE
def test_el_canje_queda_registrado_y_solo_los_codigos_nuevos_se_listan_como_disponibles(monkeypatch):
    with _en_transaccion(monkeypatch) as con:
        codigo = beta.crear_invitacion("registro")
        invitacion = beta.reservar(codigo)
        beta.registrar_canje(invitacion, None)
        cur = con.cursor()
        cur.execute("SELECT count(*) FROM beta_canjes WHERE invitacion_id = %s", (invitacion,))
        assert cur.fetchone()[0] == 1
        assert [i["estado"] for i in beta.listar_invitaciones() if i["codigo"] == codigo] == ["usada"]


@CON_BASE
def test_la_lista_de_espera_no_repite_mails_ni_acepta_cualquier_cosa(monkeypatch):
    with _en_transaccion(monkeypatch):
        assert beta.anotar_en_espera("Persona@Ejemplo.com", "ropa", "hola") is True
        assert beta.anotar_en_espera("persona@ejemplo.com") is True                # ya estaba: no falla ni se duplica
        assert [e["email"] for e in beta.listar_espera() if e["email"].lower() == "persona@ejemplo.com"] == ["Persona@Ejemplo.com"]
        for malo in ("", "sin-arroba", "a@b", "dos@@arrobas.com", "con espacio@x.com", None):
            assert beta.anotar_en_espera(malo) is False


@CON_BASE
def test_un_codigo_o_un_mail_enormes_no_rompen_nada(monkeypatch):
    with _en_transaccion(monkeypatch):
        assert beta.validar("A" * 10000) == (False, "no_existe")
        assert beta.anotar_en_espera("ok@x.com", "r" * 1000, "m" * 5000) is True      # se recorta, no explota
        assert beta.anotar_en_espera("a" * 300 + "@x.com") is False                   # un mail de 300 letras no es un mail


# ── Rutas ───────────────────────────────────────────────────────────────────────
@pytest.fixture
def cliente(monkeypatch):
    import app as aplicacion
    monkeypatch.setattr(aplicacion.config, "BETA_SOLO_INVITADOS", True)
    return aplicacion.app.test_client(), aplicacion


def test_beta_explica_y_avisa_de_la_pantalla_de_aplicacion_no_certificada(cliente):
    c, _ = cliente
    r = c.get("/beta")
    html = r.get_data(as_text=True)
    assert r.status_code == 200
    assert "aplicación no certificada" in html and "nunca vemos tu contraseña" in html
    assert 'name="codigo"' in html and 'name="email"' in html
    assert "14 días" not in html


def test_si_el_callback_lo_manda_de_vuelta_sin_codigo_la_pagina_lo_explica(cliente):
    c, _ = cliente
    html = c.get("/beta?motivo=sin_invitacion").get_data(as_text=True)
    assert "necesitás un código de invitación" in html


def test_con_el_registro_abierto_beta_manda_directo_a_conectar(cliente, monkeypatch):
    c, app = cliente
    monkeypatch.setattr(app.config, "BETA_SOLO_INVITADOS", False)
    assert c.get("/beta").headers["Location"].endswith("/conectar")
    assert c.post("/beta/entrar", data={"codigo": "x"}).headers["Location"].endswith("/conectar")


def test_un_codigo_que_no_sirve_se_rechaza_con_el_motivo_y_no_guarda_nada(cliente, monkeypatch):
    c, app = cliente
    monkeypatch.setattr(app.beta, "validar", lambda codigo: (False, "agotado"))
    r = c.post("/beta/entrar", data={"codigo": "cl-aaaa-bbbb"})
    assert r.status_code == 400 and "ya se usó" in r.get_data(as_text=True)
    with c.session_transaction() as s:
        assert "beta_codigo" not in s


def test_un_codigo_que_sirve_se_recuerda_y_sigue_a_mercado_libre(cliente, monkeypatch):
    c, app = cliente
    monkeypatch.setattr(app.beta, "validar", lambda codigo: (True, None))
    r = c.post("/beta/entrar", data={"codigo": "cl 7k4m 9qxd"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/conectar")
    with c.session_transaction() as s:
        assert s["beta_codigo"] == "CL-7K4M-9QXD"


def test_la_lista_de_espera_confirma_y_rechaza_un_mail_malo(cliente, monkeypatch):
    c, app = cliente
    anotados = []
    monkeypatch.setattr(app.beta, "anotar_en_espera", lambda email, rubro=None, mensaje=None: anotados.append(email) or ("@" in email))
    ok = c.post("/beta/espera", data={"email": "a@b.com", "rubro": "ropa"})
    assert ok.status_code == 302 and "espera=ok" in ok.headers["Location"]
    assert "te anotamos" in c.get(ok.headers["Location"]).get_data(as_text=True)
    malo = c.post("/beta/espera", data={"email": "nada"})
    assert malo.status_code == 400 and "no parece uno válido" in malo.get_data(as_text=True)


def test_probar_codigos_a_lo_loco_se_frena(cliente, monkeypatch):
    c, app = cliente
    monkeypatch.setitem(app.app.config, "TESTING", False)                         # con TESTING el limitador no corre (otras pruebas lo dejan encendido)
    monkeypatch.setattr(app.beta, "validar", lambda codigo: (False, "no_existe"))
    codigos = [c.post("/beta/entrar", data={"codigo": f"CL-AAAA-{i:04d}"}).status_code for i in range(12)]
    assert 429 in codigos and codigos[0] == 400


# ── La puerta de /callback ─────────────────────────────────────────────────────
class _Registro:
    def __init__(self):
        self.creados, self.liberados, self.canjes = [], [], []


@pytest.fixture
def puerta(monkeypatch):
    import app as aplicacion
    monkeypatch.setattr(aplicacion.config, "BETA_SOLO_INVITADOS", True)
    reg = _Registro()

    @contextmanager
    def admin_falso():
        class Cursor:
            def execute(self, *a, **k):
                pass

            def fetchone(self):
                return None

        class Conexion:
            def cursor(self):
                return Cursor()
        yield Conexion()
    monkeypatch.setattr(aplicacion.db, "conexion_admin", admin_falso)
    monkeypatch.setattr(aplicacion.oauth_meli, "intercambiar_codigo_por_token", lambda code: (True, {"access_token": "a", "refresh_token": "r", "expires_in": 21600}))
    monkeypatch.setattr(aplicacion.oauth_meli, "obtener_datos_usuario_meli", lambda t: (True, {"meli_user_id": 777, "nickname": "NUEVA", "site_id": "MLA"}))
    monkeypatch.setattr(aplicacion.registro, "crear_o_actualizar_login", lambda datos: reg.creados.append(datos) or (31, 41, True))
    monkeypatch.setattr(aplicacion.token_manager, "guardar_tokens", lambda *a, **k: None)
    monkeypatch.setattr(aplicacion, "_en_segundo_plano", lambda *a, **k: None)
    monkeypatch.setattr(aplicacion.beta, "liberar", lambda i: reg.liberados.append(i))
    monkeypatch.setattr(aplicacion.beta, "registrar_canje", lambda i, u: reg.canjes.append((i, u)))

    def entrar(existe=False, reserva=5, codigo="CL-AAAA-BBBB"):
        monkeypatch.setattr(aplicacion.beta, "cuenta_existe", lambda meli_user_id: existe)
        monkeypatch.setattr(aplicacion.beta, "reservar", lambda c: reserva if c else None)
        c = aplicacion.app.test_client()
        with c.session_transaction() as s:
            s["oauth_state"] = "S1"
            if codigo:
                s["beta_codigo"] = codigo
        return c, c.get("/callback?code=C1&state=S1")
    return entrar, reg


def test_quien_ya_tiene_cuenta_entra_sin_invitacion(puerta):
    entrar, reg = puerta
    c, r = entrar(existe=True, reserva=None, codigo=None)
    assert r.status_code == 302 and "/beta" not in r.headers["Location"]
    assert len(reg.creados) == 1 and reg.canjes == []


def test_una_cuenta_nueva_sin_codigo_no_se_crea_y_vuelve_a_la_entrada(puerta):
    entrar, reg = puerta
    c, r = entrar(existe=False, codigo=None)
    assert r.status_code == 302 and "/beta?motivo=sin_invitacion" in r.headers["Location"]
    assert reg.creados == []
    with c.session_transaction() as s:
        assert "usuario_id" not in s


def test_una_cuenta_nueva_con_un_codigo_que_ya_no_sirve_tampoco(puerta):
    entrar, reg = puerta
    c, r = entrar(existe=False, reserva=None)
    assert "/beta?motivo=sin_invitacion" in r.headers["Location"] and reg.creados == []
    with c.session_transaction() as s:
        assert "beta_codigo" not in s


def test_una_cuenta_nueva_con_codigo_se_crea_y_el_canje_queda_anotado(puerta):
    entrar, reg = puerta
    c, r = entrar(existe=False, reserva=5)
    assert r.status_code == 302 and "/beta" not in r.headers["Location"]
    assert len(reg.creados) == 1 and reg.canjes == [(5, 31)] and reg.liberados == []
    with c.session_transaction() as s:
        assert s["usuario_id"] == 31 and "beta_codigo" not in s


def test_si_la_cuenta_no_llega_a_crearse_el_codigo_se_devuelve(puerta, monkeypatch):
    import app as aplicacion
    entrar, reg = puerta

    def falla(datos):
        raise RuntimeError("base caída")
    monkeypatch.setattr(aplicacion.registro, "crear_o_actualizar_login", falla)
    c = aplicacion.app.test_client()
    with c.session_transaction() as s:
        s["oauth_state"] = "S1"
        s["beta_codigo"] = "CL-AAAA-BBBB"
    monkeypatch.setattr(aplicacion.beta, "cuenta_existe", lambda m: False)
    monkeypatch.setattr(aplicacion.beta, "reservar", lambda c: 9)
    aplicacion.app.config["PROPAGATE_EXCEPTIONS"] = False
    r = c.get("/callback?code=C1&state=S1")
    assert r.status_code >= 500 and reg.liberados == [9] and reg.canjes == []


def test_con_el_registro_abierto_no_se_pide_codigo(puerta, monkeypatch):
    import app as aplicacion
    entrar, reg = puerta
    monkeypatch.setattr(aplicacion.config, "BETA_SOLO_INVITADOS", False)
    c, r = entrar(existe=False, reserva=None, codigo=None)
    assert len(reg.creados) == 1 and "/beta" not in r.headers["Location"]


# ── Planes y otras pantallas sin cobro ───────────────────────────────────────────
def test_planes_sin_sesion_es_una_pagina_publica_sin_la_carcasa_de_la_app(cliente):
    c, _ = cliente
    html = c.get("/planes").get_data(as_text=True)
    assert 'class="sidebar"' not in html and "app-shell" not in html
    assert "pb-nav" in html and "Pedir acceso a la beta" in html
    assert "Suscribirme" not in html and "Próximamente" not in html


def test_planes_en_beta_no_ofrece_suscribirse_aunque_haya_token_de_mercado_pago(cliente, monkeypatch):
    c, app = cliente
    monkeypatch.setattr(app.config, "MP_ACCESS_TOKEN", "TEST-123")
    monkeypatch.setattr(app.config, "PAGOS_HABILITADOS", True)
    html = c.get("/planes").get_data(as_text=True)
    assert "Suscribirme" not in html and "Beta cerrada" in html


def test_el_boton_elite_es_violeta_y_no_dorado():
    css = _leer("templates", "planes.html")
    bloque = re.search(r"\.btn-plan-elite\s*\{([^}]*)\}", css).group(1)
    assert "accent-solid" in bloque and "accent-gold" not in bloque


def test_la_landing_en_beta_lleva_a_pedir_acceso_y_no_promete_una_prueba_de_14_dias(cliente):
    c, _ = cliente
    html = c.get("/").get_data(as_text=True)
    assert "Pedir acceso a la beta" in html and "Probar 14 días gratis" not in html
    assert 'href="/beta"' in html and 'href="/conectar"' in html                    # «Entrar» para quien ya tiene cuenta


# ── El resto de la Ola 0 ─────────────────────────────────────────────────────────
def _persona_lista():
    import db
    with db.conexion_admin() as conexion:
        cur = conexion.cursor()
        cur.execute("""SELECT c.usuario_id, c.id FROM cuentas_meli c JOIN usuarios u ON u.id = c.usuario_id
                       WHERE u.onboarding_completo AND c.sincronizacion_inicial_completa ORDER BY c.id LIMIT 1""")
        return cur.fetchone()


@CON_BASE
def test_en_beta_nadie_que_no_sea_el_administrador_arma_una_suscripcion_aunque_haya_token(monkeypatch):
    import app as aplicacion
    persona = _persona_lista()
    if not persona:
        pytest.skip("Hace falta una persona con la cuenta lista en la base")
    monkeypatch.setattr(aplicacion.config, "MP_ACCESS_TOKEN", "TEST-123")
    monkeypatch.setattr(aplicacion.config, "MODO_BETA", True)
    monkeypatch.setattr(aplicacion.auditoria, "es_administrador", lambda usuario_id: False)
    monkeypatch.setattr(aplicacion.pagos, "crear_link_suscripcion", lambda *a, **k: pytest.fail("no se arma ningún cobro en beta"))
    c = aplicacion.app.test_client()
    with c.session_transaction() as s:
        s["usuario_id"], s["cuenta_id"] = persona
    r = c.post("/suscripcion/iniciar", data={"plan": "base"}, headers={"Sec-Fetch-Site": "same-origin"})
    assert r.status_code == 302 and "aviso=sin_pagos" in r.headers["Location"]


@CON_BASE
def test_sin_cobro_el_programa_de_referidos_no_se_ofrece_ni_por_direccion(monkeypatch):
    import app as aplicacion
    persona = _persona_lista()
    if not persona:
        pytest.skip("Hace falta una persona con la cuenta lista en la base")
    monkeypatch.setattr(aplicacion.config, "MODO_BETA", True)
    c = aplicacion.app.test_client()
    with c.session_transaction() as s:
        s["usuario_id"], s["cuenta_id"] = persona
    r = c.get("/referidos")
    assert r.status_code == 302 and "/referidos" not in r.headers["Location"]


def test_el_panel_de_invitaciones_se_dibuja_con_y_sin_datos():
    import datetime as dt
    import app as aplicacion
    ahora = dt.datetime.now(dt.timezone.utc)
    inv = [{"id": 1, "codigo": "CL-AAAA-BBBB", "nota": "Marcela", "usos": 0, "usos_max": 1, "activa": True, "expira_en": None, "creada_en": ahora, "estado": "disponible"},
           {"id": 2, "codigo": "CL-CCCC-DDDD", "nota": None, "usos": 1, "usos_max": 1, "activa": True, "expira_en": ahora, "creada_en": ahora, "estado": "usada"}]
    espera = [{"id": 1, "email": "x@y.com", "rubro": "ropa", "mensaje": None, "creado_en": ahora}]
    with aplicacion.app.test_request_context("/admin/beta"):
        lleno = aplicacion.render_template("admin_beta.html", active_nav="admin", invitaciones=inv, espera=espera, pide_invitacion=True, nuevo_codigo="CL-AAAA-BBBB")
        vacio = aplicacion.render_template("admin_beta.html", active_nav="admin", invitaciones=[], espera=[], pide_invitacion=False, nuevo_codigo=None)
    assert "CL-AAAA-BBBB" in lleno and "Marcela" in lleno and "x@y.com" in lleno and "Desactivar" in lleno
    assert lleno.count("Desactivar") == 1                                       # solo la que está disponible
    assert "Todavía no creaste invitaciones" in vacio and "Nadie se anotó todavía" in vacio and "La beta está abierta" in vacio


def test_tendencias_ya_no_identifica_a_ningun_vendedor():
    import tendencias
    assert not hasattr(tendencias, "_perfil_vendedor")
    codigo = _leer("tendencias.py")
    assert "top_vendedores" not in codigo and "/users/" not in codigo           # ni se pide el perfil de nadie ni se devuelve una lista de vendedores
    assert "top_vendedores" not in _leer("templates", "tendencias.html")


def test_la_pantalla_huerfana_de_logistica_no_existe_mas_y_el_menu_dice_radar():
    import app as aplicacion
    rutas = {r.rule for r in aplicacion.app.url_map.iter_rules()}
    assert "/comparador_logistica" not in rutas
    assert not os.path.exists(os.path.join(RAIZ, "templates", "comparador_logistica.html"))
    import nav_config
    etiquetas = {p["label"] for g in nav_config.GRUPOS_NAV.values() for p in g["paginas"]}
    assert "Radar" in etiquetas and "Mercado" not in etiquetas


def test_el_aviso_de_iva_solo_sale_para_un_responsable_inscripto():
    import app as aplicacion
    from flask import render_template_string
    plantilla = "{% from '_ux.html' import aviso_iva %}{{ aviso_iva(c) }}"
    with aplicacion.app.test_request_context("/"):
        ri = render_template_string(plantilla, c="responsable_inscripto")
        for otra in ("monotributo", "sin_inscripcion", None, ""):
            assert "IVA" not in render_template_string(plantilla, c=otra)
    assert "todavía incluyen el IVA" in ri and "contador" in ri
    for pantalla in ("metricas.html", "dashboard_personalizable.html"):
        assert "aviso_iva(condicion_fiscal)" in _leer("templates", pantalla)


def test_los_terminos_y_la_privacidad_dicen_lo_que_hacemos_de_verdad(cliente):
    c, _ = cliente
    terminos = c.get("/terminos").get_data(as_text=True)
    privacidad = c.get("/privacidad").get_data(as_text=True)
    assert "beta cerrada" in terminos and "gratuito" in terminos and "14 días" not in terminos
    assert "IVA" in terminos
    assert "código postal" in privacidad and "coordenadas" in privacidad
    assert "fuera de la Argentina" in privacidad and "DeepSeek" in privacidad
    assert 'class="sidebar"' not in terminos and "pb-nav" in terminos                 # mismo estilo que el resto de las páginas públicas
