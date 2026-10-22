"""
Respuestas guardadas para las preguntas de compradores (plantillas_respuesta.py, migración 0053, pantalla Preguntas de Día a día).

  · la lógica (validar, saludo por hora, completar variables) con casos armados a mano;
  · la tabla y las rutas contra la base REAL, SIEMPRE dentro de una transacción que se revierte (la migración se aplica ahí, dos veces: funciona igual antes y después de desplegarla);
  · la pantalla: lo que no se puede publicar (una variable sin completar, una respuesta pasada de largo) y que nada se escriba sin escapar.
"""
import os
import re
from contextlib import contextmanager
from datetime import datetime

import pytest

import plantillas_respuesta as pr

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CON_BASE = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="Sin DATABASE_URL")


def _leer(*partes):
    return open(os.path.join(RAIZ, *partes), encoding="utf-8").read()


@pytest.fixture(autouse=True)
def _limitador_en_cero():
    import limitador
    limitador.reiniciar()


# ── La lógica ──────────────────────────────────────────────────────────────────
def test_validar_limpia_y_rechaza_con_un_mensaje_que_se_entiende():
    assert pr.validar("  Hay   stock ", "  Sí, hay.\n\n\n\nGracias  ") == ("Hay stock", "Sí, hay.\n\nGracias", None)
    for titulo, texto in (("", "x"), ("   ", "x"), ("a", ""), ("a", "   ")):
        assert pr.validar(titulo, texto)[2]
    assert "máximo 60" in pr.validar("a" * 61, "x")[2]
    assert "2000" in pr.validar("a", "x" * 2001)[2]
    assert pr.validar("a", "x" * 2000)[2] is None                                      # el límite exacto de Mercado Libre pasa


def test_una_variable_que_no_existe_se_rechaza_al_guardar_y_dice_cuales_hay():
    _, _, error = pr.validar("Hay stock", "{saludo}! Tenemos {produto} y {Precio}.")
    assert error and "{produto}" in error and "{Precio}" in error
    assert "{saludo}, {producto}, {precio}" in error
    assert pr.validar("ok", "{saludo}! {producto} a {precio}")[2] is None


def test_el_saludo_depende_de_la_hora_de_argentina():
    def a(h):
        return pr.saludo(datetime(2026, 10, 22, h, 0))
    assert [a(h) for h in (0, 5, 6, 11, 12, 19, 20, 23)] == ["Buenas noches", "Buenas noches", "Buen día", "Buen día", "Buenas tardes", "Buenas tardes", "Buenas noches", "Buenas noches"]


def test_se_completan_las_variables_que_se_conocen_y_se_avisa_de_las_que_no():
    texto, falta = pr.aplicar("{saludo}! {producto} cuesta {precio}.", {"saludo": "Buen día", "producto": "Campera de jean", "precio": "$54.990"})
    assert texto == "Buen día! Campera de jean cuesta $54.990." and falta == []
    texto, falta = pr.aplicar("{saludo}! {producto} cuesta {precio}.", {"saludo": "Buen día", "producto": "Campera de jean"})
    assert texto == "Buen día! Campera de jean cuesta {precio}." and falta == ["precio"]               # nunca se inventa un precio


def test_lo_que_vino_de_la_publicacion_no_se_vuelve_a_interpretar():
    """Un título con llaves no puede colar otra variable ni romper la cuenta: se reemplaza en una sola pasada."""
    texto, falta = pr.aplicar("Hola, {producto}", {"producto": "Funda {precio} Premium", "precio": "$1"})
    assert texto == "Hola, Funda {precio} Premium" and falta == ["precio"]                            # queda a la vista para que no se publique así


def test_los_ejemplos_para_empezar_son_validos_y_no_prometen_nada_concreto():
    for e in pr.SUGERIDAS:
        assert pr.validar(e["titulo"], e["texto"])[2] is None, e
        assert not re.search(r"\d|garant[ií]a|gratis|reembols|devoluci[oó]n garantizada", e["texto"], re.I), e["texto"]      # ni plazos, ni montos, ni garantías inventadas


