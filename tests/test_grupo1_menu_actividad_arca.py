"""
Lote de mejoras de interfaz (2026-10-13), Grupo 1:
  · la Calculadora es un ítem propio del menú lateral (antes una pestaña escondida dentro de «Precios y costos»);
  · «Actividad» no muestra datos técnicos (el pedido crudo, ids internos, IP) a una persona común: solo qué pasó y cuándo;
  · AFIP pasó a llamarse ARCA (Agencia de Recaudación y Control Aduanero): ya no queda ninguna mención en el código ni en las pantallas.
El contraste del tema claro se prueba en test_contraste.py.
"""
import datetime as dt
import glob
import os
import re

import pytest

import nav_config

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CON_BASE = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="Sin DATABASE_URL")


# ── Calculadora en el menú ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_la_calculadora_es_una_seccion_propia_del_menu_y_ya_no_una_pestana_de_precios():
    assert [p["nav_key"] for p in nav_config.GRUPOS_NAV["precios"]["paginas"]] == ["costos", "precios", "historial_precios"]
    calculadora = nav_config.GRUPOS_NAV["calculadora"]
    assert calculadora["icono"] == "calculator" and len(calculadora["paginas"]) == 1
    assert calculadora["paginas"][0]["href"] == "/calculadora" and nav_config.SECCION_DE_NAV["calculadora"] == "calculadora"


def test_una_seccion_de_una_sola_pantalla_no_lleva_pestanas_ni_mas_usado():
    assert nav_config.calcular_mas_usado({"calculadora": 50}) == {}


def test_el_menu_lateral_la_dibuja_y_el_celular_la_alcanza_desde_mas():
    base = open(os.path.join(RAIZ, "templates", "base.html"), encoding="utf-8").read()
    assert "{% for clave, s in nav_grupos.items() %}" in base                                    # el menú sale de GRUPOS_NAV: la sección nueva aparece sola
    assert "['inicio', 'dia', 'ventas', 'stock']" in base and 'data-click="abrirSidebar"' in base      # la barra inferior del celular: «Más» abre el menú lateral con TODAS las secciones
    assert '<symbol id="icon-calculator"' in base


# ── Actividad: sin datos técnicos para una persona común ────────────────────────────────────────────────────────────────────────────────
class _Cursor:
    def execute(self, sql, params=None):
        pass

    def fetchall(self):
        return [("precios_masivo", {"ruta": "/x", "pedido": {"precios": {"MLA1": 100}}}, "190.1.2.3", dt.datetime(2026, 10, 13, 15, 0, tzinfo=dt.timezone.utc), 7)]


class _Conexion:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self):
        return _Cursor()


def test_el_registro_de_un_usuario_comun_trae_solo_que_paso_y_cuando(monkeypatch):
    import auditoria
    monkeypatch.setattr(auditoria.db, "conexion_usuario", lambda *a, **k: _Conexion())
    (evento,) = auditoria.listar(1, 7)
    assert set(evento) == {"accion", "etiqueta", "cuando"} and evento["etiqueta"] == "Cambio de precios masivo"
    assert "detalle" not in evento and "ip" not in evento and "cuenta_id" not in evento


def test_el_administrador_si_recibe_los_datos_tecnicos(monkeypatch):
    import auditoria
    monkeypatch.setattr(auditoria.db, "conexion_usuario", lambda *a, **k: _Conexion())
    (evento,) = auditoria.listar(1, 7, completo=True)
    assert evento["detalle"]["pedido"] == {"precios": {"MLA1": 100}} and evento["ip"] == "190.1.2.3" and evento["cuenta_id"] == 7


def test_es_administrador_solo_si_el_email_esta_en_admin_email(monkeypatch):
    import auditoria

    class Cursor(_Cursor):
        def fetchone(self):
            return ("Dueno@Corelux.app",)

    class Conexion(_Conexion):
        def cursor(self):
            return Cursor()
    monkeypatch.setattr(auditoria.db, "conexion_usuario", lambda *a, **k: Conexion())
    monkeypatch.setattr(auditoria.config, "ADMIN_EMAILS", {"dueno@corelux.app"})
    assert auditoria.es_administrador(1) is True
    monkeypatch.setattr(auditoria.config, "ADMIN_EMAILS", {"otro@corelux.app"})
    assert auditoria.es_administrador(1) is False
    monkeypatch.setattr(auditoria.config, "ADMIN_EMAILS", set())
    assert auditoria.es_administrador(1) is False                                                # sin ADMIN_EMAIL nadie es administrador


@CON_BASE
@pytest.mark.parametrize("es_admin", [False, True])
def test_la_pantalla_y_la_api_de_actividad_respetan_quien_mira(monkeypatch, es_admin):
    import app as a
    import auditoria
    import db
    evento = {"accion": "precios_masivo", "etiqueta": "Cambio de precios masivo", "cuando": dt.datetime(2026, 10, 13, 12, 0, tzinfo=dt.timezone.utc)}
    secreto = {"detalle": {"ruta": "/actualizar_precios_masivo", "pedido": {"ids_internos": [999111]}}, "ip": "200.9.8.7", "cuenta_id": 7}
    monkeypatch.setattr(auditoria, "es_administrador", lambda usuario_id: es_admin)
    monkeypatch.setattr(auditoria, "listar", lambda usuario_id, cuenta_id, limite=100, completo=False: [{**evento, **(secreto if completo else {})}])
    with db.conexion_admin() as con:
        cur = con.cursor()
        cur.execute("SELECT usuario_id, id FROM cuentas_meli ORDER BY id LIMIT 1")
        usuario, cuenta = cur.fetchone()
    cliente = a.app.test_client()
    with cliente.session_transaction() as s:
        s["usuario_id"], s["cuenta_id"] = usuario, cuenta
    html = cliente.get("/cuenta/actividad").get_data(as_text=True)
    api = cliente.get("/api/cuenta/actividad").get_data(as_text=True)
    assert "Cambio de precios masivo" in html and "Cambio de precios masivo" in api
    for dato in ("999111", "200.9.8.7", "/actualizar_precios_masivo"):
        assert (dato in html) == es_admin and (dato in api) == es_admin, dato
    assert ("Datos técnicos" in html) == es_admin


# ── AFIP → ARCA ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
PALABRA_ARCA = r"(?<![A-Za-z])ARCA(?![A-Za-z])"          # la palabra suelta (no «MARCA»)


def _fuentes():
    for patron in ("*.py", os.path.join("auth", "*.py"), os.path.join("templates", "*.html"), os.path.join("static", "js", "*.js")):
        for ruta in glob.glob(os.path.join(RAIZ, patron)):
            yield os.path.relpath(ruta, RAIZ), open(ruta, encoding="utf-8").read()


def test_no_queda_ninguna_mencion_de_afip_en_el_codigo_ni_en_las_pantallas():
    quedan = [rel for rel, src in _fuentes() if re.search(r"\bAFIP\b", src, re.IGNORECASE)]
    assert not quedan, f"Usá «ARCA» (Agencia de Recaudación y Control Aduanero): {quedan}"


def test_la_primera_mencion_de_cada_pantalla_fiscal_dice_el_nombre_completo():
    for archivo in (os.path.join("templates", "monotributo.html"), os.path.join("templates", "reporte_fiscal.html"), "monotributo.py"):
        src = open(os.path.join(RAIZ, archivo), encoding="utf-8").read()
        assert src.index("ARCA (Agencia de Recaudación y Control Aduanero)") == re.search(PALABRA_ARCA, src).start(), archivo