# ── La tabla ──────────────────────────────────────────────────────────────────
def test_la_migracion_es_aditiva_y_aisla_por_cuenta_activa():
    sql = re.sub(r"--.*$", "", _leer("migrations", "0053_plantillas_respuesta.sql"), flags=re.M)
    assert not re.search(r"\bDROP\s+(TABLE|COLUMN)\b", sql, re.I) and "CREATE TABLE IF NOT EXISTS plantillas_respuesta" in sql
    assert "ENABLE ROW LEVEL SECURITY" in sql and "current_setting('app.cuenta_actual', true)" in sql             # igual que `ventas` (migración 0010)
    assert "CREATE INDEX IF NOT EXISTS idx_plantillas_respuesta_cuenta" in sql                                    # toda clave foránea lleva índice
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON plantillas_respuesta TO app_backend" in sql


class _Revertir(Exception):
    pass


class _Mantener:
    def __init__(self, con):
        self.con = con

    def __enter__(self):
        return self.con

    def __exit__(self, *a):
        return False


@contextmanager
def _transaccion(monkeypatch):
    """Una conexión con la migración aplicada (dos veces) y todo lo que escriban las rutas en ella; al salir se revierte entera."""
    import db
    try:
        with db.conexion_admin() as con:
            cur = con.cursor()
            cur.execute("SET LOCAL lock_timeout = '5s'")
            for _ in range(2):
                cur.execute(_leer("migrations", "0053_plantillas_respuesta.sql"))
            cur.execute("SELECT usuario_id, id FROM cuentas_meli WHERE activa ORDER BY id LIMIT 1")
            persona = cur.fetchone()
            if not persona:
                pytest.skip("Hace falta una cuenta en la base")
            monkeypatch.setattr(db, "conexion_usuario", lambda *a, **k: _Mantener(con))
            yield con, persona
            raise _Revertir()
    except _Revertir:
        pass


@CON_BASE
def test_crear_listar_editar_y_borrar_una_respuesta(monkeypatch):
    with _transaccion(monkeypatch) as (con, (usuario, cuenta)):
        cur = con.cursor()
        assert pr.listar(cur, cuenta) == []
        stock, error = pr.crear(cur, cuenta, "Hay stock", "{saludo}! Sí, hay {producto}.")
        assert error is None and stock["usos"] == 0
        envios, _ = pr.crear(cur, cuenta, "Envíos", "Hacemos envíos.")
        assert [p["titulo"] for p in pr.listar(cur, cuenta)] == ["Envíos", "Hay stock"]                  # a igual uso, por nombre
        editada, error = pr.actualizar(cur, cuenta, stock["id"], "Hay stock", "Sí, hay. Gracias.")
        assert error is None and editada["texto"] == "Sí, hay. Gracias."
        assert pr.actualizar(cur, cuenta, stock["id"], "x", "{inventada}")[1]                           # una edición también se valida
        assert pr.actualizar(cur, cuenta, 987654321, "x", "y") == (None, "Esa respuesta ya no existe.")
        assert pr.borrar(cur, cuenta, envios["id"]) is True and pr.borrar(cur, cuenta, envios["id"]) is False
        assert [p["titulo"] for p in pr.listar(cur, cuenta)] == ["Hay stock"]


@CON_BASE
def test_hay_un_tope_de_respuestas_por_cuenta(monkeypatch):
    with _transaccion(monkeypatch) as (con, (usuario, cuenta)):
        cur = con.cursor()
        for i in range(pr.MAX_PLANTILLAS):
            assert pr.crear(cur, cuenta, f"R{i}", "texto")[1] is None
        plantilla, error = pr.crear(cur, cuenta, "Una más", "texto")
        assert plantilla is None and str(pr.MAX_PLANTILLAS) in error


@CON_BASE
def test_una_respuesta_de_otra_cuenta_no_se_toca_ni_se_usa(monkeypatch):
    with _transaccion(monkeypatch) as (con, (usuario, cuenta)):
        cur = con.cursor()
        mia, _ = pr.crear(cur, cuenta, "Mía", "texto")
        ajena_id = cuenta + 1_000_000                                                                     # una cuenta que no es la mía
        assert pr.actualizar(cur, ajena_id, mia["id"], "Robada", "texto")[1] == "Esa respuesta ya no existe."
        assert pr.borrar(cur, ajena_id, mia["id"]) is False
        assert pr.usar(cur, ajena_id, mia["id"], "1")[2] == "Esa respuesta ya no existe."
        assert pr.listar(cur, ajena_id) == [] and [p["titulo"] for p in pr.listar(cur, cuenta)] == ["Mía"]


@CON_BASE
def test_usar_una_respuesta_completa_la_pregunta_suma_un_uso_y_no_inventa_el_precio(monkeypatch):
    with _transaccion(monkeypatch) as (con, (usuario, cuenta)):
        cur = con.cursor()
        cur.execute("INSERT INTO productos_padre (cuenta_id, id_meli, titulo, precio) VALUES (%s, 'PRUEBA-PL-1', 'Campera de jean', 54990)", (cuenta,))
        cur.execute("INSERT INTO productos_padre (cuenta_id, id_meli, titulo) VALUES (%s, 'PRUEBA-PL-2', 'Buzo sin precio')", (cuenta,))
        for qid, item in (("9910000000001", "PRUEBA-PL-1"), ("9910000000002", "PRUEBA-PL-2")):
            cur.execute("INSERT INTO preguntas_pendientes (cuenta_id, question_id, item_id, texto_pregunta, estado) VALUES (%s, %s, %s, '¿Hay?', 'pendiente')", (cuenta, qid, item))
        plantilla, _ = pr.crear(cur, cuenta, "Precio", "{saludo}! {producto} cuesta {precio}.")
        ahora = datetime(2026, 10, 22, 15, 0)
        texto, falta, error = pr.usar(cur, cuenta, plantilla["id"], "9910000000001", ahora)
        assert error is None and falta == [] and texto == "Buenas tardes! Campera de jean cuesta $54.990."
        texto, falta, _ = pr.usar(cur, cuenta, plantilla["id"], "9910000000002", ahora)
        assert texto == "Buenas tardes! Buzo sin precio cuesta {precio}." and falta == ["precio"]
        texto, falta, _ = pr.usar(cur, cuenta, plantilla["id"], "0000", ahora)                            # una pregunta que no está: solo el saludo
        assert texto == "Buenas tardes! {producto} cuesta {precio}." and falta == ["precio", "producto"]
        assert pr.listar(cur, cuenta)[0]["usos"] == 3


@CON_BASE
def test_las_rutas_de_punta_a_punta(monkeypatch):
    import app as aplicacion
    with _transaccion(monkeypatch) as (con, (usuario, cuenta)):
        cliente = aplicacion.app.test_client()
        with cliente.session_transaction() as s:
            s["usuario_id"], s["cuenta_id"] = usuario, cuenta
        con.cursor().execute("UPDATE usuarios SET onboarding_completo = true WHERE id = %s", (usuario,))
        con.cursor().execute("UPDATE cuentas_meli SET sincronizacion_inicial_completa = true WHERE id = %s", (cuenta,))
        cab = {"Sec-Fetch-Site": "same-origin"}
        vacio = cliente.get("/api/preguntas/plantillas").get_json()
        assert vacio["plantillas"] == [] and len(vacio["sugeridas"]) == len(pr.SUGERIDAS) and vacio["max_texto"] == 2000
        mala = cliente.post("/api/preguntas/plantillas", json={"titulo": "", "texto": "x"}, headers=cab)
        assert mala.status_code == 400 and "nombre corto" in mala.get_json()["detalle"]
        creada = cliente.post("/api/preguntas/plantillas", json={"titulo": "Hay stock", "texto": "{saludo}! Sí."}, headers=cab).get_json()
        assert creada["ok"] and creada["plantilla"]["titulo"] == "Hay stock"
        lista = cliente.get("/api/preguntas/plantillas").get_json()
        assert [p["titulo"] for p in lista["plantillas"]] == ["Hay stock"] and lista["sugeridas"] == []                  # con una guardada ya no se ofrecen ejemplos
        pid = creada["plantilla"]["id"]
        editada = cliente.post(f"/api/preguntas/plantillas/{pid}", json={"titulo": "Stock", "texto": "Sí, hay."}, headers=cab).get_json()
        assert editada["ok"] and editada["plantilla"]["titulo"] == "Stock"
        usada = cliente.post(f"/api/preguntas/plantillas/{pid}/usar", json={"question_id": "no-existe"}, headers=cab).get_json()
        assert usada["ok"] and usada["texto"] == "Sí, hay." and usada["sin_completar"] == []
        assert cliente.post("/api/preguntas/plantillas/987654321/usar", json={}, headers=cab).status_code == 404
        borrada = cliente.post(f"/api/preguntas/plantillas/{pid}/borrar", headers=cab)
        assert borrada.status_code == 200 and borrada.get_json()["ok"] is True
        assert cliente.post(f"/api/preguntas/plantillas/{pid}/borrar", headers=cab).status_code == 404


def test_las_rutas_piden_sesion_y_son_post_las_que_cambian_algo():
    import app as aplicacion
    reglas = {}
    for r in aplicacion.app.url_map.iter_rules():
        if r.rule.startswith("/api/preguntas/plantillas"):
            reglas.setdefault(r.rule, set()).update(r.methods)                       # la misma dirección puede estar una vez para GET y otra para POST
    assert "GET" in reglas["/api/preguntas/plantillas"] and "POST" in reglas["/api/preguntas/plantillas"]
    for ruta in ("/api/preguntas/plantillas/<int:plantilla_id>", "/api/preguntas/plantillas/<int:plantilla_id>/borrar", "/api/preguntas/plantillas/<int:plantilla_id>/usar"):
        assert reglas[ruta] - {"OPTIONS", "HEAD"} == {"POST"}, ruta                           # nada que escriba se hace con un GET
    sin_sesion = aplicacion.app.test_client().get("/api/preguntas/plantillas")
    assert sin_sesion.status_code in (302, 401)


# ── La pantalla ───────────────────────────────────────────────────────────────
def test_la_pantalla_no_deja_publicar_con_variables_sin_completar_ni_pasada_de_largo():
    html = _leer("templates", "_dia_preguntas.html")
    assert "texto.match(/\\{\\w+\\}/g)" in html and "antes de publicar" in html
    assert f"const LIMITE_RESPUESTA = {pr.MAX_TEXTO};" in html                                   # el mismo límite que el servidor
    assert "if (texto.length > LIMITE_RESPUESTA)" in html


def test_la_pantalla_ofrece_las_respuestas_guardadas_en_cada_pregunta_y_un_panel_para_cuidarlas():
    html = _leer("templates", "_dia_preguntas.html")
    for pieza in ('id="mis-respuestas"', 'id="mr-lista"', 'id="mr-guardar"', 'data-chips', 'data-accion="guardarplantilla"', "/api/preguntas/plantillas/${id}/usar", "/borrar"):
        assert pieza in html, pieza
    for variable in pr.VARIABLES:
        assert f'data-mr-variable="{variable}"' in html, variable                               # un botón para insertar cada variable
    assert "confirmarDecision('¿Reemplazar lo que escribiste?'" in html                          # nunca se pisa lo escrito sin preguntar
    assert "confirmarDecision('¿Borrar esta respuesta guardada?'" in html
    assert not re.search(r"\son(click|input|change)=", html)                                    # la política de scripts estricta: nada de manejadores escritos en el HTML


def test_el_precio_de_la_publicacion_se_ve_al_lado_de_cada_pregunta():
    assert '"precio_texto":' in _leer("app.py") and "p.precio_texto" in _leer("templates", "_dia_preguntas.html")


def test_antes_de_aplicar_la_migracion_preguntas_sigue_andando_sin_respuestas_guardadas(monkeypatch):
    """Justo antes de desplegar la tabla todavía no existe: la lista vuelve vacía (con los ejemplos) en vez de dar un error 500 en toda la pantalla."""
    import app as aplicacion
    from flask import g
    from psycopg.errors import UndefinedTable

    class SinTabla:
        def __enter__(self):
            raise UndefinedTable('relation "plantillas_respuesta" does not exist')

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(pr.db, "conexion_usuario", lambda *a, **k: SinTabla())
    with aplicacion.app.test_request_context("/api/preguntas/plantillas"):
        g.usuario_id, g.cuenta_id = 1, 1
        d = pr.api_listar.__wrapped__().get_json()
    assert d["plantillas"] == [] and len(d["sugeridas"]) == len(pr.SUGERIDAS)
